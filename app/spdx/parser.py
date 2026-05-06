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

    def __init__(
        self, bom_dir, repos_dir,
        go_root=None, cargo_home=None,
    ):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.go_root = go_root or "/usr/local/go"
        self.cargo_home = cargo_home or "~/.cargo"
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

        go_stdlib_prefix = f"{self.go_root}/src/"

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
            elif (
                "/.cargo/registry/src/" in fp
                or f"{self.cargo_home}/registry/" in fp
            ):
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

    def get_jar_source_files(self):
        """Return per-JAR source file mapping.

        Traces treedb: JAR → hash_tree → class files
        → hash_tree → source .java files.

        Returns dict:
          { "rel/path/to.jar": [
              {"sha1": "...", "file_path": "..."},
              ...
            ]
          }
        Only includes project JARs (under repos_dir),
        excluding test JARs.
        """
        treedb_path = (
            self.meta_dir / "bomsh_omnibor_treedb"
        )
        treedb = json.loads(treedb_path.read_text())
        repos_prefix = str(self.repos_dir)

        result = {}
        for sha1, entry in treedb.items():
            fp = entry.get("file_path", "")
            if not (
                fp.endswith(".jar")
                and fp.startswith(repos_prefix)
                and "hash_tree" in entry
                and "/test-classes/" not in fp
                and "/test/" not in fp
                and not fp.endswith("-tests.jar")
            ):
                continue

            # Relative path from repos_dir
            rel = fp[len(repos_prefix):].lstrip("/")
            sources = []
            seen = set()

            for class_sha in entry["hash_tree"]:
                if class_sha not in treedb:
                    continue
                cls = treedb[class_sha]
                cls_path = cls.get("file_path", "")

                # Trace class → source via hash_tree
                for src_sha in cls.get(
                    "hash_tree", []
                ):
                    if (
                        src_sha in treedb
                        and src_sha not in seen
                    ):
                        src = treedb[src_sha]
                        seen.add(src_sha)
                        sources.append({
                            "sha1": src_sha,
                            "file_path": src.get(
                                "file_path", ""
                            ),
                        })

                # Also include the class file itself
                if (
                    cls_path
                    and class_sha not in seen
                ):
                    seen.add(class_sha)
                    sources.append({
                        "sha1": class_sha,
                        "file_path": cls_path,
                    })

            if sources:
                result[rel] = sources

        return result

    def load_doc_mapping(self):
        """Return dict: sha1 -> omnibor_doc_id."""
        path = (
            self.meta_dir / "bomsh_omnibor_doc_mapping"
        )
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def parse_strace_openat_log(self):
        """Parse strace openat log for Java builds.

        Returns set of absolute file paths that were
        opened during the build (via openat syscalls).
        Mirrors how C/C++ uses load_raw_logfile_hashes()
        to consume tracer output.

        strace -e trace=openat format (single-thread):
          PID openat(AT_FDCWD, "/path", flags) = fd
          PID openat(AT_FDCWD, "/path", flags) = -1
        Multi-threaded (common in Java/Maven builds):
          PID openat(AT_FDCWD, "/path", flags <unfinished ...>
          PID <... openat resumed>) = fd
        We capture both completed and unfinished lines.
        For unfinished lines we include the path since
        a successful resume is likely (and the resumed
        line does not repeat the path).
        """
        log_path = (
            self.meta_dir / "strace_java_logfile"
        )
        if not log_path.exists():
            return set()

        accessed = set()
        failed = set()
        for line in log_path.read_text(
            errors="replace"
        ).splitlines():
            # Completed: PID openat(..., "/path", ...)= N
            m = re.match(
                r'^\d+\s+openat\('
                r'[^,]*,\s*"([^"]+)"'
                r'.*=\s*(\d+|-1)',
                line,
            )
            if m:
                if m.group(2) != "-1":
                    accessed.add(m.group(1))
                else:
                    failed.add(m.group(1))
                continue

            # Unfinished: PID openat(..., "/path", ... <unfinished
            m = re.match(
                r'^\d+\s+openat\('
                r'[^,]*,\s*"([^"]+)"'
                r'.*<unfinished',
                line,
            )
            if m:
                accessed.add(m.group(1))

        # Remove paths that only appeared as failures
        accessed -= failed
        return accessed

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
