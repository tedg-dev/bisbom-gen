"""Tests for app.version_detection module.

Covers all 12 strategies plus patterns/helpers,
with emphasis on real-world version numbering
conventions across C/C++, JavaScript, Python,
and multi-part version schemes.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from app.version_detection import (
    VendoredVersionDetector,
)
from app.version_detection.patterns import (
    name_prefixes,
)
from app.version_detection.strategies import (
    parse_version_file,
    parse_kv_version_file,
    parse_package_json,
    parse_version_json,
    parse_pyproject_toml,
    parse_cargo_toml,
    parse_pom_xml,
    parse_configure_ac,
    parse_cmakelists,
    parse_meson_build,
    parse_pc_in,
    parse_define_version_str,
    parse_define_parts,
    parse_define_any_version,
    parse_header_comment,
    parse_makefile,
)
from app.collect_metadata import (
    _version_from_tag,
    _detect_repo_version,
)


# ── Strategy 1: VERSION text files ──────────────


class TestParseVersionFile(unittest.TestCase):
    """Strategy 1: Plain text VERSION files."""

    def test_simple_semver(self):
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION"
            vf.write_text("1.3.1\n")
            self.assertEqual(
                parse_version_file(vf), "1.3.1"
            )

    def test_version_with_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION"
            vf.write_text("5.3.0-0-g0\n")
            self.assertEqual(
                parse_version_file(vf), "5.3.0"
            )

    def test_version_with_v_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION"
            vf.write_text("v2.0.0-rc1\n")
            self.assertEqual(
                parse_version_file(vf), "2.0.0"
            )

    def test_two_part(self):
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "RELEASE"
            vf.write_text("8.0\n")
            self.assertEqual(
                parse_version_file(vf), "8.0"
            )

    def test_unreadable(self):
        self.assertIsNone(
            parse_version_file(
                Path("/nonexistent/VERSION")
            )
        )


# ── Strategy 2: Key-value version files ─────────


class TestParseKvVersionFile(unittest.TestCase):
    """Strategy 2: OpenSSL-style VERSION.dat."""

    def test_openssl_version_dat(self):
        """OpenSSL VERSION.dat format."""
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION.dat"
            vf.write_text(
                "MAJOR=3\n"
                "MINOR=5\n"
                "PATCH=5\n"
                'PRE_RELEASE_TAG=\n'
                'BUILD_METADATA=\n'
                'RELEASE_DATE="27 Jan 2026"\n'
                "SHLIB_VERSION=3\n"
            )
            self.assertEqual(
                parse_kv_version_file(vf), "3.5.5"
            )

    def test_major_minor_only(self):
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION.dat"
            vf.write_text("MAJOR=2\nMINOR=0\n")
            self.assertEqual(
                parse_kv_version_file(vf), "2.0"
            )

    def test_colon_separated(self):
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "version.properties"
            vf.write_text(
                "version.major: 1\n"
                "version.minor: 4\n"
                "version.patch: 2\n"
            )
            # Should match via dotted prefix
            self.assertIsNotNone(
                parse_kv_version_file(vf)
            )

    def test_unreadable(self):
        self.assertIsNone(
            parse_kv_version_file(
                Path("/nonexistent/VERSION.dat")
            )
        )

    def test_no_major_minor(self):
        """Return None if no MAJOR/MINOR found."""
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION.dat"
            vf.write_text("SOMETHING_ELSE=3\n")
            self.assertIsNone(
                parse_kv_version_file(vf)
            )


# ── Strategy 3: Structured data files ───────────


class TestParsePackageJson(unittest.TestCase):
    """Strategy 3a: package.json (JavaScript)."""

    def test_nodejs_package_json(self):
        with tempfile.TemporaryDirectory() as td:
            pj = Path(td) / "package.json"
            pj.write_text(json.dumps({
                "name": "node",
                "version": "22.14.0",
            }))
            self.assertEqual(
                parse_package_json(pj), "22.14.0"
            )

    def test_scoped_package(self):
        with tempfile.TemporaryDirectory() as td:
            pj = Path(td) / "package.json"
            pj.write_text(json.dumps({
                "name": "@babel/core",
                "version": "7.24.5",
            }))
            self.assertEqual(
                parse_package_json(pj), "7.24.5"
            )

    def test_no_version_field(self):
        with tempfile.TemporaryDirectory() as td:
            pj = Path(td) / "package.json"
            pj.write_text(json.dumps({
                "name": "no-ver",
            }))
            self.assertIsNone(parse_package_json(pj))

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            pj = Path(td) / "package.json"
            pj.write_text("not json {{{")
            self.assertIsNone(parse_package_json(pj))

    def test_unreadable(self):
        self.assertIsNone(
            parse_package_json(
                Path("/nonexistent/package.json")
            )
        )


class TestParseVersionJson(unittest.TestCase):
    """Strategy 3b: version.json."""

    def test_simple_object(self):
        with tempfile.TemporaryDirectory() as td:
            vj = Path(td) / "version.json"
            vj.write_text(json.dumps({
                "version": "1.2.3",
            }))
            self.assertEqual(
                parse_version_json(vj), "1.2.3"
            )

    def test_array_format(self):
        """Node.js-style array of versions."""
        with tempfile.TemporaryDirectory() as td:
            vj = Path(td) / "version.json"
            vj.write_text(json.dumps([
                {"version": "22.14.0"},
                {"version": "22.13.1"},
            ]))
            self.assertEqual(
                parse_version_json(vj), "22.14.0"
            )


class TestParsePyprojectToml(unittest.TestCase):
    """Strategy 3c: pyproject.toml (Python)."""

    def test_project_section(self):
        with tempfile.TemporaryDirectory() as td:
            pt = Path(td) / "pyproject.toml"
            pt.write_text(
                '[project]\n'
                'name = "mylib"\n'
                'version = "1.5.0"\n'
            )
            self.assertEqual(
                parse_pyproject_toml(pt), "1.5.0"
            )

    def test_poetry_section(self):
        with tempfile.TemporaryDirectory() as td:
            pt = Path(td) / "pyproject.toml"
            pt.write_text(
                '[tool.poetry]\n'
                'name = "mylib"\n'
                'version = "2.3.1"\n'
            )
            self.assertEqual(
                parse_pyproject_toml(pt), "2.3.1"
            )


# ── Strategy 4-7: Build system files ────────────


class TestParseBuildSystems(unittest.TestCase):
    """Strategies 4-7: configure.ac, CMake, meson,
    .pc.in."""

    def test_configure_ac(self):
        with tempfile.TemporaryDirectory() as td:
            ac = Path(td) / "configure.ac"
            ac.write_text(
                "AC_INIT([libdnet],[1.18.0])\n"
            )
            self.assertEqual(
                parse_configure_ac(ac), "1.18.0"
            )

    def test_configure_ac_spaced(self):
        with tempfile.TemporaryDirectory() as td:
            ac = Path(td) / "configure.ac"
            ac.write_text(
                "AC_INIT(libfoo, 2.3.4, bug@foo)\n"
            )
            self.assertEqual(
                parse_configure_ac(ac), "2.3.4"
            )

    def test_cmakelists(self):
        with tempfile.TemporaryDirectory() as td:
            cm = Path(td) / "CMakeLists.txt"
            cm.write_text(
                "cmake_minimum_required(VERSION 3.1)\n"
                "project(libssh2 C VERSION 1.11.1)\n"
            )
            self.assertEqual(
                parse_cmakelists(cm), "1.11.1"
            )

    def test_meson_build(self):
        with tempfile.TemporaryDirectory() as td:
            mb = Path(td) / "meson.build"
            mb.write_text(
                "project('mylib', 'c',\n"
                "  version: '2.4.1',\n"
                ")\n"
            )
            self.assertEqual(
                parse_meson_build(mb), "2.4.1"
            )

    def test_pc_in(self):
        with tempfile.TemporaryDirectory() as td:
            pc = Path(td) / "hiredis.pc.in"
            pc.write_text(
                "prefix=@PREFIX@\n"
                "Name: hiredis\n"
                "Version: 1.2.0\n"
            )
            self.assertEqual(
                parse_pc_in(pc), "1.2.0"
            )

    def test_all_unreadable(self):
        bad = Path("/nonexistent/file")
        self.assertIsNone(parse_configure_ac(bad))
        self.assertIsNone(parse_cmakelists(bad))
        self.assertIsNone(parse_meson_build(bad))
        self.assertIsNone(parse_pc_in(bad))


# ── Strategy 8: #define PREFIX_VERSION "str" ─────


class TestParseDefineVersionStr(unittest.TestCase):
    """Strategy 8: #define PREFIX_VERSION string."""

    def test_curl_version(self):
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "curlver.h"
            h.write_text(
                '#define LIBCURL_VERSION "8.5.0"\n'
            )
            self.assertEqual(
                parse_define_version_str(
                    h, ["LIBCURL", "CURL"]
                ),
                "8.5.0",
            )

    def test_lua_release(self):
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lua.h"
            h.write_text(
                '#define LUA_VERSION "Lua 5.1"\n'
                '#define LUA_RELEASE "Lua 5.1.5"\n'
            )
            self.assertEqual(
                parse_define_version_str(
                    h, ["LUA"]
                ),
                "5.1.5",
            )

    def test_unreadable(self):
        self.assertIsNone(
            parse_define_version_str(
                "/nonexistent/lib.h", ["LIB"]
            )
        )


