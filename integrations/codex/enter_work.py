"""Agent-operated local entry after user confirmation; no implicit permissions.

Discovery is read-only. Confirmation is supplied by the calling agent, not
inferred from chat titles or claimed to be a security/approval boundary.
"""
import argparse
import json
import sys
from pathlib import Path
from handoff_hook import CheckpointError, call_writer, digest, identifier

DOC_ENTRIES = ('AGENTS.md', '.agent-context/HANDOFF.md', 'docs/10-current-baseline.md',
               'docs/05-current-iteration.md', 'README.md')


def enter(project, session, objective, writer, *, confirmed=False, task_id=None, related=(), new_task=False):
    if not project.is_absolute() or not project.is_dir() or not identifier(session):
        raise CheckpointError('invalid_work_identity')
    project = project.resolve(strict=True)
    if not isinstance(objective, str) or not 0 < len(objective.strip()) <= 256:
        raise CheckpointError('invalid_work_objective')
    if len(related) > 8 or any(not Path(p).is_absolute() for p in related):
        raise CheckpointError('invalid_related_locations')
    client = 'local:' + digest(session)
    state = writer({'action': 'status', 'client_id': client})
    if type(state.get('enabled')) is not bool:
        raise CheckpointError('invalid_discovery_response')
    entries = [str(project / p) for p in DOC_ENTRIES if (project / p).is_file()]
    if not confirmed:
        return {'status': 'awaiting_project_and_objective_confirmation',
                'project': str(project), 'tasks': state.get('tasks', []),
                'document_entries': entries, 'writes': False}
    if not state['enabled'] and (project / 'handoff/index.json').exists():
        raise CheckpointError('handoff_disabled')
    bound = state.get('bound_task_id')
    if new_task and (task_id or bound):
        raise CheckpointError('binding_conflict')
    if task_id is None and bound:
        return {'status': 'existing_binding_requires_intent_check', 'task_id': bound,
                'checkpoint': writer({'action': 'read', 'task_id': bound}), 'writes': False}
    if task_id is None and state.get('tasks') and not new_task:
        return {'status': 'agent_task_selection_required', 'tasks': state['tasks'],
                'hint': 'Match the user objective; do not choose by recency. Ask only when ambiguous.',
                'writes': False}
    if task_id:
        if bound and bound != task_id:
            raise CheckpointError('binding_conflict')
        checkpoint = writer({'action': 'read', 'task_id': task_id})
        writer({'action': 'bind', 'task_id': task_id, 'client_id': client})
        return {'status': 'bound', 'task_id': task_id, 'checkpoint': checkpoint,
                'document_entries': entries}
    task_id = 'work-' + digest(session + '\0' + objective)[:24]
    refs = entries + [str(Path(p)) for p in related]
    summary = 'Confirmed work objective: ' + objective
    if refs:
        summary += ' Reference locations (not permission grants or current-state proof): ' + json.dumps(refs, ensure_ascii=False)
    if len(summary) > 4096:
        raise CheckpointError('references_too_large')
    writer({'action': 'create', 'task_id': task_id, 'title': objective,
            'binding': {'task_id': task_id, 'client_id': client},
            'event': {'type': 'note_added', 'source': 'local_codex',
                      'event_id': 'entry-' + digest(session + '\0' + objective),
                      'summary': summary}})
    return {'status': 'bound', 'task_id': task_id,
            'checkpoint': writer({'action': 'read', 'task_id': task_id}),
            'document_entries': entries}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--session', required=True)
    p.add_argument('--objective', required=True)
    p.add_argument('--confirmed', action='store_true')
    selection = p.add_mutually_exclusive_group()
    selection.add_argument('--task-id')
    selection.add_argument('--new-task', action='store_true')
    p.add_argument('--related', action='append', default=[])
    args = p.parse_args()
    if not args.binary.is_absolute():
        p.error('binary must be absolute')
    try:
        result = enter(args.project, args.session, args.objective,
                       lambda req: call_writer(args.binary, args.project, req),
                       confirmed=args.confirmed, task_id=args.task_id, related=args.related, new_task=args.new_task)
        print(json.dumps(result, ensure_ascii=False))
    except (CheckpointError, OSError) as exc:
        print(json.dumps({'status': 'not_confirmed', 'error': str(exc) if isinstance(exc, CheckpointError) else 'filesystem_unavailable'}))
        sys.exit(1)


if __name__ == '__main__':
    main()
