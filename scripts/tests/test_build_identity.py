"""Exercise Cargo invalidation against disposable Git metadata, without dependencies."""

import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "crates/webcodex-build-info/build.rs"


class BuildIdentityTests(unittest.TestCase):
    def install_observed_build_script(self, package):
        # Instrument only the disposable fixture. Run the shipped collector
        # unchanged, then record execution in the documented OUT_DIR workspace.
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(source.count("fn main() {"), 1)
        source = source.replace("fn main() {", "fn collect_build_identity() {", 1)
        source += r'''
fn main() {
    collect_build_identity();
    let marker = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap())
        .join("fixture-build-executions");
    let previous = std::fs::read_to_string(&marker)
        .map(|value| value.parse::<u64>().unwrap())
        .unwrap_or(0);
    std::fs::write(marker, (previous + 1).to_string()).unwrap();
}
'''
        (package / "build.rs").write_text(source, encoding="utf-8")

    @staticmethod
    def marker_state(output):
        return int(output.read_text(encoding="utf-8")), output.stat().st_mtime_ns

    def build_fixture(self, run, package):
        # Cargo's build-directory package spelling is not a stable interface.
        # Resolve the one dependency-free fixture from its structured messages.
        messages = run(package, "cargo", "build", "--offline", "--quiet", "--message-format=json")
        events = [json.loads(line) for line in messages.splitlines()]
        scripts = [event for event in events if event.get("reason") == "build-script-executed"]
        binaries = [event for event in events if event.get("reason") == "compiler-artifact"
                    and event.get("executable")]
        self.assertEqual(len(scripts), 1, scripts)
        self.assertEqual(len(binaries), 1, binaries)
        self.assertEqual(scripts[0]["package_id"], binaries[0]["package_id"])
        output = Path(scripts[0]["out_dir"]) / "fixture-build-executions"
        self.assertTrue(output.is_file(), output)
        return run(package, binaries[0]["executable"]), output

    def test_fixture_output_path_follows_cargo_messages(self):
        for directory in ("identity-fixture-hash", "identity_fixture-hash", "identity-fixture/hash"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                package = Path(tmp) / "package"
                out_dir = Path(tmp) / "custom-build-dir" / directory / "out"
                out_dir.mkdir(parents=True)
                output = out_dir / "fixture-build-executions"
                output.write_text("1", encoding="utf-8")
                self.assertFalse((out_dir.parent / "output").exists())
                executable = str(Path(tmp) / "fixture-bin")
                events = [
                    {"reason": "build-script-executed", "package_id": "fixture", "out_dir": str(out_dir)},
                    {"reason": "compiler-artifact", "package_id": "fixture", "executable": executable},
                ]

                def run(cwd, *args):
                    self.assertEqual(cwd, package)
                    if args[0] == "cargo":
                        self.assertEqual(args, ("cargo", "build", "--offline", "--quiet", "--message-format=json"))
                        return "\n".join(json.dumps(event) for event in events)
                    self.assertEqual(args, (executable,))
                    return "fixture identity"

                self.assertEqual(self.build_fixture(run, package), ("fixture identity", output))

    def test_packed_branch_without_reflog_refreshes_and_then_stays_cached(self):
        for linked_worktree in (False, True):
            with self.subTest(linked_worktree=linked_worktree), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = os.environ.copy()
                for key in (
                    "WEBCODEX_GIT_COMMIT", "WEBCODEX_GIT_DIRTY", "WEBCODEX_BUILT_AT",
                    "SOURCE_DATE_EPOCH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                ):
                    env.pop(key, None)
                env["CARGO_TARGET_DIR"] = str(root / "target")

                def run(cwd, *args):
                    return subprocess.run(
                        args, cwd=cwd, env=env, check=True, capture_output=True,
                        text=True, timeout=60,
                    ).stdout.strip()

                repo = root / "repo"
                repo.mkdir()
                run(repo, "git", "init", "-b", "review/packed")
                run(repo, "git", "config", "core.logAllRefUpdates", "false")
                run(repo, "git", "config", "user.name", "Build fixture")
                run(repo, "git", "config", "user.email", "fixture@example.invalid")
                package = repo / "crates/fixture"
                (package / "src").mkdir(parents=True)
                (package / "Cargo.toml").write_text(
                    '[package]\nname = "identity-fixture"\nversion = "0.0.0"\n'
                    'edition = "2021"\n', encoding="utf-8",
                )
                self.install_observed_build_script(package)
                (package / "src/main.rs").write_text(
                    'fn main() { println!("{}", env!("WEBCODEX_BUILD_GIT_COMMIT")); }\n',
                    encoding="utf-8",
                )
                run(repo, "git", "add", ".")
                run(repo, "git", "commit", "-m", "fixture")
                if linked_worktree:
                    checkout = root / "checkout"
                    run(repo, "git", "worktree", "add", "-b", "review/linked", str(checkout))
                    repo = checkout
                    package = repo / "crates/fixture"
                run(repo, "git", "pack-refs", "--all", "--prune")
                head_log = Path(run(repo, "git", "rev-parse", "--git-path", "logs/HEAD"))
                self.assertFalse((repo / head_log).exists())

                outputs = []

                def build():
                    value, output = self.build_fixture(run, package)
                    if outputs:
                        self.assertEqual(outputs, [output])
                    else:
                        outputs.append(output)
                    return value

                before = build()
                self.assertEqual(len(outputs), 1)
                stamp = self.marker_state(outputs[0])
                self.assertEqual(build(), before)
                self.assertEqual(self.marker_state(outputs[0]), stamp)
                run(repo, "git", "commit", "--allow-empty", "-m", "new identity")
                expected = run(repo, "git", "rev-parse", "--short=12", "HEAD")
                self.assertNotEqual(before, expected)
                self.assertEqual(build(), expected)
                self.assertGreater(self.marker_state(outputs[0])[0], stamp[0])
                stamp = self.marker_state(outputs[0])
                self.assertEqual(build(), expected)
                self.assertEqual(self.marker_state(outputs[0]), stamp)

    def test_tracked_dirty_state_refreshes_at_same_head(self):
        for linked_worktree in (False, True):
            with self.subTest(linked_worktree=linked_worktree), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = os.environ.copy()
                for key in (
                    "WEBCODEX_GIT_COMMIT", "WEBCODEX_GIT_DIRTY", "WEBCODEX_BUILT_AT",
                    "SOURCE_DATE_EPOCH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                ):
                    env.pop(key, None)
                env["CARGO_TARGET_DIR"] = str(root / "target")

                def run(cwd, *args):
                    return subprocess.run(
                        args, cwd=cwd, env=env, check=True, capture_output=True,
                        text=True, timeout=60,
                    ).stdout.strip()

                repo = root / "repo"
                repo.mkdir()
                run(repo, "git", "init", "-b", "review/dirty")
                run(repo, "git", "config", "user.name", "Build fixture")
                run(repo, "git", "config", "user.email", "fixture@example.invalid")
                (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
                (repo / "other.txt").write_text("clean\n", encoding="utf-8")
                package = repo / "crates/fixture"
                (package / "src").mkdir(parents=True)
                (package / "Cargo.toml").write_text(
                    '[package]\nname = "identity-fixture"\nversion = "0.0.0"\n'
                    'edition = "2021"\n', encoding="utf-8",
                )
                self.install_observed_build_script(package)
                (package / "src/main.rs").write_text(
                    'fn main() { println!("{}", env!("WEBCODEX_BUILD_GIT_DIRTY")); }\n',
                    encoding="utf-8",
                )
                run(repo, "git", "add", ".")
                run(repo, "git", "commit", "-m", "fixture")
                if linked_worktree:
                    checkout = root / "checkout"
                    run(repo, "git", "worktree", "add", "-b", "review/linked", str(checkout))
                    repo = checkout
                    package = repo / "crates/fixture"

                outputs = []

                def build():
                    value, output = self.build_fixture(run, package)
                    if outputs:
                        self.assertEqual(outputs, [output])
                    else:
                        outputs.append(output)
                    return value

                head = run(repo, "git", "rev-parse", "HEAD")
                self.assertEqual(build(), "false")
                clean_count = self.marker_state(outputs[0])[0]
                (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
                self.assertEqual(run(repo, "git", "rev-parse", "HEAD"), head)
                self.assertEqual(build(), "true")
                self.assertGreater(self.marker_state(outputs[0])[0], clean_count)
                self.assertEqual(len(outputs), 1)
                dirty_stamp = self.marker_state(outputs[0])
                (repo / "other.txt").write_text("also dirty\n", encoding="utf-8")
                self.assertEqual(build(), "true")
                self.assertEqual(self.marker_state(outputs[0]), dirty_stamp)

                run(repo, "git", "restore", "tracked.txt")
                self.assertEqual(run(repo, "git", "rev-parse", "HEAD"), head)
                self.assertEqual(build(), "true")
                run(repo, "git", "restore", "other.txt")
                self.assertEqual(run(repo, "git", "rev-parse", "HEAD"), head)
                self.assertEqual(build(), "false")

                (repo / "tracked.txt").unlink()
                self.assertEqual(build(), "true")
                deleted_stamp = self.marker_state(outputs[0])
                self.assertEqual(build(), "true")
                self.assertEqual(self.marker_state(outputs[0]), deleted_stamp)
                run(repo, "git", "restore", "tracked.txt")
                self.assertEqual(build(), "false")

                env["WEBCODEX_GIT_DIRTY"] = "false"
                self.assertEqual(build(), "false")
                self.assertEqual(len(outputs), 1)
                stamp = self.marker_state(outputs[0])
                (repo / "tracked.txt").write_text("dirty with pinned identity\n", encoding="utf-8")
                self.assertEqual(build(), "false")
                self.assertEqual(self.marker_state(outputs[0]), stamp)


    def test_stat_only_change_is_clean_without_refreshing_index(self):
        for linked_worktree in (False, True):
            with self.subTest(linked_worktree=linked_worktree), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = os.environ.copy()
                for key in (
                    "WEBCODEX_GIT_COMMIT", "WEBCODEX_GIT_DIRTY", "WEBCODEX_BUILT_AT",
                    "SOURCE_DATE_EPOCH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                ):
                    env.pop(key, None)
                env["CARGO_TARGET_DIR"] = str(root / "target")
                env["GIT_OPTIONAL_LOCKS"] = "0"

                def run(cwd, *args):
                    return subprocess.run(
                        args, cwd=cwd, env=env, check=True, capture_output=True,
                        text=True, timeout=60,
                    ).stdout.strip()

                repo = root / "repo"
                repo.mkdir()
                run(repo, "git", "init", "-b", "review/stat-only")
                run(repo, "git", "config", "user.name", "Build fixture")
                run(repo, "git", "config", "user.email", "fixture@example.invalid")
                tracked = repo / "tracked.txt"
                tracked.write_text("clean\n", encoding="utf-8")
                package = repo / "crates/fixture"
                (package / "src").mkdir(parents=True)
                (package / "Cargo.toml").write_text(
                    '[package]\nname = "identity-fixture"\nversion = "0.0.0"\n'
                    'edition = "2021"\n', encoding="utf-8",
                )
                shutil.copyfile(BUILD_SCRIPT, package / "build.rs")
                (package / "src/main.rs").write_text(
                    'fn main() { println!("{}", env!("WEBCODEX_BUILD_GIT_DIRTY")); }\n',
                    encoding="utf-8",
                )
                run(repo, "git", "add", ".")
                run(repo, "git", "commit", "-m", "fixture")
                if linked_worktree:
                    checkout = root / "checkout"
                    run(repo, "git", "worktree", "add", "-b", "review/linked", str(checkout))
                    repo = checkout
                    package = repo / "crates/fixture"
                    tracked = repo / "tracked.txt"

                # Change only stat data before the FIRST build, so this tests
                # dirty computation independently of Cargo's rerun decisions.
                original = tracked.read_bytes()
                info = tracked.stat()
                os.utime(tracked, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
                self.assertEqual(tracked.read_bytes(), original)
                self.assertEqual(run(repo, "git", "status", "--porcelain=v1"), "")
                stale = subprocess.run(
                    ["git", "diff-index", "--quiet", "HEAD", "--"],
                    cwd=repo, env=env, capture_output=True, timeout=60,
                )
                self.assertEqual(stale.returncode, 1)
                self.assertEqual(run(package, "cargo", "run", "--offline", "--quiet"), "false")

                # Real content changes must still be dirty, both unstaged and staged.
                tracked.write_text("real change\n", encoding="utf-8")
                self.assertEqual(run(package, "cargo", "run", "--offline", "--quiet"), "true")
                run(repo, "git", "add", "tracked.txt")
                self.assertEqual(run(package, "cargo", "run", "--offline", "--quiet"), "true")


class BuildIdentityBoundaryTests(unittest.TestCase):
    def test_git_identity_changes_do_not_invalidate_core_or_domain_artifacts(self):
        """Real Cargo/Git with the shipped collector, no registry dependencies."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            env = os.environ.copy()
            for key in (
                "WEBCODEX_GIT_COMMIT", "WEBCODEX_GIT_DIRTY", "WEBCODEX_BUILT_AT",
                "SOURCE_DATE_EPOCH", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
            ):
                env.pop(key, None)
            env["CARGO_TARGET_DIR"] = str(root / "target")

            def run(cwd, *args):
                return subprocess.run(args, cwd=cwd, env=env, check=True,
                                      capture_output=True, text=True, timeout=90).stdout.strip()

            (repo / "Cargo.toml").write_text(
                '[workspace]\nresolver = "2"\nmembers = ["crates/*"]\n', encoding="utf-8")
            definitions = {
                "identity-core": ('pub fn value() -> u8 { 7 }\n', {}),
                "identity-domain": ('pub fn value() -> u8 { identity_core::value() }\n',
                                    {"identity-core": "../identity-core"}),
                "identity-build": (
                    'pub fn values() -> [&\'static str; 5] { [env!("WEBCODEX_BUILD_GIT_COMMIT"), '
                    'env!("WEBCODEX_BUILD_GIT_DIRTY"), env!("WEBCODEX_BUILD_BUILT_AT"), '
                    'env!("WEBCODEX_BUILD_TARGET"), env!("WEBCODEX_BUILD_ARCHITECTURE")] }\n',
                    {"identity-core": "../identity-core"}),
                "identity-app": (
                    'fn main() { assert_eq!(identity_domain::value(), 7); '
                    'println!("{}", identity_build::values().join("|")); }\n',
                    {"identity-domain": "../identity-domain", "identity-build": "../identity-build"}),
            }
            for name, (source, dependencies) in definitions.items():
                package = repo / "crates" / name
                (package / "src").mkdir(parents=True)
                manifest = f'[package]\nname = "{name}"\nversion = "0.0.0"\nedition = "2021"\n[dependencies]\n'
                manifest += ''.join(f'{dep} = {{ path = "{path}" }}\n' for dep, path in dependencies.items())
                (package / "Cargo.toml").write_text(manifest, encoding="utf-8")
                (package / "src" / ("main.rs" if name == "identity-app" else "lib.rs")).write_text(source, encoding="utf-8")
            shutil.copyfile(BUILD_SCRIPT, repo / "crates/identity-build/build.rs")
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            run(repo, "git", "init", "-b", "identity-fixture")
            run(repo, "git", "config", "user.name", "Build fixture")
            run(repo, "git", "config", "user.email", "fixture@example.invalid")
            run(repo, "git", "add", ".")
            run(repo, "git", "commit", "-m", "fixture")

            def build(checkout):
                messages = run(checkout, "cargo", "build", "--offline", "--message-format=json", "-p", "identity-app")
                artifacts = [json.loads(line) for line in messages.splitlines() if line.startswith('{')]
                freshness = {item["target"]["name"]: item["fresh"] for item in artifacts
                             if item.get("reason") == "compiler-artifact" and "custom-build" not in item["target"]["kind"]}
                binary = root / "target/debug" / ("identity-app.exe" if os.name == "nt" else "identity-app")
                return run(checkout, str(binary)).split("|"), freshness

            first, _ = build(repo)
            repeated, fresh = build(repo)
            self.assertEqual(first, repeated)
            self.assertTrue(all(fresh.values()), fresh)
            self.assertEqual(first[1], "false")
            run(repo, "git", "commit", "--allow-empty", "-m", "identity-only")
            current, fresh = build(repo)
            self.assertEqual(current[0], run(repo, "git", "rev-parse", "--short=12", "HEAD"))
            self.assertNotEqual(first[0], current[0])
            self.assertTrue(fresh["identity_core"])
            self.assertTrue(fresh["identity_domain"])
            self.assertFalse(fresh["identity_build"])
            self.assertFalse(fresh["identity-app"])

            (repo / "README.md").write_text("dirty documentation\n", encoding="utf-8")
            dirty, fresh = build(repo)
            self.assertEqual(dirty[1], "true")
            self.assertTrue(fresh["identity_core"])
            self.assertTrue(fresh["identity_domain"])
            app = repo / "crates/identity-app/src/main.rs"
            app.write_text(app.read_text(encoding="utf-8") + "// local implementation change\n", encoding="utf-8")
            _, fresh = build(repo)
            self.assertTrue(fresh["identity_core"])
            self.assertTrue(fresh["identity_domain"])
            self.assertTrue(fresh["identity_build"])
            self.assertFalse(fresh["identity-app"])
            # Restore only this disposable fixture, never the user's workspace.
            run(repo, "git", "restore", "README.md", "crates/identity-app/src/main.rs")
            clean, _ = build(repo)
            self.assertEqual(clean[1], "false")
            linked = root / "linked"
            run(repo, "git", "worktree", "add", "-b", "linked-identity", str(linked))
            run(linked, "git", "commit", "--allow-empty", "-m", "linked identity")
            linked_identity, _ = build(linked)
            self.assertEqual(linked_identity[0], run(linked, "git", "rev-parse", "--short=12", "HEAD"))
            self.assertNotEqual(linked_identity[0], clean[0])
            returned, _ = build(repo)
            self.assertEqual(returned, clean)

    def test_source_archive_and_release_overrides_keep_explicit_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "crates/identity-archive"
            (package / "src").mkdir(parents=True)
            (package / "Cargo.toml").write_text(
                '[package]\nname = "identity-archive"\nversion = "0.0.0"\nedition = "2021"\n', encoding="utf-8")
            shutil.copyfile(BUILD_SCRIPT, package / "build.rs")
            (package / "src/main.rs").write_text(
                'fn main() { println!("{}|{}|{}", env!("WEBCODEX_BUILD_GIT_COMMIT"), '
                'env!("WEBCODEX_BUILD_GIT_DIRTY"), env!("WEBCODEX_BUILD_BUILT_AT")); }\n', encoding="utf-8")
            env = os.environ.copy()
            for key in ("WEBCODEX_GIT_COMMIT", "WEBCODEX_GIT_DIRTY", "WEBCODEX_BUILT_AT", "SOURCE_DATE_EPOCH",
                        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
                env.pop(key, None)
            env["CARGO_TARGET_DIR"] = str(root / "target")
            env["SOURCE_DATE_EPOCH"] = "1234567890"

            def build():
                return subprocess.run(["cargo", "run", "--offline", "--quiet"], cwd=package,
                                      env=env, check=True, capture_output=True, text=True, timeout=90).stdout.strip()

            self.assertEqual(build(), "unknown|unknown|1234567890")
            env.update(WEBCODEX_GIT_COMMIT="abcdef012345", WEBCODEX_GIT_DIRTY="false", WEBCODEX_BUILT_AT="1234567891")
            self.assertEqual(build(), "abcdef012345|false|1234567891")
            env["WEBCODEX_GIT_DIRTY"] = "true"
            self.assertEqual(build(), "abcdef012345|true|1234567891")


if __name__ == "__main__":
    unittest.main()
