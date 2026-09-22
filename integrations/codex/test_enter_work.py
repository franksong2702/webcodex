import tempfile
import unittest
from pathlib import Path
from enter_work import enter
from handoff_hook import CheckpointError


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.calls = []
        self.state = {'enabled': False, 'tasks': []}

    def writer(self, request):
        self.calls.append(request)
        return self.state if request['action'] == 'status' else {'revision': 1}

    def test_discovery_never_creates_files(self):
        out = enter(self.root, 's', '研究', self.writer)
        self.assertFalse(out['writes'])
        self.assertEqual([r['action'] for r in self.calls], ['status'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_confirmed_creation_binds_in_same_request_and_references_existing_docs(self):
        doc = self.root / 'AGENTS.md'
        doc.write_text('Keep existing rules')
        enter(self.root, 's', '修复', self.writer, confirmed=True)
        create = self.calls[1]
        self.assertEqual(create['binding']['task_id'], create['task_id'])
        self.assertIn(str(doc), create['event']['summary'])
        self.assertNotIn('Keep existing rules', create['event']['summary'])
        self.assertEqual(doc.read_text(), 'Keep existing rules')

    def test_even_single_existing_task_requires_intent_match(self):
        self.state = {'enabled': True, 'tasks': [{'task_id': 'other-work'}]}
        out = enter(self.root, 's', 'new objective', self.writer, confirmed=True)
        self.assertEqual(out['status'], 'agent_task_selection_required')
        self.assertEqual(len(self.calls), 1)

    def test_existing_binding_not_retargeted(self):
        self.state = {'enabled': True, 'bound_task_id': 'old'}
        with self.assertRaisesRegex(CheckpointError, 'binding_conflict'):
            enter(self.root, 's', 'new', self.writer, confirmed=True, task_id='new')
        self.assertEqual(len(self.calls), 1)

    def test_disabled_not_reenabled(self):
        (self.root / 'handoff').mkdir()
        (self.root / 'handoff/index.json').write_text('{}')
        with self.assertRaisesRegex(CheckpointError, 'handoff_disabled'):
            enter(self.root, 's', 'new', self.writer, confirmed=True)
        self.assertEqual(len(self.calls), 1)

    def test_explicit_new_work_does_not_pick_an_old_task(self):
        self.state = {'enabled': True, 'tasks': [{'task_id': 'old'}]}
        enter(self.root, 'new-session', 'different task', self.writer, confirmed=True, new_task=True)
        self.assertEqual(self.calls[1]['action'], 'create')
        self.assertNotEqual(self.calls[1]['task_id'], 'old')
