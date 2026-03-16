"""
AdgSpdxGenerator — facade orchestrating ADG-to-SPDX pipeline.
"""

import json
from pathlib import Path

from app.spdx.parser import AdgParser
from app.spdx.resolver import ComponentResolver
from app.spdx.emitter import SpdxEmitter


class AdgSpdxGenerator:
    """Facade: generate per-binary SPDX from ADG data.

    Orchestrates AdgParser, ComponentResolver, and
    SpdxEmitter to produce one SPDX 2.3 JSON file per
    binary (e.g. curl, libcurl.so).
    """

    def __init__(
        self, bom_dir, repos_dir, repo_name,
        bomtrace_version="unknown",
        bomsh_version="unknown",
        vendored_dirs=None,
    ):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.repo_name = repo_name
        self.bomtrace_version = bomtrace_version
        self.bomsh_version = bomsh_version
        self.vendored_dirs = vendored_dirs

    def generate(
        self, output_path,
        binary_name=None,
        dynlib_dir=None,
        direct_only=False,
        static_only=False,
    ):
        """Generate SPDX for a single binary.

        Args:
            output_path: where to write the SPDX JSON
            binary_name: name of the binary
                (e.g. "curl" or "libcurl.so");
                defaults to repo_name
            dynlib_dir: path to directory containing
                dynamic_libs.json for this binary;
                defaults to bom_dir/metadata
            direct_only: if True, include only direct
                dependencies. Use when transitive deps
                belong to a downstream binary's SBOM.
            static_only: if True, omit dynamically
                linked library packages.

        Returns the output path on success, None on
        failure.
        """
        bin_name = binary_name or self.repo_name

        # Parse ADG for OmniBOR data
        parser = AdgParser(
            self.bom_dir, self.repos_dir
        )
        classified = parser.parse()
        doc_mapping = parser.load_doc_mapping()
        logfile_hashes = (
            parser.load_raw_logfile_hashes()
        )

        go_stdlib_count = len(
            classified.get("go_stdlib", [])
        )
        extra = (
            f", Go stdlib: {go_stdlib_count}"
            if go_stdlib_count
            else ""
        )
        print(
            f"[{bin_name}] Source files: "
            f"{len(classified['project_source'])}, "
            f"Build intermediates: "
            f"{len(classified['build_intermediate'])}"
            f"{extra}"
        )

        # Load component metadata
        meta_path = (
            self.bom_dir / "metadata"
            / "component_metadata.json"
        )
        if not meta_path.exists():
            print(
                "[ERROR] component_metadata.json "
                "not found. Run collect_metadata.py "
                "first."
            )
            return None

        resolver = ComponentResolver(str(meta_path))

        # Load dynamic library data
        dl_dir = Path(
            dynlib_dir
            if dynlib_dir
            else self.bom_dir / "metadata"
        )
        dynlib_path = dl_dir / "dynamic_libs.json"
        if not dynlib_path.exists():
            print(
                f"[ERROR] {dynlib_path} not found. "
                f"Run collect_dynamic_libs.py for "
                f"{bin_name} first."
            )
            return None

        resolver.load_dynamic_libs(
            str(dynlib_path)
        )
        components = (
            resolver.resolve_dynamic_components()
        )

        direct = sum(
            1 for c in components if c["direct"]
        )
        trans = len(components) - direct
        print(
            f"[{bin_name}] Dynamic libraries: "
            f"{len(components)} components "
            f"({direct} direct, "
            f"{trans} transitive)"
        )

        # Emit SPDX
        emitter = SpdxEmitter(
            repo_name=self.repo_name,
            repo_version=resolver.repo_version,
            distro=resolver.distro,
            gcc_version=resolver.gcc_version,
            bomtrace_version=self.bomtrace_version,
            bomsh_version=self.bomsh_version,
            binary_name=bin_name,
            vendored_dirs=self.vendored_dirs,
            repos_dir=self.repos_dir,
        )

        doc = emitter.emit(
            components=components,
            project_files=(
                classified["project_source"]
            ),
            doc_mapping=doc_mapping,
            logfile_hashes=logfile_hashes,
            direct_only=direct_only,
            static_only=static_only,
            go_stdlib=classified.get("go_stdlib"),
        )

        # Write output
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(doc, indent=2) + "\n"
        )

        pkg_count = len(doc["packages"])
        file_count = len(doc["files"])
        rel_count = len(doc["relationships"])
        print(
            f"[OK] {bin_name} SPDX: {out.name} "
            f"({pkg_count} packages, "
            f"{file_count} files, "
            f"{rel_count} relationships)"
        )

        # Generate HTML visualization
        try:
            from spdx_visualize import generate_html
            html_path = str(
                out.with_suffix(".html")
            )
            generate_html(doc, html_path)
        except Exception as e:
            print(
                f"[WARN] Visualization failed: {e}"
            )

        return str(out)
