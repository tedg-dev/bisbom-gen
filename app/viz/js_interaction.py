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

// CVE indicator: red diamond on nodes with vulnerabilities
// Diamond color = worst severity found on node:
//   Critical → red, High → orange, Medium → yellow,
//   Low → blue, Negligible/Unknown → gray
const cveSeverityColor = {
  'Critical': '#dc2626',
  'High': '#ea580c',
  'Medium': '#eab308',
  'Low': '#2563eb',
  'Negligible': '#6b7280',
  'Unknown': '#6b7280',
};
function worstSeverity(cves) {
  const order = ['Critical','High','Medium','Low','Negligible','Unknown'];
  let best = 99;
  cves.forEach(c => {
    const idx = order.indexOf(c.severity);
    if (idx >= 0 && idx < best) best = idx;
  });
  return order[best] || 'Unknown';
}
const cveNodes = node.filter(d => d.cves && d.cves.length > 0);
cveNodes.append('path')
  .attr('d', d3.symbol().type(d3.symbolDiamond).size(120))
  .attr('transform', d => {
    const r = d.group === 'root' ? 24 : (d.fileCount > 50 ? 18 : (d.fileCount > 10 ? 14 : 12));
    return 'translate(' + (r + 4) + ',' + (-r + 2) + ')';
  })
  .attr('fill', d => cveSeverityColor[worstSeverity(d.cves)] || '#dc2626')
  .attr('stroke', '#fff')
  .attr('stroke-width', 1)
  .attr('class', 'cve-indicator')
  .style('cursor', 'pointer');

// CVE tooltip (hover) — quick summary on mouseover
const cveTip = d3.select('#cve-tooltip');
cveNodes.selectAll('.cve-indicator')
  .on('mouseover', (event, d) => {
    const lines = d.cves.map(c =>
      '<div class="cve-row">'
      + '<span class="cve-sev cve-sev-' + c.severity.toLowerCase() + '">'
      + c.severity + '</span> '
      + '<span class="cve-id">' + c.id + '</span>'
      + '</div>'
    );
    cveTip.select('.cve-title').text(
      d.cves.length + ' CVE' + (d.cves.length > 1 ? 's' : '')
      + ' \u2014 ' + d.name + ' ' + (d.version || '')
    );
    cveTip.select('.cve-list').html(lines.join(''));
    cveTip.style('opacity', 1)
      .style('left', (event.clientX + 16) + 'px')
      .style('top', (event.clientY - 10) + 'px');
  })
  .on('mousemove', (event) => {
    cveTip.style('left', (event.clientX + 16) + 'px')
      .style('top', (event.clientY - 10) + 'px');
  })
  .on('mouseout', () => {
    cveTip.style('opacity', 0);
  });

// ── CVE disposition panel ─────────────────────────────
// localStorage key derived from document title
const lsKey = 'cve-disp-' + (document.title || 'spdx');

function loadDispositions() {
  try {
    return JSON.parse(localStorage.getItem(lsKey)) || {};
  } catch(e) { return {}; }
}
function saveDispositions(d) {
  localStorage.setItem(lsKey, JSON.stringify(d));
}
let dispositions = loadDispositions();

const cvePanel = document.getElementById('cve-panel');
const cvePanelTitle = document.getElementById('cve-panel-title');
const cvePanelBody = document.getElementById('cve-panel-body');
const cvePanelStatus = document.getElementById('cve-panel-status');

function nvdUrl(id) {
  if (id.startsWith('CVE-'))
    return 'https://nvd.nist.gov/vuln/detail/' + id;
  return 'https://github.com/advisories/' + id;
}

