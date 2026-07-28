"""
Tests for app/pipeline/gradle_dep_tree_parser.py.

Tests the Gradle dependency tree parser wrapper and
GradleDepTreeStrategy with realistic fixture data.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.pipeline.gradle_dep_tree_parser import (
    run_gradle_dep_tree,
    run_gradle_all_dep_trees,
    find_gradle_subprojects,
    get_all_gradle_deps,
    _split_dep_report_sections,
)


# ============================================================
# Fixture: single-project Gradle output
# ============================================================

_SINGLE_PROJECT_OUTPUT = (
    'runtimeClasspath - Runtime classpath'
    " of source set 'main'.\n"
    '+--- org.slf4j:slf4j-api:2.0.7\n'
    '+--- com.google.guava'
    ':guava:32.1.3-jre\n'
    '|    +--- com.google.guava'
    ':failureaccess:1.0.1\n'
    '|    \\--- com.google.guava'
    ':listenablefuture'
    ':9999.0-empty-to-avoid'
    '-conflict-with-guava\n'
    '+--- org.apache.commons'
    ':commons-lang3:3.14.0\n'
    '\\--- com.fasterxml.jackson.core'
    ':jackson-databind:2.16.0\n'
    '     +--- com.fasterxml.jackson.core'
    ':jackson-core:2.16.0\n'
    '     \\--- com.fasterxml.jackson.core'
    ':jackson-annotations:2.16.0\n'
)


# ============================================================
# Fixture: aggregated multi-project report (single invocation)
# ============================================================

_DASHES = "-" * 60
_MULTI_PROJECT_REPORT = (
    "> Task :util:omniborDeps\n\n"
    f"{_DASHES}\n"
    # ':util' carries a ' - description' suffix to exercise the
    # header regex's optional trailing text.
    "Project ':util' - Example utility module\n"
    f"{_DASHES}\n\n"
    "runtimeClasspath - Runtime classpath of source set 'main'.\n"
    "+--- com.a:b:1.0\n"
    "\\--- com.c:d:2.0\n\n"
    "> Task :core:omniborDeps\n\n"
    f"{_DASHES}\n"
    "Project ':core'\n"
    f"{_DASHES}\n\n"
    "runtimeClasspath - Runtime classpath of source set 'main'.\n"
    "+--- com.e:f:3.0\n"
)


# ============================================================
# Tests: run_gradle_dep_tree
# ============================================================

class TestRunGradleDepTree(unittest.TestCase):
    """Tests for run_gradle_dep_tree()."""

    def test_no_gradlew_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                result = run_gradle_dep_tree(td)
            self.assertIsNone(result)

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".subprocess.run"
    )
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_SINGLE_PROJECT_OUTPUT,
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            result = run_gradle_dep_tree(td)
        self.assertEqual(
            result, _SINGLE_PROJECT_OUTPUT,
        )

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".subprocess.run"
    )
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="BUILD FAILED",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            with patch("builtins.print"):
                result = run_gradle_dep_tree(td)
            self.assertIsNone(result)

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".subprocess.run"
    )
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = (
            subprocess.TimeoutExpired("gradlew", 120)
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            with patch("builtins.print"):
                result = run_gradle_dep_tree(td)
            self.assertIsNone(result)

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".subprocess.run"
    )
    def test_subproject(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_SINGLE_PROJECT_OUTPUT,
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            run_gradle_dep_tree(
                td, project=":core",
            )
        call_args = mock_run.call_args[0][0]
        self.assertIn(":core:dependencies", call_args)


# ============================================================
# Tests: find_gradle_subprojects
# ============================================================

class TestFindGradleSubprojects(unittest.TestCase):
    """Tests for find_gradle_subprojects()."""

    def test_no_settings_file(self):
        with tempfile.TemporaryDirectory() as td:
            result = find_gradle_subprojects(td)
        self.assertEqual(result, [])

    def test_groovy_settings(self):
        with tempfile.TemporaryDirectory() as td:
            settings = Path(td) / "settings.gradle"
            settings.write_text(
                "include ':core'\n"
                "include ':web'\n",
                encoding="utf-8",
            )
            result = find_gradle_subprojects(td)
        self.assertIn(":core", result)
        self.assertIn(":web", result)

    def test_kotlin_settings(self):
        with tempfile.TemporaryDirectory() as td:
            settings = (
                Path(td) / "settings.gradle.kts"
            )
            settings.write_text(
                'include(":core")\n'
                'include(":web")\n',
                encoding="utf-8",
            )
            result = find_gradle_subprojects(td)
        self.assertIn(":core", result)
        self.assertIn(":web", result)


# ============================================================
# Tests: GradleDepTreeStrategy
# ============================================================

class TestGradleDepTreeStrategy(unittest.TestCase):
    """Tests for GradleDepTreeStrategy."""

    def test_instrument_command_passthrough(self):
        from app.pipeline.interception import (
            GradleDepTreeStrategy,
        )
        strategy = GradleDepTreeStrategy()
        cmd, env = strategy.instrument_command(
            "./gradlew build", "/repo",
        )
        self.assertEqual(cmd, "./gradlew build")
        self.assertEqual(env, {})

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".run_gradle_dep_tree"
    )
    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".find_gradle_subprojects"
    )
    def test_generate_adg_success(
        self, mock_subs, mock_run,
    ):
        from app.pipeline.interception import (
            GradleDepTreeStrategy,
        )
        mock_subs.return_value = []
        mock_run.return_value = _SINGLE_PROJECT_OUTPUT
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        strategy = GradleDepTreeStrategy(
            runner=mock_runner,
        )
        with tempfile.TemporaryDirectory() as td:
            bom_dir = Path(td) / "bom"
            with patch("builtins.print"):
                ok = strategy.generate_adg(
                    "/repo", str(bom_dir), {},
                )
            self.assertTrue(ok)
            capture_file = bom_dir / "gradle_deps.json"
            self.assertTrue(capture_file.exists())
            capture = json.loads(capture_file.read_text())
            self.assertEqual(capture["tool"], "gradle")
            self.assertEqual(
                capture["modules"][0]["key"], ":",
            )
            substeps_file = (
                bom_dir / "adg_substeps.json"
            )
            self.assertTrue(substeps_file.exists())
            substeps = json.loads(
                substeps_file.read_text()
            )
            self.assertEqual(len(substeps), 2)
            self.assertEqual(
                substeps[0]["name"], "treedb",
            )
            self.assertEqual(
                substeps[1]["name"], "dep_tree",
            )
            self.assertIn(
                "wall_sec", substeps[0],
            )
            mock_runner.run.assert_called_once()

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".run_gradle_dep_tree"
    )
    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".find_gradle_subprojects"
    )
    def test_generate_adg_no_deps(
        self, mock_subs, mock_run,
    ):
        from app.pipeline.interception import (
            GradleDepTreeStrategy,
        )
        mock_subs.return_value = []
        mock_run.return_value = None
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        strategy = GradleDepTreeStrategy(
            runner=mock_runner,
        )
        with tempfile.TemporaryDirectory() as td:
            bom_dir = Path(td) / "bom"
            with patch("builtins.print"):
                ok = strategy.generate_adg(
                    "/repo", str(bom_dir), {},
                )
            self.assertTrue(ok)

    def test_generate_adg_treedb_failure(self):
        from app.pipeline.interception import (
            GradleDepTreeStrategy,
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = 1
        strategy = GradleDepTreeStrategy(
            runner=mock_runner,
        )
        with tempfile.TemporaryDirectory() as td:
            ok = strategy.generate_adg(
                "/repo",
                str(Path(td) / "bom"),
                {},
            )
            self.assertFalse(ok)


class TestRunGradleDepTreeEdge(unittest.TestCase):
    """Edge cases for run_gradle_dep_tree."""

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".subprocess.run"
    )
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            with patch("builtins.print"):
                result = run_gradle_dep_tree(td)
        self.assertIsNone(result)

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".subprocess.run"
    )
    def test_offline_no_daemon(self, mock_run):
        """dep:tree must use --offline and omit --no-daemon
        to reuse the warm Gradle daemon."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            run_gradle_dep_tree(td)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--offline", cmd)
        self.assertNotIn("--no-daemon", cmd)


