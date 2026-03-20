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
  }
  #legend h3 {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 10px;
    color: #fff;
  }
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

  /* Group labels (unused, kept for potential future use) */
  .group-label {
    font-size: 14px;
    font-weight: 600;
    fill: #333;
    text-anchor: middle;
    pointer-events: none;
  }
"""
