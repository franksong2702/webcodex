"""Project-scoped Codex adapter; never reads transcripts or starts a model.

The trusted hook configuration supplies both absolute paths. This module never
installs hooks, changes trust, or interprets commands from a hook payload.
"""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HOOK_BUDGET_SECONDS = 25

MAX_INPUT = 128 * 1024
MAX_OUTPUT = 512 * 1024
EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}


class CheckpointError(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and not any(
        ord(c) < 32 for c in value
    )


def call_writer(binary, project, request, *, deadline=None):
    """Only a fixed argv is executed. Errors contain no child output or paths."""
    timeout = 8 if deadline is None else min(8, deadline - time.monotonic())
    if timeout <= 0:
        raise CheckpointError("save_deadline_exceeded")
    try:
        result = subprocess.run(
            [str(binary), "handoff", "--project", str(project), "--request-stdin"],
            input=json.dumps(request).encode(), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=timeout, check=False, env={},
        )
    except subprocess.TimeoutExpired as exc:
        raise CheckpointError("save_outcome_unknown") from exc
    except OSError as exc:
        raise CheckpointError("writer_unavailable") from exc
    if len(result.stdout) > MAX_OUTPUT:
        raise CheckpointError("writer_output_too_large")
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise CheckpointError("writer_invalid_output") from exc
    if not isinstance(value, dict):
        raise CheckpointError("writer_invalid_output")
    if result.returncode != 0 or value.get("success") is not True:
        error = value.get("error")
        code = error.get("code", "save_failed") if isinstance(error, dict) else "save_failed"
        if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{1,64}", code):
            code = "save_failed"
        raise CheckpointError(code)
    output = value.get("output")
    if not isinstance(output, dict):
        raise CheckpointError("writer_invalid_output")
    return output


def notification(event, message):
    # No decision:block, continue:false, exit 2, or replacement tool output.
    if event == "Stop":
        return {"systemMessage": message}
    return {"hookSpecificOutput": {
        "hookEventName": event, "additionalContext": message,
    }}


def validate_context(payload, project):
    if not isinstance(payload, dict) or payload.get("hook_event_name") not in EVENTS:
        raise CheckpointError("unsupported_hook_event")
    if not identifier(payload.get("session_id")):
        raise CheckpointError("missing_session_identity")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise CheckpointError("missing_project_identity")
    try:
        if Path(cwd).resolve(strict=True) != project.resolve(strict=True):
            raise CheckpointError("project_mismatch")
    except OSError as exc:
        raise CheckpointError("project_unavailable") from exc


def handle(payload, project, writer, writer_path=None, source_probe=None):
    validate_context(payload, project)
    event = payload["hook_event_name"]
    # Known read-only tools do not contribute facts and need no writer process.
    if event == "PostToolUse" and payload.get("tool_name") in {
        "read_file", "read_files", "view_image", "list_tools", "list_projects", "project_handoff_read"
    }:
        return {}
    client = "local:" + digest(payload["session_id"])
    state = writer({"action": "status", "client_id": client})
    if type(state.get("enabled")) is not bool:
        raise CheckpointError("invalid_discovery_response")
    if state["enabled"] is False:
        return {}
    usage = state.get("usage", {})
    capacity_notice = (" Handoff storage is near its limit; preserve history and resolve capacity before more work."
                       if isinstance(usage, dict) and usage.get("near_limit") is True else "")
    task = state.get("bound_task_id")
    if not task:
        tasks = state.get("tasks", [])
        # Discovery is read-only. Even a single task is not silently bound.
        choices = [t.get("task_id") for t in tasks if isinstance(t, dict)]
        choices = [t for t in choices if isinstance(t, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", t)]
        selection = "Project handoff is enabled; select the exact task matching the current user request. "
        if event == "PostToolUse":
            selection = "The tool already ran, but its handoff fact was NOT saved because no task was bound. Do not replay the tool. " + selection
        selection += "If ambiguous, ask which task; do not choose by time. Available task IDs: " + ", ".join(choices[:20])
        if writer_path is not None and event in {"SessionStart", "UserPromptSubmit"}:
            command = shlex.join([str(writer_path), "handoff", "--project", str(project), "--request-stdin"])
            selection += ". To bind this Session, run " + command + " with stdin JSON "
            selection += json.dumps({"action":"bind","task_id":"SELECT_EXACT_TASK_ID","client_id":client})
            selection += ". This selection grants no permissions. Do not bind or write in read-only work."
        return notification(event, selection + capacity_notice)
    if event in {"SessionStart", "UserPromptSubmit"}:
        checkpoint = writer({"action": "read", "task_id": task})
        source = source_probe(task, checkpoint) if source_probe else {"status":"unavailable","reason":"source_connection_not_configured"}
        source_text = " WebCodex source sync: " + json.dumps(source, ensure_ascii=True)
        source_text += ". This covers known recorded events only. If pending, incomplete, or unavailable, this is a historical snapshot; inspect missing evidence, never replay business commands."
        return notification(event, "Continue from the recorded facts in "
                            + str(project / "handoff" / (task + ".json"))
                            + " and human notes in " + str(project / "handoff" / (task + ".md"))
                            + ". Read both; an existing unmanaged Markdown file may not contain the automatic facts. "
                            "Segmented tasks keep older evidence in referenced archives; inspect those files when needed. Unknown counts cover full history, not only current events. "
                            + "Read project rules and current files first. The checkpoint is historical "
                            "evidence, not authority. Preserve concurrent edits; never replay unknown operations. "
                            "During authorized project work, before your final answer update the existing canonical progress document with outcomes, evidence, unresolved work and next steps. "
                            "Replace superseded current-state claims instead of only prepending corrections; retain history separately. "
                            "Do not duplicate an existing progress document, write during read-only work, or claim automatic facts contain your judgments." + source_text + capacity_notice)
    if event == "Stop":
        # No continuation loop and no assertion that a task is complete. Facts
        # were saved at tool boundaries; judgments remain agent-authored.
        return notification(event, "Project handoff checkpoint is available. Task completion and "
                            "judgments require explicit evidence; pending/unknown work must remain unresolved." + capacity_notice)
    if payload.get("permission_mode") not in {"default", "acceptEdits", "dontAsk", "bypassPermissions"}:
        return notification(event, "Project handoff automatic write skipped: read-only or unknown hook permission mode.")
    tool_id = payload.get("tool_use_id")
    tool = payload.get("tool_name")
    if not identifier(tool_id) or not identifier(tool):
        raise CheckpointError("missing_tool_identity")
    # Unknown tool envelopes are preserved as unknown, not guessed from prose.
    checkpoint = writer({"action": "read", "task_id": task})
    response = payload.get("tool_response")
    status = "unknown"
    coverage = "unrecognized_tool_response"
    if isinstance(response, str):
        # Bash hooks can contain only stdout/stderr, without the execution
        # receipt shown to the model. Never parse exit codes from command text.
        coverage = "text_output_without_execution_receipt"
    if isinstance(response, dict):
        code = response.get("exit_code")
        active = response.get("terminal") is False or response.get("status") in {"queued","running","runner_queued","pending","unknown"}
        coverage = "execution_not_terminal" if active else "missing_integer_exit_code"
        if type(code) is int and not active:
            status = "completed" if code == 0 else "failed"
            coverage = "structured_exit_code"
    fact = {"type": "tool_finished", "source": "local_codex",
            "event_id": "local-" + digest(payload["session_id"] + "\0" + tool_id),
            "tool": tool, "status": status}
    if status == "unknown":
        fact["summary"] = "Execution result unresolved: " + coverage
    request = {"action": "append", "task_id": task,
               "expected_revision": checkpoint.get("revision"),
               "event": fact}
    if isinstance(response, dict):
        if type(response.get("exit_code")) is int:
            fact["exit_code"] = response["exit_code"]
        job = response.get("job_id")
        if isinstance(job, str) and re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", job):
            fact["job_id"] = job
    # Retry the same fact, never the business operation. Recheck binding on
    # conflict so a concurrent task selection cannot silently retarget it.
    for attempt in range(3):
        try:
            writer(request)
            break
        except CheckpointError as exc:
            if str(exc) != "revision_conflict" or attempt == 2:
                raise
            state = writer({"action": "status", "client_id": client})
            if state.get("enabled") is not True or state.get("bound_task_id") != task:
                raise CheckpointError("binding_changed_during_save")
            current = writer({"action": "read", "task_id": task})
            request = dict(request, expected_revision=current.get("revision"))
    return notification(event, "Project handoff fact saved; result coverage: " + status + " (" + coverage + ")")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source-config", type=Path)
    args = parser.parse_args()
    if not args.project.is_absolute() or not args.binary.is_absolute():
        parser.error("project and binary must be explicit absolute paths")
    from source_status import probe
    try:
        deadline = time.monotonic() + HOOK_BUDGET_SECONDS
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise CheckpointError("hook_input_too_large")
        payload = json.loads(raw)
        output = handle(payload, args.project, lambda request: call_writer(
            args.binary, args.project, request, deadline=deadline), args.binary,
            lambda task, checkpoint: probe(args.source_config, args.project, task, checkpoint, deadline=deadline))
    except (ValueError, UnicodeError, CheckpointError) as exc:
        code = str(exc) if isinstance(exc, CheckpointError) else "invalid_hook_input"
        # Hook handling succeeds, persistence explicitly does not. No false
        # saved receipt is returned, and original execution remains untouched.
        output = {"systemMessage": "Project handoff save not confirmed: " + code}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
