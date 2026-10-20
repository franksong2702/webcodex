from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.agent_knowledge_fixture import CASE_IDS, KnowledgeFixture, REFERENCE, SKILL


class KnowledgeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def prepare(self, case="knowledge_identifier"):
        return KnowledgeFixture(self.base / "fixture", case).prepare()

    def test_six_cases_have_clean_tracked_sources_and_explicit_facts(self):
        self.assertEqual(CASE_IDS, (
            "knowledge_identifier", "knowledge_procedure", "knowledge_paraphrase",
            "knowledge_source_update", "knowledge_skill_read", "knowledge_skill_update"))
        for case in CASE_IDS:
            with self.subTest(case=case):
                fixture = KnowledgeFixture(self.base / case, case).prepare()
                self.assertTrue(fixture.oracle()["passed"])
                self.assertFalse(fixture.advanced)
                self.assertEqual(fixture._git("status", "--porcelain"), b"")
                self.assertEqual(set(fixture._git("ls-files", "-z").decode().strip("\0").split("\0")),
                                 set(fixture.source_versions))
                sources = fixture.sources()
                self.assertEqual([source["path"] for source in sources], list(fixture.required_sources))
                for source in sources:
                    self.assertEqual(source["start_line"], 1)
                    self.assertEqual(source["end_line"], len(source["text"].splitlines()))
                    self.assertEqual(len(source["source_hash"]), 64)
                text = "\n".join(source["text"] for source in sources)
                for fact in fixture.expected_facts():
                    self.assertIn(fact, text)

    def test_exact_near_names_and_skill_sources_are_distinguishable(self):
        fixture = self.prepare("knowledge_procedure")
        self.assertEqual(fixture.required_sources, (SKILL, REFERENCE))
        self.assertNotEqual((fixture.root / "src/receipt_policy.py").read_bytes(),
                            (fixture.root / "src/receipts_policy.py").read_bytes())
        for distractor in ("docs/receipt-procedure.md", ".agents/skills/receipts-audit/SKILL.md"):
            text = (fixture.root / distractor).read_text()
            self.assertFalse(any(fact in text for fact in fixture.expected_facts()))
        self.assertNotIn("scripts/", (fixture.root / SKILL).read_text())

    def test_updates_change_one_admitted_source_without_commit_and_independent_facts(self):
        for case, changed_path, new_fact in (
            ("knowledge_source_update", "docs/receipt-ledger.md", "ledger-window=23 days"),
            ("knowledge_skill_update", SKILL, "audit-order=annotate then match"),
        ):
            with self.subTest(case=case):
                fixture = KnowledgeFixture(self.base / case, case).prepare()
                before = {path: (fixture.root / path).read_bytes() for path in fixture.source_versions}
                old_facts = fixture.expected_facts()
                initial = fixture.snapshot_sources(0)
                changed = fixture.snapshot_sources(1)
                head = fixture._git("rev-parse", "HEAD")
                result = fixture.advance()
                self.assertTrue(fixture.advanced)
                self.assertEqual(result["path"], changed_path)
                self.assertNotEqual(result["old_sha256"], result["new_sha256"])
                self.assertEqual(fixture._git("rev-parse", "HEAD"), head)
                self.assertEqual(fixture._git("diff", "--name-only").decode().strip(), changed_path)
                self.assertEqual([path for path in before if before[path] != (fixture.root / path).read_bytes()],
                                 [changed_path])
                self.assertTrue(fixture.oracle()["passed"])
                self.assertEqual(fixture.sources(), changed)
                self.assertEqual(fixture.snapshot_sources(0), initial)
                self.assertNotEqual(old_facts, fixture.expected_facts())
                self.assertIn(new_fact, fixture.expected_facts())
                current = "\n".join(source["text"] for source in fixture.sources())
                for fact in fixture.expected_facts():
                    self.assertIn(fact, current)
                for fact in set(old_facts) - set(fixture.expected_facts()):
                    self.assertNotIn(fact, current)
                with self.assertRaises(ValueError):
                    fixture.advance()

    def test_non_update_cannot_advance_or_request_stage_one(self):
        fixture = self.prepare()
        with self.assertRaises(ValueError):
            fixture.advance()
        for stage in (1, -1, 2, True, "0"):
            with self.assertRaises(ValueError):
                fixture.snapshot_sources(stage)
        self.assertTrue(fixture.oracle()["passed"])

    def test_source_drift_untracked_file_and_empty_directory_fail_closed(self):
        for kind in ("source", "untracked", "directory", "oversize"):
            with self.subTest(kind=kind):
                fixture = KnowledgeFixture(self.base / kind, "knowledge_source_update").prepare()
                if kind == "source":
                    (fixture.root / "docs/receipt-ledger.md").write_text("stale facts\n")
                elif kind == "untracked":
                    (fixture.root / "extra.txt").write_text("unauthorized\n")
                elif kind == "directory":
                    (fixture.root / "empty").mkdir()
                else:
                    (fixture.root / "extra.txt").write_bytes(b"x" * 20000)
                self.assertFalse(fixture.oracle()["passed"])
                with self.assertRaises(ValueError):
                    fixture.advance()
                with self.assertRaises(ValueError):
                    fixture.sources()

    def test_untracking_or_staging_changes_fails_oracle(self):
        fixture = self.prepare("knowledge_source_update")
        fixture._git("update-index", "--force-remove", "docs/receipt-ledger.md")
        self.assertFalse(fixture.oracle()["passed"])

    def test_symlink_file_and_directory_rejected_without_reading_target(self):
        fixture = self.prepare("knowledge_source_update")
        external = self.base / "external"
        external.write_text("external unchanged\n")
        source = fixture.root / "docs/receipt-ledger.md"
        source.unlink()
        source.symlink_to(external)
        self.assertFalse(fixture.oracle()["passed"])
        with self.assertRaises(ValueError):
            fixture.advance()
        self.assertEqual(external.read_text(), "external unchanged\n")
        source.unlink()
        source.write_bytes(fixture.source_versions["docs/receipt-ledger.md"][0])
        (fixture.root / "linked").symlink_to(self.base, target_is_directory=True)
        self.assertFalse(fixture.oracle()["passed"])

    def test_root_replacement_and_symlink_root_cannot_retarget_advance(self):
        fixture = self.prepare("knowledge_source_update")
        old = self.base / "old"
        fixture.root.rename(old)
        fixture.root.mkdir()
        (fixture.root / "sentinel").write_text("replacement\n")
        self.assertFalse(fixture.oracle()["passed"])
        with self.assertRaises(ValueError):
            fixture.advance()
        self.assertEqual((fixture.root / "sentinel").read_text(), "replacement\n")
        with self.assertRaises(ValueError):
            KnowledgeFixture(self.base / "bad", "invalid")
        link = self.base / "link"
        link.symlink_to(old, target_is_directory=True)
        with self.assertRaises(ValueError):
            KnowledgeFixture(link, "knowledge_identifier").prepare()

    def test_source_race_after_oracle_cannot_overwrite_changed_source(self):
        fixture = self.prepare("knowledge_source_update")
        original_oracle = fixture.oracle
        source = fixture.root / "docs/receipt-ledger.md"

        def race():
            result = original_oracle()
            source.write_text("raced source\n")
            return result

        with mock.patch.object(fixture, "oracle", side_effect=race):
            with self.assertRaises(ValueError):
                fixture.advance()
        self.assertFalse(fixture.advanced)
        self.assertEqual(source.read_text(), "raced source\n")

    def test_root_race_after_oracle_cannot_write_replacement(self):
        fixture = self.prepare("knowledge_source_update")
        original_oracle = fixture.oracle

        def race():
            result = original_oracle()
            fixture.root.rename(self.base / "moved")
            fixture.root.mkdir()
            return result

        with mock.patch.object(fixture, "oracle", side_effect=race):
            with self.assertRaises(ValueError):
                fixture.advance()
        self.assertEqual(list(fixture.root.iterdir()), [])

    def test_symlink_race_after_oracle_cannot_write_external_source(self):
        fixture = self.prepare("knowledge_source_update")
        original_oracle = fixture.oracle
        source = fixture.root / "docs/receipt-ledger.md"
        external = self.base / "external"
        external.write_bytes(source.read_bytes())
        before = external.read_bytes()

        def race():
            result = original_oracle()
            source.unlink()
            source.symlink_to(external)
            return result

        with mock.patch.object(fixture, "oracle", side_effect=race):
            with self.assertRaises((OSError, ValueError)):
                fixture.advance()
        self.assertFalse(fixture.advanced)
        self.assertEqual(external.read_bytes(), before)

    def test_hardlink_source_and_race_cannot_write_external_source(self):
        fixture = self.prepare("knowledge_source_update")
        source = fixture.root / "docs/receipt-ledger.md"
        external = self.base / "external"
        external.write_bytes(source.read_bytes())
        before = external.read_bytes()
        original_oracle = fixture.oracle

        def race():
            result = original_oracle()
            source.unlink()
            os.link(external, source)
            return result

        with mock.patch.object(fixture, "oracle", side_effect=race):
            with self.assertRaises(ValueError):
                fixture.advance()
        self.assertFalse(fixture.advanced)
        self.assertEqual(external.read_bytes(), before)
        self.assertFalse(fixture.oracle()["passed"])

    def test_preparation_has_deterministic_bytes_and_commit(self):
        first = self.prepare("knowledge_identifier")
        second = KnowledgeFixture(self.base / "second", "knowledge_identifier").prepare()
        self.assertEqual(first.source_versions, second.source_versions)
        self.assertEqual(first._git("rev-parse", "HEAD"), second._git("rev-parse", "HEAD"))

    def test_prepare_rejects_existing_content_and_inherited_git_redirect(self):
        target = self.base / "fixture"
        target.mkdir()
        sentinel = target / "sentinel"
        sentinel.write_text("preserve\n")
        with self.assertRaises(ValueError):
            KnowledgeFixture(target, "knowledge_identifier").prepare()
        self.assertEqual(sentinel.read_text(), "preserve\n")
        external = self.base / "redirect"
        with mock.patch.dict(os.environ, {"GIT_DIR": str(external), "GIT_WORK_TREE": str(self.base),
                                          "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name",
                                          "GIT_CONFIG_VALUE_0": "unwanted"}):
            fixture = KnowledgeFixture(self.base / "clean", "knowledge_identifier").prepare()
        self.assertFalse(external.exists())
        self.assertTrue(fixture.oracle()["passed"])
        self.assertEqual(fixture._git("show", "-s", "--format=%an"), b"Knowledge Fixture\n")
        with self.assertRaises(ValueError):
            fixture.prepare()


if __name__ == "__main__":
    unittest.main()
