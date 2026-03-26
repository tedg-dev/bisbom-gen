#!/usr/bin/env python3
"""
Tests for app/analyze.py — class-based analysis pipeline.

Uses unittest.mock to avoid real subprocess calls.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add app/ to path so we can import analyze
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import analyze
from analyze import (
    CommandRunner, DependencyValidator,
    RepoCloner, BomtraceBuilder,
    SpdxGenerator, MetadataCollector, SpdxValidator,
    SyftGenerator, BinaryCollector, DocWriter,
    AnalysisPipeline, load_config, timestamp,
    _run_go_pipeline,
    _run_rust_pipeline,
    _validate_syft_spdx,
)


# ============================================================
# Utilities
# ============================================================

class TestLoadConfig(unittest.TestCase):
    """Tests for load_config()."""

    def test_loads_real_config(self):
        config = load_config()
        self.assertIn("repos", config)
        self.assertIn("paths", config)
        self.assertIn("omnibor", config)

    def test_loads_custom_path(self):
        import yaml
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            yaml.dump({"test": True}, f)
            tmp = Path(f.name)
        result = load_config(tmp)
        self.assertTrue(result["test"])
        tmp.unlink()


class TestTimestamp(unittest.TestCase):
    """Tests for timestamp()."""

    def test_format(self):
        ts = timestamp()
        self.assertRegex(
            ts, r"\d{4}-\d{2}-\d{2}_\d{4}"
        )


# ============================================================
# CommandRunner
# ============================================================

class TestCommandRunner(unittest.TestCase):
    """Tests for CommandRunner."""

    @patch("analyze.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ok\n",
        )
        runner = CommandRunner()
        with patch("builtins.print"):
            rc = runner.run(
                "echo hello", description="test"
            )
        self.assertEqual(rc, 0)

    @patch("analyze.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="fail\n",
        )
        runner = CommandRunner()
        with patch("builtins.print"):
            rc = runner.run(
                "false", description="fail test"
            )
        self.assertEqual(rc, 1)

    @patch("analyze.subprocess.run")
    def test_cwd_passed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="",
        )
        runner = CommandRunner()
        with patch("builtins.print"):
            runner.run(
                "ls", cwd="/tmp",
                description="cwd test",
            )
        mock_run.assert_called_once()
        self.assertEqual(
            mock_run.call_args.kwargs.get("cwd")
            or mock_run.call_args[1].get("cwd"),
            "/tmp",
        )

    @patch("analyze.subprocess.run")
    def test_prints_error_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=42, stdout="",
        )
        runner = CommandRunner()
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            runner.run("bad", description="x")
        output = "\n".join(printed)
        self.assertIn("42", output)


# ============================================================
# DependencyValidator
# ============================================================

class TestDependencyValidator(unittest.TestCase):
    """Tests for DependencyValidator."""

    def test_no_apt_deps(self):
        runner = MagicMock()
        v = DependencyValidator(runner)
        ok, missing = v.validate({})
        self.assertTrue(ok)
        self.assertEqual(missing, [])
        runner.run.assert_not_called()

    def test_empty_apt_deps(self):
        runner = MagicMock()
        v = DependencyValidator(runner)
        ok, missing = v.validate({"apt_deps": []})
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_all_installed(self):
        runner = MagicMock()
        runner.run.return_value = 0
        v = DependencyValidator(runner)
        with patch("builtins.print"):
            ok, missing = v.validate(
                {"apt_deps": ["libssl-dev", "zlib1g-dev"]}
            )
        self.assertTrue(ok)
        self.assertEqual(missing, [])
        self.assertEqual(runner.run.call_count, 2)

    def test_some_missing(self):
        runner = MagicMock()
        runner.run.side_effect = [0, 1, 0]
        v = DependencyValidator(runner)
        with patch("builtins.print"):
            ok, missing = v.validate(
                {"apt_deps": [
                    "libssl-dev", "libpsl-dev",
                    "zlib1g-dev",
                ]}
            )
        self.assertFalse(ok)
        self.assertEqual(missing, ["libpsl-dev"])

    def test_all_missing(self):
        runner = MagicMock()
        runner.run.return_value = 1
        v = DependencyValidator(runner)
        with patch("builtins.print"):
            ok, missing = v.validate(
                {"apt_deps": ["a", "b"]}
            )
        self.assertFalse(ok)
        self.assertEqual(missing, ["a", "b"])

    def test_prints_install_hint(self):
        runner = MagicMock()
        runner.run.return_value = 1
        v = DependencyValidator(runner)
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            v.validate({"apt_deps": ["libfoo-dev"]})
        output = "\n".join(printed)
        self.assertIn("apt-get install", output)
        self.assertIn("libfoo-dev", output)


# ============================================================
# RepoCloner
# ============================================================

class TestRepoCloner(unittest.TestCase):
    """Tests for RepoCloner."""

    def test_skips_existing_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "myrepo"
            repo_dir.mkdir()
            (repo_dir / "file.txt").touch()

            runner = MagicMock()
            cloner = RepoCloner(runner)
            paths = {"repos_dir": tmpdir}
            cfg = {"url": "x", "branch": "main"}

            with patch("builtins.print"):
                result = cloner.clone(
                    "myrepo", cfg, paths
                )
            self.assertEqual(
                result, str(repo_dir)
            )
            runner.run.assert_not_called()

    def test_clones_new_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            cloner = RepoCloner(runner)
            paths = {"repos_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "main",
            }

            cloner.clone("newrepo", cfg, paths)
            # Two calls: clone + tag checkout attempt
            self.assertEqual(runner.run.call_count, 2)
            clone_args = runner.run.call_args_list[0]
            self.assertIn(
                "git clone", clone_args[0][0]
            )
            self.assertIn("main", clone_args[0][0])
            tag_args = runner.run.call_args_list[1]
            self.assertIn(
                "tags/main", tag_args[0][0]
            )

    def test_default_branch_master(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            cloner = RepoCloner(runner)
            paths = {"repos_dir": tmpdir}
            cfg = {"url": "https://github.com/x/y.git"}

            cloner.clone("repo", cfg, paths)
            call_args = runner.run.call_args
            self.assertIn("master", call_args[0][0])


# ============================================================
# BomtraceBuilder
# ============================================================

class TestBomtraceBuilder(unittest.TestCase):
    """Tests for BomtraceBuilder."""

    def _cfg(self):
        return (
            {
                "build_steps": [
                    "autoreconf -fi",
                    "./configure",
                    "make -j4",
                ],
                "clean_cmd": "make clean",
                "language": "c-cpp",
            },
            {"repos_dir": "/repos", "output_dir": "/out"},
            {
                "tracer": "bomtrace3",
                "raw_logfile": "/tmp/log",
                "create_bom_script": "/usr/bin/bom",
            },
        )

    def test_success(self):
        runner = MagicMock()
        runner.run.return_value = 0
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertTrue(result)
        # clean + 2 pre-build + instrumented + ADG = 5
        self.assertEqual(runner.run.call_count, 5)

    def test_success_no_clean_cmd(self):
        runner = MagicMock()
        runner.run.return_value = 0
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()
        del repo_cfg["clean_cmd"]

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertTrue(result)
        # no clean + 2 pre-build + instrumented + ADG = 4
        self.assertEqual(runner.run.call_count, 4)

    def test_prebuild_failure(self):
        runner = MagicMock()
        # clean ok, first pre-build fails
        runner.run.side_effect = [0, 1]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertFalse(result)

    def test_make_failure(self):
        runner = MagicMock()
        # clean ok, 2 pre-build ok, instrumented fails
        runner.run.side_effect = [0, 0, 0, 1]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertFalse(result)

    def test_adg_failure(self):
        runner = MagicMock()
        # clean ok, 2 pre-build ok, instrumented ok, ADG fails
        runner.run.side_effect = [0, 0, 0, 0, 1]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertFalse(result)

    def test_clean_failure_ignored(self):
        runner = MagicMock()
        # clean fails (fresh clone), rest succeeds
        runner.run.side_effect = [1, 0, 0, 0, 0]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertTrue(result)

    def test_instrumented_cmd_uses_tracer(self):
        runner = MagicMock()
        runner.run.return_value = 0
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        # clean(0) + pre-build(1,2) + instrumented(3)
        instrumented_call = runner.run.call_args_list[3]
        self.assertIn(
            "bomtrace3", instrumented_call[0][0]
        )


# ============================================================
# SpdxGenerator
# ============================================================

class TestSpdxGenerator(unittest.TestCase):
    """Tests for SpdxGenerator."""

    def _setup_repo(self, tmpdir):
        """Create fake repo with binaries."""
        repo_dir = (
            Path(tmpdir) / "repos" / "curl"
            / "src" / ".libs"
        )
        repo_dir.mkdir(parents=True)
        (repo_dir / "curl").write_bytes(b"bin")
        return {
            "repos_dir": str(Path(tmpdir) / "repos"),
            "output_dir": str(
                Path(tmpdir) / "output"
            ),
        }

    def test_generate_calls_bomsh_with_files(self):
        with tempfile.TemporaryDirectory() as td:
            runner = MagicMock()
            runner.run.return_value = 0
            gen = SpdxGenerator(runner)
            paths = self._setup_repo(td)
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }
            omnibor = {
                "sbom_script": "/usr/bin/sbom",
            }

            with patch("builtins.print"):
                gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                )
            cmd = runner.run.call_args[0][0]
            self.assertIn("-F ", cmd)
            self.assertIn("-s spdx-json", cmd)
            self.assertIn("src/.libs/curl", cmd)

    def test_generate_renames_output(self):
        with tempfile.TemporaryDirectory() as td:
            runner = MagicMock()
            runner.run.return_value = 0
            gen = SpdxGenerator(runner)
            paths = self._setup_repo(td)
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }
            omnibor = {
                "sbom_script": "/usr/bin/sbom",
            }

            # Simulate bomsh_sbom.py output
            spdx_dir = (
                Path(td) / "output" / "spdx"
                / "c-cpp" / "curl" / "2026-02-12_1300"
            )
            spdx_dir.mkdir(parents=True)
            (
                spdx_dir
                / "omnibor.curl.syft.spdx-json"
            ).write_text('{"creationInfo":{}}')

            with patch("builtins.print"), \
                    patch.object(
                        SpdxGenerator,
                        "patch_spdx_metadata",
                    ):
                result = gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                    run_ts="2026-02-12_1300",
                )
            self.assertIsNotNone(result)
            self.assertIn(
                "curl_omnibor.spdx.json", result
            )
            self.assertTrue(Path(result).exists())

    def test_generate_renames_all_spdx_json_files(self):
        """All .spdx-json files get renamed to .spdx.json."""
        with tempfile.TemporaryDirectory() as td:
            runner = MagicMock()
            runner.run.return_value = 0
            gen = SpdxGenerator(runner)
            paths = self._setup_repo(td)
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }
            omnibor = {
                "sbom_script": "/usr/bin/sbom",
            }

            # Simulate multiple bomsh_sbom.py outputs
            spdx_dir = (
                Path(td) / "output" / "spdx"
                / "c-cpp" / "curl" / "2026-02-12_1300"
            )
            spdx_dir.mkdir(parents=True)
            (
                spdx_dir
                / "omnibor.curl.syft.spdx-json"
            ).write_text('{"creationInfo":{}}')
            (
                spdx_dir
                / "curl.syft.spdx-json"
            ).write_text('{"creationInfo":{}}')
            (
                spdx_dir
                / "libcurl.syft.spdx-json"
            ).write_text('{"creationInfo":{}}')

            with patch("builtins.print"), \
                    patch.object(
                        SpdxGenerator,
                        "patch_spdx_metadata",
                    ):
                result = gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                    run_ts="2026-02-12_1300",
                )
            self.assertIsNotNone(result)

            # Primary renamed to standard name
            self.assertTrue(Path(result).exists())

            # Remaining files renamed to .spdx.json
            remaining = sorted(
                spdx_dir.glob("*.spdx.json")
            )
            names = [f.name for f in remaining]
            self.assertIn(
                "curl.syft.spdx.json", names
            )
            self.assertIn(
                "libcurl.syft.spdx.json", names
            )

            # No .spdx-json files should remain
            leftover = list(
                spdx_dir.glob("*.spdx-json")
            )
            self.assertEqual(len(leftover), 0)

    def test_generate_no_binaries_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            runner = MagicMock()
            gen = SpdxGenerator(runner)
            paths = {
                "repos_dir": str(
                    Path(td) / "repos"
                ),
                "output_dir": str(
                    Path(td) / "output"
                ),
            }
            repo_cfg = {
                "output_binaries": [
                    "nonexistent/bin"
                ],
                "language": "c-cpp",
            }
            omnibor = {"sbom_script": "x"}

            with patch("builtins.print"):
                result = gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                )
            self.assertIsNone(result)
            runner.run.assert_not_called()

    def test_generate_warns_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            runner = MagicMock()
            runner.run.return_value = 1
            gen = SpdxGenerator(runner)
            paths = self._setup_repo(td)
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }
            omnibor = {"sbom_script": "x"}

            printed = []
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                ),
            ):
                gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                )
            output = "\n".join(printed)
            self.assertIn("WARN", output)


# ============================================================
# SpdxGenerator — creator patching
# ============================================================

class TestSpdxGeneratorMetadata(unittest.TestCase):
    """Tests for SpdxGenerator.patch_spdx_metadata()."""

    def _write_spdx(self, tmpdir, doc):
        import json
        path = Path(tmpdir) / "test.spdx.json"
        path.write_text(json.dumps(doc))
        return str(path)

    def test_patches_creators_and_namespace(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/file/"
                    "curl-a1b2c3d4-e5f6-7890-abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [
                        "Tool: syft-1.42.0"
                    ],
                },
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1-5823f7d",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path
                )

            self.assertTrue(ok)
            result = json.loads(
                Path(path).read_text()
            )
            # --- creators ---
            creators = (
                result["creationInfo"]["creators"]
            )
            self.assertEqual(len(creators), 4)
            self.assertIn(
                "Tool: syft-1.42.0", creators
            )
            self.assertIn(
                "Tool: bomtrace3-6.11", creators
            )
            self.assertIn(
                "Tool: bomsh-0.0.1-5823f7d",
                creators,
            )
            self.assertTrue(
                any(
                    "omnibor-analysis" in c
                    for c in creators
                )
            )
            # --- namespace ---
            ns = result["documentNamespace"]
            self.assertIn("omnibor.io", ns)
            self.assertIn("curl", ns)
            self.assertIn(
                "a1b2c3d4-e5f6-7890-abcd-"
                "ef1234567890",
                ns,
            )
            self.assertNotIn("anchore.com", ns)

    def test_patch_idempotent(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/file/"
                    "curl-a1b2c3d4-e5f6-7890-abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [
                        "Tool: syft-1.42.0"
                    ],
                },
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                SpdxGenerator.patch_spdx_metadata(path)
                SpdxGenerator.patch_spdx_metadata(path)

            result = json.loads(
                Path(path).read_text()
            )
            creators = (
                result["creationInfo"]["creators"]
            )
            # Should not duplicate entries
            self.assertEqual(len(creators), 4)

    def test_patch_missing_file(self):
        ok = SpdxGenerator.patch_spdx_metadata(
            "/nonexistent.json"
        )
        self.assertFalse(ok)

    def test_patch_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False,
        ) as f:
            f.write("not json{{{")
            path = f.name
        try:
            ok = SpdxGenerator.patch_spdx_metadata(
                path
            )
            self.assertFalse(ok)
        finally:
            Path(path).unlink()

    def test_patch_no_creation_info(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            doc = {"spdxVersion": "SPDX-2.3"}
            path = self._write_spdx(td, doc)
            ok = SpdxGenerator.patch_spdx_metadata(
                path
            )
            self.assertFalse(ok)

    def test_namespace_no_uuid_uses_timestamp(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://example.com/no-uuid"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [],
                },
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch(
                "app.pipeline.spdx_generator.timestamp",
                return_value="2026-02-12_1300",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path
                )
            self.assertTrue(ok)
            result = json.loads(
                Path(path).read_text()
            )
            ns = result["documentNamespace"]
            self.assertIn("omnibor.io", ns)
            self.assertIn(
                "2026-02-12_1300", ns
            )

    def test_bomsh_version_fallback(self):
        with patch(
            "subprocess.check_output",
            side_effect=Exception("no cmd"),
        ):
            ver = SpdxGenerator._bomsh_version()
        self.assertEqual(ver, "unknown")

    def test_bomtrace_version_fallback(self):
        with patch(
            "subprocess.check_output",
            side_effect=Exception("no cmd"),
        ):
            ver = SpdxGenerator._bomtrace_version()
        self.assertEqual(ver, "unknown")

    def test_generate_calls_patch_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            # Set up repo with binary
            repo_dir = (
                Path(td) / "repos" / "curl"
                / "src" / ".libs"
            )
            repo_dir.mkdir(parents=True)
            (repo_dir / "curl").write_bytes(b"bin")
            paths = {
                "repos_dir": str(
                    Path(td) / "repos"
                ),
                "output_dir": str(
                    Path(td) / "output"
                ),
            }
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }
            omnibor = {
                "sbom_script": "/usr/bin/sbom",
            }
            # Simulate bomsh output
            spdx_dir = (
                Path(td) / "output"
                / "spdx" / "c-cpp" / "curl"
                / "2026-02-12_1300"
            )
            spdx_dir.mkdir(parents=True)
            (
                spdx_dir
                / "omnibor.curl.syft.spdx-json"
            ).write_text('{"creationInfo":{}}')

            runner = MagicMock()
            runner.run.return_value = 0
            gen = SpdxGenerator(runner)
            with patch.object(
                SpdxGenerator,
                "patch_spdx_metadata",
            ) as mock_patch, patch(
                "builtins.print"
            ):
                result = gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                    run_ts="2026-02-12_1300",
                )
            bom_dir = str(
                Path(td) / "output"
                / "omnibor" / "c-cpp" / "curl"
                / "2026-02-12_1300"
            )
            mock_patch.assert_called_once_with(
                result, bom_dir
            )

    def test_generate_no_patch_when_no_output(self):
        with tempfile.TemporaryDirectory() as td:
            repo_dir = (
                Path(td) / "repos" / "curl"
                / "src" / ".libs"
            )
            repo_dir.mkdir(parents=True)
            (repo_dir / "curl").write_bytes(b"bin")
            paths = {
                "repos_dir": str(
                    Path(td) / "repos"
                ),
                "output_dir": str(
                    Path(td) / "output"
                ),
            }
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }
            omnibor = {"sbom_script": "x"}
            runner = MagicMock()
            runner.run.return_value = 1
            gen = SpdxGenerator(runner)
            with patch.object(
                SpdxGenerator,
                "patch_spdx_metadata",
            ) as mock_patch, patch(
                "builtins.print"
            ):
                result = gen.generate(
                    "curl", repo_cfg,
                    paths, omnibor,
                )
            # No bomsh output file, so no patch
            mock_patch.assert_not_called()
            self.assertIsNone(result)

    def test_inject_omnibor_refs(self):
        """ExternalRefs injected when logfile+mapping exist."""
        import json
        with tempfile.TemporaryDirectory() as td:
            # Create bomsh metadata
            meta = (
                Path(td) / "bom" / "metadata" / "bomsh"
            )
            meta.mkdir(parents=True)
            sha_curl = "a" * 40
            sha_lib = "b" * 40
            (meta / "bomsh_hook_raw_logfile").write_text(
                f"outfile: {sha_curl} path: /repo/src/.libs/curl\n"
                f"outfile: {sha_lib} path: /repo/lib/.libs/libcurl.so\n"
            )
            (meta / "bomsh_omnibor_doc_mapping").write_text(
                json.dumps({
                    sha_curl: "omnibor_doc_curl",
                    sha_lib: "omnibor_doc_libcurl",
                })
            )
            # SPDX doc with matching packages
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/"
                    "curl-a1b2c3d4-e5f6-7890-"
                    "abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": ["Tool: syft-1.42.0"],
                },
                "packages": [
                    {
                        "name": "curl",
                        "SPDXID": "SPDXRef-curl",
                        "externalRefs": [],
                    },
                ],
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path, str(Path(td) / "bom")
                )
            self.assertTrue(ok)
            result = json.loads(
                Path(path).read_text()
            )
            refs = result["packages"][0][
                "externalRefs"
            ]
            omnibor_refs = [
                r for r in refs
                if "gitoid" in r.get(
                    "referenceLocator", ""
                )
            ]
            self.assertEqual(len(omnibor_refs), 1)
            self.assertIn(
                "omnibor_doc_curl",
                omnibor_refs[0]["referenceLocator"],
            )

    def test_inject_omnibor_refs_no_metadata(self):
        """No crash when bom_dir has no metadata."""
        import json
        with tempfile.TemporaryDirectory() as td:
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/"
                    "curl-a1b2c3d4-e5f6-7890-"
                    "abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [],
                },
                "packages": [
                    {"name": "curl", "SPDXID": "x"},
                ],
            }
            path = self._write_spdx(td, doc)
            bom_dir = str(Path(td) / "empty_bom")
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path, bom_dir
                )
            self.assertTrue(ok)
            result = json.loads(
                Path(path).read_text()
            )
            # No ExternalRefs injected
            refs = result["packages"][0].get(
                "externalRefs", []
            )
            omnibor = [
                r for r in refs
                if "gitoid" in r.get(
                    "referenceLocator", ""
                )
            ]
            self.assertEqual(len(omnibor), 0)

    def test_inject_omnibor_refs_no_match(self):
        """No injection when package name doesn't match."""
        import json
        with tempfile.TemporaryDirectory() as td:
            meta = (
                Path(td) / "bom" / "metadata" / "bomsh"
            )
            meta.mkdir(parents=True)
            sha_other = "c" * 40
            (meta / "bomsh_hook_raw_logfile").write_text(
                f"outfile: {sha_other} path: /repo/other_bin\n"
            )
            (meta / "bomsh_omnibor_doc_mapping").write_text(
                json.dumps({sha_other: "doc_other"})
            )
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/"
                    "curl-a1b2c3d4-e5f6-7890-"
                    "abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [],
                },
                "packages": [
                    {"name": "curl", "SPDXID": "x"},
                ],
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path, str(Path(td) / "bom")
                )
            self.assertTrue(ok)
            result = json.loads(
                Path(path).read_text()
            )
            refs = result["packages"][0].get(
                "externalRefs", []
            )
            self.assertEqual(len(refs), 0)

    def test_inject_refs_bad_mapping_json(self):
        """Graceful when mapping file has invalid JSON."""
        import json
        with tempfile.TemporaryDirectory() as td:
            meta = (
                Path(td) / "bom" / "metadata" / "bomsh"
            )
            meta.mkdir(parents=True)
            sha = "d" * 40
            (meta / "bomsh_hook_raw_logfile").write_text(
                f"outfile: {sha} path: /repo/curl\n"
            )
            (meta / "bomsh_omnibor_doc_mapping").write_text(
                "not-json{{{"
            )
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/"
                    "curl-a1b2c3d4-e5f6-7890-"
                    "abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [],
                },
                "packages": [
                    {"name": "curl", "SPDXID": "x"},
                ],
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path, str(Path(td) / "bom")
                )
            self.assertTrue(ok)

    def test_inject_refs_logfile_only(self):
        """Graceful when mapping file is missing."""
        import json
        with tempfile.TemporaryDirectory() as td:
            meta = (
                Path(td) / "bom" / "metadata" / "bomsh"
            )
            meta.mkdir(parents=True)
            sha = "e" * 40
            (meta / "bomsh_hook_raw_logfile").write_text(
                f"outfile: {sha} path: /repo/curl\n"
            )
            # No mapping file
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/"
                    "curl-a1b2c3d4-e5f6-7890-"
                    "abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [],
                },
                "packages": [
                    {"name": "curl", "SPDXID": "x"},
                ],
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path, str(Path(td) / "bom")
                )
            self.assertTrue(ok)

    def test_inject_refs_hash_not_in_mapping(self):
        """No ref when hash exists in logfile but not mapping."""
        import json
        with tempfile.TemporaryDirectory() as td:
            meta = (
                Path(td) / "bom" / "metadata" / "bomsh"
            )
            meta.mkdir(parents=True)
            sha = "f" * 40
            (meta / "bomsh_hook_raw_logfile").write_text(
                f"outfile: {sha} path: /repo/curl\n"
            )
            (meta / "bomsh_omnibor_doc_mapping").write_text(
                json.dumps({"other_hash": "doc"})
            )
            doc = {
                "spdxVersion": "SPDX-2.3",
                "name": "curl",
                "documentNamespace": (
                    "https://anchore.com/syft/"
                    "curl-a1b2c3d4-e5f6-7890-"
                    "abcd-ef1234567890"
                ),
                "creationInfo": {
                    "created": "2026-01-01T00:00:00Z",
                    "creators": [],
                },
                "packages": [
                    {"name": "curl", "SPDXID": "x"},
                ],
            }
            path = self._write_spdx(td, doc)
            with patch.object(
                SpdxGenerator, "_bomsh_version",
                return_value="0.0.1",
            ), patch.object(
                SpdxGenerator, "_bomtrace_version",
                return_value="6.11",
            ), patch("builtins.print"):
                ok = SpdxGenerator.patch_spdx_metadata(
                    path, str(Path(td) / "bom")
                )
            self.assertTrue(ok)
            result = json.loads(
                Path(path).read_text()
            )
            refs = result["packages"][0].get(
                "externalRefs", []
            )
            self.assertEqual(len(refs), 0)


