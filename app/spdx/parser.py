"""
ADG Parser — reads bomsh treedb and classifies artifacts.
"""

import json
import re
from pathlib import Path

from app.spdx.identity import (
    IDENTITY_INDEX_FILENAME,
    write_identity_index,
)


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
                # Catch-all: anything not positively matched
                # above (e.g. /tmp/ build intermediates,
                # /opt/ tool files).  Allowlist above is the
                # security boundary — nothing reaches
                # project_source without a prefix match.
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
        for _sha1, entry in treedb.items():
            fp = entry.get("file_path", "")
            if not self._is_project_jar(fp, entry, repos_prefix):
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

                # Also include the class file itself,
                # but skip bomsh extraction artifacts
                # (/tmp/bomjdir/) — these are intermediate
                # paths from JAR introspection, not
                # project source files.
                if (
                    cls_path
                    and class_sha not in seen
                    and "/tmp/bomjdir/" not in cls_path
                ):
                    seen.add(class_sha)
                    sources.append({
                        "sha1": class_sha,
                        "file_path": cls_path,
                    })

            if sources:
                result[rel] = sources

        return result

    @staticmethod
    def _is_project_jar(fp, entry, repos_prefix):
        """Return True for a production project JAR entry.

        Shared predicate used by ``get_jar_source_files`` and
        ``get_jar_artifact_ids`` so both agree on which treedb
        entries are project JARs.  Excludes test JARs and any
        JAR outside the cloned repo tree.
        """
        return (
            fp.endswith(".jar")
            and fp.startswith(repos_prefix)
            and "hash_tree" in entry
            and "/test-classes/" not in fp
            and "/test/" not in fp
            and not fp.endswith("-tests.jar")
        )

    def get_jar_artifact_ids(self):
        """Return each project JAR's bomsh ``SHA-1`` treedb key.

        The treedb key of a JAR entry is that JAR's git-blob
        ``SHA-1`` -- a **topology** key only.  It is the lookup
        key into ``load_doc_mapping()`` for the JAR's bomsh
        OmniBOR document id.  It is NOT the value the SBOM
        surfaces: per the design of record
        (``project/artifact-identity.md``) the SPDX checksum is
        the artifact's raw ``SHA-256`` and its gitOID is
        ``gitoid:blob:sha256``, both computed from the artifact
        by the identity layer -- see ``persist_identity_index``
        and ``app.spdx.identity``.

        Returns dict keyed identically to
        ``get_jar_source_files`` (repo-relative JAR path):
          { "rel/path/to.jar": "<jar_sha1>" }
        """
        treedb_path = (
            self.meta_dir / "bomsh_omnibor_treedb"
        )
        treedb = json.loads(treedb_path.read_text())
        repos_prefix = str(self.repos_dir)

        result = {}
        for sha1, entry in treedb.items():
            fp = entry.get("file_path", "")
            if not self._is_project_jar(fp, entry, repos_prefix):
                continue
            rel = fp[len(repos_prefix):].lstrip("/")
            result[rel] = sha1

        return result

    def validate_jar_topology(self):
        """Report project JARs' class->source topology gaps.

        Design of record (``project/artifact-identity.md``, Java
        caveats): ``strace``-based Java capture is more fragile
        than ``bomtrace3``, so every production ``.class`` in a
        JAR should trace back to a ``.java`` source.  This
        surfaces gaps rather than emitting a silently-incomplete
        manifest.

        Returns dict: ``rel_jar_path -> {"classes": int,
        "classes_without_source": int}``.
        """
        treedb_path = (
            self.meta_dir / "bomsh_omnibor_treedb"
        )
        if not treedb_path.exists():
            return {}
        treedb = json.loads(treedb_path.read_text())
        repos_prefix = str(self.repos_dir)
        report = {}
        for _sha1, entry in treedb.items():
            fp = entry.get("file_path", "")
            if not self._is_project_jar(
                fp, entry, repos_prefix
            ):
                continue
            rel = fp[len(repos_prefix):].lstrip("/")
            classes = 0
            without_src = 0
            for class_sha in entry.get("hash_tree", []):
                cls = treedb.get(class_sha)
                if cls is None:
                    continue
                if not cls.get(
                    "file_path", ""
                ).endswith(".class"):
                    continue
                classes += 1
                has_src = any(
                    treedb.get(s, {})
                    .get("file_path", "")
                    .endswith(".java")
                    for s in cls.get("hash_tree", [])
                )
                if not has_src:
                    without_src += 1
            report[rel] = {
                "classes": classes,
                "classes_without_source": without_src,
            }
        return report

    def load_doc_mapping(self):
        """Return dict: sha1 -> omnibor_doc_id (topology only).

        The C/Rust/Go tool (``bomsh_create_bom.py``) writes
        ``bomsh_omnibor_doc_mapping``; the Java tool
        (``bomsh_create_bom_java.py``) writes
        ``bomsh_gitbom_doc_mapping``.  Both map an artifact's
        git-blob ``SHA-1`` to its bomsh OmniBOR document id
        (also ``SHA-1``).  These ``SHA-1`` values are used only
        as a topology bridge and are never surfaced in the SBOM;
        the ``SHA-256`` Input Manifest gitOID (OMID) is computed
        canonically per the OmniBOR spec (see the design of
        record, ``project/artifact-identity.md``).
        """
        for name in (
            "bomsh_omnibor_doc_mapping",
            "bomsh_gitbom_doc_mapping",
        ):
            path = self.meta_dir / name
            if path.exists():
                return json.loads(path.read_text())
        return {}

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

    def persist_identity_index(
        self, out_path=None, algo="sha256",
    ):
        """Write the Phase-1 ``SHA-256`` identity index to disk.

        Implements the topology-vs-identity split (design of
        record, ``project/artifact-identity.md``): bomsh's treedb
        gives the graph *topology* keyed by ``SHA-1``; here we
        enumerate each node's file path and hand it to the
        language-agnostic identity layer, which reads each
        artifact once and records its ``SHA-256`` raw hash +
        ``gitoid:blob:sha256``.

        This MUST run in Phase 1, while build intermediates
        (``.class`` / ``.o``) still exist, so an offline Phase 2
        (after workspace cleanup) can surface identity for files
        that no longer exist on disk.  Unreadable paths are
        skipped by the identity layer.

        Args:
            out_path: destination JSON file; defaults to
                ``<meta_dir>/<IDENTITY_INDEX_FILENAME>``.
            algo: hash algorithm (default ``sha256``).

        Returns:
            Number of artifacts written to the index (0 when the
            treedb is absent).
        """
        treedb_path = (
            self.meta_dir / "bomsh_omnibor_treedb"
        )
        if not treedb_path.exists():
            return 0
        treedb = json.loads(treedb_path.read_text())
        paths = []
        seen = set()
        for entry in treedb.values():
            fp = entry.get("file_path", "")
            if fp and fp not in seen:
                seen.add(fp)
                paths.append(fp)
        out = (
            Path(out_path) if out_path
            else self.meta_dir / IDENTITY_INDEX_FILENAME
        )
        return write_identity_index(paths, out, algo)

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
