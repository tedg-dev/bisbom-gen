"""
Repository cloning for OmniBOR Analysis.

Handles shallow cloning of target repositories.
"""

import subprocess
from pathlib import Path

from app.runner import CommandRunner


class RepoCloner:
    """Handles git clone logic."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def clone(self, repo_name, repo_cfg, paths_cfg):
        """Clone the target repository if not already present."""
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        if repo_dir.exists() and any(
            repo_dir.iterdir()
        ):
            print(
                "[INFO] Repository already exists "
                f"at {repo_dir}, skipping clone."
            )
            return str(repo_dir)

        url = repo_cfg["url"]
        branch = repo_cfg.get("branch", "master")
        self.runner.run(
            f"git clone --depth 1 "
            f"--branch {branch} {url} {repo_dir}",
            description=(
                f"Cloning {repo_name} ({branch})"
            ),
        )
        # Prefer tag over branch when both share a
        # name (avoids Maven SNAPSHOT builds)
        self.runner.run(
            f"git -C {repo_dir} fetch origin "
            f"tag {branch} --no-tags 2>/dev/null "
            f"&& git -C {repo_dir} checkout "
            f"tags/{branch} 2>/dev/null || true",
            description=(
                f"Checkout tag {branch} "
                f"(if exists)"
            ),
        )
        return str(repo_dir)

    @staticmethod
    def get_commit_sha(repo_dir):
        """Return the HEAD commit SHA for a repo directory.

        Returns the full 40-character hex SHA, or None
        if the directory is not a git repository or
        git is unavailable.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                sha = result.stdout.strip()
                if len(sha) == 40:
                    return sha
        except Exception:
            pass
        return None

    @staticmethod
    def build_vcs_uri(repo_url, commit_sha):
        """Build a VCS download URI for SPDX downloadLocation.

        Follows the SPDX 2.3 Annex E VCS URI format:
            git+<url>@<commit_sha>

        Args:
            repo_url: the repository clone URL.
            commit_sha: the 40-char commit SHA.

        Returns:
            str: VCS URI, or "NOASSERTION" if inputs
            are missing.
        """
        if not repo_url or not commit_sha:
            return "NOASSERTION"
        return f"git+{repo_url}@{commit_sha}"
