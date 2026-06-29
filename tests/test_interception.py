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

from app.pipeline.interception import (
    InterceptionStrategy,
    PtraceStrategy,
    CcWrapperStrategy,
    GoToolexecStrategy,
    RustcWrapperStrategy,
    MavenDepTreeStrategy,
    GradleDepTreeStrategy,
    _generate_java_treedb,
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


if __name__ == "__main__":
    unittest.main()
