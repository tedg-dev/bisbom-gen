"""HTML fragments for the SPDX dependency graph visualization.

Generates the header, legend, tooltip, and search UI components.
"""

import html as html_mod


def get_header_html(doc_name, created):
    """Return the HTML header bar."""
    return (
        '<div id="header">\n'
        "  <h1>SPDX Dependency Graph</h1>\n"
        f'  <span class="meta">'
        f"{html_mod.escape(doc_name)} &mdash; "
        f"{html_mod.escape(created)}</span>\n"
        "</div>"
    )


def get_legend_html(
    nodes, edges, doc,
    type_counts, grp_counts,
    vendored_count,
    build_deep_legend, go_legend,
):
    """Return the legend panel HTML."""
    from collections import Counter

    rel_counts = Counter(e["type"] for e in edges)
    contains_count = sum(
        1 for r in doc.get("relationships", [])
        if r["relationshipType"] in (
            "CONTAINS", "CONTAINED_BY"
        )
    )

    return f"""<div id="legend">
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
    <div class="legend-dot" style="background:#888;border:2px dashed #ff8c00"></div>
    <span>Vendored ({vendored_count})</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#c084fc;box-shadow:0 0 0 2px #fff, 0 0 0 4px #7c3aed"></div>
    <span>Sibling module ({type_counts.get('sibling', 0)})</span>
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
</div>"""


def get_ui_html():
    """Return the tooltip, search box, and graph container HTML."""
    return """<div id="tooltip">
  <div class="tt-name"></div>
  <div class="tt-details"></div>
</div>

<div id="search-box">
  <input type="text" id="search" placeholder="Search packages...">
  <div id="search-hint">Click node to highlight connections</div>
</div>

<div id="graph"></div>"""
