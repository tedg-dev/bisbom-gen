"""
Tests for Java pipeline strategy wiring (#109 B4).

Verifies that _select_java_strategy returns the correct
strategy based on mode and build system (Maven vs Gradle).
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.pipeline.lang_runners import (
    _detect_java_build_tool,
    _extract_maven_modules,
    _select_java_strategy,
    run_java_pipeline,
)
from app.pipeline.interception import (
    MavenDepTreeStrategy,
    GradleDepTreeStrategy,
)
from app.pipeline.builder import BuildResult


class TestSelectJavaStrategy(unittest.TestCase):
    """Tests for _select_java_strategy()."""

    def _paths(self):
        return {"repos_dir": "/workspace/repos"}

    def _repo_cfg(self):
        return {
            "url": "https://github.com/example/app.git",
            "language": "java",
            "build_steps": ["mvn package"],
        }

    def test_standalone_returns_none(self):
        result = _select_java_strategy(
            "myapp", self._repo_cfg(),
            self._paths(), "standalone",
        )
        self.assertIsNone(result)

    def test_default_mode_returns_none(self):
        result = _select_java_strategy(
            "myapp", self._repo_cfg(),
            self._paths(), "standalone",
        )
        self.assertIsNone(result)

    @patch(
        "app.spdx.gradle_parser"
        ".is_gradle_project",
        return_value=False,
    )
    def test_sidecar_maven(self, mock_is_gradle):
        result = _select_java_strategy(
            "jsoup", self._repo_cfg(),
            self._paths(), "sidecar",
        )
        self.assertIsInstance(
            result, MavenDepTreeStrategy,
        )
        mock_is_gradle.assert_called_once_with(
            "/workspace/repos/jsoup",
        )

    @patch(
        "app.spdx.gradle_parser"
        ".is_gradle_project",
        return_value=True,
    )
    def test_sidecar_gradle(self, _mock_is_gradle):
        result = _select_java_strategy(
            "checkstyle", self._repo_cfg(),
            self._paths(), "sidecar",
        )
        self.assertIsInstance(
            result, GradleDepTreeStrategy,
        )

    def test_non_sidecar_skips_detection(self):
        # Should not import or call is_gradle_project
        result = _select_java_strategy(
            "myapp", self._repo_cfg(),
            self._paths(), "standalone",
        )
        self.assertIsNone(result)


class TestRunJavaPipelineMode(unittest.TestCase):
    """Tests for run_java_pipeline mode dispatch."""

    def _setup(self):
        pipeline = MagicMock()
        pipeline.builder.build_java.return_value = (
            BuildResult(success=True)
        )
        pipeline.builder.build.return_value = (
            BuildResult(success=True)
        )
        pipeline.spdx_gen.generate_java.return_value = (
            "/out/spdx.json"
        )
        pipeline.metadata_collector.collect\
            .return_value = None
        pipeline.spdx_validator.validate\
            .return_value = None
        pipeline.binary_collector.collect\
            .return_value = None
        return pipeline

    def _repo_cfg(self):
        return {
            "url": "https://github.com/example/app",
            "language": "java",
            "build_steps": ["mvn package"],
            "output_binaries": ["target/app.jar"],
        }

    def _omnibor(self):
        return {
            "strace_opts": "-f -e trace=openat",
            "strace_logfile": "/tmp/strace.log",
            "create_bom_script": "bomsh_java.py",
        }

    def _paths(self):
        return {
            "repos_dir": "/workspace/repos",
            "output_dir": "/workspace/output",
        }

    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
        return_value=[],
    )
    def test_standalone_uses_build_java(self, _):
        pipeline = self._setup()
        with patch("builtins.print"):
            timing = run_java_pipeline(
                pipeline, "jsoup",
                self._repo_cfg(), self._paths(),
                self._omnibor(), "2024-01-01",
                mode="standalone",
            )
        self.assertTrue(timing.success)
        self.assertEqual(timing.tracer, "strace")
        pipeline.builder.build_java\
            .assert_called_once()
        pipeline.builder.build\
            .assert_not_called()

    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
        return_value=[],
    )
    @patch(
        "app.spdx.gradle_parser"
        ".is_gradle_project",
        return_value=False,
    )
    def test_sidecar_uses_build_with_strategy(
        self, _, __,
    ):
        pipeline = self._setup()
        with patch("builtins.print"):
            timing = run_java_pipeline(
                pipeline, "jsoup",
                self._repo_cfg(), self._paths(),
                self._omnibor(), "2024-01-01",
                mode="sidecar",
            )
        self.assertTrue(timing.success)
        self.assertEqual(
            timing.tracer, "maven-dep-tree",
        )
        pipeline.builder.build\
            .assert_called_once()
        # Verify strategy was passed
        call_kw = pipeline.builder.build\
            .call_args[1]
        self.assertIsInstance(
            call_kw["strategy"],
            MavenDepTreeStrategy,
        )
        pipeline.builder.build_java\
            .assert_not_called()

    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
        return_value=[],
    )
    def test_default_mode_is_standalone(self, _):
        pipeline = self._setup()
        with patch("builtins.print"):
            timing = run_java_pipeline(
                pipeline, "jsoup",
                self._repo_cfg(), self._paths(),
                self._omnibor(), "2024-01-01",
            )
        self.assertEqual(timing.tracer, "strace")
        # Default mode=standalone -> build_java
        pipeline.builder.build_java\
            .assert_called_once()


class TestExtractMavenModules(unittest.TestCase):
    """Tests for _extract_maven_modules()."""

    def test_no_pl_flag(self):
        steps = ["mvn package -DskipTests"]
        self.assertIsNone(
            _extract_maven_modules(steps),
        )

    def test_pl_flag(self):
        steps = [
            "mvn package -DskipTests -q -pl crawler4j",
        ]
        self.assertEqual(
            _extract_maven_modules(steps),
            "crawler4j",
        )

    def test_pl_with_also_make(self):
        steps = ["mvn package -pl cli -am"]
        self.assertEqual(
            _extract_maven_modules(steps),
            "cli",
        )

    def test_non_maven_step_ignored(self):
        steps = [
            "gradle build",
            "mvn package -pl core",
        ]
        self.assertEqual(
            _extract_maven_modules(steps),
            "core",
        )

    def test_none_build_steps(self):
        self.assertIsNone(
            _extract_maven_modules(None),
        )

    def test_empty_build_steps(self):
        self.assertIsNone(
            _extract_maven_modules([]),
        )


class TestDetectJavaBuildTool(unittest.TestCase):
    """Tests for _detect_java_build_tool()."""

    def _detect_with_files(self, *filenames):
        with tempfile.TemporaryDirectory() as tmp:
            for name in filenames:
                open(
                    os.path.join(tmp, name),
                    "w", encoding="utf-8",
                ).close()
            return _detect_java_build_tool(tmp)

    def test_override_valid(self):
        self.assertEqual(
            _detect_java_build_tool(
                "/nonexistent",
                {"java_build_tool": "bazel"},
            ),
            "bazel",
        )

    def test_override_normalizes_case_and_space(self):
        self.assertEqual(
            _detect_java_build_tool(
                "/nonexistent",
                {"java_build_tool": "  Maven "},
            ),
            "maven",
        )

    def test_override_invalid_raises(self):
        with self.assertRaises(ValueError):
            _detect_java_build_tool(
                "/nonexistent",
                {"java_build_tool": "sbt"},
            )

    def test_detect_gradle(self):
        self.assertEqual(
            self._detect_with_files("build.gradle"),
            "gradle",
        )

    def test_detect_maven(self):
        self.assertEqual(
            self._detect_with_files("pom.xml"),
            "maven",
        )

    def test_detect_ivy(self):
        self.assertEqual(
            self._detect_with_files("build.xml", "ivy.xml"),
            "ivy",
        )

    def test_detect_ant(self):
        self.assertEqual(
            self._detect_with_files("build.xml"),
            "ant",
        )

    def test_detect_bazel_workspace(self):
        self.assertEqual(
            self._detect_with_files("WORKSPACE"),
            "bazel",
        )

    def test_detect_bazel_module(self):
        self.assertEqual(
            self._detect_with_files("MODULE.bazel"),
            "bazel",
        )

    def test_detect_make(self):
        self.assertEqual(
            self._detect_with_files("Makefile"),
            "make",
        )

    def test_detect_unknown(self):
        self.assertEqual(self._detect_with_files(), "unknown")

    def test_precedence_gradle_over_maven(self):
        self.assertEqual(
            self._detect_with_files("build.gradle", "pom.xml"),
            "gradle",
        )

    def test_precedence_maven_over_ivy(self):
        self.assertEqual(
            self._detect_with_files("pom.xml", "ivy.xml"),
            "maven",
        )

    def test_precedence_ivy_over_make(self):
        self.assertEqual(
            self._detect_with_files("ivy.xml", "Makefile"),
            "ivy",
        )

    def test_precedence_make_over_bazel(self):
        self.assertEqual(
            self._detect_with_files("Makefile", "WORKSPACE"),
            "make",
        )

    def test_repo_cfg_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(
                os.path.join(tmp, "pom.xml"),
                "w", encoding="utf-8",
            ).close()
            self.assertEqual(
                _detect_java_build_tool(tmp), "maven",
            )


class TestSelectJavaStrategyUnsupportedTools(unittest.TestCase):
    """Detected-but-unimplemented tools fall back to Maven."""

    def _paths(self):
        return {"repos_dir": "/workspace/repos"}

    def test_override_gradle_returns_gradle(self):
        cfg = {
            "java_build_tool": "gradle",
            "build_steps": ["gradle build"],
        }
        strategy = _select_java_strategy(
            "app", cfg, self._paths(), "sidecar",
        )
        self.assertIsInstance(
            strategy, GradleDepTreeStrategy,
        )

    def test_override_ivy_falls_back_to_maven_with_log(self):
        cfg = {
            "java_build_tool": "ivy",
            "build_steps": ["ant jar"],
        }
        with self.assertLogs(
            "app.pipeline.lang_runners", level="INFO",
        ) as logs:
            strategy = _select_java_strategy(
                "ant-ivy", cfg, self._paths(), "sidecar",
            )
        self.assertIsInstance(
            strategy, MavenDepTreeStrategy,
        )
        self.assertTrue(
            any("ivy" in m for m in logs.output),
        )


class TestSidecarPassesMavenModules(unittest.TestCase):
    """Verify -pl flows from config to strategy."""

    @patch(
        "app.spdx.gradle_parser"
        ".is_gradle_project",
        return_value=False,
    )
    def test_modules_set_on_strategy(self, _):
        cfg = {
            "build_steps": [
                "mvn package -pl crawler4j",
            ],
        }
        paths = {"repos_dir": "/workspace/repos"}
        strategy = _select_java_strategy(
            "crawler4j", cfg, paths, "sidecar",
        )
        self.assertIsInstance(
            strategy, MavenDepTreeStrategy,
        )
        self.assertEqual(
            strategy._maven_modules, "crawler4j",
        )

    @patch(
        "app.spdx.gradle_parser"
        ".is_gradle_project",
        return_value=False,
    )
    def test_no_modules_when_absent(self, _):
        cfg = {"build_steps": ["mvn package"]}
        paths = {"repos_dir": "/workspace/repos"}
        strategy = _select_java_strategy(
            "jsoup", cfg, paths, "sidecar",
        )
        self.assertIsNone(
            strategy._maven_modules,
        )


if __name__ == "__main__":
    unittest.main()
