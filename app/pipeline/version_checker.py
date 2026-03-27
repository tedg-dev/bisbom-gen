"""
OmniBOR/bomsh version checker.

Checks for updates to the upstream bomsh repository before running analysis.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Cache file to avoid repeated checks
CACHE_FILE = Path.home() / ".cache" / "omnibor-analysis" / "version_check.json"
CACHE_TTL_HOURS = 24

BOMSH_REPO = "omnibor/bomsh"


def get_latest_release():
    """Get the latest release tag from omnibor/bomsh.

    Returns:
        dict with 'tag_name', 'published_at', 'html_url' or None on error
    """
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{BOMSH_REPO}/releases/latest",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            # No releases yet, check latest commit instead
            return _get_latest_commit()

        data = json.loads(result.stdout)
        return {
            "tag_name": data.get("tag_name"),
            "published_at": data.get("published_at"),
            "html_url": data.get(
                "html_url"
            ),
            "type": "release",
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def _get_latest_commit():
    """Fall back to latest commit if no releases exist."""
    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{BOMSH_REPO}/commits/master",
                "--jq", ".sha,.commit.committer.date",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            return {
                "tag_name": lines[0][:12],  # Short SHA
                "published_at": lines[1],
                "html_url": (
                    f"https://github.com/{BOMSH_REPO}"
                    f"/commit/{lines[0]}"
                ),
                "type": "commit",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def load_cache():
    """Load cached version check result."""
    if not CACHE_FILE.exists():
        return None

    try:
        data = json.loads(CACHE_FILE.read_text())
        checked_at = datetime.fromisoformat(data.get("checked_at", ""))
        if datetime.now() - checked_at < timedelta(hours=CACHE_TTL_HOURS):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def save_cache(latest_info):
    """Save version check result to cache."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "checked_at": datetime.now().isoformat(),
        "latest": latest_info,
    }
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def should_skip_check():
    """Check if version check should be skipped."""
    # Skip in CI environments
    if os.environ.get("CI"):
        return True
    # Skip if explicitly disabled
    if os.environ.get("OMNIBOR_SKIP_VERSION_CHECK"):
        return True
    return False


def check_for_updates(current_version=None, force=False):
    """Check if bomsh has updates available.

    Args:
        current_version: Current pinned version (optional)
        force: Force check even if cached

    Returns:
        tuple: (has_update, latest_info, message)
    """
    if should_skip_check():
        return False, None, "Version check skipped (CI mode)"

    # Check cache first
    if not force:
        cached = load_cache()
        if cached:
            return False, cached.get("latest"), "Using cached check"

    latest = get_latest_release()
    if not latest:
        return False, None, "Could not fetch latest version"

    save_cache(latest)

    # If we have a current version, compare
    if current_version:
        if latest["tag_name"] != current_version:
            return True, latest, format_update_message(current_version, latest)

    return False, latest, "Up to date"


def format_update_message(current, latest):
    """Format an update notification message."""
    return f"""
[UPDATE AVAILABLE] OmniBOR/bomsh has a newer version.

Current: {current}
Latest:  {latest['tag_name']} ({latest['type']})
Date:    {latest.get('published_at', 'unknown')}
URL:     {latest['html_url']}

To update:
1. Update docker/Dockerfile with the new version
2. Rebuild: docker compose -f docker/docker-compose.yml build
3. Test with a known-good repo

Continue without updating? (y/n)
"""
