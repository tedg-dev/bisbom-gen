"""SPDX 2.3 relationship type constants and classifiers.

Centralises the rules for choosing SPDX relationship types so
that every generator uses the same spec-aligned logic.

Reference: SPDX 2.3 Clause 11, Table 68
https://spdx.github.io/spdx-spec/v2.3/relationships-between-SPDX-elements/

Key spec guidance (Table 68 examples):
  - compile scope      → DEPENDS_ON
  - runtime scope      → DEPENDS_ON
  - provided scope     → DEPENDS_ON (unless build tool)
  - test scope         → TEST_DEPENDENCY_OF
  - devDependencies    → DEV_DEPENDENCY_OF
  - optional           → OPTIONAL_DEPENDENCY_OF
  - compiler / linker  → BUILD_TOOL_OF
  - makefile           → BUILD_TOOL_OF
  - build tool dep     → BUILD_TOOL_OF

BUILD_TOOL_OF applies to packages that compile, link, or
package the software — gcc, go, javac, maven, gradle,
make, etc.  Build tools are detected and emitted by
each generator's ``_add_build_tools()`` method, not
inferred from library dependencies.

Maven/Gradle dependency tree entries are always library
dependencies — they get scope-based relationship types.
Even if a dependency (e.g. ant) is a build tool for
OTHER projects, if it appears in the dependency tree
it means THIS project uses it as a library (DEPENDS_ON).
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
    """Return the SPDX relationship type for a Java dep.

    All Maven/Gradle dependency tree entries are library
    dependencies — their relationship type is determined
    solely by scope.  Build tools (javac, maven, gradle)
    are emitted separately by ``_add_build_tools()``.

    Args:
        scope: Maven or Gradle dependency scope string.

    Returns:
        The SPDX 2.3 relationship type string, or *None*
        if the scope should be excluded from the SBOM.
    """
    if scope in _JAVA_EXCLUDED_SCOPES:
        return None
    return _JAVA_SCOPE_MAP.get(scope, DEPENDS_ON)
