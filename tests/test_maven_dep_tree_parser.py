"""
Tests for app/pipeline/maven_dep_tree_parser.py.

Tests the Maven ``dependency:tree`` default-text per-module parser
with realistic fixture data from real Maven projects.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.pipeline.maven_dep_tree_parser import (
    parse_maven_coordinate,
    parse_text_output,
    filter_production_deps,
    classify_scopes,
    run_maven_dep_tree,
)


# ============================================================
# Fixture: single-module project text output
# ============================================================

# Simplified output from dependency-check-core
_SINGLE_MODULE_TEXT = "\n".join([
    "[INFO] --- dependency:3.6.1:tree (default-cli) @"
    " dependency-check-core ---",
    "[INFO] org.owasp:dependency-check-core:jar:9.0.9",
    "[INFO] +- org.slf4j:slf4j-api:jar:2.0.7:compile",
    "[INFO] +- commons-io:commons-io:jar:2.15.1:compile",
    "[INFO] +- org.apache.commons:commons-lang3:jar:3.14.0"
    ":compile",
    "[INFO] |  \\- org.apache.commons:commons-text:jar:1.11.0"
    ":compile",
    "[INFO] +- org.projectlombok:lombok:jar:1.18.30:provided"
    " (optional)",
    "[INFO] \\- org.junit.jupiter:junit-jupiter:jar:5.10.1:test",
    "[INFO]    \\- org.junit.jupiter:junit-jupiter-api:jar:5.10.1"
    ":test",
    "[INFO]       \\- org.opentest4j:opentest4j:jar:1.3.0:test",
]) + "\n"

# ============================================================
# Fixture: multi-module project text output
# ============================================================
# guava is shared by BOTH the core and web modules; it must
# appear under each (no cross-module de-duplication).

_MULTI_MODULE_TEXT = "\n".join([
    "[INFO] --- dependency:3.6.1:tree (default-cli) @ parent ---",
    "[INFO] com.example:parent:pom:1.0.0",
    "[INFO] ",
    "[INFO] --- dependency:3.6.1:tree (default-cli) @ core ---",
    "[INFO] com.example:core:jar:1.0.0",
    "[INFO] +- org.slf4j:slf4j-api:jar:2.0.7:compile",
    "[INFO] \\- com.google.guava:guava:jar:32.1.3-jre:compile",
    "[INFO] ",
    "[INFO] --- dependency:3.6.1:tree (default-cli) @ web ---",
    "[INFO] com.example:web:war:1.0.0",
    "[INFO] +- com.example:core:jar:1.0.0:compile",
    "[INFO] +- com.google.guava:guava:jar:32.1.3-jre:compile",
    "[INFO] +- javax.servlet:javax.servlet-api:jar:4.0.1"
    ":provided",
    "[INFO] \\- org.mockito:mockito-core:jar:5.8.0:test",
    "[INFO]    \\- net.bytebuddy:byte-buddy:jar:1.14.10:test",
]) + "\n"

# ============================================================
# Fixture: root-only module (no dependencies)
# ============================================================

_ROOT_ONLY_TEXT = "[INFO] com.example:app:jar:2.0.0\n"

# ============================================================
# Fixture: all production + test scopes
# ============================================================

_SCOPES_TEXT = "\n".join([
    "[INFO] com.example:app:jar:1.0.0",
    "[INFO] +- com.oracle:ojdbc8:jar:21.9.0:system",
    "[INFO] +- org.slf4j:slf4j-api:jar:2.0.7:runtime",
    "[INFO] +- org.projectlombok:lombok:jar:1.18.30:provided",
    "[INFO] \\- org.junit:junit:jar:4.13.2:test",
]) + "\n"


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
# Tests: parse_text_output
# ============================================================

class TestParseTextOutput(unittest.TestCase):
    """Tests for parse_text_output()."""

    @staticmethod
    def _module(modules, key):
        return next(m for m in modules if m["key"] == key)

    @staticmethod
    def _single_deps():
        return parse_text_output(_SINGLE_MODULE_TEXT)[0]["deps"]

    def test_single_module_key(self):
        modules = parse_text_output(_SINGLE_MODULE_TEXT)
        self.assertEqual(len(modules), 1)
        self.assertEqual(
            modules[0]["key"],
            "org.owasp:dependency-check-core",
        )
        self.assertEqual(modules[0]["version"], "9.0.9")

    def test_single_module_direct_deps(self):
        direct = [d for d in self._single_deps() if d["direct"]]
        names = {d["artifactId"] for d in direct}
        self.assertEqual(len(direct), 5)
        self.assertIn("slf4j-api", names)
        self.assertIn("commons-io", names)
        self.assertIn("commons-lang3", names)
        self.assertIn("lombok", names)
        self.assertIn("junit-jupiter", names)

    def test_single_module_transitive_deps(self):
        deps = self._single_deps()
        transitive = [d for d in deps if not d["direct"]]
        names = {d["artifactId"] for d in transitive}
        self.assertIn("commons-text", names)
        self.assertIn("junit-jupiter-api", names)
        self.assertIn("opentest4j", names)

    def test_transitive_parent_set(self):
        text = next(
            d for d in self._single_deps()
            if d["artifactId"] == "commons-text"
        )
        self.assertEqual(text["parent"], "commons-lang3")
        self.assertFalse(text["direct"])

    def test_nested_transitive_parent(self):
        opentest = next(
            d for d in self._single_deps()
            if d["artifactId"] == "opentest4j"
        )
        self.assertEqual(
            opentest["parent"], "junit-jupiter-api",
        )

    def test_direct_parent_is_none(self):
        slf4j = next(
            d for d in self._single_deps()
            if d["artifactId"] == "slf4j-api"
        )
        self.assertIsNone(slf4j["parent"])
        self.assertTrue(slf4j["direct"])

    def test_optional_flag_preserved(self):
        deps = self._single_deps()
        lombok = next(
            d for d in deps if d["artifactId"] == "lombok"
        )
        self.assertTrue(lombok["optional"])
        slf4j = next(
            d for d in deps if d["artifactId"] == "slf4j-api"
        )
        self.assertFalse(slf4j["optional"])

    def test_scope_parsed(self):
        slf4j = next(
            d for d in self._single_deps()
            if d["artifactId"] == "slf4j-api"
        )
        self.assertEqual(slf4j["scope"], "compile")

    def test_multi_module_keys(self):
        modules = parse_text_output(_MULTI_MODULE_TEXT)
        keys = {m["key"] for m in modules}
        self.assertIn("com.example:parent", keys)
        self.assertIn("com.example:core", keys)
        self.assertIn("com.example:web", keys)

    def test_parent_module_has_no_deps(self):
        modules = parse_text_output(_MULTI_MODULE_TEXT)
        parent = self._module(modules, "com.example:parent")
        self.assertEqual(parent["deps"], [])

    def test_shared_component_in_both_modules(self):
        """A component shared by two modules must appear in BOTH
        (no cross-module de-duplication)."""
        modules = parse_text_output(_MULTI_MODULE_TEXT)
        core = self._module(modules, "com.example:core")
        web = self._module(modules, "com.example:web")
        core_names = {d["artifactId"] for d in core["deps"]}
        web_names = {d["artifactId"] for d in web["deps"]}
        self.assertIn("guava", core_names)
        self.assertIn("guava", web_names)

    def test_multi_module_provided_scope(self):
        modules = parse_text_output(_MULTI_MODULE_TEXT)
        web = self._module(modules, "com.example:web")
        servlet = next(
            d for d in web["deps"]
            if d["artifactId"] == "javax.servlet-api"
        )
        self.assertEqual(servlet["scope"], "provided")

    def test_root_only_module_empty_deps(self):
        modules = parse_text_output(_ROOT_ONLY_TEXT)
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["deps"], [])

    def test_no_info_prefix(self):
        """Works with raw text (no [INFO] prefixes)."""
        raw = "\n".join([
            "a.b:c:jar:1.0",
            "+- d.e:f:jar:2.0:compile",
        ]) + "\n"
        modules = parse_text_output(raw)
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["key"], "a.b:c")
        self.assertEqual(
            modules[0]["deps"][0]["artifactId"], "f",
        )

    def test_empty_string(self):
        self.assertEqual(parse_text_output(""), [])

    def test_garbage_input(self):
        self.assertEqual(
            parse_text_output("not a dependency tree"), [],
        )


# ============================================================
# Tests: filter_production_deps
# ============================================================

class TestFilterProductionDeps(unittest.TestCase):
    """Tests for filter_production_deps()."""

    @staticmethod
    def _single_deps():
        return parse_text_output(_SINGLE_MODULE_TEXT)[0]["deps"]

    @staticmethod
    def _scope_deps():
        return parse_text_output(_SCOPES_TEXT)[0]["deps"]

    def test_removes_test_scope(self):
        prod = filter_production_deps(self._single_deps())
        test_deps = [d for d in prod if d["scope"] == "test"]
        self.assertEqual(test_deps, [])

    def test_keeps_compile_scope(self):
        prod = filter_production_deps(self._single_deps())
        names = {d["artifactId"] for d in prod}
        self.assertIn("slf4j-api", names)
        self.assertIn("commons-io", names)

    def test_keeps_provided_scope(self):
        prod = filter_production_deps(self._scope_deps())
        names = {d["artifactId"] for d in prod}
        self.assertIn("lombok", names)

    def test_keeps_system_scope(self):
        prod = filter_production_deps(self._scope_deps())
        names = {d["artifactId"] for d in prod}
        self.assertIn("ojdbc8", names)

    def test_keeps_runtime_scope(self):
        prod = filter_production_deps(self._scope_deps())
        names = {d["artifactId"] for d in prod}
        self.assertIn("slf4j-api", names)

    def test_empty_list(self):
        self.assertEqual(filter_production_deps([]), [])


# ============================================================
# Tests: classify_scopes
# ============================================================

class TestClassifyScopes(unittest.TestCase):
    """Tests for classify_scopes()."""

    @staticmethod
    def _scope_deps():
        return parse_text_output(_SCOPES_TEXT)[0]["deps"]

    def test_scopes_classified(self):
        by_scope = classify_scopes(self._scope_deps())
        self.assertIn("system", by_scope)
        self.assertIn("runtime", by_scope)
        self.assertIn("provided", by_scope)
        self.assertIn("test", by_scope)

    def test_counts(self):
        by_scope = classify_scopes(self._scope_deps())
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
            stdout=_SINGLE_MODULE_TEXT,
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            result = run_maven_dep_tree(td)
        self.assertEqual(result, _SINGLE_MODULE_TEXT)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="BUILD FAILURE",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            with patch("builtins.print"):
                result = run_maven_dep_tree(td)
            self.assertIsNone(result)
        # Offline attempt + online fallback = 2 invocations
        self.assertEqual(mock_run.call_count, 2)

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

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_offline_and_skip_flags(self, mock_run):
        """dep:tree must run offline with skip flags to
        minimise Phase 1 build-time impact."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            run_maven_dep_tree(td)
        cmd = mock_run.call_args[0][0]
        self.assertIn("-o", cmd)
        self.assertIn("-DskipTests", cmd)
        self.assertIn(
            "-Dmaven.javadoc.skip=true", cmd,
        )
        self.assertIn(
            "-Denforcer.skip=true", cmd,
        )
        self.assertIn(
            "-Dcheckstyle.skip=true", cmd,
        )
        # Default text output is used (DOT cannot carry the
        # optional flag); -DoutputType must not be forced to dot.
        self.assertNotIn("-DoutputType=dot", cmd)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_offline_failure_falls_back_online(
        self, mock_run,
    ):
        """When the offline attempt fails, dep:tree retries
        online and returns the online output."""
        mock_run.side_effect = [
            MagicMock(
                returncode=1,
                stdout="No plugin found for prefix "
                       "'dependency'",
                stderr="",
            ),
            MagicMock(
                returncode=0,
                stdout=_SINGLE_MODULE_TEXT,
                stderr="",
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            with patch("builtins.print"):
                result = run_maven_dep_tree(td)
        self.assertEqual(result, _SINGLE_MODULE_TEXT)
        self.assertEqual(mock_run.call_count, 2)
        # First attempt is offline (-o); the fallback is not
        first_cmd = mock_run.call_args_list[0][0][0]
        second_cmd = mock_run.call_args_list[1][0][0]
        self.assertIn("-o", first_cmd)
        self.assertNotIn("-o", second_cmd)

    @patch("app.pipeline.maven_dep_tree_parser"
           ".subprocess.run")
    def test_both_attempts_fail_logs_stdout(
        self, mock_run,
    ):
        """Maven writes resolution errors to stdout; the
        final error log must include that output."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="No plugin found for prefix "
                   "'dependency'",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            with patch("builtins.print") as mock_print:
                result = run_maven_dep_tree(td)
        self.assertIsNone(result)
        self.assertEqual(mock_run.call_count, 2)
        printed = " ".join(
            str(c.args[0])
            for c in mock_print.call_args_list
        )
        self.assertIn("No plugin found", printed)


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
        mock_run.return_value = _SINGLE_MODULE_TEXT
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
            capture_file = bom_dir / "maven_deps.json"
            self.assertTrue(capture_file.exists())
            capture = json.loads(capture_file.read_text())
            self.assertEqual(capture["tool"], "maven")
            self.assertEqual(
                capture["modules"][0]["key"],
                "org.owasp:dependency-check-core",
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
