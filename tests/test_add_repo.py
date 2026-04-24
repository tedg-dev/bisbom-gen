#!/usr/bin/env python3
"""
Tests for app/add_repo.py — class-based repo discovery.

Uses unittest.mock to avoid real GitHub API calls.
"""

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add app/ to path so we can import add_repo
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import add_repo
import yaml
from add_repo import (
    GitHubClient, BuildSystemDetector,
    DependencyAnalyzer, BinaryDetector,
    BuildStepGenerator, ConfigGenerator,
    RepoDiscovery,
)


# ============================================================
# GitHubClient
# ============================================================

class TestParseGithubUrl(unittest.TestCase):
    """Tests for GitHubClient.parse_github_url()."""

    def test_https_url(self):
        result = GitHubClient.parse_github_url(
            "https://github.com/curl/curl"
        )
        self.assertEqual(result, "curl/curl")

    def test_https_url_with_git_suffix(self):
        result = GitHubClient.parse_github_url(
            "https://github.com/curl/curl.git"
        )
        self.assertEqual(result, "curl/curl")

    def test_ssh_url(self):
        result = GitHubClient.parse_github_url(
            "git@github.com:curl/curl.git"
        )
        self.assertEqual(result, "curl/curl")

    def test_plain_name_returns_none(self):
        self.assertIsNone(
            GitHubClient.parse_github_url("curl")
        )

    def test_owner_repo_returns_none(self):
        self.assertIsNone(
            GitHubClient.parse_github_url(
                "curl/curl"
            )
        )


class TestGitHubClientApi(unittest.TestCase):
    """Tests for GitHubClient.api()."""

    @patch("add_repo.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"full_name": "curl/curl"}',
        )
        client = GitHubClient()
        result = client.api("repos/curl/curl")
        self.assertEqual(
            result["full_name"], "curl/curl"
        )

    @patch("add_repo.subprocess.run")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error",
        )
        client = GitHubClient()
        self.assertIsNone(
            client.api("repos/bad/repo")
        )

    @patch("add_repo.subprocess.run")
    def test_invalid_json(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json",
        )
        client = GitHubClient()
        self.assertIsNone(
            client.api("repos/curl/curl")
        )


class TestGitHubClientSearchRepos(unittest.TestCase):
    """Tests for GitHubClient.search_repos()."""

    @patch("add_repo.subprocess.run")
    def test_exact_name_match(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "someone/curl-wrapper",
                    "language": "C",
                    "stargazersCount": 100,
                },
                {
                    "fullName": "curl/curl",
                    "language": "C",
                    "stargazersCount": 40000,
                },
            ]),
        )
        client = GitHubClient()
        result = client.search_repos("curl")
        self.assertEqual(
            result["fullName"], "curl/curl"
        )

    @patch("add_repo.subprocess.run")
    def test_c_repos_preferred(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "js/mylib",
                    "language": "JavaScript",
                    "stargazersCount": 50000,
                },
                {
                    "fullName": "c/mylib",
                    "language": "C",
                    "stargazersCount": 1000,
                },
            ]),
        )
        client = GitHubClient()
        result = client.search_repos("mylib")
        self.assertEqual(
            result["fullName"], "c/mylib"
        )

    @patch("add_repo.subprocess.run")
    def test_no_results(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]",
        )
        client = GitHubClient()
        self.assertIsNone(
            client.search_repos("nonexistent")
        )

    @patch("add_repo.subprocess.run")
    def test_gh_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="",
            stderr="auth required",
        )
        client = GitHubClient()
        self.assertIsNone(
            client.search_repos("curl")
        )

    @patch("add_repo.subprocess.run")
    def test_invalid_json(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json",
        )
        client = GitHubClient()
        self.assertIsNone(
            client.search_repos("curl")
        )

    @patch("add_repo.subprocess.run")
    def test_falls_back_to_highest_stars(
        self, mock_run
    ):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "a/low",
                    "language": "C",
                    "stargazersCount": 10,
                },
                {
                    "fullName": "b/high",
                    "language": "C",
                    "stargazersCount": 50000,
                },
            ]),
        )
        client = GitHubClient()
        result = client.search_repos("nomatch")
        self.assertEqual(
            result["fullName"], "b/high"
        )

    @patch("add_repo.subprocess.run")
    def test_non_c_repos_fallback(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "js/lib",
                    "language": "JavaScript",
                    "stargazersCount": 100,
                },
            ]),
        )
        client = GitHubClient()
        result = client.search_repos("lib")
        self.assertEqual(
            result["fullName"], "js/lib"
        )


