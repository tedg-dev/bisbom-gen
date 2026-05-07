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

    def test_provided_library_is_depends_on(self):
        """Maven 'provided' for a regular library is
        DEPENDS_ON — the dependency is needed at compile
        time but supplied by the deployment environment."""
        result = java_dep_relationship("provided")
        assert result == DEPENDS_ON

    def test_provided_build_tool_is_build_tool_of(self):
        """Maven 'provided' for a known build tool gets
        BUILD_TOOL_OF — scope does not override identity."""
        result = java_dep_relationship(
            "provided", group_id="org.apache.ant",
        )
        assert result == BUILD_TOOL_OF

    def test_compile_build_tool_is_build_tool_of(self):
        """Even compile-scope build tools get BUILD_TOOL_OF."""
        result = java_dep_relationship(
            "compile", group_id="org.apache.maven",
        )
        assert result == BUILD_TOOL_OF

    def test_test_scope_build_tool_excluded(self):
        """Test-scope deps excluded even if build tool."""
        result = java_dep_relationship(
            "test", group_id="org.apache.ant",
        )
        assert result is None


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

    def test_ant_is_build_tool(self):
        """Apache Ant is a build tool."""
        assert is_build_tool(
            group_id="org.apache.ant",
        ) is True

    @pytest.mark.parametrize("group_id", [
        "com.google.guava",
        "org.checkerframework",
        "info.picocli",
    ])
    def test_library_group_ids_not_build_tools(
        self, group_id,
    ):
        """Library dependencies are NOT build tools."""
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
