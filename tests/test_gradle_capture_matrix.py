"""
Gradle-version compatibility matrix for the dependency-graph capture.

Runs the hermetic synthetic fixtures in ``tests/fixtures/gradle/``
against a matrix of Gradle versions using the **real** capture code
(``app.pipeline.gradle_dep_tree_parser.get_all_gradle_deps``), asserting
that each fixture yields the expected per-project sections on every
version. This protects the two API surfaces the capture depends on
(``startParameter`` mutation and ``DependencyReportTask.outputFile``)
against Gradle version drift.

Opt-in only — it downloads Gradle distributions and builds, so it never
runs in the default unit gate. Enable with::

    OMNIBOR_GRADLE_MATRIX=1 pytest tests/test_gradle_capture_matrix.py

Requires a bootstrap ``gradle`` on PATH (used only to generate a wrapper
pinned to each matrix version) and a JDK compatible with every version
in the matrix (JDK 17 covers 7.6.4 through 9.6.1).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.pipeline.gradle_dep_tree_parser import (
    get_all_gradle_deps,
)

# Matrix: enterprise 7.6 floor, an 8.x, and the 9.6 ceiling.
GRADLE_MATRIX = ["7.6.4", "8.13", "9.6.1"]

FIXTURES_ROOT = (
    Path(__file__).parent / "fixtures" / "gradle"
)

_ENABLED = os.environ.get("OMNIBOR_GRADLE_MATRIX") == "1"
_GRADLE = shutil.which("gradle")

pytestmark = [
    pytest.mark.gradle_matrix,
    pytest.mark.skipif(
        not _ENABLED,
        reason="set OMNIBOR_GRADLE_MATRIX=1 to enable",
    ),
    pytest.mark.skipif(
        _GRADLE is None,
        reason="no bootstrap 'gradle' on PATH",
    ),
]


@pytest.fixture(params=GRADLE_MATRIX)
def gradle_tree(request, tmp_path_factory):
    """Copy the whole fixtures tree to a temp dir per version.

    The whole tree is copied (not just one fixture) so each fixture's
    ``${rootDir}/../local-repo`` file repository still resolves.
    """
    version = request.param
    dest = (
        tmp_path_factory.mktemp(f"gradle-{version}")
        / "gradle"
    )
    shutil.copytree(FIXTURES_ROOT, dest)
    return version, dest


def _capture(fixture_dir, version):
    """Pin a wrapper to ``version`` and run the real capture.

    Returns ``{project_key: {artifactId, ...}}``.
    """
    subprocess.run(
        [
            "gradle", "wrapper",
            "--gradle-version", version,
            "--console=plain",
        ],
        cwd=str(fixture_dir),
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    modules = get_all_gradle_deps(str(fixture_dir))
    return {
        m["key"]: {d["artifactId"] for d in m["deps"]}
        for m in modules
    }


def test_single_module(gradle_tree):
    version, tree = gradle_tree
    caps = _capture(tree / "single-module", version)
    assert set(caps) == {":"}
    assert {"libutil", "libcore"} <= caps[":"]


def test_configure_on_demand(gradle_tree):
    version, tree = gradle_tree
    caps = _capture(
        tree / "configure-on-demand", version,
    )
    # configure-on-demand must not drop a project's section.
    assert ":app" in caps
    assert ":lib" in caps


def test_configuration_cache(gradle_tree):
    version, tree = gradle_tree
    caps = _capture(
        tree / "configuration-cache", version,
    )
    # Capture must survive the configuration cache.
    assert ":app" in caps
    assert ":lib" in caps


def test_composite_substitution(gradle_tree):
    version, tree = gradle_tree
    caps = _capture(
        tree / "composite-substitution", version,
    )
    # Known gap: an included-build production dependency is
    # not captured as an external package (it renders as a
    # skipped ``project :`` line).
    assert ":" in caps
    assert "libutil" not in caps[":"]


def test_java_platform(gradle_tree):
    version, tree = gradle_tree
    caps = _capture(tree / "java-platform", version)
    # The BOM project has no runtimeClasspath and is skipped;
    # the consumer is captured.
    assert ":app" in caps
    assert ":platform" not in caps
