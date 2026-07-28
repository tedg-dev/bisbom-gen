# SPDX 2.3 Relationship Type Policy

All SPDX relationship types MUST follow the SPDX 2.3 specification
(Clause 11, Table 68). Use `app/spdx/relationships.py` as the
single source of truth for constants and scope-to-relationship mapping.

## Key Rules

### BUILD_TOOL_OF — only for compilers and build systems

BUILD_TOOL_OF means "A is used to build B". It applies ONLY to:

- **Compilers**: gcc, g++, go, rustc, javac
- **Linkers**: ld, ld.lld, gold
- **Build systems**: make, cmake, maven, gradle, cargo

It does NOT apply to library dependencies, even if the library
is a build tool in other contexts (e.g. `ant` as a Maven
`provided` dependency of checkstyle — checkstyle depends on
ant's API, ant does not build checkstyle).

### DEPENDS_ON — for all library dependencies

All Maven/Gradle dependency scopes that represent library
dependencies map to DEPENDS_ON:

| Scope | Relationship | Rationale |
|-------|-------------|-----------|
| compile | DEPENDS_ON | Needed at compile + runtime |
| runtime | DEPENDS_ON | Needed at runtime |
| provided | DEPENDS_ON | Needed but supplied by environment |
| system | DEPENDS_ON | Like provided, from local filesystem |
| implementation | DEPENDS_ON | Gradle compile scope |
| api | DEPENDS_ON | Gradle transitive compile scope |
| compileOnly | DEPENDS_ON | Gradle compile-only |
| runtimeOnly | DEPENDS_ON | Gradle runtime-only |

### test scope — excluded

Test-scope dependencies are excluded from the SPDX entirely
(they don't ship in the binary).

### Scope metadata

The dependency scope is recorded in the SPDX package `comment`
field for transparency, not in the relationship type.

## Other Language Relationships

| Language | Dependency Type | Relationship |
|----------|----------------|-------------|
| C/C++ | Dynamic library | DYNAMIC_LINK |
| C/C++ | Vendored source | STATIC_LINK + CONTAINS |
| Go | Module dependency | DEPENDS_ON |
| Go | Go toolchain | BUILD_TOOL_OF |
| Rust | Crate dependency | STATIC_LINK |

## Implementation

All generators MUST import constants from
`app/spdx/relationships.py` — never hardcode relationship
type strings.
