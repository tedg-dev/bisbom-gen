"""Tests for Java SPDX generator."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

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

    @patch("app.spdx.java_generator.subprocess.run")
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

    @patch("app.spdx.java_generator.subprocess.run")
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

    @patch("app.spdx.java_generator.subprocess.run")
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

    @patch("app.spdx.java_generator.subprocess.run")
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
    """Tests for _build_spdx."""

    def setUp(self):
        self.gen = JavaSpdxGenerator(
            bom_dir="/tmp/bom",
            repos_dir="/tmp/repos",
            repo_name="myapp",
        )

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

    def test_direct_compile_dep_static_link(self):
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
            if r["relationshipType"] == "STATIC_LINK"
        ]
        self.assertEqual(len(rels), 1)
        self.assertIn(
            "SPDXRef-Package-myapp.jar",
            rels[0]["relatedSpdxElement"],
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
        self.assertEqual(len(depends), 1)
        self.assertEqual(
            depends[0]["relatedSpdxElement"],
            "SPDXRef-Dep-0",
        )

    def test_provided_dep_build_tool_of(self):
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
        build_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(build_rels), 1)

    def test_transitive_provided_build_tool_of(self):
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
        build_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(build_rels), 1)

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
        self.assertIn(
            "SPDXRef-Package-myapp.jar",
            depends[0]["relatedSpdxElement"],
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

    def test_runtime_scope_direct_static_link(self):
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
            if r["relationshipType"] == "STATIC_LINK"
        ]
        self.assertEqual(len(rels), 1)

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


class TestGenerate(unittest.TestCase):
    """Tests for the generate method."""

    @patch.object(JavaSpdxGenerator, "_get_maven_deps")
    @patch("app.spdx.java_generator.AdgParser")
    def test_generate_success(
        self, mock_parser_cls, mock_maven
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
            out = Path(td) / "out" / "test.spdx.json"

            mock_parser = MagicMock()
            mock_parser.parse.return_value = {
                "project_source": [
                    {
                        "file_path": str(
                            repo / "src/A.java"
                        ),
                        "sha1": "abc",
                    }
                ],
            }
            mock_parser_cls.return_value = mock_parser
            mock_maven.return_value = []

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(str(out))
            self.assertIsNotNone(result)
            self.assertTrue(out.exists())
            doc = json.loads(out.read_text())
            self.assertEqual(
                doc["spdxVersion"], "SPDX-2.3"
            )

    @patch("app.spdx.java_generator.AdgParser")
    def test_generate_parser_failure(
        self, mock_parser_cls
    ):
        with tempfile.TemporaryDirectory() as td:
            repos = Path(td) / "repos"
            repo = repos / "myapp"
            repo.mkdir(parents=True)
            bom = Path(td) / "bom"
            bom.mkdir()

            mock_parser = MagicMock()
            mock_parser.parse.side_effect = (
                FileNotFoundError("treedb not found")
            )
            mock_parser_cls.return_value = mock_parser

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(
                str(Path(td) / "out.json")
            )
            self.assertIsNone(result)

    @patch.object(JavaSpdxGenerator, "_get_maven_deps")
    @patch("app.spdx.java_generator.AdgParser")
    def test_generate_default_binary_name(
        self, mock_parser_cls, mock_maven
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

            mock_parser = MagicMock()
            mock_parser.parse.return_value = {
                "project_source": [],
            }
            mock_parser_cls.return_value = mock_parser
            mock_maven.return_value = []

            gen = JavaSpdxGenerator(
                bom_dir=str(bom),
                repos_dir=str(repos),
                repo_name="myapp",
            )
            result = gen.generate(str(out))
            self.assertIsNotNone(result)
            doc = json.loads(out.read_text())
            # Default name uses repo_name.jar
            self.assertIn(
                "myapp.jar", doc["name"]
            )

    @patch.object(JavaSpdxGenerator, "_get_maven_deps")
    @patch("app.spdx.java_generator.AdgParser")
    def test_generate_filters_test_deps(
        self, mock_parser_cls, mock_maven
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

            mock_parser = MagicMock()
            mock_parser.parse.return_value = {
                "project_source": [],
            }
            mock_parser_cls.return_value = mock_parser
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
            result = gen.generate(str(out))
            doc = json.loads(out.read_text())
            # Only root + compile dep, not test dep
            self.assertEqual(len(doc["packages"]), 2)


if __name__ == "__main__":
    unittest.main()
