import importlib.util
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

spec = importlib.util.spec_from_file_location("handoff_hook", Path(__file__).with_name("handoff_hook.py"))
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class HookTests(unittest.TestCase):
    def test_malformed_writer_envelope_is_visible_failure(self):
        for raw in (b"[]", b'{"success":false,"error":[]}'):
            with self.subTest(raw=raw), patch.object(
                hook.subprocess, "run", return_value=SimpleNamespace(stdout=raw, returncode=0)
            ):
                with self.assertRaises(hook.CheckpointError):
                    hook.call_writer("/fixed/writer", "/fixed/project", {"action": "status"})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="webcodex-handoff-hook-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.calls = []

    def payload(self, event="PostToolUse", **extra):
        return dict(hook_event_name=event, cwd=str(self.root), session_id="session-1",
                    permission_mode="default",
                    tool_use_id="call-1", tool_name="Bash", **extra)

    def writer(self, request):
        self.calls.append(request)
        if request["action"] == "status":
            return {"enabled": True, "bound_task_id": "task-a"}
        if request["action"] == "read":
            return {"revision": 3}
        return {"revision": 4}

    def test_read_tool_uses_no_writer_and_stop_does_not_load_history(self):
        payload = self.payload()
        payload['tool_name'] = 'read_files'
        self.assertEqual(hook.handle(payload, self.root, self.writer), {})
        self.assertEqual(self.calls, [])
        hook.handle(self.payload('Stop'), self.root, self.writer)
        self.assertEqual([r['action'] for r in self.calls], ['status'])

    def test_near_capacity_warning_does_not_claim_completion(self):
        def writer(request):
            return {'enabled':True,'bound_task_id':'a','usage':{'near_limit':True}}
        result = hook.handle(self.payload('Stop'),self.root,writer)
        self.assertIn('near its limit',str(result))
        self.assertNotIn('decision',result)

    def test_project_mismatch_never_reads_or_writes_checkpoint(self):
        payload = self.payload()
        payload["cwd"] = str(self.root.parent)
        with self.assertRaisesRegex(hook.CheckpointError, "project_mismatch"):
            hook.handle(payload, self.root, self.writer)
        self.assertEqual(self.calls, [])

    def test_unbound_multi_task_does_not_guess_or_write(self):
        def writer(req):
            self.calls.append(req)
            return {"enabled": True, "tasks": [{"task_id": "a"}, {"task_id": "b"}]}
        output = hook.handle(self.payload("SessionStart"), self.root, writer)
        self.assertIn("a, b", str(output))
        self.assertEqual([r["action"] for r in self.calls], ["status"])

    def test_unbound_post_tool_reports_missing_fact_without_replay(self):
        result=hook.handle(self.payload(),self.root,lambda req:{"enabled":True,"tasks":[]})
        self.assertIn("NOT saved",str(result))
        self.assertIn("Do not replay",str(result))

    def test_pending_job_success_is_not_terminal_success(self):
        result = hook.handle(self.payload(tool_response={"success": True, "job_id": "j1",
                            "status": "running"}), self.root, self.writer)
        self.assertEqual(self.calls[-1]["event"]["status"], "unknown")
        self.assertNotIn("decision", result)
        self.assertNotIn("continue", result)

    def test_successful_job_submission_with_exit_zero_stays_unknown(self):
        hook.handle(self.payload(tool_response={"exit_code":0,"job_id":"job-1","terminal":False}),self.root,self.writer)
        self.assertEqual(self.calls[-1]["event"]["status"],"unknown")
        self.assertEqual(self.calls[-1]["event"]["job_id"],"job-1")

    def test_text_only_bash_output_never_forges_execution_receipt(self):
        for output in ("", "Process exited with code 0\nOutput:\nsuccess",
                       '{"exit_code": 0}', "secret-output"):
            with self.subTest(output=output):
                result = hook.handle(self.payload(tool_response=output), self.root, self.writer)
                fact = self.calls[-1]["event"]
                self.assertEqual(fact["status"], "unknown")
                self.assertNotIn("exit_code", fact)
                self.assertIn("text_output_without_execution_receipt", fact["summary"])
                self.assertNotIn("secret-output", str(self.calls))
                self.assertIn("text_output_without_execution_receipt", str(result))

    def test_structured_terminal_receipts_and_invalid_exit_codes(self):
        for code, expected in ((0, "completed"), (7, "failed"), (True, "unknown"),
                               ("0", "unknown"), (None, "unknown")):
            with self.subTest(code=code):
                hook.handle(self.payload(tool_response={"exit_code": code}), self.root, self.writer)
                self.assertEqual(self.calls[-1]["event"]["status"], expected)

    def test_known_read_tool_does_not_append(self):
        payload=self.payload();payload["tool_name"]="read_files"
        self.assertEqual(hook.handle(payload,self.root,self.writer),{})
        self.assertEqual([r["action"] for r in self.calls],[])

    def test_startup_surfaces_source_pending(self):
        result=hook.handle(self.payload("UserPromptSubmit"),self.root,self.writer,
            source_probe=lambda task,checkpoint:{"status":"pending","pending":3,"capture_gaps":0})
        self.assertIn('"pending": 3',str(result))
        self.assertIn('historical snapshot',str(result))
        self.assertIn(str(self.root/'handoff/task-a.json'),str(result))
        self.assertIn(str(self.root/'handoff/task-a.md'),str(result))

    def test_failed_command_remains_failed_and_no_raw_payload_is_persisted(self):
        payload = self.payload(tool_response={"exit_code": 7, "stdout": "secret-output"},
                               tool_input={"command": "secret-command"},
                               transcript_path="/unrelated/private-transcript")
        hook.handle(payload, self.root, self.writer)
        self.assertEqual(self.calls[-1]["event"]["status"], "failed")
        serialized = str(self.calls)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("transcript", serialized)
        self.assertNotIn("session-1", serialized)

    def test_stop_does_not_loop_or_assert_completion(self):
        output = hook.handle(self.payload("Stop", stop_hook_active=True), self.root, self.writer)
        self.assertEqual([r["action"] for r in self.calls], ["status"])
        self.assertNotIn("decision", output)
        self.assertNotIn("continue", output)

    def test_save_failure_not_returned_as_saved(self):
        def writer(req):
            if req["action"] == "append":
                raise hook.CheckpointError("revision_conflict")
            return self.writer(req)
        with self.assertRaisesRegex(hook.CheckpointError, "revision_conflict"):
            hook.handle(self.payload(), self.root, writer)

    def test_duplicate_callback_uses_same_event_id_and_expected_revision(self):
        hook.handle(self.payload(), self.root, self.writer)
        first = self.calls[-1]
        hook.handle(self.payload(), self.root, self.writer)
        self.assertEqual(first, self.calls[-1])
        self.assertEqual(first["expected_revision"], 3)

    def test_missing_enabled_is_not_silent_disable(self):
        with self.assertRaisesRegex(hook.CheckpointError, "invalid_discovery_response"):
            hook.handle(self.payload(), self.root, lambda req: {})

    def test_disabled_project_is_read_only(self):
        output = hook.handle(self.payload(), self.root, lambda req: {"enabled": False})
        self.assertEqual(output, {})

    def test_plan_mode_never_appends(self):
        payload = self.payload()
        payload["permission_mode"] = "plan"
        output = hook.handle(payload, self.root, self.writer)
        self.assertEqual([r["action"] for r in self.calls], ["status"])
        self.assertIn("write skipped", str(output))


