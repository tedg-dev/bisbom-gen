"""Tests for app/pipeline/version_checker.py."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from app.pipeline.version_checker import (
    check_for_updates,
    format_update_message,
    get_latest_release,
    load_cache,
    save_cache,
    should_skip_check,
    _get_latest_commit,
    CACHE_FILE,
)


class TestGetLatestRelease(unittest.TestCase):
    """Tests for get_latest_release()."""

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "tag_name": "v1.0",
                "published_at": "2026-01-01",
                "html_url": "https://github.com/x",
            }),
        )
        result = get_latest_release()
        self.assertEqual(result["tag_name"], "v1.0")
        self.assertEqual(result["type"], "release")

    @patch(
        "app.pipeline.version_checker._get_latest_commit"
    )
    @patch("app.pipeline.version_checker.subprocess.run")
    def test_no_releases_fallback(
        self, mock_run, mock_commit
    ):
        mock_run.return_value = MagicMock(returncode=1)
        mock_commit.return_value = {
            "tag_name": "abc123",
            "type": "commit",
        }
        result = get_latest_release()
        self.assertEqual(result["type"], "commit")

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = (
            subprocess.TimeoutExpired("gh", 30)
        )
        result = get_latest_release()
        self.assertIsNone(result)

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_json_decode_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json"
        )
        result = get_latest_release()
        self.assertIsNone(result)


class TestGetLatestCommit(unittest.TestCase):
    """Tests for _get_latest_commit()."""

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123def456\n2026-01-01T00:00:00Z\n",
        )
        result = _get_latest_commit()
        self.assertEqual(
            result["tag_name"], "abc123def456"
        )
        self.assertEqual(result["type"], "commit")

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        result = _get_latest_commit()
        self.assertIsNone(result)

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_short_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="onlyoneline\n",
        )
        result = _get_latest_commit()
        self.assertIsNone(result)

    @patch("app.pipeline.version_checker.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = (
            subprocess.TimeoutExpired("gh", 30)
        )
        result = _get_latest_commit()
        self.assertIsNone(result)


class TestLoadCache(unittest.TestCase):
    """Tests for load_cache()."""

    def test_no_cache_file(self):
        with patch(
            "app.pipeline.version_checker.CACHE_FILE",
            Path("/nonexistent/file.json"),
        ):
            result = load_cache()
            self.assertIsNone(result)

    def test_valid_cache(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        ) as f:
            json.dump({
                "checked_at": datetime.now().isoformat(),
                "latest": {"tag_name": "v1.0"},
            }, f)
            tmp = Path(f.name)
        with patch(
            "app.pipeline.version_checker.CACHE_FILE",
            tmp,
        ):
            result = load_cache()
        self.assertIsNotNone(result)
        tmp.unlink()

    def test_expired_cache(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        ) as f:
            old = datetime.now() - timedelta(hours=48)
            json.dump({
                "checked_at": old.isoformat(),
                "latest": {"tag_name": "v1.0"},
            }, f)
            tmp = Path(f.name)
        with patch(
            "app.pipeline.version_checker.CACHE_FILE",
            tmp,
        ):
            result = load_cache()
        self.assertIsNone(result)
        tmp.unlink()

    def test_corrupt_cache(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w",
        ) as f:
            f.write("not json")
            tmp = Path(f.name)
        with patch(
            "app.pipeline.version_checker.CACHE_FILE",
            tmp,
        ):
            result = load_cache()
        self.assertIsNone(result)
        tmp.unlink()


class TestSaveCache(unittest.TestCase):
    """Tests for save_cache()."""

    def test_creates_cache_file(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = (
                Path(td) / "sub" / "cache.json"
            )
            with patch(
                "app.pipeline.version_checker"
                ".CACHE_FILE",
                cache_path,
            ):
                save_cache({"tag_name": "v2.0"})
            self.assertTrue(cache_path.exists())
            data = json.loads(cache_path.read_text())
            self.assertEqual(
                data["latest"]["tag_name"], "v2.0"
            )


class TestShouldSkipCheck(unittest.TestCase):
    """Tests for should_skip_check()."""

    def test_ci_env(self):
        with patch.dict(os.environ, {"CI": "true"}):
            self.assertTrue(should_skip_check())

    def test_skip_env(self):
        with patch.dict(
            os.environ,
            {"OMNIBOR_SKIP_VERSION_CHECK": "1"},
        ):
            self.assertTrue(should_skip_check())

    def test_normal(self):
        with patch.dict(
            os.environ, {}, clear=True,
        ):
            # Remove CI and skip vars if present
            os.environ.pop("CI", None)
            os.environ.pop(
                "OMNIBOR_SKIP_VERSION_CHECK", None
            )
            self.assertFalse(should_skip_check())


class TestCheckForUpdates(unittest.TestCase):
    """Tests for check_for_updates()."""

    @patch(
        "app.pipeline.version_checker"
        ".should_skip_check",
        return_value=True,
    )
    def test_skipped(self, _):
        has, info, msg = check_for_updates()
        self.assertFalse(has)
        self.assertIn("skipped", msg)

    @patch(
        "app.pipeline.version_checker.save_cache"
    )
    @patch(
        "app.pipeline.version_checker"
        ".get_latest_release",
        return_value=None,
    )
    @patch(
        "app.pipeline.version_checker.load_cache",
        return_value=None,
    )
    @patch(
        "app.pipeline.version_checker"
        ".should_skip_check",
        return_value=False,
    )
    def test_fetch_failure(self, *_):
        has, info, msg = check_for_updates(force=True)
        self.assertFalse(has)
        self.assertIn("Could not fetch", msg)

    @patch(
        "app.pipeline.version_checker.save_cache"
    )
    @patch(
        "app.pipeline.version_checker"
        ".get_latest_release",
    )
    @patch(
        "app.pipeline.version_checker.load_cache",
        return_value=None,
    )
    @patch(
        "app.pipeline.version_checker"
        ".should_skip_check",
        return_value=False,
    )
    def test_update_available(
        self, _, _lc, mock_release, _sc,
    ):
        mock_release.return_value = {
            "tag_name": "v2.0",
            "type": "release",
            "published_at": "2026-06-01",
            "html_url": "https://github.com/x",
        }
        has, info, msg = check_for_updates(
            current_version="v1.0", force=True,
        )
        self.assertTrue(has)
        self.assertIn("UPDATE", msg)

    @patch(
        "app.pipeline.version_checker.save_cache"
    )
    @patch(
        "app.pipeline.version_checker"
        ".get_latest_release",
    )
    @patch(
        "app.pipeline.version_checker.load_cache",
        return_value=None,
    )
    @patch(
        "app.pipeline.version_checker"
        ".should_skip_check",
        return_value=False,
    )
    def test_up_to_date(
        self, _, _lc, mock_release, _sc,
    ):
        mock_release.return_value = {
            "tag_name": "v1.0",
            "type": "release",
            "published_at": "2026-01-01",
            "html_url": "https://github.com/x",
        }
        has, info, msg = check_for_updates(
            current_version="v1.0", force=True,
        )
        self.assertFalse(has)
        self.assertEqual(msg, "Up to date")

    @patch(
        "app.pipeline.version_checker.load_cache",
    )
    @patch(
        "app.pipeline.version_checker"
        ".should_skip_check",
        return_value=False,
    )
    def test_uses_cache(self, _, mock_cache):
        mock_cache.return_value = {
            "latest": {"tag_name": "v1.0"},
        }
        has, info, msg = check_for_updates()
        self.assertFalse(has)
        self.assertIn("cached", msg)


class TestFormatUpdateMessage(unittest.TestCase):
    """Tests for format_update_message()."""

    def test_format(self):
        msg = format_update_message("v1.0", {
            "tag_name": "v2.0",
            "type": "release",
            "published_at": "2026-06-01",
            "html_url": "https://github.com/x",
        })
        self.assertIn("v1.0", msg)
        self.assertIn("v2.0", msg)
        self.assertIn("UPDATE", msg)


if __name__ == "__main__":
    unittest.main()
