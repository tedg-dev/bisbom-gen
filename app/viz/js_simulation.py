"""JavaScript template for the D3 force simulation and layout.

Generates the JS code for: colors, zoom, zoom-to-fit, arrow markers,
layout positions, spanning tree/BFS, fan-out force, and force simulation.
"""


def get_js_simulation():
    """Return the JS code for simulation setup and layout."""
    return r"""
const colors = {
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
  sibling: '#c084fc',
  other: '#888',
};

const linkColors = {
  'STATIC_LINK': '#4ecdc4',
  'DYNAMIC_LINK': '#ff6b6b',
  'BUILD_TOOL_OF': '#ffd93d',
  'DEPENDS_ON': '#56b6f7',
};

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
function zoomToFit(duration) {
  const pad = 60;
  let x0 = Infinity, y0 = Infinity;
  let x1 = -Infinity, y1 = -Infinity;
  data.nodes.forEach(d => {
    if (d.x < x0) x0 = d.x;
    if (d.y < y0) y0 = d.y;
    if (d.x > x1) x1 = d.x;
    if (d.y > y1) y1 = d.y;
  });
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
  if (duration) {
    svg.transition().duration(duration)
      .call(zoom.transform, t);
  } else {
    svg.call(zoom.transform, t);
  }
}

// Arrow markers
const defs = svg.append('defs');
Object.entries(linkColors).forEach(([type, color]) => {
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
});

// Horizontal layout: transitive left, dynamic/build center-top, static right
const xPositions = {
  root: width / 2,
  'depth-1': width * 0.72,
  'depth-2': width * 0.38,
  'depth-3': width * 0.22,
  'depth-4': width * 0.15,
  'depth-5': width * 0.10,
  vendored: width * 0.85,
  sibling: width * 0.28,
  go_stdlib: width * 0.20,
  go_direct: width * 0.72,
  go_indirect: width * 0.38,
  dynamic: width * 0.5,
  build: width * 0.5,
  build_deep: width * 0.5,
  other: width / 2,
};

// Vertical bias: dynamic/build top, everything else center-to-below
const yPositions = {
  root: height * 0.48,
  'depth-1': height * 0.50,
  'depth-2': height * 0.52,
  'depth-3': height * 0.54,
  'depth-4': height * 0.56,
  'depth-5': height * 0.58,
  vendored: height * 0.72,
  sibling: height * 0.48,
  go_stdlib: height * 0.75,
  go_direct: height * 0.50,
  go_indirect: height * 0.52,
  dynamic: height * 0.18,
  build: height * 0.18,
  build_deep: height * 0.25,
  other: height * 0.55,
};

const yStrengths = {
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
};

// --- Build spanning tree for fan-out force ---
// For each dep node, figure out its tree parent so
// 2nd-level deps can be pushed away from root.
const nodeById = {};
data.nodes.forEach(d => { nodeById[d.id] = d; });
const rootNode = data.nodes.find(
  d => d.group === 'root'
);
const rootId = rootNode ? rootNode.id : null;

// depsOf[X] = nodes that X depends on
// deppedBy[Y] = nodes that depend on Y
const depsOf = {};
const deppedBy = {};
data.links.forEach(l => {
  const sid = l.source.id || l.source;
  const tid = l.target.id || l.target;
  if (l.type === 'DEPENDS_ON') {
    if (!depsOf[sid]) depsOf[sid] = [];
    depsOf[sid].push(tid);
    if (!deppedBy[tid]) deppedBy[tid] = [];
    deppedBy[tid].push(sid);
  } else if (l.type === 'STATIC_LINK') {
    if (tid === rootId) {
      if (!depsOf[tid]) depsOf[tid] = [];
      depsOf[tid].push(sid);
      if (!deppedBy[sid]) deppedBy[sid] = [];
      deppedBy[sid].push(tid);
    } else if (sid === rootId) {
      if (!depsOf[sid]) depsOf[sid] = [];
      depsOf[sid].push(tid);
      if (!deppedBy[tid]) deppedBy[tid] = [];
      deppedBy[tid].push(sid);
    }
  }
});

// Build tree: prefer non-root parents so that
// shared deps become children of their non-root
// parent (depth 2+) instead of root (depth 1).
const treeParent = {};  // child -> parent id
const treeDepthMap = {};
const treeVisited = new Set();
if (rootId) {
  treeVisited.add(rootId);
  treeDepthMap[rootId] = 0;
  // Phase 1: seed with root-exclusive deps
  const queue = [];
  (depsOf[rootId] || []).forEach(c => {
    const nonRoot = (deppedBy[c] || []).filter(
      p => p !== rootId
    );
    if (nonRoot.length === 0) {
      treeVisited.add(c);
      treeParent[c] = rootId;
      treeDepthMap[c] = 1;
      queue.push(c);
    }
  });
  // Phase 2: BFS from seeds
  while (queue.length) {
    const n = queue.shift();
    (depsOf[n] || []).forEach(c => {
      if (!treeVisited.has(c)) {
        treeVisited.add(c);
        treeParent[c] = n;
        treeDepthMap[c] = treeDepthMap[n] + 1;
        queue.push(c);
      }
    });
  }
  // Phase 3: remaining go under root
  (depsOf[rootId] || []).forEach(c => {
    if (!treeVisited.has(c)) {
      treeVisited.add(c);
      treeParent[c] = rootId;
      treeDepthMap[c] = 1;
      const q2 = [c];
      while (q2.length) {
        const n2 = q2.shift();
        (depsOf[n2] || []).forEach(c2 => {
          if (!treeVisited.has(c2)) {
            treeVisited.add(c2);
            treeParent[c2] = n2;
            treeDepthMap[c2] = treeDepthMap[n2] + 1;
            q2.push(c2);
          }
        });
      }
    }
  });
}

// Collect depth-2+ nodes for fan-out
const deepNodes = data.nodes.filter(
  d => (treeDepthMap[d.id] || 0) >= 2
);
// Cache each deep node's depth-1 ancestor
const depthOneAnc = {};
deepNodes.forEach(d => {
  let anc = d.id;
  while (treeDepthMap[anc] > 1 && treeParent[anc])
    anc = treeParent[anc];
  depthOneAnc[d.id] = anc;
});

console.log('Fan-out: ' + deepNodes.length
  + ' depth-2+ nodes out of ' + data.nodes.length);
deepNodes.forEach(d => {
  const pName = nodeById[treeParent[d.id]]
    ? nodeById[treeParent[d.id]].name : '?';
  const aName = nodeById[depthOneAnc[d.id]]
    ? nodeById[depthOneAnc[d.id]].name : '?';
  console.log('  depth=' + treeDepthMap[d.id]
    + ' ' + d.name + ' -> parent:' + pName
    + ' anchor:' + aName);
});

// Build set of depth-2+ ids for force callbacks
const deepIdSet = new Set(
  deepNodes.map(d => d.id));

// Force simulation (original layout + fan-out)
const simulation = d3.forceSimulation(data.nodes)
  .alphaDecay(0.05)
  .force('link', d3.forceLink(data.links)
    .id(d => d.id)
    .distance(d => {
      if (d.type === 'BUILD_TOOL_OF') return 180;
      return 140;
    }))
  .force('charge', d3.forceManyBody()
    .strength(-600))
  // No forceCenter — forceX/forceY handle
  // centering.  forceCenter shifts centroid of
  // ALL nodes, counteracting rightward fanout.
  .force('x', d3.forceX(
    d => xPositions[d.group] || width / 2)
    .strength(d => {
      // No X pull for depth-2+ nodes (fanout
      // controls their position instead)
      if (deepIdSet.has(d.id)) return 0;
      return 0.15;
    }))
  .force('y', d3.forceY(
    d => yPositions[d.group] || height / 2)
    .strength(d => {
      if (d.group === 'dynamic'
          || d.group === 'build') return 0.5;
      if (deepIdSet.has(d.id)) return 0;
      if (d.group === 'root') return 0.08;
      return 0.10;
    }))
  .force('collision', d3.forceCollide().radius(50));

// --- Fan-out force (alpha-dependent, strong) ---
// Pushes depth-2+ nodes beyond their parent in the
// direction from root through their depth-1 ancestor.
// Scales with alpha so the sim properly settles.
if (deepNodes.length > 0 && rootNode) {
  const fanout = function(alpha) {
    const rx = rootNode.x, ry = rootNode.y;
    deepNodes.forEach(d => {
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
    });
  };
  fanout.initialize = function() {};
  simulation.force('fanout', fanout);
}
"""