class TestGitHubClientNormalize(unittest.TestCase):
    """Tests for GitHubClient._normalize()."""

    def test_converts_api_response(self):
        data = {
            "full_name": "curl/curl",
            "description": "transfer lib",
            "html_url": (
                "https://github.com/curl/curl"
            ),
            "stargazers_count": 40000,
            "default_branch": "master",
            "language": "C",
        }
        result = GitHubClient._normalize(data)
        self.assertEqual(
            result["fullName"], "curl/curl"
        )
        self.assertEqual(
            result["defaultBranch"], "master"
        )
        self.assertEqual(
            result["stargazersCount"], 40000
        )

    def test_handles_missing_fields(self):
        data = {
            "full_name": "test/repo",
            "html_url": (
                "https://github.com/test/repo"
            ),
        }
        result = GitHubClient._normalize(data)
        self.assertEqual(result["description"], "")
        self.assertEqual(result["language"], "")
        self.assertEqual(
            result["stargazersCount"], 0
        )
        self.assertEqual(
            result["defaultBranch"], "main"
        )


class TestGitHubClientGetRepoInfo(unittest.TestCase):
    """Tests for GitHubClient.get_repo_info()."""

    def test_full_url(self):
        client = GitHubClient()
        with patch.object(
            client, "api",
            return_value={
                "full_name": "curl/curl",
                "description": "transfer lib",
                "html_url": (
                    "https://github.com/curl/curl"
                ),
                "stargazers_count": 40000,
                "default_branch": "master",
                "language": "C",
            },
        ):
            result = client.get_repo_info(
                "https://github.com/curl/curl"
            )
        self.assertEqual(
            result["fullName"], "curl/curl"
        )

    def test_owner_repo(self):
        client = GitHubClient()
        with patch.object(
            client, "api",
            return_value={
                "full_name": "curl/curl",
                "description": "transfer lib",
                "html_url": (
                    "https://github.com/curl/curl"
                ),
                "stargazers_count": 40000,
                "default_branch": "master",
                "language": "C",
            },
        ):
            result = client.get_repo_info(
                "curl/curl"
            )
        self.assertEqual(
            result["fullName"], "curl/curl"
        )

    def test_plain_name_searches(self):
        client = GitHubClient()
        with patch.object(
            client, "search_repos",
            return_value={
                "fullName": "curl/curl",
                "defaultBranch": "master",
            },
        ) as mock_search:
            result = client.get_repo_info("curl")
        mock_search.assert_called_once_with("curl")
        self.assertEqual(
            result["fullName"], "curl/curl"
        )

    def test_url_api_failure_falls_to_search(self):
        client = GitHubClient()
        with patch.object(
            client, "api", return_value=None
        ):
            with patch.object(
                client, "search_repos",
                return_value={
                    "fullName": "curl/curl"
                },
            ) as mock_search:
                client.get_repo_info(
                    "https://github.com/curl/curl"
                )
        mock_search.assert_called_once()

    def test_owner_repo_api_failure(self):
        client = GitHubClient()
        with patch.object(
            client, "api", return_value=None
        ):
            with patch.object(
                client, "search_repos",
                return_value=None,
            ) as mock_search:
                client.get_repo_info("bad/repo")
        mock_search.assert_called_once_with(
            "bad/repo"
        )


