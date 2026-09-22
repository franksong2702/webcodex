import shlex
import unittest
from pathlib import Path
from generate_config import configuration, universal_configuration

class ConfigTests(unittest.TestCase):
    def test_exact_four_events_and_literal_paths(self):
        config=configuration(Path("/project with spaces"),Path("/binary with ' quote"),Path("/private source.json"))
        self.assertEqual(set(config),{"hooks"})
        self.assertEqual(set(config["hooks"]),{"SessionStart","UserPromptSubmit","PostToolUse","Stop"})
        for groups in config["hooks"].values():
            hook=groups[0]["hooks"][0]
            self.assertEqual(hook["timeout"],30)
            argv=shlex.split(hook["command"])
            self.assertEqual(argv[-6:],["--project","/project with spaces","--binary","/binary with ' quote","--source-config","/private source.json"])
    def test_relative_targets_rejected(self):
        with self.assertRaises(ValueError): configuration(Path("relative"),Path("/binary"))
        with self.assertRaises(ValueError): configuration(Path("/project"),Path("/binary"),Path("relative"))

    def test_universal_configuration_has_no_project_or_source_credentials(self):
        config = universal_configuration(Path("/fixed binary"))
        self.assertEqual(len(config["hooks"]), 4)
        for groups in config["hooks"].values():
            argv = shlex.split(groups[0]["hooks"][0]["command"])
            self.assertTrue(argv[1].endswith("universal_hook.py"))
            self.assertEqual(argv[2:], ["--binary", "/fixed binary"])
        with self.assertRaises(ValueError):
            universal_configuration(Path("relative"))

    def test_universal_source_uses_one_explicit_trusted_config(self):
        config = universal_configuration(Path('/binary'), Path('/trusted connection.json'))
        for groups in config['hooks'].values():
            argv = shlex.split(groups[0]['hooks'][0]['command'])
            self.assertEqual(argv[-2:], ['--source-config', '/trusted connection.json'])
            self.assertNotIn('--project', argv)
        with self.assertRaises(ValueError):
            universal_configuration(Path('/binary'), Path('relative'))
