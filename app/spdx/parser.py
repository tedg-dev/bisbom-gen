"""
ADG Parser — reads bomsh treedb and classifies artifacts.
"""

import json
import re
from pathlib import Path


class AdgParser:
    """Parse bomsh treedb and classify artifacts.

    Artifact categories:
      - system_lib: shared libraries under /usr/lib
      - system_header: headers under /usr/include
      - project_source: files under the project repo
      - build_intermediate: .o files under the project repo
      - crt_object: C runtime objects (crt*.o)
    """

    def __init__(self, bom_dir, repos_dir):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.meta_dir = (
            self.bom_dir / "metadata" / "bomsh"
        )

    def parse(self):
        """Return classified artifacts dict.

        Keys: system_lib, system_header,
              project_source, build_intermediate,
              crt_object.
        Each value is a list of dicts with keys:
          sha1, file_path, build_cmd (if present).
        """
        treedb_path = (
            self.meta_dir / "bomsh_omnibor_treedb"
        )
        treedb = json.loads(treedb_path.read_text())

        classified = {
            "system_lib": [],
            "system_header": [],
            "project_source": [],
            "build_intermediate": [],
            "crt_object": [],
            "go_stdlib": [],
        }

        go_stdlib_prefix = "/usr/local/go/src/"

        for sha1, entry in treedb.items():
            fp = entry.get("file_path", "")
            if not fp:
                continue

            item = {
                "sha1": sha1,
                "file_path": fp,
            }
            if "build_cmd" in entry:
                item["build_cmd"] = entry["build_cmd"]

            if fp.startswith(go_stdlib_prefix):
                classified["go_stdlib"].append(item)
            elif fp.startswith("/usr/lib"):
                base = Path(fp).name
                if base.startswith("crt") and (
                    base.endswith(".o")
                ):
                    classified["crt_object"].append(
                        item
                    )
                elif base.endswith(".so") or (
                    ".so." in base
                ):
                    classified["system_lib"].append(
                        item
                    )
                else:
                    # Static libs, other objects
                    classified["system_lib"].append(
                        item
                    )
            elif fp.startswith("/usr/include"):
                classified["system_header"].append(
                    item
                )
            elif fp.startswith(str(self.repos_dir)):
                if fp.endswith(".o"):
                    classified[
                        "build_intermediate"
                    ].append(item)
                else:
                    classified[
                        "project_source"
                    ].append(item)
            elif "/.cargo/registry/src/" in fp:
                # Rust crate sources from Cargo registry
                classified[
                    "project_source"
                ].append(item)
            else:
                # Other system files (incl. /tmp/go-build)
                classified["system_header"].append(
                    item
                )

        return classified

    def load_doc_mapping(self):
        """Return dict: sha1 -> omnibor_doc_id."""
        path = (
            self.meta_dir / "bomsh_omnibor_doc_mapping"
        )
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def load_raw_logfile_hashes(self):
        """Return dict: file_path -> build-time sha1."""
        path = (
            self.meta_dir / "bomsh_hook_raw_logfile"
        )
        if not path.exists():
            return {}
        result = {}
        for line in path.read_text(
            errors="replace"
        ).splitlines():
            m = re.match(
                r"^outfile:\s+([0-9a-f]{40})"
                r"\s+path:\s+(.+)$",
                line,
            )
            if m:
                result[m.group(2)] = m.group(1)
        return result
