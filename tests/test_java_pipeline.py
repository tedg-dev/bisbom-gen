"""Tests for Java pipeline functions in runners.py."""
import json
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
from app.pipeline.builder import BuildResult
from app.pipeline.timing import (
    TimingResult, StepMetrics,
)


class TestRunJavaPipeline(unittest.TestCase):
    """Tests for _run_java_pipeline."""

    def _make_pipeline(self):
        p = MagicMock()
        p.builder.build_java.return_value = BuildResult(
            success=True,
        )
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
        bisbom_java_cfg = {
            "strace_opts": "-f",
            "create_bom_script": "bomsh_bom_java.py",
            "strace_logfile": "/tmp/strace.log",
        }
        return paths_cfg, repo_cfg, bisbom_java_cfg

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

            timing = _run_java_pipeline(
                pipeline, "myapp", repo_cfg,
                paths, java_cfg, "ts1",
            )

            self.assertTrue(timing.success)
            self.assertEqual(timing.tracer, "strace")
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
            pipeline.builder.build_java.return_value = (
                BuildResult(success=False)
            )

            timing = _run_java_pipeline(
                pipeline, "myapp", repo_cfg,
                paths, java_cfg, "ts1",
            )

            self.assertFalse(timing.success)
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

            timing = _run_java_pipeline(
                pipeline, "myapp", repo_cfg,
                paths, java_cfg, "ts1",
            )

            self.assertTrue(timing.success)
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
            "/tmp/out/myapp-1.0_analyzed.spdx.json",
            "/tmp/out/myapp-1.0_build.spdx.json",
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
            # Called twice per JAR: analyzed + build
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
    def test_passes_artifact_identity(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """Built JAR path reaches both SBOMs so the
        generator can compute its SHA-256 identity."""
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
        mock_parser.validate_jar_topology.return_value = {}
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

            _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            calls = mock_gen.generate.call_args_list
            self.assertEqual(len(calls), 2)
            for c in calls:
                self.assertEqual(
                    c.kwargs["jar_path"], str(jar)
                )

    @patch(
        "app.spdx.parser.AdgParser"
    )
    @patch(
        "app.spdx.java_generator.JavaSpdxGenerator"
    )
    def test_no_sha1_identity_kwargs_passed(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """Regression: bomsh SHA-1 topology values must not
        be passed as identity; only ``jar_path`` is used so
        the generator computes SHA-256 identity from the JAR
        (project/artifact-identity.md)."""
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
        mock_parser.validate_jar_topology.return_value = {}
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

            _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )

            calls = mock_gen.generate.call_args_list
            for c in calls:
                self.assertNotIn("jar_sha1", c.kwargs)
                self.assertNotIn("jar_gitoid", c.kwargs)
                self.assertEqual(
                    c.kwargs["jar_path"], str(jar)
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
    def test_multi_binary_per_jar_spdx(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """Multi-module project: 3 JARs → 6 SPDX docs."""
        mock_gen = MagicMock()
        # 2 calls per JAR (analyzed + build) × 3 JARs
        mock_gen.generate.side_effect = [
            "/tmp/out/utils-1.0_analyzed.spdx.json",
            "/tmp/out/utils-1.0_build.spdx.json",
            "/tmp/out/core-1.0_analyzed.spdx.json",
            "/tmp/out/core-1.0_build.spdx.json",
            "/tmp/out/cli-1.0_analyzed.spdx.json",
            "/tmp/out/cli-1.0_build.spdx.json",
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

            # 6 SPDX docs (2 per JAR × 3 JARs)
            self.assertEqual(len(result), 6)
            self.assertEqual(
                mock_gen.generate.call_count, 6
            )
            calls = mock_gen.generate.call_args_list
            # Alternates: analyzed, build for each JAR
            for i in range(0, 6, 2):
                self.assertEqual(
                    calls[i].kwargs["sbom_type"],
                    "analyzed",
                )
                self.assertEqual(
                    calls[i + 1].kwargs["sbom_type"],
                    "build",
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
            # Verify jar_files passed per-JAR
            calls = (
                mock_gen.generate.call_args_list
            )
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


class TestGenerateJavaAdgSpdxBranches(unittest.TestCase):
    """Cover remaining branches of _generate_java_adg_spdx."""

    @patch("app.spdx.parser.AdgParser")
    def test_missing_treedb_returns_empty(
        self, mock_parser_cls,
    ):
        """get_jar_source_files raises -> empty result."""
        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.side_effect = (
            FileNotFoundError("no treedb")
        )
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": ["target/myapp-1.0.jar"],
            }
            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )
        self.assertEqual(result, [])

    @patch("app.spdx.parser.AdgParser")
    @patch("app.spdx.java_generator.JavaSpdxGenerator")
    def test_glob_pattern_resolves_jars(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """A wildcard output_binaries pattern is globbed."""
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = [
            "/tmp/analyzed.spdx.json",
            "/tmp/build.spdx.json",
        ]
        mock_gen_cls.return_value = mock_gen

        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/target/myapp-1.0.jar": [
                {"sha1": "a", "file_path": "a.java"},
            ],
        }
        mock_parser.parse_strace_openat_log.return_value = (
            set()
        )
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": ["target/*.jar"],
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
        self.assertEqual(len(result), 2)

    @patch("app.spdx.parser.AdgParser")
    def test_no_output_jars_returns_empty(
        self, mock_parser_cls,
    ):
        """No resolved JARs -> warn and return empty."""
        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {}
        mock_parser.parse_strace_openat_log.return_value = (
            set()
        )
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": [],
            }
            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )
        self.assertEqual(result, [])

    @patch(
        "app.pipeline.maven_plugin_detector"
        ".detect_repackaging_plugins"
    )
    @patch("app.spdx.parser.AdgParser")
    @patch("app.spdx.java_generator.JavaSpdxGenerator")
    def test_uber_jar_warns_and_finds_module_pom(
        self, mock_gen_cls, mock_parser_cls, mock_detect,
    ):
        """Uber-JAR warnings emitted; module pom located."""
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = [
            "/tmp/analyzed.spdx.json",
            "/tmp/build.spdx.json",
        ]
        mock_gen_cls.return_value = mock_gen

        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/target/myapp-1.0.jar": [
                {"sha1": "a", "file_path": "a.java"},
            ],
        }
        mock_parser.parse_strace_openat_log.return_value = (
            set()
        )
        mock_parser_cls.return_value = mock_parser

        detection = MagicMock()
        detection.warning = "shade plugin bundles deps"
        plugin_result = MagicMock()
        plugin_result.is_uber_jar = True
        plugin_result.detections = [detection]
        mock_detect.return_value = plugin_result

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": ["target/myapp-1.0.jar"],
            }
            repo_dir = Path(td) / "repos" / "myapp"
            jar = repo_dir / "target" / "myapp-1.0.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"PK")
            # pom.xml in the module root so the walk-up
            # from target/ locates pom_dir.
            (repo_dir / "pom.xml").write_text("<project/>")

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )
        self.assertEqual(len(result), 2)
        mock_detect.assert_called_once()

    @patch("app.spdx.parser.AdgParser")
    @patch("app.spdx.java_generator.JavaSpdxGenerator")
    def test_build_deps_from_capture(
        self, mock_gen_cls, mock_parser_cls,
    ):
        """With a Phase 1 capture present, the _build SBOM is
        generated from the captured per-module deps directly
        (no source-tree access / pom_dir)."""
        mock_gen = MagicMock()
        mock_gen.generate.side_effect = [
            "/tmp/analyzed.spdx.json",
            "/tmp/build.spdx.json",
        ]
        mock_gen_cls.return_value = mock_gen

        mock_parser = MagicMock()
        mock_parser.get_jar_source_files.return_value = {
            "myapp/target/myapp-1.0.jar": [
                {"sha1": "a", "file_path": "a.java"},
            ],
        }
        mock_parser.parse_strace_openat_log.return_value = (
            set()
        )
        mock_parser_cls.return_value = mock_parser

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = {
                "output_dir": str(Path(td) / "output"),
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "language": "java",
                "output_binaries": ["target/myapp-1.0.jar"],
            }
            jar = (
                Path(td) / "repos" / "myapp"
                / "target" / "myapp-1.0.jar"
            )
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"PK")

            bom_dir = (
                Path(td) / "output" / "bisbom"
                / "java" / "myapp" / "ts1"
            )
            bom_dir.mkdir(parents=True)
            captured_dep = {
                "groupId": "org.slf4j",
                "artifactId": "slf4j-api",
                "version": "2.0.7", "scope": "compile",
                "direct": True, "optional": False,
                "parent": None,
            }
            (bom_dir / "maven_deps.json").write_text(
                json.dumps({
                    "tool": "maven",
                    "modules": [{
                        "key": "com.example:myapp",
                        "groupId": "com.example",
                        "artifactId": "myapp",
                        "version": "1.0",
                        "packaging": "jar",
                        "deps": [captured_dep],
                    }],
                })
            )

            result = _generate_java_adg_spdx(
                "myapp", repo_cfg, paths_cfg, "ts1",
            )
        self.assertEqual(len(result), 2)
        build_call = mock_gen.generate.call_args_list[1]
        self.assertEqual(
            build_call.kwargs["deps"], [captured_dep],
        )
        self.assertIsNone(build_call.kwargs["pom_dir"])


class TestMainJavaDispatch(unittest.TestCase):
    """Test that main() dispatches to Java pipeline."""

    @patch(
        "app.pipeline.timing.save_runtime_json",
    )
    @patch(
        "app.pipeline.timing.load_baseline",
        return_value=None,
    )
    @patch("app.pipeline.runners.run_java_pipeline")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch("app.pipeline.runners.load_config")
    @patch("app.pipeline.runners.timestamp")
    def test_java_dispatch(
        self, mock_ts, mock_cfg, mock_pipe,
        mock_java, _bl, _save,
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
            "bisbom": {
                "tracer": "bomtrace3",
                "create_bom_script": "bom.py",
                "sbom_script": "sbom.py",
                "raw_logfile": "/tmp/log",
            },
            "bisbom_java": {
                "strace_opts": "-f",
                "create_bom_script": "bom.py",
                "strace_logfile": "/tmp/log",
            },
        }
        mock_pipe_inst = MagicMock()
        mock_pipe.return_value = mock_pipe_inst
        mock_java.return_value = TimingResult(
            tracer="strace",
            success=True,
            steps=[
                StepMetrics(
                    name="build",
                    phase="phase1",
                    wall_sec=8.0,
                ),
            ],
        )

        from app.pipeline.runners import main
        with patch(
            "sys.argv",
            ["analyze", "--repo", "checkstyle"],
        ):
            main()

        mock_java.assert_called_once()

    @patch(
        "app.pipeline.timing.save_runtime_json",
    )
    @patch(
        "app.pipeline.timing.load_baseline",
        return_value=None,
    )
    @patch("app.pipeline.runners.run_rust_pipeline")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch("app.pipeline.runners.load_config")
    @patch("app.pipeline.runners.timestamp")
    def test_rust_dispatch(
        self, mock_ts, mock_cfg, mock_pipe,
        mock_rust, _bl, _save,
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
            "bisbom": {
                "tracer": "bomtrace3",
                "create_bom_script": "bom.py",
                "sbom_script": "sbom.py",
                "raw_logfile": "/tmp/log",
            },
            "bisbom_rust": {
                "tracer": "bomtrace2",
                "create_bom_script": "bom.py",
                "sbom_script": "sbom.py",
                "raw_logfile": "/tmp/log",
            },
        }
        mock_pipe_inst = MagicMock()
        mock_pipe.return_value = mock_pipe_inst
        mock_rust.return_value = TimingResult(
            tracer="bomtrace2",
            success=True,
            steps=[
                StepMetrics(
                    name="build",
                    phase="phase1",
                    wall_sec=8.0,
                ),
            ],
        )

        from app.pipeline.runners import main
        with patch(
            "sys.argv",
            ["analyze", "--repo", "oxipng"],
        ):
            main()

        mock_rust.assert_called_once()


class TestPhase1IdentityIndex(unittest.TestCase):
    """Tests for Phase-1 identity-index wiring in run_java_phase1.

    Design of record: project/artifact-identity.md (Java caveat —
    hash intermediates while they exist, before workspace cleanup).
    """

    def _paths(self, td):
        return {
            "output_dir": str(Path(td) / "output"),
            "repos_dir": str(Path(td) / "repos"),
        }

    def _write_treedb(self, paths_cfg, run_ts, treedb):
        meta = (
            Path(paths_cfg["output_dir"]) / "bisbom"
            / "java" / "myapp" / run_ts
            / "metadata" / "bomsh"
        )
        meta.mkdir(parents=True)
        (meta / "bomsh_omnibor_treedb").write_text(
            json.dumps(treedb)
        )
        return meta

    def test_persist_helper_writes_index(self):
        from app.pipeline.lang_runners import (
            _persist_identity_index,
        )
        from app.spdx.identity import (
            IDENTITY_INDEX_FILENAME,
        )

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = self._paths(td)
            src = (
                Path(paths_cfg["repos_dir"]) / "myapp"
                / "App.class"
            )
            src.parent.mkdir(parents=True)
            src.write_bytes(b"\xca\xfe\xba\xbe")
            meta = self._write_treedb(
                paths_cfg, "ts1",
                {"s1": {"file_path": str(src)}},
            )
            _persist_identity_index(
                "myapp", {"language": "java"},
                paths_cfg, "ts1",
            )
            index_path = meta / IDENTITY_INDEX_FILENAME
            self.assertTrue(index_path.exists())
            index = json.loads(index_path.read_text())
            self.assertIn(str(src), index)
            self.assertEqual(
                index[str(src)]["algo"], "sha256"
            )

    def test_persist_helper_no_treedb_is_quiet(self):
        """Missing treedb: no index, no exception."""
        from app.pipeline.lang_runners import (
            _persist_identity_index,
        )

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = self._paths(td)
            # No treedb written — must not raise.
            _persist_identity_index(
                "myapp", {"language": "java"},
                paths_cfg, "ts1",
            )

    def test_persist_helper_swallows_errors(self):
        """A persistence failure is logged, never raised, so it
        cannot break an otherwise successful build."""
        from app.pipeline.lang_runners import (
            _persist_identity_index,
        )

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = self._paths(td)
            with patch(
                "app.spdx.parser.AdgParser."
                "persist_identity_index",
                side_effect=OSError("disk full"),
            ):
                # Must return without raising.
                _persist_identity_index(
                    "myapp", {"language": "java"},
                    paths_cfg, "ts1",
                )

    def test_phase1_success_persists_index(self):
        from app.pipeline.lang_runners import run_java_phase1

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = self._paths(td)
            self._write_treedb(
                paths_cfg, "ts1",
                {"s1": {"file_path": "/gone/App.class"}},
            )
            pipeline = MagicMock()
            pipeline.builder.build_java.return_value = (
                BuildResult(success=True)
            )
            with patch(
                "app.pipeline.lang_runners."
                "_persist_identity_index"
            ) as mock_persist:
                timing, _ = run_java_phase1(
                    pipeline, "myapp",
                    {"language": "java"},
                    paths_cfg,
                    {
                        "strace_opts": "-f",
                        "create_bom_script": "x.py",
                        "strace_logfile": "/tmp/s.log",
                    },
                    "ts1",
                )
            self.assertTrue(timing.success)
            mock_persist.assert_called_once()

    def test_phase1_failure_skips_index(self):
        from app.pipeline.lang_runners import run_java_phase1

        with tempfile.TemporaryDirectory() as td:
            paths_cfg = self._paths(td)
            pipeline = MagicMock()
            pipeline.builder.build_java.return_value = (
                BuildResult(success=False)
            )
            with patch(
                "app.pipeline.lang_runners."
                "_persist_identity_index"
            ) as mock_persist:
                timing, _ = run_java_phase1(
                    pipeline, "myapp",
                    {"language": "java"},
                    paths_cfg,
                    {
                        "strace_opts": "-f",
                        "create_bom_script": "x.py",
                        "strace_logfile": "/tmp/s.log",
                    },
                    "ts1",
                )
            self.assertFalse(timing.success)
            mock_persist.assert_not_called()


class TestHandoffManifestHelpers(unittest.TestCase):
    """Tests for the Phase 2 hand-off manifest helpers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_artifact_record_from_index(self):
        from app.pipeline.lang_runners import _jar_artifact_record

        index = {
            "/build/libs/app.jar": {
                "raw": "r" * 64,
                "gitoid": "gitoid:blob:sha256:" + "g" * 64,
            },
        }
        rec = _jar_artifact_record(
            index, self.tmp / "app.jar", "app.jar",
        )
        self.assertEqual(rec["sha256"], "r" * 64)
        self.assertEqual(
            rec["gitoid"], "gitoid:blob:sha256:" + "g" * 64,
        )

    def test_artifact_record_file_fallback(self):
        from app.pipeline.lang_runners import _jar_artifact_record
        from app.spdx import identity

        jar = self.tmp / "app.jar"
        jar.write_bytes(b"PK\x03\x04payload")
        rec = _jar_artifact_record({}, jar, "app.jar")
        self.assertEqual(rec["sha256"], identity.raw_hash(jar))
        self.assertEqual(rec["gitoid"], identity.gitoid(jar))

    def test_artifact_record_unavailable(self):
        from app.pipeline.lang_runners import _jar_artifact_record

        rec = _jar_artifact_record(
            {}, self.tmp / "gone.jar", "gone.jar",
        )
        self.assertIsNone(rec)

    def test_emit_empty_sboms_returns_none(self):
        from app.pipeline.lang_runners import _emit_handoff_manifest

        result = _emit_handoff_manifest(
            self.tmp, "app", "java", "sidecar",
            "sha", "vcs", "bid", [],
        )
        self.assertIsNone(result)

    def test_emit_success_writes_manifest(self):
        from app.pipeline.lang_runners import _emit_handoff_manifest
        from app.pipeline import handoff

        build = self.tmp / "app_build.spdx.json"
        analyzed = self.tmp / "app_analyzed.spdx.json"
        build.write_text("{}", encoding="utf-8")
        analyzed.write_text("{}", encoding="utf-8")
        sboms = [{
            "artifact": {
                "name": "app.jar",
                "sha256": "r" * 64,
                "gitoid": "gitoid:blob:sha256:" + "g" * 64,
            },
            "build": str(build),
            "analyzed": str(analyzed),
        }]
        path = _emit_handoff_manifest(
            self.tmp, "app", "java", "sidecar",
            "sha", "vcs", "bid", sboms,
        )
        self.assertEqual(path.name, handoff.HANDOFF_FILENAME)
        data = handoff.read_handoff_manifest(path)
        self.assertEqual(data["build_id"], "bid")
        self.assertEqual(data["producer"]["mode"], "sidecar")

    def test_emit_handoff_error_returns_none(self):
        from app.pipeline.lang_runners import _emit_handoff_manifest
        from app.pipeline import handoff

        sboms = [{"artifact": {}, "build": "x", "analyzed": "y"}]
        with patch(
            "app.pipeline.lang_runners.handoff."
            "write_handoff_manifest",
            side_effect=handoff.HandoffError("boom"),
        ):
            result = _emit_handoff_manifest(
                self.tmp, "app", "java", "sidecar",
                "sha", "vcs", "bid", sboms,
            )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
