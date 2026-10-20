#!/usr/bin/env python3
"""Explicit, disposable-fixture verifier for actual full MCP trace captures.

Unlike agent_loop_report, this opt-in verifier opens payloads. Its caller owns
the private capture directory, selects an exact recorded Session, and destroys
the directory afterwards. Only bounded checks, reasons and fixture identity leave this module.
Trace integrity is local producer evidence, not cryptographic Host attestation.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import itertools
import sqlite3
import time
import tokenize
import uuid

try:
    from scripts import agent_loop_report as report
    from scripts.e2e_generic_agent_ws import SENTINEL, EXTERNAL_SENTINEL, PENDING_SCRIPT, pressure_script, mixed_note_script, encoded_csv_script, binary_fixtures, GenericFixture
except ModuleNotFoundError:
    import agent_loop_report as report
    from e2e_generic_agent_ws import SENTINEL, EXTERNAL_SENTINEL, PENDING_SCRIPT, pressure_script, mixed_note_script, encoded_csv_script, binary_fixtures, GenericFixture

TEMPORAL_CASES = frozenset(("generic_failure_repair", "generic_pending_independent_join",
                           "generic_stale_read_revision", "generic_missing_output"))
PROOF_SCHEMA_VERSION = 2
RUNTIME_CASES = TEMPORAL_CASES | {"generic_mixed_files_conflict", "generic_encoded_csv"}
CHECK_NAMES = {
    "generic_mixed_files_conflict": {"binary_artifact_transfers", "conflict_preserving_text_mutation"},
    "generic_encoded_csv": {"controlled_csv_conversion", "verified_csv_output_receipts"},
    "generic_failure_repair": {"exact_failure_repair_commands", "ordered_exit_7_then_0", "failure_diagnostic_and_sentinel"},
    "generic_pending_independent_join": {"one_original_job_and_join", "independent_before_release", "same_job_release_join_terminal"},
    "generic_stale_read_revision": {"stale_rejection_fresh_recovery"},
    "generic_missing_output": {"missing_output_blocks_finish"},
}
for _case_checks in CHECK_NAMES.values():
    _case_checks.add("fixture_root_session_project")

# These canonical observers cannot execute or mutate Project work. Their target
# must still resolve to this exact recorded Session; their discussion bodies are
# unnecessary for the task oracle and must not be opened.
SESSION_CONTEXT_TOOLS = frozenset(("read_session_discussion_summary",))
MAX_CALLS = 128
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_COMPRESSED_BYTES = 512 * 1024
CAPTURE_MARKER = ".webcodex-benchmark-capture"
UNAVAILABLE_REASONS = frozenset(("unsafe_capture", "capture_limit", "capture_changed", "corrupt_capture",
    "invalid_trace_identity", "trace_identity_mismatch", "incomplete_capture", "ambiguous_capture",
    "missing_canonical_call", "missing_order", "missing_scope", "scope_mismatch", "canonical_call_mismatch",
    "missing_mcp_result", "canonical_result_mismatch", "ambiguous_order", "project_mismatch",
    "unsupported_case", "capture_identity_mismatch", "unlinked_runtime_call", "context_session_mismatch",
    "fixture_binding_unavailable", "fixture_binding_mismatch", "fixture_identity_mismatch", "unsupported_case_command"))


class EvidenceUnavailable(ValueError):
    pass


def _private(path, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or (not directory and info.st_nlink != 1)):
        raise EvidenceUnavailable("unsafe_capture")
    return info


def _read(path, ceiling):
    before = _private(path)
    if before.st_size > ceiling:
        raise EvidenceUnavailable("capture_limit")
    # Descriptor-relative traversal prevents a replaced parent symlink from
    # redirecting a capture read between the ownership check and open.
    absolute = path.absolute()
    parent = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:-1]:
            next_parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = next_parent
        fd = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise EvidenceUnavailable("capture_changed")
        data = handle.read(ceiling + 1)
        after = os.fstat(handle.fileno())
        if len(data) > ceiling or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise EvidenceUnavailable("capture_changed")
        return data


def fixture_identity(root):
    """Coordinator-owned identity, not freshness or a digest of Project contents."""
    root = Path(root).absolute()
    resolved = root.resolve(strict=True)
    info = root.lstat()
    if resolved != root or not stat.S_ISDIR(info.st_mode):
        raise EvidenceUnavailable("fixture_identity_mismatch")
    return hashlib.sha256(json.dumps([str(root), info.st_dev, info.st_ino]).encode()).hexdigest()


def prepare_capture(root, case_id, base_revision, fingerprint, *, fixture_root):
    identity = fixture_identity(fixture_root)
    # A disposable Server may create the private trace directory during setup,
    # before its fixture root exists. A marker can only be created once.
    root.mkdir(mode=0o700, exist_ok=True)
    _private(root, True)
    marker = root / CAPTURE_MARKER
    with marker.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps({"case_id": case_id, "base_revision": base_revision,
                                 "case_fingerprint": fingerprint, "fixture_identity": identity}))
    marker.chmod(0o600)
    return identity


def _decompress(data):
    # Read at most the ceiling from stdout before waiting; never communicate an
    # unbounded decompression bomb or inherit input/stderr from the terminal.
    import tempfile
    with tempfile.TemporaryFile() as source:
        source.write(data)
        source.seek(0)
        process = subprocess.Popen(["zstd", "-q", "-d", "-c"], stdin=source,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            raw = process.stdout.read(MAX_PAYLOAD_BYTES + 1)
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise EvidenceUnavailable("capture_limit")
            if process.wait(timeout=5) != 0:
                raise EvidenceUnavailable("corrupt_capture")
            return raw
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()


def _payloads(root, trace_id, phases=frozenset(("effective_arguments", "final_response"))):
    if not isinstance(trace_id, str) or str(uuid.UUID(trace_id)) != trace_id:
        raise EvidenceUnavailable("invalid_trace_identity")
    directory = root / trace_id
    _private(directory, True)
    _read(directory / ".webcodex-tool-trace", 1024)
    _private(directory / "payloads", True)
    events = [json.loads(line) for line in _read(directory / "events.jsonl", MAX_INDEX_BYTES).splitlines() if line.strip()]
    if len(events) > 4096:
        raise EvidenceUnavailable("capture_limit")
    selected = {}
    for event in events:
        if not isinstance(event, dict) or event.get("server_trace_id") != trace_id:
            raise EvidenceUnavailable("trace_identity_mismatch")
        if event.get("event") in ("tool_trace_capture_omitted", "tool_trace_capture_failed"):
            raise EvidenceUnavailable("incomplete_capture")
        if event.get("event") != "tool_trace_payload_captured":
            continue
        phase = event.get("phase")
        if phase not in phases:
            continue
        if phase in selected or event.get("encoding") != "json+zstd":
            raise EvidenceUnavailable("ambiguous_capture")
        size, compressed = event.get("payload_bytes"), event.get("compressed_bytes")
        if (type(size) is not int or not 0 < size <= MAX_PAYLOAD_BYTES
                or type(compressed) is not int or not 0 < compressed <= MAX_COMPRESSED_BYTES):
            raise EvidenceUnavailable("capture_limit")
        name = event.get("payload_path")
        if not isinstance(name, str) or not re.fullmatch(r"payloads/[a-zA-Z0-9_-]+\.json\.zst", name):
            raise EvidenceUnavailable("unsafe_capture")
        data = _read(directory / name, MAX_COMPRESSED_BYTES)
        if len(data) != compressed:
            raise EvidenceUnavailable("corrupt_capture")
        raw = _decompress(data)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != event.get("payload_sha256"):
            raise EvidenceUnavailable("corrupt_capture")
        selected[phase] = json.loads(raw)
    if set(selected) != phases:
        raise EvidenceUnavailable("incomplete_capture")
    return selected


def _calls(events, root, workflow_session_id, *, require_serial=True):
    calls, seen, scope = [], set(), None
    intervals, contexts = [], []
    for event in events:
        if event.get("action_name") != "toolsCall":
            continue
        telemetry = (event.get("summary") or {}).get("model_ergonomics") or {}
        tool = telemetry.get("tool_name")
        if not isinstance(tool, str) or not tool:
            raise EvidenceUnavailable("missing_canonical_call")
        trace_id = event.get("server_trace_id")
        if trace_id in seen:
            raise EvidenceUnavailable("ambiguous_capture")
        seen.add(trace_id)
        started, ended = event.get("request_observed_at_ms"), event.get("response_handed_at_ms")
        if (type(started) is not int or type(ended) is not int or ended < started
                or event.get("response_streaming") is not False):
            raise EvidenceUnavailable("missing_order")
        current_scope = tuple(event.get(key) for key in ("client_window_key", "principal_correlation_kind", "principal_correlation_id"))
        if not all(isinstance(value, str) and value for value in current_scope):
            raise EvidenceUnavailable("missing_scope")
        if scope is not None and scope != current_scope:
            raise EvidenceUnavailable("scope_mismatch")
        scope = current_scope
        intervals.append((started, ended))
        context_only = tool in SESSION_CONTEXT_TOOLS
        captured = _payloads(root, trace_id, frozenset(("effective_arguments",)) if context_only
                             else frozenset(("effective_arguments", "final_response")))
        arguments = captured["effective_arguments"]
        if event.get("operation") == "call_runtime_tool":
            if arguments.get("tool") != tool or not isinstance(arguments.get("arguments"), dict):
                raise EvidenceUnavailable("canonical_call_mismatch")
            arguments = arguments["arguments"]
        if context_only:
            if not isinstance(arguments, dict):
                raise EvidenceUnavailable("missing_canonical_call")
            contexts.append((arguments.get("session_id"), started))
            continue
        body = captured["final_response"]
        result = body.get("result", {}).get("structuredContent")
        if not isinstance(arguments, dict) or not isinstance(result, dict):
            raise EvidenceUnavailable("missing_mcp_result")
        if type(result.get("success")) is not bool or result["success"] != telemetry.get("success"):
            raise EvidenceUnavailable("canonical_result_mismatch")
        output = result.get("output")
        if not isinstance(output, dict):
            raise EvidenceUnavailable("missing_mcp_result")
        calls.append({"tool": tool, "arguments": arguments, "result": result,
                      "output": output, "started": started, "ended": ended,
                      "envelope": body, "project": event.get("project"),
                      "execution_state": telemetry.get("execution_state"),
                      "edit_outcome": telemetry.get("edit_outcome")})
    if not 0 < len(calls) <= MAX_CALLS:
        raise EvidenceUnavailable("capture_limit")
    calls.sort(key=lambda call: call["started"])
    intervals.sort()
    if require_serial and any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise EvidenceUnavailable("ambiguous_order")
    for selector, started in contexts:
        # A short ref is valid only after a successful bootstrap independently
        # returned its mapping to this canonical Session in the same scope.
        mapped = any(call["tool"] == "work_on_project" and call["result"]["success"] is True
                     and call["ended"] <= started and call["output"].get("session_id") == workflow_session_id
                     and isinstance(selector, str) and re.fullmatch(r"~s[1-9][0-9]{0,18}", selector)
                     and call["output"].get("session_ref") == selector for call in calls)
        if selector != workflow_session_id and not mapped:
            raise EvidenceUnavailable("context_session_mismatch")
    return calls


def _coverage(root, selected):
    """An unrecorded call cannot disappear from an execution-count assertion."""
    selected_traces = {event.get("server_trace_id") for event in selected if event.get("action_name") == "toolsCall"}
    allowed_setup = {"work_on_project", "list_projects", "get_runtime_status", "read_tool_manifest"}
    entries = list(itertools.islice(root.iterdir(), MAX_CALLS + 2))
    if len(entries) > MAX_CALLS + 1:
        raise EvidenceUnavailable("capture_limit")
    for directory in entries:
        if directory.name == CAPTURE_MARKER:
            continue
        if str(uuid.UUID(directory.name)) != directory.name:
            raise EvidenceUnavailable("invalid_trace_identity")
        _private(directory, True)
        for line in _read(directory / "events.jsonl", MAX_INDEX_BYTES).splitlines():
            event = json.loads(line)
            if not isinstance(event, dict) or event.get("server_trace_id") != directory.name:
                raise EvidenceUnavailable("trace_identity_mismatch")
            if event.get("phase") == "kernel_arguments" and event.get("tool_name") not in allowed_setup:
                if directory.name not in selected_traces:
                    raise EvidenceUnavailable("unlinked_runtime_call")


def _audit_events(audit_db, workflow_session_id):
    connection = report._open_sqlite_readonly(Path(audit_db))
    deadline = time.monotonic() + 5
    try:
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
        rows = connection.execute(f"""
            SELECT DISTINCT {report._AUDIT_COLUMNS}
            FROM action_events e JOIN action_event_workflow_links l ON l.event_id=e.event_id
            WHERE l.workflow_session_id=? LIMIT ?
        """, (workflow_session_id, MAX_CALLS + 1)).fetchall()
        if len(rows) > MAX_CALLS:
            raise EvidenceUnavailable("capture_limit")
        return [report._row_to_audit_event(row) for row in rows]
    finally:
        connection.close()


def _command(call):
    args = call["arguments"]
    if call["tool"] == "run_script" and args.get("language") == "python":
        return args.get("script")
    if call["tool"] == "run_process" and isinstance(args.get("args"), list):
        argv = args["args"]
        executable = args.get("executable")
        if (isinstance(executable, str) and re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(executable).name)
                and len(argv) >= 2 and argv[:-1] in (["-c"], ["-u", "-c"])):
            return argv[-1]
    return None


def _matches_python_command(call, expected):
    actual = _command(call)
    if not isinstance(actual, str):
        return False
    try:
        # The Host may expand a one-line loop or change quoting. Match the exact
        # syntax tree, without executing it. Reject comments as well, including
        # encoding cookies that could change how the Runner reads UTF-8 bytes.
        if any(token.type == tokenize.COMMENT for token in tokenize.generate_tokens(io.StringIO(actual).readline)):
            return False
        return ast.dump(ast.parse(actual), include_attributes=False) == ast.dump(ast.parse(expected), include_attributes=False)
    except (SyntaxError, ValueError, RecursionError, tokenize.TokenError):
        return False


def _job(call):
    output = call["output"]
    if isinstance(output.get("job_id"), str):
        return output["job_id"]
    items = output.get("continuation", {}).get("arguments", {}).get("items", [])
    return items[0].get("job_id") if len(items) == 1 and isinstance(items[0], dict) else None


def _read_result(call):
    if call["tool"] != "read_files" or call["result"]["success"] is not True:
        return None
    items = call["output"].get("items", [])
    if len(items) != 1 or items[0].get("path") != "stale.txt":
        return None
    output = items[0].get("output", {})
    revision = output.get("read_revision")
    valid_revision = (type(revision) is int and revision > 0) or (isinstance(revision, str) and bool(revision))
    return (revision, output.get("text")) if valid_revision else None


def _exit_code(call):
    code = call["output"].get("exit_code")
    if type(code) is int:
        return code
    # result_projection.rs only omits these fields for established synchronous
    # terminal command success. Require its pre-projection canonical Audit fact;
    # a bare success flag (including pending admission) never implies exit zero.
    if ("exit_code" not in call["output"] and call["result"]["success"] is True
            and call.get("execution_state") == "completed"
            and not call["output"].get("continuation") and not _job(call)):
        return 0
    return None


def _bind_fixture(calls, fixture_root, workflow_session_id):
    relevant = [call for call in calls if call["tool"] not in
                {"work_on_project", "read_tool_manifest", "get_runtime_status", "list_projects"}]
    bootstraps = [call for call in calls if call["tool"] == "work_on_project"
                  and call["result"]["success"] is True]
    fixture_path = str(Path(fixture_root).absolute())
    rooted = [call for call in bootstraps if call["arguments"].get("path") == fixture_path
              and isinstance(call["arguments"].get("client_id"), str) and call["arguments"]["client_id"]]
    if not rooted or not relevant:
        raise EvidenceUnavailable("fixture_binding_unavailable")
    bootstrap = rooted[0]
    if bootstrap["arguments"].get("mode", "checkout") != "checkout":
        raise EvidenceUnavailable("fixture_binding_mismatch")
    output = bootstrap["output"]
    project = output.get("resolved_project")
    if (output.get("session_id") != workflow_session_id or not isinstance(project, str) or not project
            or bootstrap["ended"] > min(call["started"] for call in relevant)):
        raise EvidenceUnavailable("fixture_binding_mismatch")
    projects = {project}
    sessions = {workflow_session_id}
    initial_runner = bootstrap["arguments"]["client_id"]
    for call in bootstraps:
        # A later successful bootstrap cannot extend the allowed Project/Session
        # alias set by claiming a different fixture path or Runner identity,
        # even when its other returned fields happen to look identical.
        selectors = call["arguments"]
        if (selectors.get("path") not in (None, fixture_path)
                or selectors.get("client_id") not in (None, initial_runner)):
            raise EvidenceUnavailable("fixture_binding_mismatch")
        value = call["output"]
        context = value.get("execution_context") or {}
        if call["arguments"].get("mode", "checkout") != "checkout":
            raise EvidenceUnavailable("fixture_binding_mismatch")
        if (not isinstance(context, dict) or context.get("default_cwd") not in (None, "", ".")
                or context.get("resource") is not None):
            raise EvidenceUnavailable("fixture_binding_mismatch")
        if value.get("session_id") != workflow_session_id or value.get("resolved_project") != project:
            raise EvidenceUnavailable("fixture_binding_mismatch")
        if isinstance(value.get("project_ref"), str):
            projects.add(value["project_ref"])
        if isinstance(value.get("session_ref"), str):
            sessions.add(value["session_ref"])
    for call in relevant:
        args = call["arguments"]
        if (call["tool"] == "set_session_execution_context"
                or args.get("cwd") not in (None, "", ".")
                or call["output"].get("cwd") not in (None, "", ".", str(Path(fixture_root).absolute()))):
            raise EvidenceUnavailable("fixture_binding_mismatch")
        if call["tool"] == "transfer_project_artifact":
            # Transfers carry two explicit Project selectors, rather than the
            # ordinary single Project field. Both must bind to this fixture.
            if (args.get("source_project") not in projects or args.get("destination_project") not in projects
                    or call["project"] is not None and call["project"] not in projects):
                raise EvidenceUnavailable("project_mismatch")
            if call["result"]["success"] is True and (
                    call["output"].get("source_project") not in projects
                    or call["output"].get("destination_project") not in projects):
                raise EvidenceUnavailable("project_mismatch")
        elif call["project"] not in projects:
            raise EvidenceUnavailable("project_mismatch")
        if args.get("project") is not None and args["project"] not in projects:
            raise EvidenceUnavailable("project_mismatch")
        if args.get("session_id") is not None and args["session_id"] not in sessions:
            raise EvidenceUnavailable("fixture_binding_mismatch")
    return projects


def _applied_creates(call, expected):
    if (call["tool"] != "edit_project_files" or call["result"]["success"] is not True
            or call.get("edit_outcome") != "applied" or call["arguments"].get("dry_run", False) is not False):
        return False
    changes = call["arguments"].get("changes")
    if not isinstance(changes, list) or len(changes) != len(expected):
        return False
    found = {}
    for change in changes:
        if (not isinstance(change, dict) or set(change) != {"kind", "path", "content"}
                or change["kind"] != "create" or change["path"] in found):
            return False
        found[change["path"]] = change["content"]
    if set(found) != set(expected):
        return False
    for path, value in expected.items():
        if isinstance(value, dict):
            try:
                if json.loads(found[path]) != value:
                    return False
            except (TypeError, ValueError):
                return False
        elif found[path] != value:
            return False
    return True


def _controlled_mutation(calls, script, creates):
    candidates = [call for call in calls if call["tool"] in {"run_script", "run_process", "run_shell", "edit_project_files"}]
    matches = [call for call in candidates if _applied_creates(call, creates) or _matches_python_command(call, script)]
    if len(matches) != 1:
        raise EvidenceUnavailable("unsupported_case_command")
    value = matches[0]
    # Additional actual validation/read scripts are legitimate. Their purpose
    # annotation grants nothing: each must establish terminal success itself.
    for other in candidates:
        if other is value:
            continue
        if (other["tool"] == "edit_project_files" or other["result"]["success"] is not True
                or _exit_code(other) != 0):
            raise EvidenceUnavailable("unsupported_case_command")
    if _applied_creates(value, creates):
        return value
    if value["result"]["success"] is not True or _exit_code(value) != 0:
        return None
    return value


def _checks(case_id, calls):
    relevant = [call for call in calls if call["tool"] not in ("work_on_project", "read_tool_manifest", "get_runtime_status", "list_projects")]
    if not relevant:
        raise EvidenceUnavailable("project_mismatch")
    if case_id in TEMPORAL_CASES and (len({call["project"] for call in relevant}) != 1 or not relevant[0]["project"]):
        raise EvidenceUnavailable("project_mismatch")
    if case_id == "generic_mixed_files_conflict":
        transfers = [call for call in relevant if call["tool"] == "transfer_project_artifact"]
        expected = binary_fixtures()
        names = {call["arguments"].get("source_path") for call in transfers}
        valid = len(transfers) == len(expected) and names == {"input/" + name for name in expected}
        for call in transfers:
            args, output = call["arguments"], call["output"]
            name = args.get("source_path", "").removeprefix("input/")
            data = expected.get(name)
            valid = valid and (data is not None and call["result"]["success"] is True
                and args.get("destination_path") == "sorted/" + name
                and output.get("source_path") == args["source_path"]
                and output.get("destination_path") == args["destination_path"]
                and isinstance(output.get("source_project"), str)
                and isinstance(output.get("destination_project"), str)
                and type(output.get("bytes")) is int and output["bytes"] == len(data)
                and output.get("sha256") == hashlib.sha256(data).hexdigest())
        mutation = _controlled_mutation(relevant, mixed_note_script(), {"sorted/note-2.txt": "original note\n"})
        return {"binary_artifact_transfers": valid, "conflict_preserving_text_mutation": mutation is not None}
    if case_id == "generic_encoded_csv":
        expected_csv = "name,value\nAlice,2\nBob,3\n陈,5\n丁,7\n"
        mutation = _controlled_mutation(relevant, encoded_csv_script(),
            {"merged.csv": expected_csv, "report.json": {"count": 4, "total": 17}})
        finishes = [call for call in relevant if call["tool"] == "finish_coding_task"]
        if len(finishes) != 1 or "outputs" not in finishes[0]["arguments"]:
            raise EvidenceUnavailable("unsupported_case_command")
        finish = finishes[0]
        receipt = finish["output"].get("task_outputs", {})
        outcome = finish["output"].get("task_outcome")
        if (not isinstance(outcome, dict) or not {"status", "blocking", "blocking_reasons"} <= set(outcome)
                or outcome["status"] not in {"pass", "warn", "fail"}
                or type(outcome["blocking"]) is not bool or not isinstance(outcome["blocking_reasons"], list)):
            raise EvidenceUnavailable("unsupported_case_command")
        items = receipt.get("items", [])
        valid = (mutation is not None and mutation["ended"] <= finish["started"]
            # This canonical PureRead/project:read observer cannot mutate task
            # files. Keep it recorded and bound, including post-finish diagnosis.
            and all(call is finish or call["ended"] <= finish["started"]
                    or (call["tool"] == "check_workspace_hygiene" and finish["ended"] <= call["started"])
                    for call in relevant)
            and finish["result"]["success"] is True
            and outcome["status"] in {"pass", "warn"} and outcome["blocking"] is False
            and outcome["blocking_reasons"] == []
            and set(finish["arguments"].get("outputs", [])) == {"merged.csv", "report.json"}
            and len(finish["arguments"]["outputs"]) == 2
            and all(type(receipt.get(key)) is int for key in ("verified_count", "missing_count", "unavailable_count"))
            and receipt["verified_count"] == 2 and receipt["missing_count"] == 0
            and receipt["unavailable_count"] == 0 and len(items) == 2
            and {item.get("path") for item in items} == {"merged.csv", "report.json"}
            and all(item.get("status") == "verified" for item in items))
        return {"controlled_csv_conversion": mutation is not None, "verified_csv_output_receipts": valid}
    if case_id == "generic_failure_repair":
        commands = [call for call in relevant if call["tool"] in ("run_script", "run_process", "run_shell")]
        exact = len(commands) == 2 and all(_matches_python_command(call, expected)
            for call, expected in zip(commands, (pressure_script(), pressure_script(False))))
        return {"exact_failure_repair_commands": exact,
                "ordered_exit_7_then_0": exact and commands[0]["result"]["success"] is False
                    and _exit_code(commands[0]) == 7 and commands[1]["result"]["success"] is True
                    and _exit_code(commands[1]) == 0,
                "failure_diagnostic_and_sentinel": exact and "expected failure" in json.dumps(commands[0]["envelope"])
                    and all(SENTINEL in json.dumps(call["envelope"]) for call in commands)}
    if case_id == "generic_pending_independent_join":
        starts = [call for call in relevant if call["tool"] == "run_process"]
        joins = [call for call in relevant if call["tool"] == "wait_for_job_readiness"]
        releases = [call for call in relevant if call["tool"] == "write_job_input"]
        observes = [call for call in relevant if call["tool"] == "observe_jobs"]
        start = starts[0] if len(starts) == 1 else None
        job = _job(start) if start else None
        exact = bool(job and len(joins) == len(releases) == len(observes) == 1)
        if not exact:
            return {"one_original_job_and_join": False}
        release, join, observe = releases[0], joins[0], observes[0]
        independent = [call for call in relevant if start["ended"] <= call["started"] < release["started"]
                       and call["result"]["success"] and call["tool"] in ("run_script", "edit_project_files")]
        independent_script = "from pathlib import Path\nPath('independent.txt').write_text('independent work completed')\n"
        def writes_independent(call):
            if _matches_python_command(call, independent_script):
                return _exit_code(call) == 0
            return _applied_creates(call, {"independent.txt": "independent work completed"})
        observed = observe["output"].get("items", [])
        item = observed[0] if len(observed) == 1 else {}
        target = observe["arguments"].get("items", [])
        return {"one_original_job_and_join": exact and start["arguments"].get("interactive") is True
                    and _matches_python_command(start, PENDING_SCRIPT)
                    and start["output"].get("execution_state") == "pending",
                "independent_before_release": any(writes_independent(call) for call in independent),
                "same_job_release_join_terminal": release["arguments"].get("job_id") == job
                    and release["arguments"].get("close") is True and release["result"]["success"]
                    and join["arguments"].get("job_ids") == [job] and join["arguments"].get("mode") == "all"
                    and join["result"]["success"] and not join["output"].get("pending_job_ids")
                    and release["ended"] <= join["started"] and join["ended"] <= observe["started"]
                    and len(target) == 1 and target[0].get("job_id") == job
                    and item.get("job_id") == job and item.get("terminal") is True
                    and type(item.get("exit_code")) is int and item["exit_code"] == 0
                    and "controlled-job-complete" in json.dumps(item)}
    if case_id == "generic_stale_read_revision":
        reads = [(call, _read_result(call)) for call in relevant if _read_result(call) is not None]
        edits = [call for call in relevant if call["tool"] == "edit_project_files"]
        if len(reads) < 2 or len(edits) != 2:
            return {"stale_rejection_fresh_recovery": False}
        first, (revision, _) = reads[0]
        rejected, applied = edits
        fresh = [(call, value) for call, value in reads if rejected["ended"] <= call["started"] < applied["started"]]
        def edit_revision(call):
            changes = call["arguments"].get("changes", [])
            return changes[0].get("expected_read_revision") if len(changes) == 1 and changes[0].get("path") == "stale.txt" else None
        return {"stale_rejection_fresh_recovery": bool(fresh) and first["ended"] <= rejected["started"]
                    and rejected["result"]["success"] is False and edit_revision(rejected) == revision
                    and rejected["output"].get("error_kind") == "stale_file_revision"
                    and rejected["output"].get("state_changed") is False
                    and applied["result"]["success"] is True and applied.get("edit_outcome") == "applied"
                    and applied["arguments"].get("dry_run", False) is False
                    and edit_revision(applied) == fresh[-1][1][0]
                    and fresh[-1][1][0] != revision and EXTERNAL_SENTINEL in (fresh[-1][1][1] or "")}
    if case_id == "generic_missing_output":
        finishes = [call for call in relevant if call["tool"] == "finish_coding_task"]
        if len(finishes) != 1:
            return {"missing_output_blocks_finish": False}
        finish = finishes[0]
        outputs, outcome = finish["output"].get("task_outputs", {}), finish["output"].get("task_outcome", {})
        return {"missing_output_blocks_finish": finish["result"]["success"] is True
                and finish["arguments"].get("outputs") == ["missing-result.csv"]
                and type(outputs.get("missing_count")) is int and outputs["missing_count"] == 1
                and type(outputs.get("verified_count")) is int and outputs["verified_count"] == 0
                and outcome.get("status") == "fail" and outcome.get("blocking") is True
                and "task_outputs_unverified" in outcome.get("blocking_reasons", [])}
    raise EvidenceUnavailable("unsupported_case")


def verify(*, capture_root, audit_db, workflow_session_id, case_id, base_revision, fingerprint, fixture_root):
    """Return only bounded facts; input errors never expose filenames or payloads."""
    identity = None
    try:
        root = Path(capture_root)
        for parent in [root, *root.parents]:
            if parent.is_symlink():
                raise EvidenceUnavailable("unsafe_capture")
        _private(root, True)
        identity = fixture_identity(fixture_root)
        marker = json.loads(_read(root / CAPTURE_MARKER, 4096))
        if marker != {"case_id": case_id, "base_revision": base_revision, "case_fingerprint": fingerprint,
                      "fixture_identity": identity}:
            raise EvidenceUnavailable("capture_identity_mismatch")
        events = _audit_events(audit_db, workflow_session_id)
        if len(events) > MAX_CALLS:
            raise EvidenceUnavailable("capture_limit")
        _coverage(root, events)
        # The four temporal sequences require exact serial order. Independent
        # file transfers may overlap; CSV still requires all work before finish.
        calls = _calls(events, root, workflow_session_id, require_serial=case_id in TEMPORAL_CASES)
        _bind_fixture(calls, fixture_root, workflow_session_id)
        checks = {"fixture_root_session_project": True, **_checks(case_id, calls)}
        if case_id == "generic_encoded_csv":
            # The only filesystem reads in this verifier are bounded fixture
            # outputs, never arbitrary trace paths or operator-selected sources.
            from_fixture = GenericFixture(Path(fixture_root), case_id)
            hashes = {name: hashlib.sha256(from_fixture.read(name)).hexdigest()
                      for name in ("merged.csv", "report.json")}
            finish = next(call for call in calls if call["tool"] == "finish_coding_task")
            checks["verified_csv_output_receipts"] = checks["verified_csv_output_receipts"] and all(
                item.get("sha256") == hashes.get(item.get("path"))
                for item in finish["output"].get("task_outputs", {}).get("items", []))
        if fixture_identity(fixture_root) != identity:
            raise EvidenceUnavailable("fixture_identity_mismatch")
        return {"schema_version": PROOF_SCHEMA_VERSION, "fixture_identity": identity, "case_id": case_id, "base_revision": base_revision,
                "case_fingerprint": fingerprint, "available": True, "passed": all(checks.values()),
                "checks": checks, "reason": None}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, sqlite3.Error, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, EvidenceUnavailable) and str(error) in UNAVAILABLE_REASONS else "runtime_capture_unavailable"
        return {"schema_version": PROOF_SCHEMA_VERSION, "fixture_identity": identity, "case_id": case_id, "base_revision": base_revision,
                "case_fingerprint": fingerprint, "available": False, "passed": None,
                "checks": {}, "reason": reason}