# ── Strategy 9: Split #define MAJOR/MINOR/PATCH ──


class TestParseDefineParts(unittest.TestCase):
    """Strategy 9: Split macro version detection.

    This is the most complex strategy — needs to
    handle diverse naming conventions across major
    open-source projects.
    """

    def test_standard_major_minor_patch(self):
        """Standard _MAJOR/_MINOR/_PATCH (libuv)."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "uv_version.h"
            h.write_text(
                "#define UV_VERSION_MAJOR 1\n"
                "#define UV_VERSION_MINOR 51\n"
                "#define UV_VERSION_PATCH 0\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["UV"]
                ),
                "1.51.0",
            )

    def test_openssl_version_major_minor_patch(self):
        """OpenSSL: OPENSSL_VERSION_MAJOR/MINOR/PATCH."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "opensslv.h"
            h.write_text(
                "# define OPENSSL_VERSION_MAJOR  3\n"
                "# define OPENSSL_VERSION_MINOR  5\n"
                "# define OPENSSL_VERSION_PATCH  5\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["OPENSSL"]
                ),
                "3.5.5",
            )

    def test_v8_four_part_version(self):
        """V8: MAJOR_VERSION, MINOR_VERSION,
        BUILD_NUMBER, PATCH_LEVEL → 4-part."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "v8-version.h"
            h.write_text(
                "#define V8_MAJOR_VERSION 12\n"
                "#define V8_MINOR_VERSION 4\n"
                "#define V8_BUILD_NUMBER 254\n"
                "#define V8_PATCH_LEVEL 21\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["V8"]
                ),
                "12.4.254.21",
            )

    def test_node_major_minor_patch_version(self):
        """Node.js: NODE_MAJOR_VERSION, NODE_MINOR_VERSION,
        NODE_PATCH_VERSION."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "node_version.h"
            h.write_text(
                "#define NODE_MAJOR_VERSION 22\n"
                "#define NODE_MINOR_VERSION 14\n"
                "#define NODE_PATCH_VERSION 0\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["NODE"]
                ),
                "22.14.0",
            )

    def test_lua_quoted_release(self):
        """Lua: quoted major/minor/release strings."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lua.h"
            h.write_text(
                '#define LUA_VERSION_MAJOR\t"5"\n'
                '#define LUA_VERSION_MINOR\t"4"\n'
                '#define LUA_VERSION_RELEASE\t"8"\n'
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["LUA"]
                ),
                "5.4.8",
            )

    def test_pcre2_no_patch(self):
        """PCRE2: only MAJOR/MINOR, no PATCH."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "pcre2.h"
            h.write_text(
                "#define PCRE2_MAJOR 10\n"
                "#define PCRE2_MINOR 42\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["PCRE2"]
                ),
                "10.42",
            )

    def test_glib_micro(self):
        """GLib: uses _MICRO as patch alias."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "glib.h"
            h.write_text(
                "#define GLIB_MAJOR 2\n"
                "#define GLIB_MINOR 78\n"
                "#define GLIB_MICRO 3\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["GLIB"]
                ),
                "2.78.3",
            )

    def test_freetype_subminor(self):
        """FreeType: uses _SUBMINOR as patch alias."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "freetype.h"
            h.write_text(
                "#define FREETYPE_MAJOR 2\n"
                "#define FREETYPE_MINOR 13\n"
                "#define FREETYPE_SUBMINOR 2\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["FREETYPE"]
                ),
                "2.13.2",
            )

    def test_ruby_teeny(self):
        """Ruby: uses _TEENY as patch alias."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "ruby_version.h"
            h.write_text(
                "#define RUBY_VERSION_MAJOR 3\n"
                "#define RUBY_VERSION_MINOR 3\n"
                "#define RUBY_VERSION_TEENY 0\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["RUBY"]
                ),
                "3.3.0",
            )

    def test_hiredis_bare_major_minor_patch(self):
        """Hiredis: PREFIX_MAJOR/MINOR/PATCH (no
        _VERSION_ infix)."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "hiredis.h"
            h.write_text(
                "#define HIREDIS_MAJOR 1\n"
                "#define HIREDIS_MINOR 2\n"
                "#define HIREDIS_PATCH 0\n"
            )
            self.assertEqual(
                parse_define_parts(
                    h, ["HIREDIS"]
                ),
                "1.2.0",
            )

    def test_unreadable(self):
        self.assertIsNone(
            parse_define_parts(
                "/nonexistent/lib.h", ["LIB"]
            )
        )


