from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import agent_loop_benchmark as benchmark
from scripts import agent_loop_report as report
from scripts.tests.test_agent_loop_report import code_mode_composition


class ToolSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = report.load_case_manifest(report.DEFAULT_CASE_MANIFEST)
        self.case = report._case_by_id(self.manifest, "selection_single_read")

    def event(self, tool: str, facts: dict | None = None, *, version: int = 13) -> dict:
        telemetry = {"schema_version": version, "tool_name": tool, "success": True}
        if facts is not None:
            telemetry["native_batch"] = facts
        return {"event_id": f"event-{tool}", "action_name": "toolsCall", "operation": tool, "summary": {"model_ergonomics": telemetry}}

    def test_selection_cases_are_separate_and_do_not_prescribe_tool_lanes(self) -> None:
        cases = [c for c in self.manifest["cases"] if c.get("experiment") == "tool_selection"]
        repository_cases = [c for c in cases if c.get("target") == "webcodex_repository"]
        fixture_cases = [c for c in cases if c.get("target") == "knowledge_skill_disposable_fixture"]
        self.assertEqual({case["id"] for case in repository_cases}, {
            "selection_single_read", "selection_batch_read",
            "selection_cross_tool_review", "selection_compound_source_context",
            "selection_failed_test_recovery", "selection_session_recovery",
        })
        self.assertEqual({case["id"] for case in fixture_cases}, {
            "knowledge_identifier", "knowledge_procedure", "knowledge_paraphrase",
            "knowledge_source_update", "knowledge_skill_read", "knowledge_skill_update",
        })
        self.assertEqual(len(cases), len(repository_cases) + len(fixture_cases))
        self.assertEqual(benchmark.DEFAULT_SELECTION_CASES, (
            "selection_single_read", "selection_batch_read",
            "selection_cross_tool_review", "selection_compound_source_context",
        ))
        self.assertTrue(set(benchmark.DEFAULT_SELECTION_CASES).issubset(
            {case["id"] for case in repository_cases}))
        for case in cases:
            self.assertNotIn("code_mode_surface", case)
        invalid = copy.deepcopy(self.manifest)
        invalid["cases"][-1]["code_mode_surface"] = "read_only"
        with self.assertRaisesRegex(report.ReportError, "must not prescribe"):
            report.validate_case_manifest(invalid)

    def test_metadata_prevents_cross_experiment_relabeling(self) -> None:
        kwargs = dict(case_manifest=None, base_revision="a" * 40)
        actual = report._benchmark_metadata(case_id=self.case["id"], variant="tool_selection", **kwargs)
        self.assertEqual(actual["surface"], "tool_selection")
        self.assertEqual(actual["experiment"], "tool_selection")
        for case_id, variant in ((self.case["id"], "direct"), ("readonly_review", "tool_selection")):
            with self.assertRaisesRegex(report.ReportError, "cannot be mixed"):
                report._benchmark_metadata(case_id=case_id, variant=variant, **kwargs)

    def test_selection_may_mix_direct_discovery_and_code_mode_without_weakening_original_gate(self) -> None:
        events = [self.event("work_on_project"), self.event("read_tool_manifest"), self.event("read_files"), self.event("execute_code_mode")]
        events[-1]["summary"]["model_ergonomics"]["code_mode_composition"] = code_mode_composition()
        # Composition is carried alongside ModelErgonomics in canonical rows.
        events[-1]["summary"]["code_mode_composition"] = code_mode_composition()
        summary = report._summarize_audit(events, "tool_selection")
        self.assertTrue(benchmark._runtime_evidence_proven(summary, "tool_selection", "tool_selection"))
        self.assertFalse(benchmark._runtime_evidence_proven(summary, "code_mode", "read_only"))
        events[-1]["summary"].pop("code_mode_composition")
        events[-1]["summary"]["model_ergonomics"].pop("code_mode_composition")
        self.assertFalse(benchmark._runtime_evidence_proven(report._summarize_audit(events, "tool_selection"), "tool_selection", "tool_selection"))

    def test_oracle_cannot_invent_answer_correctness_for_selection(self) -> None:
        annotation = benchmark._annotation(self.case, variant="tool_selection", surface="tool_selection", base_revision="a" * 40, receipt={}, oracle={"available": True, "passed": True})
        self.assertEqual(annotation["correctness"]["task_verdict"], "unavailable")

    def test_selection_requires_valid_canonical_identity_and_outcome(self) -> None:
        valid = self.event("read_files")
        for telemetry in (None, {}, {"schema_version": 13, "tool_name": "search_project_texts", "success": True}, {"schema_version": True, "tool_name": "read_files", "success": True}, {"schema_version": 13, "tool_name": "read_files", "success": "true"}):
            with self.subTest(telemetry=telemetry):
                event = copy.deepcopy(valid)
                event["summary"]["model_ergonomics"] = telemetry
                summary = report._summarize_audit([event], "tool_selection")
                self.assertFalse(benchmark._runtime_evidence_proven(summary, "tool_selection", "tool_selection"))
                self.assertIsNone(summary["canonical_calls"]["total"])
                self.assertFalse(summary["availability"]["native_batch"]["available"])
        # Old valid identities can prove tool choice without claiming new counts.
        summary = report._summarize_audit([self.event("read_files", version=12)], "tool_selection")
        self.assertTrue(benchmark._runtime_evidence_proven(summary, "tool_selection", "tool_selection"))
        self.assertFalse(summary["availability"]["native_batch"]["available"])

    def test_native_batch_counts_actual_admitted_requests_not_completed_items(self) -> None:
        events = [self.event("read_files", {"kind": "read_files", "requested_items": n}) for n in (1, 2, 8)]
        events[-1]["summary"]["model_ergonomics"]["success"] = False
        facts, availability = report._summarize_native_batch(events, action_audit_available=True)
        self.assertTrue(availability["available"])
        self.assertEqual(facts["read_files"]["multi_item_calls"], 2)
        self.assertEqual(facts["read_files"]["requested_cardinality"]["total"], 11)
        self.assertNotIn("completed", json.dumps(facts))

    def test_native_batch_rejects_bad_counts_and_preserves_missing(self) -> None:
        for value in (0, 9, -1, True, 1.0, "2", None):
            with self.subTest(value=value):
                event = self.event("read_files", {"kind": "read_files", "requested_items": value})
                facts, available = report._summarize_native_batch([event], action_audit_available=True)
                self.assertFalse(available["available"])
                self.assertIsNone(facts["read_files"]["multi_item_calls"])
                self.assertIsNone(facts["read_files"]["requested_cardinality"]["total"])
        for facts in (None, {"kind": "search_project_texts", "requested_queries": 2}, {"kind": "read_files", "requested_items": 2, "private": "x"}):
            self.assertFalse(report._summarize_native_batch([self.event("read_files", facts)], action_audit_available=True)[1]["available"])
        self.assertFalse(report._summarize_native_batch([self.event("read_files", {"kind": "read_files", "requested_items": 2}, version=12)], action_audit_available=True)[1]["available"])

    def test_batch_coverage_unknown_for_unidentified_gateway_or_trace_only(self) -> None:
        unknown = {"operation": "call_runtime_tool", "summary": {}}
        facts, availability = report._summarize_native_batch([unknown], action_audit_available=True)
        self.assertFalse(availability["available"])
        self.assertIsNone(facts["read_files"]["outer_calls"])
        facts, availability = report._summarize_native_batch([], action_audit_available=False)
        self.assertFalse(availability["available"])
        self.assertIsNone(facts["read_files"]["multi_item_calls"])

    def test_selection_reports_compare_only_with_matching_experiment_and_correctness(self) -> None:
        metadata = report._benchmark_metadata(case_manifest=None, case_id=self.case["id"], variant="tool_selection", base_revision="a" * 40)
        left = {"schema_version": 1, "kind": "agent_loop_summary", "benchmark": metadata, "correctness": {"task_verdict": "pass", "validation_verdict": "not_required"}}
        left["native_batch"] = {"read_files": {"outer_calls": 2, "multi_item_calls": 1, "requested_cardinality": {"total": 3}}}
        right = copy.deepcopy(left)
        right["native_batch"]["read_files"]["requested_cardinality"]["total"] = 4
        self.assertTrue(report.compare_reports(left, right)["throughput_compatibility"]["comparable"])
        metrics = {item["metric"]: item for item in report.compare_reports(left, right)["metrics"]}
        self.assertEqual(metrics["native_batch.read_files.requested_cardinality.total"]["delta"], 1)
        self.assertIsNone(metrics["native_batch.search_project_texts.requested_cardinality.total"]["delta"])
        right["correctness"]["task_verdict"] = "unavailable"
        self.assertFalse(report.compare_reports(left, right)["throughput_compatibility"]["comparable"])
        right["benchmark"]["experiment"] = "forced_lanes"
        self.assertFalse(report.compare_reports(left, right)["pair_compatibility"]["comparable"])

    def test_selection_runner_repeats_unrestricted_samples_and_retains_failure(self) -> None:
        fake_sample = {"variant": "tool_selection", "status": "partial", "summary": None}
        with (
            mock.patch.object(benchmark, "_git_root", side_effect=lambda p: p),
            mock.patch.object(benchmark, "_require_exact_revision", return_value="a" * 40),
            mock.patch.object(benchmark, "_head_revision", return_value="a" * 40),
            mock.patch.object(benchmark, "_read_manifest_at_revision", return_value=json.dumps(self.manifest)),
            mock.patch.object(benchmark, "_run_sample", return_value=fake_sample) as sample,
        ):
            result = benchmark.run_selection_benchmark(repo=Path("."), base_revision="a" * 40, driver_argv=["host-driver"], case_ids=[self.case["id"]], samples=2)
            self.assertEqual(result["status_counts"]["partial"], 2)
            self.assertEqual(sample.call_count, 2)
            self.assertEqual(result["experiment"], "tool_selection")
            self.assertNotIn("comparison", result["cases"][0])
            with self.assertRaisesRegex(benchmark.BenchmarkError, "explicit tool_selection"):
                benchmark.run_selection_benchmark(repo=Path("."), base_revision="a" * 40, driver_argv=["host-driver"], case_ids=["readonly_review"], samples=1)

    def test_discovery_cli_reports_partial_evidence_without_traceback(self) -> None:
        from scripts import agent_tool_discovery as discovery
        corpus = discovery.load_corpus(discovery.DEFAULT_CORPUS)
        with tempfile.TemporaryDirectory() as tmp:
            captured, output = Path(tmp) / "results.json", Path(tmp) / "report.json"
            captured.write_text(json.dumps({"schema_version": 1, "corpus_fingerprint": discovery.corpus_fingerprint(corpus), "base_revision": "a" * 40, "results": []}))
            self.assertEqual(report.main(["discovery", "--results", str(captured), "--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text())["status"], "unavailable")
            captured.write_text("{}")
            self.assertEqual(report.main(["discovery", "--results", str(captured), "--output", str(output)]), 2)


if __name__ == "__main__":
    unittest.main()
