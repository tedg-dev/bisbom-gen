"""
Tests for app/spdx/dep_capture_reader.py.

Verifies Phase 2 resolution of an output JAR to its Phase 1
dependency-capture module, with no source-tree access.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.spdx.dep_capture_reader import (
    get_module_deps,
    load_capture,
    resolve_module,
)


def _maven_capture():
    return {
        "tool": "maven",
        "modules": [
            {
                "key": "com.example:core",
                "groupId": "com.example",
                "artifactId": "core",
                "version": "1.0",
                "packaging": "jar",
                "deps": [
                    {"groupId": "org.slf4j",
                     "artifactId": "slf4j-api",
                     "version": "2.0.7", "scope": "compile",
                     "direct": True, "optional": False,
                     "parent": None},
                ],
            },
            {
                "key": "com.example:cli",
                "groupId": "com.example",
                "artifactId": "cli",
                "version": "1.0",
                "packaging": "jar",
                "deps": [],
            },
        ],
    }


def _gradle_capture():
    return {
        "tool": "gradle",
        "modules": [
            {"key": ":", "project": None, "deps": []},
            {
                "key": ":core",
                "project": "core",
                "deps": [
                    {"groupId": "com.google.guava",
                     "artifactId": "guava", "version": "32.1.3",
                     "scope": "compile", "direct": True,
                     "optional": False, "parent": None},
                ],
            },
        ],
    }


class TestLoadCapture(unittest.TestCase):
    """Tests for load_capture()."""

    def test_loads_maven(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "maven_deps.json"
            path.write_text(json.dumps(_maven_capture()))
            capture = load_capture(td)
        self.assertEqual(capture["tool"], "maven")

    def test_loads_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "gradle_deps.json"
            path.write_text(json.dumps(_gradle_capture()))
            capture = load_capture(td)
        self.assertEqual(capture["tool"], "gradle")

    def test_prefers_maven_over_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "maven_deps.json").write_text(
                json.dumps(_maven_capture())
            )
            (Path(td) / "gradle_deps.json").write_text(
                json.dumps(_gradle_capture())
            )
            capture = load_capture(td)
        self.assertEqual(capture["tool"], "maven")

    def test_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(load_capture(td))


class TestResolveMaven(unittest.TestCase):
    """Maven JAR -> module resolution."""

    def test_match_by_artifact_name(self):
        module = resolve_module(
            _maven_capture(), "cli",
            "cli/target/cli-1.0.jar",
        )
        self.assertEqual(module["key"], "com.example:cli")

    def test_match_by_dir_backup(self):
        """Custom finalName: filename does not match artifactId,
        so the module directory in the JAR path is used."""
        module = resolve_module(
            _maven_capture(), "custom-final-name",
            "core/target/custom-final-name.jar",
        )
        self.assertEqual(module["key"], "com.example:core")

    def test_single_module_fallback(self):
        capture = {
            "tool": "maven",
            "modules": [{
                "key": "g:a", "groupId": "g",
                "artifactId": "a", "version": "1.0",
                "packaging": "jar", "deps": [],
            }],
        }
        module = resolve_module(
            capture, "unrelated", "target/unrelated.jar",
        )
        self.assertEqual(module["key"], "g:a")

    def test_not_found(self):
        module = resolve_module(
            _maven_capture(), "nope",
            "nope/target/nope.jar",
        )
        self.assertIsNone(module)


class TestResolveGradle(unittest.TestCase):
    """Gradle JAR -> module resolution."""

    def test_match_by_subproject_name(self):
        module = resolve_module(
            _gradle_capture(), "core",
            "core/build/libs/core-1.0.jar",
        )
        self.assertEqual(module["key"], ":core")

    def test_match_by_dir_backup(self):
        module = resolve_module(
            _gradle_capture(), "custom",
            "core/build/libs/custom.jar",
        )
        self.assertEqual(module["key"], ":core")

    def test_root_project_jar(self):
        module = resolve_module(
            _gradle_capture(), "app",
            "build/libs/app.jar",
        )
        self.assertEqual(module["key"], ":")

    def test_single_module_fallback(self):
        capture = {
            "tool": "gradle",
            "modules": [
                {"key": ":only", "project": "only",
                 "deps": []},
            ],
        }
        module = resolve_module(
            capture, "x", "sub/build/libs/x.jar",
        )
        self.assertEqual(module["key"], ":only")

    def test_not_found(self):
        module = resolve_module(
            _gradle_capture(), "missing",
            "missing/build/libs/missing.jar",
        )
        self.assertIsNone(module)


class TestGetModuleDeps(unittest.TestCase):
    """Tests for get_module_deps()."""

    def test_returns_deps(self):
        deps = get_module_deps(
            _maven_capture(), "core",
            "core/target/core-1.0.jar",
        )
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["artifactId"], "slf4j-api")

    def test_found_module_empty_deps(self):
        deps = get_module_deps(
            _maven_capture(), "cli",
            "cli/target/cli-1.0.jar",
        )
        self.assertEqual(deps, [])

    def test_not_found_returns_none(self):
        deps = get_module_deps(
            _maven_capture(), "missing",
            "missing/target/missing.jar",
        )
        self.assertIsNone(deps)


class TestResolveEdgeCases(unittest.TestCase):
    """Edge cases for resolve_module()."""

    def test_empty_capture(self):
        self.assertIsNone(resolve_module(None, "x"))

    def test_no_modules(self):
        self.assertIsNone(
            resolve_module({"tool": "maven", "modules": []}, "x")
        )

    def test_no_jar_path(self):
        module = resolve_module(_maven_capture(), "core")
        self.assertEqual(module["key"], "com.example:core")


if __name__ == "__main__":
    unittest.main()
