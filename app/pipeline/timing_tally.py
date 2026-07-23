"""
Aggregate per-repo timing into a build / sidecar / Phase 2 tally.

Reads the ``runtime.json`` written by ``save_runtime_json`` for
each repository and produces a consolidated table that separates:

  - the native CI/CD build (``category == "build"``),
  - the sidecar work that creates and stores build metadata for
    Phase 2 (``category == "sidecar"``: ADG/treedb, dependency
    capture, identity index, manifest), and
  - Phase 2 SPDX generation (``category == "phase2"``).

The ADG/treedb vs dependency-capture breakdown is read from the
``adg_substeps.json`` written alongside the OmniBOR output, so the
sidecar figure can be attributed to its two dominant components.

This module holds the reusable, tested logic; ``scripts/
java_timing_tally.py`` is a thin CLI wrapper around it.
"""

import json
from pathlib import Path

from app.pipeline.timing import (
    CATEGORY_BUILD,
    CATEGORY_PHASE2,
    CATEGORY_SIDECAR,
    categorize_step,
)


def find_latest_runtimes(runtime_lang_dir):
    """Map each repo to its latest ``runtime.json`` path.

    Args:
        runtime_lang_dir: ``output/runtime/<lang>`` directory.
            Expected layout is
            ``<runtime_lang_dir>/<repo>/<run_ts>/runtime.json``.

    Returns:
        Dict of ``repo_name -> Path`` for the most recent run.
        Run timestamps sort chronologically, so the
        lexicographically greatest ``run_ts`` that contains a
        ``runtime.json`` is treated as latest.  Returns an empty
        dict when the directory is absent.
    """
    root = Path(runtime_lang_dir)
    result = {}
    if not root.is_dir():
        return result
    for repo_dir in sorted(root.iterdir()):
        if not repo_dir.is_dir():
            continue
        latest = None
        for ts_dir in sorted(repo_dir.iterdir()):
            if not ts_dir.is_dir():
                continue
            candidate = ts_dir / "runtime.json"
            if candidate.exists():
                latest = candidate
        if latest is not None:
            result[repo_dir.name] = latest
    return result


def read_adg_substeps(omnibor_lang_dir, repo, run_ts):
    """Return the treedb and dep-tree wall times for a run.

    Args:
        omnibor_lang_dir: ``output/omnibor/<lang>`` directory.
        repo: Repository name.
        run_ts: Run timestamp (the run's output subdirectory).

    Returns:
        Dict ``{"treedb": float, "dep_tree": float}``.  Missing
        file or entries yield ``0.0`` for that key.
    """
    path = (
        Path(omnibor_lang_dir) / repo / run_ts
        / "adg_substeps.json"
    )
    out = {"treedb": 0.0, "dep_tree": 0.0}
    if not path.exists():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for entry in data:
        name = entry.get("name")
        if name in out:
            out[name] = float(entry.get("wall_sec", 0.0))
    return out


def _category_totals(steps):
    """Sum step wall times per category (build/sidecar/phase2)."""
    totals = {
        CATEGORY_BUILD: 0.0,
        CATEGORY_SIDECAR: 0.0,
        CATEGORY_PHASE2: 0.0,
    }
    for step in steps:
        category = step.get("category") or categorize_step(
            step.get("name", ""), step.get("phase", ""),
        )
        if category in totals:
            totals[category] += float(
                step.get("wall_sec", 0.0)
            )
    return totals


def _step_wall(steps, name):
    """Return the wall time of the named step, or 0.0."""
    for step in steps:
        if step.get("name") == name:
            return float(step.get("wall_sec", 0.0))
    return 0.0


def build_row(repo, runtime_path, omnibor_lang_dir):
    """Parse one ``runtime.json`` into a tally row.

    Args:
        repo: Repository name.
        runtime_path: Path to the repo's ``runtime.json``.
        omnibor_lang_dir: ``output/omnibor/<lang>`` directory,
            used to locate ``adg_substeps.json``.

    Returns:
        A dict with the per-category totals and the treedb /
        dep-tree / identity / manifest breakdown.
    """
    data = json.loads(
        Path(runtime_path).read_text(encoding="utf-8")
    )
    steps = data.get("steps", [])
    run_ts = Path(runtime_path).parent.name
    totals = _category_totals(steps)
    sub = read_adg_substeps(omnibor_lang_dir, repo, run_ts)
    return {
        "repo": repo,
        "run_ts": run_ts,
        "success": bool(data.get("success", False)),
        "tracer": data.get("tracer", ""),
        "ci_build_sec": round(totals[CATEGORY_BUILD], 2),
        "sidecar_sec": round(totals[CATEGORY_SIDECAR], 2),
        "treedb_sec": round(sub["treedb"], 2),
        "dep_tree_sec": round(sub["dep_tree"], 2),
        "identity_sec": round(
            _step_wall(steps, "identity_index"), 2
        ),
        "manifest_sec": round(
            _step_wall(steps, "manifest"), 2
        ),
        "phase2_sec": round(totals[CATEGORY_PHASE2], 2),
        "total_sec": round(
            float(data.get("total_sec", 0.0)), 2
        ),
    }