# ============================================================
# SpdxValidator
# ============================================================

class TestSpdxValidator(unittest.TestCase):
    """Tests for SpdxValidator."""

    def _minimal_spdx(self):
        """Return a minimal valid SPDX 2.3 JSON dict."""
        return {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test-doc",
            "documentNamespace": (
                "https://example.org/test"
            ),
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
        }

    def test_validate_file_not_found(self):
        v = SpdxValidator()
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            result = v.validate("/nonexistent.json")
        self.assertIsNone(result["schema_ok"])
        self.assertIsNone(result["semantic_ok"])
        self.assertIn(
            "not found",
            "\n".join(printed),
        )

    def test_validate_invalid_json(self):
        import json
        v = SpdxValidator()
        with tempfile.NamedTemporaryFile(
            suffix=".spdx.json", mode="w",
            delete=False,
        ) as f:
            f.write("not json{{{")
            path = f.name
        try:
            printed = []
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                ),
            ):
                result = v.validate(path)
            self.assertIsNone(result["schema_ok"])
            output = "\n".join(printed)
            self.assertIn("Cannot read", output)
        finally:
            Path(path).unlink()

    def test_schema_validation_pass(self):
        """Minimal SPDX doc should pass schema."""
        import json
        v = SpdxValidator()
        with tempfile.NamedTemporaryFile(
            suffix=".spdx.json", mode="w",
            delete=False,
        ) as f:
            json.dump(self._minimal_spdx(), f)
            path = f.name
        try:
            with patch("builtins.print"):
                result = v.validate(path)
            # Schema should pass (or be skipped if
            # network unavailable)
            if result["schema_ok"] is not None:
                self.assertTrue(result["schema_ok"])
        finally:
            Path(path).unlink()

    def test_schema_validation_fail(self):
        """Invalid doc should fail schema."""
        import json
        v = SpdxValidator()
        bad_doc = {"not": "spdx"}
        with tempfile.NamedTemporaryFile(
            suffix=".spdx.json", mode="w",
            delete=False,
        ) as f:
            json.dump(bad_doc, f)
            path = f.name
        try:
            with patch("builtins.print"):
                result = v.validate(path)
            if result["schema_ok"] is not None:
                self.assertFalse(result["schema_ok"])
                self.assertTrue(
                    len(result["schema_errors"]) > 0
                )
        finally:
            Path(path).unlink()

    def test_schema_skipped_when_jsonschema_missing(
        self,
    ):
        """Schema check skipped if jsonschema absent."""
        import json
        v = SpdxValidator()
        with tempfile.NamedTemporaryFile(
            suffix=".spdx.json", mode="w",
            delete=False,
        ) as f:
            json.dump(self._minimal_spdx(), f)
            path = f.name
        try:
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "jsonschema":
                    raise ImportError("mocked")
                return real_import(
                    name, *args, **kwargs
                )

            with patch(
                "builtins.__import__",
                side_effect=mock_import,
            ):
                with patch("builtins.print"):
                    result = v.validate(path)
            self.assertIsNone(result["schema_ok"])
        finally:
            Path(path).unlink()

    def test_semantic_skipped_when_spdx_tools_missing(
        self,
    ):
        """Semantic check skipped if spdx-tools absent."""
        import json
        v = SpdxValidator()
        with tempfile.NamedTemporaryFile(
            suffix=".spdx.json", mode="w",
            delete=False,
        ) as f:
            json.dump(self._minimal_spdx(), f)
            path = f.name
        try:
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "spdx_tools" in name:
                    raise ImportError("mocked")
                return real_import(
                    name, *args, **kwargs
                )

            with patch(
                "builtins.__import__",
                side_effect=mock_import,
            ):
                with patch("builtins.print"):
                    result = v.validate(path)
            self.assertIsNone(result["semantic_ok"])
        finally:
            Path(path).unlink()

    def test_semantic_parse_error(self):
        """Semantic fails gracefully on unparseable doc."""
        import json
        v = SpdxValidator()
        bad_doc = {"spdxVersion": "SPDX-2.3"}
        with tempfile.NamedTemporaryFile(
            suffix=".spdx.json", mode="w",
            delete=False,
        ) as f:
            json.dump(bad_doc, f)
            path = f.name
        try:
            with patch("builtins.print"):
                result = v.validate(path)
            if result["semantic_ok"] is not None:
                self.assertFalse(result["semantic_ok"])
                self.assertTrue(
                    len(result["semantic_errors"]) > 0
                )
        finally:
            Path(path).unlink()

    def test_print_summary_pass(self):
        """Summary prints PASS for valid results."""
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            SpdxValidator._print_summary(
                "/tmp/test.spdx.json",
                {
                    "schema_ok": True,
                    "semantic_ok": True,
                    "schema_errors": [],
                    "semantic_errors": [],
                },
            )
        output = "\n".join(printed)
        self.assertIn("PASS", output)

    def test_print_summary_fail(self):
        """Summary prints FAIL with error count."""
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            SpdxValidator._print_summary(
                "/tmp/test.spdx.json",
                {
                    "schema_ok": False,
                    "semantic_ok": False,
                    "schema_errors": ["err1", "err2"],
                    "semantic_errors": ["err3"],
                },
            )
        output = "\n".join(printed)
        self.assertIn("FAIL", output)
        self.assertIn("2 errors", output)

    def test_print_summary_skipped(self):
        """Summary prints SKIPPED when None."""
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            SpdxValidator._print_summary(
                "/tmp/test.spdx.json",
                {
                    "schema_ok": None,
                    "semantic_ok": None,
                    "schema_errors": [],
                    "semantic_errors": [],
                },
            )
        output = "\n".join(printed)
        self.assertIn("SKIPPED", output)