# ── Strategy 10-12: Fallbacks ────────────────────


class TestFallbackStrategies(unittest.TestCase):
    """Strategies 10-12: broad define, header
    comment, Makefile."""

    def test_broad_define_redis(self):
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "version.h"
            h.write_text(
                '#define REDIS_VERSION "7.2.4"\n'
            )
            self.assertEqual(
                parse_define_any_version(h),
                "7.2.4",
            )

    def test_header_comment(self):
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lib.h"
            h.write_text(
                "/* lib.h -- VERSION 1.0 */\n"
            )
            self.assertEqual(
                parse_header_comment(h), "1.0"
            )

    def test_header_comment_past_line_20(self):
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "big.h"
            lines = ["/* padding */\n"] * 21
            lines.append("/* VERSION 9.9 */\n")
            h.write_text("".join(lines))
            self.assertIsNone(
                parse_header_comment(h)
            )

    def test_makefile_version(self):
        with tempfile.TemporaryDirectory() as td:
            mf = Path(td) / "Makefile"
            mf.write_text(
                "CC = gcc\n"
                "VERSION = 3.7.2\n"
            )
            self.assertEqual(
                parse_makefile(mf), "3.7.2"
            )


# ── name_prefixes helper ────────────────────────


class TestNamePrefixes(unittest.TestCase):
    """Test prefix generation for macro matching."""

    def test_simple(self):
        pfx = name_prefixes("openssl")
        self.assertEqual(pfx, ["OPENSSL"])

    def test_lib_prefix(self):
        pfx = name_prefixes("liblua")
        self.assertIn("LIBLUA", pfx)
        self.assertIn("LUA", pfx)

    def test_stripped_suffix(self):
        pfx = name_prefixes("libdnet-stripped")
        self.assertIn("LIBDNET_STRIPPED", pfx)
        self.assertIn("DNET_STRIPPED", pfx)
        self.assertIn("LIBDNET", pfx)
        self.assertIn("DNET", pfx)

    def test_small_suffix(self):
        pfx = name_prefixes("icu-small")
        self.assertIn("ICU_SMALL", pfx)
        self.assertIn("ICU", pfx)

    def test_v8(self):
        pfx = name_prefixes("v8")
        self.assertEqual(pfx, ["V8"])

    def test_hyphen_to_underscore(self):
        pfx = name_prefixes("icu-small")
        self.assertTrue(
            all("_" in p or len(p) <= 3
                for p in pfx)
        )