class ConcurrentSaveTests(unittest.TestCase):
    setUp = HookTests.setUp
    payload = HookTests.payload

    def test_conflict_retries_identical_fact_at_fresh_revision(self):
        import copy
        attempts = []
        def writer(req):
            if req['action'] == 'status':
                return {'enabled': True, 'bound_task_id': 'task-a'}
            if req['action'] == 'read':
                return {'revision': 3 + len(attempts)}
            attempts.append(copy.deepcopy(req))
            if len(attempts) == 1:
                raise hook.CheckpointError('revision_conflict')
            return {'status':'saved'}
        hook.handle(self.payload(tool_response={'exit_code':0}), self.root, writer)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]['event'], attempts[1]['event'])
        self.assertEqual([r['expected_revision'] for r in attempts], [3,4])

    def test_conflict_rechecks_binding_and_does_not_retarget(self):
        attempts = []
        def writer(req):
            if req['action'] == 'status':
                return {'enabled':True, 'bound_task_id':'other' if attempts else 'task-a'}
            if req['action'] == 'read': return {'revision':3}
            attempts.append(req)
            raise hook.CheckpointError('revision_conflict')
        with self.assertRaisesRegex(hook.CheckpointError, 'binding_changed_during_save'):
            hook.handle(self.payload(), self.root, writer)
        self.assertEqual(len(attempts), 1)

    def test_repeated_conflict_is_bounded_and_timeout_is_not_retried(self):
        for error, count in [('revision_conflict',3), ('save_outcome_unknown',1)]:
            attempts=[]
            def writer(req):
                if req['action']=='status': return {'enabled':True,'bound_task_id':'task-a'}
                if req['action']=='read': return {'revision':3+len(attempts)}
                attempts.append(req)
                raise hook.CheckpointError(error)
            with self.assertRaisesRegex(hook.CheckpointError,error):
                hook.handle(self.payload(),self.root,writer)
            self.assertEqual(len(attempts),count)

class DeadlineTests(unittest.TestCase):
    setUp = HookTests.setUp
    payload = HookTests.payload

    def test_conflict_retry_exhausts_shared_budget_without_replaying_append(self):
        import json
        elapsed = [0.0]
        actions, timeouts = [], []
        def child(argv, **kwargs):
            req = json.loads(kwargs['input'])
            actions.append(req['action'])
            timeouts.append(kwargs['timeout'])
            if kwargs['timeout'] < 6:
                elapsed[0] += kwargs['timeout']
                raise hook.subprocess.TimeoutExpired(argv, kwargs['timeout'])
            elapsed[0] += 6
            if req['action'] == 'status':
                value = {'success':True, 'output':{'enabled':True,'bound_task_id':'a'}}
            elif req['action'] == 'read':
                value = {'success':True,'output':{'revision':1}}
            else:
                value = {'success':False,'error':{'code':'revision_conflict'}}
            return SimpleNamespace(stdout=json.dumps(value).encode(),returncode=0)
        with patch.object(hook.time, 'monotonic', side_effect=lambda:elapsed[0]), patch.object(hook.subprocess, 'run', side_effect=child):
            with self.assertRaisesRegex(hook.CheckpointError, 'save_outcome_unknown'):
                hook.handle(self.payload(tool_response={'exit_code':0}), self.root,
                            lambda req:hook.call_writer('/writer',self.root,req,deadline=25))
        self.assertEqual(elapsed[0],25)
        self.assertEqual(actions,['status','read','append','status','read'])
        self.assertEqual(timeouts,[8,8,8,7,1])

    def test_expired_budget_does_not_start_writer(self):
        with patch.object(hook.time,'monotonic',return_value=26), patch.object(hook.subprocess,'run') as child:
            with self.assertRaisesRegex(hook.CheckpointError,'save_deadline_exceeded'):
                hook.call_writer('/writer',self.root,{'action':'append'},deadline=25)
            child.assert_not_called()

if __name__ == "__main__":
    unittest.main()
