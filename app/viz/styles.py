"""CSS styles for the SPDX dependency graph visualization."""


def get_css():
    """Return the CSS stylesheet for the visualization."""
    return """
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e0e0e0;
    overflow: hidden;
  }
  #header {
    position: fixed; top: 0; left: 0; right: 0;
    background: rgba(15, 17, 23, 0.95);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid #2a2d35;
    padding: 12px 24px;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 24px;
  }
  #header h1 {
    font-size: 16px;
    font-weight: 600;
    color: #fff;
    white-space: nowrap;
  }
  #header .meta {
    font-size: 12px;
    color: #888;
  }
  #legend {
    position: fixed; top: 60px; right: 20px;
    background: rgba(22, 24, 32, 0.95);
    backdrop-filter: blur(8px);
    border: 1px solid #2a2d35;
    border-radius: 8px;
    padding: 16px;
    z-index: 100;
    font-size: 13px;
    min-width: 200px;
    transition: min-width 0.2s;
  }
  #legend.collapsed { min-width: auto; }
  #legend.collapsed #legend-body { display: none; }
  #legend.collapsed #legend-title { display: none; }
  #legend-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 10px;
  }
  #legend.collapsed #legend-header { margin-bottom: 0; }
  #legend-toggle {
    background: none;
    border: 1px solid #444;
    border-radius: 4px;
    color: #aaa;
    cursor: pointer;
    font-size: 12px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s, border-color 0.15s;
    flex-shrink: 0;
  }
  #legend-toggle:hover {
    color: #fff;
    border-color: #888;
  }
  #legend.collapsed #legend-toggle {
    transform: rotate(-90deg);
  }
  #legend h3 {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 0;
    color: #fff;
  }
  #legend-body h3 { margin-bottom: 10px; }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .legend-dot {
    width: 12px; height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .legend-line {
    width: 24px; height: 2px;
    flex-shrink: 0;
  }
  #tooltip {
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
  }
  #tooltip .tt-name {
    font-weight: 600;
    font-size: 14px;
    color: #fff;
    margin-bottom: 4px;
  }
  #tooltip .tt-row {
    color: #aaa;
    margin-top: 2px;
  }
  #tooltip .tt-row span {
    color: #ddd;
  }
  #graph { width: 100vw; height: 100vh; }
  svg { display: block; }

  /* Edge styles */
  .link-STATIC_LINK { stroke: #4ecdc4; }
  .link-DYNAMIC_LINK { stroke: #ff6b6b; }
  .link-BUILD_TOOL_OF { stroke: #ffd93d; }
  .link-DEPENDS_ON { stroke: #56b6f7; }

  /* Search box */
  #search-box {
    position: fixed;
    top: 60px; left: 20px;
    z-index: 100;
  }
  #search-box input {
    background: rgba(22, 24, 32, 0.95);
    border: 1px solid #2a2d35;
    border-radius: 6px;
    padding: 8px 12px;
    color: #e0e0e0;
    font-size: 13px;
    width: 220px;
    outline: none;
  }
  #search-box input:focus {
    border-color: #56b6f7;
  }
  #search-box input::placeholder {
    color: #555;
  }
  #search-hint {
    font-size: 11px;
    color: #555;
    margin-top: 4px;
    padding-left: 4px;
  }

  /* CVE toggle switch */
  .cve-toggle {
    position: relative;
    display: inline-block;
    width: 32px;
    height: 18px;
    flex-shrink: 0;
  }
  .cve-toggle input { opacity: 0; width: 0; height: 0; }
  .cve-toggle-slider {
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background: #4b5563;
    border-radius: 18px;
    transition: 0.2s;
  }
  .cve-toggle-slider:before {
    content: '';
    position: absolute;
    height: 14px; width: 14px;
    left: 2px; bottom: 2px;
    background: #fff;
    border-radius: 50%;
    transition: 0.2s;
  }
  .cve-toggle input:checked + .cve-toggle-slider {
    background: #dc2626;
  }
  .cve-toggle input:checked + .cve-toggle-slider:before {
    transform: translateX(14px);
  }
  /* Hide CVE elements when overlay is off */
  body.cve-hidden .cve-indicator,
  body.cve-hidden #cve-tooltip,
  body.cve-hidden #cve-panel {
    display: none !important;
    opacity: 0 !important;
  }

  /* CVE tooltip */
  #cve-tooltip {
    position: fixed;
    background: rgba(30, 10, 10, 0.97);
    border: 1px solid #dc2626;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 13px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 210;
    max-width: 400px;
    max-height: 300px;
    overflow-y: auto;
    box-shadow: 0 4px 20px rgba(220,38,38,0.3);
  }
  #cve-tooltip .cve-title {
    font-weight: 600;
    font-size: 13px;
    color: #fca5a5;
    margin-bottom: 6px;
  }
  .cve-row {
    margin-top: 3px;
    font-size: 12px;
  }
  .cve-id { color: #e0e0e0; }
  .cve-sev {
    display: inline-block;
    min-width: 64px;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    text-align: center;
  }
  .cve-sev-critical { background: #dc2626; color: #fff; }
  .cve-sev-high { background: #ea580c; color: #fff; }
  .cve-sev-medium { background: #eab308; color: #000; }
  .cve-sev-low { background: #2563eb; color: #fff; }
  .cve-sev-negligible { background: #4b5563; color: #d1d5db; }
  .cve-sev-unknown { background: #4b5563; color: #d1d5db; }

  /* CVE diamond indicator */
  .cve-indicator {
    filter: drop-shadow(0 0 3px rgba(220,38,38,0.6));
  }

  /* CVE detail panel (slide-out) */
  #cve-panel {
    position: fixed;
    top: 60px; left: -460px;
    width: 440px;
    bottom: 0;
    background: rgba(22, 24, 32, 0.98);
    border-right: 1px solid #dc2626;
    z-index: 300;
    display: flex;
    flex-direction: column;
    transition: left 0.25s ease;
    box-shadow: 4px 0 20px rgba(0,0,0,0.5);
  }
  #cve-panel.open { left: 0; }
  #cve-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid #2a2d35;
    background: rgba(30, 10, 10, 0.6);
  }
  #cve-panel-title {
    font-weight: 600;
    font-size: 14px;
    color: #fca5a5;
  }
  #cve-panel-close {
    background: none;
    border: none;
    color: #888;
    font-size: 22px;
    cursor: pointer;
    padding: 0 4px;
  }
  #cve-panel-close:hover { color: #fff; }
  #cve-panel-body {
    flex: 1;
    overflow-y: auto;
    padding: 12px 18px;
  }
  #cve-panel-footer {
    padding: 12px 18px;
    border-top: 1px solid #2a2d35;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  #cve-review-btn, #cve-export-btn {
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  #cve-review-btn { background: #7c3aed; }
  #cve-review-btn:hover { background: #6d28d9; }
  #cve-export-btn:hover { background: #1d4ed8; }
  .cve-review-section {
    margin-bottom: 14px;
  }
  .cve-review-section h4 {
    font-size: 12px;
    font-weight: 600;
    color: #a78bfa;
    margin-bottom: 6px;
    border-bottom: 1px solid #2a2d35;
    padding-bottom: 4px;
  }
  .cve-review-entry {
    font-size: 12px;
    color: #d1d5db;
    padding: 4px 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .cve-review-entry .disp-badge {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
  }
  .disp-badge.db-affected { background: #dc2626; color: #fff; }
  .disp-badge.db-not_affected { background: #22c55e; color: #fff; }
  .disp-badge.db-fixed { background: #2563eb; color: #fff; }
  .disp-badge.db-under_investigation {
    background: #eab308; color: #000;
  }
  .cve-review-edit {
    background: none;
    border: 1px solid #4b5563;
    border-radius: 4px;
    color: #9ca3af;
    font-size: 13px;
    padding: 1px 5px;
    cursor: pointer;
    flex-shrink: 0;
  }
  .cve-review-edit:hover {
    background: #7c3aed;
    border-color: #7c3aed;
    color: #fff;
  }
  .cve-review-none {
    font-size: 12px;
    color: #6b7280;
    padding: 20px 0;
    text-align: center;
  }
  #cve-panel-status {
    font-size: 11px;
    color: #6b7280;
  }

  /* CVE panel rows */
  .cve-panel-row {
    padding: 10px 0;
    border-bottom: 1px solid #1e2028;
  }
  .cve-panel-row:last-child { border-bottom: none; }
  .cve-panel-id {
    font-size: 13px;
    font-weight: 600;
    color: #e0e0e0;
  }
  .cve-panel-id a {
    color: #93c5fd;
    text-decoration: none;
  }
  .cve-panel-id a:hover {
    text-decoration: underline;
    color: #bfdbfe;
  }
  .cve-panel-meta {
    font-size: 11px;
    color: #888;
    margin-top: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .cve-disp-select {
    background: #1a1c24;
    color: #e0e0e0;
    border: 1px solid #3a3d45;
    border-radius: 4px;
    padding: 3px 6px;
    font-size: 11px;
    cursor: pointer;
  }
  .cve-disp-select:focus { border-color: #2563eb; outline: none; }
  .cve-disp-select.disp-not_affected { border-color: #22c55e; }
  .cve-disp-select.disp-fixed { border-color: #2563eb; }
  .cve-disp-select.disp-under_investigation {
    border-color: #eab308;
  }
  .cve-disp-select.disp-affected { border-color: #dc2626; }
  .cve-disp-delete {
    background: none;
    border: 1px solid #4b5563;
    border-radius: 4px;
    color: #9ca3af;
    font-size: 14px;
    line-height: 1;
    padding: 2px 6px;
    cursor: pointer;
    display: none;
  }
  .cve-disp-delete:hover {
    background: #dc2626;
    border-color: #dc2626;
    color: #fff;
  }
  .cve-disp-delete.visible { display: inline-block; }
  .cve-disp-justification-select {
    background: #1a1c24;
    color: #e0e0e0;
    border: 1px solid #3a3d45;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 11px;
    width: 100%;
    margin-top: 4px;
    cursor: pointer;
    display: none;
  }
  .cve-disp-justification-select:focus {
    border-color: #22c55e;
    outline: none;
  }
  .cve-disp-justification-select.visible { display: block; }
  .cve-disp-justification {
    background: #1a1c24;
    color: #e0e0e0;
    border: 1px solid #3a3d45;
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 11px;
    width: 100%;
    margin-top: 4px;
    display: none;
  }
  .cve-disp-justification:focus {
    border-color: #2563eb;
    outline: none;
  }
  .cve-disp-justification.visible { display: block; }

  /* Group labels (unused, kept for potential future use) */
  .group-label {
    font-size: 14px;
    font-weight: 600;
    fill: #333;
    text-anchor: middle;
    pointer-events: none;
  }
"""
