"""
Tests for app/pipeline/gradle_dep_tree_parser.py.

Tests the Gradle dependency tree parser wrapper and
GradleDepTreeStrategy with realistic fixture data.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.pipeline.gradle_dep_tree_parser import (
    parse_gradle_output,
    run_gradle_dep_tree,
    find_gradle_subprojects,
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
# Fixture: version conflict
# ============================================================

_VERSION_CONFLICT_OUTPUT = """\
runtimeClasspath - Runtime classpath of source set 'main'.
+--- org.slf4j:slf4j-api:2.0.7
+--- com.example:lib-a:1.0.0
|    \\--- org.slf4j:slf4j-api:1.7.36 -> 2.0.7 (*)
\\--- com.example:lib-b:2.0.0
     \\--- org.slf4j:slf4j-api:2.0.0 -> 2.0.7 (*)
"""

# ============================================================
# Fixture: empty output
# ============================================================

_EMPTY_OUTPUT = """\
runtimeClasspath - Runtime classpath of source set 'main'.
No dependencies
"""


# ============================================================
# Tests: parse_gradle_output
# ============================================================

class TestParseGradleOutput(unittest.TestCase):
    """Tests for parse_gradle_output()."""

    def test_single_project_deps(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        names = {d["artifactId"] for d in deps}
        self.assertIn("slf4j-api", names)
        self.assertIn("guava", names)
        self.assertIn("commons-lang3", names)
        self.assertIn("jackson-databind", names)

    def test_transitive_deps(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        transitive = [
            d for d in deps if not d["direct"]
        ]
        names = {d["artifactId"] for d in transitive}
        self.assertIn("failureaccess", names)
        self.assertIn("jackson-core", names)

    def test_direct_deps(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        direct = [d for d in deps if d["direct"]]
        self.assertEqual(len(direct), 4)

    def test_output_format_has_required_keys(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        required = {
            "groupId", "artifactId", "version",
            "scope", "packaging", "direct",
            "parent", "is_test", "module",
        }
        for d in deps:
            self.assertTrue(
                required.issubset(d.keys()),
                f"Missing keys in {d}",
            )

    def test_packaging_defaults_to_jar(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        for d in deps:
            self.assertEqual(d["packaging"], "jar")

    def test_version_conflict_resolved(self):
        deps = parse_gradle_output(
            _VERSION_CONFLICT_OUTPUT,
        )
        slf4j = [
            d for d in deps
            if d["artifactId"] == "slf4j-api"
        ]
        self.assertEqual(len(slf4j), 1)
        self.assertEqual(slf4j[0]["version"], "2.0.7")

    def test_empty_output(self):
        deps = parse_gradle_output(_EMPTY_OUTPUT)
        self.assertEqual(deps, [])

    def test_empty_string(self):
        deps = parse_gradle_output("")
        self.assertEqual(deps, [])

    def test_scope_is_compile(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        for d in deps:
            self.assertEqual(d["scope"], "compile")

    def test_not_test_scope(self):
        deps = parse_gradle_output(
            _SINGLE_PROJECT_OUTPUT,
        )
        for d in deps:
            self.assertFalse(d["is_test"])


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
            self.assertTrue(
                (bom_dir / "gradle_deps.json").exists()
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
        result = run_gradle_dep_tree("/repo")
        self.assertIsNone(result)


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


class TestGetAllGradleDeps(unittest.TestCase):
    """Tests for get_all_gradle_deps."""

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".run_gradle_dep_tree"
    )
    def test_subproject_deps_merged(self, mock_run):
        from app.pipeline.gradle_dep_tree_parser import (
            get_all_gradle_deps,
        )
        mock_run.side_effect = [
            # Root project
            (
                "runtimeClasspath\n"
                "+--- com.a:b:1.0\n"
            ),
            # Subproject
            (
                "runtimeClasspath\n"
                "+--- com.c:d:2.0\n"
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "settings.gradle"
            s.write_text("include 'sub'\n")
            deps = get_all_gradle_deps(td)
        self.assertEqual(len(deps), 2)

    @patch(
        "app.pipeline.gradle_dep_tree_parser"
        ".run_gradle_dep_tree"
    )
    def test_dedup_across_projects(self, mock_run):
        from app.pipeline.gradle_dep_tree_parser import (
            get_all_gradle_deps,
        )
        mock_run.side_effect = [
            (
                "runtimeClasspath\n"
                "+--- com.a:b:1.0\n"
            ),
            (
                "runtimeClasspath\n"
                "+--- com.a:b:1.0\n"
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            s = Path(td) / "settings.gradle"
            s.write_text("include 'sub'\n")
            deps = get_all_gradle_deps(td)
        # Deduped: same groupId:artifactId
        self.assertEqual(len(deps), 1)


if __name__ == "__main__":
    unittest.main()