class TestFindGradleSubprojectsEdge(unittest.TestCase):
    """Edge cases for find_gradle_subprojects."""

    def test_settings_oserror(self):
        with tempfile.TemporaryDirectory() as td:
            # Create dir instead of file to trigger OSError
            s = Path(td) / "settings.gradle"
            s.mkdir()
            result = find_gradle_subprojects(td)
        self.assertEqual(result, [])

    def test_colon_prefix_subproject(self):
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "settings.gradle"
            s.write_text(
                "include 'sub1', ':sub2'\n"
            )
            result = find_gradle_subprojects(td)
        self.assertIn("sub1", result)
        self.assertIn(":sub2", result)


class TestRunGradleAllDepTrees(unittest.TestCase):
    """Tests for run_gradle_all_dep_trees (single invocation)."""

    def test_no_gradlew_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                self.assertIsNone(run_gradle_all_dep_trees(td))

    @patch("app.pipeline.gradle_dep_tree_parser.subprocess.run")
    def test_success_flags_and_cleanup(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=_MULTI_PROJECT_REPORT,
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            out = run_gradle_all_dep_trees(td)
        self.assertEqual(out, _MULTI_PROJECT_REPORT)
        cmd = mock_run.call_args[0][0]
        self.assertIn("omniborDeps", cmd)
        self.assertIn("--init-script", cmd)
        self.assertIn("--offline", cmd)
        self.assertIn("--continue", cmd)
        self.assertNotIn("-q", cmd)
        # The temp init script is removed after the invocation.
        init_path = cmd[cmd.index("--init-script") + 1]
        self.assertFalse(Path(init_path).exists())

    @patch("app.pipeline.gradle_dep_tree_parser.subprocess.run")
    def test_empty_stdout_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            self.assertIsNone(run_gradle_all_dep_trees(td))

    @patch("app.pipeline.gradle_dep_tree_parser.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("gradlew", 600)
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            with patch("builtins.print"):
                self.assertIsNone(run_gradle_all_dep_trees(td))

    @patch("app.pipeline.gradle_dep_tree_parser.subprocess.run")
    def test_file_not_found_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            with patch("builtins.print"):
                self.assertIsNone(run_gradle_all_dep_trees(td))

    @patch("app.pipeline.gradle_dep_tree_parser.subprocess.run")
    def test_cleanup_oserror_swallowed(self, mock_run):
        """A failure to delete the temp init script must not raise."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=_MULTI_PROJECT_REPORT,
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            with patch(
                "app.pipeline.gradle_dep_tree_parser.os.unlink",
                side_effect=OSError,
            ):
                out = run_gradle_all_dep_trees(td)
        self.assertEqual(out, _MULTI_PROJECT_REPORT)
        # os.unlink is restored here; clean up the leaked temp file.
        init_path = mock_run.call_args[0][0][
            mock_run.call_args[0][0].index("--init-script") + 1
        ]
        Path(init_path).unlink(missing_ok=True)


class TestSplitDepReportSections(unittest.TestCase):
    """Tests for _split_dep_report_sections."""

    def test_splits_projects(self):
        sections = _split_dep_report_sections(_MULTI_PROJECT_REPORT)
        self.assertEqual(set(sections), {":util", ":core"})

    def test_description_suffix_handled(self):
        sections = _split_dep_report_sections(_MULTI_PROJECT_REPORT)
        self.assertIn("com.a:b:1.0", sections[":util"])

    def test_root_project_key(self):
        report = (
            f"{_DASHES}\n"
            "Root project 'demo'\n"
            f"{_DASHES}\n"
            "runtimeClasspath\n"
            "+--- com.x:y:1.0\n"
        )
        sections = _split_dep_report_sections(report)
        self.assertIn(":", sections)

    def test_no_headers_empty(self):
        self.assertEqual(
            _split_dep_report_sections("no headers here"), {},
        )


class TestGetAllGradleDepsPrimary(unittest.TestCase):
    """get_all_gradle_deps uses the single-invocation report."""

    @patch(
        "app.pipeline.gradle_dep_tree_parser.run_gradle_all_dep_trees"
    )
    def test_single_invocation_parses_modules(self, mock_all):
        mock_all.return_value = _MULTI_PROJECT_REPORT
        modules = get_all_gradle_deps("/repo")
        keys = {m["key"] for m in modules}
        self.assertEqual(keys, {":util", ":core"})
        util = next(m for m in modules if m["key"] == ":util")
        names = {d["artifactId"] for d in util["deps"]}
        self.assertEqual(names, {"b", "d"})

    @patch(
        "app.pipeline.gradle_dep_tree_parser.run_gradle_all_dep_trees"
    )
    def test_project_field_derived_from_key(self, mock_all):
        mock_all.return_value = _MULTI_PROJECT_REPORT
        modules = get_all_gradle_deps("/repo")
        util = next(m for m in modules if m["key"] == ":util")
        self.assertEqual(util["project"], "util")


class TestGetAllGradleDepsFallback(unittest.TestCase):
    """Falls back to per-subproject capture when the single-invocation
    report yields no parseable sections."""

    @patch(
        "app.pipeline.gradle_dep_tree_parser.run_gradle_all_dep_trees"
    )
    @patch("app.pipeline.gradle_dep_tree_parser.run_gradle_dep_tree")
    def test_per_subproject_modules(self, mock_run, mock_all):
        mock_all.return_value = None
        mock_run.side_effect = [
            # Root project
            "runtimeClasspath\n+--- com.a:b:1.0\n",
            # Subproject
            "runtimeClasspath\n+--- com.c:d:2.0\n",
        ]
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "settings.gradle"
            s.write_text("include 'sub'\n")
            modules = get_all_gradle_deps(td)
        self.assertEqual(len(modules), 2)
        keys = {m["key"] for m in modules}
        self.assertEqual(keys, {":", ":sub"})

    @patch(
        "app.pipeline.gradle_dep_tree_parser.run_gradle_all_dep_trees"
    )
    @patch("app.pipeline.gradle_dep_tree_parser.run_gradle_dep_tree")
    def test_no_cross_subproject_dedup(self, mock_run, mock_all):
        """A dependency used by two subprojects must appear in
        BOTH module subtrees (no cross-subproject dedup)."""
        mock_all.return_value = None
        mock_run.side_effect = [
            "runtimeClasspath\n+--- com.a:b:1.0\n",
            "runtimeClasspath\n+--- com.a:b:1.0\n",
        ]
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "settings.gradle"
            s.write_text("include 'sub'\n")
            modules = get_all_gradle_deps(td)
        self.assertEqual(len(modules), 2)
        for module in modules:
            names = {
                d["artifactId"] for d in module["deps"]
            }
            self.assertIn("b", names)


if __name__ == "__main__":
    unittest.main()
