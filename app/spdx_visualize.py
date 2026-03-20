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
import json
import html
from collections import Counter
from pathlib import Path


def extract_graph(doc):
    """Extract nodes and edges from SPDX document.

    Returns:
        nodes: list of {id, name, version, purpose, group, fileCount}
        edges: list of {source, target, type}
        file_counts: dict of SPDXID -> count of CONTAINS relationships
    """
    pkg_map = {}
    for p in doc.get("packages", []):
        pkg_map[p["SPDXID"]] = {
            "id": p["SPDXID"],
            "name": p.get("name", "unknown"),
            "version": p.get("versionInfo", ""),
            "purpose": p.get(
                "primaryPackagePurpose", ""
            ),
            "comment": p.get("comment", ""),
            "vendored": "vendored" in p.get(
                "comment", ""
            ).lower(),
        }

    # Count CONTAINS / CONTAINED_BY relationships
    # per package (Java uses CONTAINED_BY)
    file_counts = {}
    for r in doc.get("relationships", []):
        rt = r["relationshipType"]
        if rt == "CONTAINS":
            src = r["spdxElementId"]
            file_counts[src] = (
                file_counts.get(src, 0) + 1
            )
        elif rt == "CONTAINED_BY":
            tgt = r["relatedSpdxElement"]
            file_counts[tgt] = (
                file_counts.get(tgt, 0) + 1
            )

    # Classify packages into groups
    # Relationship directions vary by type:
    #   STATIC_LINK:  root → dep (root links dep)
    #   DYNAMIC_LINK: root → lib (target = lib)
    #   BUILD_TOOL_OF: tool → root (source = tool)
    #   DEPENDS_ON:   parent → child (parent needs child)
    rels = doc.get("relationships", [])
    dynamic_nodes = set()
    build_nodes = set()
    static_nodes = set()
    depends_nodes = set()

    # Find root package (target of DESCRIBES)
    root_ids = set()
    for r in rels:
        if r["relationshipType"] == "DESCRIBES":
            root_ids.add(r["relatedSpdxElement"])
    # Fallback: APPLICATION-purpose packages
    if not root_ids:
        for p in doc.get("packages", []):
            if p.get("primaryPackagePurpose") == (
                "APPLICATION"
            ):
                root_ids.add(p["SPDXID"])

    # Build adjacency for BFS depth computation
    # parent -> [children] for dependency edges
    children_of = {}  # target -> [sources]
    for r in rels:
        rt = r["relationshipType"]
        src = r["spdxElementId"]
        tgt = r["relatedSpdxElement"]
        if rt == "DYNAMIC_LINK":
            dynamic_nodes.add(src)
            dynamic_nodes.add(tgt)
        elif rt == "BUILD_TOOL_OF":
            build_nodes.add(src)
            # Reverse for BFS: target -> tool
            children_of.setdefault(
                tgt, []
            ).append(src)
        elif rt == "DEPENDS_ON":
            depends_nodes.add(src)
            depends_nodes.add(tgt)
            # src DEPENDS_ON tgt: src -> tgt
            children_of.setdefault(
                src, []
            ).append(tgt)
        elif rt == "STATIC_LINK":
            static_nodes.add(src)
            static_nodes.add(tgt)
            # Direction varies: either
            # dep→root or root→dep.
            # Add both so BFS finds them.
            children_of.setdefault(
                tgt, []
            ).append(src)
            children_of.setdefault(
                src, []
            ).append(tgt)

    # BFS from root to compute depth
    node_depth = {}  # spdx_id -> depth
    queue = list(root_ids)
    for rid in root_ids:
        node_depth[rid] = 0
    while queue:
        current = queue.pop(0)
        cur_depth = node_depth[current]
        for child in children_of.get(
            current, []
        ):
            if child not in node_depth:
                node_depth[child] = (
                    cur_depth + 1
                )
                queue.append(child)

    # Detect Go modules by parsing comment field
    go_node_kind = {}  # spdx_id -> 'stdlib'|'direct'|'indirect'
    for spdx_id, info in pkg_map.items():
        cmt = info.get("comment", "").lower()
        if "go standard library" in cmt:
            go_node_kind[spdx_id] = "stdlib"
        elif "go module (direct)" in cmt:
            go_node_kind[spdx_id] = "direct"
        elif "go module (indirect)" in cmt:
            go_node_kind[spdx_id] = "indirect"

    # When only DEPENDS_ON exists (Go, Java), use
    # BFS depth to distinguish direct vs transitive.
    # Rust uses STATIC_LINK for all crates.
    # C/C++ uses STATIC_LINK for vendored/compiled.
    has_static = bool(static_nodes - root_ids)

    nodes = []
    for spdx_id, info in pkg_map.items():
        depth = node_depth.get(spdx_id)
        if spdx_id in root_ids:
            group = "root"
            node_type = "root"
        elif spdx_id in dynamic_nodes:
            group = "dynamic"
            node_type = "dynamic"
        elif spdx_id in build_nodes:
            if depth is not None and depth >= 2:
                group = "build_deep"
                node_type = "build_deep"
            else:
                group = "build"
                node_type = "build"
        elif spdx_id in static_nodes:
            # Color by depth but type is static
            node_type = "static"
            if info.get("vendored"):
                group = "vendored"
            elif depth is not None and depth >= 1:
                group = f"depth-{min(depth, 5)}"
            else:
                group = "depth-1"
        elif spdx_id in depends_nodes:
            # Go module type grouping
            gk = go_node_kind.get(spdx_id)
            if gk == "stdlib":
                node_type = "go_stdlib"
                group = "go_stdlib"
            elif gk == "direct":
                node_type = "go_direct"
                group = "go_direct"
            elif gk == "indirect":
                node_type = "go_indirect"
                group = "go_indirect"
            elif has_static:
                # C/C++: DEPENDS_ON = transitive
                node_type = "transitive_dep"
                if depth is not None and depth >= 1:
                    group = f"depth-{min(depth, 5)}"
                else:
                    group = "depth-1"
            elif depth is not None and depth > 1:
                # Java/other: depth > 1 = transitive
                node_type = "transitive_dep"
                if depth is not None and depth >= 1:
                    group = f"depth-{min(depth, 5)}"
                else:
                    group = "depth-1"
            else:
                # Java/other: depth 1 = direct
                node_type = "direct_dep"
                group = "depth-1"
        else:
            group = "other"
            node_type = "other"

        nodes.append({
            "id": spdx_id,
            "name": info["name"],
            "version": info["version"],
            "purpose": info["purpose"],
            "group": group,
            "node_type": node_type,
            "depth": depth if depth is not None else 0,
            "comment": info["comment"],
            "vendored": info.get("vendored", False),
            "fileCount": file_counts.get(
                spdx_id, 0
            ),
        })

    # Edges: only package-to-package (skip CONTAINS, DESCRIBES)
    edges = []
    for r in rels:
        rt = r["relationshipType"]
        src = r["spdxElementId"]
        tgt = r["relatedSpdxElement"]
        if rt in (
            "STATIC_LINK", "DYNAMIC_LINK",
            "BUILD_TOOL_OF", "DEPENDS_ON",
        ):
            if src in pkg_map and tgt in pkg_map:
                edges.append({
                    "source": src,
                    "target": tgt,
                    "type": rt,
                })

    return nodes, edges


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
    rel_counts = Counter(
        e["type"] for e in edges
    )
    # Also count CONTAINS/CONTAINED_BY from original doc
    contains_count = sum(
        1 for r in doc.get("relationships", [])
        if r["relationshipType"] in (
            "CONTAINS", "CONTAINED_BY"
        )
    )
    grp_counts = Counter(
        n["group"] for n in nodes
    )
    type_counts = Counter(
        n["node_type"] for n in nodes
    )
    vendored_count = sum(
        1 for n in nodes if n.get("vendored")
    )

    # Build conditional legend sections
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
    if type_counts.get("go_direct", 0):
        go_legend += (
            '  <div class="legend-item">\n'
            '    <div class="legend-dot" '
            'style="background:#34d399"></div>\n'
            "    <span>Go direct "
            f"({type_counts['go_direct']})"
            "</span>\n"
            "  </div>\n"
        )
    if type_counts.get("go_indirect", 0):
        go_legend += (
            '  <div class="legend-item">\n'
            '    <div class="legend-dot" '
            'style="background:#fb7185"></div>\n'
            "    <span>Go indirect "
            f"({type_counts['go_indirect']})"
            "</span>\n"
            "  </div>\n"
        )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SPDX Dependency Graph — {html.escape(doc_name)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e0e0e0;
    overflow: hidden;
  }}
  #header {{
    position: fixed; top: 0; left: 0; right: 0;
    background: rgba(15, 17, 23, 0.95);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid #2a2d35;
    padding: 12px 24px;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 24px;
  }}
  #header h1 {{
    font-size: 16px;
    font-weight: 600;
    color: #fff;
    white-space: nowrap;
  }}
  #header .meta {{
    font-size: 12px;
    color: #888;
  }}
  #legend {{
    position: fixed; top: 60px; right: 20px;
    background: rgba(22, 24, 32, 0.95);
    backdrop-filter: blur(8px);
    border: 1px solid #2a2d35;
    border-radius: 8px;
    padding: 16px;
    z-index: 100;
    font-size: 13px;
    min-width: 200px;
  }}
  #legend h3 {{
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 10px;
    color: #fff;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }}
  .legend-dot {{
    width: 12px; height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
  }}
  .legend-line {{
    width: 24px; height: 2px;
    flex-shrink: 0;
  }}
  #tooltip {{
    position: fixed;
    background: rgba(22, 24, 32, 0.97);
    border: 1px solid #3a3d45;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 13px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 200;
    max-width: 350px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
  }}
  #tooltip .tt-name {{
    font-weight: 600;
    font-size: 14px;
    color: #fff;
    margin-bottom: 4px;
  }}
  #tooltip .tt-row {{
    color: #aaa;
    margin-top: 2px;
  }}
  #tooltip .tt-row span {{
    color: #ddd;
  }}
  #graph {{ width: 100vw; height: 100vh; }}
  svg {{ display: block; }}

  /* Edge styles */
  .link-STATIC_LINK {{ stroke: #4ecdc4; }}
  .link-DYNAMIC_LINK {{ stroke: #ff6b6b; }}
  .link-BUILD_TOOL_OF {{ stroke: #ffd93d; }}
  .link-DEPENDS_ON {{ stroke: #56b6f7; }}

  /* Search box */
  #search-box {{
    position: fixed;
    top: 60px; left: 20px;
    z-index: 100;
  }}
  #search-box input {{
    background: rgba(22, 24, 32, 0.95);
    border: 1px solid #2a2d35;
    border-radius: 6px;
    padding: 8px 12px;
    color: #e0e0e0;
    font-size: 13px;
    width: 220px;
    outline: none;
  }}
  #search-box input:focus {{
    border-color: #56b6f7;
  }}
  #search-box input::placeholder {{
    color: #555;
  }}
  #search-hint {{
    font-size: 11px;
    color: #555;
    margin-top: 4px;
    padding-left: 4px;
  }}

  /* Group labels (unused, kept for potential future use) */
  .group-label {{
    font-size: 14px;
    font-weight: 600;
    fill: #333;
    text-anchor: middle;
    pointer-events: none;
  }}
