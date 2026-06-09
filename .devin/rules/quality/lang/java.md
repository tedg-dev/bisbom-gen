---
description: Java-specific best practices, tooling, and conventions
---

# Java Best Practices

## Project Structure

- **Java version**: Target Java 17+ (LTS) unless the project requires older.
  Set `<maven.compiler.release>17</maven.compiler.release>` in pom.xml
- **Build tool**: Maven (preferred for OmniBOR) or Gradle. Pin wrapper
  versions (`mvnw`, `gradlew`)
- **Layout**: Follow Maven standard directory layout:
  `src/main/java/`, `src/main/resources/`, `src/test/java/`
- **Multi-module**: Use `<modules>` in a parent POM. Each module gets its
  own `pom.xml` with shared dependency management in the parent

## Formatting & Linting

- **Formatter**: google-java-format or Spotless Maven plugin
  (`mvn spotless:apply`)
- **Linter**: Checkstyle with Google or Sun conventions, or SpotBugs for
  bug detection
- **Static analysis**: Error Prone compiler plugin for compile-time bug
  detection

## Idioms

- **Immutability**: Prefer `final` fields, `List.of()`, `Map.of()` for
  collections. Use records for value types (Java 16+)
- **Optionals**: Use `Optional<T>` for return types that may be absent.
  Never use `Optional` as a method parameter or field
- **Streams**: Use streams for collection transformations. Avoid streams
  for simple iterations where a for-loop is clearer
- **Resource management**: Always use try-with-resources for `AutoCloseable`
  resources (files, connections, streams)
- **Logging**: SLF4J + Logback (or Log4j2). Never use `System.out.println`
  in library code
- **Null safety**: Use `@Nullable` / `@NonNull` annotations. Check
  parameters with `Objects.requireNonNull()`

## Error Handling

- Use checked exceptions for recoverable conditions, unchecked for
  programming errors
- Never catch `Exception` or `Throwable` without re-throwing or specific
  handling
- Provide meaningful messages: `throw new IllegalArgumentException("groupId must not be blank")`
- Document thrown exceptions in Javadoc `@throws`

## Testing

- **Framework**: JUnit 5 (Jupiter) with AssertJ for fluent assertions
- **Mocking**: Mockito for mocking dependencies
- **Test scope**: Maven `<scope>test</scope>` for test-only dependencies —
  these must NOT appear in production JARs
- **Temp files**: `@TempDir` JUnit extension for temporary directories
- **Integration tests**: Use Maven Failsafe plugin (`*IT.java` suffix)
  separate from unit tests

## Maven Dependency Management

- **Version properties**: Define versions as properties in the parent POM
  (`<junit.version>5.10.2</junit.version>`)
- **Dependency management**: Use `<dependencyManagement>` in parent POM
  to control versions across modules
- **BOM imports**: Use `<type>pom</type><scope>import</scope>` for
  dependency BOMs (e.g., `spring-boot-dependencies`)
- **No SNAPSHOT deps**: Never depend on SNAPSHOT versions in releases

## CI Configuration

- **Setup**: `actions/setup-java` with pinned JDK distribution and version
  (e.g., `temurin`, `17`)
- **Cache**: `~/.m2/repository` keyed on `pom.xml` hash (use
  `actions/cache` or `setup-java` built-in caching)
- **Build job**: `mvn verify -B -q` (`-B` for batch mode, `-q` for quiet)
- **Lint job**: `mvn checkstyle:check` or `mvn spotless:check`
- **Test job**: `mvn test -B` (Surefire) + `mvn verify -B` (Failsafe for ITs)

## Release Builds (OmniBOR)

- Always `mvn package -DskipTests` (skip test execution in release builds)
- Standard Maven JAR packaging includes `target/classes/` only (main sources)
- Test classes (`target/test-classes/`) are NOT in the production JAR
- SPDX generation must exclude `test`-scope dependencies
- If a shade/assembly plugin includes test artifacts, annotate in SPDX comments

## Dependency Audit

- `mvn dependency-check:check` (OWASP Dependency-Check plugin)
- `mvn versions:display-dependency-updates` for outdated dependencies
- `mvn dependency:analyze` for unused/undeclared dependencies