# ── Full detector integration ───────────────────


class TestDetectorIntegration(unittest.TestCase):
    """End-to-end tests through VendoredVersionDetector
    simulating real vendored directory layouts."""

    def test_openssl_version_dat(self):
        """OpenSSL: VERSION.dat in library root."""
        with tempfile.TemporaryDirectory() as td:
            ssl_dir = (
                Path(td) / "deps" / "openssl"
                / "openssl"
            )
            src = ssl_dir / "crypto"
            src.mkdir(parents=True)
            (ssl_dir / "VERSION.dat").write_text(
                "MAJOR=3\nMINOR=5\nPATCH=5\n"
                'PRE_RELEASE_TAG=\n'
            )
            (src / "evp.c").write_text("")
            det = VendoredVersionDetector()
            ver = det.detect("openssl", [
                str(src / "evp.c"),
            ])
            self.assertEqual(ver, "3.5.5")

    def test_v8_four_part(self):
        """V8: 4-part version from v8-version.h."""
        with tempfile.TemporaryDirectory() as td:
            inc = (
                Path(td) / "deps" / "v8" / "include"
            )
            inc.mkdir(parents=True)
            (inc / "v8-version.h").write_text(
                "#define V8_MAJOR_VERSION 12\n"
                "#define V8_MINOR_VERSION 4\n"
                "#define V8_BUILD_NUMBER 254\n"
                "#define V8_PATCH_LEVEL 21\n"
            )
            det = VendoredVersionDetector()
            ver = det.detect("v8", [
                str(inc / "v8-version.h"),
            ])
            self.assertEqual(ver, "12.4.254.21")

    def test_node_version_header(self):
        """Node.js: NODE_MAJOR/MINOR/PATCH_VERSION."""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "node_version.h").write_text(
                "#define NODE_MAJOR_VERSION 22\n"
                "#define NODE_MINOR_VERSION 14\n"
                "#define NODE_PATCH_VERSION 0\n"
            )
            det = VendoredVersionDetector()
            ver = det.detect("node", [
                str(src / "node_version.h"),
            ])
            self.assertEqual(ver, "22.14.0")

    def test_libuv_version_header(self):
        """libuv: UV_VERSION_MAJOR/MINOR/PATCH."""
        with tempfile.TemporaryDirectory() as td:
            inc = Path(td) / "include" / "uv"
            inc.mkdir(parents=True)
            (inc / "version.h").write_text(
                "#define UV_VERSION_MAJOR 1\n"
                "#define UV_VERSION_MINOR 51\n"
                "#define UV_VERSION_PATCH 0\n"
            )
            det = VendoredVersionDetector()
            ver = det.detect("uv", [
                str(inc / "version.h"),
            ])
            self.assertEqual(ver, "1.51.0")

    def test_package_json_js_project(self):
        """JavaScript: version from package.json."""
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "package.json"
            pkg.write_text(json.dumps({
                "name": "undici",
                "version": "6.21.1",
            }))
            src = Path(td) / "lib"
            src.mkdir()
            (src / "index.js").write_text("")
            det = VendoredVersionDetector()
            # Pass a file so the detector finds
            # the parent directory
            ver = det.detect("undici", [
                str(src / "index.js"),
            ])
            # package.json is in parent of lib/
            self.assertEqual(ver, "6.21.1")

    def test_no_version_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "empty.h"
            h.write_text("/* nothing */\n")
            det = VendoredVersionDetector()
            self.assertIsNone(
                det.detect("unknown", [str(h)])
            )

    def test_cargo_toml_rust_project(self):
        """Rust: version from Cargo.toml."""
        with tempfile.TemporaryDirectory() as td:
            ct = Path(td) / "Cargo.toml"
            ct.write_text(
                '[package]\n'
                'name = "oxipng"\n'
                'version = "10.1.0"\n'
            )
            src = Path(td) / "src"
            src.mkdir()
            (src / "main.rs").write_text("")
            det = VendoredVersionDetector()
            ver = det.detect("oxipng", [
                str(src / "main.rs"),
            ])
            self.assertEqual(ver, "10.1.0")

    def test_pom_xml_java_project(self):
        """Java: version from pom.xml."""
        with tempfile.TemporaryDirectory() as td:
            pom = Path(td) / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <parent>\n'
                '    <version>2.0.0</version>\n'
                '  </parent>\n'
                '  <artifactId>mylib</artifactId>\n'
                '  <version>1.8.3</version>\n'
                '</project>\n'
            )
            src = Path(td) / "src"
            src.mkdir()
            (src / "Main.java").write_text("")
            det = VendoredVersionDetector()
            ver = det.detect("mylib", [
                str(src / "Main.java"),
            ])
            self.assertEqual(ver, "1.8.3")


