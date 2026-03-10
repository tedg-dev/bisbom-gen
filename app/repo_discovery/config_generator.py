"""
Config generation and persistence — generates and writes config.yaml entries.
"""

import yaml
from pathlib import Path


class ConfigGenerator:
    """Generates and writes config.yaml entries."""

    def __init__(self, config_path=None):
        self.config_path = config_path or (
            Path(__file__).parent / "config.yaml"
        )

    def generate_entry(
        self, repo_info, build_steps,
        output_binaries, description,
        apt_deps=None,
    ):
        """Generate the YAML config entry as a dict."""
        entry = {
            "url": (
                "https://github.com/"
                f"{repo_info['fullName']}.git"
            ),
            "branch": repo_info["defaultBranch"],
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

