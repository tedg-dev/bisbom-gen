"""
GitHub API client — encapsulates all gh CLI / GitHub API calls.
"""

import base64
import json
import re
import subprocess


class GitHubClient:
    """Encapsulates all GitHub API interactions via gh CLI."""

    def api(self, endpoint):
        """Call the GitHub API via gh CLI. Returns parsed JSON."""
        result = subprocess.run(
            ["gh", "api", endpoint, "--paginate"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def search_repos(self, query):
        """Search GitHub for repos by name. Returns top result."""
        fields = (
            "fullName,description,url,"
            "stargazersCount,defaultBranch,language"
        )
        result = subprocess.run(
            [
                "gh", "search", "repos", query,
                "--limit", "5", "--json", fields,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(
                "[ERROR] gh search failed: "
                f"{result.stderr.strip()}"
            )
            return None
        try:
            repos = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        if not repos:
            print(
                "[ERROR] No repositories found "
                f"for '{query}'"
            )
            return None

        c_langs = ("c", "c++", "")
        c_repos = [
            r for r in repos
            if r.get(
                "language", ""
            ).lower() in c_langs
        ]
        candidates = c_repos if c_repos else repos

        for r in candidates:
            name = (
                r["fullName"].split("/")[-1].lower()
            )
            if name == query.lower():
                return r

        return sorted(
            candidates,
            key=lambda r: r.get(
                "stargazersCount", 0
            ),
            reverse=True,
        )[0]

    def get_repo_info(self, name_or_url):
        """Get repository info. Accepts name, owner/repo, or URL."""
        full_name = self.parse_github_url(
            name_or_url
        )

        if full_name:
            data = self.api(f"repos/{full_name}")
            if data:
                return self._normalize(data)
        elif "/" in name_or_url:
            data = self.api(f"repos/{name_or_url}")
            if data:
                return self._normalize(data)

        return self.search_repos(name_or_url)

    def get_file_tree(self, full_name, branch):
        """Get the file tree (top-level + src/ + lib/ + auto/)."""
        contents = self.api(
            f"repos/{full_name}"
            f"/contents?ref={branch}"
        )
        if not contents:
            return []

        files = [item["name"] for item in contents]

        for subdir in ("src", "lib", "auto"):
            url = (
                f"repos/{full_name}"
                f"/contents/{subdir}"
                f"?ref={branch}"
            )
            sub = self.api(url)
            if sub and isinstance(sub, list):
                for item in sub:
                    files.append(
                        f"{subdir}/{item['name']}"
                    )

        return files

    def get_file_content(
        self, full_name, path, branch
    ):
        """Fetch a file's content (base64-decoded)."""
        url = (
            f"repos/{full_name}/contents/{path}"
            f"?ref={branch}"
        )
        data = self.api(url)
        if not data or "content" not in data:
            return None
        try:
            return base64.b64decode(
                data["content"]
            ).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None

    def get_languages(self, full_name):
        """Get language byte counts from GitHub API."""
        return self.api(
            f"repos/{full_name}/languages"
        )

    @staticmethod
    def parse_github_url(url_or_name):
        """Parse a GitHub URL into owner/repo, or return None."""
        match = re.search(
            r"github\.com[:/]([^/]+)/([^/.]+)",
            url_or_name,
        )
        if match:
            return (
                f"{match.group(1)}/{match.group(2)}"
            )
        return None

    @staticmethod
    def _normalize(data):
        """Convert GitHub API repo response to info dict."""
        return {
            "fullName": data["full_name"],
            "description": data.get(
                "description", ""
            ),
            "url": data["html_url"],
            "stargazersCount": data.get(
                "stargazers_count", 0
            ),
            "defaultBranch": data.get(
                "default_branch", "main"
            ),
            "language": data.get("language", ""),
        }