function openCvePanel(d) {
  cveTip.style('opacity', 0);
  cvePanelTitle.textContent =
    d.cves.length + ' CVE' + (d.cves.length > 1 ? 's' : '')
    + ' \u2014 ' + d.name + ' ' + (d.version || '');

  const pkgKey = d.name + '@' + (d.version || '');
  const sorted = [...d.cves].sort((a,b) => {
    const order = ['Critical','High','Medium','Low','Negligible','Unknown'];
    return order.indexOf(a.severity) - order.indexOf(b.severity);
  });

  cvePanelBody.innerHTML = sorted.map(c => {
    const dk = pkgKey + '/' + c.id;
    const saved = dispositions[dk] || {};
    const disp = saved.status || '';
    const just = saved.justification || '';
    const justVisible = disp && disp !== 'affected' ? 'visible' : '';
    return '<div class="cve-panel-row" data-key="' + dk + '">'
      + '<div class="cve-panel-id">'
      + '<span class="cve-sev cve-sev-' + c.severity.toLowerCase() + '">'
      + c.severity + '</span> '
      + '<a href="' + nvdUrl(c.id) + '" target="_blank" rel="noopener">'
      + c.id + '</a></div>'
      + '<div class="cve-panel-meta">'
      + '<label>Disposition: </label>'
      + '<select class="cve-disp-select' + (disp ? ' disp-' + disp : '')
      + '" data-dk="' + dk + '">'
      + '<option value=""' + (!disp ? ' selected' : '') + '>\u2014</option>'
      + '<option value="affected"'
      + (disp === 'affected' ? ' selected' : '')
      + '>Affected</option>'
      + '<option value="not_affected"'
      + (disp === 'not_affected' ? ' selected' : '')
      + '>Not Affected</option>'
      + '<option value="fixed"'
      + (disp === 'fixed' ? ' selected' : '')
      + '>Fixed</option>'
      + '<option value="under_investigation"'
      + (disp === 'under_investigation' ? ' selected' : '')
      + '>Under Investigation</option>'
      + '</select></div>'
      + '<input class="cve-disp-justification ' + justVisible
      + '" data-dk="' + dk
      + '" placeholder="Justification (optional)" value="'
      + just.replace(/"/g, '&quot;') + '"/>'
      + '</div>';
  }).join('');

  updatePanelStatus();
  cvePanel.classList.add('open');

  // Bind change events
  cvePanelBody.querySelectorAll('.cve-disp-select').forEach(sel => {
    sel.addEventListener('change', (e) => {
      const dk = e.target.dataset.dk;
      const val = e.target.value;
      sel.className = 'cve-disp-select' + (val ? ' disp-' + val : '');
      const row = e.target.closest('.cve-panel-row');
      const justInput = row.querySelector('.cve-disp-justification');
      if (val && val !== 'affected') {
        justInput.classList.add('visible');
      } else {
        justInput.classList.remove('visible');
      }
      if (val) {
        dispositions[dk] = dispositions[dk] || {};
        dispositions[dk].status = val;
      } else {
        delete dispositions[dk];
      }
      saveDispositions(dispositions);
      updatePanelStatus();
      updateDiamondVisuals();
    });
  });

  cvePanelBody.querySelectorAll('.cve-disp-justification').forEach(inp => {
    inp.addEventListener('input', (e) => {
      const dk = e.target.dataset.dk;
      if (dispositions[dk]) {
        dispositions[dk].justification = e.target.value;
        saveDispositions(dispositions);
      }
    });
  });
}

function updatePanelStatus() {
  const total = Object.keys(dispositions).length;
  cvePanelStatus.textContent = total
    ? total + ' disposition' + (total > 1 ? 's' : '') + ' saved'
    : '';
}

// Update diamond appearance when dispositions change
function updateDiamondVisuals() {
  cveNodes.selectAll('.cve-indicator')
    .attr('stroke', d => {
      const pkgKey = d.name + '@' + (d.version || '');
      const allSet = d.cves.every(c =>
        dispositions[pkgKey + '/' + c.id]
        && dispositions[pkgKey + '/' + c.id].status
      );
      return allSet ? '#22c55e' : '#fff';
    })
    .attr('stroke-width', d => {
      const pkgKey = d.name + '@' + (d.version || '');
      const allSet = d.cves.every(c =>
        dispositions[pkgKey + '/' + c.id]
        && dispositions[pkgKey + '/' + c.id].status
      );
      return allSet ? 2 : 1;
    });
}
updateDiamondVisuals();

// Click diamond → open panel
cveNodes.selectAll('.cve-indicator')
  .on('click', (event, d) => {
    event.stopPropagation();
    openCvePanel(d);
  });

// Close panel
document.getElementById('cve-panel-close')
  .addEventListener('click', () => {
    cvePanel.classList.remove('open');
  });

// Review All — show summary of all dispositions
document.getElementById('cve-review-btn')
  .addEventListener('click', () => {
    const keys = Object.keys(dispositions);
    if (!keys.length) {
      cvePanelTitle.textContent = 'VEX Review — No Dispositions';
      cvePanelBody.innerHTML =
        '<div class="cve-review-none">'
        + 'No dispositions set yet.<br>'
        + 'Click a CVE diamond to start triaging.'
        + '</div>';
      updatePanelStatus();
      cvePanel.classList.add('open');
      return;
    }
    // Group by status
    const groups = {};
    keys.forEach(dk => {
      const d = dispositions[dk];
      const st = d.status || 'unknown';
      if (!groups[st]) groups[st] = [];
      const parts = dk.split('/');
      const cveId = parts.pop();
      const pkgKey = parts.join('/');
      const [name, version] = pkgKey.split('@');
      groups[st].push({
        cveId: cveId, name: name,
        version: version || '',
        justification: d.justification || '',
      });
    });
    const statusLabels = {
      'affected': 'Affected',
      'not_affected': 'Not Affected',
      'fixed': 'Fixed',
      'under_investigation': 'Under Investigation',
    };
    const statusOrder = [
      'affected', 'under_investigation',
      'not_affected', 'fixed',
    ];
    let html = '';
    statusOrder.forEach(st => {
      const items = groups[st];
      if (!items || !items.length) return;
      html += '<div class="cve-review-section">'
        + '<h4>' + (statusLabels[st] || st)
        + ' (' + items.length + ')</h4>';
      items.forEach(it => {
        html += '<div class="cve-review-entry">'
          + '<span class="disp-badge db-' + st + '">'
          + (statusLabels[st] || st) + '</span>'
          + '<a href="' + nvdUrl(it.cveId)
          + '" target="_blank" rel="noopener"'
          + ' style="color:#93c5fd;text-decoration:none">'
          + it.cveId + '</a>'
          + '<span style="color:#888">' + it.name
          + (it.version ? '@' + it.version : '') + '</span>';
        if (it.justification) {
          html += '<span style="color:#6b7280;font-style:italic">'
            + '\u2014 ' + it.justification + '</span>';
        }
        html += '</div>';
      });
      html += '</div>';
    });
    cvePanelTitle.textContent = 'VEX Review — '
      + keys.length + ' disposition'
      + (keys.length > 1 ? 's' : '');
    cvePanelBody.innerHTML = html;
    updatePanelStatus();
    cvePanel.classList.add('open');
  });

// Export VEX JSON
document.getElementById('cve-export-btn')
  .addEventListener('click', () => {
    const entries = [];
    Object.keys(dispositions).forEach(dk => {
      const parts = dk.split('/');
      const cveId = parts.pop();
      const pkgKey = parts.join('/');
      const [name, version] = pkgKey.split('@');
      const d = dispositions[dk];
      entries.push({
        package: { name: name, version: version || '' },
        vulnerability: cveId,
        status: d.status,
        justification: d.justification || '',
        timestamp: new Date().toISOString(),
      });
    });
    const vex = {
      type: 'vex-dispositions',
      version: '1.0',
      generated: new Date().toISOString(),
      dispositions: entries,
    };
    const blob = new Blob(
      [JSON.stringify(vex, null, 2)],
      { type: 'application/json' }
    );
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'vex-dispositions.json';
    a.click();
    URL.revokeObjectURL(a.href);
    cvePanelStatus.textContent = 'Exported ' + entries.length
      + ' disposition' + (entries.length > 1 ? 's' : '');
  });

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
  if (d.cves && d.cves.length > 0) {
    rows.push('<div class="tt-row" style="color:#ef4444;font-weight:600">\u26a0 ' + d.cves.length + ' CVE' + (d.cves.length > 1 ? 's' : '') + ' found</div>');
  }
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
  // Kill the simulation permanently — all future
  // interaction is pure DOM manipulation.
  simulation.stop();
  pinAllNodes();
});

