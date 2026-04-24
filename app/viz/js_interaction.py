"""JavaScript template for D3 graph interaction and rendering.

Generates the JS code for: link/node rendering, tooltips, tick handler,
drag handlers, click-to-highlight, and search functionality.
"""


def get_js_interaction():
    """Return the JS code for rendering and user interaction."""
    return r"""
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
    .clickDistance(5)
    .on('start', dragstarted)
    .on('drag', dragged)
    .on('end', dragended));

// Node circles — size by file count
node.append('circle')
  .attr('r', d => {
    if (d.group === 'root') return 24;
    if (d.fileCount > 50) return 18;
    if (d.fileCount > 10) return 14;
    return 12;
  })
  .attr('fill', d => colors[d.group] || colors.other)
  .attr('stroke', '#fff')
  .attr('stroke-width', d => d.group === 'root' ? 2.5 : 1.5)
  .attr('stroke-opacity', 0.3);

// Vendored indicator: orange dashed ring
node.filter(d => d.vendored)
  .append('circle')
  .attr('r', d => {
    if (d.fileCount > 50) return 22;
    if (d.fileCount > 10) return 18;
    return 16;
  })
  .attr('fill', 'none')
  .attr('stroke', '#ff8c00')
  .attr('stroke-width', 2)
  .attr('stroke-dasharray', '4,3')
  .attr('stroke-opacity', 0.85);

// Sibling module indicator: purple double ring
node.filter(d => d.sibling)
  .append('circle')
  .attr('r', d => {
    if (d.fileCount > 50) return 22;
    if (d.fileCount > 10) return 18;
    return 16;
  })
  .attr('fill', 'none')
  .attr('stroke', '#7c3aed')
  .attr('stroke-width', 3)
  .attr('stroke-opacity', 0.9);

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
  .attr('dy', d => {
    if (d.group === 'root') return 38;
    if (d.fileCount > 50) return 30;
    return 26;
  })
  .attr('text-anchor', 'middle')
  .attr('font-size', d => d.group === 'root' ? 13 : 11)
  .attr('font-weight', d => d.group === 'root' ? 700 : 500)
  .attr('fill', '#e0e0e0')
  .text(d => d.name);

// Version labels
node.filter(d => d.version)
  .append('text')
  .attr('dy', d => {
    if (d.group === 'root') return 52;
    if (d.fileCount > 50) return 43;
    return 39;
  })
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

node.on('mouseover', (event, d) => {
  const rows = [];
  if (d.version) rows.push('<div class="tt-row">Version: <span>' + d.version + '</span></div>');
  rows.push('<div class="tt-row">Purpose: <span>' + d.purpose + '</span></div>');
  const typeLabels = {
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
  };
  const typeLabel = typeLabels[d.node_type] || d.node_type;
  rows.push('<div class="tt-row">Type: <span>' + typeLabel + '</span></div>');
  const td = treeDepthMap[d.id];
  if (td !== undefined) rows.push('<div class="tt-row">Tree depth: <span>' + td + '</span></div>');
  if (d.fileCount) rows.push('<div class="tt-row">Source files: <span>' + d.fileCount + '</span></div>');
  if (d.vendored) rows.push('<div class="tt-row" style="color:#ff8c00;font-weight:600">\u26a0 Vendored dependency</div>');
  if (d.comment) rows.push('<div class="tt-row" style="margin-top:6px;font-size:11px;color:#777">' + d.comment + '</div>');

  tooltip.select('.tt-name').text(d.name);
  tooltip.select('.tt-details').html(rows.join(''));
  tooltip.style('opacity', 1)
    .style('left', (event.clientX + 16) + 'px')
    .style('top', (event.clientY - 10) + 'px');
})
.on('mousemove', (event) => {
  tooltip.style('left', (event.clientX + 16) + 'px')
    .style('top', (event.clientY - 10) + 'px');
})
.on('mouseout', () => {
  tooltip.style('opacity', 0);
});

// Tick
simulation.on('tick', () => {
  link
    .attr('x1', d => d.source.x)
    .attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x)
    .attr('y2', d => d.target.y);

  linkLabel
    .attr('x', d => (d.source.x + d.target.x) / 2)
    .attr('y', d => (d.source.y + d.target.y) / 2 - 6);

  node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
});

let initialFitDone = false;
simulation.on('end', () => {
  if (!initialFitDone) {
    initialFitDone = true;
    zoomToFit(0);
  }
  // Pin every node so clicks/hovers never cause drift
  pinAllNodes();
});

function dragstarted(event, d) {
  // All nodes stay pinned — only dragged node moves
  d.fx = d.x; d.fy = d.y;
}
function dragged(event, d) {
  d.fx = event.x; d.fy = event.y;
  // Update position directly for immediate visual feedback
  d.x = event.x; d.y = event.y;
  d3.select(this).attr('transform', 'translate(' + d.x + ',' + d.y + ')');
  // Update links connected to this node
  link.filter(l => l.source === d || l.target === d)
    .attr('x1', l => l.source.x).attr('y1', l => l.source.y)
    .attr('x2', l => l.target.x).attr('y2', l => l.target.y);
  linkLabel.filter(l => l.source === d || l.target === d)
    .attr('x', l => (l.source.x + l.target.x) / 2)
    .attr('y', l => (l.source.y + l.target.y) / 2 - 6);
}
function dragended(event, d) {
  // Pin dragged node at new position
  d.fx = d.x; d.fy = d.y;
  // Unpin all descendants of the dragged node (BFS)
  const adj = {};  // parent -> [children]
  data.links.forEach(l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    if (sid !== tid) {
      if (!adj[sid]) adj[sid] = [];
      adj[sid].push(tid);
      // STATIC_LINK reverse: child -> parent
      if (l.type === 'STATIC_LINK') {
        if (!adj[tid]) adj[tid] = [];
        adj[tid].push(sid);
      }
    }
  });
  const desc = new Set();
  const queue = [d.id];
  while (queue.length) {
    const cur = queue.shift();
    (adj[cur] || []).forEach(nid => {
      if (!desc.has(nid) && nid !== d.id) {
        desc.add(nid);
        queue.push(nid);
      }
    });
  }
  desc.forEach(nid => {
    const n = nodeById[nid];
    if (n) { n.fx = null; n.fy = null; }
  });
  simulation.alpha(0.15).restart();
  // Let it cool down; sim 'end' re-pins all
  setTimeout(() => simulation.alphaTarget(0), 400);
}

// --- Click-to-highlight subgraph ---
let selectedNode = null;

function highlightConnections(d) {
  if (selectedNode === d) {
    // Deselect: restore all
    selectedNode = null;
    node.style('opacity', 1);
    link.style('opacity', 0.6);
    linkLabel.style('opacity', 0.7);
    return;
  }
  selectedNode = d;
  const connected = new Set();
  connected.add(d.id);
  data.links.forEach(l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    if (sid === d.id) connected.add(tid);
    if (tid === d.id) connected.add(sid);
  });

  node.style('opacity', n => connected.has(n.id) ? 1 : 0.08);
  link.style('opacity', l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    return (sid === d.id || tid === d.id) ? 0.8 : 0.03;
  });
  linkLabel.style('opacity', l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source;
    const tid = typeof l.target === 'object' ? l.target.id : l.target;
    return (sid === d.id || tid === d.id) ? 0.9 : 0.03;
  });
}

node.on('click', (event, d) => {
  event.stopPropagation();
  highlightConnections(d);
});

svg.on('click', () => {
  selectedNode = null;
  node.style('opacity', 1);
  link.style('opacity', 0.6);
  linkLabel.style('opacity', 0.7);
});

// --- Search/filter ---
const searchInput = document.getElementById('search');
const searchHint = document.getElementById('search-hint');

searchInput.addEventListener('input', () => {
  const q = searchInput.value.toLowerCase().trim();
  if (!q) {
    node.style('opacity', 1);
    link.style('opacity', 0.6);
    linkLabel.style('opacity', 0.7);
    searchHint.textContent = 'Click node to highlight connections';
    return;
  }
  const matches = data.nodes.filter(n => n.name.toLowerCase().includes(q));
  const matchIds = new Set(matches.map(n => n.id));
  const count = matches.length;
  searchHint.textContent = count + ' match' + (count !== 1 ? 'es' : '');

  node.style('opacity', n => matchIds.has(n.id) ? 1 : 0.1);
  link.style('opacity', 0.05);
  linkLabel.style('opacity', 0.05);

  // Zoom to first match
  if (matches.length === 1) {
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
  }
});
"""
