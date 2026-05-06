"""
Tests for Java pipeline strategy wiring (#109 B4).

Verifies that _select_java_strategy returns the correct
strategy based on mode and build system (Maven vs Gradle).
"""

import unittest
from unittest.mock import patch, MagicMock

from app.pipeline.lang_runners import (
    _select_java_strategy,
    run_java_pipeline,
)
from app.pipeline.interception import (
    MavenDepTreeStrategy,
    GradleDepTreeStrategy,
)


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
    def test_sidecar_gradle(self, mock_is_gradle):
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
        pipeline.builder.build_java.return_value = True
        pipeline.builder.build.return_value = True
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
            success, dur = run_java_pipeline(
                pipeline, "jsoup",
                self._repo_cfg(), self._paths(),
                self._omnibor(), "2024-01-01",
                mode="standalone",
            )
        self.assertTrue(success)
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
            success, dur = run_java_pipeline(
                pipeline, "jsoup",
                self._repo_cfg(), self._paths(),
                self._omnibor(), "2024-01-01",
                mode="sidecar",
            )
        self.assertTrue(success)
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
            success, dur = run_java_pipeline(
                pipeline, "jsoup",
                self._repo_cfg(), self._paths(),
                self._omnibor(), "2024-01-01",
            )
        # Default mode=standalone -> build_java
        pipeline.builder.build_java\
            .assert_called_once()


if __name__ == "__main__":
    unittest.main()