class TestGitHubClientGetFileTree(unittest.TestCase):
    """Tests for GitHubClient.get_file_tree()."""

    def test_collects_files(self):
        client = GitHubClient()

        def side_effect(url):
            is_root = (
                "contents?" in url
                and "/src" not in url
                and "/lib" not in url
                and "/auto" not in url
            )
            if is_root:
                return [
                    {"name": "configure.ac"},
                    {"name": "Makefile"},
                    {"name": "src"},
                ]
            elif "/contents/src" in url:
                return [{"name": "main.c"}]
            elif "/contents/lib" in url:
                return None
            elif "/contents/auto" in url:
                return None
            return None

        with patch.object(
            client, "api",
            side_effect=side_effect,
        ):
            files = client.get_file_tree(
                "test/repo", "main"
            )
        self.assertIn("configure.ac", files)
        self.assertIn("Makefile", files)
        self.assertIn("src/main.c", files)

    def test_returns_empty_on_failure(self):
        client = GitHubClient()
        with patch.object(
            client, "api", return_value=None
        ):
            files = client.get_file_tree(
                "bad/repo", "main"
            )
        self.assertEqual(files, [])

    def test_auto_dir_scanned(self):
        client = GitHubClient()

        def side_effect(url):
            is_root = (
                "contents?" in url
                and "/src" not in url
                and "/lib" not in url
                and "/auto" not in url
            )
            if is_root:
                return [
                    {"name": "src"},
                    {"name": "auto"},
                ]
            elif "/contents/src" in url:
                return [{"name": "core"}]
            elif "/contents/lib" in url:
                return None
            elif "/contents/auto" in url:
                return [{"name": "configure"}]
            return None

        with patch.object(
            client, "api",
            side_effect=side_effect,
        ):
            files = client.get_file_tree(
                "nginx/nginx", "master"
            )
        self.assertIn("auto/configure", files)
        self.assertIn("src/core", files)


class TestGitHubClientGetFileContent(
    unittest.TestCase
):
    """Tests for GitHubClient.get_file_content()."""

    def test_decodes_base64(self):
        client = GitHubClient()
        content = "hello world"
        encoded = base64.b64encode(
            content.encode()
        ).decode()
        with patch.object(
            client, "api",
            return_value={"content": encoded},
        ):
            result = client.get_file_content(
                "test/repo", "README.md", "main"
            )
        self.assertEqual(result, "hello world")

    def test_returns_none_on_missing(self):
        client = GitHubClient()
        with patch.object(
            client, "api", return_value=None
        ):
            result = client.get_file_content(
                "test/repo", "missing.txt", "main"
            )
        self.assertIsNone(result)

    def test_returns_none_on_no_content(self):
        client = GitHubClient()
        with patch.object(
            client, "api",
            return_value={"name": "file.txt"},
        ):
            result = client.get_file_content(
                "test/repo", "file.txt", "main"
            )
        self.assertIsNone(result)


class TestGitHubClientGetLanguages(
    unittest.TestCase
):
    """Tests for GitHubClient.get_languages()."""

    def test_returns_language_data(self):
        client = GitHubClient()
        with patch.object(
            client, "api",
            return_value={"C": 400000},
        ):
            result = client.get_languages(
                "curl/curl"
            )
        self.assertEqual(result, {"C": 400000})


# ============================================================
# BuildSystemDetector
# ============================================================

class TestBuildSystemDetector(unittest.TestCase):
    """Tests for BuildSystemDetector."""

    def _detector(self):
        from data_loader import DataLoader
        indicators = DataLoader().load_build_systems()
        return BuildSystemDetector(indicators)

    def test_autoconf(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["configure.ac", "Makefile.am"]),
            "autoconf",
        )

    def test_autoconf_in(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["configure.in", "Makefile"]),
            "autoconf",
        )

    def test_cmake(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["CMakeLists.txt", "src/main.c"]),
            "cmake",
        )

    def test_meson(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["meson.build", "src/main.c"]),
            "meson",
        )

    def test_perl_configure_capital(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["Configure", "Makefile"]),
            "perl-configure",
        )

    def test_perl_configure_config(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["config", "Makefile"]),
            "perl-configure",
        )

    def test_auto_configure(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["auto/configure", "src/core"]),
            "auto-configure",
        )

    def test_configure_only(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["configure", "Makefile"]),
            "configure-only",
        )

    def test_configure_before_makefile(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["Makefile", "configure"]),
            "configure-only",
        )

    def test_make_only(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["Makefile", "src/main.c"]),
            "make-only",
        )

    def test_unknown(self):
        d = self._detector()
        self.assertEqual(
            d.detect(["README.md", "src/main.rs"]),
            "unknown",
        )

    def test_autoconf_priority_over_cmake(self):
        d = self._detector()
        self.assertEqual(
            d.detect([
                "configure.ac", "CMakeLists.txt",
            ]),
            "autoconf",
        )

    def test_empty_indicators(self):
        d = BuildSystemDetector([])
        self.assertEqual(
            d.detect(["configure.ac"]), "unknown"
        )


