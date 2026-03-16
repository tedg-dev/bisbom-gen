"""Collect dynamic library dependencies from a binary.

Runs inside the build container. Uses ldd and readelf to identify
all dynamically linked libraries, distinguishes direct (NEEDED)
from transitive, and resolves each to its dpkg package with
full metadata.

Outputs dynamic_libs.json alongside the treedb.
"""
import json
import os
import re
import subprocess


def main(binary_path, out_dir):
    # Get ldd output
    ldd_out = subprocess.check_output(
        ["ldd", binary_path], text=True
    )

    # Get NEEDED (direct deps)
    readelf_out = subprocess.check_output(
        ["readelf", "-d", binary_path], text=True
    )
    needed = set()
    for line in readelf_out.splitlines():
        m = re.search(r"NEEDED.*\[(.+)\]", line)
        if m:
            needed.add(m.group(1))

    print(f"Direct NEEDED: {sorted(needed)}")

    # Parse ldd output
    libs = {}
    not_found = set()
    for line in ldd_out.strip().splitlines():
        line = line.strip()
        m = re.match(r"(\S+)\s+=>\s+(\S+)\s+\(", line)
        if m:
            soname = m.group(1)
            path = m.group(2)
            is_direct = soname in needed
            libs[soname] = {
                "path": path, "direct": is_direct,
            }
        elif "not found" in line:
            m_nf = re.match(r"(\S+)\s+=>", line)
            if m_nf:
                not_found.add(m_nf.group(1))
        elif "ld-linux" in line:
            m2 = re.match(r"(\S+)\s+\(", line)
            if m2:
                libs["ld-linux"] = {
                    "path": m2.group(1),
                    "direct": False,
                }

    direct_count = sum(
        1 for v in libs.values() if v["direct"]
    )
    trans_count = len(libs) - direct_count
    print(
        f"Total: {len(libs)} "
        f"(direct: {direct_count}, "
        f"transitive: {trans_count})"
    )

    # Resolve each to dpkg package
    fields = [
        "Package", "Version", "Source",
        "Maintainer", "Homepage", "Architecture",
    ]
    fmt = "|".join(
        ["${" + f + "}" for f in fields]
    )

    results = {}
    for soname, info in sorted(libs.items()):
        real_path = os.path.realpath(info["path"])
        pkg = None
        # Try real path first, then original path
        for try_path in [real_path, info["path"]]:
            try:
                dpkg_out = subprocess.check_output(
                    ["dpkg", "-S", try_path],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                pkg = (
                    dpkg_out.split(":")[0]
                    .split(",")[0].strip()
                )
                if pkg:
                    break
            except Exception:
                continue

        meta = {}
        if pkg:
            try:
                out = subprocess.check_output(
                    ["dpkg-query", "-W", "-f", fmt, pkg],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                parts = out.split("|")
                for i, f in enumerate(fields):
                    if i < len(parts) and parts[i]:
                        meta[f] = parts[i]
            except Exception:
                pass

        source = meta.get("Source", pkg or soname)
        results[soname] = {
            "path": info["path"],
            "real_path": real_path,
            "direct": info["direct"],
            "dpkg_package": pkg,
            "source": source,
            "metadata": meta,
        }
        tag = "DIRECT" if info["direct"] else "transitive"
        ver = meta.get("Version", "?")
        print(f"  {soname:40s} {tag:12s} {source} ({ver})")

    # Record project-built .so files that ldd
    # could not resolve (e.g. libavcodec.so.62
    # built by FFmpeg). These are NEEDED entries
    # that show as "not found" in ldd output.
    project_built_libs = {}
    for soname in sorted(not_found):
        is_direct = soname in needed
        # Derive a readable name from soname:
        # libavcodec.so.62 -> libavcodec
        name = re.sub(r"\.so(\.\d+)*$", "", soname)
        project_built_libs[soname] = {
            "name": name,
            "direct": is_direct,
            "project_built": True,
        }
        tag = (
            "DIRECT" if is_direct
            else "transitive"
        )
        print(
            f"  {soname:40s} {tag:12s} "
            f"{name} (project-built)"
        )

    if project_built_libs:
        print(
            f"Project-built libs: "
            f"{len(project_built_libs)}"
        )

    output = {
        "binary": binary_path,
        "direct_needed": sorted(needed),
        "dynamic_libs": results,
        "project_built_libs": project_built_libs,
    }

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dynamic_libs.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description=(
            "Collect dynamic library dependencies"
            " from a binary"
        ),
    )
    ap.add_argument(
        "binary",
        help="Path to the binary to analyze",
    )
    ap.add_argument(
        "out_dir",
        help="Output directory for dynamic_libs.json",
    )
    args = ap.parse_args()
    main(args.binary, args.out_dir)