# ============================================================
# SyftGenerator
# ============================================================

class TestSyftGenerator(unittest.TestCase):
    """Tests for SyftGenerator."""

    def test_generate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            gen = SyftGenerator(runner)
            repo_cfg = {"language": "c-cpp"}
            paths = {
                "repos_dir": tmpdir,
                "output_dir": tmpdir,
            }

            with patch("builtins.print"):
                result = gen.generate(
                    "curl", repo_cfg, paths,
                    run_ts="2026-02-12_1300",
                )
            self.assertIn(
                "curl_syft.spdx.json", result
            )

    def test_generate_creates_html_visualization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            spdx_dir = (
                Path(tmpdir) / "spdx" / "c-cpp"
                / "curl" / "2026-02-12_1300"
            )
            spdx_dir.mkdir(parents=True)
            spdx_file = (
                spdx_dir / "curl_syft.spdx.json"
            )
            minimal_spdx = {
                "spdxVersion": "SPDX-2.3",
                "SPDXID": "SPDXRef-DOCUMENT",
                "name": "curl-syft",
                "packages": [],
                "relationships": [],
            }

            def fake_run(cmd, **kw):
                import json
                spdx_file.write_text(
                    json.dumps(minimal_spdx)
                )
                return 0

            runner.run.side_effect = fake_run
            gen = SyftGenerator(runner)
            repo_cfg = {"language": "c-cpp"}
            paths = {
                "repos_dir": tmpdir,
                "output_dir": tmpdir,
            }

            with patch("builtins.print"):
                with patch(
                    "spdx_visualize.generate_html"
                ) as mock_viz:
                    result = gen.generate(
                        "curl", repo_cfg, paths,
                        run_ts="2026-02-12_1300",
                    )
                    mock_viz.assert_called_once()
                    html_arg = (
                        mock_viz.call_args[0][1]
                    )
                    self.assertIn(
                        "curl_syft.spdx.html",
                        html_arg,
                    )

    def test_generate_warns_on_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 1
            gen = SyftGenerator(runner)
            repo_cfg = {"language": "c-cpp"}
            paths = {
                "repos_dir": tmpdir,
                "output_dir": tmpdir,
            }

            printed = []
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                ),
            ):
                gen.generate("curl", repo_cfg, paths)
            output = "\n".join(printed)
            self.assertIn("WARN", output)