def collect_rows(output_dir, lang="java"):
    """Collect tally rows for every repo of a language.

    Args:
        output_dir: The pipeline ``output`` directory.
        lang: Language subdirectory (default ``java``).

    Returns:
        A list of row dicts sorted by repository name.
    """
    runtime_lang = Path(output_dir) / "runtime" / lang
    omnibor_lang = Path(output_dir) / "omnibor" / lang
    latest = find_latest_runtimes(runtime_lang)
    return [
        build_row(repo, latest[repo], omnibor_lang)
        for repo in sorted(latest)
    ]


_NUMERIC_FIELDS = (
    "ci_build_sec", "sidecar_sec", "treedb_sec",
    "dep_tree_sec", "identity_sec", "manifest_sec",
    "phase2_sec", "total_sec",
)


def aggregate(rows):
    """Sum every numeric field across rows for a TOTAL line."""
    agg = {field: 0.0 for field in _NUMERIC_FIELDS}
    for row in rows:
        for field in _NUMERIC_FIELDS:
            agg[field] += row.get(field, 0.0)
    return {k: round(v, 2) for k, v in agg.items()}


def format_markdown(rows):
    """Render the tally as a GitHub-flavored markdown table."""
    header = (
        "| Repo | CI/CD build (s) | Sidecar total (s) "
        "| treedb (s) | dep tree (s) | identity (s) "
        "| manifest (s) | Phase 2 (s) | Total (s) |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for row in rows:
        lines.append(
            f"| `{row['repo']}` | {row['ci_build_sec']:.2f} "
            f"| {row['sidecar_sec']:.2f} "
            f"| {row['treedb_sec']:.2f} "
            f"| {row['dep_tree_sec']:.2f} "
            f"| {row['identity_sec']:.2f} "
            f"| {row['manifest_sec']:.2f} "
            f"| {row['phase2_sec']:.2f} "
            f"| {row['total_sec']:.2f} |"
        )
    if rows:
        agg = aggregate(rows)
        lines.append(
            f"| **TOTAL** | **{agg['ci_build_sec']:.2f}** "
            f"| **{agg['sidecar_sec']:.2f}** "
            f"| {agg['treedb_sec']:.2f} "
            f"| {agg['dep_tree_sec']:.2f} "
            f"| {agg['identity_sec']:.2f} "
            f"| {agg['manifest_sec']:.2f} "
            f"| **{agg['phase2_sec']:.2f}** "
            f"| **{agg['total_sec']:.2f}** |"
        )
    return "\n".join(lines)


_CONSOLE_COLUMNS = (
    ("repo", "Repo", "{}"),
    ("ci_build_sec", "CI/CD build", "{:.2f}"),
    ("sidecar_sec", "Sidecar", "{:.2f}"),
    ("treedb_sec", "treedb", "{:.2f}"),
    ("dep_tree_sec", "dep_tree", "{:.2f}"),
    ("identity_sec", "identity", "{:.2f}"),
    ("manifest_sec", "manifest", "{:.2f}"),
    ("phase2_sec", "Phase2", "{:.2f}"),
    ("total_sec", "Total", "{:.2f}"),
)


def _console_cells(row):
    """Format a single row's cells for the console table."""
    return [
        fmt.format(row.get(key, 0))
        for key, _title, fmt in _CONSOLE_COLUMNS
    ]


def format_console(rows):
    """Render the tally as a fixed-width table for a terminal."""
    titles = [title for _key, title, _fmt in _CONSOLE_COLUMNS]
    table = [titles]
    for row in rows:
        table.append(_console_cells(row))
    if rows:
        agg = aggregate(rows)
        total_row = {"repo": "TOTAL", **agg}
        table.append(_console_cells(total_row))

    widths = [
        max(len(r[i]) for r in table)
        for i in range(len(titles))
    ]
    out = []
    for idx, cells in enumerate(table):
        out.append(
            "  ".join(
                cell.rjust(widths[i]) if i else
                cell.ljust(widths[i])
                for i, cell in enumerate(cells)
            )
        )
        if idx == 0:
            out.append(
                "  ".join("-" * w for w in widths)
            )
    return "\n".join(out)
