#!/usr/bin/env python3
"""Bounded current-source Direct/Host Code Mode paired evidence collector.

The caller supplies the live Host driver. This module reuses Agent Loop sample
ownership, fixture oracles, runtime gates and comparison; it is not a model.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts import agent_loop_benchmark as bench, agent_loop_report as report
except ModuleNotFoundError:
    import agent_loop_benchmark as bench
    import agent_loop_report as report

CASES = bench.DEFAULT_CASES
LANES = ("direct", "host_code_mode")
HOST_POLICIES = ("host_single_call", "host_composition_allowed")
EXPERIMENTS = ("direct_vs_host", "host_cell_policy")
MAX_PAIRS = 10
METRICS = (*bench.PAIRED_DELTA_METRICS, "job_convergence.pending_followed_immediately_by_observe_count", "efficiency.job_observe_calls")


def _attest(sample, receipt, case, revision, identity_digest):
    expected = {
        "model_config_digest": identity_digest,
        "base_revision": revision,
        "case_fingerprint": report._case_fingerprint(case),
        "variant": sample["variant"],
        "surface": sample["surface"],
    }
    actual = receipt.get("efficiency_attestation")
    valid = isinstance(actual, dict) and actual == expected
    sample["identity_attestation"] = {"matched": valid, "independently_verified": False}
    if not valid:
        if sample.get("status") == "pass":
            sample["status"] = "fail"
        sample.setdefault("reason_code", "efficiency_attestation_mismatch")
    # Job control remains outer even in nested Code Mode. Missing canonical
    # coverage is unknown, never a zero observation count.
    summary = sample.get("summary")
    if isinstance(summary, dict):
        count = None
        if report._get_path(summary, "availability.canonical_calls.available") is True:
            tools = report._get_path(summary, "tools.outer_by_name")
            if isinstance(tools, dict):
                observed = tools.get("observe_jobs", 0)
                if type(observed) is int and observed >= 0:
                    count = observed
        summary["efficiency"] = {"job_observe_calls": count}
    # Only pinned digest leaves the receipt boundary. Never echo unexpected data.
    if isinstance(sample.get("summary"), dict):
        sample["summary"]["efficiency_identity"] = {
            "model_config_digest": identity_digest if valid else None,
            "attested": valid,
        }
    return sample


def _host_cell_evidence(value, policy, summary):
    """Check caller UI evidence shape/coverage; Audit cannot prove cell grouping."""
    if (not isinstance(value, dict) or set(value) != {"policy", "source", "ui_evidence_sha256",
        "complete_tool_call_coverage", "cells"} or value["policy"] != policy
        or policy not in HOST_POLICIES or value["source"] != "caller_ui_attestation"
        or not report._is_exact_sha256(value["ui_evidence_sha256"])
        or value["complete_tool_call_coverage"] is not True):
        return False
    cells = value["cells"]
    if not isinstance(cells, list) or not 1 <= len(cells) <= 4096:
        return False
    ids, traces = set(), set()
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != {"cell_id_sha256", "tool_trace_ids_sha256"}:
            return False
        identity, calls = cell["cell_id_sha256"], cell["tool_trace_ids_sha256"]
        if not report._is_exact_sha256(identity) or identity in ids:
            return False
        ids.add(identity)
        if (not isinstance(calls, list) or not 1 <= len(calls) <= 4096
            or policy == HOST_POLICIES[0] and len(calls) != 1):
            return False
        for call in calls:
            if not report._is_exact_sha256(call) or call in traces:
                return False
            traces.add(call)
    total = report._get_path(summary, "outer_calls.total")
    return type(total) is int and total == len(traces)


def _attest_host_cells(sample, receipt, policy):
    evidence = receipt.get("host_cell_attestation")
    valid = _host_cell_evidence(evidence, policy, sample.get("summary") or {})
    sample["host_cell_policy"] = policy
    if isinstance(sample.get("summary"), dict):
        sample["summary"]["efficiency_host_policy"] = policy
    sample["host_cell_evidence"] = {"matched": valid, "independently_verified": False,
        "attestation": evidence if valid else None}
    if not valid:
        if sample.get("status") == "pass":
            sample["status"] = "fail"
        sample.setdefault("reason_code", "host_cell_attestation_mismatch")
    return sample


def _metrics(summary):
    return {name: report._get_path(summary or {}, name) for name in METRICS}


def _hotspots(summary):
    """Prioritized evidence candidates, never infer inefficiency from call count."""
    rows = []
    repairs = report._get_path(summary, "repair_turns.by_reason") or {}
    for name in ("invalid_arguments", "tool_selection_repair"):
        value = repairs.get(name)
        if type(value) is int and value > 0:
            rows.append({"priority": 1, "candidate": name, "observed_count": value,
                         "interpretation": "driver-annotated repair; inspect contract evidence before changing guidance"})
    pairs = report._get_path(summary, "host_short_chain.observed_by_tool_pair") or {}
    count = sum(value for name, value in pairs.items()
                if isinstance(name, str) and len(parts := name.split("->")) == 2
                and parts[0] == parts[1] and type(value) is int and value > 0)
    if count:
        rows.append({"priority": 2, "candidate": "same_kind_serial_calls", "observed_count": count,
                     "interpretation": "serial Window proxy; does not prove unnecessary microcalls or same model turn"})
    # Canonical summary has no read-content identity proving repeated reads.
    # Immediate observe is not redundant observe; keep that distinction explicit.
    value = report._get_path(summary, "job_convergence.terminal_failure_followed_by_observe_count")
    if type(value) is int and value > 0:
        rows.append({"priority": 4, "candidate": "observe_after_delivered_failure", "observed_count": value,
                     "interpretation": "explicit observe after delivered failure; inspect necessity before proposing a change"})
    return rows


def _delta_summary(pairs):
    output = bench._paired_delta_summary(pairs)
    # Existing aggregation owns the four core metrics. Add the Job proxy with
    # the same nullable/missing convention; it is not an excess-observe count.
    comparisons = [p["comparison"] for p in pairs if isinstance(p.get("comparison"), dict)
                   and p["comparison"]["throughput_compatibility"]["comparable"]]
    for name in METRICS[len(bench.PAIRED_DELTA_METRICS):]:
        deltas = [m["delta"] for c in comparisons for m in c["metrics"]
                  if m["metric"] == name and m["comparable"] and type(m["delta"]) is int]
        value = report._metric_distribution(deltas, missing=len(comparisons) - len(deltas))
        if not comparisons:
            value["total"] = None
        value["complete"] = bool(comparisons) and value["missing"] == 0
        output["candidate_minus_direct"][name] = value
    return output


def run_efficiency(*, repo: Path, base_revision: str, driver_argv: list[str],
                   identity_digest: str, pairs: int = 3, experimental_nested: bool = False,
                   experiment: str = "direct_vs_host"):
    if experiment not in EXPERIMENTS or experiment == "host_cell_policy" and experimental_nested:
        raise bench.BenchmarkError("invalid or mixed efficiency experiment")
    host_policy = experiment == "host_cell_policy"
    if type(pairs) is not int or not 1 <= pairs <= MAX_PAIRS:
        raise bench.BenchmarkError("pairs must be between 1 and 10")
    if not driver_argv or not report._is_exact_sha256(identity_digest):
        raise bench.BenchmarkError("real driver and exact SHA-256 model/config digest are required")
    if not report._is_exact_git_revision(base_revision):
        raise bench.BenchmarkError("base revision must be an exact 40-hex commit")
    repo = bench._git_root(repo)
    if bench._require_exact_revision(repo, base_revision) != base_revision or bench._head_revision(repo) != base_revision:
        raise bench.BenchmarkError("base revision must equal current checkout HEAD")
    with tempfile.TemporaryDirectory(prefix="webcodex-agent-efficiency-") as owned:
        root = Path(owned)
        for name in ("worktrees", "receipts", "annotations"):
            (root / name).mkdir()
        manifest_path = root / "agent_loop_cases.json"
        manifest_path.write_text(bench._read_manifest_at_revision(repo, base_revision), encoding="utf-8")
        manifest = report.load_case_manifest(manifest_path)
        cases = [bench._case(manifest, name) for name in CASES]
        outputs = []
        for case in cases:
            if case.get("target") != "webcodex_repository":
                raise bench.BenchmarkError("efficiency tasks require repository worktrees")
            groups = []
            # Nested Code Mode gets a separate fresh Direct control, so it
            # cannot contaminate the default Host comparison or its deltas.
            for candidate in ((HOST_POLICIES[1],) if host_policy else
                              (("host_code_mode", "code_mode") if experimental_nested else ("host_code_mode",))):
                paired = []
                for index in range(pairs):
                    lanes = (HOST_POLICIES[0] if host_policy else "direct", candidate)
                    order = lanes if index % 2 == 0 else tuple(reversed(lanes))
                    samples = []
                    for ordinal, lane in enumerate(order):
                        variant = "host_code_mode" if host_policy else lane
                        options = {"host_cell_policy": lane} if host_policy else {}
                        sample = bench._run_sample(repo, root, driver_argv, case, variant=variant,
                            pair_index=index, ordinal=ordinal, base_revision=base_revision, case_manifest=manifest_path, **options)
                        label = f"{case['id']}-p{index + 1}-{ordinal + 1}-{variant}"
                        try:
                            receipt = bench._load_driver_receipt(root / "receipts" / (label + ".json"))
                        except bench.BenchmarkError:
                            receipt = {}
                        _attest(sample, receipt, case, base_revision, identity_digest)
                        if host_policy:
                            _attest_host_cells(sample, receipt, lane)
                        sample["metrics"] = _metrics(sample.get("summary"))
                        sample["hotspot_candidates"] = _hotspots(sample.get("summary") or {})
                        samples.append(sample)
                    by_lane = {s["host_cell_policy" if host_policy else "variant"]: s for s in samples}
                    paired.append({"pair_index": index, "order": list(order), "samples": samples,
                                   "comparison": bench._comparison(by_lane[HOST_POLICIES[0] if host_policy else "direct"], by_lane[candidate])})
                deltas = _delta_summary(paired)
                if host_policy:
                    deltas["candidate_minus_baseline"] = deltas.pop("candidate_minus_direct")
                groups.append({"candidate": candidate, "pairs": paired,
                               "paired_delta_summary": deltas})
            outputs.append({"case_id": case["id"], "groups": groups})
        result = {"schema_version": 1, "kind": "agent_efficiency_benchmark", "base_revision": base_revision,
                  "model_config_digest": identity_digest, "pair_count": pairs,
                  "experimental_nested": experimental_nested, "experiment": experiment, "cases": outputs,
                  "notes": ["identity is pinned caller/driver attestation, not independent model verification",
                            "missing metrics are null; outer calls and immediate observe are proxies",
                            "hotspots are evidence candidates, not production recommendations"]}
        result["strict_passed"] = strict_passed(result, manifest)
        return result


def strict_passed(result, manifest):
    """Recompute evidence and comparison; never trust stored success/counts."""
    try:
        experiment = result.get("experiment", "direct_vs_host")
        if experiment not in EXPERIMENTS or experiment == "host_cell_policy" and result.get("experimental_nested") is not False:
            return False
        host_policy = experiment == "host_cell_policy"
        pairs = result["pair_count"]
        if type(pairs) is not int or not 1 <= pairs <= MAX_PAIRS:
            return False
        identity = result["model_config_digest"]
        revision = result["base_revision"]
        if not report._is_exact_sha256(identity) or not report._is_exact_git_revision(revision):
            return False
        cases = result["cases"]
        if len(cases) != len(CASES) or {c["case_id"] for c in cases} != set(CASES):
            return False
        candidates = {HOST_POLICIES[1]} if host_policy else (
            {"host_code_mode", "code_mode"} if result.get("experimental_nested") is True else {"host_code_mode"})
        for case in cases:
            definition = bench._case(manifest, case["case_id"])
            if len(case["groups"]) != len(candidates) or {g["candidate"] for g in case["groups"]} != candidates:
                return False
            for group in case["groups"]:
                candidate = group["candidate"]
                if len(group["pairs"]) != pairs or {p["pair_index"] for p in group["pairs"]} != set(range(pairs)):
                    return False
                for pair in group["pairs"]:
                    samples = pair["samples"]
                    index = pair["pair_index"]
                    baseline = HOST_POLICIES[0] if host_policy else "direct"
                    lane_key = "host_cell_policy" if host_policy else "variant"
                    lanes = (baseline, candidate)
                    expected_order = list(lanes if index % 2 == 0 else tuple(reversed(lanes)))
                    if (type(index) is not int or pair.get("order") != expected_order
                        or [s.get(lane_key) for s in samples] != expected_order):
                        return False
                    if len(samples) != 2 or {s[lane_key] for s in samples} != set(lanes):
                        return False
                    by_lane = {s[lane_key]: s for s in samples}
                    for sample in samples:
                        summary = sample["summary"]
                        if host_policy:
                            evidence = sample.get("host_cell_evidence", {})
                            if (summary.get("efficiency_host_policy") != sample[lane_key]
                                or sample.get("variant") != "host_code_mode" or evidence.get("matched") is not True
                                or evidence.get("independently_verified") is not False
                                or not _host_cell_evidence(evidence.get("attestation"), sample[lane_key], summary)):
                                return False
                        elif ("host_cell_policy" in sample or "host_cell_evidence" in sample
                              or "efficiency_host_policy" in summary):
                            return False
                        expected_surface = "direct" if sample["variant"] == "direct" else (
                            "host_code_mode" if sample["variant"] == "host_code_mode" else definition["code_mode_surface"])
                        if (sample["case_id"] != case["case_id"] or sample["status"] != "pass"
                            or sample.get("surface") != expected_surface
                            or type(sample.get("driver_exit_code")) is not int or sample.get("driver_exit_code") != 0
                            or sample.get("identity_attestation", {}).get("matched") is not True
                            or summary.get("efficiency_identity") != {"model_config_digest": identity, "attested": True}):
                            return False
                        metadata = summary["benchmark"]
                        expected = {"case_id": case["case_id"], "base_revision": revision,
                            "case_fingerprint": report._case_fingerprint(definition), "variant": sample["variant"], "surface": expected_surface,
                            "validation_required": definition["validation"]["required"]}
                        if any(metadata.get(k) != v for k, v in expected.items()):
                            return False
                        if not bench._runtime_evidence_proven(summary, sample["variant"], expected_surface):
                            return False
                        if case["case_id"] == "long_validation_handoff" and not bench._long_handoff_terminal_proven(summary, sample["variant"]):
                            return False
                        if case["case_id"] == "guarded_multi_file_edit" and not bench._guarded_multi_file_contract_proven(summary, sample["variant"]):
                            return False
                        oracle = sample["fixture_oracle"]
                        if ((definition.get("correctness") or {}).get("fixture_oracle") is not None
                            and (oracle.get("available") is not True or oracle.get("passed") is not True)):
                            return False
                        if oracle.get("available") is True and oracle.get("passed") is not True:
                            return False
                    comparison = bench._comparison(by_lane[HOST_POLICIES[0] if host_policy else "direct"], by_lane[candidate])
                    if not comparison or comparison["throughput_compatibility"]["comparable"] is not True:
                        return False
        return True
    except (KeyError, TypeError, AttributeError, bench.BenchmarkError, report.ReportError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--driver-command", required=True)
    parser.add_argument("--model-config-digest", required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--experiment", choices=EXPERIMENTS, default="direct_vs_host")
    parser.add_argument("--experimental-nested", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_efficiency(repo=args.repo, base_revision=args.base_revision,
            driver_argv=shlex.split(args.driver_command), identity_digest=args.model_config_digest,
            pairs=args.pairs, experimental_nested=args.experimental_nested, experiment=args.experiment)
        report._write_json(result, args.output)
        return 1 if args.strict and not result["strict_passed"] else 0
    except (ValueError, OSError):
        print("agent efficiency benchmark failed; check pinned inputs and driver contract", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