# ============================================================
# BinaryCollector
# ============================================================

class TestBinaryCollector(unittest.TestCase):
    """Tests for BinaryCollector."""

    @patch("app.pipeline.binary_collector.timestamp", return_value="2026-02-12_1300")
    def test_collect_copies_binaries(self, _ts):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake repo with a binary
            repo_dir = Path(tmpdir) / "repos" / "curl"
            (repo_dir / "src" / ".libs").mkdir(
                parents=True
            )
            binary = repo_dir / "src" / ".libs" / "curl"
            binary.write_bytes(b"\x7fELF fake binary")

            paths = {
                "repos_dir": str(Path(tmpdir) / "repos"),
                "output_dir": str(
                    Path(tmpdir) / "output"
                ),
            }
            cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }

            with patch("builtins.print"):
                result = BinaryCollector.collect(
                    "curl", cfg, paths
                )

            self.assertEqual(len(result), 1)
            dst = Path(result[0][1])
            self.assertTrue(dst.exists())
            self.assertEqual(dst.name, "curl")
            self.assertIn(
                "2026-02-12_1300", str(dst)
            )
            self.assertEqual(
                dst.read_bytes(),
                b"\x7fELF fake binary",
            )

    @patch("app.pipeline.binary_collector.timestamp", return_value="2026-02-12_1300")
    def test_collect_missing_binary_warns(self, _ts):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "repos" / "curl"
            repo_dir.mkdir(parents=True)

            paths = {
                "repos_dir": str(Path(tmpdir) / "repos"),
                "output_dir": str(
                    Path(tmpdir) / "output"
                ),
            }
            cfg = {
                "output_binaries": [
                    "src/.libs/curl"
                ],
                "language": "c-cpp",
            }

            printed = []
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                ),
            ):
                result = BinaryCollector.collect(
                    "curl", cfg, paths
                )

            self.assertEqual(len(result), 0)
            output = "\n".join(printed)
            self.assertIn("not found", output)

    def test_collect_no_output_binaries_defined(self):
        paths = {
            "repos_dir": "/tmp",
            "output_dir": "/tmp",
        }
        cfg = {"language": "c-cpp"}

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            result = BinaryCollector.collect(
                "curl", cfg, paths
            )

        self.assertEqual(len(result), 0)
        output = "\n".join(printed)
        self.assertIn("No output_binaries", output)

    @patch("app.pipeline.binary_collector.timestamp", return_value="2026-02-12_1300")
    def test_collect_multiple_binaries(self, _ts):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "repos" / "curl"
            (repo_dir / "src" / ".libs").mkdir(
                parents=True
            )
            (repo_dir / "lib" / ".libs").mkdir(
                parents=True
            )
            (
                repo_dir / "src" / ".libs" / "curl"
            ).write_bytes(b"bin1")
            (
                repo_dir / "lib" / ".libs"
                / "libcurl.so"
            ).write_bytes(b"bin2")

            paths = {
                "repos_dir": str(Path(tmpdir) / "repos"),
                "output_dir": str(
                    Path(tmpdir) / "output"
                ),
            }
            cfg = {
                "output_binaries": [
                    "src/.libs/curl",
                    "lib/.libs/libcurl.so",
                ],
                "language": "c-cpp",
            }

            with patch("builtins.print"):
                result = BinaryCollector.collect(
                    "curl", cfg, paths
                )

            self.assertEqual(len(result), 2)
            out_dir = (
                Path(tmpdir) / "output"
                / "binaries" / "c-cpp" / "curl"
                / "2026-02-12_1300"
            )
            self.assertTrue(
                (out_dir / "curl").exists()
            )
            self.assertTrue(
                (out_dir / "libcurl.so").exists()
            )


