"""Tests for Java pipeline functions in runners.py."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from app.pipeline.runners import (
    _run_java_pipeline,
    _generate_java_adg_spdx,
)


class TestRunJavaPipeline(unittest.TestCase):
    """Tests for _run_java_pipeline."""

    def _make_pipeline(self):
        p = MagicMock()
        p.builder.build_java.return_value = True
        p.spdx_gen.generate_java.return_value = (
            "/tmp/spdx.json"
        )
        p.metadata_collector.collect.return_value = None
        p.spdx_validator.validate.return_value = None
        p.binary_collector.collect.return_value = None
        return p

    def _make_cfg(self, td):
        paths_cfg = {
            "output_dir": str(Path(td) / "output"),
            "repos_dir": str(Path(td) / "repos"),
        }
        repo_cfg = {
            "language": "java",
            "url": "https://github.com/test/test.git",
        }
        omnibor_java_cfg = {
            "strace_opts": "-f",
            "create_bom_script": "bomsh_bom_java.py",
            "strace_logfile": "/tmp/strace.log",
        }
        return paths_cfg, repo_cfg, omnibor_java_cfg

    @patch(
        "app.pipeline.lang_runners.generate_java_adg_spdx"
    )
    def test_success_flow(self, mock_adg):
        mock_adg.return_value = ["/tmp/adg.spdx.json"]
        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, java_cfg = self._make_cfg(td)
            # Create syft spdx path so validation
            # branch is exercised
            spdx_dir = (
                Path(td) / "output" / "spdx" / "java"
                / "myapp" / "ts1"
            )
            spdx_dir.mkdir(parents=True)
            (spdx_dir / "myapp_syft.spdx.json").write_text(
                "{}"
            )
            pipeline = self._make_pipeline()

            success, _dur, tracer = _run_java_pipeline(
                pipeline, "myapp", repo_cfg,
                paths, java_cfg, "ts1",
            )

            self.assertTrue(success)
            self.assertEqual(tracer, "strace")
            pipeline.builder.build_java.assert_called_once()
            pipeline.spdx_gen.generate_java.assert_called_once()
            pipeline.metadata_collector.collect.assert_called_once()
            mock_adg.assert_called_once()
            pipeline.binary_collector.collect.assert_called_once()
            # spdx_validator called for spdx + adg
            # (Syft validation is now in main via
            # _validate_syft_spdx)
            self.assertEqual(
                pipeline.spdx_validator.validate.call_count,
                2,
            )

    @patch(
        "app.pipeline.lang_runners.generate_java_adg_spdx"
    )
    def test_build_failure_skips_steps(self, mock_adg):
        mock_adg.return_value = []
        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, java_cfg = self._make_cfg(td)
            pipeline = self._make_pipeline()
            pipeline.builder.build_java.return_value = False

            success, _dur, _ = _run_java_pipeline(
                pipeline, "myapp", repo_cfg,
                paths, java_cfg, "ts1",
            )

            self.assertFalse(success)
            pipeline.spdx_gen.generate_java.assert_not_called()
            pipeline.metadata_collector.collect.assert_not_called()
            pipeline.binary_collector.collect.assert_not_called()

    @patch(
        "app.pipeline.lang_runners.generate_java_adg_spdx"
    )
    def test_no_spdx_file_skips_validation(
        self, mock_adg
    ):
        mock_adg.return_value = []
        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, java_cfg = self._make_cfg(td)
            pipeline = self._make_pipeline()
            pipeline.spdx_gen.generate_java.return_value = (
                None
            )

            success, _dur, _ = _run_java_pipeline(
                pipeline, "myapp", repo_cfg,
                paths, java_cfg, "ts1",
            )

            self.assertTrue(success)
            # No spdx file + no adg files + no syft
            pipeline.spdx_validator.validate.assert_not_called()


class TestGenerateJavaAdgSpdx(unittest.TestCase):
    """Tests for _generate_java_adg_spdx."""

    @patch(
        "app.spdx.parser.AdgParser"
    )
    @patch(
        "app.spdx.java_generator.JavaSpdxGenerator"
    )
    def test_generates_both_sboms(
        self, mock_gen_cls, mock_parser_cls,
    ):
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = [
            "/tmp/out/myapp_analyzed.spdx.json",
            "/tmp/out/myapp_build.spdx.json",
        ]
        mock_gen_cls.return_value = mock_gen

        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/target/myapp-1.0.jar": [
                {"sha1": "aaa", "file_path": "a.java"},
            ],
        }
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": [
                    "target/myapp-1.0.jar",
                ],
            }
            # Create the JAR file on disk
            jar = (
                Path(td) / "repos" / "myapp"
                / "target" / "myapp-1.0.jar"
            )
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"PK")

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            self.assertEqual(len(result), 2)
            mock_gen_cls.assert_called_once()
            # Called twice: analyzed + build
            self.assertEqual(
                mock_gen.generate.call_count, 2
            )
            calls = mock_gen.generate.call_args_list
            self.assertEqual(
                calls[0].kwargs["sbom_type"],
                "analyzed",
            )
            self.assertEqual(
                calls[1].kwargs["sbom_type"],
                "build",
            )

    @patch(
        "app.spdx.parser.AdgParser"
    )
    @patch(
        "app.spdx.java_generator.JavaSpdxGenerator"
    )
    def test_returns_empty_on_failure(
        self, mock_gen_cls, mock_parser_cls,
    ):
        mock_gen = MagicMock()
        mock_gen.generate.return_value = None
        mock_gen_cls.return_value = mock_gen

        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/target/myapp-1.0.jar": [],
        }
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": [
                    "target/myapp-1.0.jar",
                ],
            }
            jar = (
                Path(td) / "repos" / "myapp"
                / "target" / "myapp-1.0.jar"
            )
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"PK")

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            # Both calls return None → empty list
            self.assertEqual(result, [])

    @patch(
        "app.spdx.parser.AdgParser"
    )
    @patch(
        "app.spdx.java_generator.JavaSpdxGenerator"
    )
    def test_multi_binary_produces_per_jar_spdx(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """Multi-module project: 3 JARs → 6 SPDX."""
        mock_gen = MagicMock()
        # 6 calls: analyzed+build for each of 3 JARs
        mock_gen.generate.side_effect = [
            f"/tmp/out/{n}"
            for n in [
                "utils_analyzed.spdx.json",
                "utils_build.spdx.json",
                "core_analyzed.spdx.json",
                "core_build.spdx.json",
                "cli_analyzed.spdx.json",
                "cli_build.spdx.json",
            ]
        ]
        mock_gen_cls.return_value = mock_gen

        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/utils/target/utils-1.0.jar": [
                {"sha1": "a", "file_path": "u.java"},
            ],
            "myapp/core/target/core-1.0.jar": [
                {"sha1": "b", "file_path": "c.java"},
            ],
            "myapp/cli/target/cli-1.0.jar": [
                {"sha1": "c", "file_path": "m.java"},
            ],
        }
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": [
                    "utils/target/utils-1.0.jar",
                    "core/target/core-1.0.jar",
                    "cli/target/cli-1.0.jar",
                ],
            }
            # Create JAR files on disk
            for sub in [
                "utils/target", "core/target",
                "cli/target",
            ]:
                jar = (
                    Path(td) / "repos" / "myapp"
                    / sub
                    / f"{sub.split('/')[0]}-1.0.jar"
                )
                jar.parent.mkdir(parents=True)
                jar.write_bytes(b"PK")

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            # 3 JARs × 2 SBOMs = 6 files
            self.assertEqual(len(result), 6)
            self.assertEqual(
                mock_gen.generate.call_count, 6
            )
            # Verify each JAR gets its own jar_files
            calls = mock_gen.generate.call_args_list
            # First pair: utils
            self.assertIn(
                "utils-1.0.jar",
                calls[0].kwargs["binary_name"],
            )
            self.assertEqual(
                calls[0].kwargs["sbom_type"],
                "analyzed",
            )
            self.assertEqual(
                calls[1].kwargs["sbom_type"],
                "build",
            )
            # Second pair: core
            self.assertIn(
                "core-1.0.jar",
                calls[2].kwargs["binary_name"],
            )
            # Third pair: cli
            self.assertIn(
                "cli-1.0.jar",
                calls[4].kwargs["binary_name"],
            )


class TestJarMapFallbackMatching(unittest.TestCase):
    """Tests for JAR filename-based fallback matching.

    When the treedb JAR path differs from the
    output_binaries glob path (e.g., Gradle
    maven-publish puts JARs in build/maven-repository/
    while glob finds build/libs/), the pipeline must
    match by filename and never silently fall back to
    all project files.
    """

    @patch(
        "app.spdx.parser.AdgParser"
    )
    @patch(
        "app.spdx.java_generator.JavaSpdxGenerator"
    )
    def test_filename_fallback_matches(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """Exact path miss but filename match succeeds."""
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = [
            "/tmp/analyzed.spdx.json",
            "/tmp/build.spdx.json",
        ]
        mock_gen_cls.return_value = mock_gen

        # Treedb has JAR under maven-repository/
        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/build/maven-repo/myapp-1.0.jar": [
                {"sha1": "a", "file_path": "a.java"},
            ],
        }
        mock_parser.parse_strace_openat_log.return_value = (
            set()
        )
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(
                    Path(td) / "output"
                ),
                "repos_dir": str(
                    Path(td) / "repos"
                ),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": [
                    # Glob finds build/libs/
                    "build/libs/myapp-1.0.jar",
                ],
            }
            jar = (
                Path(td) / "repos" / "myapp"
                / "build" / "libs" / "myapp-1.0.jar"
            )
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"PK")

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            self.assertEqual(len(result), 2)
            # Verify jar_files was passed (not None)
            calls = mock_gen.generate.call_args_list
            for call in calls:
                self.assertIsNotNone(
                    call.kwargs["jar_files"],
                )
                self.assertEqual(
                    len(call.kwargs["jar_files"]), 1,
                )

    @patch(
        "app.spdx.parser.AdgParser"
    )
    @patch(
        "app.spdx.java_generator.JavaSpdxGenerator"
    )
    def test_no_match_skips_jar(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """No path or filename match → skip JAR."""
        mock_gen = MagicMock()
        mock_gen_cls.return_value = mock_gen

        # Treedb has different JARs entirely
        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/target/other-1.0.jar": [
                {"sha1": "a", "file_path": "a.java"},
            ],
        }
        mock_parser.parse_strace_openat_log.return_value = (
            set()
        )
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(
                    Path(td) / "output"
                ),
                "repos_dir": str(
                    Path(td) / "repos"
                ),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": [
                    "target/myapp-1.0.jar",
                ],
            }
            jar = (
                Path(td) / "repos" / "myapp"
                / "target" / "myapp-1.0.jar"
            )
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"PK")

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            # JAR skipped — no SPDX generated
            self.assertEqual(result, [])
            mock_gen.generate.assert_not_called()


class TestMainJavaDispatch(unittest.TestCase):
    """Test that main() dispatches to Java pipeline."""

    @patch("app.pipeline.runners.run_java_pipeline")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch("app.pipeline.runners.load_config")
    @patch("app.pipeline.runners.timestamp")
    def test_java_dispatch(
        self, mock_ts, mock_cfg, mock_pipe, mock_java,
    ):
        mock_ts.return_value = "ts1"
        mock_cfg.return_value = {
            "repos": {
                "checkstyle": {
                    "language": "java",
                    "url": "https://github.com/test.git",
                },
            },
            "paths": {
                "output_dir": "/tmp/out",
                "repos_dir": "/tmp/repos",
            },
            "omnibor": {
                "tracer": "bomtrace3",
                "create_bom_script": "bom.py",
                "sbom_script": "sbom.py",
                "raw_logfile": "/tmp/log",
            },
            "omnibor_java": {
                "strace_opts": "-f",
                "create_bom_script": "bom.py",
                "strace_logfile": "/tmp/log",
            },
        }
        mock_pipe_inst = MagicMock()
        mock_pipe.return_value = mock_pipe_inst
        mock_java.return_value = (True, 10.0, "strace")

        from app.pipeline.runners import main
        with patch(
            "sys.argv",
            ["analyze", "--repo", "checkstyle"],
        ):
            main()

        mock_java.assert_called_once()

    @patch("app.pipeline.runners.run_rust_pipeline")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch("app.pipeline.runners.load_config")
    @patch("app.pipeline.runners.timestamp")
    def test_rust_dispatch(
        self, mock_ts, mock_cfg, mock_pipe, mock_rust,
    ):
        mock_ts.return_value = "ts1"
        mock_cfg.return_value = {
            "repos": {
                "oxipng": {
                    "language": "rust",
                    "url": "https://github.com/test.git",
                },
            },
            "paths": {
                "output_dir": "/tmp/out",
                "repos_dir": "/tmp/repos",
            },
            "omnibor": {
                "tracer": "bomtrace3",
                "create_bom_script": "bom.py",
                "sbom_script": "sbom.py",
                "raw_logfile": "/tmp/log",
            },
            "omnibor_rust": {
                "tracer": "bomtrace2",
                "create_bom_script": "bom.py",
                "sbom_script": "sbom.py",
                "raw_logfile": "/tmp/log",
            },
        }
        mock_pipe_inst = MagicMock()
        mock_pipe.return_value = mock_pipe_inst
        mock_rust.return_value = (True, 10.0, "bomtrace2")

        from app.pipeline.runners import main
        with patch(
            "sys.argv",
            ["analyze", "--repo", "oxipng"],
        ):
            main()

        mock_rust.assert_called_once()


if __name__ == "__main__":
    unittest.main()
