"""New explicit cases cannot borrow historical or driver-declared acceptance."""
import copy
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from scripts import agent_loop_benchmark as benchmark, agent_loop_report as report
from scripts import agent_knowledge_evidence as evidence
from scripts.agent_knowledge_fixture import CASE_IDS, KnowledgeFixture
from scripts.agent_knowledge_host import private_directory, write_private, read_private, archive_capture
from scripts import agent_knowledge_host as host


class KnowledgeBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.manifest = report.load_case_manifest(report.DEFAULT_CASE_MANIFEST)
        self.case = report._case_by_id(self.manifest, "knowledge_identifier")

    @unittest.skipUnless(os.name == "posix", "POSIX umask and directory permission contract")
    def test_host_main_scopes_private_umask_and_restores_it_on_all_exits(self):
        for caller_mask in (0o022, 0o077):
            for error in (None, ValueError("handled"), RuntimeError("unhandled")):
                with self.subTest(caller_mask=caller_mask, error=error), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    def drive(args):
                        (root / "inside").mkdir()
                        self.assertEqual((root / "inside").stat().st_mode & 0o777, 0o700)
                        if error is not None:
                            raise error
                        return 0
                    previous = os.umask(caller_mask)
                    try:
                        with patch.object(host, "drive", side_effect=drive):
                            argv = ["drive", "--state-dir", str(root), "--bin-dir", str(root),
                                    "--model-config", str(root / "unused.json")]
                            if isinstance(error, RuntimeError):
                                with self.assertRaisesRegex(RuntimeError, "unhandled"):
                                    host.main(argv)
                            else:
                                self.assertEqual(host.main(argv), 2 if error else 0)
                        (root / "after").mkdir()
                        self.assertEqual((root / "after").stat().st_mode & 0o777, 0o777 & ~caller_mask)
                    finally:
                        os.umask(previous)

    def test_six_opt_in_cases_do_not_change_default_matrix_or_force_lanes(self):
        self.assertEqual(benchmark.DEFAULT_CASES, ("readonly_review", "guarded_multi_file_edit", "long_validation_handoff"))
        self.assertEqual(len(benchmark.DEFAULT_SELECTION_CASES), 4)
        for name in CASE_IDS:
            case = report._case_by_id(self.manifest, name)
            self.assertEqual(case["target"], evidence.TARGET)
            self.assertEqual(case["experiment"], "tool_selection")
            self.assertNotIn("code_mode_surface", case)
            self.assertEqual(benchmark._surface(case, "tool_selection"), "tool_selection")

    def proof(self):
        return {"schema_version": 1, "case_id": self.case["id"],
            "case_fingerprint": report._case_fingerprint(self.case), "base_revision": "a" * 40,
            "fixture_identity": "b" * 64, "available": True, "passed": True,
            "canonical_call_count": 2, "checks": {key: True for key in evidence.CHECK_NAMES}}

    def test_strict_proof_binds_all_identity_and_exact_boolean_checks(self):
        summary = {"benchmark": {"base_revision": "a" * 40}}
        self.assertTrue(benchmark._knowledge_evidence_proven(self.case, summary, self.proof(), "b" * 64))
        for key, value in (("case_id", "knowledge_procedure"), ("base_revision", "c" * 40),
                           ("case_fingerprint", "d" * 64), ("schema_version", True),
                           ("canonical_call_count", True), ("available", 1), ("passed", 1)):
            proof = self.proof(); proof[key] = value
            self.assertFalse(benchmark._knowledge_evidence_proven(self.case, summary, proof, "b" * 64))
        for value in (False, 1, None):
            proof = self.proof(); proof["checks"]["source_content_observed"] = value
            self.assertFalse(benchmark._knowledge_evidence_proven(self.case, summary, proof, "b" * 64))
        proof = self.proof(); proof["checks"]["invented"] = True
        self.assertFalse(benchmark._knowledge_evidence_proven(self.case, summary, proof, "b" * 64))

    def test_actual_run_ignores_driver_supplied_pass_proof_without_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("worktrees", "receipts", "annotations"):
                (root / name).mkdir()
            driver = root / "driver.py"
            driver.write_text('import os,json\nfrom pathlib import Path\n'
                'Path(os.environ["WEBCODEX_BENCH_DRIVER_RESULT"]).write_text(json.dumps({"status":"pass",'
                '"audit_db":"/nonexistent-knowledge-audit.db","workflow_session_id":"invented",'
                '"knowledge_evidence":{"available":True,"passed":True},"answer":{"facts":[],"sources":[]}}))\n')
            manifest = root / "manifest.json"; manifest.write_text(json.dumps(self.manifest))
            with patch.object(benchmark, "_summary_for_receipt", return_value={"benchmark": {"base_revision": "a" * 40}}):
                result = benchmark._run_sample(Path.cwd(), root, [sys.executable, str(driver)], self.case,
                    variant="tool_selection", pair_index=0, ordinal=0, base_revision="a" * 40, case_manifest=manifest)
            self.assertEqual(result["status"], "partial")
            self.assertFalse(result["knowledge_evidence"]["available"])
            self.assertFalse(list((root / "worktrees").iterdir()))

    def test_unsupported_driver_remains_unsupported_without_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("worktrees", "receipts", "annotations"):
                (root / name).mkdir()
            driver = root / "unsupported.py"
            driver.write_text('import os\nfrom pathlib import Path\n'
                'Path(os.environ["WEBCODEX_BENCH_DRIVER_RESULT"]).write_text(\'{"status":"unsupported"}\')\n')
            result = benchmark._run_sample(Path.cwd(), root, [sys.executable, str(driver)], self.case,
                variant="tool_selection", pair_index=0, ordinal=0, base_revision="a" * 40, case_manifest=root / "manifest.json")
            self.assertEqual(result["status"], "unsupported")

    def test_published_identity_is_bounded_and_matches_clean_runtime_source(self):
        receipt = {"host_config_digest": "b" * 64, "runtime_identity": {
            "build": {"version": "0.5.0", "commit_prefix": "a" * 12, "dirty": False, "built_at": 10},
            "binary_sha256": {"webcodex-server": "c" * 64, "webcodex-runner": "d" * 64}}}
        self.assertIsNotNone(benchmark._knowledge_host_identity(receipt, "a" * 40))
        for key, value in (("dirty", True), ("built_at", True), ("commit_prefix", "e" * 12), ("version", "/private/path")):
            bad = copy.deepcopy(receipt); bad["runtime_identity"]["build"][key] = value
            self.assertIsNone(benchmark._knowledge_host_identity(bad, "a" * 40))
        bad = copy.deepcopy(receipt); bad["runtime_identity"]["private"] = "never publish"
        self.assertIsNone(benchmark._knowledge_host_identity(bad, "a" * 40))

    def test_strict_matrix_rejects_missing_or_mixed_host_configuration(self):
        identity = {"model_config_digest": "b" * 64, "runtime_identity": {
            "build": {"version": "0.5.0", "commit_prefix": "a" * 12, "dirty": False, "built_at": 10},
            "binary_sha256": {"webcodex-server": "c" * 64, "webcodex-runner": "d" * 64}}}
        sample = {"case_id": self.case["id"], "status": "pass", "variant": "tool_selection", "surface": "tool_selection",
            "summary": {"benchmark": {"base_revision": "a" * 40}, "correctness": {"task_verdict": "pass", "validation_verdict": "not_required"}},
            "fixture_oracle": {"available": True, "passed": True, "fixture_identity": "b" * 64},
            "knowledge_evidence": self.proof(), "host_identity": identity}
        result = {"experiment": "tool_selection", "cases": [{"case_id": self.case["id"], "samples": [sample, copy.deepcopy(sample)]}]}
        self.assertTrue(benchmark._strict_passed(result, [self.case["id"]], 2, self.manifest))
        result["cases"][0]["samples"][1]["host_identity"]["model_config_digest"] = "e" * 64
        self.assertFalse(benchmark._strict_passed(result, [self.case["id"]], 2, self.manifest))
        result["cases"][0]["samples"][1]["host_identity"] = None
        self.assertFalse(benchmark._strict_passed(result, [self.case["id"]], 2, self.manifest))


