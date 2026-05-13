"""
Tests for app/pipeline/maven_dep_tree_parser.py.

Tests the Maven ``dependency:tree`` DOT format parser
with realistic fixture data from real Maven projects.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.pipeline.maven_dep_tree_parser import (
    parse_maven_coordinate,
    parse_dot_output,
    filter_production_deps,
    classify_scopes,
    run_maven_dep_tree,
)


# ============================================================
# Fixture: single-module project DOT output
# ============================================================

# Simplified output from dependency-check-core
_SINGLE_MODULE_DOT = (
    '[INFO] --- dependency:3.6.1:tree'
    ' (default-cli) @'
    ' dependency-check-core ---\n'
    '[INFO] digraph'
    ' "org.owasp:dependency-check-core'
    ':jar:9.0.9" {\n'
    '[INFO]    "org.owasp:dependency-check'
    '-core:jar:9.0.9" ->'
    ' "org.slf4j:slf4j-api'
    ':jar:2.0.7:compile" ;\n'
    '[INFO]    "org.owasp:dependency-check'
    '-core:jar:9.0.9" ->'
    ' "commons-io:commons-io'
    ':jar:2.15.1:compile" ;\n'
    '[INFO]    "org.owasp:dependency-check'
    '-core:jar:9.0.9" ->'
    ' "org.apache.commons:commons-lang3'
    ':jar:3.14.0:compile" ;\n'
    '[INFO]    "org.owasp:dependency-check'
    '-core:jar:9.0.9" ->'
    ' "org.junit.jupiter:junit-jupiter'
    ':jar:5.10.1:test" ;\n'
    '[INFO]    "org.apache.commons'
    ':commons-lang3:jar:3.14.0:compile"'
    ' -> "org.apache.commons'
    ':commons-text:jar:1.11.0:compile"'
    ' ;\n'
    '[INFO]    "org.junit.jupiter'
    ':junit-jupiter:jar:5.10.1:test"'
    ' -> "org.junit.jupiter'
    ':junit-jupiter-api'
    ':jar:5.10.1:test" ;\n'
    '[INFO]    "org.junit.jupiter'
    ':junit-jupiter-api'
    ':jar:5.10.1:test" ->'
    ' "org.opentest4j:opentest4j'
    ':jar:1.3.0:test" ;\n'
    '[INFO] }\n'
)

# ============================================================
# Fixture: multi-module project DOT output
# ============================================================

_MULTI_MODULE_DOT = (
    '[INFO] --- dependency:3.6.1:tree'
    ' (default-cli) @ parent ---\n'
    '[INFO] digraph'
    ' "com.example:parent:pom:1.0.0"'
    ' {\n'
    '[INFO] }\n'
    '[INFO]\n'
    '[INFO] --- dependency:3.6.1:tree'
    ' (default-cli) @ core ---\n'
    '[INFO] digraph'
    ' "com.example:core:jar:1.0.0"'
    ' {\n'
    '[INFO]    "com.example:core'
    ':jar:1.0.0" ->'
    ' "org.slf4j:slf4j-api'
    ':jar:2.0.7:compile" ;\n'
    '[INFO]    "com.example:core'
    ':jar:1.0.0" ->'
    ' "com.google.guava:guava'
    ':jar:32.1.3-jre:compile" ;\n'
    '[INFO] }\n'
    '[INFO]\n'
    '[INFO] --- dependency:3.6.1:tree'
    ' (default-cli) @ web ---\n'
    '[INFO] digraph'
    ' "com.example:web:war:1.0.0"'
    ' {\n'
    '[INFO]    "com.example:web'
    ':war:1.0.0" ->'
    ' "com.example:core'
    ':jar:1.0.0:compile" ;\n'
    '[INFO]    "com.example:web'
    ':war:1.0.0" ->'
    ' "javax.servlet:javax.servlet-api'
    ':jar:4.0.1:provided" ;\n'
    '[INFO]    "com.example:web'
    ':war:1.0.0" ->'
    ' "org.mockito:mockito-core'
    ':jar:5.8.0:test" ;\n'
    '[INFO]    "org.mockito:mockito-core'
    ':jar:5.8.0:test" ->'
    ' "net.bytebuddy:byte-buddy'
    ':jar:1.14.10:test" ;\n'
    '[INFO] }\n'
)

# ============================================================
# Fixture: no-scope root node (DOT format edge case)
# ============================================================

_ROOT_ONLY_DOT = """\
digraph "com.example:app:jar:2.0.0" {
}
"""

# ============================================================
# Fixture: version conflict (managed version wins)
# ============================================================

_VERSION_CONFLICT_DOT = (
    'digraph "com.example:app:jar:1.0.0"'
    ' {\n'
    '    "com.example:app:jar:1.0.0" ->'
    ' "org.apache:commons-lang3'
    ':jar:3.14.0:compile" ;\n'
    '    "com.example:app:jar:1.0.0" ->'
    ' "com.foo:bar:jar:1.0.0:compile"'
    ' ;\n'
    '    "com.foo:bar:jar:1.0.0:compile"'
    ' -> "org.apache:commons-lang3'
    ':jar:3.12.0:compile" ;\n'
    '}\n'
)

# ============================================================
# Fixture: optional and system scope
# ============================================================

_SCOPES_DOT = (
    'digraph "com.example:app:jar:1.0.0"'
    ' {\n'
    '    "com.example:app:jar:1.0.0" ->'
    ' "com.oracle:ojdbc8'
    ':jar:21.9.0:system" ;\n'
    '    "com.example:app:jar:1.0.0" ->'
    ' "org.slf4j:slf4j-api'
    ':jar:2.0.7:runtime" ;\n'
    '    "com.example:app:jar:1.0.0" ->'
    ' "org.projectlombok:lombok'
    ':jar:1.18.30:provided" ;\n'
    '    "com.example:app:jar:1.0.0" ->'
    ' "org.junit:junit'
    ':jar:4.13.2:test" ;\n'
    '}\n'
)


# ============================================================
# Tests: parse_maven_coordinate
# ============================================================

class TestParseMavenCoordinate(unittest.TestCase):
    """Tests for parse_maven_coordinate()."""

    def test_four_part_root(self):
        result = parse_maven_coordinate(
            "com.example:app:jar:1.0.0"
        )
        self.assertEqual(result["groupId"], "com.example")
        self.assertEqual(result["artifactId"], "app")
        self.assertEqual(result["packaging"], "jar")
        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(result["scope"], "")

    def test_five_part_with_scope(self):
        result = parse_maven_coordinate(
            "org.slf4j:slf4j-api:jar:2.0.7:compile"
        )
        self.assertEqual(result["groupId"], "org.slf4j")
        self.assertEqual(result["artifactId"], "slf4j-api")
        self.assertEqual(result["packaging"], "jar")
        self.assertEqual(result["version"], "2.0.7")
        self.assertEqual(result["scope"], "compile")

    def test_test_scope(self):
        result = parse_maven_coordinate(
            "org.junit:junit:jar:4.13.2:test"
        )
        self.assertEqual(result["scope"], "test")

    def test_war_packaging(self):
        result = parse_maven_coordinate(
            "com.example:web:war:1.0.0"
        )
        self.assertEqual(result["packaging"], "war")

    def test_malformed_too_few_parts(self):
        self.assertIsNone(
            parse_maven_coordinate("com.example:app")
        )

    def test_malformed_too_many_parts(self):
        self.assertIsNone(
            parse_maven_coordinate(
                "a:b:c:d:e:f"
            )
        )

    def test_empty_string(self):
        self.assertIsNone(parse_maven_coordinate(""))

    def test_jre_classifier_in_version(self):
        result = parse_maven_coordinate(
            "com.google.guava:guava:jar:"
            "32.1.3-jre:compile"
        )
        self.assertEqual(result["version"], "32.1.3-jre")


# ============================================================
# Tests: parse_dot_output
# ============================================================

class TestParseDotOutput(unittest.TestCase):
    """Tests for parse_dot_output()."""

    def test_single_module_direct_deps(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        direct = [d for d in deps if d["direct"]]
        self.assertEqual(len(direct), 4)
        names = {d["artifactId"] for d in direct}
        self.assertIn("slf4j-api", names)
        self.assertIn("commons-io", names)
        self.assertIn("commons-lang3", names)
        self.assertIn("junit-jupiter", names)

    def test_single_module_transitive_deps(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        transitive = [d for d in deps if not d["direct"]]
        self.assertEqual(len(transitive), 3)
        names = {d["artifactId"] for d in transitive}
        self.assertIn("commons-text", names)
        self.assertIn("junit-jupiter-api", names)
        self.assertIn("opentest4j", names)

    def test_transitive_parent_set(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        text = next(
            d for d in deps
            if d["artifactId"] == "commons-text"
        )
        self.assertEqual(text["parent"], "commons-lang3")
        self.assertFalse(text["direct"])

    def test_direct_parent_is_none(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        slf4j = next(
            d for d in deps
            if d["artifactId"] == "slf4j-api"
        )
        self.assertIsNone(slf4j["parent"])
        self.assertTrue(slf4j["direct"])

    def test_test_scope_flagged(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        test_deps = [d for d in deps if d["is_test"]]
        self.assertTrue(len(test_deps) >= 1)
        names = {d["artifactId"] for d in test_deps}
        self.assertIn("junit-jupiter", names)

    def test_compile_scope_not_test(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        slf4j = next(
            d for d in deps
            if d["artifactId"] == "slf4j-api"
        )
        self.assertFalse(slf4j["is_test"])
        self.assertEqual(slf4j["scope"], "compile")

    def test_multi_module_all_deps(self):
        deps = parse_dot_output(_MULTI_MODULE_DOT)
        names = {d["artifactId"] for d in deps}
        self.assertIn("slf4j-api", names)
        self.assertIn("guava", names)
        self.assertIn("javax.servlet-api", names)
        self.assertIn("mockito-core", names)
        self.assertIn("byte-buddy", names)
        # core is a sibling module dependency
        self.assertIn("core", names)

    def test_multi_module_provided_scope(self):
        deps = parse_dot_output(_MULTI_MODULE_DOT)
        servlet = next(
            d for d in deps
            if d["artifactId"] == "javax.servlet-api"
        )
        self.assertEqual(servlet["scope"], "provided")

    def test_empty_digraph(self):
        deps = parse_dot_output(_ROOT_ONLY_DOT)
        self.assertEqual(deps, [])

    def test_version_conflict_dedup(self):
        deps = parse_dot_output(_VERSION_CONFLICT_DOT)
        lang3 = [
            d for d in deps
            if d["artifactId"] == "commons-lang3"
        ]
        # First occurrence wins (direct dep at 3.14.0)
        self.assertEqual(len(lang3), 1)
        self.assertEqual(lang3[0]["version"], "3.14.0")

    def test_no_info_prefix(self):
        """Works with raw DOT (no [INFO] prefixes)."""
        raw = (
            'digraph "a:b:jar:1.0" {\n'
            '  "a:b:jar:1.0" -> '
            '"c:d:jar:2.0:compile" ;\n'
            '}\n'
        )
        deps = parse_dot_output(raw)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["artifactId"], "d")

    def test_empty_string(self):
        self.assertEqual(parse_dot_output(""), [])

    def test_garbage_input(self):
        self.assertEqual(
            parse_dot_output("not a dot graph"), []
        )


# ============================================================
# Tests: filter_production_deps
# ============================================================

class TestFilterProductionDeps(unittest.TestCase):
    """Tests for filter_production_deps()."""

    def test_removes_test_scope(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        prod = filter_production_deps(deps)
        test_deps = [d for d in prod if d["is_test"]]
        self.assertEqual(test_deps, [])

    def test_keeps_compile_scope(self):
        deps = parse_dot_output(_SINGLE_MODULE_DOT)
        prod = filter_production_deps(deps)
        names = {d["artifactId"] for d in prod}
        self.assertIn("slf4j-api", names)
        self.assertIn("commons-io", names)

    def test_keeps_provided_scope(self):
        deps = parse_dot_output(_SCOPES_DOT)
        prod = filter_production_deps(deps)
        names = {d["artifactId"] for d in prod}
        self.assertIn("lombok", names)

    def test_keeps_system_scope(self):
        deps = parse_dot_output(_SCOPES_DOT)
        prod = filter_production_deps(deps)
        names = {d["artifactId"] for d in prod}
        self.assertIn("ojdbc8", names)

    def test_keeps_runtime_scope(self):
        deps = parse_dot_output(_SCOPES_DOT)
        prod = filter_production_deps(deps)
        names = {d["artifactId"] for d in prod}
        self.assertIn("slf4j-api", names)

    def test_empty_list(self):
        self.assertEqual(filter_production_deps([]), [])


# ============================================================
# Tests: classify_scopes
# ============================================================

class TestClassifyScopes(unittest.TestCase):
    """Tests for classify_scopes()."""

    def test_scopes_classified(self):
        deps = parse_dot_output(_SCOPES_DOT)
        by_scope = classify_scopes(deps)
        self.assertIn("system", by_scope)
        self.assertIn("runtime", by_scope)
        self.assertIn("provided", by_scope)
        self.assertIn("test", by_scope)

    def test_counts(self):
        deps = parse_dot_output(_SCOPES_DOT)
        by_scope = classify_scopes(deps)
        self.assertEqual(len(by_scope["system"]), 1)
        self.assertEqual(len(by_scope["test"]), 1)

    def test_empty_list(self):
        self.assertEqual(classify_scopes([]), {})


# ============================================================
# Tests: run_maven_dep_tree
# ============================================================

class TestRunMavenDepTree(unittest.TestCase):
    """Tests for run_maven_dep_tree()."""

    def test_no_pom_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                result = run_maven_dep_tree(td)
            self.assertIsNone(result)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_SINGLE_MODULE_DOT,
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            result = run_maven_dep_tree(td)
        self.assertEqual(result, _SINGLE_MODULE_DOT)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="BUILD FAILURE",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            with patch("builtins.print"):
                result = run_maven_dep_tree(td)
            self.assertIsNone(result)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = (
            subprocess.TimeoutExpired("mvn", 120)
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            with patch("builtins.print"):
                result = run_maven_dep_tree(td)
            self.assertIsNone(result)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_mvn_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            with patch("builtins.print"):
                result = run_maven_dep_tree(td)
            self.assertIsNone(result)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_maven_modules_passes_pl_and_am(
        self, mock_run,
    ):
        """When maven_modules is set, -pl and -am must
        both be passed to mvn dependency:tree."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            run_maven_dep_tree(
                td, maven_modules="crawler4j",
            )
        args = mock_run.call_args
        cmd = args[0][0]
        self.assertIn("-pl", cmd)
        self.assertIn("crawler4j", cmd)
        self.assertIn("-am", cmd)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_no_maven_modules_no_pl(self, mock_run):
        """Without maven_modules, -pl and -am must NOT
        appear in the command."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            run_maven_dep_tree(td)
        args = mock_run.call_args
        cmd = args[0][0]
        self.assertNotIn("-pl", cmd)
        self.assertNotIn("-am", cmd)


# ============================================================
# Tests: InterceptionStrategy / MavenDepTreeStrategy
# ============================================================

class TestMavenDepTreeStrategy(unittest.TestCase):
    """Tests for MavenDepTreeStrategy."""

    def test_instrument_command_passthrough(self):
        from app.pipeline.interception import (
            MavenDepTreeStrategy,
        )
        strategy = MavenDepTreeStrategy()
        cmd, env = strategy.instrument_command(
            "mvn package -DskipTests", "/repo"
        )
        self.assertEqual(
            cmd, "mvn package -DskipTests"
        )
        self.assertEqual(env, {})

    @patch("app.pipeline.maven_dep_tree_parser"
           ".run_maven_dep_tree")
    def test_generate_adg_success(self, mock_run):
        from app.pipeline.interception import (
            MavenDepTreeStrategy,
        )
        mock_run.return_value = _SINGLE_MODULE_DOT
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        strategy = MavenDepTreeStrategy(
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
                (bom_dir / "maven_deps.json").exists()
            )
            mock_runner.run.assert_called_once()

    @patch("app.pipeline.maven_dep_tree_parser"
           ".run_maven_dep_tree")
    def test_generate_adg_dep_tree_failure(
        self, mock_run,
    ):
        from app.pipeline.interception import (
            MavenDepTreeStrategy,
        )
        mock_run.return_value = None
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        strategy = MavenDepTreeStrategy(
            runner=mock_runner,
        )
        with tempfile.TemporaryDirectory() as td:
            ok = strategy.generate_adg(
                "/repo", str(Path(td) / "bom"), {},
            )
            self.assertFalse(ok)

    def test_generate_adg_treedb_failure(self):
        from app.pipeline.interception import (
            MavenDepTreeStrategy,
        )
        mock_runner = MagicMock()
        mock_runner.run.return_value = 1
        strategy = MavenDepTreeStrategy(
            runner=mock_runner,
        )
        with tempfile.TemporaryDirectory() as td:
            ok = strategy.generate_adg(
                "/repo", str(Path(td) / "bom"), {},
            )
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
