from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest
import uuid

from scripts import agent_temporal_evidence as evidence
from scripts import agent_loop_benchmark as benchmark
from scripts import agent_loop_report as report
from scripts.tests import test_agent_loop_report as audit_tests


def call(tool, args, output, *, success=True, index=0):
    result = {"success": success, "output": output}
    return {"tool": tool, "arguments": args, "output": output, "result": result,
            "envelope": {"result": {"structuredContent": result}}, "project": "project",
            "started": index * 10, "ended": index * 10 + 1}


def positive_cases():
    failure = [call("run_script", {"language": "python", "script": evidence.pressure_script()},
                    {"exit_code": 7, "stdout": evidence.SENTINEL, "stderr": "expected failure"}, success=False),
               call("run_script", {"language": "python", "script": evidence.pressure_script(False)},
                    {"exit_code": 0, "stdout": evidence.SENTINEL}, index=1)]
    pending = [call("run_process", {"interactive": True, "executable": "python3", "args": ["-u", "-c", evidence.PENDING_SCRIPT]}, {"execution_state": "pending", "job_id": "original"}),
               call("run_script", {"language": "python", "script": "from pathlib import Path\nPath('independent.txt').write_text('independent work completed')\n"}, {"exit_code": 0}, index=1),
               call("write_job_input", {"job_id": "original", "close": True}, {}, index=2),
               call("wait_for_job_readiness", {"job_ids": ["original"], "mode": "all"}, {"pending_job_ids": []}, index=3),
               call("observe_jobs", {"items": [{"job_id": "original"}]}, {"items": [{"job_id": "original", "terminal": True,
                    "exit_code": 0, "stdout_tail": "controlled-job-complete"}]}, index=4)]
    stale = [call("read_files", {"items": [{"path": "stale.txt"}]}, {"items": [{"path": "stale.txt", "output": {"read_revision": "old", "text": "before"}}]}),
             call("edit_project_files", {"changes": [{"path": "stale.txt", "expected_read_revision": "old"}]},
                  {"error_kind": "stale_file_revision", "state_changed": False}, success=False, index=1),
             call("read_files", {"items": [{"path": "stale.txt"}]}, {"items": [{"path": "stale.txt", "output": {"read_revision": "new", "text": evidence.EXTERNAL_SENTINEL}}]}, index=2),
             call("edit_project_files", {"changes": [{"path": "stale.txt", "expected_read_revision": "new"}]}, {}, index=3)]
    stale[-1]["edit_outcome"] = "applied"
    missing = [call("finish_coding_task", {"outputs": ["missing-result.csv"]},
                    {"task_outputs": {"missing_count": 1, "verified_count": 0},
                     "task_outcome": {"status": "fail", "blocking": True, "blocking_reasons": ["task_outputs_unverified"]}})]
    values = dict(zip(sorted(evidence.TEMPORAL_CASES), [failure, missing, pending, stale]))
    transfers = []
    for index, (name, data) in enumerate(evidence.binary_fixtures().items()):
        args = {"source_project": "project", "source_path": "input/" + name,
                "destination_project": "project", "destination_path": "sorted/" + name}
        transfers.append(call("transfer_project_artifact", args,
            dict(args, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()), index=index))
    transfers.append(call("run_script", {"language": "python", "script": evidence.mixed_note_script()},
                          {"exit_code": 0}, index=3))
    values["generic_mixed_files_conflict"] = transfers
    csv = "name,value\nAlice,2\nBob,3\n陈,5\n丁,7\n"
    report_bytes = json.dumps({"count": 4, "total": 17}).encode()
    values["generic_encoded_csv"] = [
        call("run_script", {"language": "python", "script": evidence.encoded_csv_script()}, {"exit_code": 0}),
        call("finish_coding_task", {"outputs": ["merged.csv", "report.json"]},
            {"task_outcome": {"status": "warn", "blocking": False, "blocking_reasons": []},
             "task_outputs": {"verified_count": 2, "missing_count": 0, "unavailable_count": 0,
                "items": [{"path": name, "status": "verified", "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in (("merged.csv", csv.encode()), ("report.json", report_bytes))]}}, index=1)]
    return values


class TemporalSemanticsTests(unittest.TestCase):
    def test_all_six_case_sequences_can_qualify(self):
        for case, calls in positive_cases().items():
            with self.subTest(case=case):
                self.assertTrue(all(evidence._checks(case, calls).values()))

    def test_pending_rejects_redispatch_changed_job_extra_wait_and_late_work(self):
        original = positive_cases()["generic_pending_independent_join"]
        variants = []
        duplicate = copy.deepcopy(original); duplicate.append(copy.deepcopy(duplicate[0])); variants.append(duplicate)
        wrong = copy.deepcopy(original); wrong[-1]["output"]["items"][0]["job_id"] = "replacement"; variants.append(wrong)
        extra = copy.deepcopy(original); extra.append(copy.deepcopy(extra[3])); variants.append(extra)
        late = copy.deepcopy(original); late[1]["started"] = 35; variants.append(late)
        unrelated = copy.deepcopy(original); unrelated[1]["arguments"]["script"] = "pass"; variants.append(unrelated)
        for calls in variants:
            self.assertFalse(all(evidence._checks("generic_pending_independent_join", calls).values()))

    def test_failure_repair_rejects_fabricated_exit_and_lost_sentinel(self):
        original = positive_cases()["generic_failure_repair"]
        for field, value in (("exit_code", 0), ("stdout", "omitted"), ("stderr", "omitted")):
            calls = copy.deepcopy(original); calls[0]["output"][field] = value
            self.assertFalse(all(evidence._checks("generic_failure_repair", calls).values()))
        wrong = copy.deepcopy(original); wrong[1]["arguments"]["script"] = "pass"
        self.assertFalse(all(evidence._checks("generic_failure_repair", wrong).values()))

    def test_real_host_expanded_loop_and_optional_final_newline_preserve_command(self):
        calls = positive_cases()["generic_failure_repair"]
        for value in calls:
            value["arguments"]["script"] = value["arguments"]["script"].replace(
                "for i in range(2500): print('pressure-' + str(i))",
                "for i in range(2500):\n    print('pressure-' + str(i))").removesuffix("\n")
        self.assertTrue(all(evidence._checks("generic_failure_repair", calls).values()))

    def test_command_formatting_does_not_allow_changed_or_additional_execution(self):
        expected = evidence.pressure_script()
        for actual in (expected.replace("range(2500)", "range(2499)"),
                       expected + "print('extra')\n", expected.replace("sys.exit(7)", "sys.exit(0)"),
                       "# coding: latin-1\n" + expected, "# comment\n" + expected,
                       "not python !!!", None):
            with self.subTest(actual_type=type(actual).__name__):
                self.assertFalse(evidence._matches_python_command(call("run_script", {
                    "language": "python", "script": actual}, {}), expected))

    def test_stale_recovery_rejects_missing_reread_unchanged_revision_or_effect(self):
        original = positive_cases()["generic_stale_read_revision"]
        variants = [original[:2] + original[3:]]
        for field, value in (("error_kind", "permission_denied"), ("state_changed", True)):
            wrong = copy.deepcopy(original); wrong[1]["output"][field] = value; variants.append(wrong)
        wrong = copy.deepcopy(original); wrong[3]["arguments"]["changes"][0]["expected_read_revision"] = "old"; variants.append(wrong)
        for calls in variants:
            self.assertFalse(all(evidence._checks("generic_stale_read_revision", calls).values()))

    def test_missing_output_cannot_be_omitted_or_reported_as_success(self):
        original = positive_cases()["generic_missing_output"]
        for key, value in (("status", "success"), ("blocking", False), ("blocking_reasons", [])):
            calls = copy.deepcopy(original); calls[0]["output"]["task_outcome"][key] = value
            self.assertFalse(all(evidence._checks("generic_missing_output", calls).values()))
        calls = copy.deepcopy(original); calls[0]["arguments"]["outputs"] = []
        self.assertFalse(all(evidence._checks("generic_missing_output", calls).values()))

    def test_project_scope_is_not_inferred_from_order(self):
        calls = positive_cases()["generic_failure_repair"]
        calls[1]["project"] = "other"
        with self.assertRaises(evidence.EvidenceUnavailable):
            evidence._checks("generic_failure_repair", calls)

    def test_host_lane_uses_canonical_calls_without_claiming_model_turn_identity(self):
        summary = {"outer_calls": {"total": 2}, "canonical_calls": {"total": 2, "by_name": {"read_files": 2}},
                   "availability": {"code_mode_composition": {"available": True}}}
        self.assertTrue(benchmark._runtime_evidence_proven(summary, "host_code_mode", "host_code_mode"))
        self.assertEqual(benchmark._tool_count(summary, "host_code_mode", "read_files"), 2)
        summary["canonical_calls"]["by_name"]["execute_code_mode"] = 1
        self.assertFalse(benchmark._runtime_evidence_proven(summary, "host_code_mode", "host_code_mode"))

    def test_success_flag_without_terminal_fact_is_not_exit_zero(self):
        value = call("run_script", {}, {})
        self.assertIsNone(evidence._exit_code(value))
        value["execution_state"] = "pending"
        self.assertIsNone(evidence._exit_code(value))
        value["execution_state"] = "completed"
        self.assertEqual(evidence._exit_code(value), 0)
        value["output"]["exit_code"] = True
        self.assertIsNone(evidence._exit_code(value))

    def test_host_candidate_order_and_surface_are_explicit(self):
        self.assertEqual(benchmark._pair_order(0, "host_code_mode"), ("direct", "host_code_mode"))
        self.assertEqual(benchmark._pair_order(1, "host_code_mode"), ("host_code_mode", "direct"))
        self.assertEqual(benchmark._surface({}, "host_code_mode"), "host_code_mode")

    def test_temporal_gate_rejects_renamed_checks_and_wrong_case_or_base(self):
        case = report._case_by_id(report.load_case_manifest(report.DEFAULT_CASE_MANIFEST), "generic_missing_output")
        proof = {"schema_version": evidence.PROOF_SCHEMA_VERSION, "fixture_identity": "d" * 64, "case_id": case["id"], "base_revision": "a" * 40,
                 "case_fingerprint": report._case_fingerprint(case), "available": True,
                 "passed": True, "checks": {name: True for name in evidence.CHECK_NAMES[case["id"]]}}
        summary = {"benchmark": {"base_revision": "a" * 40}}
        self.assertTrue(benchmark._generic_temporal_evidence_proven(case, summary, "direct", proof, "d" * 64))
        for key, value in (("checks", {"driver_says_pass": True}), ("case_id", "other"),
                           ("base_revision", "b" * 40), ("case_fingerprint", "c" * 64)):
            wrong = dict(proof); wrong[key] = value
            self.assertFalse(benchmark._generic_temporal_evidence_proven(case, summary, "direct", wrong, "d" * 64))


class GenericRuntimeProofTests(unittest.TestCase):
    def test_all_six_require_exact_fixture_bootstrap_session_and_project(self):
        root = Path("/tmp/coordinator-fixture")
        for case_id, calls in positive_cases().items():
            bootstrap = call("work_on_project", {"client_id": "runner", "path": str(root)},
                {"session_id": "wc_sess_test", "resolved_project": "project", "project_ref": "~p1"}, index=-1)
            with self.subTest(case=case_id):
                evidence._bind_fixture([bootstrap, *calls], root, "wc_sess_test")
                variants = [calls, [], [bootstrap]]
                for field, value in (("path", "/tmp/wrong-root"), ("client_id", None), ("mode", "worktree")):
                    wrong = copy.deepcopy(bootstrap); wrong["arguments"][field] = value
                    variants.append([wrong, *calls])
                for field, value in (("session_id", "wc_sess_other"), ("resolved_project", "other-project")):
                    wrong = copy.deepcopy(bootstrap); wrong["output"][field] = value
                    variants.append([wrong, *calls])
                late = copy.deepcopy(bootstrap); late["ended"] = 999
                variants.append([late, *calls])
                wrong = copy.deepcopy(calls); wrong[-1]["project"] = "other-project"
                variants.append([bootstrap, *wrong])
                wrong = copy.deepcopy(calls); wrong[-1]["arguments"]["cwd"] = "other-subdirectory"
                variants.append([bootstrap, *wrong])
                wrong = copy.deepcopy(bootstrap); wrong["output"]["execution_context"] = {"default_cwd": "other-subdirectory"}
                variants.append([wrong, *calls])
                for variant in variants:
                    with self.assertRaises(evidence.EvidenceUnavailable):
                        evidence._bind_fixture(variant, root, "wc_sess_test")

    def test_every_successful_bootstrap_must_match_original_fixture_and_runner(self):
        root = Path("/tmp/coordinator-fixture")
        bootstrap = call("work_on_project", {"client_id": "runner", "path": str(root)},
            {"session_id": "wc_sess_test", "resolved_project": "project", "project_ref": "~p1"}, index=-1)
        calls = positive_cases()["generic_missing_output"]
        evidence._bind_fixture([bootstrap, *calls], root, "wc_sess_test")
        for field, value in (("path", "/tmp/other-fixture"), ("client_id", "other-runner")):
            foreign = copy.deepcopy(bootstrap)
            foreign["arguments"][field] = value
            foreign["output"]["project_ref"] = "~p-foreign"
            with self.subTest(field=field), self.assertRaisesRegex(
                evidence.EvidenceUnavailable, "fixture_binding_mismatch"
            ):
                evidence._bind_fixture([bootstrap, foreign, *calls], root, "wc_sess_test")
        # A later bootstrap may legitimately select the exact same Project
        # by ID rather than repeating an explicit client/path selector.
        by_project = copy.deepcopy(bootstrap)
        by_project["arguments"] = {"project": "project"}
        evidence._bind_fixture([bootstrap, by_project, *calls], root, "wc_sess_test")

    def test_boolean_status_counts_and_exit_codes_cannot_pass_strict_proof(self):
        missing = positive_cases()["generic_missing_output"]
        missing[0]["output"]["task_outputs"].update(missing_count=True, verified_count=False)
        self.assertFalse(all(evidence._checks("generic_missing_output", missing).values()))
        csv = positive_cases()["generic_encoded_csv"]
        csv[1]["output"]["task_outputs"].update(missing_count=False, unavailable_count=False)
        self.assertFalse(all(evidence._checks("generic_encoded_csv", csv).values()))
        pending = positive_cases()["generic_pending_independent_join"]
        pending[-1]["output"]["items"][0]["exit_code"] = False
        self.assertFalse(all(evidence._checks("generic_pending_independent_join", pending).values()))

    def test_mixed_transfer_results_require_exact_paths_hashes_and_success(self):
        original = positive_cases()["generic_mixed_files_conflict"]
        for where, field, value in (("output", "sha256", "f" * 64), ("output", "bytes", 0),
                                    ("arguments", "destination_path", "sorted/note.txt"),
                                    ("output", "source_path", "input/unrelated.bin"),
                                    ("result", "success", False)):
            wrong = copy.deepcopy(original); wrong[0][where][field] = value
            self.assertFalse(all(evidence._checks("generic_mixed_files_conflict", wrong).values()))
        wrong = copy.deepcopy(original); wrong.pop(0)
        self.assertFalse(all(evidence._checks("generic_mixed_files_conflict", wrong).values()))

    def test_noop_and_arbitrary_commands_are_unavailable_for_both_file_cases(self):
        for case_id in ("generic_mixed_files_conflict", "generic_encoded_csv"):
            for script in ("pass", "print('success')", "from pathlib import Path\nPath('unrelated.txt').touch()"):
                wrong = positive_cases()[case_id]
                command = next(value for value in wrong if value["tool"] == "run_script")
                command["arguments"]["script"] = script
                with self.assertRaisesRegex(evidence.EvidenceUnavailable, "unsupported_case_command"):
                    evidence._checks(case_id, wrong)

    def test_csv_requires_terminal_conversion_and_verified_output_receipts(self):
        original = positive_cases()["generic_encoded_csv"]
        variants = []
        wrong = copy.deepcopy(original); wrong[0]["output"]["exit_code"] = 7; variants.append(wrong)
        wrong = copy.deepcopy(original); wrong[0]["output"] = {}; variants.append(wrong)
        wrong = copy.deepcopy(original); wrong[1]["output"]["task_outputs"]["verified_count"] = 1; variants.append(wrong)
        wrong = copy.deepcopy(original); wrong[1]["output"]["task_outputs"]["items"][0]["status"] = "missing"; variants.append(wrong)
        wrong = copy.deepcopy(original); wrong[1]["started"] = -1; variants.append(wrong)
        for value in variants:
            self.assertFalse(all(evidence._checks("generic_encoded_csv", value).values()))
        original[1]["arguments"].pop("outputs")
        with self.assertRaisesRegex(evidence.EvidenceUnavailable, "unsupported_case_command"):
            evidence._checks("generic_encoded_csv", original)

    def test_csv_post_finish_canonical_read_only_hygiene_is_retained_and_allowed(self):
        calls = positive_cases()["generic_encoded_csv"]
        manifest = call("read_tool_manifest", {"tool": "check_workspace_hygiene"}, {}, index=2)
        hygiene = call("check_workspace_hygiene", {"project": "project"},
                       {"verdict": {"status": "warn", "blocking": False}}, index=3)
        self.assertEqual(calls[-1]["output"]["task_outcome"]["status"], "warn")
        self.assertTrue(all(evidence._checks("generic_encoded_csv", [*calls, manifest, hygiene]).values()))
        # The exception does not skip the common Project/Session/root checks.
        root = Path("/tmp/coordinator-fixture")
        bootstrap = call("work_on_project", {"client_id": "runner", "path": str(root)},
                         {"session_id": "wc_sess_test", "resolved_project": "project"}, index=-1)
        evidence._bind_fixture([bootstrap, *calls, manifest, hygiene], root, "wc_sess_test")
        hygiene["project"] = "other-project"
        with self.assertRaises(evidence.EvidenceUnavailable):
            evidence._bind_fixture([bootstrap, *calls, manifest, hygiene], root, "wc_sess_test")

    def test_csv_after_finish_execution_edit_second_finish_and_other_observers_do_not_qualify(self):
        later_calls = [
            call("run_script", {"language": "python", "script": "assert True"}, {"exit_code": 0}, index=3),
            call("run_process", {"executable": "python3", "args": ["-c", "assert True"]}, {"exit_code": 0}, index=3),
            call("run_shell", {"command": "true"}, {"exit_code": 0}, index=3),
            call("edit_project_files", {"changes": []}, {}, index=3),
            call("finish_coding_task", {"outputs": ["merged.csv", "report.json"]}, {}, index=3),
            call("read_files", {"items": [{"path": "merged.csv"}]}, {}, index=3),
        ]
        for later in later_calls:
            with self.subTest(tool=later["tool"]):
                try:
                    checks = evidence._checks("generic_encoded_csv", [*positive_cases()["generic_encoded_csv"], later])
                except evidence.EvidenceUnavailable:
                    continue
                self.assertFalse(all(checks.values()))

    def test_csv_structured_applied_create_is_supported_and_dry_run_is_not(self):
        calls = positive_cases()["generic_encoded_csv"]
        edit = call("edit_project_files", {"changes": [
            {"kind": "create", "path": "merged.csv", "content": "name,value\nAlice,2\nBob,3\n陈,5\n丁,7\n"},
            {"kind": "create", "path": "report.json", "content": '{"total":17,"count":4}'}]}, {})
        edit["edit_outcome"] = "applied"
        calls[0] = edit
        self.assertTrue(all(evidence._checks("generic_encoded_csv", calls).values()))
        edit["arguments"]["dry_run"] = True
        with self.assertRaises(evidence.EvidenceUnavailable):
            evidence._checks("generic_encoded_csv", calls)

    def test_extra_successful_validation_is_allowed_but_noop_only_and_duplicate_mutations_are_not(self):
        for case_id in ("generic_mixed_files_conflict", "generic_encoded_csv"):
            calls = positive_cases()[case_id]
            validation = call("run_script", {"language": "python", "script": "assert True"}, {"exit_code": 0}, index=8)
            if case_id == "generic_encoded_csv":
                calls[-1]["started"], calls[-1]["ended"] = 100, 101
            self.assertTrue(all(evidence._checks(case_id, [*calls, validation]).values()))
            for output in ({}, {"exit_code": 7}, {"execution_state": "pending", "job_id": "job"}):
                wrong = copy.deepcopy(validation); wrong["output"] = output
                with self.assertRaises(evidence.EvidenceUnavailable):
                    evidence._checks(case_id, [*calls, wrong])
            mutation = next(value for value in calls if value["tool"] == "run_script")
            with self.assertRaises(evidence.EvidenceUnavailable):
                evidence._checks(case_id, [*calls, copy.deepcopy(mutation)])

    def test_csv_finish_requires_actual_nonblocking_outcome(self):
        for field, value in (("status", "fail"), ("blocking", True), ("blocking_reasons", ["task_outputs_unverified"])):
            calls = positive_cases()["generic_encoded_csv"]
            calls[1]["output"]["task_outcome"][field] = value
            self.assertFalse(all(evidence._checks("generic_encoded_csv", calls).values()))
        calls[1]["output"].pop("task_outcome")
        with self.assertRaises(evidence.EvidenceUnavailable):
            evidence._checks("generic_encoded_csv", calls)

    def test_foreign_runtime_cwd_and_echo_as_python_do_not_prove_fixture_execution(self):
        root = Path("/tmp/coordinator-fixture")
        bootstrap = call("work_on_project", {"client_id": "runner", "path": str(root)},
            {"session_id": "wc_sess_test", "resolved_project": "project"}, index=-1)
        for field in ("cwd",):
            calls = positive_cases()["generic_failure_repair"]
            calls[0]["output"][field] = "/tmp/foreign-root"
            with self.assertRaises(evidence.EvidenceUnavailable):
                evidence._bind_fixture([bootstrap, *calls], root, "wc_sess_test")
        calls = positive_cases()["generic_pending_independent_join"]
        calls[0]["arguments"]["executable"] = "echo"
        self.assertFalse(all(evidence._checks("generic_pending_independent_join", calls).values()))

    def test_stale_dry_run_or_no_change_does_not_prove_applied_recovery(self):
        for outcome in (None, "validated", "no_change"):
            calls = positive_cases()["generic_stale_read_revision"]
            calls[-1]["edit_outcome"] = outcome
            self.assertFalse(all(evidence._checks("generic_stale_read_revision", calls).values()))
        calls[-1]["edit_outcome"] = "applied"
        calls[-1]["arguments"]["dry_run"] = True
        self.assertFalse(all(evidence._checks("generic_stale_read_revision", calls).values()))

    def test_schema_one_proof_and_cross_fixture_proof_never_grant_strict(self):
        manifest = report.load_case_manifest(report.DEFAULT_CASE_MANIFEST)
        for case_id in evidence.RUNTIME_CASES:
            case = report._case_by_id(manifest, case_id)
            proof = {"schema_version": 2, "fixture_identity": "d" * 64, "case_id": case_id,
                     "base_revision": "a" * 40, "case_fingerprint": report._case_fingerprint(case),
                     "available": True, "passed": True,
                     "checks": {name: True for name in evidence.CHECK_NAMES[case_id]}}
            summary = {"benchmark": {"base_revision": "a" * 40}}
            self.assertTrue(benchmark._generic_temporal_evidence_proven(case, summary, "direct", proof, "d" * 64))
            self.assertFalse(benchmark._generic_temporal_evidence_proven(case, summary, "direct", dict(proof, schema_version=1), "d" * 64))
            self.assertFalse(benchmark._generic_temporal_evidence_proven(case, summary, "direct", proof, "e" * 64))
            self.assertFalse(benchmark._generic_temporal_evidence_proven(case, summary, "direct", proof))


@unittest.skipUnless(os.name == "posix" and shutil.which("zstd"), "private local trace verifier requires POSIX and zstd")
class TemporalCaptureTests(unittest.TestCase):
    def setUp(self):
        self.audit = audit_tests.AgentLoopReportTests()
        self.audit.setUp()
        self.addCleanup(self.audit.tearDown)
        self.root = self.audit.root / "capture"
        self.case = "generic_missing_output"
        self.base, self.fingerprint = "a" * 40, "b" * 64
        self.fixture_root = self.audit.root / "fixture"
        self.fixture_root.mkdir()
        evidence.prepare_capture(self.root, self.case, self.base, self.fingerprint, fixture_root=self.fixture_root)
        self.trace = str(uuid.uuid4())
        self.directory = self.root / self.trace
        self.directory.mkdir(mode=0o700)
        (self.directory / "payloads").mkdir(mode=0o700)
        self.private_write(self.directory / ".webcodex-tool-trace", b"")
        self.audit.insert_event("one", tool="finish_coding_task", trace_id=self.trace)
        self.events = []
        self.calls = positive_cases()[self.case]
        for phase, value in (("effective_arguments", self.calls[0]["arguments"]), ("final_response", self.calls[0]["envelope"])):
            self.payload(phase, value)
        self.extra_capture("work_on_project", {"client_id": "runner", "path": str(self.fixture_root)},
                           output={"session_id": "wc_sess_test", "resolved_project": "agent:test:project"},
                           started=10, handed=20)

    def private_write(self, path, data):
        path.write_bytes(data); path.chmod(0o600)

    def payload(self, phase, value):
        raw = json.dumps(value).encode()
        compressed = subprocess.run(["zstd", "-q", "-c"], input=raw, stdout=subprocess.PIPE, check=True).stdout
        path = "payloads/" + phase + ".json.zst"
        self.private_write(self.directory / path, compressed)
        self.events.append({"event": "tool_trace_payload_captured", "server_trace_id": self.trace,
                            "encoding": "json+zstd", "phase": phase, "payload_path": path,
                            "payload_bytes": len(raw), "compressed_bytes": len(compressed),
                            "payload_sha256": hashlib.sha256(raw).hexdigest()})
        self.flush()

    def flush(self):
        self.private_write(self.directory / "events.jsonl", b"\n".join(json.dumps(event).encode() for event in self.events))

    def verify(self):
        return evidence.verify(capture_root=self.root, audit_db=self.audit.audit_db,
                               workflow_session_id="wc_sess_test", case_id=self.case,
                               base_revision=self.base, fingerprint=self.fingerprint, fixture_root=self.fixture_root)

    def extra_capture(self, tool, arguments, *, output=None, started=130, handed=140, window="hashed-window-a"):
        if tool == "work_on_project" and output is not None:
            output = dict(output)
            output.setdefault("resolved_project", "agent:test:project")
        saved = self.trace, self.directory, self.events
        self.trace = str(uuid.uuid4())
        self.directory = self.root / self.trace
        self.directory.mkdir(mode=0o700)
        (self.directory / "payloads").mkdir(mode=0o700)
        self.private_write(self.directory / ".webcodex-tool-trace", b"")
        self.events = []
        self.audit.insert_event(self.trace, tool=tool, trace_id=self.trace, started=started, handed=handed, window=window)
        with sqlite3.connect(self.audit.audit_db) as connection:
            connection.execute("UPDATE action_events SET project=NULL WHERE event_id=?", (self.trace,))
        try:
            self.payload("effective_arguments", arguments)
            if output is not None:
                self.payload("final_response", {"result": {"structuredContent": {"success": True, "output": output}}})
        finally:
            self.trace, self.directory, self.events = saved

    def test_exact_session_summary_needs_no_discussion_response_capture(self):
        self.extra_capture("read_session_discussion_summary", {"session_id": "wc_sess_test"})
        self.assertTrue(self.verify()["passed"], self.verify())

    def test_session_summary_cannot_borrow_recording_link_for_another_target(self):
        for index, selector in enumerate(("wc_sess_other", "~s1", None)):
            with self.subTest(selector=selector):
                self.extra_capture("read_session_discussion_summary", {"session_id": selector},
                                   started=130 + index * 20, handed=140 + index * 20)
                self.assertEqual(self.verify()["reason"], "context_session_mismatch")

    def test_session_summary_alias_requires_prior_exact_bootstrap_mapping(self):
        self.extra_capture("work_on_project", {}, output={"session_id": "wc_sess_test", "session_ref": "~s1"})
        self.extra_capture("read_session_discussion_summary", {"session_id": "~s1"}, started=150, handed=160)
        self.assertTrue(self.verify()["passed"], self.verify())

    def test_later_bootstrap_cannot_retroactively_bind_context_alias(self):
        self.extra_capture("read_session_discussion_summary", {"session_id": "~s1"})
        self.extra_capture("work_on_project", {}, output={"session_id": "wc_sess_test", "session_ref": "~s1"},
                           started=150, handed=160)
        self.assertEqual(self.verify()["reason"], "context_session_mismatch")

    def test_bootstrap_for_other_session_does_not_prove_context_alias(self):
        self.extra_capture("work_on_project", {}, output={"session_id": "wc_sess_other", "session_ref": "~s1"})
        self.extra_capture("read_session_discussion_summary", {"session_id": "~s1"}, started=150, handed=160)
        self.assertEqual(self.verify()["reason"], "context_session_mismatch")

    def test_session_context_retains_window_and_order_fences(self):
        self.extra_capture("read_session_discussion_summary", {"session_id": "wc_sess_test"}, window="other-window")
        self.assertEqual(self.verify()["reason"], "scope_mismatch")

    def test_session_context_overlap_is_still_incomplete(self):
        self.extra_capture("read_session_discussion_summary", {"session_id": "wc_sess_test"}, started=110, handed=130)
        self.assertEqual(self.verify()["reason"], "ambiguous_order")

    def test_independent_file_evidence_can_retain_overlapping_context_without_relaxing_temporal_order(self):
        self.extra_capture("read_session_discussion_summary", {"session_id": "wc_sess_test"}, started=110, handed=130)
        events = evidence._audit_events(self.audit.audit_db, "wc_sess_test")
        self.assertTrue(evidence._calls(events, self.root, "wc_sess_test", require_serial=False))
        with self.assertRaisesRegex(evidence.EvidenceUnavailable, "ambiguous_order"):
            evidence._calls(events, self.root, "wc_sess_test")

    def test_projectless_mutation_is_not_session_read_context(self):
        self.extra_capture("checkpoint_goal", {}, output={})
        self.assertEqual(self.verify()["reason"], "project_mismatch")

    def test_fixture_root_replacement_and_other_trusted_root_cannot_borrow_capture(self):
        other = self.audit.root / "other-fixture"
        other.mkdir()
        result = evidence.verify(capture_root=self.root, audit_db=self.audit.audit_db,
            workflow_session_id="wc_sess_test", case_id=self.case, base_revision=self.base,
            fingerprint=self.fingerprint, fixture_root=other)
        self.assertFalse(result["available"])
        self.fixture_root.rename(self.audit.root / "old-fixture")
        self.fixture_root.mkdir()
        self.assertFalse(self.verify()["available"])

    def test_actual_capture_with_exact_audit_and_digest_passes_without_payload_output(self):
        result = self.verify()
        self.assertTrue(result["available"], result)
        self.assertTrue(result["passed"], result)
        serialized = json.dumps(result)
        for private in (self.trace, "missing-result.csv", "wc_sess_test", "agent:test:project"):
            self.assertNotIn(private, serialized)

    def test_unlinked_session_cannot_borrow_another_capture(self):
        self.audit.insert_event("other", session="other", tool="finish_coding_task", trace_id=str(uuid.uuid4()))
        self.assertTrue(self.verify()["passed"])

    def test_unrecorded_runtime_call_cannot_disappear_from_dispatch_counts(self):
        unlinked = self.root / str(uuid.uuid4())
        unlinked.mkdir(mode=0o700)
        self.private_write(unlinked / "events.jsonl", json.dumps({"event": "tool_trace_diagnostic",
            "server_trace_id": unlinked.name, "phase": "kernel_arguments", "tool_name": "run_process"}).encode())
        self.assertEqual(self.verify()["reason"], "unlinked_runtime_call")

    def test_tampered_size_digest_path_duplicate_and_missing_phase_fail_closed(self):
        original = copy.deepcopy(self.events)
        variants = []
        for key, value in (("payload_sha256", "f" * 64), ("payload_bytes", 1),
                           ("payload_path", "payloads/../../private.json.zst"), ("server_trace_id", str(uuid.uuid4()))):
            wrong = copy.deepcopy(original); wrong[0][key] = value; variants.append(wrong)
        variants.extend([original[:1], original + original[:1]])
        for events in variants:
            self.events = events; self.flush()
            self.assertFalse(self.verify()["available"])

    def test_symlink_and_world_readable_capture_fail_closed(self):
        path = self.directory / self.events[0]["payload_path"]
        path.chmod(0o644)
        self.assertFalse(self.verify()["available"])
        path.chmod(0o600)
        outside = self.audit.root / "outside"
        path.rename(outside)
        path.symlink_to(outside)
        self.assertFalse(self.verify()["available"])
        self.assertTrue(outside.exists())

    def test_corrupt_payload_and_wrong_case_binding_are_unavailable(self):
        path = self.directory / self.events[0]["payload_path"]
        self.private_write(path, b"corrupted")
        self.assertFalse(self.verify()["available"])
        self.private_write(self.root / evidence.CAPTURE_MARKER, b"{}")
        self.assertFalse(self.verify()["available"])

    def test_overlap_or_mismatched_canonical_outcome_is_not_evidence(self):
        self.audit.insert_event("second", trace_id=str(uuid.uuid4()), started=110, handed=130)
        self.assertFalse(self.verify()["available"])


if __name__ == "__main__":
    unittest.main()
