"""
Tests for app/pipeline/interception.py.

Tests all InterceptionStrategy implementations:
PtraceStrategy, CcWrapperStrategy, GoToolexecStrategy,
RustcWrapperStrategy, MavenDepTreeStrategy,
GradleDepTreeStrategy.
"""

import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import json
import os
import tempfile

from app.pipeline.interception import (
    InterceptionStrategy,
    PtraceStrategy,
    CcWrapperStrategy,
    GoToolexecStrategy,
    RustcWrapperStrategy,
    MavenDepTreeStrategy,
    GradleDepTreeStrategy,
    _generate_java_treedb,
    _git_blob_sha1,
    assemble_treedb_from_capture,
    build_inline_hash_env,
    build_java_treedb,
    make_source_resolver,
    prepare_capture_log,
)


# ============================================================
# PtraceStrategy
# ============================================================

class TestPtraceStrategy(unittest.TestCase):
    """Tests for PtraceStrategy."""

    def test_name_default(self):
        s = PtraceStrategy()
        self.assertEqual(s.name, "bomtrace3")

    def test_name_custom_tracer(self):
        s = PtraceStrategy(tracer="bomtrace2")
        self.assertEqual(s.name, "bomtrace2")

    def test_default_tracer(self):
        s = PtraceStrategy()
        cmd, env = s.instrument_command(
            "make -j4", "/repo",
        )
        self.assertEqual(cmd, "bomtrace3 make -j4")
        self.assertEqual(env, {})

    def test_custom_tracer(self):
        s = PtraceStrategy(tracer="bomtrace2")
        cmd, env = s.instrument_command(
            "cargo build --release", "/repo",
        )
        self.assertEqual(
            cmd, "bomtrace2 cargo build --release",
        )
        self.assertEqual(env, {})

    def test_tracer_with_config_flags(self):
        s = PtraceStrategy(
            tracer="bomtrace2 -c /opt/go.conf",
        )
        cmd, env = s.instrument_command(
            "go build -o fzf .", "/repo",
        )
        self.assertEqual(
            cmd,
            "bomtrace2 -c /opt/go.conf "
            "go build -o fzf .",
        )

    def test_exact_current_builder_behavior(self):
        """Verify output matches builder.py line 82."""
        tracer = "bomtrace3"
        make_cmd = "make -j$(nproc)"
        s = PtraceStrategy(tracer=tracer)
        cmd, env = s.instrument_command(
            make_cmd, "/workspace/repos/curl",
        )
        self.assertEqual(
            cmd, f"{tracer} {make_cmd}",
        )

    @patch("app.runner.CommandRunner")
    def test_generate_adg_success(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        mock_cls.return_value = mock_runner
        s = PtraceStrategy()
        cfg = {
            "create_bom_script": "bomsh_create_bom.py",
            "raw_logfile": "/tmp/log.sha1",
        }
        result = s.generate_adg(
            "/repo", "/bom", cfg,
        )
        self.assertTrue(result)
        mock_runner.run.assert_called_once()

    @patch("app.runner.CommandRunner")
    def test_generate_adg_failure(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.run.return_value = 1
        mock_cls.return_value = mock_runner
        s = PtraceStrategy()
        result = s.generate_adg(
            "/repo", "/bom", {},
        )
        self.assertFalse(result)

    @patch("app.runner.CommandRunner")
    def test_generate_adg_default_config(self, mock_cls):
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        mock_cls.return_value = mock_runner
        s = PtraceStrategy()
        s.generate_adg("/repo", "/bom", {})
        call_args = mock_runner.run.call_args
        cmd_str = call_args[0][0]
        self.assertIn(
            "bomsh_create_bom.py", cmd_str,
        )
        self.assertIn(
            "bomsh_hook_raw_logfile", cmd_str,
        )


# ============================================================
# CcWrapperStrategy
# ============================================================

class TestCcWrapperStrategy(unittest.TestCase):
    """Tests for CcWrapperStrategy."""

    def test_name(self):
        s = CcWrapperStrategy()
        self.assertEqual(s.name, "cc-wrapper")

    def test_default_wrappers(self):
        s = CcWrapperStrategy()
        cmd, env = s.instrument_command(
            "make -j4", "/repo",
        )
        self.assertEqual(cmd, "make -j4")
        self.assertIn("CC", env)
        self.assertIn("CXX", env)
        self.assertIn("AR", env)
        self.assertIn("LD", env)

    def test_custom_wrapper_dir(self):
        s = CcWrapperStrategy(wrapper_dir="/custom")
        cmd, env = s.instrument_command(
            "make", "/repo",
        )
        self.assertEqual(
            env["CC"], "/custom/bomsh_cc_wrapper.sh",
        )

    def test_command_unchanged(self):
        s = CcWrapperStrategy()
        cmd, env = s.instrument_command(
            "make -j$(nproc)", "/repo",
        )
        self.assertEqual(cmd, "make -j$(nproc)")


# ============================================================
# GoToolexecStrategy
# ============================================================

class TestGoToolexecStrategy(unittest.TestCase):
    """Tests for GoToolexecStrategy."""

    def test_name(self):
        s = GoToolexecStrategy()
        self.assertEqual(s.name, "go-toolexec")

    def test_default_wrapper(self):
        s = GoToolexecStrategy()
        cmd, env = s.instrument_command(
            "go build -o fzf .", "/repo",
        )
        self.assertIn("-toolexec=", cmd)
        self.assertIn("bomsh_hook.sh", cmd)
        self.assertEqual(env, {})

    def test_go_build_replacement(self):
        s = GoToolexecStrategy(wrapper="/w.sh")
        cmd, env = s.instrument_command(
            "go build -a -o fzf .", "/repo",
        )
        self.assertEqual(
            cmd,
            "go build -toolexec=/w.sh -a -o fzf .",
        )

    def test_no_go_build_no_change(self):
        s = GoToolexecStrategy()
        cmd, env = s.instrument_command(
            "go test ./...", "/repo",
        )
        self.assertEqual(cmd, "go test ./...")

    def test_only_first_go_build_replaced(self):
        s = GoToolexecStrategy(wrapper="/w")
        cmd, _ = s.instrument_command(
            "go build && go build", "/repo",
        )
        # Only first occurrence replaced
        self.assertEqual(
            cmd.count("-toolexec="), 1,
        )


# ============================================================
# RustcWrapperStrategy
# ============================================================

class TestRustcWrapperStrategy(unittest.TestCase):
    """Tests for RustcWrapperStrategy."""

    def test_name(self):
        s = RustcWrapperStrategy()
        self.assertEqual(s.name, "rustc-wrapper")

    def test_default_wrapper(self):
        s = RustcWrapperStrategy()
        cmd, env = s.instrument_command(
            "cargo build --release", "/repo",
        )
        self.assertEqual(
            cmd, "cargo build --release",
        )
        self.assertIn("RUSTC_WRAPPER", env)
        self.assertIn(
            "bomsh_hook.sh",
            env["RUSTC_WRAPPER"],
        )

    def test_custom_wrapper(self):
        s = RustcWrapperStrategy(wrapper="/my/w")
        cmd, env = s.instrument_command(
            "cargo build", "/repo",
        )
        self.assertEqual(
            env["RUSTC_WRAPPER"], "/my/w",
        )

    def test_command_unchanged(self):
        s = RustcWrapperStrategy()
        cmd, env = s.instrument_command(
            "cargo build --release", "/repo",
        )
        self.assertEqual(
            cmd, "cargo build --release",
        )


# ============================================================
# MavenDepTreeStrategy
# ============================================================

class TestMavenDepTreeStrategy(unittest.TestCase):
    """Tests for MavenDepTreeStrategy."""

    def test_name(self):
        s = MavenDepTreeStrategy(runner=MagicMock())
        self.assertEqual(s.name, "maven-dep-tree")

    def test_command_passthrough(self):
        s = MavenDepTreeStrategy(runner=MagicMock())
        cmd, env = s.instrument_command(
            "mvn package -DskipTests", "/repo",
        )
        self.assertEqual(
            cmd, "mvn package -DskipTests",
        )
        self.assertEqual(env, {})


# ============================================================
# GradleDepTreeStrategy
# ============================================================

class TestGradleDepTreeStrategy(unittest.TestCase):
    """Tests for GradleDepTreeStrategy."""

    def test_name(self):
        s = GradleDepTreeStrategy(runner=MagicMock())
        self.assertEqual(s.name, "gradle-dep-tree")

    def test_command_passthrough(self):
        s = GradleDepTreeStrategy(runner=MagicMock())
        cmd, env = s.instrument_command(
            "./gradlew build", "/repo",
        )
        self.assertEqual(cmd, "./gradlew build")
        self.assertEqual(env, {})


# ============================================================
# ABC enforcement
# ============================================================

class TestInterceptionStrategyABC(unittest.TestCase):
    """Tests for InterceptionStrategy ABC."""

    def test_cannot_instantiate(self):
        with self.assertRaises(TypeError):
            InterceptionStrategy()

    def test_subclass_must_implement(self):
        class Incomplete(InterceptionStrategy):
            pass
        with self.assertRaises(TypeError):
            Incomplete()


# ============================================================
# _generate_java_treedb (shared helper)
# ============================================================

class TestGenerateJavaTreedb(unittest.TestCase):
    """Tests for the shared _generate_java_treedb helper."""

    def test_success_appends_treedb_substep(self):
        runner = MagicMock()
        runner.run.return_value = 0
        substeps = []
        with patch("builtins.print"):
            ok = _generate_java_treedb(
                runner, "/repo", Path("/bom/meta"),
                {}, substeps,
            )
        self.assertTrue(ok)
        self.assertEqual(len(substeps), 1)
        self.assertEqual(substeps[0]["name"], "treedb")
        self.assertEqual(
            substeps[0]["tool"], "bomsh_create_bom_java.py",
        )
        self.assertIn("wall_sec", substeps[0])

    def test_failure_returns_false_but_records_substep(self):
        runner = MagicMock()
        runner.run.return_value = 1
        substeps = []
        with patch("builtins.print"):
            ok = _generate_java_treedb(
                runner, "/repo", Path("/bom/meta"),
                {}, substeps,
            )
        self.assertFalse(ok)
        self.assertEqual(len(substeps), 1)
        self.assertEqual(substeps[0]["name"], "treedb")

    def test_uses_default_create_bom_script(self):
        runner = MagicMock()
        runner.run.return_value = 0
        with patch("builtins.print"):
            _generate_java_treedb(
                runner, "/repo", Path("/bom/meta"),
                {}, [],
            )
        cmd_str = runner.run.call_args[0][0]
        self.assertIn("bomsh_create_bom_java.py", cmd_str)
        self.assertIn("-r /repo", cmd_str)
        self.assertIn(
            "-j /bom/meta/bomsh_omnibor_treedb", cmd_str,
        )
        self.assertIn("-b /bom/meta", cmd_str)
        self.assertIn("-m", cmd_str.split())

    def test_honors_config_create_bom_script(self):
        runner = MagicMock()
        runner.run.return_value = 0
        cfg = {"create_bom_script": "/custom/mkbom.py"}
        with patch("builtins.print"):
            _generate_java_treedb(
                runner, "/repo", Path("/bom/meta"),
                cfg, [],
            )
        cmd_str = runner.run.call_args[0][0]
        self.assertIn("/custom/mkbom.py", cmd_str)


# ============================================================
# Inline-hashing helpers
# ============================================================

class TestBuildInlineHashEnv(unittest.TestCase):
    """Tests for build_inline_hash_env."""

    def test_basic_env(self):
        env = build_inline_hash_env("/lib/shim.so", "/w/cap.jsonl")
        self.assertEqual(env["LD_PRELOAD"], "/lib/shim.so")
        self.assertEqual(
            env["OMNIBOR_CAPTURE_LOG"], "/w/cap.jsonl",
        )

    def test_extra_merged(self):
        env = build_inline_hash_env(
            "/lib/shim.so", "/w/cap.jsonl",
            extra={"GRADLE_OPTS": "-Dorg.gradle.daemon=false"},
        )
        self.assertEqual(
            env["GRADLE_OPTS"], "-Dorg.gradle.daemon=false",
        )


class TestGitBlobSha1(unittest.TestCase):
    """Tests for _git_blob_sha1 (git object id parity)."""

    def test_matches_known_empty_blob(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty"
            p.write_bytes(b"")
            # git hash-object of an empty blob is a well-known SHA-1.
            self.assertEqual(
                _git_blob_sha1(str(p)),
                "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
            )

    def test_matches_known_hello_blob(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f"
            p.write_bytes(b"hello")
            # printf 'hello' | git hash-object --stdin
            self.assertEqual(
                _git_blob_sha1(str(p)),
                "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0",
            )


class TestMakeSourceResolver(unittest.TestCase):
    """Tests for make_source_resolver."""

    def _make_repo(self, td):
        src = (
            Path(td) / "src" / "main" / "java"
            / "com" / "x"
        )
        src.mkdir(parents=True)
        (src / "App.java").write_bytes(b"class App {}")
        return td

    def test_resolves_by_path_similarity(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            resolve = make_source_resolver(td)
            class_path = f"{td}/target/classes/com/x/App.class"
            result = resolve("App.java", class_path)
            self.assertIsNotNone(result)
            path, sha1 = result
            self.assertTrue(
                path.endswith("src/main/java/com/x/App.java")
            )
            self.assertEqual(len(sha1), 40)

    def test_returns_none_for_empty_source(self):
        with tempfile.TemporaryDirectory() as td:
            resolve = make_source_resolver(td)
            self.assertIsNone(resolve("", f"{td}/a/App.class"))

    def test_returns_none_for_empty_class_path(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            resolve = make_source_resolver(td)
            self.assertIsNone(resolve("App.java", ""))

    def test_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            resolve = make_source_resolver(td)
            self.assertIsNone(
                resolve("Missing.java", f"{td}/a/Missing.class"),
            )

    def test_disambiguates_when_repo_dir_relative_class_abs(self):
        # Production condition: the source index is walked from a
        # *relative* repo_dir while the shim records *absolute* class
        # paths.  Both must be normalised to absolute so the class
        # resolves to the source in its own module, not a sibling.
        with tempfile.TemporaryDirectory() as td:
            base = (Path(td) / "api" / "src" / "main" / "java"
                    / "o" / "p")
            v9 = (Path(td) / "api-java9" / "src" / "main" / "java"
                  / "o" / "p")
            base.mkdir(parents=True)
            v9.mkdir(parents=True)
            (base / "Provider.java").write_bytes(b"base")
            (v9 / "Provider.java").write_bytes(b"v9")
            cwd = os.getcwd()
            try:
                os.chdir(td)
                resolve = make_source_resolver(".")
                v9_cls = (f"{td}/api-java9/target/classes"
                          "/o/p/Provider.class")
                v9_src, _ = resolve("Provider.java", v9_cls)
            finally:
                os.chdir(cwd)
            self.assertIn("api-java9", v9_src)

    def test_base_vs_versioned_disambiguated_by_path(self):
        # The same fully-qualified class exists in a base module and a
        # java9 companion module.  The resolver must pick the source in
        # the class's own module tree (path similarity), not the sibling.
        with tempfile.TemporaryDirectory() as td:
            base = (Path(td) / "api" / "src" / "main" / "java"
                    / "o" / "p")
            v9 = (Path(td) / "api-java9" / "src" / "main" / "java"
                  / "o" / "p")
            base.mkdir(parents=True)
            v9.mkdir(parents=True)
            (base / "Provider.java").write_bytes(b"base")
            (v9 / "Provider.java").write_bytes(b"v9")
            resolve = make_source_resolver(td)
            base_cls = f"{td}/api/target/classes/o/p/Provider.class"
            v9_cls = (
                f"{td}/api-java9/target/classes/o/p/Provider.class"
            )
            base_src, _ = resolve("Provider.java", base_cls)
            v9_src, _ = resolve("Provider.java", v9_cls)
            self.assertIn("/api/src/", base_src)
            self.assertIn("/api-java9/src/", v9_src)


class TestAssembleTreedbFromCapture(unittest.TestCase):
    """Tests for assemble_treedb_from_capture."""

    def test_missing_log_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            substeps = []
            with patch("builtins.print"):
                ok = assemble_treedb_from_capture(
                    str(Path(td) / "nope.jsonl"),
                    td, Path(td), substeps,
                )
            self.assertFalse(ok)
            self.assertEqual(substeps[0]["name"], "treedb")

    def test_assembles_and_writes_treedb(self):
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "cap.jsonl"
            cap.write_text(
                json.dumps({
                    "kind": "class", "path": "/t/App.class",
                    "sha1": "cls1", "class_name": "com.x.App",
                }) + "\n",
                encoding="utf-8",
            )
            meta = Path(td) / "meta"
            meta.mkdir()
            substeps = []
            with patch("builtins.print"):
                ok = assemble_treedb_from_capture(
                    str(cap), td, meta, substeps,
                    resolver=lambda s, c: None,
                )
            self.assertTrue(ok)
            treedb = json.loads(
                (meta / "bomsh_omnibor_treedb").read_text(),
            )
            self.assertIn("cls1", treedb)
            self.assertEqual(
                substeps[0]["tool"], "inline-assemble",
            )


class TestBuildJavaTreedb(unittest.TestCase):
    """Tests for the build_java_treedb dispatcher."""

    def test_legacy_path_when_not_inline(self):
        runner = MagicMock()
        runner.run.return_value = 0
        with patch("builtins.print"):
            ok = build_java_treedb(
                False, None, runner, "/repo",
                Path("/bom/meta"), {}, [],
            )
        self.assertTrue(ok)
        runner.run.assert_called_once()

    def test_inline_path_when_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "cap.jsonl"
            cap.write_text(
                json.dumps({
                    "kind": "class", "path": "/t/App.class",
                    "sha1": "cls1",
                }) + "\n",
                encoding="utf-8",
            )
            meta = Path(td) / "meta"
            meta.mkdir()
            runner = MagicMock()
            with patch("builtins.print"):
                ok = build_java_treedb(
                    True, str(cap), runner, td, meta, {}, [],
                )
            self.assertTrue(ok)
            # Inline assembly must NOT invoke the rescan runner.
            runner.run.assert_not_called()


# ============================================================
# Inline-hash strategy behavior
# ============================================================

class TestPrepareCaptureLog(unittest.TestCase):
    """Tests for prepare_capture_log."""

    def test_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "sub" / "dir" / "cap.jsonl"
            prepare_capture_log(str(cap))
            self.assertTrue(cap.parent.is_dir())

    def test_clears_stale_log(self):
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "cap.jsonl"
            cap.write_text("stale\n", encoding="utf-8")
            prepare_capture_log(str(cap))
            self.assertFalse(cap.exists())


class TestStrategyInlineBehavior(unittest.TestCase):
    """Maven/Gradle inline-hash instrument_command + naming."""

    def _cap(self, td):
        return str(Path(td) / ".omnibor" / "c.jsonl")

    def test_maven_inline_name(self):
        s = MavenDepTreeStrategy(
            runner=MagicMock(), inline_hash=True,
            shim_path="/lib/shim.so", capture_log="/w/c.jsonl",
        )
        self.assertEqual(s.name, "maven-inline-hash")

    def test_maven_inline_env_injected(self):
        with tempfile.TemporaryDirectory() as td:
            cap = self._cap(td)
            s = MavenDepTreeStrategy(
                runner=MagicMock(), inline_hash=True,
                shim_path="/lib/shim.so", capture_log=cap,
            )
            cmd, env = s.instrument_command("mvn package", td)
            self.assertEqual(cmd, "mvn package")
            self.assertEqual(env["LD_PRELOAD"], "/lib/shim.so")
            self.assertEqual(env["OMNIBOR_CAPTURE_LOG"], cap)
            self.assertTrue(Path(cap).parent.is_dir())

    def test_maven_no_env_without_shim(self):
        s = MavenDepTreeStrategy(
            runner=MagicMock(), inline_hash=True,
            shim_path=None, capture_log="/w/c.jsonl",
        )
        _cmd, env = s.instrument_command("mvn package", "/repo")
        self.assertEqual(env, {})

    def test_gradle_inline_name(self):
        s = GradleDepTreeStrategy(
            runner=MagicMock(), inline_hash=True,
            shim_path="/lib/shim.so", capture_log="/w/c.jsonl",
        )
        self.assertEqual(s.name, "gradle-inline-hash")

    def test_gradle_inline_env_disables_daemon(self):
        with tempfile.TemporaryDirectory() as td:
            s = GradleDepTreeStrategy(
                runner=MagicMock(), inline_hash=True,
                shim_path="/lib/shim.so",
                capture_log=self._cap(td),
            )
            _cmd, env = s.instrument_command("./gradlew build", td)
            self.assertEqual(
                env["GRADLE_OPTS"], "-Dorg.gradle.daemon=false",
            )

    def test_legacy_names_unchanged(self):
        self.assertEqual(
            MavenDepTreeStrategy(runner=MagicMock()).name,
            "maven-dep-tree",
        )
        self.assertEqual(
            GradleDepTreeStrategy(runner=MagicMock()).name,
            "gradle-dep-tree",
        )


if __name__ == "__main__":
    unittest.main()
