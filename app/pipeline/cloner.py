"""
Repository cloning for bisbom-gen.

Handles shallow cloning of target repositories.
"""

import re
import shutil
import subprocess
from pathlib import Path

from app.runner import CommandRunner

# A configured ref that is exactly 40 hex chars is treated as a pinned
# commit SHA (repos without stable release tags, per upstream-pinning).
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

# Instrumentation artifacts that must never persist across runs inside a
# reused checkout.  Some native builds audit their own working tree (e.g.
# the Apache RAT license plugin) and fail on unrecognized files, so a
# stale capture dir from a previous run would break an otherwise-clean
# build.  ``.omnibor`` is the pre-rebrand name, kept for legacy checkouts.
_STALE_CAPTURE_DIRS = (".bisbom", ".omnibor")


class RepoCloner:
    """Handles git clone logic."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def clone(self, repo_name, repo_cfg, paths_cfg):
        """Clone the target repository, pinned to the configured ref.

        The ``branch`` config field may be a branch name, a tag name, or
        a 40-char commit SHA.  When an existing checkout is found it is
        verified against the pinned ref and re-cloned if it does not
        match, so a run always builds exactly the pinned version.
        """
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        url = repo_cfg["url"]
        ref = repo_cfg.get("branch", "master")

        if repo_dir.exists() and any(repo_dir.iterdir()):
            if self._at_pinned_ref(repo_dir, url, ref):
                self._clean_stale_capture_dirs(repo_dir)
                print(
                    f"[INFO] Repository already at pinned ref "
                    f"'{ref}' at {repo_dir}, skipping clone."
                )
                return str(repo_dir)
            print(
                f"[WARN] Checkout at {repo_dir} does not match "
                f"pinned ref '{ref}'; removing and re-cloning."
            )
            shutil.rmtree(repo_dir, ignore_errors=True)

        if _SHA_RE.match(ref):
            self._clone_commit(repo_name, url, ref, repo_dir)
        else:
            self._clone_ref(repo_name, url, ref, repo_dir)
        return str(repo_dir)

    def _clone_ref(self, repo_name, url, ref, repo_dir):
        """Shallow-clone a branch or tag, preferring a tag on collision."""
        self.runner.run(
            f"git clone --depth 1 "
            f"--branch {ref} {url} {repo_dir}",
            description=(
                f"Cloning {repo_name} ({ref})"
            ),
        )
        # Prefer tag over branch when both share a
        # name (avoids Maven SNAPSHOT builds)
        self.runner.run(
            f"git -C {repo_dir} fetch origin "
            f"tag {ref} --no-tags 2>/dev/null "
            f"&& git -C {repo_dir} checkout "
            f"tags/{ref} 2>/dev/null || true",
            description=(
                f"Checkout tag {ref} "
                f"(if exists)"
            ),
        )

    def _clone_commit(self, repo_name, url, sha, repo_dir):
        """Shallow-fetch and checkout an exact commit SHA.

        Used for repositories without stable release tags, which are
        pinned to a specific commit per the upstream-pinning policy.
        ``git clone --branch`` cannot check out a bare SHA, so the repo
        is initialised and the single commit is fetched directly.
        """
        repo_dir.mkdir(parents=True, exist_ok=True)
        self.runner.run(
            f"git -C {repo_dir} init -q "
            f"&& git -C {repo_dir} remote add origin {url} "
            f"&& git -C {repo_dir} fetch --depth 1 origin {sha} "
            f"&& git -C {repo_dir} checkout -q FETCH_HEAD",
            description=(
                f"Cloning {repo_name} @ {sha[:12]}"
            ),
        )

    def _at_pinned_ref(self, repo_dir, url, ref):
        """Return True if the checkout HEAD matches the pinned ref."""
        head = self.get_commit_sha(repo_dir)
        if not head:
            return False
        target = self._resolve_ref_sha(repo_dir, url, ref)
        return bool(target) and head.lower() == target.lower()

    @staticmethod
    def _resolve_ref_sha(repo_dir, url, ref):
        """Resolve a ref (commit SHA, tag, or branch) to a commit SHA.

        A 40-char SHA resolves to itself.  Tags/branches are resolved
        locally first (immutable tags are offline-safe), then via the
        remote as a fallback.  Returns the SHA, or None if unresolved.
        """
        if _SHA_RE.match(ref):
            return ref.lower()
        for spec in (f"{ref}^{{}}", ref):
            sha = RepoCloner._rev_parse(repo_dir, spec)
            if sha:
                return sha
        return RepoCloner._ls_remote_sha(url, ref)

    @staticmethod
    def _rev_parse(repo_dir, spec):
        """Locally resolve a rev spec to a 40-char SHA, or None."""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse",
                 "--verify", "--quiet", spec],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return None
        sha = result.stdout.strip()
        return sha.lower() if len(sha) == 40 else None

    @staticmethod
    def _ls_remote_sha(url, ref):
        """Resolve a ref to a commit SHA via the remote, or None.

        Prefers the peeled entry (``refs/tags/X^{}``) for annotated tags
        so the result is the underlying commit, not the tag object.
        """
        try:
            result = subprocess.run(
                ["git", "ls-remote", url,
                 f"refs/tags/{ref}", f"refs/heads/{ref}", ref],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        peeled = None
        plain = None
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            sha, name = parts
            if name.endswith("^{}"):
                peeled = sha
            elif plain is None:
                plain = sha
        return (peeled or plain or "").lower() or None

    @staticmethod
    def _clean_stale_capture_dirs(repo_dir):
        """Remove stale bisbom capture dirs from a reused checkout.

        Instrumentation artifacts (``.bisbom`` / legacy ``.omnibor``)
        must never persist into a later build: some native builds audit
        their own working tree (e.g. the Apache RAT license plugin) and
        fail on unrecognized files.  Missing dirs are ignored.
        """
        for name in _STALE_CAPTURE_DIRS:
            stale = Path(repo_dir) / name
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
                print(
                    f"[INFO] Removed stale capture dir {stale}"
                )

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
        """Build a commit URL for SPDX downloadLocation.

        Produces a browsable commit URL:
            <repo_url>/commit/<commit_sha>

        The .git suffix is stripped from the URL so the
        result is a valid browser link on GitHub/GitLab.

        Args:
            repo_url: the repository clone URL.
            commit_sha: the 40-char commit SHA.

        Returns:
            str: commit URL, or "NOASSERTION" if inputs
            are missing.
        """
        if not repo_url or not commit_sha:
            return "NOASSERTION"
        base = repo_url.removesuffix(".git")
        return f"{base}/commit/{commit_sha}"