# ============================================================
# DocWriter
# ============================================================

class TestDocWriter(unittest.TestCase):
    """Tests for DocWriter."""

    def test_write_build_doc_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "main",
                "description": "test repo",
                "build_steps": ["./configure", "make"],
                "output_binaries": ["bin/app"],
                "language": "c-cpp",
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "myrepo", cfg, paths,
                    True, 42.5,
                )
            self.assertTrue(Path(result).exists())
            content = Path(result).read_text()
            self.assertIn("SUCCESS", content)
            self.assertIn("42.5", content)
            self.assertIn("myrepo", content)
            self.assertIn("bin/app", content)

    def test_write_build_doc_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "x",
                "build_steps": ["make"],
                "language": "c-cpp",
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "repo", cfg, paths,
                    False, 10.0,
                )
            content = Path(result).read_text()
            self.assertIn("FAILED", content)

    def test_write_runtime_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            repo_cfg = {"language": "c-cpp"}
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "myrepo", repo_cfg, paths, 55.3,
                )
            self.assertTrue(Path(result).exists())
            content = Path(result).read_text()
            self.assertIn("55.3", content)
            self.assertIn("myrepo", content)

    def test_write_runtime_doc_with_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            repo_cfg = {"language": "c-cpp"}
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "repo", repo_cfg, paths, 60.0,
                    baseline_sec=30.0,
                )
            content = Path(result).read_text()
            self.assertIn("100.0%", content)

    def test_write_runtime_doc_no_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            repo_cfg = {"language": "c-cpp"}
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "repo", repo_cfg, paths, 60.0,
                    baseline_sec=None,
                )
            content = Path(result).read_text()
            self.assertNotIn("overhead", content)

    def test_write_build_doc_go(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "master",
                "description": "Go CLI tool",
                "build_steps": [
                    "go build -o fzf .",
                ],
                "output_binaries": ["fzf"],
                "language": "go",
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "fzf", cfg, paths,
                    True, 10.0,
                    tracer="bomtrace2",
                )
            content = Path(result).read_text()
            self.assertIn("bomtrace2", content)
            self.assertNotIn(
                "**Tracer:** bomtrace3", content
            )
            self.assertIn("fzf", content)

    def test_write_runtime_doc_go(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            repo_cfg = {
                "language": "go",
                "build_steps": ["go build -a -o fzf ."],
            }
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "fzf", repo_cfg, paths, 10.0,
                    tracer="bomtrace2",
                )
            content = Path(result).read_text()
            self.assertIn(
                "Instrumented build time", content
            )
            self.assertIn("go build -a", content)
            self.assertIn("bomtrace2", content)

    def test_write_build_doc_rust(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "https://github.com/oxipng/oxipng.git",
                "branch": "master",
                "description": "PNG optimizer",
                "build_steps": [
                    "cargo build --release",
                ],
                "output_binaries": [
                    "target/release/oxipng",
                ],
                "language": "rust",
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "oxipng", cfg, paths,
                    True, 15.0,
                    tracer="bomtrace2",
                )
            content = Path(result).read_text()
            self.assertIn("bomtrace2", content)
            self.assertIn("oxipng", content)

    def test_write_runtime_doc_rust(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            repo_cfg = {
                "language": "rust",
                "build_steps": [
                    "cargo build --release",
                ],
            }
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "oxipng", repo_cfg, paths, 15.0,
                    tracer="bomtrace2",
                )
            content = Path(result).read_text()
            self.assertIn(
                "Instrumented build time", content
            )
            self.assertIn(
                "cargo build --release", content
            )
            self.assertIn("bomtrace2", content)

    def test_write_build_doc_c_cpp_has_bomtrace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "main",
                "build_steps": ["make"],
                "output_binaries": ["app"],
                "language": "c-cpp",
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "myrepo", cfg, paths,
                    True, 42.5,
                    tracer="bomtrace3",
                )
            content = Path(result).read_text()
            self.assertIn("bomtrace3", content)
            self.assertNotIn("bomtrace2", content)

    def test_write_build_doc_has_release_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "main",
                "build_steps": [
                    "./configure", "make",
                ],
                "output_binaries": ["bin/app"],
                "language": "c-cpp",
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "myrepo", cfg, paths,
                    True, 10.0,
                )
            content = Path(result).read_text()
            self.assertIn(
                "Release Build Verification", content
            )
            self.assertIn("RELEASE", content)


