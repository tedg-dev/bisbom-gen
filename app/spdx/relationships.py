"""SPDX 2.3 relationship type constants and classifiers.

Centralises the rules for choosing SPDX relationship types so
that every generator uses the same spec-aligned logic.

Reference: SPDX 2.3 Clause 11, Table 68
https://spdx.github.io/spdx-spec/v2.3/relationships-between-SPDX-elements/

Key spec guidance (Table 68 examples):
  - compile scope      → DEPENDS_ON
  - runtime scope      → DEPENDS_ON
  - provided scope     → DEPENDS_ON  (NOT BUILD_TOOL_OF)
  - test scope         → TEST_DEPENDENCY_OF
  - devDependencies    → DEV_DEPENDENCY_OF
  - optional           → OPTIONAL_DEPENDENCY_OF
  - compiler / linker  → BUILD_TOOL_OF
  - makefile           → BUILD_TOOL_OF

BUILD_TOOL_OF is reserved for the *build system itself*
(gcc, go, javac, maven, gradle, make) — packages that
compile/link the software. It is NOT for library
dependencies in Maven ``provided`` scope.

Maven ``provided`` means "the dependency is required at
compile time but supplied by the deployment environment
at runtime".  In SPDX terms this is still DEPENDS_ON;
the scope is recorded in the package comment field.
SPDX 3.0 formalises this as ``hasProvidedDependency``.
"""

# -----------------------------------------------------------
# Relationship type constants (SPDX 2.3)
# -----------------------------------------------------------
DESCRIBES = "DESCRIBES"
DEPENDS_ON = "DEPENDS_ON"
BUILD_TOOL_OF = "BUILD_TOOL_OF"
DEV_TOOL_OF = "DEV_TOOL_OF"
TEST_DEPENDENCY_OF = "TEST_DEPENDENCY_OF"
DEV_DEPENDENCY_OF = "DEV_DEPENDENCY_OF"
OPTIONAL_DEPENDENCY_OF = "OPTIONAL_DEPENDENCY_OF"
STATIC_LINK = "STATIC_LINK"
DYNAMIC_LINK = "DYNAMIC_LINK"
CONTAINS = "CONTAINS"
CONTAINED_BY = "CONTAINED_BY"
GENERATED_FROM = "GENERATED_FROM"

# -----------------------------------------------------------
# Scope → relationship mapping (Java: Maven + Gradle)
# -----------------------------------------------------------
# Maps Maven/Gradle dependency scopes to SPDX relationship
# types per SPDX 2.3 Table 68.
_JAVA_SCOPE_MAP = {
    "compile": DEPENDS_ON,
    "runtime": DEPENDS_ON,
    "provided": DEPENDS_ON,
    "system": DEPENDS_ON,
    # Gradle-specific
    "implementation": DEPENDS_ON,
    "api": DEPENDS_ON,
    "runtimeOnly": DEPENDS_ON,
    "compileOnly": DEPENDS_ON,
    "compileOnlyApi": DEPENDS_ON,
}

# Scopes that we exclude from the SPDX entirely
# (they don't ship in the binary).
_JAVA_EXCLUDED_SCOPES = frozenset({"test"})


def java_dep_relationship(scope):
    """Return the SPDX relationship type for a Java dependency.

    Args:
        scope: Maven or Gradle dependency scope string.

    Returns:
        The SPDX 2.3 relationship type string, or *None*
        if the scope should be excluded from the SBOM.
    """
    if scope in _JAVA_EXCLUDED_SCOPES:
        return None
    return _JAVA_SCOPE_MAP.get(scope, DEPENDS_ON)


# -----------------------------------------------------------
# Build-tool classification
# -----------------------------------------------------------
# These groupIds identify *build tools* — software used to
# compile, link, or package the project.  If we ever extract
# Maven/Gradle plugins as SPDX packages, they should use
# BUILD_TOOL_OF rather than DEPENDS_ON.
BUILD_TOOL_GROUP_IDS = frozenset({
    # Java build systems
    "org.apache.maven",
    "org.apache.maven.plugins",
    "org.codehaus.mojo",
    "org.gradle",
    # Compilers / code generators
    "org.apache.maven.plugin-tools",
})

# Binary names that are build tools (C/C++/Go)
BUILD_TOOL_BINARIES = frozenset({
    "gcc", "g++", "cc", "c++",
    "ld", "ld.lld", "gold",
    "ar", "ranlib",
    "as",
    "make", "cmake", "ninja",
    "go",
    "rustc", "cargo",
    "javac",
})


def is_build_tool(*, group_id=None, binary_name=None):
    """Check if a dependency is a build tool.

    Build tools compile, link, or package the software.
    They are NOT runtime dependencies.

    Args:
        group_id: Maven/Gradle groupId (Java).
        binary_name: Executable name (C/C++/Go/Rust).

    Returns:
        True if the dependency is a build tool.
    """
    if group_id and group_id in BUILD_TOOL_GROUP_IDS:
        return True
    if binary_name and binary_name in BUILD_TOOL_BINARIES:
        return True
    return False
