"""Tests for SPDX 2.3 relationship type classification.

Validates that dependency scopes map to the correct SPDX
relationship types per SPDX 2.3 Clause 11, Table 68.
"""

import pytest

from app.spdx.relationships import (
    DEPENDS_ON,
    java_dep_relationship,
)


class TestJavaDepRelationship:
    """SPDX 2.3 Table 68 scope → relationship mapping.

    All Maven/Gradle dependency tree entries are library
    dependencies — relationship type is scope-based only.
    Build tools are emitted separately by _add_build_tools().
    """

    @pytest.mark.parametrize("scope", [
        "compile",
        "runtime",
        "provided",
        "system",
    ])
    def test_maven_deps_are_depends_on(self, scope):
        """Maven compile/runtime/provided/system scopes
        all map to DEPENDS_ON per SPDX 2.3 Table 68."""
        assert java_dep_relationship(scope) == DEPENDS_ON

    @pytest.mark.parametrize("scope", [
        "implementation",
        "api",
        "runtimeOnly",
        "compileOnly",
        "compileOnlyApi",
    ])
    def test_gradle_deps_are_depends_on(self, scope):
        """Gradle configuration scopes map to DEPENDS_ON."""
        assert java_dep_relationship(scope) == DEPENDS_ON

    def test_test_scope_excluded(self):
        """Test-scope deps are excluded from SPDX entirely."""
        assert java_dep_relationship("test") is None

    def test_unknown_scope_defaults_to_depends_on(self):
        """Unknown scopes default to DEPENDS_ON."""
        assert java_dep_relationship("custom") == DEPENDS_ON

    def test_provided_is_depends_on(self):
        """Maven 'provided' is always DEPENDS_ON — the dep
        is needed at compile time but supplied by the
        deployment environment."""
        assert java_dep_relationship("provided") == DEPENDS_ON

    def test_ant_dep_is_depends_on(self):
        """A project that depends on ant as a library
        (e.g. checkstyle) gets DEPENDS_ON, not
        BUILD_TOOL_OF.  Build tools are emitted via
        _add_build_tools(), not from the dependency tree."""
        assert java_dep_relationship("compile") == DEPENDS_ON

    def test_maven_lib_dep_is_depends_on(self):
        """Even org.apache.maven dependencies in the tree
        are library deps (DEPENDS_ON), not build tools."""
        assert java_dep_relationship("compile") == DEPENDS_ON