class TestClassifyReleaseBuild(unittest.TestCase):
    """Tests for DocWriter.classify_release_build."""

    def test_c_cpp_release(self):
        cfg = {
            "language": "c-cpp",
            "build_steps": [
                "./configure --with-openssl",
                "make -j$(nproc)",
            ],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])
        self.assertEqual(rb["label"], "RELEASE")
        self.assertEqual(rb["warnings"], [])
        self.assertIn("configure", rb["reason"])

    def test_c_cpp_make_only(self):
        cfg = {
            "language": "c-cpp",
            "build_steps": ["make -j$(nproc)"],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])
        self.assertIn("default optimization", rb["reason"])

    def test_c_cpp_debug_flag(self):
        cfg = {
            "language": "c-cpp",
            "build_steps": [
                "./configure --enable-debug",
                "make",
            ],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertFalse(rb["is_release"])
        self.assertEqual(rb["label"], "WARNING")
        self.assertEqual(len(rb["warnings"]), 1)
        self.assertIn("--enable-debug", rb["warnings"][0])

    def test_c_cpp_asan(self):
        cfg = {
            "language": "c-cpp",
            "build_steps": ["make ASAN=1"],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertFalse(rb["is_release"])
        self.assertIn("ASAN=1", rb["warnings"][0])

    def test_rust_release(self):
        cfg = {
            "language": "rust",
            "build_steps": ["cargo build --release"],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])
        self.assertEqual(rb["label"], "RELEASE")

    def test_rust_debug(self):
        cfg = {
            "language": "rust",
            "build_steps": ["cargo build"],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertFalse(rb["is_release"])
        self.assertIn("--release", rb["warnings"][0])

    def test_go_release(self):
        cfg = {
            "language": "go",
            "build_steps": [
                'go build -a -trimpath '
                '-ldflags="-s -w" -o app .',
            ],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])
        self.assertEqual(rb["label"], "RELEASE")

    def test_go_missing_trimpath(self):
        cfg = {
            "language": "go",
            "build_steps": ["go build -a -o app ."],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertFalse(rb["is_release"])
        self.assertEqual(len(rb["warnings"]), 2)

    def test_go_partial_flags(self):
        cfg = {
            "language": "go",
            "build_steps": [
                "go build -a -trimpath -o app .",
            ],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertFalse(rb["is_release"])
        self.assertEqual(len(rb["warnings"]), 1)
        self.assertIn("ldflags", rb["warnings"][0])

    def test_java_release(self):
        cfg = {
            "language": "java",
            "build_steps": [
                "mvn package -DskipTests -q",
            ],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])

    def test_java_missing_skip_tests(self):
        cfg = {
            "language": "java",
            "build_steps": ["mvn package -q"],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertFalse(rb["is_release"])
        self.assertIn(
            "-DskipTests", rb["warnings"][0]
        )

    def test_unknown_language(self):
        cfg = {
            "language": "python",
            "build_steps": ["pip install ."],
        }
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])
        self.assertIn("unknown", rb["reason"])

    def test_default_language(self):
        cfg = {"build_steps": ["make"]}
        rb = DocWriter.classify_release_build(cfg)
        self.assertTrue(rb["is_release"])
        self.assertIn("optimization", rb["reason"])


# ============================================================
# AnalysisPipeline
# ============================================================

class TestAnalysisPipeline(unittest.TestCase):
    """Tests for AnalysisPipeline facade."""

    def test_default_construction(self):
        p = AnalysisPipeline()
        self.assertIsInstance(p.runner, CommandRunner)
        self.assertIsInstance(
            p.validator, DependencyValidator
        )
        self.assertIsInstance(p.cloner, RepoCloner)
        self.assertIsInstance(
            p.builder, BomtraceBuilder
        )
        self.assertIsInstance(
            p.spdx_gen, SpdxGenerator
        )
        self.assertIsInstance(
            p.spdx_validator, SpdxValidator
        )
        self.assertIsInstance(
            p.syft_gen, SyftGenerator
        )
        self.assertIsInstance(
            p.binary_collector, BinaryCollector
        )
        self.assertIsInstance(p.docs, DocWriter)

    def test_injected_components(self):
        runner = MagicMock()
        p = AnalysisPipeline(runner=runner)
        self.assertIs(p.runner, runner)

    def test_list_repos(self):
        config = {
            "repos": {
                "curl": {
                    "description": "URL lib",
                    "url": "https://github.com/curl/curl.git",
                },
            }
        }
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            AnalysisPipeline.list_repos(config)
        output = "\n".join(printed)
        self.assertIn("curl", output)
        self.assertIn("URL lib", output)


# ============================================================
# main() CLI
# ============================================================

def _mock_pipeline():
    """Create an AnalysisPipeline with all mocked components."""
    runner = MagicMock()
    validator = MagicMock()
    validator.validate.return_value = (True, [])
    cloner = MagicMock()
    builder = MagicMock()
    spdx_gen = MagicMock()
    metadata_collector = MagicMock()
    adg_spdx = MagicMock()
    adg_spdx.generate.return_value = []
    spdx_validator = MagicMock()
    syft_gen = MagicMock()
    binary_collector = MagicMock()
    doc_writer = MagicMock()
    return AnalysisPipeline(
        runner=runner,
        validator=validator,
        cloner=cloner,
        builder=builder,
        spdx_gen=spdx_gen,
        metadata_collector=metadata_collector,
        adg_spdx=adg_spdx,
        spdx_validator=spdx_validator,
        syft_gen=syft_gen,
        binary_collector=binary_collector,
        doc_writer=doc_writer,
    )


class TestMainList(unittest.TestCase):
    """Tests for main() --list mode."""

    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch("sys.argv", ["analyze.py", "--list"])
    def test_list_mode(self, mock_cls):
        p = MagicMock()
        mock_cls.return_value = p
        with patch("builtins.print"):
            analyze.main()
        p.list_repos.assert_called_once()


class TestMainNoRepo(unittest.TestCase):
    """Tests for main() without --repo."""

    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch("sys.argv", ["analyze.py"])
    def test_exits_without_repo(self, mock_cls):
        mock_cls.return_value = _mock_pipeline()
        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                analyze.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainUnknownRepo(unittest.TestCase):
    """Tests for main() with unknown repo."""

    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "nonexistent"],
    )
    def test_exits_unknown_repo(self, mock_cls):
        mock_cls.return_value = _mock_pipeline()
        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                analyze.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainFullRun(unittest.TestCase):
    """Tests for main() full analysis run."""

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_full_run_success(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = True
        mock_time.side_effect = [100.0, 142.5]

        with patch("builtins.print"):
            analyze.main()

        p.cloner.clone.assert_called_once()
        p.syft_gen.generate.assert_called_once()
        p.validator.validate.assert_called_once()
        p.builder.build.assert_called_once()
        p.spdx_gen.generate.assert_called_once()
        p.spdx_validator.validate.assert_called_once()
        p.binary_collector.collect.assert_called_once()
        p.docs.write_build_doc.assert_called_once()
        p.docs.write_runtime_doc.assert_called_once()

    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_validation_failure_exits(
        self, mock_cls
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.validator.validate.return_value = (
            False, ["libpsl-dev"]
        )

        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                analyze.main()
            self.assertEqual(cm.exception.code, 1)

        p.builder.build.assert_not_called()

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_full_run_build_failure(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = False
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        p.spdx_gen.generate.assert_not_called()
        p.spdx_validator.validate.assert_not_called()
        p.binary_collector.collect.assert_not_called()
        p.docs.write_build_doc.assert_called_once()

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        [
            "analyze.py", "--repo", "curl",
            "--skip-clone",
        ],
    )
    def test_skip_clone(self, mock_cls, mock_time):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = True
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        p.cloner.clone.assert_not_called()

    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        [
            "analyze.py", "--repo", "curl",
            "--syft-only",
        ],
    )
    def test_syft_only(self, mock_cls):
        p = _mock_pipeline()
        mock_cls.return_value = p

        with patch("builtins.print"):
            analyze.main()

        p.syft_gen.generate.assert_called_once()
        p.builder.build.assert_not_called()
        p.spdx_gen.generate.assert_not_called()


# ============================================================
# Go pipeline (main + _run_go_pipeline)
# ============================================================

class TestMainGoRepo(unittest.TestCase):
    """Tests for main() with Go repos."""

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "fzf"],
    )
    def test_go_uses_bomtrace2(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = True
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        # Go uses builder (bomtrace2) for
        # instrumented build — same as C/C++
        p.builder.build.assert_called_once()
        # Full pipeline steps called
        p.cloner.clone.assert_called_once()
        p.syft_gen.generate.assert_called_once()
        p.spdx_gen.generate.assert_called_once()
        p.metadata_collector.collect\
            .assert_called_once()
        p.adg_spdx.generate.assert_called_once()
        p.binary_collector.collect\
            .assert_called_once()
        p.docs.write_build_doc.assert_called_once()
        p.docs.write_runtime_doc\
            .assert_called_once()

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "fzf"],
    )
    def test_go_build_failure(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = False
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        p.binary_collector.collect\
            .assert_not_called()
        p.docs.write_build_doc.assert_called_once()

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        [
            "analyze.py", "--repo", "fzf",
            "--syft-only",
        ],
    )
    def test_go_syft_only(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p

        with patch("builtins.print"):
            analyze.main()

        p.syft_gen.generate.assert_called_once()
        p.builder.build.assert_not_called()


class TestRunGoPipeline(unittest.TestCase):
    """Unit tests for _run_go_pipeline."""

    GO_OMNIBOR_CFG = {
        "tracer": (
            "bomtrace2 -c "
            "/opt/bomsh/bin/bomtrace_go.conf"
        ),
        "create_bom_script": "bomsh_create_bom.py",
        "sbom_script": "bomsh_sbom.py",
        "raw_logfile": (
            "/tmp/bomsh_hook_raw_logfile.sha1"
        ),
    }

    def test_instrumented_build_called(self):
        p = _mock_pipeline()
        p.builder.build.return_value = True
        repo_cfg = {"language": "go"}
        paths_cfg = {"output_dir": "/tmp/out"}

        with patch("builtins.print"):
            success, duration = _run_go_pipeline(
                p, "fzf", repo_cfg,
                paths_cfg, self.GO_OMNIBOR_CFG,
                "2026-03-04_1200",
            )

        self.assertTrue(success)
        p.builder.build.assert_called_once_with(
            "fzf", repo_cfg,
            paths_cfg, self.GO_OMNIBOR_CFG,
            run_ts="2026-03-04_1200",
        )

    def test_full_pipeline_on_success(self):
        p = _mock_pipeline()
        p.builder.build.return_value = True
        repo_cfg = {"language": "go"}
        paths_cfg = {"output_dir": "/tmp/out"}

        with patch("builtins.print"):
            _run_go_pipeline(
                p, "fzf", repo_cfg,
                paths_cfg, self.GO_OMNIBOR_CFG,
                "2026-03-04_1200",
            )

        # Full pipeline: SPDX gen, metadata,
        # ADG SPDX, binaries
        p.spdx_gen.generate.assert_called_once()
        p.metadata_collector.collect\
            .assert_called_once()
        p.adg_spdx.generate.assert_called_once()
        p.binary_collector.collect\
            .assert_called_once()

    def test_skips_steps_on_failure(self):
        p = _mock_pipeline()
        p.builder.build.return_value = False
        repo_cfg = {"language": "go"}
        paths_cfg = {"output_dir": "/tmp/out"}

        with patch("builtins.print"):
            success, _ = _run_go_pipeline(
                p, "fzf", repo_cfg,
                paths_cfg, self.GO_OMNIBOR_CFG,
                "2026-03-04_1200",
            )

        self.assertFalse(success)
        p.spdx_gen.generate.assert_not_called()
        p.metadata_collector.collect\
            .assert_not_called()
        p.adg_spdx.generate.assert_not_called()
        p.binary_collector.collect\
            .assert_not_called()

    def test_validates_syft_spdx(self):
        """Syft validation is now in _validate_syft_spdx."""
        with tempfile.TemporaryDirectory() as td:
            p = _mock_pipeline()
            repo_cfg = {"language": "go"}
            paths_cfg = {"output_dir": td}

            spdx_dir = (
                Path(td) / "spdx" / "go"
                / "fzf" / "2026-03-04_1200"
            )
            spdx_dir.mkdir(parents=True)
            (
                spdx_dir / "fzf_syft.spdx.json"
            ).write_text("{}")

            _validate_syft_spdx(
                p, "fzf", repo_cfg,
                paths_cfg, "2026-03-04_1200",
            )

            v = p.spdx_validator.validate
            calls = [
                str(c) for c in v.call_args_list
            ]
            syft_calls = [
                c for c in calls
                if "syft" in c
            ]
            self.assertTrue(len(syft_calls) > 0)


# ============================================================
# Rust pipeline (_run_rust_pipeline)
# ============================================================

class TestRunRustPipeline(unittest.TestCase):
    """Unit tests for _run_rust_pipeline."""

    RUST_OMNIBOR_CFG = {
        "tracer": "bomtrace2",
        "create_bom_script": "bomsh_create_bom.py",
        "sbom_script": "bomsh_sbom.py",
        "raw_logfile": (
            "/tmp/bomsh_hook_raw_logfile.sha1"
        ),
    }

    def test_instrumented_build_called(self):
        p = _mock_pipeline()
        p.builder.build.return_value = True
        repo_cfg = {"language": "rust"}
        paths_cfg = {"output_dir": "/tmp/out"}

        with patch("builtins.print"):
            success, duration = _run_rust_pipeline(
                p, "oxipng", repo_cfg,
                paths_cfg, self.RUST_OMNIBOR_CFG,
                "2026-03-05_1200",
            )

        self.assertTrue(success)
        p.builder.build.assert_called_once_with(
            "oxipng", repo_cfg,
            paths_cfg, self.RUST_OMNIBOR_CFG,
            run_ts="2026-03-05_1200",
        )

    def test_full_pipeline_on_success(self):
        p = _mock_pipeline()
        p.builder.build.return_value = True
        repo_cfg = {"language": "rust"}
        paths_cfg = {"output_dir": "/tmp/out"}

        with patch("builtins.print"):
            _run_rust_pipeline(
                p, "oxipng", repo_cfg,
                paths_cfg, self.RUST_OMNIBOR_CFG,
                "2026-03-05_1200",
            )

        p.spdx_gen.generate.assert_called_once()
        p.metadata_collector.collect\
            .assert_called_once()
        p.adg_spdx.generate.assert_called_once()
        p.binary_collector.collect\
            .assert_called_once()

    def test_skips_steps_on_failure(self):
        p = _mock_pipeline()
        p.builder.build.return_value = False
        repo_cfg = {"language": "rust"}
        paths_cfg = {"output_dir": "/tmp/out"}

        with patch("builtins.print"):
            success, _ = _run_rust_pipeline(
                p, "oxipng", repo_cfg,
                paths_cfg, self.RUST_OMNIBOR_CFG,
                "2026-03-05_1200",
            )

        self.assertFalse(success)
        p.spdx_gen.generate.assert_not_called()
        p.metadata_collector.collect\
            .assert_not_called()
        p.adg_spdx.generate.assert_not_called()
        p.binary_collector.collect\
            .assert_not_called()

    def test_validates_syft_spdx(self):
        """Syft validation is now in _validate_syft_spdx."""
        with tempfile.TemporaryDirectory() as td:
            p = _mock_pipeline()
            repo_cfg = {"language": "rust"}
            paths_cfg = {"output_dir": td}

            spdx_dir = (
                Path(td) / "spdx" / "rust"
                / "oxipng" / "2026-03-05_1200"
            )
            spdx_dir.mkdir(parents=True)
            (
                spdx_dir / "oxipng_syft.spdx.json"
            ).write_text("{}")

            _validate_syft_spdx(
                p, "oxipng", repo_cfg,
                paths_cfg, "2026-03-05_1200",
            )

            v = p.spdx_validator.validate
            calls = [
                str(c) for c in v.call_args_list
            ]
            syft_calls = [
                c for c in calls
                if "syft" in c
            ]
            self.assertTrue(len(syft_calls) > 0)


# ============================================================
# SpdxGenerator — version detection branches
# ============================================================

class TestVersionDetection(unittest.TestCase):
    """Cover _bomsh_version and _bomtrace_version branches."""

    def test_bomsh_version_ver_and_commit(self):
        """Lines 339-340: ver + commit returns 'ver-commit'."""
        with patch(
            "subprocess.check_output",
            side_effect=[
                "bomsh_create_bom.py 0.0.1",
                "5823f7d",
            ],
        ):
            ver = SpdxGenerator._bomsh_version()
        self.assertEqual(ver, "0.0.1-5823f7d")

    def test_bomsh_version_commit_only(self):
        """Line 341-342: no ver, only commit."""
        with patch(
            "subprocess.check_output",
            side_effect=[
                Exception("no cmd"),
                "abc1234",
            ],
        ):
            ver = SpdxGenerator._bomsh_version()
        self.assertEqual(ver, "git-abc1234")

    def test_bomsh_version_ver_only(self):
        """Line 343-344: ver but no commit."""
        with patch(
            "subprocess.check_output",
            side_effect=[
                "bomsh_create_bom.py 0.0.1",
                Exception("no git"),
            ],
        ):
            ver = SpdxGenerator._bomsh_version()
        self.assertEqual(ver, "0.0.1")

    def test_bomsh_version_empty_output(self):
        """Line 321: empty output."""
        with patch(
            "subprocess.check_output",
            side_effect=[
                "",
                Exception("no git"),
            ],
        ):
            ver = SpdxGenerator._bomsh_version()
        self.assertIsNotNone(ver)

    def test_bomtrace_version_found(self):
        """Lines 360-374: bomtrace3 found, version extracted."""
        with patch("shutil.which", return_value="/usr/bin/bomtrace3"):
            with patch(
                "subprocess.check_output",
                return_value="some stuff\n6.11-dirty\nmore stuff\n",
            ):
                ver = SpdxGenerator._bomtrace_version()
        self.assertEqual(ver, "6.11-dirty")

    def test_bomtrace_version_not_found(self):
        """Line 358-359: bomtrace3 not in PATH."""
        with patch("shutil.which", return_value=None):
            ver = SpdxGenerator._bomtrace_version()
        self.assertEqual(ver, "unknown")

    def test_bomtrace_version_strings_fails(self):
        """Lines 372-374: strings command fails."""
        with patch("shutil.which", return_value="/usr/bin/bomtrace3"):
            with patch(
                "subprocess.check_output",
                side_effect=Exception("no strings"),
            ):
                ver = SpdxGenerator._bomtrace_version()
        self.assertEqual(ver, "unknown")

    def test_bomtrace_version_no_match(self):
        """Lines 366-374: strings output has no version."""
        with patch("shutil.which", return_value="/usr/bin/bomtrace3"):
            with patch(
                "subprocess.check_output",
                return_value="no version here\njust text\n",
            ):
                ver = SpdxGenerator._bomtrace_version()
        self.assertEqual(ver, "unknown")


# ============================================================
# SpdxValidator — schema validation success + error overflow
# ============================================================

class TestSpdxValidatorCoverage(unittest.TestCase):
    """Cover schema validation success and >10 error paths."""

    def test_schema_validation_pass(self):
        """Lines 790, 798-810: schema fetch succeeds,
        validation passes."""
        import json as json_mod
        doc = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "documentNamespace": "https://test",
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
            "packages": [],
            "relationships": [],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.spdx.json"
            path.write_text(json_mod.dumps(doc))

            # Mock schema fetch to return a permissive schema
            schema = {"type": "object"}
            mock_resp = MagicMock()
            mock_resp.read.return_value = (
                json_mod.dumps(schema).encode()
            )
            mock_resp.__enter__ = (
                lambda s: mock_resp
            )
            mock_resp.__exit__ = (
                lambda s, *a: None
            )

            v = SpdxValidator()
            with patch(
                "urllib.request.urlopen",
                return_value=mock_resp,
            ), patch(
                "builtins.print",
            ):
                result = v.validate(str(path))
            self.assertTrue(result["schema_ok"])

    def test_validation_many_schema_errors(self):
        """Lines 868-869, 881-882: >10 errors truncated."""
        import json as json_mod

        doc = {"bad": "doc"}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.spdx.json"
            path.write_text(json_mod.dumps(doc))

            # Schema that requires 15 properties
            required = [f"prop{i}" for i in range(15)]
            schema = {
                "type": "object",
                "required": required,
            }
            mock_resp = MagicMock()
            mock_resp.read.return_value = (
                json_mod.dumps(schema).encode()
            )
            mock_resp.__enter__ = (
                lambda s: mock_resp
            )
            mock_resp.__exit__ = (
                lambda s, *a: None
            )

            v = SpdxValidator()
            with patch(
                "urllib.request.urlopen",
                return_value=mock_resp,
            ), patch(
                "builtins.print",
            ):
                result = v.validate(str(path))
            self.assertFalse(result["schema_ok"])
            self.assertGreater(
                len(result["schema_errors"]), 10,
            )

    def test_validation_many_semantic_errors(self):
        """Line 882: >10 semantic errors truncated."""
        import json as json_mod

        doc = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "packages": [],
            "relationships": [],
        }

        def _inject_errors(path, result):
            result["semantic_ok"] = False
            result["semantic_errors"] = [
                f"error {i}" for i in range(15)
            ]
            return result

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.spdx.json"
            path.write_text(json_mod.dumps(doc))

            v = SpdxValidator()
            with patch.object(
                v, "_validate_semantic",
                side_effect=_inject_errors,
            ), patch(
                "urllib.request.urlopen",
                side_effect=Exception("no net"),
            ), patch(
                "builtins.print",
            ):
                result = v.validate(str(path))
            self.assertFalse(result["semantic_ok"])
            self.assertEqual(
                len(result["semantic_errors"]), 15,
            )


