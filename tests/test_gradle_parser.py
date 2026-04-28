"""Tests for Gradle dependency parser."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from app.spdx.gradle_parser import (
    parse_gradle_dep_tree,
    get_gradle_version,
    get_gradle_group,
    is_gradle_project,
    _parse_build_gradle,
    get_gradle_deps,
)


class TestParseGradleDepTree(unittest.TestCase):
    """Tests for parse_gradle_dep_tree."""

    def test_empty_output(self):
        result = parse_gradle_dep_tree("")
        self.assertEqual(result, [])

    def test_no_config_section(self):
        result = parse_gradle_dep_tree(
            "some random text\n"
        )
        self.assertEqual(result, [])

    def test_single_direct_dep(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- com.google.guava:guava:30.1-jre\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 1)
        dep = result[0]
        self.assertEqual(
            dep["groupId"], "com.google.guava"
        )
        self.assertEqual(dep["artifactId"], "guava")
        self.assertEqual(dep["version"], "30.1-jre")
        self.assertEqual(dep["scope"], "compile")
        self.assertTrue(dep["direct"])
        self.assertFalse(dep["optional"])
        self.assertIsNone(dep["parent"])

    def test_transitive_dep(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- com.google.guava:guava:30.1-jre\n"
            "|    +--- com.google.guava:failureaccess"
            ":1.0.1\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 2)
        child = result[1]
        self.assertEqual(
            child["artifactId"], "failureaccess"
        )
        self.assertEqual(child["version"], "1.0.1")
        self.assertFalse(child["direct"])
        self.assertEqual(child["parent"], "guava")
        self.assertEqual(child["depth"], 1)

    def test_version_conflict_resolution(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "\\--- com.google.code.findbugs"
            ":jsr305:3.0.1 -> 3.0.2\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 1)
        dep = result[0]
        self.assertEqual(dep["artifactId"], "jsr305")
        self.assertEqual(dep["version"], "3.0.2")

    def test_omitted_dep_star(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- org.springframework"
            ":spring-aop:5.3.4\n"
            "|    +--- org.springframework"
            ":spring-beans:5.3.4\n"
            "|    |    \\--- org.springframework"
            ":spring-core:5.3.4\n"
            "|    \\--- org.springframework"
            ":spring-core:5.3.4 (*)\n"
        )
        result = parse_gradle_dep_tree(output)
        # spring-core appears twice but should be
        # deduplicated to 3 unique entries
        self.assertEqual(len(result), 3)
        names = [d["artifactId"] for d in result]
        self.assertEqual(
            names,
            ["spring-aop", "spring-beans",
             "spring-core"],
        )

    def test_deep_tree(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- a.b:c:1.0\n"
            "|    +--- d.e:f:2.0\n"
            "|    |    \\--- g.h:i:3.0\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["depth"], 0)
        self.assertEqual(result[1]["depth"], 1)
        self.assertEqual(result[2]["depth"], 2)
        self.assertTrue(result[0]["direct"])
        self.assertFalse(result[1]["direct"])
        self.assertFalse(result[2]["direct"])
        self.assertEqual(result[1]["parent"], "c")
        self.assertEqual(result[2]["parent"], "f")

    def test_no_dependencies(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "No dependencies\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(result, [])

    def test_skips_project_deps(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- project :submodule\n"
            "+--- com.google.guava:guava:30.1-jre\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["artifactId"], "guava"
        )

    def test_multiple_direct_deps(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- org.slf4j:slf4j-api:2.0.9\n"
            "+--- ch.qos.logback:logback-classic"
            ":1.4.11\n"
            "\\--- com.google.guava:guava:32.1.3-jre\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 3)
        for dep in result:
            self.assertTrue(dep["direct"])
            self.assertEqual(dep["scope"], "compile")

    def test_stops_at_blank_line(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- com.google.guava:guava:30.1-jre\n"
            "\n"
            "testRuntimeClasspath - Test runtime.\n"
            "+--- junit:junit:4.13.2\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["artifactId"], "guava"
        )

    def test_version_conflict_with_star(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- com.google.guava:guava:30.1-jre\n"
            "|    +--- com.google.code.findbugs"
            ":jsr305:3.0.2\n"
            "\\--- com.google.code.findbugs"
            ":jsr305:3.0.1 -> 3.0.2 (*)\n"
        )
        result = parse_gradle_dep_tree(output)
        # jsr305 resolved to 3.0.2 appears twice
        # but dedup keeps only the first
        self.assertEqual(len(result), 2)
        self.assertEqual(
            result[1]["artifactId"], "jsr305"
        )
        self.assertEqual(result[1]["version"], "3.0.2")

    def test_dedup_same_artifact_different_parents(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- org.a:lib-a:1.0\n"
            "|    \\--- org.c:shared:2.0\n"
            "\\--- org.b:lib-b:1.0\n"
            "     \\--- org.c:shared:2.0 (*)\n"
        )
        result = parse_gradle_dep_tree(output)
        names = [d["artifactId"] for d in result]
        self.assertEqual(
            names, ["lib-a", "shared", "lib-b"]
        )
        # First occurrence kept (parent = lib-a)
        shared = result[1]
        self.assertEqual(shared["parent"], "lib-a")

    def test_keeps_bom_entries(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- com.fasterxml.jackson"
            ":jackson-bom:2.18.3\n"
            "+--- io.netty:netty-bom"
            ":4.1.119.Final\n"
            "+--- org.slf4j:slf4j-api:2.0.9\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 3)
        names = [d["artifactId"] for d in result]
        self.assertIn("jackson-bom", names)
        self.assertIn("netty-bom", names)
        self.assertIn("slf4j-api", names)

    def test_keeps_dependencies_suffix(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- org.spring:spring-dependencies"
            ":3.4.4\n"
            "+--- org.slf4j:slf4j-api:2.0.9\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 2)
        names = [d["artifactId"] for d in result]
        self.assertIn("spring-dependencies", names)
        self.assertIn("slf4j-api", names)

    def test_filters_constraint_entries(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- org.slf4j:slf4j-api:2.0.9\n"
            "+--- com.google.guava:guava:30.1-jre"
            " (c)\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["artifactId"], "slf4j-api"
        )

    def test_keeps_underscore_bom(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- io.prometheus:simpleclient_bom"
            ":0.16.0\n"
            "+--- org.slf4j:slf4j-api:2.0.9\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 2)
        names = [d["artifactId"] for d in result]
        self.assertIn("simpleclient_bom", names)
        self.assertIn("slf4j-api", names)

    def test_filters_rich_version_strictly(self):
        output = (
            "runtimeClasspath - Runtime classpath.\n"
            "+--- org.codehaus.janino"
            ":janino:{strictly 3.1.10}\n"
            "+--- org.slf4j:slf4j-api:2.0.9\n"
        )
        result = parse_gradle_dep_tree(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["artifactId"], "slf4j-api"
        )


class TestParseBuildGradle(unittest.TestCase):
    """Tests for _parse_build_gradle fallback."""

    def test_no_build_file(self):
        with tempfile.TemporaryDirectory() as td:
            result = _parse_build_gradle(Path(td))
        self.assertEqual(result, [])

    def test_parse_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle"
            bg.write_text(
                "dependencies {\n"
                "    implementation "
                "'com.google.guava:guava:30.1-jre'\n"
                "}\n"
            )
            result = _parse_build_gradle(Path(td))
        self.assertEqual(len(result), 1)
        dep = result[0]
        self.assertEqual(
            dep["groupId"], "com.google.guava"
        )
        self.assertEqual(dep["artifactId"], "guava")
        self.assertEqual(dep["version"], "30.1-jre")
        self.assertEqual(dep["scope"], "compile")
        self.assertTrue(dep["direct"])

    def test_parse_test_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle"
            bg.write_text(
                "dependencies {\n"
                "    testImplementation "
                "'junit:junit:4.13.2'\n"
                "}\n"
            )
            result = _parse_build_gradle(Path(td))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["scope"], "test")

    def test_parse_multiple_configs(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle"
            bg.write_text(
                "dependencies {\n"
                "    implementation "
                "'com.google.guava:guava:30.1-jre'\n"
                "    runtimeOnly "
                "'org.postgresql:postgresql:42.7.1'\n"
                "    compileOnly "
                "'org.projectlombok:lombok:1.18.30'\n"
                "    testImplementation "
                "'junit:junit:4.13.2'\n"
                "}\n"
            )
            result = _parse_build_gradle(Path(td))
        self.assertEqual(len(result), 4)
        scopes = [d["scope"] for d in result]
        self.assertIn("compile", scopes)
        self.assertIn("runtime", scopes)
        self.assertIn("provided", scopes)
        self.assertIn("test", scopes)

    def test_parse_kts(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle.kts"
            bg.write_text(
                "dependencies {\n"
                '    implementation("com.google.guava'
                ':guava:30.1-jre")\n'
                "}\n"
            )
            result = _parse_build_gradle(Path(td))
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["artifactId"], "guava"
        )


class TestGetGradleVersion(unittest.TestCase):
    """Tests for get_gradle_version."""

    def test_from_gradle_properties(self):
        with tempfile.TemporaryDirectory() as td:
            props = Path(td) / "gradle.properties"
            props.write_text("version=1.2.3\n")
            result = get_gradle_version(td)
        self.assertEqual(result, "1.2.3")

    def test_strips_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            props = Path(td) / "gradle.properties"
            props.write_text(
                "version=1.2.3-SNAPSHOT\n"
            )
            result = get_gradle_version(td)
        self.assertEqual(result, "1.2.3")

    def test_from_build_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle"
            bg.write_text("version = '2.0.0'\n")
            result = get_gradle_version(td)
        self.assertEqual(result, "2.0.0")

    def test_from_build_gradle_kts(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle.kts"
            bg.write_text('version = "3.0.0"\n')
            result = get_gradle_version(td)
        self.assertEqual(result, "3.0.0")

    def test_unknown_when_no_files(self):
        with tempfile.TemporaryDirectory() as td:
            result = get_gradle_version(td)
        self.assertEqual(result, "unknown")

    def test_properties_takes_precedence(self):
        with tempfile.TemporaryDirectory() as td:
            props = Path(td) / "gradle.properties"
            props.write_text("version=1.0.0\n")
            bg = Path(td) / "build.gradle"
            bg.write_text("version = '2.0.0'\n")
            result = get_gradle_version(td)
        self.assertEqual(result, "1.0.0")


class TestGetGradleGroup(unittest.TestCase):
    """Tests for get_gradle_group."""

    def test_from_gradle_properties(self):
        with tempfile.TemporaryDirectory() as td:
            props = Path(td) / "gradle.properties"
            props.write_text("group=com.example\n")
            result = get_gradle_group(td)
        self.assertEqual(result, "com.example")

    def test_from_build_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            bg = Path(td) / "build.gradle"
            bg.write_text(
                "group = 'org.springframework.boot'\n"
            )
            result = get_gradle_group(td)
        self.assertEqual(
            result, "org.springframework.boot"
        )

    def test_none_when_no_files(self):
        with tempfile.TemporaryDirectory() as td:
            result = get_gradle_group(td)
        self.assertIsNone(result)


class TestIsGradleProject(unittest.TestCase):
    """Tests for is_gradle_project."""

    def test_gradlew(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            self.assertTrue(is_gradle_project(td))

    def test_build_gradle(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "build.gradle").touch()
            self.assertTrue(is_gradle_project(td))

    def test_build_gradle_kts(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "build.gradle.kts").touch()
            self.assertTrue(is_gradle_project(td))

    def test_maven_project(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pom.xml").touch()
            self.assertFalse(is_gradle_project(td))

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(is_gradle_project(td))


class TestGetGradleDeps(unittest.TestCase):
    """Tests for get_gradle_deps (subprocess integration)."""

    def test_no_gradlew(self):
        with tempfile.TemporaryDirectory() as td:
            result = get_gradle_deps(td)
        self.assertEqual(result, [])

    @patch("app.spdx.gradle_parser.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "runtimeClasspath - Runtime.\n"
                "+--- com.google.guava:guava:30.1\n"
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            result = get_gradle_deps(td)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["artifactId"], "guava"
        )

    @patch("app.spdx.gradle_parser.subprocess.run")
    def test_failure_falls_back(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="BUILD FAILED",
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            bg = Path(td) / "build.gradle"
            bg.write_text(
                "dependencies {\n"
                "    implementation "
                "'com.google.guava:guava:30.1-jre'\n"
                "}\n"
            )
            result = get_gradle_deps(td)
        self.assertEqual(len(result), 1)

    @patch("app.spdx.gradle_parser.subprocess.run")
    def test_with_project(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "runtimeClasspath - Runtime.\n"
                "+--- org.slf4j:slf4j-api:2.0.9\n"
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "gradlew").touch()
            result = get_gradle_deps(
                td, project="submod"
            )
        self.assertEqual(len(result), 1)
        call_args = mock_run.call_args[0][0]
        self.assertIn(
            "submod:dependencies", call_args
        )


if __name__ == "__main__":
    unittest.main()
