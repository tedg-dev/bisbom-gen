#!/usr/bin/env python3
"""
External data loader for build system indicators and dependency metadata.

Implements a fetch -> cache -> fallback pattern using the Strategy
pattern for pluggable data sources:

1. Try to load from local cached JSON files (app/data/)
2. If cache is stale, refresh from external sources:

   - Repology API for dependency -> apt package mapping
   - GitHub Linguist for build system file indicators

3. If network is unavailable, use cached data (never fail)

Cache files are JSON in app/data/ with _meta.last_updated timestamps.

Classes:

    - HttpClient: minimal HTTP transport with user-agent
    - JsonCache: atomic JSON read/write with age tracking
    - RepologyResolver: resolves library names to Debian -dev packages
    - DataLoader: main facade composing the above
"""

import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REPOLOGY_API = "https://repology.org/api/v1/project"
REPOLOGY_DEBIAN_REPOS = (
    "debian_unstable", "debian_13", "debian_14",
    "ubuntu_24_04", "ubuntu_22_04",
)


# ============================================================
# Network transport
# ============================================================

class HttpClient:
    """Minimal HTTP client with user-agent and error handling."""

    DEFAULT_USER_AGENT = (
        "bisbom-gen/0.1 "
        "(https://github.com/tedg-dev/bisbom-gen)"
    )

    def __init__(self, user_agent=None, timeout=10):
        self.user_agent = (
            user_agent or self.DEFAULT_USER_AGENT
        )
        self.timeout = timeout

    def fetch(self, url):
        """Fetch raw bytes from a URL. Returns None on failure."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.timeout
            ) as resp:
                return resp.read()
        except (
            urllib.error.URLError, OSError, TimeoutError
        ) as exc:
            logger.info(
                "Network fetch failed for %s: %s",
                url, exc,
            )
            return None

    def fetch_json(self, url):
        """Fetch and parse JSON from a URL. Returns None on failure."""
        raw = self.fetch(url)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Invalid JSON from %s: %s", url, exc
            )
            return None


# ============================================================
# JSON file cache
# ============================================================

class JsonCache:
    """Read/write JSON files with atomic writes and age tracking."""

    @staticmethod
    def read(path):
        """Read and parse a JSON file. Returns None on failure."""
        try:
            with open(
                path, "r", encoding="utf-8"
            ) as fh:
                return json.load(fh)
        except (
            OSError, json.JSONDecodeError
        ) as exc:
            logger.warning(
                "Failed to read %s: %s", path, exc
            )
            return None

    @staticmethod
    def write(path, data):
        """Write data to a JSON file atomically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            with open(
                tmp, "w", encoding="utf-8"
            ) as fh:
                json.dump(
                    data, fh,
                    indent=2, sort_keys=False,
                )
                fh.write("\n")
            tmp.replace(path)
        except OSError as exc:
            logger.warning(
                "Failed to write %s: %s", path, exc
            )
            if tmp.exists():
                tmp.unlink()

    @staticmethod
    def age_days(data):
        """Return the age of cached data in days, or None."""
        meta = (
            data.get("_meta", {}) if data else {}
        )
        ts = meta.get("last_updated")
        if not ts:
            return None
        try:
            updated = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            return (
                (now - updated).total_seconds()
                / 86400
            )
        except (ValueError, TypeError):
            return None


# ============================================================
# Repology resolver (Strategy for dependency sources)
# ============================================================

class RepologyResolver:
    """Resolves library names to Debian -dev packages via Repology."""

    def __init__(self, http=None):
        self.http = http or HttpClient(timeout=15)

    def find_dev_package(self, repology_data):
        """Extract the -dev package name from Repology project data."""
        if not isinstance(repology_data, list):
            return None

        for entry in repology_data:
            repo = entry.get("repo", "")
            if not any(
                repo.startswith(r)
                for r in REPOLOGY_DEBIAN_REPOS
            ):
                continue

            binnames = entry.get("binnames", [])
            if not binnames:
                bn = entry.get("binname")
                if bn:
                    binnames = [bn]

            for name in binnames:
                if name.endswith("-dev"):
                    return name

        return None

    def refresh_dependency(self, dep_name, dep_info):
        """Refresh a single dependency's apt package.

        Returns updated dep_info dict, or original if refresh fails.
        """
        project = dep_info.get(
            "repology_project", dep_name
        )
        url = f"{REPOLOGY_API}/{project}"
        data = self.http.fetch_json(url)
        if data is None:
            return dep_info

        dev_pkg = self.find_dev_package(data)
        if dev_pkg:
            updated = dict(dep_info)
            updated["apt_packages"] = [dev_pkg]
            return updated

        return dep_info

    def resolve_unknown(self, dep_name):
        """Resolve an unknown dependency name to a dep_info dict.

        Returns None if resolution fails.
        """
        url = f"{REPOLOGY_API}/{dep_name}"
        data = self.http.fetch_json(url)
        if data is None:
            return None

        dev_pkg = self.find_dev_package(data)
        if dev_pkg is None:
            return None

        return {
            "pkg_config": dep_name,
            "configure_flag": f"--with-{dep_name}",
            "cmake_flag": "",
            "apt_packages": [dev_pkg],
            "repology_project": dep_name,
        }