# ============================================================
# AdgSpdxStep coverage
# ============================================================

class TestAdgSpdxStep(unittest.TestCase):
    """Cover AdgSpdxStep.generate (lines 949-1023)."""

    def test_no_output_binaries(self):
        """Lines 963-968: no output_binaries returns []."""
        from analyze import AdgSpdxStep
        with tempfile.TemporaryDirectory() as td:
            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            result = AdgSpdxStep.generate(
                "test", {"language": "c-cpp"}, paths,
                run_ts="2026-02-12_1300",
            )
            self.assertEqual(result, [])

    def test_generate_calls_adg_generator(self):
        """Lines 949-1023: full generate path."""
        from analyze import AdgSpdxStep
        with tempfile.TemporaryDirectory() as td:
            # Create dirs
            bom_dir = (
                Path(td) / "omnibor" / "c-cpp"
                / "nmap" / "2026-02-12_1300"
                / "metadata" / "nmap"
            )
            bom_dir.mkdir(parents=True)
            spdx_dir = (
                Path(td) / "spdx" / "c-cpp"
                / "nmap" / "2026-02-12_1300"
            )
            spdx_dir.mkdir(parents=True)

            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "output_binaries": ["nmap"],
                "vendored_dirs": ["/liblua/"],
                "language": "c-cpp",
            }

            mock_gen = MagicMock()
            mock_gen.generate.side_effect = [
                str(spdx_dir / "nmap_analyzed.spdx.json"),
                str(spdx_dir / "nmap_build.spdx.json"),
            ]

            with patch(
                "spdx_from_adg.AdgSpdxGenerator",
                return_value=mock_gen,
            ):
                result = AdgSpdxStep.generate(
                    "nmap", repo_cfg, paths,
                    run_ts="2026-02-12_1300",
                )

            # 2 files per binary: analyzed + build
            self.assertEqual(len(result), 2)
            self.assertEqual(
                mock_gen.generate.call_count, 2
            )
            calls = mock_gen.generate.call_args_list
            self.assertTrue(
                calls[0].kwargs.get("static_only")
            )
            self.assertFalse(
                calls[1].kwargs.get("static_only")
            )
            self.assertEqual(
                calls[0].kwargs.get("binary_name"),
                "nmap",
            )

    def test_generate_with_shared_lib(self):
        """Lines 991-1002: direct_only=True when shared
        lib is in output_binaries."""
        from analyze import AdgSpdxStep
        with tempfile.TemporaryDirectory() as td:
            # Create per-binary metadata dir
            meta = (
                Path(td) / "omnibor" / "c-cpp"
                / "curl" / "2026-02-12_1300"
                / "metadata" / "curl"
            )
            meta.mkdir(parents=True)

            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "output_binaries": [
                    "src/.libs/curl",
                    "lib/.libs/libcurl.so",
                ],
                "language": "c-cpp",
            }

            mock_gen = MagicMock()
            mock_gen.generate.return_value = None

            with patch(
                "spdx_from_adg.AdgSpdxGenerator",
                return_value=mock_gen,
            ):
                result = AdgSpdxStep.generate(
                    "curl", repo_cfg, paths,
                    run_ts="2026-02-12_1300",
                )

            # curl binary should have direct_only=True
            # Each binary gets 2 calls (analyzed + build)
            calls = mock_gen.generate.call_args_list
            curl_calls = [
                c for c in calls
                if c.kwargs.get("binary_name") == "curl"
            ]
            self.assertEqual(len(curl_calls), 2)
            self.assertTrue(
                curl_calls[0].kwargs["direct_only"]
            )
            self.assertTrue(
                curl_calls[1].kwargs["direct_only"]
            )
            # result is empty because generate returned None
            self.assertEqual(result, [])


