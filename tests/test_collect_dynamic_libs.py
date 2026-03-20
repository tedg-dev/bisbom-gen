"""Tests for collect_dynamic_libs.py.

Focuses on the project_bins logic that identifies
project-built .so files even when a system dpkg
package provides the same soname.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "app")
)

from collect_dynamic_libs import main  # noqa: E402


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

    def _mock_dpkg_s(self, path_to_pkg):
        """Return a side_effect for dpkg -S calls."""
        def side_effect(cmd, **kwargs):
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                path = cmd[2]
                if path in path_to_pkg:
                    return path_to_pkg[path]
                raise Exception("not found")
            raise Exception("unexpected cmd")
        return side_effect

    def _mock_dpkg_query(self, pkg_to_meta):
        """Return a side_effect for dpkg-query calls."""
        def side_effect(cmd, **kwargs):
            if cmd[0] == "dpkg-query":
                pkg = cmd[4]
                if pkg in pkg_to_meta:
                    return pkg_to_meta[pkg]
                raise Exception("not found")
            raise Exception("unexpected cmd")
        return side_effect

    @patch("collect_dynamic_libs.subprocess.check_output")
    @patch("collect_dynamic_libs.os.path.realpath")
    def test_project_bins_overrides_dpkg(
        self, mock_realpath, mock_subproc,
    ):
        """When project_bins contains a .so, matching
        sonames should be moved to project_built_libs
        instead of dynamic_libs."""
        # Simulate curl scenario: libcurl.so.4 resolves
        # to system dpkg libcurl4 7.81.0
        needed = ["libcurl.so.4", "libc.so.6"]
        ldd_out = self._mock_ldd({
            "libcurl.so.4": "/lib/x86_64-linux-gnu/"
                            "libcurl.so.4",
            "libc.so.6": "/lib/x86_64-linux-gnu/"
                         "libc.so.6",
        })
        readelf_out = self._mock_readelf(needed)

        # realpath returns itself for simplicity
        mock_realpath.side_effect = lambda p: p

        def subproc_side_effect(cmd, **kwargs):
            if cmd[0] == "ldd":
                return ldd_out
            if cmd[0] == "readelf":
                return readelf_out
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                path = cmd[2]
                if "libcurl" in path:
                    return "libcurl4: " + path
                if "libc" in path:
                    return "libc6: " + path
                raise Exception("not found")
            if cmd[0] == "dpkg-query":
                pkg = cmd[4]
                if pkg == "libcurl4":
                    return (
                        "libcurl4|7.81.0-1ubuntu1.23"
                        "|curl|Ubuntu Dev|"
                        "https://curl.haxx.se|amd64"
                    )
                if pkg == "libc6":
                    return (
                        "libc6|2.35-0ubuntu3|glibc"
                        "|Ubuntu Dev|"
                        "https://www.gnu.org/software"
                        "/libc/libc.html|amd64"
                    )
                raise Exception("not found")
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/curl", td,
                    project_bins=[
                        "src/.libs/curl",
                        "lib/.libs/libcurl.so",
                    ],
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

    @patch("collect_dynamic_libs.subprocess.check_output")
    @patch("collect_dynamic_libs.os.path.realpath")
    def test_no_project_bins_keeps_dpkg(
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
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return "libcurl4: " + cmd[2]
            if cmd[0] == "dpkg-query":
                return (
                    "libcurl4|7.81.0|curl|Dev|"
                    "https://curl.haxx.se|amd64"
                )
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main("/fake/curl", td)

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            # Without project_bins, libcurl stays in
            # dynamic_libs
            self.assertIn(
                "libcurl.so.4", out["dynamic_libs"],
            )
            self.assertEqual(
                out["project_built_libs"], {},
            )

    @patch("collect_dynamic_libs.subprocess.check_output")
    @patch("collect_dynamic_libs.os.path.realpath")
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
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                if "libc" in cmd[2]:
                    return "libc6: " + cmd[2]
                raise Exception("not found")
            if cmd[0] == "dpkg-query":
                return (
                    "libc6|2.35|glibc|Dev|"
                    "https://gnu.org|amd64"
                )
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/ffmpeg", td,
                    project_bins=[
                        "ffmpeg",
                        "libavcodec/libavcodec.so",
                    ],
                )

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            # not-found lib is project_built
            self.assertIn(
                "libavcodec.so.62",
                out["project_built_libs"],
            )
            pb = out["project_built_libs"][
                "libavcodec.so.62"
            ]
            self.assertEqual(pb["name"], "libavcodec")
            self.assertTrue(pb["project_built"])

    @patch("collect_dynamic_libs.subprocess.check_output")
    @patch("collect_dynamic_libs.os.path.realpath")
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
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return "libc6: " + cmd[2]
            if cmd[0] == "dpkg-query":
                return (
                    "libc6|2.35|glibc|Dev|"
                    "https://gnu.org|amd64"
                )
            raise Exception(f"unexpected: {cmd}")

        mock_subproc.side_effect = subproc_side_effect

        with tempfile.TemporaryDirectory() as td:
            with patch("builtins.print"):
                main(
                    "/fake/redis-server", td,
                    project_bins=[
                        "src/redis-server",
                        "src/redis-cli",
                    ],
                )

            out = json.loads(
                (Path(td) / "dynamic_libs.json")
                .read_text()
            )

            # No .so in project_bins, so no overrides
            self.assertIn(
                "libc.so.6", out["dynamic_libs"],
            )
            self.assertEqual(
                out["project_built_libs"], {},
            )


if __name__ == "__main__":
    unittest.main()
