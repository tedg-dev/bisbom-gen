"""
Repository cloning for OmniBOR Analysis.

Handles shallow cloning of target repositories.
"""

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
