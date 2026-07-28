#!/usr/bin/env python3
"""Tests for app/data_loader.py — class-based external data loading."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add app/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
import data_loader
from data_loader import (
    HttpClient, JsonCache, RepologyResolver, DataLoader,
)


# ============================================================
# HttpClient
# ============================================================

class TestHttpClient(unittest.TestCase):
    """Tests for HttpClient."""

    @patch("data_loader.urllib.request.urlopen")
    def test_fetch_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(
            return_value=False
        )
        mock_urlopen.return_value = mock_resp

        client = HttpClient()
        result = client.fetch("https://example.com")
        self.assertEqual(result, b'{"ok": true}')

    @patch("data_loader.urllib.request.urlopen")
    def test_fetch_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = (
            data_loader.urllib.error.URLError("fail")
        )
        client = HttpClient()
        self.assertIsNone(
            client.fetch("https://example.com")
        )

    @patch("data_loader.urllib.request.urlopen")
    def test_fetch_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()
        client = HttpClient()
        self.assertIsNone(
            client.fetch("https://example.com")
        )

    @patch("data_loader.urllib.request.urlopen")
    def test_fetch_json_valid(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            b'[{"repo": "test"}]'
        )
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(
            return_value=False
        )
        mock_urlopen.return_value = mock_resp

        client = HttpClient()
        result = client.fetch_json(
            "https://example.com"
        )
        self.assertEqual(result, [{"repo": "test"}])

    def test_fetch_json_network_failure(self):
        client = HttpClient()
        with patch.object(
            client, "fetch", return_value=None
        ):
            self.assertIsNone(
                client.fetch_json(
                    "https://example.com"
                )
            )

    def test_fetch_json_invalid_json(self):
        client = HttpClient()
        with patch.object(
            client, "fetch", return_value=b"bad"
        ):
            self.assertIsNone(
                client.fetch_json(
                    "https://example.com"
                )
            )

    def test_custom_user_agent(self):
        client = HttpClient(user_agent="test/1.0")
        self.assertEqual(
            client.user_agent, "test/1.0"
        )

    def test_default_user_agent(self):
        client = HttpClient()
        self.assertIn(
            "bisbom-gen", client.user_agent
        )


# ============================================================
# JsonCache
# ============================================================

class TestJsonCache(unittest.TestCase):
    """Tests for JsonCache."""

    def test_read_valid(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"key": "value"}, f)
            tmp = Path(f.name)
        result = JsonCache.read(tmp)
        self.assertEqual(result, {"key": "value"})
        tmp.unlink()

    def test_read_missing_file(self):
        self.assertIsNone(
            JsonCache.read(
                Path("/nonexistent/file.json")
            )
        )

    def test_read_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("not json {{{")
            tmp = Path(f.name)
        self.assertIsNone(JsonCache.read(tmp))
        tmp.unlink()

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            JsonCache.write(
                path, {"hello": "world"}
            )
            with open(
                path, "r", encoding="utf-8"
            ) as f:
                result = json.load(f)
            self.assertEqual(
                result, {"hello": "world"}
            )

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = (
                Path(tmpdir) / "sub" / "dir"
                / "test.json"
            )
            JsonCache.write(path, {"a": 1})
            self.assertTrue(path.exists())

    def test_write_handles_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            with patch(
                "builtins.open",
                side_effect=OSError("disk full"),
            ):
                JsonCache.write(path, {"a": 1})

    def test_write_atomic_no_tmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            JsonCache.write(path, [1, 2, 3])
            self.assertFalse(
                path.with_suffix(".tmp").exists()
            )
            self.assertTrue(path.exists())

    def test_age_days_none_data(self):
        self.assertIsNone(JsonCache.age_days(None))

    def test_age_days_no_timestamp(self):
        self.assertIsNone(
            JsonCache.age_days({"_meta": {}})
        )

    def test_age_days_no_meta(self):
        self.assertIsNone(
            JsonCache.age_days({"foo": "bar"})
        )

    def test_age_days_valid(self):
        yesterday = (
            datetime.now(timezone.utc)
            - timedelta(days=1)
        ).isoformat()
        age = JsonCache.age_days(
            {"_meta": {"last_updated": yesterday}}
        )
        self.assertIsNotNone(age)
        self.assertAlmostEqual(age, 1.0, delta=0.1)

    def test_age_days_invalid_timestamp(self):
        self.assertIsNone(
            JsonCache.age_days(
                {"_meta": {
                    "last_updated": "not-a-date"
                }}
            )
        )


# ============================================================
# RepologyResolver
# ============================================================

class TestRepologyResolver(unittest.TestCase):
    """Tests for RepologyResolver."""

    def _resolver(self, fetch_return=None):
        http = MagicMock()
        http.fetch_json.return_value = fetch_return
        return RepologyResolver(http=http), http

    def test_find_dev_from_binnames(self):
        r = RepologyResolver()
        data = [
            {
                "repo": "debian_unstable",
                "binnames": [
                    "openssl", "libssl-dev",
                ],
            }
        ]
        self.assertEqual(
            r.find_dev_package(data), "libssl-dev"
        )

    def test_find_dev_from_binname(self):
        r = RepologyResolver()
        data = [
            {
                "repo": "ubuntu_24_04",
                "binname": "libz-dev",
            }
        ]
        self.assertEqual(
            r.find_dev_package(data), "libz-dev"
        )

    def test_skips_non_debian(self):
        r = RepologyResolver()
        data = [
            {
                "repo": "freebsd",
                "binnames": ["openssl-dev"],
            },
        ]
        self.assertIsNone(r.find_dev_package(data))

    def test_no_dev_package(self):
        r = RepologyResolver()
        data = [
            {
                "repo": "debian_unstable",
                "binnames": ["openssl", "libssl3"],
            }
        ]
        self.assertIsNone(r.find_dev_package(data))

    def test_non_list_returns_none(self):
        r = RepologyResolver()
        self.assertIsNone(
            r.find_dev_package("not a list")
        )

    def test_empty_list(self):
        r = RepologyResolver()
        self.assertIsNone(r.find_dev_package([]))

    def test_no_binnames_or_binname(self):
        r = RepologyResolver()
        data = [
            {
                "repo": "debian_unstable",
                "visiblename": "openssl",
            }
        ]
        self.assertIsNone(r.find_dev_package(data))

    def test_refresh_dependency_updates(self):
        r, http = self._resolver([
            {
                "repo": "debian_unstable",
                "binnames": ["libssl-dev"],
            }
        ])
        dep_info = {
            "apt_packages": ["old"],
            "repology_project": "openssl",
        }
        result = r.refresh_dependency(
            "openssl", dep_info
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )

    def test_refresh_dependency_fetch_fail(self):
        r, http = self._resolver(None)
        dep_info = {"apt_packages": ["old"]}
        result = r.refresh_dependency(
            "openssl", dep_info
        )
        self.assertIs(result, dep_info)

    def test_refresh_dependency_no_dev(self):
        r, http = self._resolver([
            {
                "repo": "debian_unstable",
                "binnames": ["openssl"],
            }
        ])
        dep_info = {"apt_packages": ["old"]}
        result = r.refresh_dependency(
            "openssl", dep_info
        )
        self.assertIs(result, dep_info)

    def test_refresh_uses_dep_name_fallback(self):
        r, http = self._resolver(None)
        r.refresh_dependency(
            "mylib", {"apt_packages": ["x"]}
        )
        http.fetch_json.assert_called_once_with(
            f"{data_loader.REPOLOGY_API}/mylib"
        )

    def test_resolve_unknown_success(self):
        r, http = self._resolver([
            {
                "repo": "debian_unstable",
                "binnames": ["libnew-dev"],
            }
        ])
        result = r.resolve_unknown("newlib")
        self.assertIsNotNone(result)
        self.assertEqual(
            result["apt_packages"], ["libnew-dev"]
        )

    def test_resolve_unknown_fetch_fail(self):
        r, http = self._resolver(None)
        self.assertIsNone(r.resolve_unknown("x"))

    def test_resolve_unknown_no_dev(self):
        r, http = self._resolver([
            {
                "repo": "debian_unstable",
                "binnames": ["nodev"],
            }
        ])
        self.assertIsNone(r.resolve_unknown("x"))


# ============================================================
# DataLoader
# ============================================================

class TestDataLoader(unittest.TestCase):
    """Tests for DataLoader class."""

    def _loader(self, cache_data=None):
        cache = MagicMock()
        cache.read.return_value = cache_data
        cache.age_days.return_value = None
        resolver = MagicMock()
        loader = DataLoader(
            data_dir=Path("/tmp/test"),
            resolver=resolver,
            cache=cache,
        )
        return loader, cache, resolver

    def test_load_build_systems(self):
        loader, cache, _ = self._loader({
            "indicators": [
                {
                    "file": "configure.ac",
                    "system": "autoconf",
                },
                {
                    "file": "CMakeLists.txt",
                    "system": "cmake",
                },
            ]
        })
        result = loader.load_build_systems()
        self.assertEqual(result, [
            ("configure.ac", "autoconf"),
            ("CMakeLists.txt", "cmake"),
        ])

    def test_load_build_systems_missing(self):
        loader, cache, _ = self._loader(None)
        self.assertEqual(
            loader.load_build_systems(), []
        )

    def test_load_build_systems_skips_bad(self):
        loader, cache, _ = self._loader({
            "indicators": [
                {
                    "file": "ok",
                    "system": "autoconf",
                },
                {"bad": "entry"},
            ]
        })
        self.assertEqual(
            len(loader.load_build_systems()), 1
        )

    def test_load_dependencies(self):
        loader, cache, _ = self._loader({
            "_meta": {"cache_max_age_days": 7},
            "libraries": {
                "openssl": {
                    "apt_packages": ["libssl-dev"]
                },
            },
        })
        result = loader.load_dependencies()
        self.assertIn("openssl", result)

    def test_load_dependencies_missing(self):
        loader, cache, _ = self._loader(None)
        self.assertEqual(
            loader.load_dependencies(), {}
        )

    def test_load_dependencies_refresh(self):
        data = {
            "_meta": {"cache_max_age_days": 7},
            "libraries": {
                "x": {"apt_packages": ["y"]}
            },
        }
        loader, cache, _ = self._loader(data)
        with patch.object(
            loader, "refresh_all",
            return_value=data,
        ) as mock_refresh:
            deps = loader.load_dependencies(
                refresh=True
            )
        self.assertIn("x", deps)
        mock_refresh.assert_called_once()
        cache.write.assert_called_once()

    def test_lookup_exact(self):
        loader, _, _ = self._loader(None)
        deps = {
            "openssl": {
                "apt_packages": ["libssl-dev"]
            }
        }
        result = loader.lookup_dependency(
            "openssl", deps
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )

    def test_lookup_case_insensitive(self):
        loader, _, _ = self._loader(None)
        deps = {
            "OpenSSL": {
                "apt_packages": ["libssl-dev"]
            }
        }
        result = loader.lookup_dependency(
            "openssl", deps
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )

    def test_lookup_repology_on_miss(self):
        loader, cache, resolver = self._loader(None)
        resolver.resolve_unknown.return_value = {
            "apt_packages": ["libnew-dev"]
        }
        cache.read.return_value = {"libraries": {}}
        result = loader.lookup_dependency(
            "newlib", {}
        )
        self.assertIsNotNone(result)
        cache.write.assert_called_once()

    def test_lookup_returns_none_on_miss(self):
        loader, _, resolver = self._loader(None)
        resolver.resolve_unknown.return_value = None
        result = loader.lookup_dependency(
            "unknown", {}
        )
        self.assertIsNone(result)

    def test_lookup_no_persist_no_libraries(self):
        loader, cache, resolver = self._loader(None)
        resolver.resolve_unknown.return_value = {
            "apt_packages": ["libnew-dev"]
        }
        cache.read.return_value = None
        result = loader.lookup_dependency(
            "newlib", {}
        )
        self.assertIsNotNone(result)
        cache.write.assert_not_called()

    @patch("data_loader.time.sleep")
    def test_refresh_all_stale(self, mock_sleep):
        loader, cache, resolver = self._loader(None)
        cache.age_days.return_value = None
        resolver.refresh_dependency.side_effect = (
            lambda n, i: {
                **i, "apt_packages": ["new"]
            }
        )
        deps_data = {
            "_meta": {},
            "libraries": {
                "openssl": {
                    "apt_packages": ["old"],
                },
            },
        }
        result = loader.refresh_all(deps_data)
        self.assertIn(
            "last_updated", result["_meta"]
        )
        mock_sleep.assert_called()

    def test_refresh_all_fresh(self):
        loader, cache, resolver = self._loader(None)
        cache.age_days.return_value = 1.0
        deps_data = {
            "_meta": {"last_updated": "x"},
            "libraries": {"a": {}},
        }
        result = loader.refresh_all(
            deps_data, max_age_days=7
        )
        resolver.refresh_dependency.assert_not_called()
        self.assertIs(result, deps_data)

    @patch("data_loader.time.sleep")
    def test_refresh_all_no_update(self, mock_sleep):
        loader, cache, resolver = self._loader(None)
        cache.age_days.return_value = None
        original = {"apt_packages": ["old"]}
        resolver.refresh_dependency.return_value = (
            original
        )
        deps_data = {
            "_meta": {},
            "libraries": {"lib": original},
        }
        result = loader.refresh_all(
            deps_data, max_age_days=0
        )
        self.assertIn(
            "last_updated", result["_meta"]
        )


# ============================================================
# Module-level backward compat
# ============================================================

class TestModuleLevelFunctions(unittest.TestCase):
    """Tests for module-level convenience functions."""

    def test_load_build_systems_compat(self):
        data_loader._default_loader = None
        result = data_loader.load_build_systems()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        files = [f for f, _ in result]
        self.assertIn("configure.ac", files)

    def test_load_dependencies_compat(self):
        data_loader._default_loader = None
        result = data_loader.load_dependencies()
        self.assertIsInstance(result, dict)
        self.assertIn("openssl", result)

    def test_lookup_dependency_compat(self):
        deps = {
            "openssl": {
                "apt_packages": ["libssl-dev"]
            }
        }
        result = data_loader.lookup_dependency(
            "openssl", deps
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )


# ============================================================
# Integration with real seed data
# ============================================================

class TestIntegration(unittest.TestCase):
    """Integration test using real seed data files."""

    def test_real_build_systems(self):
        loader = DataLoader()
        result = loader.load_build_systems()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        files = [f for f, _ in result]
        self.assertIn("configure.ac", files)
        self.assertIn("CMakeLists.txt", files)
        self.assertIn("meson.build", files)

    def test_real_dependencies(self):
        loader = DataLoader()
        result = loader.load_dependencies()
        self.assertIsInstance(result, dict)
        self.assertTrue(len(result) > 0)
        self.assertIn("openssl", result)
        self.assertIn(
            "libssl-dev",
            result["openssl"]["apt_packages"],
        )


if __name__ == "__main__":
    unittest.main()
