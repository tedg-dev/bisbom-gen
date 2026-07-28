"""
Config generation and persistence — generates and writes config.yaml entries.
"""

import yaml
from pathlib import Path


class ConfigGenerator:
    """Generates and writes config.yaml entries."""

    # Maps the build-system names emitted by BuildSystemDetector to a
    # generic build_profile (tool, extra traits). Kept here so /add-repo
    # produces schema-valid profiles that load_config will accept.
    _SYSTEM_TO_PROFILE = {
        "autoconf": ("autotools", []),
        "configure-only": ("autotools", []),
        "cmake": ("cmake", []),
        "meson": ("meson", []),
        "perl-configure": ("make", ["perl-configure"]),
        "auto-configure": ("make", ["auto-configure"]),
        "make-only": ("make", []),
    }

    def __init__(self, config_path=None):
        self.config_path = config_path or (
            Path(__file__).parent / "config.yaml"
        )

    @classmethod
    def build_profile_for(cls, build_system):
        """Return a schema-valid build_profile for a detected system.

        Unknown systems fall back to ``make`` with a ``needs-review``
        trait so the generated entry loads but is clearly flagged for
        the reviewer.
        """
        tool, traits = cls._SYSTEM_TO_PROFILE.get(
            build_system, ("make", ["needs-review"])
        )
        profile = {
            "tool": tool,
            "structure": "single-module",
        }
        if traits:
            profile["traits"] = list(traits)
        return profile

    def generate_entry(
        self, repo_info, build_steps,
        output_binaries, description,
        apt_deps=None, build_profile=None,
    ):
        """Generate the YAML config entry as a dict."""
        entry = {
            "url": (
                "https://github.com/"
                f"{repo_info['fullName']}.git"
            ),
            "branch": repo_info["defaultBranch"],
            "build_profile": (
                build_profile
                if build_profile is not None
                else self.build_profile_for("unknown")
            ),
            "build_steps": build_steps,
            "clean_cmd": "make clean",
            "description": description,
            "output_binaries": output_binaries,
        }
        if apt_deps:
            entry["apt_deps"] = sorted(apt_deps)
        return entry

    def write_entry(self, repo_name, entry):
        """Append the repo entry to config.yaml."""
        with open(
            self.config_path, "r", encoding="utf-8"
        ) as f:
            config = yaml.safe_load(f)

        if repo_name in config.get("repos", {}):
            print(
                f"[WARN] '{repo_name}' already in "
                "config.yaml — overwriting"
            )

        config["repos"][repo_name] = entry

        with open(
            self.config_path, "w", encoding="utf-8"
        ) as f:
            yaml.dump(
                config, f,
                default_flow_style=False,
                sort_keys=False, width=120,
            )

        print(
            f"[OK] Written to {self.config_path}"
        )

    @staticmethod
    def create_output_dirs(repo_name):
        """Create the output directory structure."""
        base = Path(__file__).parent.parent
        dirs = [
            base / "output" / "omnibor" / repo_name,
            base / "output" / "spdx" / repo_name,
            base / "output" / "binary-scan"
            / repo_name,
            base / "docs" / repo_name,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            print(f"  [DIR] {d}")

    @staticmethod
    def get_repo_stats(full_name, github):
        """Get lines of code estimate from GitHub."""
        data = github.get_languages(full_name)
        if not data:
            return ""
        total_bytes = sum(data.values())
        loc_k = total_bytes / 40 / 1000
        top_langs = sorted(
            data.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        lang_str = ", ".join(
            lang for lang, _ in top_langs
        )
        return f"~{loc_k:.0f}K LoC, {lang_str}"
