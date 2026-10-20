"""Contract tests only: fabricated fixtures are never real model evidence."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import agent_efficiency_benchmark as efficiency
from scripts import agent_loop_report as report
from scripts.tests import test_agent_loop_report as report_fixtures

REV = "a" * 40
IDENTITY = "b" * 64


def matrix():
    manifest = report.load_case_manifest(report.DEFAULT_CASE_MANIFEST)
    cases = []
    for case_id in efficiency.CASES:
        definition = report._case_by_id(manifest, case_id)
        pairs = []
        for index in range(3):
            samples = []
            for lane in efficiency.LANES:
                surface = lane
                summary = {"schema_version": 1, "kind": "agent_loop_summary",
                    "benchmark": {"case_id": case_id, "base_revision": REV,
                        "case_fingerprint": report._case_fingerprint(definition),
                        "variant": lane, "surface": surface,
                        "validation_required": definition["validation"]["required"]},
                    "correctness": {"task_verdict": "pass", "validation_verdict": "pass"},
                    "efficiency_identity": {"model_config_digest": IDENTITY, "attested": True}}
                samples.append({"case_id": case_id, "variant": lane, "surface": surface,
                    "status": "pass", "driver_exit_code": 0, "summary": summary,
                    "identity_attestation": {"matched": True, "independently_verified": False},
                    "fixture_oracle": {"available": True, "passed": True}})
            order = list(efficiency.LANES if index % 2 == 0 else reversed(efficiency.LANES))
            samples.sort(key=lambda sample: order.index(sample["variant"]))
            pairs.append({"pair_index": index, "order": order, "samples": samples,
                          "comparison": {"throughput_compatibility": {"comparable": True}}})
        cases.append({"case_id": case_id, "groups": [{"candidate": "host_code_mode", "pairs": pairs}]})
    return {"pair_count": 3, "base_revision": REV, "model_config_digest": IDENTITY,
            "cases": cases, "strict_passed": True, "sample_count": 18}, manifest


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.result, self.manifest = matrix()
        self.patches = [patch.object(efficiency.bench, name, return_value=True) for name in
            ("_runtime_evidence_proven", "_long_handoff_terminal_proven", "_guarded_multi_file_contract_proven")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def sample(self):
        return self.result["cases"][0]["groups"][0]["pairs"][0]["samples"][0]

    def strict(self):
        return efficiency.strict_passed(self.result, self.manifest)

    def test_complete_contract_matrix(self):
        self.assertTrue(self.strict())

    def test_missing_sample_ignores_misleading_counts(self):
        self.result["cases"][0]["groups"][0]["pairs"][0]["samples"].pop()
        self.assertFalse(self.strict())

    def test_missing_pair(self):
        self.result["cases"][0]["groups"][0]["pairs"].pop()
        self.assertFalse(self.strict())

    def test_missing_case(self):
        self.result["cases"].pop()
        self.assertFalse(self.strict())

    def test_altered_identity(self):
        self.sample()["summary"]["efficiency_identity"]["model_config_digest"] = "c" * 64
        self.assertFalse(self.strict())

    def test_altered_case_or_base_or_lane(self):
        for key, value in (("base_revision", "d" * 40), ("case_fingerprint", "e" * 64), ("variant", "code_mode")):
            with self.subTest(key=key):
                old = self.sample()["summary"]["benchmark"][key]
                self.sample()["summary"]["benchmark"][key] = value
                self.assertFalse(self.strict())
                self.sample()["summary"]["benchmark"][key] = old

    def test_nonpass_kept(self):
        for status in ("fail", "partial", "unsupported"):
            self.sample()["status"] = status
            self.assertFalse(self.strict())

    def test_driver_exit_requires_an_actual_integer_zero(self):
        for value in (False, True, "0", None):
            with self.subTest(value=value):
                self.sample()["driver_exit_code"] = value
                self.assertFalse(self.strict())

    def test_reported_pass_cannot_hide_failed_correctness(self):
        self.sample()["summary"]["correctness"]["task_verdict"] = "fail"
        self.assertFalse(self.strict())

    def test_stored_comparison_cannot_hide_noncomparable_report(self):
        self.sample()["summary"]["correctness"]["validation_verdict"] = "unavailable"
        self.assertFalse(self.strict())

    def test_counts_cannot_hide_runtime_failure(self):
        with patch.object(efficiency.bench, "_runtime_evidence_proven", return_value=False):
            self.assertFalse(self.strict())

    def test_oracle_required_for_guarded_edit(self):
        sample = self.result["cases"][1]["groups"][0]["pairs"][0]["samples"][0]
        sample["fixture_oracle"] = {"available": False}
        self.assertFalse(self.strict())

    def test_missing_metrics_are_null(self):
        self.assertTrue(all(v is None for v in efficiency._metrics({}).values()))
        summary = efficiency._delta_summary([])
        self.assertTrue(all(v["total"] is None for v in summary["candidate_minus_direct"].values()))

    def test_no_hotspots_from_counts_alone(self):
        self.assertEqual(efficiency._hotspots({"outer_calls": {"total": 100},
            "tools": {"outer_by_name": {"read_file": 20, "observe_job": 20}}}), [])

    def test_hotspots_state_proxy_limits(self):
        rows = efficiency._hotspots({"repair_turns": {"by_reason": {"invalid_arguments": 2}},
            "host_short_chain": {"observed_by_tool_pair": {"read_file->read_file": 3}}})
        self.assertEqual([r["priority"] for r in rows], [1, 2])
        self.assertIn("does not prove", rows[1]["interpretation"])

    def test_attestation_requires_exact_pins_and_does_not_echo_private_data(self):
        definition = report._case_by_id(self.manifest, efficiency.CASES[0])
        sample = copy.deepcopy(self.sample())
        efficiency._attest(sample, {"efficiency_attestation": {"model_config_digest": "secret-private-value"},
            "private_reasoning": "private payload"}, definition, REV, IDENTITY)
        serialized = json.dumps(sample)
        self.assertNotIn("secret-private-value", serialized)
        self.assertNotIn("private payload", serialized)
        self.assertEqual(sample["status"], "fail")
        self.assertIsNone(sample["summary"]["efficiency_identity"]["model_config_digest"])

    def test_identity_failure_retains_unsupported_status(self):
        definition = report._case_by_id(self.manifest, efficiency.CASES[0])
        self.sample()["status"] = "unsupported"
        self.sample()["reason_code"] = "driver_platform_unsupported"
        efficiency._attest(self.sample(), {}, definition, REV, IDENTITY)
        self.assertEqual(self.sample()["status"], "unsupported")
        self.assertEqual(self.sample()["reason_code"], "driver_platform_unsupported")
        self.assertFalse(self.strict())

    def test_observe_metric_requires_coverage(self):
        definition = report._case_by_id(self.manifest, efficiency.CASES[0])
        sample = self.sample()
        efficiency._attest(sample, {}, definition, REV, IDENTITY)
        self.assertIsNone(sample["summary"]["efficiency"]["job_observe_calls"])
        sample["summary"]["availability"] = {"canonical_calls": {"available": True}}
        sample["summary"]["tools"] = {"outer_by_name": {"observe_jobs": 2}}
        efficiency._attest(sample, {}, definition, REV, IDENTITY)
        self.assertEqual(sample["summary"]["efficiency"]["job_observe_calls"], 2)

    def test_missing_attestation(self):
        definition = report._case_by_id(self.manifest, efficiency.CASES[0])
        efficiency._attest(self.sample(), {}, definition, REV, IDENTITY)
        self.assertFalse(self.strict())

    def test_compare_identity_missing_or_mismatched(self):
        left, right = self.result["cases"][0]["groups"][0]["pairs"][0]["samples"]
        right["summary"].pop("efficiency_identity")
        result = report.compare_reports(left["summary"], right["summary"])
        self.assertFalse(result["throughput_compatibility"]["comparable"])

    def test_changed_required_validation_cannot_weaken_gate(self):
        sample = self.result["cases"][2]["groups"][0]["pairs"][0]["samples"][0]
        sample["summary"]["benchmark"]["validation_required"] = False
        sample["summary"]["correctness"]["validation_verdict"] = "not_required"
        self.assertFalse(self.strict())

    def test_wrong_alternating_order(self):
        self.result["cases"][0]["groups"][0]["pairs"][0]["order"] = ["host_code_mode", "direct"]
        self.assertFalse(self.strict())

    def test_orchestration_reuses_sample_and_cleans_temporary_root(self):
        roots, calls = [], []
        def fake_sample(repo, root, driver, case, **options):
            # Fabricated collector fixture, not a live-model driver.
            roots.append(root)
            calls.append((case["id"], options["pair_index"], options["variant"]))
            lane = options["variant"]
            template = next(c for c in self.result["cases"] if c["case_id"] == case["id"])
            sample = copy.deepcopy(next(s for s in template["groups"][0]["pairs"][0]["samples"] if s["variant"] == lane))
            receipt = {"status": "pass", "efficiency_attestation": {
                "model_config_digest": IDENTITY, "base_revision": REV,
                "case_fingerprint": report._case_fingerprint(case), "variant": lane, "surface": lane}}
            label = f"{case['id']}-p{options['pair_index'] + 1}-{options['ordinal'] + 1}-{lane}.json"
            (root / "receipts" / label).write_text(json.dumps(receipt))
            return sample
        with patch.object(efficiency.bench, "_git_root", return_value=Path.cwd()), \
             patch.object(efficiency.bench, "_require_exact_revision", return_value=REV), \
             patch.object(efficiency.bench, "_head_revision", return_value=REV), \
             patch.object(efficiency.bench, "_read_manifest_at_revision", return_value=json.dumps(self.manifest)), \
             patch.object(efficiency.bench, "_run_sample", side_effect=fake_sample):
            result = efficiency.run_efficiency(repo=Path.cwd(), base_revision=REV,
                driver_argv=["real-driver-placeholder"], identity_digest=IDENTITY)
        self.assertTrue(result["strict_passed"])
        self.assertEqual(len(calls), 18)
        self.assertEqual([c[2] for c in calls[:6]],
            ["direct", "host_code_mode", "host_code_mode", "direct", "direct", "host_code_mode"])
        self.assertTrue(all(not root.exists() for root in roots))

    def test_setup_failure_cleans_temporary_root(self):
        roots = []
        original = efficiency.tempfile.TemporaryDirectory
        def owned(*args, **kwargs):
            resource = original(*args, **kwargs)
            roots.append(Path(resource.name))
            return resource
        with patch.object(efficiency.bench, "_git_root", return_value=Path.cwd()), \
             patch.object(efficiency.bench, "_require_exact_revision", return_value=REV), \
             patch.object(efficiency.bench, "_head_revision", return_value=REV), \
             patch.object(efficiency.bench, "_read_manifest_at_revision", side_effect=efficiency.bench.BenchmarkError("fixture failure")), \
             patch.object(efficiency.tempfile, "TemporaryDirectory", side_effect=owned):
            with self.assertRaises(efficiency.bench.BenchmarkError):
                efficiency.run_efficiency(repo=Path.cwd(), base_revision=REV,
                    driver_argv=["driver"], identity_digest=IDENTITY)
        self.assertEqual(len(roots), 1)
        self.assertFalse(roots[0].exists())

    def test_input_bounds_before_worktree_setup(self):
        for count in (0, 11, True):
            with self.assertRaises(efficiency.bench.BenchmarkError):
                efficiency.run_efficiency(repo=Path.cwd(), base_revision=REV,
                    driver_argv=["driver"], identity_digest=IDENTITY, pairs=count)
        with self.assertRaises(efficiency.bench.BenchmarkError):
            efficiency.run_efficiency(repo=Path.cwd(), base_revision="HEAD",
                driver_argv=["driver"], identity_digest=IDENTITY)


def cell_evidence(policy, count=2):
    cells = [{"cell_id_sha256": f"{index + 100:064x}",
              "tool_trace_ids_sha256": [f"{index + 1:064x}"]} for index in range(count)]
    return {"policy": policy, "source": "caller_ui_attestation", "ui_evidence_sha256": "e" * 64,
            "complete_tool_call_coverage": True, "cells": cells}


def host_matrix():
    result, manifest = matrix()
    result.update(experiment="host_cell_policy", experimental_nested=False)
    for case in result["cases"]:
        case["groups"][0]["candidate"] = efficiency.HOST_POLICIES[1]
        for pair in case["groups"][0]["pairs"]:
            order = list(efficiency.HOST_POLICIES if pair["pair_index"] % 2 == 0 else reversed(efficiency.HOST_POLICIES))
            pair["order"] = order
            for sample, policy in zip(pair["samples"], order):
                sample.update(variant="host_code_mode", surface="host_code_mode")
                sample["summary"]["benchmark"].update(variant="host_code_mode", surface="host_code_mode")
                sample["summary"]["outer_calls"] = {"total": 2}
                efficiency._attest_host_cells(sample, {"host_cell_attestation": cell_evidence(policy)}, policy)
    return result, manifest


class HostPolicyTests(unittest.TestCase):
    def setUp(self):
        self.result, self.manifest = host_matrix()
        for name in ("_runtime_evidence_proven", "_long_handoff_terminal_proven", "_guarded_multi_file_contract_proven"):
            p = patch.object(efficiency.bench, name, return_value=True)
            p.start(); self.addCleanup(p.stop)

    def sample(self):
        return self.result["cases"][0]["groups"][0]["pairs"][0]["samples"][0]

    def strict(self):
        return efficiency.strict_passed(self.result, self.manifest)

    def test_complete_host_matrix_and_explicit_host_host_comparison(self):
        self.assertTrue(self.strict())
        left, right = self.result["cases"][0]["groups"][0]["pairs"][0]["samples"]
        comparison = efficiency.bench._comparison(left, right)
        self.assertTrue(comparison["throughput_compatibility"]["comparable"])
        self.assertEqual(comparison["baseline"]["variant"], "host_code_mode")
        self.assertEqual(comparison["candidate"]["variant"], "host_code_mode")

    def test_original_matrix_cannot_be_relabelled_as_host_policy(self):
        result, manifest = matrix(); result["experiment"] = "host_cell_policy"
        self.assertFalse(efficiency.strict_passed(result, manifest))
        self.result["experiment"] = "direct_vs_host"
        self.assertFalse(self.strict())

    def test_direct_variant_or_surface_cannot_enter_host_matrix(self):
        for key in ("variant", "surface"):
            old = self.sample()[key]; self.sample()[key] = "direct"
            self.assertFalse(self.strict()); self.sample()[key] = old

    def test_unknown_experiment_nested_mixture_or_missing_matrix_rejected(self):
        for key, value in (("experiment", "unknown"), ("experimental_nested", True), ("pair_count", 2)):
            old = self.result[key]; self.result[key] = value
            self.assertFalse(self.strict()); self.result[key] = old
        self.result["cases"][0]["groups"][0]["pairs"][0]["samples"].pop()
        self.assertFalse(self.strict())

    def test_missing_changed_or_independently_verified_ui_evidence_fails(self):
        evidence = self.sample()["host_cell_evidence"]
        for key, value in (("matched", False), ("independently_verified", True), ("attestation", None)):
            old = evidence[key]; evidence[key] = value
            self.assertFalse(self.strict()); evidence[key] = old
        evidence["attestation"]["policy"] = efficiency.HOST_POLICIES[1]
        self.assertFalse(self.strict())

    def test_single_call_cell_with_two_calls_rejected_even_with_correct_total(self):
        evidence = self.sample()["host_cell_evidence"]["attestation"]
        evidence["cells"][0]["tool_trace_ids_sha256"] += evidence["cells"].pop()["tool_trace_ids_sha256"]
        self.assertFalse(self.strict())

    def test_composition_allows_multicall_but_does_not_require_it(self):
        value = cell_evidence(efficiency.HOST_POLICIES[1])
        self.assertTrue(efficiency._host_cell_evidence(value, efficiency.HOST_POLICIES[1], {"outer_calls": {"total": 2}}))
        value["cells"][0]["tool_trace_ids_sha256"] += value["cells"].pop()["tool_trace_ids_sha256"]
        self.assertTrue(efficiency._host_cell_evidence(value, efficiency.HOST_POLICIES[1], {"outer_calls": {"total": 2}}))

    def test_duplicate_missing_or_extra_call_hashes_fail_closed(self):
        for change in ("duplicate_trace", "duplicate_cell", "missing", "incomplete", "extra"):
            value = cell_evidence(efficiency.HOST_POLICIES[0])
            if change == "duplicate_trace": value["cells"][1]["tool_trace_ids_sha256"] = value["cells"][0]["tool_trace_ids_sha256"]
            elif change == "duplicate_cell": value["cells"][1]["cell_id_sha256"] = value["cells"][0]["cell_id_sha256"]
            elif change == "missing": value["cells"].pop()
            elif change == "incomplete": value["complete_tool_call_coverage"] = False
            else: value["private_payload"] = "must not echo"
            self.assertFalse(efficiency._host_cell_evidence(value, efficiency.HOST_POLICIES[0], {"outer_calls": {"total": 2}}))

    def test_invalid_cell_receipt_does_not_echo_private_payload(self):
        sample = self.sample()
        efficiency._attest_host_cells(sample, {"host_cell_attestation": {"private": "secret argument"}}, efficiency.HOST_POLICIES[0])
        self.assertEqual(sample["status"], "fail")
        self.assertNotIn("secret argument", json.dumps(sample))

    def test_comparison_requires_both_host_policies_and_identity(self):
        left, right = self.result["cases"][0]["groups"][0]["pairs"][0]["samples"]
        right["summary"].pop("efficiency_host_policy")
        self.assertFalse(efficiency.bench._comparison(left, right)["throughput_compatibility"]["comparable"])

    def test_host_orchestration_reuses_collector_and_real_host_identity(self):
        calls, roots = [], []
        def fake_sample(repo, root, driver, case, **options):
            roots.append(root); calls.append(options)
            policy = options["host_cell_policy"]
            sample = copy.deepcopy(self.sample()); sample["case_id"] = case["id"]
            sample["summary"]["benchmark"].update(case_id=case["id"], case_fingerprint=report._case_fingerprint(case),
                validation_required=case["validation"]["required"])
            receipt = {"status": "pass", "efficiency_attestation": {"model_config_digest": IDENTITY, "base_revision": REV,
                "case_fingerprint": report._case_fingerprint(case), "variant": "host_code_mode", "surface": "host_code_mode"},
                "host_cell_attestation": cell_evidence(policy)}
            label = f"{case['id']}-p{options['pair_index'] + 1}-{options['ordinal'] + 1}-host_code_mode.json"
            (root / "receipts" / label).write_text(json.dumps(receipt))
            return sample
        with patch.object(efficiency.bench, "_git_root", return_value=Path.cwd()), \
             patch.object(efficiency.bench, "_require_exact_revision", return_value=REV), \
             patch.object(efficiency.bench, "_head_revision", return_value=REV), \
             patch.object(efficiency.bench, "_read_manifest_at_revision", return_value=json.dumps(self.manifest)), \
             patch.object(efficiency.bench, "_run_sample", side_effect=fake_sample):
            result = efficiency.run_efficiency(repo=Path.cwd(), base_revision=REV, driver_argv=["fixture-driver"],
                identity_digest=IDENTITY, experiment="host_cell_policy")
        self.assertTrue(result["strict_passed"])
        self.assertEqual(len(calls), 18)
        self.assertTrue(all(c["variant"] == "host_code_mode" for c in calls))
        self.assertEqual([c["host_cell_policy"] for c in calls[:4]], list(efficiency.HOST_POLICIES) + list(reversed(efficiency.HOST_POLICIES)))
        self.assertIn("candidate_minus_baseline", result["cases"][0]["groups"][0]["paired_delta_summary"])
        self.assertNotIn("candidate_minus_direct", result["cases"][0]["groups"][0]["paired_delta_summary"])
        self.assertTrue(all(not root.exists() for root in roots))


class EfficiencyReportIntegrationTests(unittest.TestCase):
    """Exercise persisted audit -> canonical report -> efficiency consumers."""
    def setUp(self):
        self.fixture = report_fixtures.AgentLoopReportTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def add_job_event(self, trace, previous=None, kind=None, failure=None):
        row = report_fixtures.JobConvergenceTests.row(trace, previous, kind,
            failure=failure, terminal=2000 if kind in ("passive_terminal", "explicit_observe") else None)
        self.fixture.insert_event(str(trace), trace_id=str(trace),
            previous_trace_id=str(previous) if previous else None,
            started=trace * 1000, handed=trace * 1000 + 100,
            transition="serial" if previous else "unavailable",
            tool="observe_jobs" if kind == "explicit_observe" else "run_process",
            job_convergence=row["summary"]["model_ergonomics"]["job_convergence"])

    def test_host_cell_coverage_and_comparison_use_actual_audit_summaries(self):
        self.fixture.insert_event("read-one", tool="read_files", started=100, handed=120)
        self.fixture.insert_event("read-two", tool="read_files", started=150, handed=170, transition="serial")
        summaries = [self.fixture.summarize(variant="host_code_mode", surface="host_code_mode",
            case_manifest=report.DEFAULT_CASE_MANIFEST, case_id="readonly_review", base_revision=REV) for _ in range(2)]
        for summary, policy in zip(summaries, efficiency.HOST_POLICIES):
            summary["efficiency_identity"] = {"model_config_digest": IDENTITY, "attested": True}
            summary["efficiency_host_policy"] = policy
            evidence = cell_evidence(policy)
            self.assertTrue(efficiency._host_cell_evidence(evidence, policy, summary))
            evidence["cells"].pop()
            self.assertFalse(efficiency._host_cell_evidence(evidence, policy, summary))
        comparison = report.compare_reports(*summaries)
        self.assertTrue(comparison["pair_compatibility"]["comparable"])
        summaries[0]["benchmark"]["variant"] = "direct"
        self.assertFalse(report.compare_reports(*summaries)["pair_compatibility"]["comparable"])

    def test_immediate_observe_metric_uses_canonical_report_path(self):
        self.add_job_event(1, kind="pending_handoff")
        self.add_job_event(2, 1, "explicit_observe")
        summary = self.fixture.summarize()
        path = "job_convergence.pending_followed_immediately_by_observe_count"
        self.assertEqual(efficiency._metrics(summary)[path], 1)
        comparison = report.compare_reports(summary, self.fixture.summarize(variant="host_code_mode"))
        metric = next(item for item in comparison["metrics"] if item["metric"] == path)
        self.assertTrue(metric["comparable"])
        self.assertEqual((metric["baseline"], metric["candidate"], metric["delta"]), (1, 1, 0))

    def test_passive_terminal_without_observe_is_not_an_observe_candidate(self):
        self.add_job_event(1, kind="pending_handoff")
        self.add_job_event(2, 1, "passive_terminal", failure=True)
        self.add_job_event(3, 2)
        summary = self.fixture.summarize()
        self.assertEqual(summary["job_convergence"]["passive_terminal_before_explicit_observe_count"], 1)
        self.assertEqual(summary["job_convergence"]["terminal_failure_followed_by_observe_count"], 0)
        self.assertFalse(any(row["candidate"] == "observe_after_delivered_failure"
                             for row in efficiency._hotspots(summary)))

    def test_delivered_failure_then_observe_is_only_an_inspection_candidate(self):
        self.add_job_event(1, kind="pending_handoff")
        self.add_job_event(2, 1, "passive_terminal", failure=True)
        self.add_job_event(3, 2, "explicit_observe")
        summary = self.fixture.summarize()
        rows = [row for row in efficiency._hotspots(summary)
                if row["candidate"] == "observe_after_delivered_failure"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["observed_count"], 1)
        self.assertIn("inspect necessity", rows[0]["interpretation"])
        self.assertNotIn("excess", rows[0]["interpretation"])

    def test_same_kind_hotspot_uses_actual_report_tool_pair_field(self):
        self.fixture.insert_event("read-one", tool="read_files", started=100, handed=120)
        self.fixture.insert_event("read-two", tool="read_files", started=150, handed=170, transition="serial")
        summary = self.fixture.summarize(variant="host_code_mode")
        self.assertEqual(summary["host_short_chain"]["observed_by_tool_pair"], {"read_files->read_files": 1})
        rows = efficiency._hotspots(summary)
        self.assertEqual(rows[0]["candidate"], "same_kind_serial_calls")
        self.assertEqual(rows[0]["observed_count"], 1)
        self.assertIn("does not prove", rows[0]["interpretation"])


if __name__ == "__main__":
    unittest.main()