# ============================================================
# DependencyAnalyzer
# ============================================================

class TestDependencyAnalyzer(unittest.TestCase):
    """Tests for DependencyAnalyzer."""

    def _analyzer(self, file_content=None):
        from data_loader import DataLoader
        deps = DataLoader().load_dependencies()
        github = MagicMock()
        github.get_file_content.return_value = (
            file_content
        )
        return DependencyAnalyzer(deps, github)

    def test_autoconf_detects_openssl(self):
        a = self._analyzer(
            "AC_CHECK_LIB([ssl], [SSL_new])\n"
            "PKG_CHECK_MODULES([OPENSSL], "
            "[openssl])\n"
        )
        flags, pkgs = a.analyze(
            "curl/curl", "master", "autoconf",
            ["configure.ac"],
        )
        self.assertIn("--with-openssl", flags)
        self.assertIn("libssl-dev", pkgs)

    def test_cmake_detects_openssl(self):
        a = self._analyzer(
            "find_package(OpenSSL REQUIRED)\n"
        )
        flags, pkgs = a.analyze(
            "test/repo", "main", "cmake",
            ["CMakeLists.txt"],
        )
        self.assertIn(
            "-DCMAKE_USE_OPENSSL=ON", flags
        )
        self.assertIn("libssl-dev", pkgs)

    def test_unknown_build_system(self):
        a = self._analyzer()
        flags, pkgs = a.analyze(
            "test/repo", "main", "unknown", [],
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    def test_configure_only(self):
        a = self._analyzer(
            "# --enable-libx264\n"
            "# --enable-libx265\n"
            "# openssl support\n"
        )
        flags, pkgs = a.analyze(
            "FFmpeg/FFmpeg", "master",
            "configure-only", ["configure"],
        )
        self.assertIn("--enable-libx264", flags)
        self.assertIn("--enable-libx265", flags)
        self.assertIn("--with-openssl", flags)

    def test_autoconf_no_configure_ac(self):
        a = self._analyzer()
        flags, pkgs = a.analyze(
            "test/repo", "main", "autoconf", [],
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    def test_autoconf_file_returns_none(self):
        a = self._analyzer(None)
        flags, pkgs = a.analyze(
            "test/repo", "main", "autoconf",
            ["configure.ac"],
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    def test_cmake_file_returns_none(self):
        a = self._analyzer(None)
        flags, pkgs = a.analyze(
            "test/repo", "main", "cmake",
            ["CMakeLists.txt"],
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    def test_configure_only_returns_none(self):
        a = self._analyzer(None)
        flags, pkgs = a.analyze(
            "test/repo", "main", "configure-only",
            ["configure"],
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    def test_cmake_detects_zlib(self):
        a = self._analyzer(
            "find_package(ZLIB REQUIRED)\n"
        )
        flags, pkgs = a.analyze(
            "test/repo", "main", "cmake",
            ["CMakeLists.txt"],
        )
        self.assertIn(
            "-DZLIB_LIBRARY="
            "/usr/lib/x86_64-linux-gnu/libz.so",
            flags,
        )
        self.assertIn("zlib1g-dev", pkgs)

    def test_multiple_deps(self):
        a = self._analyzer(
            "AC_CHECK openssl\n"
            "AC_CHECK zlib\n"
            "AC_CHECK nghttp2\n"
        )
        flags, pkgs = a.analyze(
            "test/repo", "main", "autoconf",
            ["configure.ac"],
        )
        self.assertIn("--with-openssl", flags)
        self.assertIn("--with-zlib", flags)
        self.assertIn("--with-nghttp2", flags)


# ============================================================
# BinaryDetector
# ============================================================

class TestBinaryDetector(unittest.TestCase):
    """Tests for BinaryDetector."""

    def _detector(self, file_content=None):
        github = MagicMock()
        github.get_file_content.return_value = (
            file_content
        )
        return BinaryDetector(github)

    def test_fallback_with_src(self):
        d = self._detector()
        bins = d.detect(
            "test/repo", "myapp", "autoconf",
            ["src/main.c", "Makefile"],
        )
        self.assertIn("src/.libs/myapp", bins)
        self.assertIn("src/myapp", bins)

    def test_fallback_without_src(self):
        d = self._detector()
        bins = d.detect(
            "test/repo", "myapp", "autoconf",
            ["main.c", "Makefile"],
        )
        self.assertEqual(bins, ["myapp"])

    def test_bin_programs(self):
        d = self._detector(
            "bin_PROGRAMS = myapp\n"
        )
        bins = d.detect(
            "test/repo", "myapp", "autoconf",
            ["Makefile.am", "src/main.c"],
        )
        self.assertIn("myapp", bins)

    def test_lib_ltlibraries(self):
        d = self._detector(
            "lib_LTLIBRARIES = libcurl.la\n"
        )
        bins = d.detect(
            "curl/curl", "curl", "autoconf",
            ["Makefile.am"],
        )
        found = any("libcurl.so" in b for b in bins)
        self.assertTrue(found)

    def test_makefile_am_returns_none(self):
        d = self._detector(None)
        bins = d.detect(
            "test/repo", "myapp", "autoconf",
            ["Makefile.am"],
        )
        self.assertIn("myapp", bins)


# ============================================================
# BuildStepGenerator
# ============================================================

class TestBuildStepGenerator(unittest.TestCase):
    """Tests for BuildStepGenerator."""

    def setUp(self):
        self.gen = BuildStepGenerator()

    def test_autoconf_no_flags(self):
        steps = self.gen.generate("autoconf", [])
        self.assertEqual(steps, [
            "autoreconf -fi",
            "./configure",
            "make -j$(nproc)",
        ])

    def test_autoconf_with_flags(self):
        steps = self.gen.generate(
            "autoconf",
            ["--with-openssl", "--with-zlib"],
        )
        self.assertEqual(
            steps[1],
            "./configure --with-openssl --with-zlib",
        )

    def test_cmake_no_flags(self):
        steps = self.gen.generate("cmake", [])
        self.assertEqual(steps, [
            "mkdir -p build && cd build && cmake ..",
            "make -C build -j$(nproc)",
        ])

    def test_cmake_with_flags(self):
        steps = self.gen.generate(
            "cmake", ["-DCMAKE_USE_OPENSSL=ON"],
        )
        self.assertIn(
            "-DCMAKE_USE_OPENSSL=ON", steps[0]
        )

    def test_meson(self):
        steps = self.gen.generate("meson", [])
        self.assertEqual(steps, [
            "meson setup build",
            "ninja -C build",
        ])

    def test_perl_configure(self):
        steps = self.gen.generate(
            "perl-configure", []
        )
        self.assertEqual(steps, [
            "./config", "make -j$(nproc)",
        ])

    def test_auto_configure(self):
        steps = self.gen.generate(
            "auto-configure", []
        )
        self.assertEqual(steps, [
            "auto/configure", "make -j$(nproc)",
        ])

    def test_configure_only(self):
        steps = self.gen.generate(
            "configure-only", []
        )
        self.assertEqual(steps, [
            "./configure", "make -j$(nproc)",
        ])

    def test_configure_only_with_flags(self):
        steps = self.gen.generate(
            "configure-only", ["--enable-libx264"],
        )
        self.assertEqual(
            steps[0],
            "./configure --enable-libx264",
        )

    def test_make_only(self):
        steps = self.gen.generate("make-only", [])
        self.assertEqual(
            steps, ["make -j$(nproc)"]
        )

    def test_unknown(self):
        steps = self.gen.generate("unknown", [])
        self.assertEqual(len(steps), 2)
        self.assertIn("TODO", steps[0])

    def test_last_step_is_make_or_ninja(self):
        for bs in [
            "autoconf", "cmake", "configure-only",
            "make-only", "perl-configure",
            "auto-configure", "unknown",
        ]:
            steps = self.gen.generate(bs, [])
            last = steps[-1]
            self.assertTrue(
                "make" in last or "ninja" in last,
                f"Last step for {bs}: {last}",
            )


# ============================================================
# ConfigGenerator
# ============================================================

class TestConfigGenerator(unittest.TestCase):
    """Tests for ConfigGenerator."""

    def test_generate_entry(self):
        gen = ConfigGenerator()
        repo_info = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
        }
        entry = gen.generate_entry(
            repo_info,
            ["autoreconf -fi", "./configure", "make"],
            ["src/curl"],
            "A URL transfer library",
        )
        self.assertEqual(
            entry["url"],
            "https://github.com/curl/curl.git",
        )
        self.assertEqual(entry["branch"], "master")
        self.assertEqual(
            len(entry["build_steps"]), 3
        )
        self.assertEqual(
            entry["clean_cmd"], "make clean"
        )
        self.assertEqual(
            entry["description"],
            "A URL transfer library",
        )
        self.assertEqual(
            entry["output_binaries"], ["src/curl"]
        )
        self.assertNotIn("apt_deps", entry)

    def test_generate_entry_with_apt_deps(self):
        gen = ConfigGenerator()
        repo_info = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
        }
        entry = gen.generate_entry(
            repo_info,
            ["make"],
            ["src/curl"],
            "test",
            apt_deps=[
                "zlib1g-dev", "libssl-dev",
            ],
        )
        self.assertIn("apt_deps", entry)
        self.assertEqual(
            entry["apt_deps"],
            ["libssl-dev", "zlib1g-dev"],
        )

    def test_generate_entry_empty_apt_deps(self):
        gen = ConfigGenerator()
        repo_info = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
        }
        entry = gen.generate_entry(
            repo_info, ["make"], ["src/curl"],
            "test", apt_deps=[],
        )
        self.assertNotIn("apt_deps", entry)

    def test_write_entry_new_repo(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            yaml.dump(
                {"repos": {"existing": {"url": "x"}}},
                f,
            )
            tmp_path = Path(f.name)

        gen = ConfigGenerator(config_path=tmp_path)
        entry = {
            "url": (
                "https://github.com/madler/zlib.git"
            ),
            "branch": "develop",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "zlib",
            "output_binaries": ["zlib"],
        }
        gen.write_entry("zlib", entry)

        with open(
            tmp_path, "r", encoding="utf-8"
        ) as fh:
            result = yaml.safe_load(fh)
        self.assertIn("zlib", result["repos"])
        self.assertIn("existing", result["repos"])
        self.assertEqual(
            result["repos"]["zlib"]["branch"],
            "develop",
        )
        tmp_path.unlink()

    def test_write_entry_overwrites_warns(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            yaml.dump(
                {"repos": {"curl": {"url": "old"}}},
                f,
            )
            tmp_path = Path(f.name)

        gen = ConfigGenerator(config_path=tmp_path)
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            gen.write_entry("curl", {"url": "new"})

        output = "\n".join(printed)
        self.assertIn("WARN", output)
        self.assertIn("curl", output)

        with open(
            tmp_path, "r", encoding="utf-8"
        ) as fh:
            result = yaml.safe_load(fh)
        self.assertEqual(
            result["repos"]["curl"]["url"], "new"
        )
        tmp_path.unlink()

    def test_create_output_dirs(self):
        import app.repo_discovery.config_generator as cg
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = str(
                Path(tmpdir) / "repo_discovery"
                / "config_generator.py"
            )
            (Path(tmpdir) / "repo_discovery").mkdir()
            with patch.object(
                cg, "__file__", fake_file
            ):
                with patch("builtins.print"):
                    ConfigGenerator.create_output_dirs(
                        "test"
                    )
            self.assertTrue(
                (Path(tmpdir) / "output"
                 / "omnibor" / "test").exists()
            )
            self.assertTrue(
                (Path(tmpdir) / "output"
                 / "spdx" / "test").exists()
            )
            self.assertTrue(
                (Path(tmpdir) / "output"
                 / "binary-scan" / "test").exists()
            )
            self.assertTrue(
                (Path(tmpdir) / "docs"
                 / "test").exists()
            )

    def test_get_repo_stats(self):
        github = MagicMock()
        github.get_languages.return_value = {
            "C": 400000, "Python": 20000,
        }
        result = ConfigGenerator.get_repo_stats(
            "curl/curl", github
        )
        self.assertIn("K LoC", result)
        self.assertIn("C", result)

    def test_get_repo_stats_empty(self):
        github = MagicMock()
        github.get_languages.return_value = None
        result = ConfigGenerator.get_repo_stats(
            "bad/repo", github
        )
        self.assertEqual(result, "")


# ============================================================
# RepoDiscovery
# ============================================================

class TestRepoDiscovery(unittest.TestCase):
    """Tests for RepoDiscovery facade."""

    def test_build_description_short(self):
        info = {
            "description": "A URL transfer library"
        }
        result = RepoDiscovery.build_description(
            info, "~170K LoC, C", "curl"
        )
        self.assertIn(
            "A URL transfer library", result
        )
        self.assertIn("~170K LoC", result)

    def test_build_description_long(self):
        info = {"description": "A" * 100}
        result = RepoDiscovery.build_description(
            info, "", "curl"
        )
        self.assertIn("...", result)
        self.assertTrue(len(result) <= 65)

    def test_build_description_empty(self):
        info = {"description": ""}
        result = RepoDiscovery.build_description(
            info, "", "curl"
        )
        self.assertEqual(result, "curl")

    def test_build_description_no_stats(self):
        info = {
            "description": "A URL transfer library"
        }
        result = RepoDiscovery.build_description(
            info, "", "curl"
        )
        self.assertEqual(
            result, "A URL transfer library"
        )


# ============================================================
# main() CLI
# ============================================================

def _mock_discovery():
    """Create a RepoDiscovery with all mocked components."""
    github = MagicMock()
    data_loader = MagicMock()
    data_loader.load_build_systems.return_value = []
    data_loader.load_dependencies.return_value = {}
    detector = MagicMock()
    analyzer = MagicMock()
    binary_detector = MagicMock()
    step_gen = MagicMock()
    config_gen = MagicMock()

    discovery = RepoDiscovery(
        github=github,
        data_loader=data_loader,
        detector=detector,
        analyzer=analyzer,
        binary_detector=binary_detector,
        step_generator=step_gen,
        config_generator=config_gen,
    )
    return discovery


class TestMainDryRun(unittest.TestCase):
    """Tests for main() in dry-run mode."""

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_dry_run_success(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "A URL transfer library",
        }
        d.github.get_file_tree.return_value = [
            "configure.ac", "Makefile", "src/main.c",
        ]
        d.detector.detect.return_value = "autoconf"
        d.analyzer.analyze.return_value = (
            ["--with-openssl"], ["libssl-dev"]
        )
        d.binary_detector.detect.return_value = [
            "src/curl"
        ]
        d.config.get_repo_stats.return_value = (
            "~170K LoC, C"
        )
        d.config.generate_entry.return_value = {
            "url": (
                "https://github.com/curl/curl.git"
            ),
            "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["src/curl"],
        }
        d.steps.generate.return_value = ["make"]

        with patch("builtins.print"):
            with patch(
                "app.repo_discovery.cli.Path.exists",
                return_value=True,
            ):
                with patch(
                    "app.repo_discovery.cli.Path.read_text",
                    return_value="libssl-dev",
                ):
                    add_repo.main()

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch(
        "sys.argv",
        ["add_repo.py", "nonexistent"],
    )
    def test_repo_not_found_exits(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = None
        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                add_repo.main()
            self.assertEqual(cm.exception.code, 1)

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_empty_tree_exits(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        d.github.get_file_tree.return_value = []
        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                add_repo.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainWrite(unittest.TestCase):
    """Tests for main() in --write mode."""

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch(
        "sys.argv",
        ["add_repo.py", "curl", "--write"],
    )
    def test_write_mode(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "A URL transfer library",
        }
        d.github.get_file_tree.return_value = [
            "configure.ac", "Makefile",
        ]
        d.detector.detect.return_value = "autoconf"
        d.analyzer.analyze.return_value = ([], [])
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = ""
        d.config.generate_entry.return_value = {
            "url": (
                "https://github.com/curl/curl.git"
            ),
            "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        with patch("builtins.print"):
            add_repo.main()

        d.config.write_entry.assert_called_once()
        d.config.create_output_dirs.assert_called_once()


class TestMainWithAptPackages(unittest.TestCase):
    """Test main() Dockerfile package checking."""

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_new_packages_reported(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        d.github.get_file_tree.return_value = [
            "configure.ac", "Makefile",
        ]
        d.detector.detect.return_value = "autoconf"
        d.analyzer.analyze.return_value = (
            ["--with-openssl"],
            ["libssl-dev", "libnew-dev"],
        )
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = ""
        d.config.generate_entry.return_value = {
            "url": "x", "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            with patch(
                "app.repo_discovery.cli.Path.exists",
                return_value=True,
            ):
                with patch(
                    "app.repo_discovery.cli.Path.read_text",
                    return_value="libssl-dev",
                ):
                    add_repo.main()

        output = "\n".join(printed)
        self.assertIn("libnew-dev", output)

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_all_packages_installed(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        d.github.get_file_tree.return_value = [
            "configure.ac", "Makefile",
        ]
        d.detector.detect.return_value = "autoconf"
        d.analyzer.analyze.return_value = (
            ["--with-openssl"], ["libssl-dev"],
        )
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = ""
        d.config.generate_entry.return_value = {
            "url": "x", "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            with patch(
                "app.repo_discovery.cli.Path.exists",
                return_value=True,
            ):
                with patch(
                    "app.repo_discovery.cli.Path.read_text",
                    return_value="libssl-dev",
                ):
                    add_repo.main()

        output = "\n".join(printed)
        self.assertIn("All required packages", output)

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_no_dockerfile(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        d.github.get_file_tree.return_value = [
            "configure.ac", "Makefile",
        ]
        d.detector.detect.return_value = "autoconf"
        d.analyzer.analyze.return_value = (
            ["--with-openssl"], ["libssl-dev"],
        )
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = ""
        d.config.generate_entry.return_value = {
            "url": "x", "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        with patch("builtins.print"):
            with patch(
                "app.repo_discovery.cli.Path.exists",
                return_value=False,
            ):
                add_repo.main()


class TestMainDescriptionTruncation(
    unittest.TestCase
):
    """Test description truncation in main()."""

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_long_description(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "A" * 100,
        }
        d.github.get_file_tree.return_value = [
            "Makefile"
        ]
        d.detector.detect.return_value = "make-only"
        d.analyzer.analyze.return_value = ([], [])
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = (
            "~170K LoC, C"
        )
        d.config.generate_entry.return_value = {
            "url": "x", "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            add_repo.main()

        output = "\n".join(printed)
        self.assertIn("...", output)

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_no_description(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "",
        }
        d.github.get_file_tree.return_value = [
            "Makefile"
        ]
        d.detector.detect.return_value = "make-only"
        d.analyzer.analyze.return_value = ([], [])
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = ""
        d.config.generate_entry.return_value = {
            "url": "x", "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        with patch("builtins.print"):
            add_repo.main()


class TestMainNoFlags(unittest.TestCase):
    """Test main() with no configure flags."""

    @patch("app.repo_discovery.cli.RepoDiscovery")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_no_flags_message(self, mock_cls):
        d = _mock_discovery()
        mock_cls.return_value = d
        d.github.get_repo_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        d.github.get_file_tree.return_value = [
            "Makefile"
        ]
        d.detector.detect.return_value = "make-only"
        d.analyzer.analyze.return_value = ([], [])
        d.binary_detector.detect.return_value = [
            "curl"
        ]
        d.config.get_repo_stats.return_value = ""
        d.config.generate_entry.return_value = {
            "url": "x", "branch": "master",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["curl"],
        }
        d.steps.generate.return_value = ["make"]

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            add_repo.main()

        output = "\n".join(printed)
        self.assertIn(
            "No optional dependency flags", output
        )


if __name__ == "__main__":
    unittest.main()