# ── Strategy 3d: Cargo.toml ────────────────────


class TestParseCargoToml(unittest.TestCase):
    """Strategy 3d: Cargo.toml (Rust)."""

    def test_standard_cargo_toml(self):
        with tempfile.TemporaryDirectory() as td:
            ct = Path(td) / "Cargo.toml"
            ct.write_text(
                '[package]\n'
                'name = "oxipng"\n'
                'version = "10.1.0"\n'
                'edition = "2021"\n'
            )
            self.assertEqual(
                parse_cargo_toml(ct), "10.1.0"
            )

    def test_workspace_cargo_toml(self):
        """Workspace Cargo.toml with
        workspace.package.version."""
        with tempfile.TemporaryDirectory() as td:
            ct = Path(td) / "Cargo.toml"
            ct.write_text(
                '[workspace.package]\n'
                'version = "0.25.9"\n'
            )
            self.assertEqual(
                parse_cargo_toml(ct), "0.25.9"
            )

    def test_no_version(self):
        with tempfile.TemporaryDirectory() as td:
            ct = Path(td) / "Cargo.toml"
            ct.write_text(
                '[package]\n'
                'name = "mylib"\n'
            )
            self.assertIsNone(parse_cargo_toml(ct))

    def test_unreadable(self):
        self.assertIsNone(
            parse_cargo_toml(
                Path("/nonexistent/Cargo.toml")
            )
        )


