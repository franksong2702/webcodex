"""One user-level hook entry; project state opts in, never supplies executable code."""
import argparse
import json
import time
import sys
import shlex
from pathlib import Path
from handoff_hook import HOOK_BUDGET_SECONDS, MAX_INPUT, CheckpointError, call_writer, handle, notification, identifier


def discover(payload):
    if not isinstance(payload, dict):
        raise CheckpointError('invalid_hook_input')
    cwd = payload.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise CheckpointError('missing_project_identity')
    current = Path(cwd).resolve(strict=True)
    if not current.is_dir():
        raise CheckpointError('project_unavailable')
    # The nearest Git boundary owns a subdirectory. Never cross an unselected
    # nested repo/worktree to inherit a parent task. Non-Git notes use exact cwd.
    project = current
    for candidate in (current, *current.parents):
        marker = candidate / '.git'
        if marker.exists() or marker.is_symlink():
            project = candidate
            break
    directory = project / 'handoff'
    index = directory / 'index.json'
    if directory.is_symlink() or index.is_symlink():
        raise CheckpointError('checkpoint_symlink_rejected')
    return project if index.is_file() else None


def dispatch(payload, binary, source_config=None):
    deadline = time.monotonic() + HOOK_BUDGET_SECONDS
    project = discover(payload)
    if project is None:
        event = payload.get('hook_event_name')
        if event not in {'SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop'} or not identifier(payload.get('session_id')):
            return {}
        # No task opted in: ordinary tools/prompts need no repeated checkpoint
        # warning. Capture errors for an enabled task still use handle().
        if event != 'SessionStart':
            return {}
        command = shlex.join([sys.executable, str(Path(__file__).with_name('enter_work.py')),
                              '--binary', str(binary), '--project', str(Path(payload['cwd']).resolve()),
                              '--session', payload['session_id']])
        return notification(event, 'No handoff task discovered at this working location. Explore with authorized read tools first; do not create a task just because a folder was read. After the user confirms the exact project and objective, the agent may use ' + command +
                            ' with --objective <confirmed goal> (read-only discovery), then --confirmed only when checkpoint writing is authorized. Replace --project with the confirmed canonical root if discovery began elsewhere. Do not ask the user to run setup commands. Existing tasks require intent matching; only ambiguous choices need a question. This is guidance, not additional authority.')
    # Config presence is not proof that another Hook runs. Both adapters use
    # the same session/tool event ID; the writer owns atomic deduplication.
    # Discovery validated the real session directory before root normalization.
    normalized = dict(payload, cwd=str(project))
    from source_status import probe
    return handle(normalized, project,
                  lambda request: call_writer(binary, project, request, deadline=deadline), binary,
                  lambda task, checkpoint: probe(source_config, project, task, checkpoint, deadline=deadline))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--source-config', type=Path)
    args = parser.parse_args()
    if args.source_config is not None and not args.source_config.is_absolute():
        parser.error('source configuration must be absolute')
    if not args.binary.is_absolute():
        parser.error('binary must be absolute')
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise CheckpointError('hook_input_too_large')
        output = dispatch(json.loads(raw), args.binary, args.source_config)
    except (ValueError, UnicodeError, OSError, CheckpointError) as exc:
        code = str(exc) if isinstance(exc, CheckpointError) else 'invalid_or_unavailable_context'
        output = {'systemMessage': 'Project handoff save not confirmed: ' + code}
    print(json.dumps(output))


if __name__ == '__main__':
    main()
