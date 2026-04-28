"""Tests for SPDX 2.3 relationship type classification.

Validates that dependency scopes map to the correct SPDX
relationship types per SPDX 2.3 Clause 11, Table 68.
"""

import pytest

from app.spdx.relationships import (
    BUILD_TOOL_OF,
    DEPENDS_ON,
    is_build_tool,
    java_dep_relationship,
)


class TestJavaDepRelationship:
    """SPDX 2.3 Table 68 scope → relationship mapping."""

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

    def test_provided_is_not_build_tool_of(self):
        """Maven 'provided' scope is DEPENDS_ON, not
        BUILD_TOOL_OF.  'provided' means the dependency
        is needed at compile/runtime but supplied by the
        deployment environment — it is still a dependency,
        not a build tool."""
        result = java_dep_relationship("provided")
        assert result == DEPENDS_ON
        assert result != BUILD_TOOL_OF


class TestIsBuildTool:
    """Build tool classification by groupId or binary name."""

    @pytest.mark.parametrize("group_id", [
        "org.apache.maven",
        "org.apache.maven.plugins",
        "org.codehaus.mojo",
        "org.gradle",
    ])
    def test_java_build_tool_group_ids(self, group_id):
        """Known build system groupIds are build tools."""
        assert is_build_tool(group_id=group_id) is True

    @pytest.mark.parametrize("group_id", [
        "org.apache.ant",
        "com.google.guava",
        "org.checkerframework",
        "info.picocli",
    ])
    def test_library_group_ids_not_build_tools(
        self, group_id,
    ):
        """Library dependencies are NOT build tools, even
        if they are build systems in other contexts (e.g.
        ant as a provided dep of checkstyle)."""
        assert is_build_tool(group_id=group_id) is False

    @pytest.mark.parametrize("binary", [
        "gcc", "g++", "ld", "ar", "make", "cmake",
        "go", "rustc", "cargo", "javac",
    ])
    def test_compiler_binaries_are_build_tools(
        self, binary,
    ):
        """Compilers and linkers are build tools."""
        assert is_build_tool(binary_name=binary) is True

    @pytest.mark.parametrize("binary", [
        "curl", "python3", "node", "java",
    ])
    def test_non_compiler_binaries(self, binary):
        """Application binaries are not build tools."""
        assert is_build_tool(binary_name=binary) is False

    def test_no_args_returns_false(self):
        """No arguments → not a build tool."""
        assert is_build_tool() is False