# ── Strategy 3e: pom.xml ───────────────────────


class TestParsePomXml(unittest.TestCase):
    """Strategy 3e: pom.xml (Java/Maven)."""

    def test_simple_pom(self):
        with tempfile.TemporaryDirectory() as td:
            pom = Path(td) / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>1.8.3</version>\n'
                '</project>\n'
            )
            self.assertEqual(
                parse_pom_xml(pom), "1.8.3"
            )

    def test_pom_skips_parent_version(self):
        """Should use project version, not parent."""
        with tempfile.TemporaryDirectory() as td:
            pom = Path(td) / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <parent>\n'
                '    <version>2.0.0</version>\n'
                '  </parent>\n'
                '  <version>1.8.3</version>\n'
                '</project>\n'
            )
            self.assertEqual(
                parse_pom_xml(pom), "1.8.3"
            )

    def test_snapshot_version(self):
        """SNAPSHOT versions: extract numeric part."""
        with tempfile.TemporaryDirectory() as td:
            pom = Path(td) / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>3.0.0-SNAPSHOT</version>\n'
                '</project>\n'
            )
            self.assertEqual(
                parse_pom_xml(pom), "3.0.0"
            )

    def test_no_version(self):
        with tempfile.TemporaryDirectory() as td:
            pom = Path(td) / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <artifactId>mylib</artifactId>\n'
                '</project>\n'
            )
            self.assertIsNone(parse_pom_xml(pom))

    def test_unreadable(self):
        self.assertIsNone(
            parse_pom_xml(
                Path("/nonexistent/pom.xml")
            )
        )