# ============================================================
# MetadataCollector coverage
# ============================================================

class TestMetadataCollector(unittest.TestCase):
    """Tests for MetadataCollector.collect()."""

    def test_no_treedb(self):
        """Returns False when treedb doesn't exist."""
        mc = MetadataCollector()
        with tempfile.TemporaryDirectory() as td:
            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            with patch("builtins.print"):
                result = mc.collect(
                    "nmap", {
                        "output_binaries": [],
                        "language": "c-cpp",
                    },
                    paths,
                    run_ts="2026-02-12_1300",
                )
            self.assertFalse(result)

    def test_collect_metadata_and_dynlibs(self):
        """Full collection: metadata + per-binary dynlibs."""
        with tempfile.TemporaryDirectory() as td:
            # Set up directory structure
            bom_dir = (
                Path(td) / "omnibor" / "c-cpp"
                / "nmap" / "2026-02-12_1300"
            )
            meta_dir = bom_dir / "metadata"
            bomsh = meta_dir / "bomsh"
            bomsh.mkdir(parents=True)

            # Create minimal treedb
            import json as json_mod
            treedb = {
                "abc": {
                    "file_path": "/usr/lib/libz.so",
                },
            }
            (bomsh / "bomsh_omnibor_treedb").write_text(
                json_mod.dumps(treedb)
            )

            # Create fake binary
            repo_dir = Path(td) / "repos" / "nmap"
            repo_dir.mkdir(parents=True)
            (repo_dir / "nmap").write_bytes(b"ELF")

            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "output_binaries": ["nmap"],
                "language": "c-cpp",
            }

            mc = MetadataCollector()

            # Mock the actual collection functions
            with patch(
                "collect_metadata.main",
            ) as mock_meta, patch(
                "collect_dynamic_libs.main",
            ) as mock_dyn, patch(
                "builtins.print",
            ):
                # Simulate collect_metadata writing file
                def write_meta(
                    treedb_p, repos, out,
                    repo_name=None,
                ):
                    Path(out).mkdir(
                        parents=True, exist_ok=True,
                    )
                    (
                        Path(out)
                        / "component_metadata.json"
                    ).write_text("{}")

                mock_meta.side_effect = write_meta
                result = mc.collect(
                    "nmap", repo_cfg, paths,
                    run_ts="2026-02-12_1300",
                )

            self.assertTrue(result)
            mock_meta.assert_called_once()
            mock_dyn.assert_called_once()
            # Verify project_bins is passed
            dyn_call = mock_dyn.call_args
            self.assertEqual(
                dyn_call.kwargs.get("project_bins"),
                ["nmap"],
            )

    def test_skips_existing_dynlibs(self):
        """Skips collection if dynamic_libs.json exists."""
        with tempfile.TemporaryDirectory() as td:
            bom_dir = (
                Path(td) / "omnibor" / "c-cpp"
                / "nmap" / "2026-02-12_1300"
            )
            meta_dir = bom_dir / "metadata"
            bomsh = meta_dir / "bomsh"
            bomsh.mkdir(parents=True)

            import json as json_mod
            treedb = {"a": {"file_path": "/usr/x"}}
            (bomsh / "bomsh_omnibor_treedb").write_text(
                json_mod.dumps(treedb)
            )

            # Pre-create metadata + dynlibs
            (meta_dir / "component_metadata.json"
             ).write_text("{}")
            bin_meta = meta_dir / "nmap"
            bin_meta.mkdir(parents=True)
            (bin_meta / "dynamic_libs.json"
             ).write_text("{}")

            repo_dir = Path(td) / "repos" / "nmap"
            repo_dir.mkdir(parents=True)
            (repo_dir / "nmap").write_bytes(b"ELF")

            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "output_binaries": ["nmap"],
                "language": "c-cpp",
            }

            mc = MetadataCollector()
            with patch(
                "builtins.print",
            ):
                result = mc.collect(
                    "nmap", repo_cfg, paths,
                    run_ts="2026-02-12_1300",
                )
            self.assertTrue(result)

    def test_binary_not_found(self):
        """Warns and continues if binary doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            bom_dir = (
                Path(td) / "omnibor" / "c-cpp"
                / "nmap" / "2026-02-12_1300"
            )
            meta_dir = bom_dir / "metadata"
            bomsh = meta_dir / "bomsh"
            bomsh.mkdir(parents=True)

            import json as json_mod
            treedb = {"a": {"file_path": "/usr/x"}}
            (bomsh / "bomsh_omnibor_treedb").write_text(
                json_mod.dumps(treedb)
            )
            (meta_dir / "component_metadata.json"
             ).write_text("{}")

            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }
            repo_cfg = {
                "output_binaries": ["nonexistent"],
                "language": "c-cpp",
            }

            mc = MetadataCollector()
            with patch("builtins.print"):
                result = mc.collect(
                    "nmap", repo_cfg, paths,
                    run_ts="2026-02-12_1300",
                )
            self.assertTrue(result)

    def test_collect_metadata_failure(self):
        """Returns False if collect_metadata raises."""
        with tempfile.TemporaryDirectory() as td:
            bom_dir = (
                Path(td) / "omnibor" / "c-cpp"
                / "nmap" / "2026-02-12_1300"
            )
            meta_dir = bom_dir / "metadata"
            bomsh = meta_dir / "bomsh"
            bomsh.mkdir(parents=True)

            import json as json_mod
            treedb = {"a": {"file_path": "/usr/x"}}
            (bomsh / "bomsh_omnibor_treedb").write_text(
                json_mod.dumps(treedb)
            )

            paths = {
                "output_dir": td,
                "repos_dir": str(Path(td) / "repos"),
            }

            mc = MetadataCollector()
            with patch(
                "collect_metadata.main",
                side_effect=Exception("dpkg fail"),
            ), patch("builtins.print"):
                result = mc.collect(
                    "nmap", {"language": "c-cpp"},
                    paths,
                    run_ts="2026-02-12_1300",
                )
            self.assertFalse(result)


# ============================================================
# main() — adg_files validation loop
# ============================================================

class TestMainAdgValidation(unittest.TestCase):
    """Cover line 1400: adg_files validation loop."""

    @patch("app.pipeline.runners.time.time")
    @patch("app.pipeline.runners.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_adg_files_validated(
        self, mock_cls, mock_time,
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = True
        p.spdx_gen.generate.return_value = (
            "/tmp/test.spdx.json"
        )
        p.adg_spdx.generate.return_value = [
            "/tmp/a.spdx.json",
            "/tmp/b.spdx.json",
        ]
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        # adg files should be validated
        calls = p.spdx_validator.validate.call_args_list
        validated = [c[0][0] for c in calls]
        self.assertIn("/tmp/test.spdx.json", validated)
        self.assertIn("/tmp/a.spdx.json", validated)
        self.assertIn("/tmp/b.spdx.json", validated)


if __name__ == "__main__":
    unittest.main()