let didDrag = false;
let dragStartX = 0, dragStartY = 0;

function dragstarted(event, d) {
  didDrag = false;
  dragStartX = d.x; dragStartY = d.y;
}
function dragged(event, d) {
  const dx = event.x - dragStartX, dy = event.y - dragStartY;
  if (!didDrag && dx*dx + dy*dy <= 25) return;  // ignore until >5px
  didDrag = true;
  d.fx = event.x; d.fy = event.y;
  d.x = event.x; d.y = event.y;
  d3.select(this).attr('transform', 'translate(' + d.x + ',' + d.y + ')');
  link.filter(l => l.source === d || l.target === d)
    .attr('x1', l => l.source.x).attr('y1', l => l.source.y)
    .attr('x2', l => l.target.x).attr('y2', l => l.target.y);
  linkLabel.filter(l => l.source === d || l.target === d)
    .attr('x', l => (l.source.x + l.target.x) / 2)
    .attr('y', l => (l.source.y + l.target.y) / 2 - 6);
}
function dragended(event, d) {
  if (!didDrag) { d.fx = d.x; d.fy = d.y; return; }
  // Compute drag delta
  const dx = d.x - dragStartX, dy = d.y - dragStartY;
  // Pin dragged node at new position
  d.fx = d.x; d.fy = d.y;
  // Collect tree-descendants via spanning tree
  const treeChildren = {};
  Object.keys(treeParent).forEach(child => {
    const par = treeParent[child];
    if (!treeChildren[par]) treeChildren[par] = [];
    treeChildren[par].push(child);
  });
  const desc = [];
  const queue = [d.id];
  while (queue.length) {
    const cur = queue.shift();
    (treeChildren[cur] || []).forEach(cid => {
      desc.push(cid);
      queue.push(cid);
    });
  }
  // Translate all descendants by the same delta — no simulation
  desc.forEach(nid => {
    const n = nodeById[nid];
    if (n) {
      n.x += dx; n.y += dy;
      n.fx = n.x; n.fy = n.y;
    }
  });
  // Update DOM for moved descendants
  node.filter(n => desc.includes(n.id))
    .attr('transform', n => 'translate(' + n.x + ',' + n.y + ')');
  // Update all links (some may connect to moved nodes)
  link.attr('x1', l => l.source.x).attr('y1', l => l.source.y)
    .attr('x2', l => l.target.x).attr('y2', l => l.target.y);
  linkLabel.attr('x', l => (l.source.x + l.target.x) / 2)
    .attr('y', l => (l.source.y + l.target.y) / 2 - 6);
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
