"""Tests for collect_dynamic_libs.py.

Focuses on the project_bins logic that identifies
project-built .so files even when a system package
provides the same soname.
"""
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from app.collect_dynamic_libs import main
from app.spdx.package_resolver import (
    PackageResolver,
    ResolvedPackage,
)


class FakeResolver(PackageResolver):
    """A test resolver that returns canned results."""

    def __init__(self, path_map=None):
        self._path_map = path_map or {}

    def resolve(self, file_path: str) -> Optional[ResolvedPackage]:
        return self._path_map.get(file_path)

    def purl_scheme(self) -> str:
        return "pkg:deb/ubuntu"


class TestProjectBuiltDetection(unittest.TestCase):
    """Test project_bins detection in main()."""

    def _mock_ldd(self, libs_map):
        """Build fake ldd output.

        libs_map: {soname: path} or {soname: None} for
        "not found".
        """
        lines = []
        for soname, path in libs_map.items():
            if path is None:
                lines.append(
                    f"\t{soname} => not found"
                )
            else:
                lines.append(
                    f"\t{soname} => {path} "
                    f"(0x00007f0000000000)"
                )
        return "\n".join(lines) + "\n"

    def _mock_readelf(self, needed):
        """Build fake readelf -d output."""
        lines = []
        for soname in needed:
            lines.append(
                f" 0x0000000000000001 (NEEDED)"
                f"             Shared library:"
                f" [{soname}]"
            )
        return "\n".join(lines) + "\n"

    @patch("app.collect_dynamic_libs.subprocess.check_output")
    @patch("app.collect_dynamic_libs.os.path.realpath")
    def test_project_bins_overrides_system_pkg(
        self, mock_realpath, mock_subproc,
    ):
        """When project_bins contains a .so, matching
        sonames should be moved to project_built_libs
        instead of dynamic_libs."""
        needed = ["libcurl.so.4", "libc.so.6"]
        ldd_out = self._mock_ldd({
            "libcurl.so.4": "/lib/x86_64-linux-gnu/"
                            "libcurl.so.4",
            "libc.so.6": "/lib/x86_64-linux-gnu/"
                         "libc.so.6",
        })
        readelf_out = self._mock_readelf(needed)
        mock_realpath.side_effect = lambda p: p

        def subproc_side_effect(cmd, **kwargs):
            if cmd[0] == "ldd":
                return ldd_out
            if cmd[0] == "readelf":
                return readelf_out
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        resolver = FakeResolver({
            "/lib/x86_64-linux-gnu/libcurl.so.4":
                ResolvedPackage(
                    name="libcurl4",
                    version="7.81.0-1ubuntu1.23",
                    source="curl",
                    maintainer="Ubuntu Dev",
                    homepage="https://curl.haxx.se",
                    architecture="amd64",
                ),
            "/lib/x86_64-linux-gnu/libc.so.6":
                ResolvedPackage(
                    name="libc6",
                    version="2.35-0ubuntu3",
                    source="glibc",
                    maintainer="Ubuntu Dev",
                    homepage="https://www.gnu.org/"
                             "software/libc/libc.html",
                    architecture="amd64",
                ),
        })

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/curl", td,
                    project_bins=[
                        "src/.libs/curl",
                        "lib/.libs/libcurl.so",
                    ],
                    resolver=resolver,
                )

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            # libcurl.so.4 should be in project_built
            self.assertIn(
                "libcurl.so.4",
                out["project_built_libs"],
            )
            pb = out["project_built_libs"][
                "libcurl.so.4"
            ]
            self.assertEqual(pb["name"], "libcurl")
            self.assertTrue(pb["project_built"])
            self.assertTrue(pb["direct"])

            # libcurl.so.4 should NOT be in dynamic_libs
            self.assertNotIn(
                "libcurl.so.4",
                out["dynamic_libs"],
            )

            # libc.so.6 should still be in dynamic_libs
            self.assertIn(
                "libc.so.6", out["dynamic_libs"],
            )

    @patch("app.collect_dynamic_libs.subprocess.check_output")
    @patch("app.collect_dynamic_libs.os.path.realpath")
    def test_no_project_bins_keeps_resolved(
        self, mock_realpath, mock_subproc,
    ):
        """Without project_bins, all libs stay in
        dynamic_libs (original behavior)."""
        needed = ["libcurl.so.4"]
        ldd_out = self._mock_ldd({
            "libcurl.so.4": "/lib/x86_64-linux-gnu/"
                            "libcurl.so.4",
        })
        readelf_out = self._mock_readelf(needed)
        mock_realpath.side_effect = lambda p: p

        def subproc_side_effect(cmd, **kwargs):
            if cmd[0] == "ldd":
                return ldd_out
            if cmd[0] == "readelf":
                return readelf_out
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        resolver = FakeResolver({
            "/lib/x86_64-linux-gnu/libcurl.so.4":
                ResolvedPackage(
                    name="libcurl4",
                    version="7.81.0",
                    source="curl",
                    maintainer="Dev",
                    homepage="https://curl.haxx.se",
                    architecture="amd64",
                ),
        })

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/curl", td,
                    resolver=resolver,
                )

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            self.assertIn(
                "libcurl.so.4", out["dynamic_libs"],
            )
            self.assertEqual(
                out["project_built_libs"], {},
            )

    @patch("app.collect_dynamic_libs.subprocess.check_output")
    @patch("app.collect_dynamic_libs.os.path.realpath")
    def test_not_found_still_project_built(
        self, mock_realpath, mock_subproc,
    ):
        """'not found' libs are still marked
        project_built (ffmpeg case)."""
        needed = [
            "libavcodec.so.62", "libc.so.6",
        ]
        ldd_out = self._mock_ldd({
            "libavcodec.so.62": None,
            "libc.so.6": "/lib/x86_64-linux-gnu/"
                         "libc.so.6",
        })
        readelf_out = self._mock_readelf(needed)
        mock_realpath.side_effect = lambda p: p

        def subproc_side_effect(cmd, **kwargs):
            if cmd[0] == "ldd":
                return ldd_out
            if cmd[0] == "readelf":
                return readelf_out
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        resolver = FakeResolver({
            "/lib/x86_64-linux-gnu/libc.so.6":
                ResolvedPackage(
                    name="libc6",
                    version="2.35",
                    source="glibc",
                    maintainer="Dev",
                    homepage="https://gnu.org",
                    architecture="amd64",
                ),
        })

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/ffmpeg", td,
                    project_bins=[
                        "ffmpeg",
                        "libavcodec/libavcodec.so",
                    ],
                    resolver=resolver,
                )

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            self.assertIn(
                "libavcodec.so.62",
                out["project_built_libs"],
            )
            pb = out["project_built_libs"][
                "libavcodec.so.62"
            ]
            self.assertEqual(pb["name"], "libavcodec")
            self.assertTrue(pb["project_built"])

    @patch("app.collect_dynamic_libs.subprocess.check_output")
    @patch("app.collect_dynamic_libs.os.path.realpath")
    def test_non_so_project_bins_ignored(
        self, mock_realpath, mock_subproc,
    ):
        """Non-.so project_bins (like 'curl') don't
        match any sonames."""
        needed = ["libc.so.6"]
        ldd_out = self._mock_ldd({
            "libc.so.6": "/lib/x86_64-linux-gnu/"
                         "libc.so.6",
        })
        readelf_out = self._mock_readelf(needed)
        mock_realpath.side_effect = lambda p: p

        def subproc_side_effect(cmd, **kwargs):
            if cmd[0] == "ldd":
                return ldd_out
            if cmd[0] == "readelf":
                return readelf_out
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        resolver = FakeResolver({
            "/lib/x86_64-linux-gnu/libc.so.6":
                ResolvedPackage(
                    name="libc6",
                    version="2.35",
                    source="glibc",
                    maintainer="Dev",
                    homepage="https://gnu.org",
                    architecture="amd64",
                ),
        })

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/redis-server", td,
                    project_bins=[
                        "src/redis-server",
                        "src/redis-cli",
                    ],
                    resolver=resolver,
                )

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            self.assertIn(
                "libc.so.6", out["dynamic_libs"],
            )
            self.assertEqual(
                out["project_built_libs"], {},
            )


if __name__ == "__main__":
    unittest.main()
