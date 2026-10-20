"""Small, local Git fixtures for knowledge and project Skill acceptance.

The oracle checks source integrity, not model answers or retrieval behavior.
No fixture instruction grants execution authority and no Skill script is used.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

CASE_IDS = (
    "knowledge_identifier", "knowledge_procedure", "knowledge_paraphrase",
    "knowledge_source_update", "knowledge_skill_read", "knowledge_skill_update",
)
MAX_FILES = 32
MAX_FILE_BYTES = 16 * 1024
MAX_TOTAL_BYTES = 128 * 1024
SKILL = ".agents/skills/receipt-audit/SKILL.md"
REFERENCE = ".agents/skills/receipt-audit/reference.md"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(info):
    return info.st_dev, info.st_ino


def _environment():
    # Do not inherit repository redirection, signing, hooks, or user configuration.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", LC_ALL="C",
               GIT_AUTHOR_DATE="2000-01-01T00:00:00Z", GIT_COMMITTER_DATE="2000-01-01T00:00:00Z")
    return env


class KnowledgeFixture:
    """Prepare once in an empty directory; update one admitted source once."""

    def __init__(self, root: Path, case_id: str):
        if case_id not in CASE_IDS:
            raise ValueError("unknown knowledge fixture case")
        self.root = Path(root).absolute()
        self.case_id = case_id
        self.advanced = False
        self._prepared = False
        self._root_identity = None
        self._git_identity = None
        self._head = None
        code = b'"""Receipt identifier constants."""\nRECEIPT_PREFIX = "RCPT-Q7"  # receipt-prefix=RCPT-Q7\nRECEIPT_WIDTH = 8  # receipt-width=8\n'
        ledger = b"# Receipt ledger retention\n\nledger-window=19 days\nledger-owner=Cedar Desk\n"
        ledger_next = b"# Receipt ledger retention\n\nledger-window=23 days\nledger-owner=Birch Desk\n"
        skill = (b"---\nname: receipt-audit\ndescription: Find receipt audit ordering and marker facts.\n---\n"
                 b"# Receipt audit\n\nUse for questions about receipt audit facts. Read reference.md for the marker and batch.\n"
                 b"audit-order=match then annotate\nReport the requested facts; this Skill does not request execution or edits.\n")
        reference = b"# Receipt audit reference\n\naudit-marker=amber-kite\naudit-batch=13 receipts\n"
        skill_next = skill.replace(b"audit-order=match then annotate", b"audit-order=annotate then match")
        files = {
            "README.md": b"# Receipt knowledge fixture\n\nA local, synthetic receipt project.\n",
            "src/receipt_policy.py": code,
            "src/receipts_policy.py": b'RECEIPT_PREFIX = "RCPT-D2"\nRECEIPT_WIDTH = 5\n',
            "docs/receipt-ledger.md": ledger,
            "docs/receipts-ledger.md": b"# Archived receipts ledger\nledger-window=7 days\nledger-owner=Elm Desk\n",
            "docs/receipt-procedure.md": b"# Historical receipt procedure\naudit-order=annotate then match\naudit-marker=gray-wren\naudit-batch=3 receipts\n",
            SKILL: skill,
            REFERENCE: reference,
            ".agents/skills/receipts-audit/SKILL.md": (
                b"---\nname: receipts-audit\ndescription: Historical plural receipts audit.\n---\n"
                b"audit-order=sort then stamp\naudit-marker=copper-owl\naudit-batch=5 receipts\n"),
        }
        self.source_versions = {path: (raw, raw) for path, raw in files.items()}
        if case_id == "knowledge_source_update":
            self.source_versions["docs/receipt-ledger.md"] = ledger, ledger_next
        elif case_id == "knowledge_skill_update":
            self.source_versions[SKILL] = skill, skill_next
        if case_id == "knowledge_identifier":
            self.required_sources = ("src/receipt_policy.py",)
        elif case_id in ("knowledge_paraphrase", "knowledge_source_update"):
            self.required_sources = ("docs/receipt-ledger.md",)
        else:
            self.required_sources = (SKILL, REFERENCE)

    def _git(self, *args):
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
             "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args],
            cwd=self.root, env=_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True,
        )
        if len(result.stdout) > MAX_TOTAL_BYTES or len(result.stderr) > MAX_TOTAL_BYTES:
            raise ValueError("fixture Git output exceeds bound")
        return result.stdout

    def prepare(self):
        if self._prepared:
            raise ValueError("fixture already prepared")
        # Reject symlink ancestors as well as a symlink root.
        for ancestor in (self.root, *self.root.parents):
            if ancestor.is_symlink():
                raise ValueError("fixture root has a symlink component")
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or any(self.root.iterdir()):
            raise ValueError("fixture root must be an empty directory")
        self._root_identity = _identity(self.root.stat())
        for path, (raw, _) in self.source_versions.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self._git("init", "--quiet", "--template=", "--initial-branch=fixture")
        self._git("add", "--", *sorted(self.source_versions))
        self._git("-c", "user.name=Knowledge Fixture", "-c", "user.email=fixture@example.invalid",
                  "commit", "--quiet", "-m", "Prepare synthetic knowledge fixture")
        self._git_identity = _identity((self.root / ".git").lstat())
        self._head = self._git("rev-parse", "HEAD").strip()
        self._prepared = True
        if not self.oracle()["passed"]:
            raise ValueError("prepared fixture failed its integrity oracle")
        return self

    def _open_root(self):
        if not self._prepared:
            raise ValueError("fixture has not been prepared")
        for ancestor in self.root.parents:
            if ancestor.is_symlink():
                raise ValueError("fixture root ancestor became a symlink")
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if _identity(os.fstat(fd)) != self._root_identity:
            os.close(fd)
            raise ValueError("fixture root identity changed")
        return fd

    def _inventory(self):
        files = {}
        directories = set()
        entries = 0
        total = 0

        def walk(directory, prefix=""):
            nonlocal entries, total
            for name in sorted(os.listdir(directory)):
                path = prefix + name
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if path == ".git":
                    if not stat.S_ISDIR(info.st_mode) or _identity(info) != self._git_identity:
                        raise ValueError("fixture Git directory identity changed")
                    continue
                entries += 1
                if entries > MAX_FILES * 2:
                    raise ValueError("fixture inventory exceeds entry bound")
                if stat.S_ISDIR(info.st_mode):
                    directories.add(path)
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    try:
                        if _identity(os.fstat(child)) != _identity(info):
                            raise ValueError("fixture directory changed during scan")
                        walk(child, path + "/")
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        raise ValueError("fixture source has multiple hard links")
                    if info.st_size > MAX_FILE_BYTES or len(files) >= MAX_FILES:
                        raise ValueError("fixture file exceeds bound")
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                    with os.fdopen(fd, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                                or _identity(opened) != _identity(info)):
                            raise ValueError("fixture file changed during scan")
                        raw = stream.read(MAX_FILE_BYTES + 1)
                        after = os.fstat(stream.fileno())
                        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns, opened.st_nlink) != (
                                after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink):
                            raise ValueError("fixture file changed during read")
                    total += len(raw)
                    if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        raise ValueError("fixture content exceeds bound")
                    files[path] = raw
                else:
                    raise ValueError("fixture contains a symlink or special file")

        fd = self._open_root()
        try:
            walk(fd)
        finally:
            os.close(fd)
        expected_directories = {str(parent) for path in self.source_versions
                                for parent in Path(path).parents if str(parent) != "."}
        if directories != expected_directories:
            raise ValueError("fixture directory inventory changed")
        return files

    def oracle(self):
        checks = []
        try:
            actual = self._inventory()
            expected = {path: versions[int(self.advanced)] for path, versions in self.source_versions.items()}
            checks.append({"name": "exact_inventory", "passed": set(actual) == set(expected)})
            checks.append({"name": "exact_source_bytes", "passed": actual == expected})
            tracked = set(self._git("ls-files", "-z").decode("utf-8").rstrip("\0").split("\0"))
            checks.append({"name": "git_tracked_sources", "passed": tracked == set(expected)})
            checks.append({"name": "git_head_unchanged", "passed": self._git("rev-parse", "HEAD").strip() == self._head})
            checks.append({"name": "git_index_unchanged", "passed": not self._git("diff", "--cached", "--name-only", "HEAD", "--")})
            fd = self._open_root()
            os.close(fd)
            passed = all(check["passed"] for check in checks)
            return {"available": True, "passed": passed, "checks": checks,
                    "reason": "fixture source integrity passed" if passed else "fixture inventory, bytes, or Git tracking changed"}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            checks.append({"name": "fixture_integrity", "passed": False})
            return {"available": True, "passed": False, "checks": checks,
                    "reason": f"fixture integrity rejected: {type(exc).__name__}"}

    def expected_facts(self) -> list[str]:
        if self.case_id == "knowledge_identifier":
            return ["receipt-prefix=RCPT-Q7", "receipt-width=8"]
        if self.case_id in ("knowledge_paraphrase", "knowledge_source_update"):
            return (["ledger-window=23 days", "ledger-owner=Birch Desk"] if self.advanced
                    else ["ledger-window=19 days", "ledger-owner=Cedar Desk"])
        return (["audit-order=annotate then match", "audit-marker=amber-kite", "audit-batch=13 receipts"]
                if self.advanced else ["audit-order=match then annotate", "audit-marker=amber-kite", "audit-batch=13 receipts"])

    def snapshot_sources(self, stage: int = 0):
        if type(stage) is not int or stage not in (0, 1):
            raise ValueError("source stage must be 0 or 1")
        if stage == 1 and self.case_id not in ("knowledge_source_update", "knowledge_skill_update"):
            raise ValueError("stage 1 is available only for update cases")
        result = []
        for path in self.required_sources:
            raw = self.source_versions[path][stage]
            result.append({"path": path, "start_line": 1, "end_line": len(raw.splitlines()),
                           "text": raw.decode("utf-8"), "source_hash": _sha(raw)})
        return result

    def sources(self):
        if not self.oracle()["passed"]:
            raise ValueError("fixture drift prevents source read")
        return self.snapshot_sources(int(self.advanced))

    def advance(self):
        if self.advanced:
            raise ValueError("fixture was already advanced")
        changes = [(path, old, new) for path, (old, new) in self.source_versions.items() if old != new]
        if len(changes) != 1:
            raise ValueError("only an update case can advance")
        if not self.oracle()["passed"]:
            raise ValueError("fixture drift prevents advance")
        path, old, new = changes[0]
        directory = self._open_root()
        try:
            parts = Path(path).parts
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "r+b") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or stream.read(MAX_FILE_BYTES + 1) != old):
                    raise ValueError("update source changed before write")
                stream.seek(0)
                stream.write(new)
                stream.truncate()
        finally:
            os.close(directory)
        self.advanced = True
        if not self.oracle()["passed"]:
            raise ValueError("fixture changed during advance")
        return {"path": path, "old_sha256": _sha(old), "new_sha256": _sha(new)}