# ============================================================
# DataLoader — main public class
# ============================================================

class DataLoader:
    """Loads build system indicators and dependency metadata.

    Uses a fetch -> cache -> fallback pattern with pluggable
    resolver for external data sources.
    """

    def __init__(
        self, data_dir=None, resolver=None,
        cache=None,
    ):
        self.data_dir = data_dir or (
            Path(__file__).parent / "data"
        )
        self.build_systems_file = (
            self.data_dir / "build_systems.json"
        )
        self.dependencies_file = (
            self.data_dir / "dependencies.json"
        )
        self.resolver = resolver or RepologyResolver()
        self.cache = cache or JsonCache()

    def load_build_systems(self, refresh=False):
        """Load build system indicators.

        Returns list of (filename, system_type) tuples
        in priority order.
        """
        data = self.cache.read(
            self.build_systems_file
        )
        if data is None:
            logger.error(
                "No build_systems.json found — "
                "using empty indicator list"
            )
            return []

        indicators = data.get("indicators", [])
        return [
            (entry["file"], entry["system"])
            for entry in indicators
            if "file" in entry and "system" in entry
        ]

    def load_dependencies(self, refresh=False):
        """Load dependency metadata.

        If refresh=True and cache is stale, fetches
        from Repology.
        Returns dict mapping dep_name -> dep_info.
        """
        data = self.cache.read(
            self.dependencies_file
        )
        if data is None:
            logger.error(
                "No dependencies.json found — "
                "using empty dependency map"
            )
            return {}

        max_age = data.get(
            "_meta", {}
        ).get("cache_max_age_days", 7)

        if refresh:
            data = self.refresh_all(data, max_age)
            self.cache.write(
                self.dependencies_file, data
            )

        return data.get("libraries", {})

    def lookup_dependency(self, dep_name, deps=None):
        """Look up a single dependency by name.

        If not in the local cache, tries Repology
        on-demand and caches the result.
        """
        if deps is None:
            deps = self.load_dependencies()

        # Exact match
        if dep_name in deps:
            return deps[dep_name]

        # Case-insensitive match
        for key, val in deps.items():
            if key.lower() == dep_name.lower():
                return val

        # On-demand Repology lookup
        logger.info(
            "Dependency '%s' not in cache, "
            "querying Repology...", dep_name,
        )
        new_entry = self.resolver.resolve_unknown(
            dep_name
        )
        if new_entry is None:
            return None

        # Persist to cache
        full_data = self.cache.read(
            self.dependencies_file
        )
        if full_data and "libraries" in full_data:
            full_data["libraries"][dep_name] = (
                new_entry
            )
            self.cache.write(
                self.dependencies_file, full_data
            )

        return new_entry

    def refresh_all(self, deps_data, max_age_days=7):
        """Refresh all dependencies from Repology if stale."""
        age = self.cache.age_days(deps_data)
        if age is not None and age < max_age_days:
            logger.info(
                "Dependencies cache is %.1f days old "
                "(max %d), skipping refresh",
                age, max_age_days,
            )
            return deps_data

        logger.info(
            "Refreshing dependencies from Repology..."
        )
        libraries = deps_data.get("libraries", {})
        updated_count = 0

        for dep_name, dep_info in libraries.items():
            new_info = (
                self.resolver.refresh_dependency(
                    dep_name, dep_info
                )
            )
            if new_info is not dep_info:
                libraries[dep_name] = new_info
                updated_count += 1
            # Respect Repology rate limit: 1 req/sec
            time.sleep(1.1)

        deps_data["libraries"] = libraries
        deps_data.setdefault(
            "_meta", {}
        )["last_updated"] = (
            datetime.now(timezone.utc).isoformat()
        )

        logger.info(
            "Refreshed %d/%d dependencies",
            updated_count, len(libraries),
        )
        return deps_data


# ============================================================
# Module-level convenience (backward compatibility)
# ============================================================

_default_loader = None


def _get_loader():
    """Lazy singleton for module-level functions."""
    global _default_loader
    if _default_loader is None:
        _default_loader = DataLoader()
    return _default_loader


def load_build_systems(refresh=False):
    """Load build system indicators (module-level convenience)."""
    return _get_loader().load_build_systems(
        refresh=refresh
    )


def load_dependencies(refresh=False):
    """Load dependency metadata (module-level convenience)."""
    return _get_loader().load_dependencies(
        refresh=refresh
    )


def lookup_dependency(dep_name, deps=None):
    """Look up a dependency (module-level convenience)."""
    return _get_loader().lookup_dependency(
        dep_name, deps=deps
    )