</style>
</head>
<body>

<div id="header">
  <h1>SPDX Dependency Graph</h1>
  <span class="meta">{html.escape(doc_name)} &mdash; {html.escape(created)}</span>
</div>

<div id="legend">
  <h3>Packages ({len(nodes)} total)</h3>
  <div class="legend-item">
    <div class="legend-dot" style="background:#7c5cfc"></div>
    <span>Root binary ({grp_counts.get('root', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#4ecdc4"></div>
    <span>Static ({type_counts.get('static', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#4ecdc4;border:2px dashed #ff8c00"></div>
    <span>Vendored ({vendored_count})</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#ff6b6b"></div>
    <span>Dynamic / runtime ({type_counts.get('dynamic', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#ffd93d"></div>
    <span>Build tool ({type_counts.get('build', 0)})</span>
  </div>
{build_deep_legend}  <div class="legend-item">
    <div class="legend-dot" style="background:#4ecdc4"></div>
    <span>Direct dep ({type_counts.get('direct_dep', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#56b6f7"></div>
    <span>Transitive dep ({type_counts.get('transitive_dep', 0)})</span>
  </div>
{go_legend}
  <h3 style="margin-top:10px;font-size:11px;color:#888">Depth breakdown</h3>
  <div class="legend-item" style="font-size:11px;color:#999">
    <div class="legend-dot" style="background:#4ecdc4;width:8px;height:8px"></div>
    <span>Depth 1: {grp_counts.get('depth-1', 0)}</span>
  </div>
  <div class="legend-item" style="font-size:11px;color:#999">
    <div class="legend-dot" style="background:#56b6f7;width:8px;height:8px"></div>
    <span>Depth 2: {grp_counts.get('depth-2', 0)}</span>
  </div>
  <div class="legend-item" style="font-size:11px;color:#999">
    <div class="legend-dot" style="background:#a78bfa;width:8px;height:8px"></div>
    <span>Depth 3: {grp_counts.get('depth-3', 0)}</span>
  </div>
  <div class="legend-item" style="font-size:11px;color:#999">
    <div class="legend-dot" style="background:#f472b6;width:8px;height:8px"></div>
    <span>Depth 4: {grp_counts.get('depth-4', 0)}</span>
  </div>
  <div class="legend-item" style="font-size:11px;color:#999">
    <div class="legend-dot" style="background:#fb923c;width:8px;height:8px"></div>
    <span>Depth 5+: {grp_counts.get('depth-5', 0)}</span>
  </div>

  <h3 style="margin-top:14px">Relationships</h3>
  <div class="legend-item">
    <div class="legend-line" style="background:#4ecdc4"></div>
    <span>STATIC_LINK ({rel_counts.get('STATIC_LINK', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-line" style="background:#ff6b6b"></div>
    <span>DYNAMIC_LINK ({rel_counts.get('DYNAMIC_LINK', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-line" style="background:#ffd93d; height:2px; border-top:1px dashed #ffd93d; background:none;"></div>
    <span>BUILD_TOOL_OF ({rel_counts.get('BUILD_TOOL_OF', 0)})</span>
  </div>
  <div class="legend-item">
    <div class="legend-line" style="background:#56b6f7"></div>
    <span>DEPENDS_ON ({rel_counts.get('DEPENDS_ON', 0)})</span>
  </div>
  <div class="legend-item" style="margin-top:4px;color:#666;font-size:11px">
    <span>+ {contains_count} CONTAINS (source files)</span>
  </div>
</div>

<div id="tooltip">
  <div class="tt-name"></div>
  <div class="tt-details"></div>
</div>

<div id="search-box">
  <input type="text" id="search" placeholder="Search packages...">
  <div id="search-hint">Click node to highlight connections</div>
</div>

<div id="graph"></div>

<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const data = {graph_data};

const colors = {{
  root: '#7c5cfc',
  'depth-1': '#4ecdc4',
  'depth-2': '#56b6f7',
  'depth-3': '#a78bfa',
  'depth-4': '#f472b6',
  'depth-5': '#fb923c',
  go_stdlib: '#38bdf8',
  go_direct: '#34d399',
  go_indirect: '#fb7185',
  dynamic: '#ff6b6b',
  build: '#ffd93d',
  build_deep: '#e6a819',
  other: '#888',
}};

const linkColors = {{
  'STATIC_LINK': '#4ecdc4',
  'DYNAMIC_LINK': '#ff6b6b',
  'BUILD_TOOL_OF': '#ffd93d',
  'DEPENDS_ON': '#56b6f7',
}};

const width = window.innerWidth;
const height = window.innerHeight;

const svg = d3.select('#graph')
  .append('svg')
  .attr('width', width)
  .attr('height', height);

// Zoom
const g = svg.append('g');
const zoom = d3.zoom()
  .scaleExtent([0.1, 5])
  .on('zoom', (e) => g.attr('transform', e.transform));
svg.call(zoom);

// Zoom-to-fit: compute bounding box of all nodes
// and apply transform to fit within viewport
function zoomToFit(duration) {{
  const pad = 60;
  let x0 = Infinity, y0 = Infinity;
  let x1 = -Infinity, y1 = -Infinity;
  data.nodes.forEach(d => {{
    if (d.x < x0) x0 = d.x;
    if (d.y < y0) y0 = d.y;
    if (d.x > x1) x1 = d.x;
    if (d.y > y1) y1 = d.y;
  }});
  const bw = x1 - x0 || 1;
  const bh = y1 - y0 || 1;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const scale = Math.min(
    (width - pad * 2) / bw,
    (height - pad * 2) / bh,
    1.5);
  const t = d3.zoomIdentity
    .translate(width / 2, height / 2)
    .scale(scale)
    .translate(-cx, -cy);
  if (duration) {{
    svg.transition().duration(duration)
      .call(zoom.transform, t);
  }} else {{
    svg.call(zoom.transform, t);
  }}
}}

// Arrow markers
const defs = svg.append('defs');
Object.entries(linkColors).forEach(([type, color]) => {{
  defs.append('marker')
    .attr('id', 'arrow-' + type)
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 28)
    .attr('refY', 0)
    .attr('markerWidth', 8)
    .attr('markerHeight', 8)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-4L10,0L0,4')
    .attr('fill', color);
}});

// Horizontal layout: transitive left, dynamic/build center-top, static right
const xPositions = {{
  root: width / 2,
  'depth-1': width * 0.72,
  'depth-2': width * 0.38,
  'depth-3': width * 0.22,
  'depth-4': width * 0.15,
  'depth-5': width * 0.10,
  vendored: width * 0.85,
  go_stdlib: width * 0.20,
  go_direct: width * 0.72,
  go_indirect: width * 0.38,
  dynamic: width * 0.5,
  build: width * 0.5,
  build_deep: width * 0.5,
  other: width / 2,
}};

// Vertical bias: dynamic/build top, everything else center-to-below
const yPositions = {{
  root: height * 0.48,
  'depth-1': height * 0.50,
  'depth-2': height * 0.52,
  'depth-3': height * 0.54,
  'depth-4': height * 0.56,
  'depth-5': height * 0.58,
  vendored: height * 0.72,
  go_stdlib: height * 0.75,
  go_direct: height * 0.50,
  go_indirect: height * 0.52,
  dynamic: height * 0.18,
  build: height * 0.18,
  build_deep: height * 0.25,
  other: height * 0.55,
}};

const yStrengths = {{
  root: 0.08,
  'depth-1': 0.10,
  'depth-2': 0.10,
  'depth-3': 0.10,
  'depth-4': 0.10,
  'depth-5': 0.10,
  go_stdlib: 0.3,
  go_direct: 0.10,
  go_indirect: 0.10,
  dynamic: 0.5,
  build: 0.5,
  build_deep: 0.4,
  other: 0.12,
}};

// --- Build spanning tree for fan-out force ---
// For each dep node, figure out its tree parent so
// 2nd-level deps can be pushed away from root.
const nodeById = {{}};
data.nodes.forEach(d => {{ nodeById[d.id] = d; }});
const rootNode = data.nodes.find(
  d => d.group === 'root'
);
const rootId = rootNode ? rootNode.id : null;

// depsOf[X] = nodes that X depends on
// deppedBy[Y] = nodes that depend on Y
const depsOf = {{}};
const deppedBy = {{}};
data.links.forEach(l => {{
  const sid = l.source.id || l.source;
  const tid = l.target.id || l.target;
  if (l.type === 'DEPENDS_ON') {{
    if (!depsOf[sid]) depsOf[sid] = [];
    depsOf[sid].push(tid);
    if (!deppedBy[tid]) deppedBy[tid] = [];
    deppedBy[tid].push(sid);
  }} else if (l.type === 'STATIC_LINK') {{
    if (tid === rootId) {{
      if (!depsOf[tid]) depsOf[tid] = [];
      depsOf[tid].push(sid);
      if (!deppedBy[sid]) deppedBy[sid] = [];
      deppedBy[sid].push(tid);
    }} else if (sid === rootId) {{
      if (!depsOf[sid]) depsOf[sid] = [];
      depsOf[sid].push(tid);
      if (!deppedBy[tid]) deppedBy[tid] = [];
      deppedBy[tid].push(sid);
    }}
  }}
}});

// Build tree: prefer non-root parents so that
// shared deps become children of their non-root
// parent (depth 2+) instead of root (depth 1).
const treeParent = {{}};  // child -> parent id
const treeDepthMap = {{}};
const treeVisited = new Set();
if (rootId) {{
  treeVisited.add(rootId);
  treeDepthMap[rootId] = 0;
  // Phase 1: seed with root-exclusive deps
  const queue = [];
  (depsOf[rootId] || []).forEach(c => {{
    const nonRoot = (deppedBy[c] || []).filter(
      p => p !== rootId
    );
    if (nonRoot.length === 0) {{
      treeVisited.add(c);
      treeParent[c] = rootId;
      treeDepthMap[c] = 1;
      queue.push(c);
    }}
  }});
  // Phase 2: BFS from seeds
  while (queue.length) {{
    const n = queue.shift();
    (depsOf[n] || []).forEach(c => {{
      if (!treeVisited.has(c)) {{
        treeVisited.add(c);
        treeParent[c] = n;
        treeDepthMap[c] = treeDepthMap[n] + 1;
        queue.push(c);
      }}
    }});
  }}
  // Phase 3: remaining go under root
  (depsOf[rootId] || []).forEach(c => {{
    if (!treeVisited.has(c)) {{
      treeVisited.add(c);
      treeParent[c] = rootId;
      treeDepthMap[c] = 1;
      const q2 = [c];
      while (q2.length) {{
        const n2 = q2.shift();
        (depsOf[n2] || []).forEach(c2 => {{
          if (!treeVisited.has(c2)) {{
            treeVisited.add(c2);
            treeParent[c2] = n2;
            treeDepthMap[c2] = treeDepthMap[n2] + 1;
            q2.push(c2);
          }}
        }});
      }}
    }}
  }});
}}

// Collect depth-2+ nodes for fan-out
const deepNodes = data.nodes.filter(
  d => (treeDepthMap[d.id] || 0) >= 2
);
// Cache each deep node's depth-1 ancestor
const depthOneAnc = {{}};
deepNodes.forEach(d => {{
  let anc = d.id;
  while (treeDepthMap[anc] > 1 && treeParent[anc])
    anc = treeParent[anc];
  depthOneAnc[d.id] = anc;
}});

console.log('Fan-out: ' + deepNodes.length
  + ' depth-2+ nodes out of ' + data.nodes.length);
deepNodes.forEach(d => {{
  const pName = nodeById[treeParent[d.id]]
    ? nodeById[treeParent[d.id]].name : '?';
  const aName = nodeById[depthOneAnc[d.id]]
    ? nodeById[depthOneAnc[d.id]].name : '?';
  console.log('  depth=' + treeDepthMap[d.id]
    + ' ' + d.name + ' -> parent:' + pName
    + ' anchor:' + aName);
}});

// Build set of depth-2+ ids for force callbacks
const deepIdSet = new Set(
  deepNodes.map(d => d.id));

// Force simulation (original layout + fan-out)
const simulation = d3.forceSimulation(data.nodes)
  .alphaDecay(0.05)
  .force('link', d3.forceLink(data.links)
    .id(d => d.id)
    .distance(d => {{
      if (d.type === 'BUILD_TOOL_OF') return 180;
      return 140;
    }}))
  .force('charge', d3.forceManyBody()
    .strength(-600))
  // No forceCenter — forceX/forceY handle
  // centering.  forceCenter shifts centroid of
  // ALL nodes, counteracting rightward fanout.
  .force('x', d3.forceX(
    d => xPositions[d.group] || width / 2)
    .strength(d => {{
      // No X pull for depth-2+ nodes (fanout
      // controls their position instead)
      if (deepIdSet.has(d.id)) return 0;
      return 0.15;
    }}))
  .force('y', d3.forceY(
    d => yPositions[d.group] || height / 2)
    .strength(d => {{
      if (d.group === 'dynamic'
          || d.group === 'build') return 0.5;
      if (deepIdSet.has(d.id)) return 0;
      if (d.group === 'root') return 0.08;
      return 0.10;
    }}))
  .force('collision', d3.forceCollide().radius(50));

// --- Fan-out force (alpha-dependent, strong) ---
// Pushes depth-2+ nodes beyond their parent in the
// direction from root through their depth-1 ancestor.
// Scales with alpha so the sim properly settles.
if (deepNodes.length > 0 && rootNode) {{
  const fanout = function(alpha) {{
    const rx = rootNode.x, ry = rootNode.y;
    deepNodes.forEach(d => {{
      const anc = nodeById[depthOneAnc[d.id]];
      if (!anc) return;
      // Direction: root -> depth-1 ancestor
      const dx = anc.x - rx;
      const dy = anc.y - ry;
      const dist = Math.sqrt(dx*dx + dy*dy);
      if (dist < 1) return;
      const nx = dx / dist, ny = dy / dist;
      // Target: beyond parent in that direction
      const par = nodeById[treeParent[d.id]];
      if (!par) return;
      // Always push one level (160px) beyond
      // direct parent — NOT accumulated.
      const tx = par.x + nx * 160;
      const ty = par.y + ny * 160;
      // Strong alpha-dependent force
      const s = alpha * 0.8;
      d.vx += (tx - d.x) * s;
      d.vy += (ty - d.y) * s;
    }});
  }};
  fanout.initialize = function() {{}};
  simulation.force('fanout', fanout);
}}

// Links
const link = g.append('g')
  .selectAll('line')
  .data(data.links)
  .join('line')
  .attr('stroke', d => linkColors[d.type] || '#555')
  .attr('stroke-width', d => d.type === 'STATIC_LINK' ? 2 : 1.5)
  .attr('stroke-dasharray', d => d.type === 'BUILD_TOOL_OF' ? '6,4' : null)
  .attr('stroke-opacity', 0.6)
  .attr('marker-end', d => 'url(#arrow-' + d.type + ')');

// Link labels
const linkLabel = g.append('g')
  .selectAll('text')
  .data(data.links)
  .join('text')
  .attr('font-size', 9)
  .attr('fill', d => linkColors[d.type] || '#555')
  .attr('fill-opacity', 0.7)
  .attr('text-anchor', 'middle')
  .text(d => d.type.replace(/_/g, ' '));

// Nodes
const node = g.append('g')
  .selectAll('g')
  .data(data.nodes)
  .join('g')
  .call(d3.drag()
    .on('start', dragstarted)
    .on('drag', dragged)
    .on('end', dragended));

// Node circles — size by file count
node.append('circle')
  .attr('r', d => {{
    if (d.group === 'root') return 24;
    if (d.fileCount > 50) return 18;
    if (d.fileCount > 10) return 14;
    return 12;
  }})
  .attr('fill', d => colors[d.group] || colors.other)
  .attr('stroke', '#fff')
  .attr('stroke-width', d => d.group === 'root' ? 2.5 : 1.5)
  .attr('stroke-opacity', 0.3);

// Vendored indicator: orange dashed ring
node.filter(d => d.vendored)
  .append('circle')
  .attr('r', d => {{
    if (d.fileCount > 50) return 22;
    if (d.fileCount > 10) return 18;
    return 16;
  }})
  .attr('fill', 'none')
  .attr('stroke', '#ff8c00')
  .attr('stroke-width', 2)
  .attr('stroke-dasharray', '4,3')
  .attr('stroke-opacity', 0.85);

// Glow for root
node.filter(d => d.group === 'root')
  .append('circle')
  .attr('r', 32)
  .attr('fill', 'none')
  .attr('stroke', colors.root)
  .attr('stroke-width', 1)
  .attr('stroke-opacity', 0.2);

// Labels
node.append('text')
  .attr('dy', d => {{
    if (d.group === 'root') return 38;
    if (d.fileCount > 50) return 30;
    return 26;
  }})
  .attr('text-anchor', 'middle')
  .attr('font-size', d => d.group === 'root' ? 13 : 11)
  .attr('font-weight', d => d.group === 'root' ? 700 : 500)
  .attr('fill', '#e0e0e0')
  .text(d => d.name);

// Version labels
node.filter(d => d.version)
  .append('text')
  .attr('dy', d => {{
    if (d.group === 'root') return 52;
    if (d.fileCount > 50) return 43;
    return 39;
  }})
  .attr('text-anchor', 'middle')
  .attr('font-size', 10)
  .attr('fill', '#888')
  .text(d => d.version);

// File count badges
node.filter(d => d.fileCount > 0)
  .append('text')
  .attr('dy', 4)
  .attr('text-anchor', 'middle')
  .attr('font-size', 9)
  .attr('font-weight', 600)
  .attr('fill', '#fff')
  .text(d => d.fileCount);

// Tooltip
const tooltip = d3.select('#tooltip');

node.on('mouseover', (event, d) => {{
  const rows = [];
  if (d.version) rows.push('<div class="tt-row">Version: <span>' + d.version + '</span></div>');
  rows.push('<div class="tt-row">Purpose: <span>' + d.purpose + '</span></div>');
  const typeLabels = {{
    'root': 'Root binary',
    'static': 'Statically linked (compiled in)',
    'dynamic': 'Dynamically linked (runtime)',
    'build': 'Build tool',
    'build_deep': 'Build tool (transitive)',
    'direct_dep': 'Direct dependency',
    'transitive_dep': 'Transitive dependency',
    'go_stdlib': 'Go standard library (compiled in)',
    'go_direct': 'Direct Go module (compiled in)',
    'go_indirect': 'Indirect Go module (compiled in)',
    'vendored': 'Vendored (compiled in)',
    'other': 'Other',
  }};
  const typeLabel = typeLabels[d.node_type] || d.node_type;
  rows.push('<div class="tt-row">Type: <span>' + typeLabel + '</span></div>');
  const td = treeDepthMap[d.id];
  if (td !== undefined) rows.push('<div class="tt-row">Tree depth: <span>' + td + '</span></div>');
  if (d.fileCount) rows.push('<div class="tt-row">Source files: <span>' + d.fileCount + '</span></div>');
  if (d.vendored) rows.push('<div class="tt-row" style="color:#ff8c00;font-weight:600">⚠ Vendored dependency</div>');
  if (d.comment) rows.push('<div class="tt-row" style="margin-top:6px;font-size:11px;color:#777">' + d.comment + '</div>');

  tooltip.select('.tt-name').text(d.name);
  tooltip.select('.tt-details').html(rows.join(''));
  tooltip.style('opacity', 1)
    .style('left', (event.clientX + 16) + 'px')
    .style('top', (event.clientY - 10) + 'px');
}})
.on('mousemove', (event) => {{
  tooltip.style('left', (event.clientX + 16) + 'px')
    .style('top', (event.clientY - 10) + 'px');
}})
.on('mouseout', () => {{
  tooltip.style('opacity', 0);
}});

// Tick
simulation.on('tick', () => {{
  link
    .attr('x1', d => d.source.x)
    .attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x)
    .attr('y2', d => d.target.y);

  linkLabel
    .attr('x', d => (d.source.x + d.target.x) / 2)
    .attr('y', d => (d.source.y + d.target.y) / 2 - 6);

  node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
}});

simulation.on('end', () => {{
  zoomToFit(0);
}});

function dragstarted(event, d) {{
  simulation.alphaTarget(0.01).restart();
  d.fx = d.x; d.fy = d.y;
}}
function dragged(event, d) {{
  d.fx = event.x; d.fy = event.y;
}}
function dragended(event, d) {{
  simulation.alphaTarget(0);
  d.fx = null; d.fy = null;
}}

// --- Click-to-highlight subgraph ---
let selectedNode = null;

function highlightConnections(d) {{
  if (selectedNode === d) {{
    // Deselect: restore all
    selectedNode = null;
    node.style('opacity', 1);
    link.style('opacity', 0.6);
    linkLabel.style('opacity', 0.7);
    return;
  }}
  selectedNode = d;
  const connected = new Set();
  connected.add(d.id);
  data.links.forEach(l => {{
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    if (sid === d.id) connected.add(tid);
    if (tid === d.id) connected.add(sid);
  }});

  node.style('opacity', n => connected.has(n.id) ? 1 : 0.08);
  link.style('opacity', l => {{
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    return (sid === d.id || tid === d.id) ? 0.8 : 0.03;
  }});
  linkLabel.style('opacity', l => {{
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    return (sid === d.id || tid === d.id) ? 0.9 : 0.03;
  }});
}}

node.on('click', (event, d) => {{
  event.stopPropagation();
  highlightConnections(d);
}});

svg.on('click', () => {{
  selectedNode = null;
  node.style('opacity', 1);
  link.style('opacity', 0.6);
  linkLabel.style('opacity', 0.7);
}});

// --- Search/filter ---
const searchInput = document.getElementById('search');
const searchHint = document.getElementById('search-hint');

searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase().trim();
  if (!q) {{
    node.style('opacity', 1);
    link.style('opacity', 0.6);
    linkLabel.style('opacity', 0.7);
    searchHint.textContent = 'Click node to highlight connections';
    return;
  }}
  const matches = data.nodes.filter(n => n.name.toLowerCase().includes(q));
  const matchIds = new Set(matches.map(n => n.id));
  const count = matches.length;
  searchHint.textContent = count + ' match' + (count !== 1 ? 'es' : '');

  node.style('opacity', n => matchIds.has(n.id) ? 1 : 0.1);
  link.style('opacity', 0.05);
  linkLabel.style('opacity', 0.05);

  // Zoom to first match
  if (matches.length === 1) {{
    const m = matches[0];
    selectedNode = null;
    highlightConnections(m);
    const scale = 1.2;
    const t = d3.zoomIdentity
      .translate(width/2, height/2)
      .scale(scale)
      .translate(-m.x, -m.y);
    svg.transition().duration(500)
      .call(zoom.transform, t);
  }}
}});

</script>
</body>
</html>"""

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
