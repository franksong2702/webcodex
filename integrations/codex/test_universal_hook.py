import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import universal_hook as hook


class UniversalHookTests(unittest.TestCase):
    def test_missing_registration_stays_quiet_without_write_or_replay(self):
        with patch.object(hook, 'call_writer') as writer:
            for event in ['PostToolUse', 'Stop', 'UserPromptSubmit']:
                result = hook.dispatch({'cwd': str(self.root), 'session_id': 's',
                                        'hook_event_name': event}, Path('/writer'))
                self.assertEqual(result, {})
            guidance = hook.dispatch({'cwd': str(self.root), 'session_id': 's',
                                      'hook_event_name': 'SessionStart'}, Path('/writer'))
            self.assertIn('No handoff task discovered', str(guidance))
            self.assertIn('not additional authority', str(guidance))
            writer.assert_not_called()
            self.assertEqual(list(self.root.iterdir()), [])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def enable(self, root):
        (root / 'handoff').mkdir(parents=True)
        (root / 'handoff/index.json').write_text('{}')

    def test_unselected_project_does_not_call_writer(self):
        with patch.object(hook, 'call_writer') as writer:
            self.assertEqual(hook.dispatch({'cwd': str(self.root)}, Path('/fixed/writer')), {})
            writer.assert_not_called()

    def test_same_entry_discovers_two_independent_projects(self):
        for name in ['code', '中文笔记']:
            project = self.root / name
            self.enable(project)
            self.assertEqual(hook.discover({'cwd': str(project)}), project)

    def test_parent_opt_in_is_not_inherited(self):
        self.enable(self.root)
        child = self.root / 'other-worktree'
        child.mkdir()
        self.assertIsNone(hook.discover({'cwd': str(child)}))

    def test_symlink_cannot_redirect_checkpoint(self):
        target = self.root / 'target'
        self.enable(target)
        project = self.root / 'project'
        project.mkdir()
        (project / 'handoff').symlink_to(target / 'handoff')
        with self.assertRaisesRegex(hook.CheckpointError, 'symlink'):
            hook.discover({'cwd': str(project)})

    def test_unknown_result_stays_unknown_and_event_is_session_scoped(self):
        self.enable(self.root)
        calls = []
        deadlines = []
        def writer(binary, project, request, *, deadline):
            deadlines.append(deadline)
            self.assertEqual(project, self.root)
            calls.append(request)
            if request['action'] == 'status':
                return {'enabled': True, 'bound_task_id': 'a'}
            if request['action'] == 'read':
                return {'revision': 1}
            return {}
        payload = dict(cwd=str(self.root), session_id='s', hook_event_name='PostToolUse',
                       permission_mode='default', tool_use_id='t', tool_name='Bash',
                       tool_response='Process exited with code 0')
        with patch.object(hook, 'call_writer', side_effect=writer):
            hook.dispatch(payload, Path('/fixed/writer'))
        self.assertEqual(len(set(deadlines)), 1)
        self.assertEqual(calls[-1]['event']['status'], 'unknown')
        self.assertNotIn('Process exited', json.dumps(calls))

    def test_partial_or_stale_legacy_config_never_suppresses_capture(self):
        self.enable(self.root)
        config = self.root / '.codex'
        config.mkdir()
        for event in ['Stop', 'PostToolUse']:
            (config / 'hooks.json').write_text(json.dumps({'hooks': {event: [
                {'hooks': [{'type': 'command', 'command': '/python /missing/handoff_hook.py --project /other'}]}
            ]}}))
            calls = []
            def writer(binary, project, request, **kwargs):
                calls.append(request)
                return {'enabled': True, 'bound_task_id': 'a'} if request['action'] == 'status' else {'revision': 1}
            payload = dict(cwd=str(self.root), session_id='s', hook_event_name='PostToolUse',
                           permission_mode='default', tool_use_id='t', tool_name='Bash', tool_response={'exit_code': 0})
            with patch.object(hook, 'call_writer', side_effect=writer):
                hook.dispatch(payload, Path('/writer'))
                hook.dispatch(payload, Path('/writer'))
            facts = [r['event'] for r in calls if r['action'] == 'append']
            self.assertEqual(len(facts), 2)
            self.assertEqual(facts[0], facts[1])  # real writer deduplicates this exact ID/content
            self.assertEqual(facts[0]['status'], 'completed')

    def test_universal_entry_passes_source_probe_only_at_startup(self):
        self.enable(self.root)
        def writer(binary, project, request, **kwargs):
            return {'enabled': True, 'bound_task_id': 'a'} if request['action'] == 'status' else {'revision': 1}
        with patch.object(hook, 'call_writer', side_effect=writer), patch('source_status.probe', return_value={
                'status': 'pending', 'pending': 1, 'capture_gaps': 0}) as probe:
            result = hook.dispatch(dict(cwd=str(self.root), session_id='s', hook_event_name='SessionStart'),
                                   Path('/writer'), Path('/trusted-source.json'))
            self.assertIn('pending', str(result))
            self.assertEqual(probe.call_args.args[:3], (Path('/trusted-source.json'), self.root, 'a'))
            probe.assert_called_once()

    def test_git_subdirectory_uses_own_root(self):
        self.enable(self.root)
        (self.root / '.git').mkdir()
        sub = self.root / 'src' / 'nested'
        sub.mkdir(parents=True)
        self.assertEqual(hook.discover({'cwd': str(sub)}), self.root)

    def test_nested_repo_without_handoff_never_inherits(self):
        self.enable(self.root)
        (self.root / '.git').mkdir()
        nested = self.root / 'vendor'
        nested.mkdir()
        (nested / '.git').write_text('gitdir: /not-followed')
        child = nested / 'src'
        child.mkdir()
        self.assertIsNone(hook.discover({'cwd': str(child)}))

    def test_symlink_outside_repo_does_not_inherit(self):
        self.enable(self.root)
        (self.root / '.git').mkdir()
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'link').symlink_to(outside)
            self.assertIsNone(hook.discover({'cwd': str(self.root / 'link')}))

    def test_first_session_guidance_never_writes_or_asks_user_for_setup(self):
        with patch.object(hook, 'call_writer') as writer:
            result = hook.dispatch({'cwd': str(self.root), 'session_id': 's',
                                    'hook_event_name': 'SessionStart'}, Path('/writer'))
            self.assertIn('After the user confirms', str(result))
            self.assertIn('Do not ask the user to run setup commands', str(result))
            writer.assert_not_called()
            self.assertEqual(list(self.root.iterdir()), [])
