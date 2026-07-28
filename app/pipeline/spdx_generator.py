"""
SPDX SBOM generation from OmniBOR data.

Generates SPDX SBOMs using bomsh_sbom.py, then patches the
document metadata to credit OmniBOR tools and injects
OmniBOR ExternalRefs into packages.
"""

import re
import subprocess
from pathlib import Path

from app.config import lang_subdir, timestamp
from app.runner import CommandRunner


class SpdxGenerator:
    """Generates SPDX SBOM from OmniBOR data.

    After bomsh_sbom.py writes the initial SPDX file,
    this class patches ``creationInfo.creators`` to
    credit the actual tools that produced the data:
    bomtrace3 (build interception), bomsh (ADG + SPDX
    enrichment), and bisbom-gen (orchestration).
    """

    # Bomsh install dir — used to detect git commit
    BOMSH_DIR = "/opt/bomsh"

    def __init__(self, runner=None, bomsh_dir=None):
        self.runner = runner or CommandRunner()
        if bomsh_dir:
            self.bomsh_dir = bomsh_dir
        else:
            self.bomsh_dir = self.BOMSH_DIR

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
        "https://github.com/tedg-dev/bisbom-gen"
    )

    @staticmethod
    def patch_spdx_metadata(
        spdx_path, bom_dir=None,
        vcs_uri=None,
    ):
        """Patch SPDX metadata to credit OmniBOR tools.

        1. Replaces ``documentNamespace`` with an
           OmniBOR-based URI (preserving the UUID).
        2. Adds bomtrace3, bomsh, and bisbom-gen
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
            "Tool: bisbom-gen"
            " (github.com/tedg-dev/bisbom-gen)",
        ]

        for entry in extra:
            if entry not in creators:
                creators.append(entry)

        ci["creators"] = creators

        # --- downloadLocation (VCS URI) ---
        if vcs_uri:
            for pkg in doc.get("packages", []):
                if pkg.get(
                    "downloadLocation"
                ) == "NOASSERTION":
                    pkg["downloadLocation"] = (
                        vcs_uri
                    )
                    break

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
        vcs_uri=None,
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
            / "bisbom" / lang / repo_name / ts
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
            / f"{repo_name}_bisbom.spdx.json"
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
            str(spdx_file), str(bom_dir),
            vcs_uri=vcs_uri,
        )
        print(
            f"[OK] SPDX SBOM: {spdx_file.name}"
        )

        # Rename remaining files: fix the upstream
        # ``.spdx-json`` extension and rebrand any leftover
        # upstream ``omnibor.`` filename prefix to ``bisbom.``
        # so all emitted filenames are consistent with the
        # rebranded primary (``<repo>_bisbom.spdx.json``).
        for f in generated:
            if f == primary:
                continue
            base = f.name.replace(".spdx-json", ".spdx.json")
            if base.startswith("omnibor."):
                base = "bisbom." + base[len("omnibor."):]
            new_name = f.with_name(base)
            if f.exists() and new_name != f:
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

    def generate_java(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_java_cfg,
        run_ts=None,
    ):
        """Generate SPDX SBOM for Java from bomsh_create_bom_java.py output.

        Java uses bomsh_create_bom_java.py which creates a treedb JSON
        file mapping .java -> .class -> .jar relationships. We need to
        convert this to SPDX format.

        For now, this is a placeholder that returns None — the ADG SPDX
        generator will handle Java artifacts using the treedb directly.

        Returns output file path or None.
        """
        # Java SPDX generation is handled by adg_spdx.generate()
        # which reads the bomsh_omnibor_treedb created by
        # bomsh_create_bom_java.py
        #
        # The treedb format is similar to C/C++/Rust but with
        # .java/.class file paths instead of .c/.o files.
        #
        # For now, return None — the primary SPDX comes from
        # adg_spdx.generate() which handles all languages.
        return None