class PrivateHostHandoffTests(unittest.TestCase):
    def test_host_failure_preserves_observation_without_inventing_model_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            write_private(root / "ready.json", {"case_id": "knowledge_procedure"})
            failure = root / "failure.txt"
            failure.write_text("无法加载此回复", encoding="utf-8")
            failure.chmod(0o600)
            self.assertEqual(host.main(["submit", "--sample-dir", str(root),
                "--session", "exact-session", "--host-failure-file", str(failure)]), 0)
            submitted = read_private(root / "submission.json")
            self.assertEqual(submitted, {"workflow_session_id": "exact-session", "answer": None})
            observation = read_private(root / "host-failure-observation.json")
            self.assertEqual(observation["reported_text"], "无法加载此回复")
            self.assertIs(observation["final_answer_observed"], False)
            self.assertEqual(observation["root_cause"], "unknown")
            fixture = KnowledgeFixture(root / "fixture", "knowledge_identifier").prepare()
            self.assertFalse(evidence.check_answer(submitted["answer"], fixture))

    def test_imported_connection_requires_a_bound_owner_and_valid_username(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            for value in ({"port": 20000, "bootstrap": "test", "username": "restored-owner"},
                          {"port": 20000, "bootstrap": "test", "owner": "test", "username": "../other"}):
                path = root / "connection.json"
                write_private(path, value)
                with self.assertRaises(ValueError):
                    host.connection(root)
                path.unlink()
            value = {"port": 20000, "bootstrap": "test", "owner": "test", "username": "restored-owner"}
            write_private(root / "connection.json", value)
            self.assertEqual(host.connection(root), value)

    def test_mcp_apps_configuration_validates_before_sample_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            model = root / "model.json"
            env = {"WEBCODEX_BENCH_" + key: "test" for key in ("WORKSPACE", "CASE_ID", "BASE_REVISION",
                "CASE_FINGERPRINT", "PROMPT", "DRIVER_RESULT", "FIXTURE_COORDINATION", "TEMPORAL_TRACE_ROOT")}
            env.update(WEBCODEX_BENCH_CASE_ID="knowledge_identifier", WEBCODEX_BENCH_TARGET=evidence.TARGET,
                       WEBCODEX_BENCH_BASE_REVISION="a" * 40)
            args = argparse.Namespace(state_dir=root, bin_dir=root, model_config=model, public_url=None)
            for value in (None, 0, 1, "false", [], {}):
                write_private(model, {"host": "chatgpt_web", "mcp_apps_enabled": value})
                with self.subTest(value=value), patch.dict(os.environ, env), patch.object(host, "HostSample") as sample:
                    with self.assertRaisesRegex(ValueError, "mcp_apps_enabled must be a boolean"):
                        host.drive(args)
                    sample.assert_not_called()
                    self.assertFalse((root / "active.lock").exists())
                model.unlink()

    def test_mcp_apps_default_and_disabled_environment(self):
        def initialize(sample, *args):
            sample.env = {"PATH": os.environ.get("PATH", ""), "WEBCODEX_MCP_APPS_ENABLED": "inherited"}
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            for option, expected in (({}, "true"), ({"mcp_apps_enabled": False}, "false")):
                directory = private_directory(root / expected)
                with patch.object(host.InteractiveSmoke, "__init__", initialize), patch.object(host, "connection",
                        return_value={"port": 20000, "bootstrap": "test"}):
                    sample = host.HostSample(root, root, directory, root, root, **option)
                self.assertEqual(sample.env["WEBCODEX_MCP_APPS_ENABLED"], expected)

    def test_drive_passes_apps_setting_and_records_explicit_ready_value(self):
        for configuration, expected in (({}, True), ({"mcp_apps_enabled": False}, False)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                root = private_directory(Path(temporary) / "private")
                model = root / "model.json"; write_private(model, {"host": "chatgpt_web", **configuration})
                args = argparse.Namespace(state_dir=root, bin_dir=root, model_config=model, public_url=None)
                env = {"WEBCODEX_BENCH_" + key: "test" for key in ("WORKSPACE", "CASE_ID", "BASE_REVISION",
                    "CASE_FINGERPRINT", "PROMPT", "DRIVER_RESULT", "FIXTURE_COORDINATION", "TEMPORAL_TRACE_ROOT")}
                env.update(WEBCODEX_BENCH_CASE_ID="knowledge_identifier", WEBCODEX_BENCH_TARGET=evidence.TARGET,
                    WEBCODEX_BENCH_BASE_REVISION="a" * 40, WEBCODEX_BENCH_DRIVER_RESULT=str(root / "receipt.json"))
                sample = Mock(url="http://127.0.0.1:20000", project="project", client_id="runner")
                def prepare():
                    directory = next((root / "samples").iterdir())
                    write_private(directory / "submission.json", {"workflow_session_id": "wc_sess_test", "answer": None})
                sample.prepare.side_effect = prepare
                with patch.dict(os.environ, env), patch.object(host, "runtime_identity", return_value={}), \
                        patch.object(host, "HostSample", return_value=sample) as constructor, \
                        patch.object(host, "archive_capture"):
                    self.assertEqual(host.drive(args), 0)
                self.assertIs(constructor.call_args.kwargs["mcp_apps_enabled"], expected)
                ready = read_private(next((root / "samples").iterdir()) / "ready.json")
                self.assertIs(ready["mcp_apps_enabled"], expected)
                self.assertEqual(ready["model_config_digest"], host.collection_identity("a" * 40, model)["model_config_digest"])

    def test_failed_prepare_closes_owned_processes_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            model = root / "model.json"; write_private(model, {"host": "chatgpt_web"})
            args = argparse.Namespace(state_dir=root, bin_dir=root, model_config=model, public_url=None)
            env = {"WEBCODEX_BENCH_" + key: "test" for key in ("WORKSPACE", "CASE_ID", "BASE_REVISION",
                "CASE_FINGERPRINT", "PROMPT", "DRIVER_RESULT", "FIXTURE_COORDINATION", "TEMPORAL_TRACE_ROOT")}
            env.update(WEBCODEX_BENCH_CASE_ID="knowledge_identifier", WEBCODEX_BENCH_TARGET=evidence.TARGET)
            env["WEBCODEX_BENCH_BASE_REVISION"] = "a" * 40
            sample = Mock(); sample.prepare.side_effect = ValueError("prepare failed after launch")
            with patch.dict(os.environ, env), patch.object(host, "runtime_identity", return_value={}), patch.object(host, "HostSample", return_value=sample):
                with self.assertRaises(ValueError):
                    host.drive(args)
            sample.close.assert_called_once()
            self.assertFalse((root / "active.lock").exists())

    def test_stop_after_current_never_launches_future_sample_or_invents_model_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            model = root / "model.json"; write_private(model, {"host": "chatgpt_web"})
            identity = host.collection_identity("a" * 40, model)
            write_private(root / "collection-stop.json", identity | {"reason": "repair evaluator"})
            env = {"WEBCODEX_BENCH_" + key: "test" for key in ("WORKSPACE", "CASE_ID", "BASE_REVISION",
                "CASE_FINGERPRINT", "PROMPT", "DRIVER_RESULT", "FIXTURE_COORDINATION", "TEMPORAL_TRACE_ROOT")}
            env.update(WEBCODEX_BENCH_CASE_ID="knowledge_identifier", WEBCODEX_BENCH_TARGET=evidence.TARGET,
                WEBCODEX_BENCH_BASE_REVISION="a" * 40, WEBCODEX_BENCH_DRIVER_RESULT=str(root / "receipt.json"))
            args = argparse.Namespace(state_dir=root, bin_dir=root, model_config=model, public_url=None)
            with patch.dict(os.environ, env), patch.object(host, "runtime_identity", return_value={}), patch.object(host, "HostSample") as sample:
                self.assertEqual(host.drive(args), 0)
            sample.assert_not_called()
            self.assertEqual(read_private(root / "receipt.json"), {"status": "unsupported",
                "reason_code": "operator_stopped_before_model_execution", "model_samples": 0})
            self.assertFalse((root / "active.lock").exists())
            self.assertFalse((root / "samples").exists())

    def test_collection_stop_rejects_other_source_configuration_and_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            model = root / "model.json"; write_private(model, {"host": "chatgpt_web"})
            common = ["--state-dir", str(root), "--base-revision", "a" * 40, "--model-config", str(model)]
            self.assertEqual(host.main(["stop-after-current", *common, "--reason", "repair evaluator"]), 0)
            with self.assertRaises(ValueError):
                host.stopped_collection(root, host.collection_identity("b" * 40, model))
            with self.assertRaises(ValueError):
                host.stopped_collection(root, {"base_revision": "a" * 40, "model_config_digest": "other"})
            self.assertEqual(host.main(["stop-after-current", *common, "--reason", "overwrite"]), 2)
            self.assertEqual(host.main(["resume-collection", *common]), 0)
            self.assertIsNone(host.stopped_collection(root, host.collection_identity("a" * 40, model)))
            self.assertEqual(len(list(root.glob("collection-stop-*.json"))), 1)
            self.assertEqual(host.main(["resume-collection", *common]), 2)

    def test_handoffs_are_private_exclusive_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "private")
            path = root / "answer.json"
            write_private(path, {"facts": [], "sources": []})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_private(path), {"facts": [], "sources": []})
            with self.assertRaises(FileExistsError):
                write_private(path, {})
            with self.assertRaises(ValueError):
                write_private(root / "large.json", {"value": "x" * 65536})

    def test_private_capture_archive_never_follows_symlink_or_hardlink(self):
        import os
        for link in ("symlink", "hardlink"):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as temporary:
                root = private_directory(Path(temporary) / "private")
                source = private_directory(root / "capture")
                outside = root / "outside"; outside.write_text("not a capture"); outside.chmod(0o600)
                if link == "symlink":
                    (source / "bad").symlink_to(outside)
                else:
                    os.link(outside, source / "bad")
                with self.assertRaises(ValueError):
                    archive_capture(source, root / "archive")


if __name__ == "__main__":
    unittest.main()
