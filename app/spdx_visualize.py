#!/usr/bin/env python3
"""Generate an interactive HTML dependency graph from an SPDX JSON file.

Reads an SPDX 2.3 JSON document and produces a standalone HTML file
with a D3.js force-directed graph, color-coded by relationship type:
  - STATIC_LINK (vendored/compiled-in)
  - DYNAMIC_LINK (runtime shared libraries)
  - BUILD_TOOL_OF (compiler/toolchain)
  - CONTAINS (source files, shown as counts)

Usage:
    python3 spdx_visualize.py input.spdx.json [-o output.html]
"""

import argparse
import html
import json
from collections import Counter
from pathlib import Path

from app.viz.extract import extract_graph  # noqa: F401
from app.viz.html_parts import (
    get_header_html,
    get_legend_html,
    get_ui_html,
)
from app.viz.js_interaction import get_js_interaction
from app.viz.js_simulation import get_js_simulation
from app.viz.styles import get_css


def _build_conditional_legends(type_counts):
    """Build conditional legend HTML for build_deep and Go types."""
    build_deep_legend = ""
    if type_counts.get("build_deep", 0):
        build_deep_legend = (
            '  <div class="legend-item">\n'
            '    <div class="legend-dot" '
            'style="background:#e6a819"></div>\n'
            "    <span>Build tool chain "
            f"({type_counts['build_deep']})"
            "</span>\n"
            "  </div>\n"
        )
    go_legend = ""
    if type_counts.get("go_stdlib", 0):
        go_legend += (
            '  <div class="legend-item">\n'
            '    <div class="legend-dot" '
            'style="background:#38bdf8"></div>\n'
            "    <span>Go stdlib "
            f"({type_counts['go_stdlib']})"
            "</span>\n"
            "  </div>\n"
        )
    return build_deep_legend, go_legend


def generate_html(doc, output_path):
    """Generate standalone HTML visualization."""
    nodes, edges = extract_graph(doc)

    doc_name = doc.get("name", "SPDX Document")
    created = doc.get(
        "creationInfo", {}
    ).get("created", "")

    graph_data = json.dumps({
        "nodes": nodes,
        "links": edges,
    })

    # Compute counts for legend
    grp_counts = Counter(
        n["group"] for n in nodes
    )
    type_counts = Counter(
        n["node_type"] for n in nodes
    )
    vendored_count = sum(
        1 for n in nodes if n.get("vendored")
    )

    build_deep_legend, go_legend = (
        _build_conditional_legends(type_counts)
    )

    # Assemble HTML from sub-modules
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" '
        'content="width=device-width, '
        'initial-scale=1.0">',
        "<title>SPDX Dependency Graph "
        f"— {html.escape(doc_name)}</title>",
        "<style>",
        get_css(),
        "</style>",
        "</head>",
        "<body>",
        "",
        get_header_html(doc_name, created),
        "",
        get_legend_html(
            nodes, edges, doc,
            type_counts, grp_counts,
            vendored_count,
            build_deep_legend, go_legend,
        ),
        "",
        get_ui_html(),
        "",
        '<script src='
        '"https://d3js.org/d3.v7.min.js">'
        "</script>",
        "<script>",
        f"const data = {graph_data};",
        get_js_simulation(),
        get_js_interaction(),
        "</script>",
        "</body>",
        "</html>",
    ]
    html_content = "\n".join(parts)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content)
    print(f"[OK] Visualization: {out}")
    print(
        f"     {len(nodes)} packages, "
        f"{len(edges)} relationships"
    )
    return str(out)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Generate interactive HTML dependency "
            "graph from SPDX JSON"
        ),
    )
    ap.add_argument(
        "input",
        help="Path to SPDX 2.3 JSON file",
    )
    ap.add_argument(
        "-o", "--output",
        default=None,
        help=(
            "Output HTML file path "
            "(default: <input>.html)"
        ),
    )
    args = ap.parse_args()

    doc = json.loads(Path(args.input).read_text())

    output = args.output
    if not output:
        inp = Path(args.input)
        output = str(
            inp.parent / (inp.stem + ".html")
        )

    generate_html(doc, output)


if __name__ == "__main__":
    main()
