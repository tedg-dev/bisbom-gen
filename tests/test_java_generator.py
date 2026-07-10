"""Tests for Java SPDX generator."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from app.spdx.identity import ArtifactIdentity
from app.spdx.java_generator import JavaSpdxGenerator


class TestJavaSpdxGeneratorInit(unittest.TestCase):
    """Tests for JavaSpdxGenerator initialization."""

    def test_init_sets_paths(self):
        gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )
        self.assertEqual(gen.bom_dir, Path("/tmp/bom"))
        self.assertEqual(
            gen.repos_dir, Path("/tmp/repos")
        )
        self.assertEqual(gen.repo_name, "myapp")
        self.assertEqual(
            gen.repo_dir, Path("/tmp/repos/myapp")
        )


class TestParseDeptree(unittest.TestCase):
    """Tests for _parse_dep_tree."""

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )

    def test_empty_output(self):
        result = self.gen._parse_dep_tree("")
        self.assertEqual(result, [])

    def test_no_info_prefix(self):
        result = self.gen._parse_dep_tree(
            "some random text\n"
        )
        self.assertEqual(result, [])

    def test_direct_dependency(self):
        output = (
            "[INFO] +- org.junit:junit:jar:4.13:compile\n"
        )
        result = self.gen._parse_dep_tree(output)
        self.assertEqual(len(result), 1)
        dep = result[0]
        self.assertEqual(dep["groupId"], "org.junit")
        self.assertEqual(dep["artifactId"], "junit")
        self.assertEqual(dep["version"], "4.13")
        self.assertEqual(dep["scope"], "compile")
        self.assertTrue(dep["direct"])
        self.assertFalse(dep["optional"])
        self.assertIsNone(dep["parent"])

    def test_transitive_dependency(self):
        output = (
            "[INFO] +- org.junit:junit:jar:4.13:compile\n"
            "[INFO] |  \\- org.hamcrest:hamcrest-core"
            ":jar:1.3:compile\n"
        )
        result = self.gen._parse_dep_tree(output)
        self.assertEqual(len(result), 2)
        child = result[1]
        self.assertEqual(
            child["artifactId"], "hamcrest-core"
        )
        self.assertFalse(child["direct"])
        self.assertEqual(child["parent"], "junit")

    def test_optional_dependency(self):
        output = (
            "[INFO] +- org.opt:optional:jar:1.0"
            ":compile (optional)\n"
        )
        result = self.gen._parse_dep_tree(output)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["optional"])

    def test_multiple_depths(self):
        output = (
            "[INFO] +- a:liba:jar:1.0:compile\n"
            "[INFO] |  +- b:libb:jar:2.0:runtime\n"
            "[INFO] |  |  \\- c:libc:jar:3.0:compile\n"
            "[INFO] |  \\- d:libd:jar:4.0:compile\n"
        )
        result = self.gen._parse_dep_tree(output)
        self.assertEqual(len(result), 4)
        self.assertTrue(result[0]["direct"])
        self.assertFalse(result[1]["direct"])
        self.assertEqual(result[1]["parent"], "liba")
        self.assertFalse(result[2]["direct"])
        self.assertEqual(result[2]["parent"], "libb")
        self.assertFalse(result[3]["direct"])
        self.assertEqual(result[3]["parent"], "liba")

    def test_non_matching_info_lines_skipped(self):
        output = (
            "[INFO] --- maven-dependency-plugin ---\n"
            "[INFO] +- a:liba:jar:1.0:compile\n"
            "[INFO] --------\n"
        )
        result = self.gen._parse_dep_tree(output)
        self.assertEqual(len(result), 1)

    def test_provided_scope(self):
        output = (
            "[INFO] +- javax:javaee:jar:8.0:provided\n"
        )
        result = self.gen._parse_dep_tree(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["scope"], "provided")


class TestParsePom(unittest.TestCase):
    """Tests for _parse_pom."""

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )

    def test_simple_pom(self):
        pom_xml = (
            '<project>\n'
            '  <dependencies>\n'
            '    <dependency>\n'
            '      <groupId>org.junit</groupId>\n'
            '      <artifactId>junit</artifactId>\n'
            '      <version>4.13</version>\n'
            '      <scope>test</scope>\n'
            '    </dependency>\n'
            '  </dependencies>\n'
            '</project>\n'
        )
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(pom_xml)
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["groupId"], "org.junit")
        self.assertEqual(result[0]["scope"], "test")
        self.assertTrue(result[0]["direct"])

    def test_pom_with_namespace(self):
        pom_xml = (
            '<project xmlns="http://maven.apache.org'
            '/POM/4.0.0">\n'
            '  <dependencies>\n'
            '    <dependency>\n'
            '      <groupId>com.google</groupId>\n'
            '      <artifactId>guava</artifactId>\n'
            '      <version>33.0</version>\n'
            '    </dependency>\n'
            '  </dependencies>\n'
            '</project>\n'
        )
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(pom_xml)
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["artifactId"], "guava")
        # Default scope is compile
        self.assertEqual(result[0]["scope"], "compile")

    def test_pom_with_properties(self):
        pom_xml = (
            '<project>\n'
            '  <properties>\n'
            '    <guava.version>33.0</guava.version>\n'
            '  </properties>\n'
            '  <dependencies>\n'
            '    <dependency>\n'
            '      <groupId>com.google</groupId>\n'
            '      <artifactId>guava</artifactId>\n'
            '      <version>${guava.version}</version>\n'
            '    </dependency>\n'
            '  </dependencies>\n'
            '</project>\n'
        )
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(pom_xml)
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(result[0]["version"], "33.0")

    def test_pom_with_ns_properties(self):
        pom_xml = (
            '<project xmlns="http://maven.apache.org'
            '/POM/4.0.0">\n'
            '  <properties>\n'
            '    <guava.version>33.0</guava.version>\n'
            '  </properties>\n'
            '  <dependencies>\n'
            '    <dependency>\n'
            '      <groupId>com.google</groupId>\n'
            '      <artifactId>guava</artifactId>\n'
            '      <version>${guava.version}</version>\n'
            '    </dependency>\n'
            '  </dependencies>\n'
            '</project>\n'
        )
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(pom_xml)
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(result[0]["version"], "33.0")

    def test_pom_missing_version(self):
        pom_xml = (
            '<project>\n'
            '  <dependencies>\n'
            '    <dependency>\n'
            '      <groupId>com.google</groupId>\n'
            '      <artifactId>guava</artifactId>\n'
            '    </dependency>\n'
            '  </dependencies>\n'
            '</project>\n'
        )
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(pom_xml)
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(result[0]["version"], "unknown")

    def test_pom_parse_error(self):
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write("not valid xml <<<<")
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(result, [])

    def test_pom_missing_group_or_artifact(self):
        pom_xml = (
            '<project>\n'
            '  <dependencies>\n'
            '    <dependency>\n'
            '      <groupId>com.google</groupId>\n'
            '    </dependency>\n'
            '  </dependencies>\n'
            '</project>\n'
        )
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", delete=False
        ) as f:
            f.write(pom_xml)
            f.flush()
            result = self.gen._parse_pom(Path(f.name))
        self.assertEqual(result, [])


class TestResolveProperty(unittest.TestCase):
    """Tests for _resolve_property."""

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )

    def test_no_property(self):
        result = self.gen._resolve_property(
            "1.0.0", {}
        )
        self.assertEqual(result, "1.0.0")

    def test_none_value(self):
        result = self.gen._resolve_property(None, {})
        self.assertIsNone(result)

    def test_resolve_simple(self):
        result = self.gen._resolve_property(
            "${my.version}", {"my.version": "2.0"}
        )
        self.assertEqual(result, "2.0")

    def test_unresolved_property(self):
        result = self.gen._resolve_property(
            "${missing}", {}
        )
        self.assertEqual(result, "${missing}")

    def test_resolve_hyphen_alt(self):
        result = self.gen._resolve_property(
            "${my.version}", {"my-version": "3.0"}
        )
        self.assertEqual(result, "3.0")


class TestGetVersion(unittest.TestCase):
    """Tests for _get_version."""

    def test_version_from_pom(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>1.2.3</version>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(gen._get_version(), "1.2.3")

    def test_version_from_pom_with_ns(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text(
                '<project xmlns="http://maven.apache.org'
                '/POM/4.0.0">\n'
                '  <version>4.5.6</version>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(gen._get_version(), "4.5.6")

    def test_version_missing_pom(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(gen._get_version(), "unknown")

    def test_version_no_version_element(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <groupId>com.test</groupId>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(gen._get_version(), "unknown")

    def test_version_parse_error(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text("bad xml <<<")
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(gen._get_version(), "unknown")

    def test_version_strips_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>10.13.4-SNAPSHOT</version>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(
                gen._get_version(), "10.13.4"
            )

    def test_version_resolves_ci_friendly_revision(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>${revision}</version>\n'
                '  <properties>\n'
                '    <revision>2.24.3</revision>\n'
                '  </properties>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(
                gen._get_version(), "2.24.3"
            )

    def test_version_falls_back_to_jar_name(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            pom = repo / "pom.xml"
            pom.write_text(
                '<project>\n'
                '  <version>${revision}</version>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            self.assertEqual(
                gen._get_version(
                    artifact_path="log4j-core-2.24.3.jar"
                ),
                "2.24.3",
            )


class TestGetMavenDeps(unittest.TestCase):
    """Tests for _get_maven_deps."""

    def test_no_pom(self):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen._get_maven_deps()
            self.assertEqual(result, [])

    @patch("app.spdx.maven_parser.subprocess.run")
    def test_mvn_success(self, mock_run):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                "<project><version>1.0</version>"
                "</project>"
            )
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=(
                    "[INFO] +- a:liba:jar:1.0:compile\n"
                ),
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen._get_maven_deps()
            self.assertEqual(len(result), 1)
            self.assertEqual(
                result[0]["artifactId"], "liba"
            )

    @patch("app.spdx.maven_parser.subprocess.run")
    def test_mvn_failure_falls_back_to_pom(
        self, mock_run
    ):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                '<project>\n'
                '  <dependencies>\n'
                '    <dependency>\n'
                '      <groupId>a</groupId>\n'
                '      <artifactId>liba</artifactId>\n'
                '      <version>2.0</version>\n'
                '    </dependency>\n'
                '  </dependencies>\n'
                '</project>\n'
            )
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="BUILD FAILURE",
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen._get_maven_deps()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["version"], "2.0")

    @patch("app.spdx.maven_parser.subprocess.run")
    def test_mvn_timeout_falls_back(self, mock_run):
        import subprocess
        mock_run.side_effect = (
            subprocess.TimeoutExpired("mvn", 120)
        )
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                '<project>\n'
                '  <dependencies>\n'
                '    <dependency>\n'
                '      <groupId>a</groupId>\n'
                '      <artifactId>liba</artifactId>\n'
                '      <version>1.0</version>\n'
                '    </dependency>\n'
                '  </dependencies>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen._get_maven_deps()
            self.assertEqual(len(result), 1)

    @patch("app.spdx.maven_parser.subprocess.run")
    def test_mvn_not_found_falls_back(self, mock_run):
        mock_run.side_effect = FileNotFoundError("mvn")
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                '<project>\n'
                '  <dependencies>\n'
                '    <dependency>\n'
                '      <groupId>a</groupId>\n'
                '      <artifactId>liba</artifactId>\n'
                '      <version>1.0</version>\n'
                '    </dependency>\n'
                '  </dependencies>\n'
                '</project>\n'
            )
            gen = JavaSpdxGenerator(
                bom_dir="/tmp/bom",
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen._get_maven_deps()
            self.assertEqual(len(result), 1)


class TestBuildSpdx(unittest.TestCase):
    """Tests for _build_spdx.

    Build tool detection is mocked out (returns None)
    so tests focus on dependency graph structure without
    being affected by the local JDK/Maven installation.
    """

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )
        # Suppress build tool detection so tests don't
        # depend on local JDK/Maven installation.
        p1 = patch.object(
            JavaSpdxGenerator,
            "_detect_javac_version",
            return_value=None,
        )
        p2 = patch.object(
            JavaSpdxGenerator,
            "_detect_maven_version",
            return_value=None,
        )
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_empty_spdx(self):
        doc = self.gen._build_spdx("myapp.jar", [], [])
        self.assertEqual(
            doc["spdxVersion"], "SPDX-2.3"
        )
        self.assertEqual(len(doc["packages"]), 1)
        self.assertEqual(len(doc["files"]), 0)
        # 1 DESCRIBES
        self.assertEqual(len(doc["relationships"]), 1)
        self.assertEqual(
            doc["relationships"][0]["relationshipType"],
            "DESCRIBES",
        )

    def test_root_package_purpose(self):
        doc = self.gen._build_spdx("myapp.jar", [], [])
        root = doc["packages"][0]
        self.assertEqual(
            root["primaryPackagePurpose"], "APPLICATION"
        )

    def test_source_files_added(self):
        sources = [
            {
                "file_path": "/tmp/repos/myapp/src/A.java",
                "sha1": "abc123",
            },
            {
                "file_path": "/tmp/repos/myapp/src/B.java",
                "sha1": "def456",
            },
        ]
        doc = self.gen._build_spdx(
            "myapp.jar", sources, []
        )
        self.assertEqual(len(doc["files"]), 2)
        self.assertEqual(
            doc["files"][0]["fileName"], "src/A.java"
        )
        # 1 DESCRIBES + 2 CONTAINED_BY
        self.assertEqual(len(doc["relationships"]), 3)

    def test_source_file_no_sha1(self):
        sources = [
            {"file_path": "/other/path/X.java", "sha1": ""},
        ]
        doc = self.gen._build_spdx(
            "myapp.jar", sources, []
        )
        self.assertEqual(
            doc["files"][0]["checksums"], []
        )

    def test_direct_compile_dep_depends_on(self):
        deps = [{
            "groupId": "com.google",
            "artifactId": "guava",
            "version": "33.0",
            "scope": "compile",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(rels), 1)
        # root DEPENDS_ON dep (correct SPDX direction)
        self.assertEqual(
            rels[0]["spdxElementId"],
            "SPDXRef-Package-myapp.jar",
        )
        self.assertEqual(
            rels[0]["relatedSpdxElement"],
            "SPDXRef-Dep-0",
        )

    def test_transitive_compile_dep_depends_on(self):
        deps = [
            {
                "groupId": "a",
                "artifactId": "parent-lib",
                "version": "1.0",
                "scope": "compile",
                "direct": True,
                "optional": False,
                "parent": None,
            },
            {
                "groupId": "b",
                "artifactId": "child-lib",
                "version": "2.0",
                "scope": "compile",
                "direct": False,
                "optional": False,
                "parent": "parent-lib",
            },
        ]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        depends = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        # Both direct and transitive use DEPENDS_ON
        self.assertEqual(len(depends), 2)
        # Direct: root DEPENDS_ON parent-lib
        self.assertEqual(
            depends[0]["spdxElementId"],
            "SPDXRef-Package-myapp.jar",
        )
        self.assertEqual(
            depends[0]["relatedSpdxElement"],
            "SPDXRef-Dep-0",
        )
        # Transitive: parent DEPENDS_ON child
        self.assertEqual(
            depends[1]["spdxElementId"],
            "SPDXRef-Dep-0",
        )
        self.assertEqual(
            depends[1]["relatedSpdxElement"],
            "SPDXRef-Dep-1",
        )

    def test_provided_dep_depends_on(self):
        deps = [{
            "groupId": "javax",
            "artifactId": "javaee-api",
            "version": "8.0",
            "scope": "provided",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        dep_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(dep_rels), 1)

    def test_transitive_provided_depends_on(self):
        deps = [
            {
                "groupId": "a",
                "artifactId": "parent-lib",
                "version": "1.0",
                "scope": "compile",
                "direct": True,
                "optional": False,
                "parent": None,
            },
            {
                "groupId": "b",
                "artifactId": "tool",
                "version": "2.0",
                "scope": "provided",
                "direct": False,
                "optional": False,
                "parent": "parent-lib",
            },
        ]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        dep_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        # Both deps use DEPENDS_ON (provided scope
        # info is in the comment field)
        self.assertEqual(len(dep_rels), 2)

    def test_transitive_no_parent_match_falls_to_root(
        self,
    ):
        deps = [{
            "groupId": "b",
            "artifactId": "orphan",
            "version": "1.0",
            "scope": "compile",
            "direct": False,
            "optional": False,
            "parent": "nonexistent",
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        depends = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(depends), 1)
        # Orphan falls to root: root DEPENDS_ON orphan
        self.assertEqual(
            depends[0]["spdxElementId"],
            "SPDXRef-Package-myapp.jar",
        )
        self.assertEqual(
            depends[0]["relatedSpdxElement"],
            "SPDXRef-Dep-0",
        )

    def test_placeholder_artifact_annotated(self):
        deps = [
            {
                "groupId": "com.google",
                "artifactId": "guava",
                "version": "33.0",
                "scope": "compile",
                "direct": True,
                "optional": False,
                "parent": None,
            },
            {
                "groupId": "com.google.guava",
                "artifactId": "listenablefuture",
                "version": (
                    "9999.0-empty-to-avoid"
                    "-conflict-with-guava"
                ),
                "scope": "compile",
                "direct": False,
                "optional": False,
                "parent": "guava",
            },
        ]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        pkg_names = [
            p["name"] for p in doc["packages"]
        ]
        self.assertIn("guava", pkg_names)
        self.assertIn(
            "listenablefuture", pkg_names,
        )
        lf_pkg = [
            p for p in doc["packages"]
            if p["name"] == "listenablefuture"
        ][0]
        self.assertIn(
            "Placeholder artifact", lf_pkg["comment"]
        )

    def test_bom_artifact_annotated(self):
        deps = [{
            "groupId": "io.prometheus",
            "artifactId": "simpleclient_bom",
            "version": "0.16.0",
            "scope": "compile",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        pkg = doc["packages"][1]
        self.assertEqual(
            pkg["name"], "simpleclient_bom"
        )
        self.assertIn(
            "BOM/platform artifact", pkg["comment"]
        )

    def test_optional_dep_comment(self):
        deps = [{
            "groupId": "com.opt",
            "artifactId": "optlib",
            "version": "1.0",
            "scope": "compile",
            "direct": True,
            "optional": True,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        pkg = doc["packages"][1]
        self.assertIn("Optional", pkg["comment"])

    def test_dep_package_fields(self):
        deps = [{
            "groupId": "com.google",
            "artifactId": "guava",
            "version": "33.0",
            "scope": "compile",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        pkg = doc["packages"][1]
        self.assertEqual(pkg["name"], "guava")
        self.assertEqual(pkg["versionInfo"], "33.0")
        self.assertIn(
            "maven2", pkg["downloadLocation"]
        )
        self.assertFalse(pkg["filesAnalyzed"])
        self.assertEqual(
            pkg["supplier"],
            "Organization: com.google",
        )
        self.assertIn("Maven Central", pkg["sourceInfo"])
        purl = pkg["externalRefs"][0]["referenceLocator"]
        self.assertEqual(
            purl, "pkg:maven/com.google/guava@33.0"
        )

    def test_dep_with_parent_comment(self):
        deps = [{
            "groupId": "b",
            "artifactId": "child",
            "version": "1.0",
            "scope": "compile",
            "direct": False,
            "optional": False,
            "parent": "parent-lib",
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        pkg = doc["packages"][1]
        self.assertIn(
            "Required by: parent-lib", pkg["comment"]
        )

    def test_runtime_scope_direct_depends_on(self):
        deps = [{
            "groupId": "a",
            "artifactId": "rtlib",
            "version": "1.0",
            "scope": "runtime",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(rels), 1)

    def test_analyzed_sbom_no_deps(self):
        sources = [
            {
                "file_path": "/tmp/repos/myapp/A.java",
                "sha1": "abc",
            },
        ]
        deps = [{
            "groupId": "a",
            "artifactId": "liba",
            "version": "1.0",
            "scope": "compile",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", sources, deps,
            sbom_type="analyzed",
        )
        # Analyzed: root + source files only, no deps
        self.assertEqual(len(doc["packages"]), 1)
        self.assertEqual(len(doc["files"]), 1)
        dep_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(dep_rels), 0)

    def test_no_static_link_in_build_sbom(self):
        deps = [{
            "groupId": "a",
            "artifactId": "liba",
            "version": "1.0",
            "scope": "compile",
            "direct": True,
            "optional": False,
            "parent": None,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps,
            sbom_type="build",
        )
        static = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "STATIC_LINK"
        ]
        self.assertEqual(len(static), 0)

    def test_transitive_no_parent_key(self):
        deps = [{
            "groupId": "b",
            "artifactId": "orphan",
            "version": "1.0",
            "scope": "compile",
            "direct": False,
            "optional": False,
        }]
        doc = self.gen._build_spdx(
            "myapp.jar", [], deps
        )
        depends = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(depends), 1)


class TestArtifactIdentity(unittest.TestCase):
    """Root JAR package must carry OmniBOR identity.

    Regression tests for project/artifact-identity.md: the
    built JAR's own raw SHA-256 checksum and SHA-256 OmniBOR
    gitOID (``gitoid:blob:sha256``) must appear on the root
    package, both computed by reading the built JAR (the
    identity layer), mirroring the C emitter.
    """

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )
        p1 = patch.object(
            JavaSpdxGenerator,
            "_detect_javac_version",
            return_value=None,
        )
        p2 = patch.object(
            JavaSpdxGenerator,
            "_detect_maven_version",
            return_value=None,
        )
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.jar_path = Path(self._tmp.name) / "myapp.jar"
        self.jar_path.write_bytes(b"PK\x03\x04 fake jar bytes")
        self.ident = ArtifactIdentity.from_file(self.jar_path)

    @staticmethod
    def _gitoid_refs(root):
        return [
            r for r in root["externalRefs"]
            if r["referenceType"] == "gitoid"
        ]

    def test_root_has_checksum_and_gitoid(self):
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
            jar_path=str(self.jar_path),
        )
        root = doc["packages"][0]
        self.assertEqual(
            root["checksums"],
            [{
                "algorithm": "SHA256",
                "checksumValue": self.ident.raw,
            }],
        )
        refs = self._gitoid_refs(root)
        self.assertEqual(len(refs), 1)
        self.assertEqual(
            refs[0]["referenceCategory"],
            "PERSISTENT-ID",
        )
        self.assertEqual(
            refs[0]["referenceLocator"],
            self.ident.gitoid,
        )
        self.assertTrue(
            self.ident.gitoid.startswith(
                "gitoid:blob:sha256:"
            )
        )

    def test_identity_on_analyzed_sbom(self):
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
            sbom_type="analyzed",
            jar_path=str(self.jar_path),
        )
        root = doc["packages"][0]
        self.assertEqual(
            root["checksums"][0]["checksumValue"],
            self.ident.raw,
        )
        self.assertEqual(
            len(self._gitoid_refs(root)), 1
        )

    def test_missing_identity_leaves_empty(self):
        doc = self.gen._build_spdx("myapp.jar", [], [])
        root = doc["packages"][0]
        self.assertEqual(root["checksums"], [])
        self.assertEqual(
            len(self._gitoid_refs(root)), 0
        )

    def test_unreadable_jar_leaves_empty(self):
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
            jar_path="/nonexistent/myapp.jar",
        )
        root = doc["packages"][0]
        self.assertEqual(root["checksums"], [])
        self.assertEqual(
            len(self._gitoid_refs(root)), 0
        )

    def test_purl_ref_still_present_with_identity(self):
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
            jar_path=str(self.jar_path),
        )
        root = doc["packages"][0]
        purls = [
            r for r in root["externalRefs"]
            if r["referenceType"] == "purl"
        ]
        self.assertEqual(len(purls), 1)

    def test_source_file_dual_hash_sha1_and_sha256(self):
        # SPDX 2.3 File entries carry the spec-mandated raw SHA-1
        # plus the raw SHA-256 identity hash
        # (project/artifact-identity.md §5.1).
        src = Path(self._tmp.name) / "App.java"
        content = b"class App {}\n"
        src.write_bytes(content)
        doc = self.gen._build_spdx(
            "myapp.jar",
            [{"file_path": str(src)}],
            [],
        )
        self.assertEqual(len(doc["files"]), 1)
        self.assertEqual(
            doc["files"][0]["checksums"],
            [
                {
                    "algorithm": "SHA1",
                    "checksumValue": hashlib.sha1(
                        content
                    ).hexdigest(),
                },
                {
                    "algorithm": "SHA256",
                    "checksumValue": hashlib.sha256(
                        content
                    ).hexdigest(),
                },
            ],
        )


class TestBuildToolEmission(unittest.TestCase):
    """Tests for javac/maven BUILD_TOOL_OF emission."""

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )

    @patch.object(
        JavaSpdxGenerator, "_detect_maven_version",
        return_value="3.9.15",
    )
    @patch.object(
        JavaSpdxGenerator, "_detect_javac_version",
        return_value="17.0.13",
    )
    def test_javac_and_maven_emitted(
        self, _m_javac, _m_mvn,
    ):
        """Both javac and maven should appear as
        BUILD_TOOL_OF on build SBOMs."""
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
        )
        bt_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(bt_rels), 2)
        bt_names = {
            p["name"] for p in doc["packages"]
            if p["SPDXID"].startswith(
                "SPDXRef-BuildTool-"
            )
        }
        self.assertEqual(
            bt_names, {"javac", "maven"},
        )

    @patch.object(
        JavaSpdxGenerator, "_detect_maven_version",
        return_value="3.9.15",
    )
    @patch.object(
        JavaSpdxGenerator, "_detect_javac_version",
        return_value="17.0.13",
    )
    def test_javac_version_in_package(
        self, _m_javac, _m_mvn,
    ):
        """javac package should have correct version."""
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
        )
        jdk_pkg = [
            p for p in doc["packages"]
            if p["name"] == "javac"
        ][0]
        self.assertEqual(
            jdk_pkg["versionInfo"], "17.0.13",
        )
        self.assertIn(
            "cpe:2.3:a:oracle:jdk:17.0.13",
            jdk_pkg["externalRefs"][0][
                "referenceLocator"
            ],
        )

    @patch.object(
        JavaSpdxGenerator, "_detect_maven_version",
        return_value="3.9.15",
    )
    @patch.object(
        JavaSpdxGenerator, "_detect_javac_version",
        return_value="17.0.13",
    )
    def test_maven_version_in_package(
        self, _m_javac, _m_mvn,
    ):
        """maven package should have correct version."""
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
        )
        mvn_pkg = [
            p for p in doc["packages"]
            if p["name"] == "maven"
        ][0]
        self.assertEqual(
            mvn_pkg["versionInfo"], "3.9.15",
        )

    @patch.object(
        JavaSpdxGenerator, "_detect_maven_version",
        return_value="3.9.15",
    )
    @patch.object(
        JavaSpdxGenerator, "_detect_javac_version",
        return_value="17.0.13",
    )
    def test_analyzed_strips_build_tools(
        self, _m_javac, _m_mvn,
    ):
        """Analyzed SBOMs should NOT contain
        BUILD_TOOL_OF relationships or packages."""
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
            sbom_type="analyzed",
        )
        bt_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(bt_rels), 0)
        bt_pkgs = [
            p for p in doc["packages"]
            if p["SPDXID"].startswith(
                "SPDXRef-BuildTool-"
            )
        ]
        self.assertEqual(len(bt_pkgs), 0)

    @patch.object(
        JavaSpdxGenerator, "_detect_maven_version",
        return_value=None,
    )
    @patch.object(
        JavaSpdxGenerator, "_detect_javac_version",
        return_value=None,
    )
    def test_no_tools_when_undetectable(
        self, _m_javac, _m_mvn,
    ):
        """No BUILD_TOOL_OF when detection fails."""
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
        )
        bt_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(bt_rels), 0)

    @patch.object(
        JavaSpdxGenerator, "_detect_maven_version",
        return_value=None,
    )
    @patch.object(
        JavaSpdxGenerator, "_detect_javac_version",
        return_value="21.0.1",
    )
    def test_javac_only_when_maven_absent(
        self, _m_javac, _m_mvn,
    ):
        """Only javac emitted when maven not found."""
        doc = self.gen._build_spdx(
            "myapp.jar", [], [],
        )
        bt_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(bt_rels), 1)
        bt_names = {
            p["name"] for p in doc["packages"]
            if p["SPDXID"].startswith(
                "SPDXRef-BuildTool-"
            )
        }
        self.assertEqual(bt_names, {"javac"})


class TestGenerate(unittest.TestCase):
    """Tests for the generate method."""

    def setUp(self):
        # Suppress build tool detection so tests don't
        # depend on local JDK/Maven installation.
        p1 = patch.object(
            JavaSpdxGenerator,
            "_detect_javac_version",
            return_value=None,
        )
        p2 = patch.object(
            JavaSpdxGenerator,
            "_detect_maven_version",
            return_value=None,
        )
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    @patch.object(JavaSpdxGenerator, "_get_maven_deps")
    def test_generate_success(self, mock_maven):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                "<project>"
                "<version>1.0</version>"
                "</project>"
            )
            bom = Path(td) / "bom"
            bom.mkdir()
            out = Path(td) / "out" / "test.spdx.json"

            mock_maven.return_value = []
            jar_files = [
                {
                    "file_path": str(
                        repo / "src/A.java"
                    ),
                    "sha1": "abc",
                },
            ]

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(
                str(out), jar_files=jar_files,
            )
            self.assertIsNotNone(result)
            self.assertTrue(out.exists())
            doc = json.loads(out.read_text())
            self.assertEqual(
                doc["spdxVersion"], "SPDX-2.3"
            )

    def test_generate_none_jar_files_returns_none(self):
        """jar_files=None is an error, not a fallback."""
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            bom = Path(td) / "bom"
            bom.mkdir()

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(
                str(Path(td) / "out.json"),
                jar_files=None,
            )
            self.assertIsNone(result)

    @patch.object(JavaSpdxGenerator, "_get_maven_deps")
    def test_generate_default_binary_name(
        self, mock_maven
    ):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                "<project>"
                "<version>1.0</version>"
                "</project>"
            )
            bom = Path(td) / "bom"
            bom.mkdir()
            out = Path(td) / "out.spdx.json"

            mock_maven.return_value = []

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(
                str(out), jar_files=[],
            )
            self.assertIsNotNone(result)
            doc = json.loads(out.read_text())
            # Default name uses repo_name.jar
            self.assertIn(
                "myapp.jar", doc["name"]
            )

    @patch.object(JavaSpdxGenerator, "_get_maven_deps")
    def test_generate_filters_test_deps(
        self, mock_maven
    ):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                "<project>"
                "<version>1.0</version>"
                "</project>"
            )
            bom = Path(td) / "bom"
            bom.mkdir()
            out = Path(td) / "out.spdx.json"

            mock_maven.return_value = [
                {
                    "groupId": "a",
                    "artifactId": "liba",
                    "version": "1.0",
                    "scope": "compile",
                    "direct": True,
                    "optional": False,
                    "parent": None,
                },
                {
                    "groupId": "b",
                    "artifactId": "testlib",
                    "version": "2.0",
                    "scope": "test",
                    "direct": True,
                    "optional": False,
                    "parent": None,
                },
            ]

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(
                str(out), jar_files=[],
            )
            self.assertIsNotNone(result)
            doc = json.loads(out.read_text())
            # Only root + compile dep, not test dep
            self.assertEqual(len(doc["packages"]), 2)


class TestIsTestFile(unittest.TestCase):
    """Tests for JavaSpdxGenerator._is_test_file."""

    def test_target_test_classes(self):
        self.assertTrue(
            JavaSpdxGenerator._is_test_file(
                "target/test-classes/com/example/"
                "MyTest.class"
            )
        )

    def test_src_test_java(self):
        self.assertTrue(
            JavaSpdxGenerator._is_test_file(
                "src/test/java/com/example/"
                "MyTest.java"
            )
        )

    def test_src_it_java(self):
        self.assertTrue(
            JavaSpdxGenerator._is_test_file(
                "src/it/java/org/check/"
                "XpathTest.java"
            )
        )

    def test_absolute_test_classes(self):
        self.assertTrue(
            JavaSpdxGenerator._is_test_file(
                "/workspace/repos/checkstyle/"
                "target/test-classes/Foo.class"
            )
        )

    def test_production_source(self):
        self.assertFalse(
            JavaSpdxGenerator._is_test_file(
                "src/main/java/com/example/"
                "App.java"
            )
        )

    def test_production_class(self):
        self.assertFalse(
            JavaSpdxGenerator._is_test_file(
                "target/classes/com/example/"
                "App.class"
            )
        )

    def test_empty_path(self):
        self.assertFalse(
            JavaSpdxGenerator._is_test_file("")
        )

    def test_pom_xml(self):
        self.assertFalse(
            JavaSpdxGenerator._is_test_file(
                "pom.xml"
            )
        )


class TestExtractArtifactName(unittest.TestCase):
    """Tests for _extract_artifact_name."""

    def test_simple_versioned_jar(self):
        self.assertEqual(
            JavaSpdxGenerator._extract_artifact_name(
                "jsoup-1.17.2.jar"
            ),
            "jsoup",
        )

    def test_multi_part_name(self):
        self.assertEqual(
            JavaSpdxGenerator._extract_artifact_name(
                "dependency-check-utils-9.2.0.jar"
            ),
            "dependency-check-utils",
        )

    def test_snapshot_version(self):
        self.assertEqual(
            JavaSpdxGenerator._extract_artifact_name(
                "my-lib-1.0-SNAPSHOT.jar"
            ),
            "my-lib",
        )

    def test_three_part_version(self):
        self.assertEqual(
            JavaSpdxGenerator._extract_artifact_name(
                "commons-io-2.16.1.jar"
            ),
            "commons-io",
        )

    def test_no_version(self):
        # If no version pattern, return name without .jar
        self.assertEqual(
            JavaSpdxGenerator._extract_artifact_name(
                "mylib.jar"
            ),
            "mylib",
        )

    def test_no_jar_extension(self):
        self.assertEqual(
            JavaSpdxGenerator._extract_artifact_name(
                "artifact-1.0.0"
            ),
            "artifact",
        )


class TestSiblingFiltering(unittest.TestCase):
    """Regression tests for sibling transitive dep filtering.

    Multi-module Java projects (like dependency-check) have sibling
    modules that are separate JARs. Each sibling's transitive deps
    should only appear in that sibling's SPDX file, not in other
    siblings' SPDX files.
    """

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )

    def test_sibling_direct_child_filtered(self):
        """Direct child of sibling should be filtered."""
        maven_deps = [
            {"groupId": "org.myapp", "artifactId": "core",
             "version": "1.0", "scope": "compile", "direct": True},
            {"groupId": "org.other", "artifactId": "lib-a",
             "version": "1.0", "scope": "compile", "parent": "core"},
        ]
        with patch.object(
            self.gen, "_get_project_group_id",
            return_value="org.myapp"
        ):
            with patch.object(
                self.gen, "_get_version",
                return_value="1.0"
            ):
                with tempfile.TemporaryDirectory() as td:
                    self.gen.repo_dir = Path(td)
                    doc = self.gen._build_spdx(
                        "myapp-1.0.jar", [], maven_deps, "build"
                    )
        # lib-a should NOT be in packages (it's child of sibling)
        pkg_names = [p["name"] for p in doc["packages"]]
        self.assertIn("core", pkg_names)  # sibling itself
        self.assertNotIn("lib-a", pkg_names)

    def test_sibling_transitive_grandchild_filtered(self):
        """Transitive grandchild of sibling should be filtered."""
        maven_deps = [
            {"groupId": "org.myapp", "artifactId": "core",
             "version": "1.0", "scope": "compile", "direct": True},
            {"groupId": "org.other", "artifactId": "lib-a",
             "version": "1.0", "scope": "compile", "parent": "core"},
            {"groupId": "org.other", "artifactId": "lib-b",
             "version": "1.0", "scope": "compile", "parent": "lib-a"},
        ]
        with patch.object(
            self.gen, "_get_project_group_id",
            return_value="org.myapp"
        ):
            with patch.object(
                self.gen, "_get_version",
                return_value="1.0"
            ):
                with tempfile.TemporaryDirectory() as td:
                    self.gen.repo_dir = Path(td)
                    doc = self.gen._build_spdx(
                        "myapp-1.0.jar", [], maven_deps, "build"
                    )
        pkg_names = [p["name"] for p in doc["packages"]]
        self.assertIn("core", pkg_names)
        self.assertNotIn("lib-a", pkg_names)
        self.assertNotIn("lib-b", pkg_names)

    def test_non_sibling_deps_kept(self):
        """Direct deps of root (not siblings) should be kept."""
        maven_deps = [
            {"groupId": "org.myapp", "artifactId": "core",
             "version": "1.0", "scope": "compile", "direct": True},
            {"groupId": "org.external", "artifactId": "commons",
             "version": "1.0", "scope": "compile", "direct": True},
        ]
        with patch.object(
            self.gen, "_get_project_group_id",
            return_value="org.myapp"
        ):
            with patch.object(
                self.gen, "_get_version",
                return_value="1.0"
            ):
                with tempfile.TemporaryDirectory() as td:
                    self.gen.repo_dir = Path(td)
                    doc = self.gen._build_spdx(
                        "myapp-1.0.jar", [], maven_deps, "build"
                    )
        pkg_names = [p["name"] for p in doc["packages"]]
        self.assertIn("core", pkg_names)
        self.assertIn("commons", pkg_names)


class TestStraceVerification(unittest.TestCase):
    """Strace is informational, not a filter.

    Treedb is the authoritative provenance chain.
    Strace provides secondary verification — files
    not in the strace log are kept but logged.
    """

    def test_init_default_strace_empty(self):
        """Default strace_accessed is empty set."""
        gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )
        self.assertEqual(gen.strace_accessed, set())

    def test_init_with_strace_set(self):
        """strace_accessed passed to constructor."""
        accessed = {"/repo/src/A.java", "/repo/B.java"}
        gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
            strace_accessed=accessed,
        )
        self.assertEqual(gen.strace_accessed, accessed)

    @patch.object(
        JavaSpdxGenerator, "_get_maven_deps"
    )
    def test_unverified_files_kept_in_spdx(
        self, mock_maven
    ):
        """Files not in strace are kept (not filtered)."""
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                "<project>"
                "<version>1.0</version>"
                "</project>"
            )
            bom = Path(td) / "bom"
            bom.mkdir()
            out = Path(td) / "out.spdx.json"

            mock_maven.return_value = []

            # Two files in treedb, only one in strace
            accessed = {
                str(repo / "src/main/App.java"),
            }
            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
                strace_accessed=accessed,
            )
            jar_files = [
                {
                    "sha1": "aaa",
                    "file_path": str(
                        repo / "src/main/App.java"
                    ),
                },
                {
                    "sha1": "bbb",
                    "file_path": str(
                        repo / "src/main/Other.java"
                    ),
                },
            ]
            result = gen.generate(
                str(out),
                binary_name="myapp-1.0.jar",
                sbom_type="analyzed",
                jar_files=jar_files,
            )
            self.assertIsNotNone(result)
            doc = json.loads(out.read_text())
            # Both files kept — strace is
            # informational, not a gate.
            self.assertEqual(len(doc["files"]), 2)
            names = {
                f["fileName"] for f in doc["files"]
            }
            self.assertIn("src/main/App.java", names)
            self.assertIn(
                "src/main/Other.java", names
            )

    @patch.object(
        JavaSpdxGenerator, "_get_maven_deps"
    )
    def test_no_strace_keeps_all_files(
        self, mock_maven
    ):
        """Without strace data, all files pass through."""
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            (repo / "pom.xml").write_text(
                "<project>"
                "<version>1.0</version>"
                "</project>"
            )
            bom = Path(td) / "bom"
            bom.mkdir()
            out = Path(td) / "out.spdx.json"

            mock_maven.return_value = []

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            jar_files = [
                {
                    "sha1": "aaa",
                    "file_path": str(
                        repo / "src/main/App.java"
                    ),
                },
                {
                    "sha1": "bbb",
                    "file_path": str(
                        repo / "src/main/Other.java"
                    ),
                },
            ]
            result = gen.generate(
                str(out),
                binary_name="myapp-1.0.jar",
                sbom_type="analyzed",
                jar_files=jar_files,
            )
            self.assertIsNotNone(result)
            doc = json.loads(out.read_text())
            # Both files kept
            self.assertEqual(len(doc["files"]), 2)


class TestIsExtractionArtifact(unittest.TestCase):
    """Tests for _is_extraction_artifact filter."""

    def test_bomjdir_path_is_artifact(self):
        self.assertTrue(
            JavaSpdxGenerator._is_extraction_artifact(
                "/tmp/bomjdir/jsoup-1.22.1.jar/"
                "META-INF/versions/11/"
                "module-info.class"
            )
        )

    def test_bomjdir_nested_path(self):
        self.assertTrue(
            JavaSpdxGenerator._is_extraction_artifact(
                "/tmp/bomjdir/foo.jar/Bar.class"
            )
        )

    def test_repo_source_not_artifact(self):
        self.assertFalse(
            JavaSpdxGenerator._is_extraction_artifact(
                "/workspace/repos/jsoup/"
                "src/main/java/org/jsoup/Jsoup.java"
            )
        )

    def test_empty_string(self):
        self.assertFalse(
            JavaSpdxGenerator._is_extraction_artifact(
                ""
            )
        )


class TestGradleProjectFromDir(unittest.TestCase):
    """Tests for _gradle_project_from_dir."""

    def _gen(self):
        # repo_dir = repos_dir / repo_name
        # = /workspace/repos / app
        return JavaSpdxGenerator(
            "/tmp/bom", "/workspace/repos", "app",
        )

    def test_none_returns_none(self):
        self.assertIsNone(
            self._gen()._gradle_project_from_dir(
                None,
            )
        )

    def test_same_dir_returns_none(self):
        self.assertIsNone(
            self._gen()._gradle_project_from_dir(
                "/workspace/repos/app"
            )
        )

    def test_subdir_returns_colon_path(self):
        result = self._gen()._gradle_project_from_dir(
            "/workspace/repos/app/sub/mod"
        )
        self.assertEqual(result, ":sub:mod")

    def test_outside_repo_returns_none(self):
        self.assertIsNone(
            self._gen()._gradle_project_from_dir(
                "/other/path"
            )
        )


class TestGetMavenDepsGradle(unittest.TestCase):
    """Test _get_maven_deps delegates to Gradle."""

    @patch(
        "app.spdx.java_generator.get_gradle_deps"
    )
    @patch(
        "app.spdx.java_generator.is_gradle_project",
        return_value=True,
    )
    def test_gradle_project_uses_gradle(
        self, _mock_is, mock_get
    ):
        mock_get.return_value = [
            {"groupId": "a", "artifactId": "b"},
        ]
        gen = JavaSpdxGenerator(
            "/repo", "/repos", "/repo/build",
        )
        result = gen._get_maven_deps()
        mock_get.assert_called_once()
        self.assertEqual(len(result), 1)


class TestGetProjectGroupIdGradle(unittest.TestCase):
    """Test _get_project_group_id Gradle branch."""

    @patch(
        "app.spdx.java_generator.get_gradle_group",
        return_value="com.example",
    )
    @patch(
        "app.spdx.java_generator.is_gradle_project",
        return_value=True,
    )
    def test_gradle_group(self, _mock_is, mock_grp):
        gen = JavaSpdxGenerator(
            "/repo", "/repos", "/repo/build",
        )
        result = gen._get_project_group_id()
        self.assertEqual(result, "com.example")


class TestDetectVersionFailures(unittest.TestCase):
    """Test version detection failure paths."""

    @patch("subprocess.run")
    def test_javac_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        result = JavaSpdxGenerator._detect_javac_version()
        self.assertIsNone(result)

    @patch("subprocess.run")
    def test_maven_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        result = JavaSpdxGenerator._detect_maven_version()
        self.assertIsNone(result)

    def test_gradle_version_from_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            wp = (
                Path(td) / "gradle" / "wrapper"
            )
            wp.mkdir(parents=True)
            props = (
                wp / "gradle-wrapper.properties"
            )
            props.write_text(
                "distributionUrl="
                "https\\://services.gradle.org/"
                "distributions/"
                "gradle-8.5-bin.zip\n"
            )
            ver = (
                JavaSpdxGenerator
                ._detect_gradle_version(td)
            )
        self.assertEqual(ver, "8.5")

    @patch("subprocess.run")
    def test_gradle_version_system_fallback(
        self, mock_run
    ):
        mock_run.return_value = MagicMock(
            stdout="Gradle 8.3\n",
        )
        with tempfile.TemporaryDirectory() as td:
            ver = (
                JavaSpdxGenerator
                ._detect_gradle_version(td)
            )
        self.assertEqual(ver, "8.3")

    @patch("subprocess.run")
    def test_gradle_version_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        with tempfile.TemporaryDirectory() as td:
            ver = (
                JavaSpdxGenerator
                ._detect_gradle_version(td)
            )
        self.assertIsNone(ver)


class TestAddBuildToolsGradle(unittest.TestCase):
    """Test _add_build_tools with Gradle project."""

    @patch(
        "app.spdx.java_generator"
        ".JavaSpdxGenerator._detect_gradle_version",
        return_value="8.5",
    )
    @patch(
        "app.spdx.java_generator"
        ".JavaSpdxGenerator._detect_javac_version",
        return_value="21.0.1",
    )
    @patch(
        "app.spdx.java_generator.is_gradle_project",
        return_value=True,
    )
    def test_gradle_build_tool_added(
        self, _g, _j, _v
    ):
        gen = JavaSpdxGenerator(
            "/repo", "/repos", "/repo/build",
        )
        doc = {"packages": [], "relationships": []}
        gen._add_build_tools(doc, "SPDXRef-Root")
        names = [
            p["name"] for p in doc["packages"]
        ]
        self.assertIn("gradle", names)
        self.assertIn("javac", names)


class TestCreationInfo(unittest.TestCase):
    """Tests for _creation_info static method."""

    def test_without_plugin_detection(self):
        info = JavaSpdxGenerator._creation_info(
            "2026-01-01T00:00:00Z",
        )
        self.assertEqual(
            info["created"], "2026-01-01T00:00:00Z",
        )
        self.assertIn(
            "Tool: omnibor-analysis", info["creators"],
        )
        self.assertNotIn("comment", info)

    def test_with_no_plugins_detected(self):
        from app.pipeline.maven_plugin_detector import (
            DetectionResult,
        )
        result = DetectionResult()
        info = JavaSpdxGenerator._creation_info(
            "2026-01-01T00:00:00Z", result,
        )
        self.assertNotIn("comment", info)

    def test_with_shade_plugin(self):
        from app.pipeline.maven_plugin_detector import (
            DetectionResult,
            PluginDetection,
        )
        result = DetectionResult(detections=[
            PluginDetection(
                plugin_id="maven-shade-plugin",
                group_id="org.apache.maven.plugins",
                warning="shade detected — uber-JAR",
                pom_path="/pom.xml",
            ),
        ])
        info = JavaSpdxGenerator._creation_info(
            "2026-01-01T00:00:00Z", result,
        )
        self.assertIn("comment", info)
        self.assertIn("shade", info["comment"])

    def test_with_none_plugin_detection(self):
        info = JavaSpdxGenerator._creation_info(
            "2026-01-01T00:00:00Z", None,
        )
        self.assertNotIn("comment", info)


if __name__ == "__main__":
    unittest.main()
