#!/usr/bin/env python3
"""
OmniBOR Analysis — Main orchestration script.

Clones a target repository, instruments the build with bomtrace3,
generates OmniBOR ADG documents and SPDX SBOMs, and produces
timestamped markdown reports.

Usage:

    python3 analyze.py --repo curl
    python3 analyze.py --repo ffmpeg
    python3 analyze.py --repo curl --skip-clone
    python3 analyze.py --list

Classes:

    - CommandRunner: wraps subprocess execution with logging
    - DependencyValidator: checks apt_deps are installed before build
    - RepoCloner: handles git clone logic
    - BomtraceBuilder: instrumented build with bomtrace3
    - SpdxGenerator: generates SPDX SBOM from OmniBOR data
    - SpdxValidator: validates SPDX v2.3 (schema + semantic)
    - SyftGenerator: generates baseline manifest SBOM via Syft
    - BinaryCollector: copies output binaries to output/binaries/<lang>/<repo>/
    - DocWriter: writes build logs and runtime metrics
    - AnalysisPipeline: facade orchestrating the full workflow
"""

import argparse
import os
import re
import subprocess
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path


# ============================================================
# Utilities
# ============================================================

def load_config(config_path=None):
    """Load config.yaml from the given path or script directory."""
    if config_path is None:
        config_path = (
            Path(__file__).parent / "config.yaml"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def timestamp():
    """Return current timestamp in configured format."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def lang_subdir(repo_cfg):
    """Return the language subfolder name from repo config.

    Used to organize output by language, e.g. c-cpp, go.
    Falls back to 'unknown' if not specified.
    """
    return repo_cfg.get("language", "unknown")


# ============================================================
# Command execution
# ============================================================

class CommandRunner:
    """Wraps subprocess execution with logging."""

    def run(self, cmd, cwd=None, description=""):
        """Run a shell command, print output, return exit code."""
        print(f"\n{'='*60}")
        print(f"  {description}")
        print(f"  CMD: {cmd}")
        print(f"  CWD: {cwd or os.getcwd()}")
        print(f"{'='*60}\n")
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(
                "[ERROR] Command exited with "
                f"code {result.returncode}"
            )
        return result.returncode


# ============================================================
# Dependency validation
# ============================================================

class DependencyValidator:
    """Checks that required apt packages are installed before build.

    Reads the apt_deps list from a repo's config entry and
    verifies each package is installed via dpkg-query.
    """

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def validate(self, repo_cfg):
        """Check all apt_deps are installed.

        Returns (ok, missing) where ok is True if all
        deps are present, and missing is a list of
        package names that are not installed.
        """
        apt_deps = repo_cfg.get("apt_deps", [])
        if not apt_deps:
            return True, []

        missing = []
        for pkg in apt_deps:
            rc = self.runner.run(
                f"dpkg-query -W -f='${{Status}}' "
                f"{pkg} 2>/dev/null "
                "| grep -q 'install ok installed'",
                description=(
                    f"Checking dependency: {pkg}"
                ),
            )
            if rc != 0:
                missing.append(pkg)

        if missing:
            print(
                f"\n[ERROR] Missing {len(missing)} "
                "required package(s):"
            )
            for pkg in missing:
                print(f"  - {pkg}")
            print(
                "\nInstall them with:\n"
                f"  apt-get install -y "
                f"{' '.join(missing)}\n"
                "\nOr add them to the Dockerfile's "
                "apt-get install list and rebuild "
                "the image.\n"
            )
            return False, missing

        print(
            f"[OK] All {len(apt_deps)} "
            "apt dependencies verified"
        )
        return True, []


# ============================================================
# Repository cloning
# ============================================================

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
        return str(repo_dir)


# ============================================================
# Bomtrace instrumented build
# ============================================================

class BomtraceBuilder:
    """Instruments the build with bomtrace and generates OmniBOR ADG.

    Works for both C/C++ (bomtrace3) and Go (bomtrace2 with
    Go-specific bomtrace.conf).  The tracer binary is specified
    in the omnibor config section passed to build().
    """

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def build(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
        run_ts=None,
    ):
        """Run pre-build steps, instrumented build, and ADG generation.

        Returns True on success, False on failure.
        """
        ts = run_ts or timestamp()
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        tracer = omnibor_cfg["tracer"]
        raw_logfile = omnibor_cfg["raw_logfile"]

        # Clean stale build artifacts so bomtrace3
        # intercepts a full recompilation.
        # Without this, a prior build leaves object
        # files in place and make becomes a no-op —
        # bomtrace3 intercepts zero compiler calls
        # and bomsh_create_bom.py has no data.
        clean_cmd = repo_cfg.get("clean_cmd")
        if clean_cmd:
            self.runner.run(
                clean_cmd, cwd=str(repo_dir),
                description=(
                    f"Clean: {clean_cmd}"
                ),
            )
            # Ignore clean_cmd exit code — it may
            # fail on a fresh clone (nothing to clean)

        # Pre-build steps (configure, etc.)
        build_steps = repo_cfg["build_steps"]
        for step in build_steps[:-1]:
            rc = self.runner.run(
                step, cwd=str(repo_dir),
                description=(
                    f"Pre-build: {step[:60]}"
                ),
            )
            if rc != 0:
                print(
                    "[ERROR] Pre-build step "
                    f"failed: {step}"
                )
                return False

        # Final build step with bomtrace3
        make_cmd = build_steps[-1]
        # Extract env var assignments (KEY=VAL) that
        # precede the actual command.  They must go
        # *before* the tracer so the shell sets them
        # for the whole pipeline; bomtrace2 cannot
        # exec "KEY=VAL" as a binary.
        env_prefix = ""
        cmd_part = make_cmd
        tokens = make_cmd.split()
        while tokens and "=" in tokens[0]:
            env_prefix += tokens.pop(0) + " "
            cmd_part = " ".join(tokens)
        instrumented = (
            f"{env_prefix}{tracer} {cmd_part}"
        )
        rc = self.runner.run(
            instrumented, cwd=str(repo_dir),
            description=(
                f"Instrumented build: "
                f"{tracer} {make_cmd[:40]}"
            ),
        )
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return False

        # Generate OmniBOR ADG documents
        create_bom = omnibor_cfg["create_bom_script"]
        rc = self.runner.run(
            f"{create_bom} -r {raw_logfile} "
            f"-b {bom_dir}",
            cwd=str(repo_dir),
            description=(
                "Generating OmniBOR ADG documents"
            ),
        )
        if rc != 0:
            print("[ERROR] ADG generation failed")
            return False

        print(
            "[OK] OmniBOR ADG documents "
            f"written to {bom_dir}"
        )
        return True


# ============================================================
# SPDX generation
# ============================================================

class SpdxGenerator:
    """Generates SPDX SBOM from OmniBOR data.

    After bomsh_sbom.py writes the initial SPDX file,
    this class patches ``creationInfo.creators`` to
    credit the actual tools that produced the data:
    bomtrace3 (build interception), bomsh (ADG + SPDX
    enrichment), and omnibor-analysis (orchestration).
    """

    # Bomsh install dir — used to detect git commit
    BOMSH_DIR = "/opt/bomsh"

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    # --------------------------------------------------
    # Version helpers
    # --------------------------------------------------

    @staticmethod
    def _bomsh_version():
        """Return bomsh version string.

        Tries ``bomsh_create_bom.py --version``, then
        falls back to the git short-rev of /opt/bomsh.
        """
        try:
            out = subprocess.check_output(
                ["bomsh_create_bom.py", "--version"],
                stderr=subprocess.STDOUT,
                text=True,
            ).strip()
            # output: "bomsh_create_bom.py 0.0.1"
            ver = out.split()[-1] if out else None
        except Exception:
            ver = None

        # Append git commit if available
        try:
            commit = subprocess.check_output(
                [
                    "git", "-C",
                    SpdxGenerator.BOMSH_DIR,
                    "rev-parse", "--short", "HEAD",
                ],
                stderr=subprocess.STDOUT,
                text=True,
            ).strip()
        except Exception:
            commit = None

        if ver and commit:
            return f"{ver}-{commit}"
        if commit:
            return f"git-{commit}"
        if ver:
            return ver
        return "unknown"

    @staticmethod
    def _bomtrace_version():
        """Return bomtrace3 version string.

        bomtrace3 has no --version flag, but the
        strace version is embedded in the binary.
        Extract it with ``strings | grep``.
        """
        import shutil

        bt = shutil.which("bomtrace3")
        if not bt:
            return "unknown"
        try:
            out = subprocess.check_output(
                ["strings", bt],
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in out.splitlines():
                line = line.strip()
                if re.match(
                    r"^\d+\.\d+(-\w+)?$", line
                ):
                    return line
        except Exception:
            pass
        return "unknown"

    # --------------------------------------------------
    # Creator patching
    # --------------------------------------------------

    # Namespace prefix for OmniBOR-generated SBOMs
    NAMESPACE_PREFIX = (
        "https://omnibor.io/omnibor-analysis"
    )

    @staticmethod
    def patch_spdx_metadata(spdx_path, bom_dir=None):
        """Patch SPDX metadata to credit OmniBOR tools.

        1. Replaces ``documentNamespace`` with an
           OmniBOR-based URI (preserving the UUID).
        2. Adds bomtrace3, bomsh, and omnibor-analysis
           to ``creationInfo.creators``.
        3. Injects OmniBOR ExternalRefs into packages
           when ``bom_dir`` is provided.

        Returns True on success, False on failure.
        """
        import json as _json

        path = Path(spdx_path)
        if not path.exists():
            return False

        try:
            doc = _json.loads(path.read_text())
        except Exception:
            return False

        ci = doc.get("creationInfo")
        if not ci or not isinstance(ci, dict):
            return False

        # --- documentNamespace ---
        old_ns = doc.get("documentNamespace", "")
        # Extract trailing UUID if present
        uuid_match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{12}",
            old_ns,
        )
        uuid_part = (
            uuid_match.group(0)
            if uuid_match
            else timestamp()
        )
        doc_name = doc.get("name", "unknown")
        doc["documentNamespace"] = (
            f"{SpdxGenerator.NAMESPACE_PREFIX}"
            f"/{doc_name}-{uuid_part}"
        )

        # --- creators ---
        creators = ci.get("creators", [])

        bomsh_ver = SpdxGenerator._bomsh_version()
        bt_ver = SpdxGenerator._bomtrace_version()

        extra = [
            f"Tool: bomtrace3-{bt_ver}",
            f"Tool: bomsh-{bomsh_ver}",
            "Tool: omnibor-analysis"
            " (github.com/tedg-dev/omnibor-analysis)",
        ]

        for entry in extra:
            if entry not in creators:
                creators.append(entry)

        ci["creators"] = creators

        # --- OmniBOR ExternalRefs ---
        if bom_dir:
            SpdxGenerator._inject_omnibor_refs(
                doc, bom_dir
            )

        path.write_text(
            _json.dumps(doc, indent=1) + "\n"
        )
        print(
            "[OK] Patched SPDX namespace: "
            + doc["documentNamespace"]
        )
        print(
            "[OK] Patched SPDX creators: "
            + ", ".join(extra)
        )
        return True

    @staticmethod
    def _inject_omnibor_refs(doc, bom_dir):
        """Inject OmniBOR ExternalRefs into SPDX packages.

        Reads the bomsh raw logfile to map binary paths
        to their build-time SHA1 hashes, then looks up
        each hash in ``bomsh_omnibor_doc_mapping`` to get
        the OmniBOR document identifier.  Adds a
        ``PERSISTENT-ID`` ExternalRef with a ``gitoid``
        locator to each matching SPDX package.

        This works around a hash mismatch where libtool
        may relink the binary after bomtrace3 records
        the hash, causing bomsh_sbom.py to fail its
        own ExternalRef injection.
        """
        import json as _json

        bom = Path(bom_dir)
        meta = bom / "metadata" / "bomsh"
        logfile = meta / "bomsh_hook_raw_logfile"
        mapping_file = (
            meta / "bomsh_omnibor_doc_mapping"
        )

        if not logfile.exists():
            return
        if not mapping_file.exists():
            return

        try:
            mapping = _json.loads(
                mapping_file.read_text()
            )
        except Exception:
            return

        # Build path→hash from raw logfile
        # Lines: "outfile: <sha1> path: <path>"
        path_to_hash = {}
        try:
            for line in logfile.read_text(
                errors="replace"
            ).splitlines():
                m = re.match(
                    r"^outfile:\s+([0-9a-f]{40})"
                    r"\s+path:\s+(.+)$",
                    line,
                )
                if m:
                    path_to_hash[m.group(2)] = (
                        m.group(1)
                    )
        except Exception:
            return

        injected = 0
        for pkg in doc.get("packages", []):
            pkg_name = pkg.get("name", "")
            # Match package name to binary basename
            for bin_path, sha1 in (
                path_to_hash.items()
            ):
                basename = Path(bin_path).name
                if basename != pkg_name:
                    continue
                omnibor_id = mapping.get(sha1)
                if not omnibor_id:
                    continue
                ref = {
                    "referenceCategory":
                        "PERSISTENT-ID",
                    "referenceType": "gitoid",
                    "referenceLocator":
                        f"gitoid:blob:sha1:"
                        f"{omnibor_id}",
                }
                refs = pkg.get("externalRefs", [])
                # Avoid duplicates
                if ref not in refs:
                    refs.append(ref)
                    pkg["externalRefs"] = refs
                    injected += 1
                break

        if injected:
            print(
                f"[OK] Injected {injected} OmniBOR "
                f"ExternalRef(s)"
            )

    # --------------------------------------------------
    # Main generate
    # --------------------------------------------------

    def generate(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
        run_ts=None,
    ):
        """Generate SPDX SBOM. Returns output file path.

        bomsh_sbom.py requires:
          -b <bom_dir>   OmniBOR ADG directory
          -F <files>     comma-separated artifact files
          -O <out_dir>   output directory for SBOMs
          -s spdx-json   SPDX JSON format
        It generates one SPDX per artifact, then we
        rename the first to our standard naming.
        """
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / lang / repo_name / ts
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        # Build comma-separated list of artifact files
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        bins = repo_cfg.get("output_binaries", [])
        artifact_paths = []
        for rel in bins:
            p = repo_dir / rel
            if p.exists():
                artifact_paths.append(str(p))
        if not artifact_paths:
            print(
                "[WARN] No output binaries found "
                "for SPDX generation"
            )
            return None

        files_arg = ",".join(artifact_paths)
        sbom_script = omnibor_cfg["sbom_script"]

        rc = self.runner.run(
            f"{sbom_script} "
            f"-b {bom_dir} "
            f"-F {files_arg} "
            f"-O {spdx_dir} "
            f"-s spdx-json "
            f"--force_insert",
            description=(
                "Generating SPDX SBOM from "
                f"{len(artifact_paths)} artifact(s)"
            ),
        )
        if rc != 0:
            print(
                "[WARN] SPDX generation may have "
                "failed — check output"
            )

        # bomsh_sbom.py writes files with .spdx-json
        # extension (e.g. omnibor.<bin>.syft.spdx-json,
        # <bin>.syft.spdx-json).  Rename ALL to use the
        # standard .spdx.json extension.
        spdx_file = (
            spdx_dir
            / f"{repo_name}_omnibor.spdx.json"
        )
        generated = sorted(spdx_dir.glob(
            "*.spdx-json"
        ))
        if not generated:
            print(
                "[WARN] No SPDX file generated by "
                "bomsh_sbom.py"
            )
            return None

        # Rename primary (first omnibor.*) to our
        # standard timestamped name
        omnibor_files = [
            f for f in generated
            if f.name.startswith("omnibor.")
        ]
        primary = (
            omnibor_files[0] if omnibor_files
            else generated[0]
        )
        primary.rename(spdx_file)
        self.patch_spdx_metadata(
            str(spdx_file), str(bom_dir)
        )
        print(
            f"[OK] SPDX SBOM: {spdx_file.name}"
        )

        # Rename remaining files: fix extension
        for f in generated:
            if f == primary:
                continue
            new_name = f.with_suffix(".json").with_suffix(
                ".spdx.json"
            )
            if f.exists():
                f.rename(new_name)
                print(
                    f"[OK] Renamed: {f.name} -> "
                    f"{new_name.name}"
                )

        # Generate HTML visualization
        try:
            import json as _viz_json
            from spdx_visualize import generate_html
            doc = _viz_json.loads(
                spdx_file.read_text()
            )
            html_path = str(
                spdx_file.with_suffix(".html")
            )
            generate_html(doc, html_path)
        except Exception as e:
            print(
                f"[WARN] Visualization failed: {e}"
            )

        return str(spdx_file)


# ============================================================
# SPDX validation
# ============================================================

class SpdxValidator:
    """Validates SPDX v2.3 JSON documents.

    Two-phase validation:
      1. JSON Schema — structural correctness against the
         official SPDX 2.3 JSON Schema.
      2. Semantic — business-rule checks via spdx-tools
         (parse + validate_full_spdx_document).

    Either phase can be skipped if its library is unavailable,
    with a warning printed instead of a hard failure.
    """

    SCHEMA_URL = (
        "https://raw.githubusercontent.com/spdx/"
        "spdx-spec/development/v2.3.1/"
        "schemas/spdx-schema.json"
    )

    def validate(self, spdx_path):
        """Run both validation phases on *spdx_path*.

        Returns a dict:
          {
            "schema_ok": bool | None,
            "semantic_ok": bool | None,
            "schema_errors": [str],
            "semantic_errors": [str],
          }
        None means the check was skipped (library missing).
        """
        result = {
            "schema_ok": None,
            "semantic_ok": None,
            "schema_errors": [],
            "semantic_errors": [],
        }

        spdx_path = Path(spdx_path)
        if not spdx_path.exists():
            print(
                f"[WARN] SPDX file not found: "
                f"{spdx_path}"
            )
            return result

        import json
        try:
            with open(spdx_path, "r") as f:
                doc_json = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"[ERROR] Cannot read SPDX JSON: {e}"
            )
            return result

        # Phase 1: JSON Schema
        result = self._validate_schema(
            doc_json, spdx_path, result
        )

        # Phase 2: Semantic (spdx-tools)
        result = self._validate_semantic(
            spdx_path, result
        )

        self._print_summary(spdx_path, result)
        return result

    def _validate_schema(
        self, doc_json, spdx_path, result
    ):
        """Validate against SPDX 2.3 JSON Schema."""
        try:
            import jsonschema
            import urllib.request
        except ImportError:
            print(
                "[WARN] jsonschema not installed — "
                "skipping JSON Schema validation"
            )
            return result

        try:
            import json
            with urllib.request.urlopen(
                self.SCHEMA_URL, timeout=30
            ) as resp:
                schema = json.loads(resp.read())
        except Exception as e:
            print(
                f"[WARN] Could not fetch SPDX schema: "
                f"{e} — skipping schema validation"
            )
            return result

        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(
            validator.iter_errors(doc_json),
            key=lambda e: list(e.absolute_path),
        )
        result["schema_errors"] = [
            f"{'.'.join(str(p) for p in e.absolute_path)}: "
            f"{e.message}"
            if e.absolute_path
            else e.message
            for e in errors
        ]
        result["schema_ok"] = len(errors) == 0
        return result

    def _validate_semantic(self, spdx_path, result):
        """Validate with spdx-tools parse + validate."""
        try:
            from spdx_tools.spdx.parser.parse_anything import (
                parse_file,
            )
            from spdx_tools.spdx.validation.document_validator import (
                validate_full_spdx_document,
            )
        except ImportError:
            print(
                "[WARN] spdx-tools not installed — "
                "skipping semantic validation"
            )
            return result

        try:
            document = parse_file(str(spdx_path))
        except Exception as e:
            result["semantic_ok"] = False
            result["semantic_errors"] = [
                f"Parse error: {e}"
            ]
            return result

        messages = validate_full_spdx_document(
            document
        )
        result["semantic_errors"] = [
            str(m.validation_message)
            for m in messages
        ]
        result["semantic_ok"] = len(messages) == 0
        return result

    @staticmethod
    def _print_summary(spdx_path, result):
        """Print human-readable validation summary."""
        name = Path(spdx_path).name
        print(
            f"\n{'='*60}\n"
            f"  SPDX Validation: {name}\n"
            f"{'='*60}"
        )

        # Schema
        if result["schema_ok"] is None:
            print("  JSON Schema:  SKIPPED")
        elif result["schema_ok"]:
            print("  JSON Schema:  PASS")
        else:
            n = len(result["schema_errors"])
            print(f"  JSON Schema:  FAIL ({n} errors)")
            for e in result["schema_errors"][:10]:
                print(f"    - {e}")
            if n > 10:
                print(f"    ... and {n - 10} more")

        # Semantic
        if result["semantic_ok"] is None:
            print("  Semantic:     SKIPPED")
        elif result["semantic_ok"]:
            print("  Semantic:     PASS")
        else:
            n = len(result["semantic_errors"])
            print(f"  Semantic:     FAIL ({n} errors)")
            for e in result["semantic_errors"][:10]:
                print(f"    - {e}")
            if n > 10:
                print(f"    ... and {n - 10} more")

        print(f"{'='*60}\n")


# ============================================================
# Syft baseline SBOM
# ============================================================

class SyftGenerator:
    """Generates a baseline manifest SBOM using Syft."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def generate(self, repo_name, repo_cfg,
                 paths_cfg, run_ts=None):
        """Generate Syft SBOM. Returns output file path."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / lang / repo_name / ts
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        spdx_file = (
            spdx_dir
            / f"{repo_name}_syft.spdx.json"
        )

        rc = self.runner.run(
            f"syft dir:{repo_dir} "
            f"-o spdx-json={spdx_file}",
            description=(
                "Generating Syft manifest SBOM: "
                f"{spdx_file.name}"
            ),
        )
        if rc != 0:
            print(
                "[WARN] Syft SBOM generation "
                "may have failed"
            )
        return str(spdx_file)


# ============================================================
# Metadata collection (per-binary)
# ============================================================

class MetadataCollector:
    """Collect component metadata and dynamic lib info.

    Runs after the instrumented build to gather:
    1. component_metadata.json — dpkg metadata for all
       system files found in the bomsh treedb
    2. dynamic_libs.json — per-binary dynamic library
       dependencies with dpkg metadata

    Both outputs are consumed by AdgSpdxStep.
    """

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def collect(
        self, repo_name, repo_cfg, paths_cfg,
        run_ts=None,
    ):
        """Collect metadata and dynamic libs.

        Returns True if at least component_metadata.json
        was created successfully.
        """
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        meta_dir = bom_dir / "metadata"
        repos_dir = paths_cfg["repos_dir"]
        repo_dir = Path(repos_dir) / repo_name

        treedb_path = (
            meta_dir / "bomsh"
            / "bomsh_omnibor_treedb"
        )
        if not treedb_path.exists():
            print(
                "[WARN] treedb not found — "
                "skipping metadata collection"
            )
            return False

        # Step 1: collect_metadata.py (once)
        meta_out = meta_dir / "component_metadata.json"
        if not meta_out.exists():
            print(
                "\n"
                + "=" * 60
                + "\n"
                "  Collecting component metadata\n"
                + "=" * 60
            )
            try:
                from collect_metadata import (
                    main as collect_meta,
                )
                collect_meta(
                    str(treedb_path),
                    repos_dir,
                    str(meta_dir),
                )
            except Exception as e:
                print(
                    f"[ERROR] collect_metadata failed: "
                    f"{e}"
                )
                return False

        # Step 2: collect_dynamic_libs.py (per binary)
        bins = repo_cfg.get("output_binaries", [])
        for rel_path in bins:
            bin_name = Path(rel_path).name
            bin_path = repo_dir / rel_path
            if not bin_path.exists():
                print(
                    f"[WARN] Binary not found: "
                    f"{bin_path}"
                )
                continue

            # Per-binary metadata dir
            bin_meta = meta_dir / bin_name
            dynlib_out = bin_meta / "dynamic_libs.json"
            if dynlib_out.exists():
                continue

            bin_meta.mkdir(parents=True, exist_ok=True)
            # Copy component_metadata.json to per-binary
            # dir so AdgSpdxStep can find it
            if meta_out.exists():
                import shutil
                comp_dst = (
                    bin_meta
                    / "component_metadata.json"
                )
                if not comp_dst.exists():
                    shutil.copy2(
                        str(meta_out), str(comp_dst),
                    )

            print(
                f"\n  Collecting dynamic libs: "
                f"{bin_name}"
            )
            try:
                from collect_dynamic_libs import (
                    main as collect_dynlibs,
                )
                collect_dynlibs(
                    str(bin_path), str(bin_meta),
                )
            except Exception as e:
                print(
                    f"[ERROR] collect_dynamic_libs "
                    f"failed for {bin_name}: {e}"
                )

        return meta_out.exists()


# ============================================================
# ADG SPDX generation (per-binary)
# ============================================================

class AdgSpdxStep:
    """Generate per-binary SPDX SBOMs from ADG data.

    Wraps spdx_from_adg.AdgSpdxGenerator to produce one
    SPDX 2.3 JSON file per output binary. Runs inside the
    container where source file paths match the treedb,
    enabling vendored dependency version detection.
    """

    @staticmethod
    def generate(repo_name, repo_cfg, paths_cfg,
                 run_ts=None):
        """Generate ADG SPDX for each output binary.

        Returns list of output file paths.
        """
        from spdx_from_adg import AdgSpdxGenerator

        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        repos_dir = paths_cfg["repos_dir"]
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / lang / repo_name / ts
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        bins = repo_cfg.get("output_binaries", [])
        if not bins:
            print(
                "[WARN] No output_binaries for "
                f"ADG SPDX: {repo_name}"
            )
            return []

        gen = AdgSpdxGenerator(
            bom_dir=str(bom_dir),
            repos_dir=repos_dir,
            repo_name=repo_name,
            vendored_dirs=repo_cfg.get(
                "vendored_dirs"
            ),
        )

        results = []
        for rel_path in bins:
            bin_name = Path(rel_path).name
            out_path = (
                spdx_dir
                / f"{bin_name}_adg.spdx.json"
            )
            # Use direct-only for binaries that
            # link against a shared lib also in
            # the output list (e.g. curl links
            # libcurl.so — transitive deps belong
            # to libcurl's SBOM).
            has_shared_lib = any(
                b != rel_path
                and (".so" in b or ".so." in b)
                for b in bins
            )
            is_app = (
                ".so" not in rel_path
                and ".so." not in rel_path
            )
            direct_only = (
                has_shared_lib and is_app
            )

            # Per-binary dynlib dir if it exists
            dynlib_dir = (
                bom_dir / "metadata" / bin_name
            )
            dl_dir = (
                str(dynlib_dir)
                if dynlib_dir.is_dir()
                else None
            )

            result = gen.generate(
                output_path=str(out_path),
                binary_name=bin_name,
                dynlib_dir=dl_dir,
                direct_only=direct_only,
            )
            if result:
                results.append(result)

        return results


# ============================================================
# Binary collector
# ============================================================

class BinaryCollector:
    """Copies output binaries from the build tree into
    output/binaries/<lang>/<repo>/<timestamp>/ so each run is
    preserved in a datetime-stamped folder.

    Uses the ``output_binaries`` list from config.yaml,
    which contains paths relative to the repo root
    (e.g. ``src/.libs/curl``).
    """

    @staticmethod
    def collect(repo_name, repo_cfg, paths_cfg,
                run_ts=None):
        """Copy each listed binary to a timestamped dir.

        Returns a list of (src, dst) tuples for binaries
        that were successfully copied.
        """
        import shutil

        ts = run_ts or timestamp()
        bins = repo_cfg.get("output_binaries", [])
        if not bins:
            print(
                "[WARN] No output_binaries defined "
                f"for {repo_name}"
            )
            return []

        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        lang = lang_subdir(repo_cfg)
        out_dir = (
            Path(paths_cfg["output_dir"])
            / "binaries" / lang / repo_name / ts
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        collected = []
        for rel_path in bins:
            src = repo_dir / rel_path
            dst = out_dir / Path(rel_path).name
            if not src.exists():
                print(
                    f"[WARN] Binary not found: {src}"
                )
                continue
            shutil.copy2(str(src), str(dst))
            size = dst.stat().st_size
            print(
                f"[OK] Collected {dst.name} "
                f"({size:,} bytes)"
            )
            collected.append((str(src), str(dst)))

        if collected:
            print(
                f"[OK] {len(collected)} binary(ies) "
                f"saved to {out_dir}"
            )
        else:
            print(
                f"[WARN] No binaries found for "
                f"{repo_name}"
            )
        return collected


# ============================================================
# Documentation writer
# ============================================================

class DocWriter:
    """Writes build logs and runtime metrics."""

    @staticmethod
    def write_build_doc(
        repo_name, repo_cfg,
        paths_cfg, success, duration_sec,
        run_ts=None,
    ):
        """Write build log to docs/<lang>/<repo>/<ts>/."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        docs_dir = (
            Path(paths_cfg["docs_dir"])
            / lang / repo_name / ts
        )
        docs_dir.mkdir(parents=True, exist_ok=True)
        doc_path = docs_dir / "build.md"

        status = "SUCCESS" if success else "FAILED"
        content = (
            f"# Build Log — {repo_name}\n\n"
            f"**Date:** {datetime.now().isoformat()}\n"
            f"**Status:** {status}\n"
            f"**Duration:** {duration_sec:.1f}"
            " seconds\n\n"
            "## Repository\n\n"
            f"- **URL:** {repo_cfg['url']}\n"
            f"- **Branch:** "
            f"{repo_cfg.get('branch', 'master')}\n"
            f"- **Description:** "
            f"{repo_cfg.get('description', 'N/A')}"
            "\n\n"
            "## Build Steps\n\n"
        )
        for i, step in enumerate(
            repo_cfg["build_steps"], 1
        ):
            content += f"{i}. `{step}`\n"

        lang = lang_subdir(repo_cfg)
        if lang == "c-cpp":
            content += (
                "\n## Instrumentation\n\n"
                "- **Tracer:** bomtrace3\n"
                "- **Raw logfile:** "
                "/tmp/bomsh_hook_raw_logfile"
                ".sha1\n"
            )
        else:
            content += (
                "\n## Instrumentation\n\n"
                "- **Tracer:** bomtrace2 "
                "(Go-specific conf)\n"
                "- **Raw logfile:** "
                "/tmp/bomsh_hook_raw_logfile"
                ".sha1\n"
                "- **Watched tools:** "
                "compile, link\n"
            )

        content += (
            "\n## Output Binaries\n\n"
        )
        for binary in repo_cfg.get(
            "output_binaries", []
        ):
            content += f"- `{binary}`\n"

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(f"[OK] Build doc written to {doc_path}")
        return str(doc_path)

    @staticmethod
    def write_runtime_doc(
        repo_name, repo_cfg, paths_cfg,
        duration_sec, baseline_sec=None,
        run_ts=None,
    ):
        """Write runtime performance metrics."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        runtime_dir = (
            Path(paths_cfg["docs_dir"])
            / "runtime" / lang / repo_name / ts
        )
        runtime_dir.mkdir(
            parents=True, exist_ok=True
        )
        doc_path = (
            runtime_dir / "runtime.md"
        )

        overhead_pct = ""
        if baseline_sec and baseline_sec > 0:
            pct = (
                (duration_sec - baseline_sec)
                / baseline_sec * 100
            )
            overhead_pct = (
                f"\n**Bomtrace3 overhead:** "
                f"{pct:.1f}%"
            )

        if lang == "c-cpp":
            build_label = "Instrumented build time"
            notes = (
                "- Measured wall-clock time for the "
                "instrumented `make` step only\n"
                "- Baseline (uninstrumented) build "
                "time should be recorded separately "
                "for comparison\n"
            )
        else:
            build_label = "Instrumented build time"
            notes = (
                "- Measured wall-clock time for "
                "bomtrace2-instrumented "
                "`go build -a`\n"
                "- OmniBOR ADG + SPDX generated "
                "from build interception\n"
                "- Syft manifest SBOM also "
                "generated from go.mod/go.sum\n"
            )

        content = (
            f"# Runtime Metrics — {repo_name}\n\n"
            f"**Date:** "
            f"{datetime.now().isoformat()}\n"
            f"**{build_label}:** "
            f"{duration_sec:.1f} seconds\n"
            f"{overhead_pct}\n\n"
            "## Notes\n\n"
            f"{notes}"
        )

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(
            f"[OK] Runtime doc written to {doc_path}"
        )
        return str(doc_path)


# ============================================================
# Facade: AnalysisPipeline
# ============================================================

class AnalysisPipeline:
    """Orchestrates the full OmniBOR analysis workflow.

    Composes CommandRunner, RepoCloner,
    BomtraceBuilder, SpdxGenerator, MetadataCollector,
    AdgSpdxStep, SpdxValidator, SyftGenerator,
    BinaryCollector, and DocWriter.
    """

    def __init__(
        self,
        runner=None,
        validator=None,
        cloner=None,
        builder=None,
        spdx_gen=None,
        metadata_collector=None,
        adg_spdx=None,
        spdx_validator=None,
        syft_gen=None,
        binary_collector=None,
        doc_writer=None,
    ):
        self.runner = runner or CommandRunner()
        self.validator = (
            validator
            or DependencyValidator(self.runner)
        )
        self.cloner = cloner or RepoCloner(
            self.runner
        )
        self.builder = builder or BomtraceBuilder(
            self.runner
        )
        self.spdx_gen = spdx_gen or SpdxGenerator(
            self.runner
        )
        self.metadata_collector = (
            metadata_collector
            or MetadataCollector(self.runner)
        )
        self.adg_spdx = (
            adg_spdx or AdgSpdxStep()
        )
        self.spdx_validator = (
            spdx_validator or SpdxValidator()
        )
        self.syft_gen = syft_gen or SyftGenerator(
            self.runner
        )
        self.binary_collector = (
            binary_collector or BinaryCollector()
        )
        self.docs = doc_writer or DocWriter()

    @staticmethod
    def list_repos(config):
        """List available repositories from config."""
        print("\nAvailable repositories:\n")
        for name, cfg in config["repos"].items():
            desc = cfg.get(
                "description", "No description"
            )
            print(f"  {name:12s}  {desc}")
            print(f"               {cfg['url']}")
            print()


# ============================================================
# CLI entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "OmniBOR Analysis — Build interception "
            "and SBOM generation"
        )
    )
    parser.add_argument(
        "--repo",
        help="Repository name from config.yaml",
    )
    parser.add_argument(
        "--skip-clone", action="store_true",
        help="Skip cloning (repo already exists)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available repositories",
    )
    parser.add_argument(
        "--syft-only", action="store_true",
        help=(
            "Only generate Syft manifest SBOM "
            "(no build)"
        ),
    )
    args = parser.parse_args()

    config = load_config()
    pipeline = AnalysisPipeline()

    if args.list:
        pipeline.list_repos(config)
        return

    if not args.repo:
        print(
            "[ERROR] --repo is required. "
            "Use --list to see options."
        )
        sys.exit(1)

    if args.repo not in config["repos"]:
        print(
            f"[ERROR] Unknown repo '{args.repo}'. "
            "Use --list to see options."
        )
        sys.exit(1)

    repo_cfg = config["repos"][args.repo]
    paths_cfg = config["paths"]
    omnibor_cfg = config["omnibor"]

    # Single timestamp for the entire run — all
    # output folders use this consistently:
    #   output/binaries/{lang}/{repo}/{run_ts}/
    #   output/spdx/{lang}/{repo}/{run_ts}/
    #   output/omnibor/{lang}/{repo}/{run_ts}/
    #   docs/{lang}/{repo}/{run_ts}/
    #   docs/runtime/{lang}/{repo}/{run_ts}/
    run_ts = timestamp()

    print(f"\n{'#'*60}")
    print(f"  OmniBOR Analysis: {args.repo}")
    desc = repo_cfg.get("description", "")
    print(f"  {desc}")
    print(f"{'#'*60}\n")

    lang = lang_subdir(repo_cfg)

    # Step 1: Clone
    if not args.skip_clone:
        pipeline.cloner.clone(
            args.repo, repo_cfg, paths_cfg
        )

    # Step 2: Syft SBOM (manifest-based — works for
    # all languages; primary SBOM for Go repos)
    pipeline.syft_gen.generate(
        args.repo, repo_cfg, paths_cfg,
        run_ts=run_ts,
    )

    if args.syft_only:
        print(
            "\n[DONE] Syft-only mode — "
            "skipping build."
        )
        return

    # -------------------------------------------------
    # Language-specific pipeline branch
    # -------------------------------------------------
    if lang == "c-cpp":
        success, duration = _run_c_cpp_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    else:
        omnibor_go_cfg = config["omnibor_go"]
        success, duration = _run_go_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_go_cfg, run_ts,
        )

    # Step 8: Write docs (all languages)
    pipeline.docs.write_build_doc(
        args.repo, repo_cfg, paths_cfg,
        success, duration,
        run_ts=run_ts,
    )
    pipeline.docs.write_runtime_doc(
        args.repo, repo_cfg, paths_cfg,
        duration, run_ts=run_ts,
    )

    status = "COMPLETE" if success else "FAILED"
    print(f"\n{'#'*60}")
    print(f"  Analysis {status}: {args.repo}")
    print(f"  Duration: {duration:.1f}s")
    print(f"{'#'*60}\n")


def _run_c_cpp_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
):
    """C/C++ pipeline: apt validation, bomtrace3 build,
    OmniBOR SPDX, metadata, ADG SPDX, validation,
    binary collection.

    Returns (success, duration_sec).
    """
    # Step 3: Validate apt dependencies
    deps_ok, missing = (
        pipeline.validator.validate(repo_cfg)
    )
    if not deps_ok:
        print(
            "[ERROR] Cannot proceed — "
            f"{len(missing)} missing package(s). "
            "Add them to the Dockerfile and "
            "rebuild the image."
        )
        sys.exit(1)

    # Step 4: Instrumented build
    start = time.time()
    success = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
        run_ts=run_ts,
    )
    duration = time.time() - start

    # Step 5a: Generate SPDX from OmniBOR
    spdx_file = None
    if success:
        spdx_file = pipeline.spdx_gen.generate(
            repo_name, repo_cfg,
            paths_cfg, omnibor_cfg,
            run_ts=run_ts,
        )

    # Step 5b: Collect component metadata + dynamic libs
    if success:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 5c: Generate per-binary ADG SPDX
    adg_files = []
    if success:
        adg_files = pipeline.adg_spdx.generate(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 6: Validate SPDX documents
    if spdx_file:
        pipeline.spdx_validator.validate(spdx_file)
    for adg_file in adg_files:
        pipeline.spdx_validator.validate(adg_file)

    # Step 7: Collect output binaries
    if success:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    return success, duration


def _run_go_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
):
    """Go pipeline: bomtrace2 instrumented build,
    OmniBOR ADG, SPDX generation, metadata, ADG SPDX,
    validation, binary collection.

    Uses bomtrace2 with a Go-specific bomtrace.conf
    that watches the Go compiler tools (compile, link)
    and traces the openat syscall.  ``go build -a`` is
    required to bypass the Go build cache so bomtrace2
    captures all compilation steps.

    See: https://github.com/omnibor/bomsh
    #software-vulnerability-cve-search-for-golang-packages

    Returns (success, duration_sec).
    """
    # Step 4: Instrumented build (bomtrace2)
    start = time.time()
    success = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_go_cfg,
        run_ts=run_ts,
    )
    duration = time.time() - start

    # Step 5a: Generate SPDX from OmniBOR
    spdx_file = None
    if success:
        spdx_file = pipeline.spdx_gen.generate(
            repo_name, repo_cfg,
            paths_cfg, omnibor_go_cfg,
            run_ts=run_ts,
        )

    # Step 5b: Collect component metadata
    if success:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 5c: Generate per-binary ADG SPDX
    adg_files = []
    if success:
        adg_files = pipeline.adg_spdx.generate(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 6: Validate SPDX documents
    if spdx_file:
        pipeline.spdx_validator.validate(spdx_file)
    for adg_file in adg_files:
        pipeline.spdx_validator.validate(adg_file)

    # Also validate Syft SPDX
    lang = lang_subdir(repo_cfg)
    syft_spdx = (
        Path(paths_cfg["output_dir"])
        / "spdx" / lang / repo_name / run_ts
        / f"{repo_name}_syft.spdx.json"
    )
    if syft_spdx.exists():
        pipeline.spdx_validator.validate(
            str(syft_spdx)
        )

    # Step 7: Collect output binaries
    if success:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    return success, duration


if __name__ == "__main__":
    main()