# ── Git tag version extraction ─────────────────


class TestVersionFromTag(unittest.TestCase):
    """Tests for _version_from_tag()."""

    def test_v_prefix(self):
        self.assertEqual(
            _version_from_tag("v0.25.9"), "0.25.9"
        )

    def test_no_prefix(self):
        self.assertEqual(
            _version_from_tag("7.2.4"), "7.2.4"
        )

    def test_release_prefix(self):
        self.assertEqual(
            _version_from_tag("release-1.2.3"),
            "1.2.3",
        )

    def test_two_part(self):
        self.assertEqual(
            _version_from_tag("v8.0"), "8.0"
        )

    def test_four_part(self):
        self.assertEqual(
            _version_from_tag("v1.2.3.4"), "1.2.3.4"
        )

    def test_main_branch(self):
        self.assertIsNone(
            _version_from_tag("main")
        )

    def test_master_branch(self):
        self.assertIsNone(
            _version_from_tag("master")
        )

    def test_develop_branch(self):
        self.assertIsNone(
            _version_from_tag("develop")
        )

    def test_none_input(self):
        self.assertIsNone(
            _version_from_tag(None)
        )

    def test_empty_string(self):
        self.assertIsNone(
            _version_from_tag("")
        )


class TestDetectRepoVersionWithTag(unittest.TestCase):
    """Tests for _detect_repo_version with
    config_branch."""

    def test_config_branch_takes_priority(self):
        """Config tag is used even when files exist."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "myrepo"
            repo.mkdir()
            vf = repo / "VERSION"
            vf.write_text("1.0.0\n")
            ver = _detect_repo_version(
                "myrepo", td,
                config_branch="v2.5.0",
            )
            self.assertEqual(ver, "2.5.0")

    def test_falls_back_to_file(self):
        """When config_branch has no version,
        fall back to file detection."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "myrepo"
            repo.mkdir()
            vf = repo / "VERSION"
            vf.write_text("1.0.0\n")
            ver = _detect_repo_version(
                "myrepo", td,
                config_branch="main",
            )
            self.assertEqual(ver, "1.0.0")

    def test_no_branch_no_files(self):
        """Returns None when no version source."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "myrepo"
            repo.mkdir()
            (repo / "README.md").write_text("hi")
            ver = _detect_repo_version(
                "myrepo", td,
            )
            self.assertIsNone(ver)

    def test_cargo_toml_fallback(self):
        """Rust: Cargo.toml version via fallback."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "oxipng"
            repo.mkdir()
            ct = repo / "Cargo.toml"
            ct.write_text(
                '[package]\n'
                'name = "oxipng"\n'
                'version = "10.1.0"\n'
            )
            ver = _detect_repo_version(
                "oxipng", td,
            )
            self.assertEqual(ver, "10.1.0")

    def test_pom_xml_fallback(self):
        """Java: pom.xml version via fallback."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "mylib"
            repo.mkdir()
            pom = repo / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>1.8.3</version>\n'
                '</project>\n'
            )
            ver = _detect_repo_version(
                "mylib", td,
            )
            self.assertEqual(ver, "1.8.3")


if __name__ == "__main__":
    unittest.main()
