"""
Tests for app/pipeline/maven_plugin_detector.py.

Uses fixture pom.xml content to test shade/assembly
plugin detection without requiring Maven or real repos.
"""

import tempfile
import unittest
from pathlib import Path

from app.pipeline.maven_plugin_detector import (
    detect_repackaging_plugins,
    DetectionResult,
    PluginDetection,
)


# ============================================================
# Fixture POM fragments
# ============================================================

_POM_WITH_SHADE = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-shade-plugin</artifactId>
        <version>3.5.1</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

_POM_WITH_SHADE_FILTERS = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-shade-plugin</artifactId>
        <version>3.5.1</version>
        <configuration>
          <artifactSet>
            <includes>
              <include>org.apache.commons:*</include>
            </includes>
          </artifactSet>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
"""

_POM_WITH_ASSEMBLY = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-assembly-plugin</artifactId>
        <version>3.6.0</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

_POM_SPRING_BOOT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""

_POM_NO_PLUGINS = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>2.0.7</version>
    </dependency>
  </dependencies>
</project>
"""

_POM_NO_NAMESPACE = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <artifactId>maven-shade-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""

_POM_PLUGIN_MANAGEMENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
  <build>
    <pluginManagement>
      <plugins>
        <plugin>
          <groupId>org.apache.maven.plugins</groupId>
          <artifactId>maven-shade-plugin</artifactId>
          <version>3.5.1</version>
        </plugin>
      </plugins>
    </pluginManagement>
  </build>
</project>
"""

_POM_MULTI_MODULE_PARENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>core</module>
    <module>cli</module>
  </modules>
</project>
"""


# ============================================================
# Tests: detect_repackaging_plugins
# ============================================================

class TestDetectRepackagingPlugins(unittest.TestCase):
    """Tests for detect_repackaging_plugins()."""

    def _write_pom(self, td, content, subdir=None):
        """Write a pom.xml in the temp directory."""
        if subdir:
            d = Path(td) / subdir
            d.mkdir(parents=True, exist_ok=True)
            pom = d / "pom.xml"
        else:
            pom = Path(td) / "pom.xml"
        pom.write_text(content, encoding="utf-8")
        return pom

    def test_shade_detected(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_WITH_SHADE)
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)
        self.assertEqual(len(result.detections), 1)
        self.assertEqual(
            result.detections[0].plugin_id,
            "maven-shade-plugin",
        )

    def test_shade_warning_message(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_WITH_SHADE)
            result = detect_repackaging_plugins(td)
        self.assertIn(
            "shade", result.detections[0].warning,
        )

    def test_shade_with_filters(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_WITH_SHADE_FILTERS)
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)
        self.assertTrue(result.detections[0].has_filters)

    def test_shade_without_filters(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_WITH_SHADE)
            result = detect_repackaging_plugins(td)
        self.assertFalse(result.detections[0].has_filters)

    def test_assembly_detected(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_WITH_ASSEMBLY)
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)
        self.assertEqual(
            result.detections[0].plugin_id,
            "maven-assembly-plugin",
        )

    def test_spring_boot_detected(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_SPRING_BOOT)
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)
        self.assertEqual(
            result.detections[0].plugin_id,
            "spring-boot-maven-plugin",
        )

    def test_no_plugins_clean(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_NO_PLUGINS)
            result = detect_repackaging_plugins(td)
        self.assertFalse(result.is_uber_jar)
        self.assertEqual(len(result.detections), 0)

    def test_no_pom_file(self):
        with tempfile.TemporaryDirectory() as td:
            result = detect_repackaging_plugins(td)
        self.assertFalse(result.is_uber_jar)

    def test_no_namespace_pom(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_NO_NAMESPACE)
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)
        self.assertEqual(
            result.detections[0].plugin_id,
            "maven-shade-plugin",
        )

    def test_plugin_management(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(td, _POM_PLUGIN_MANAGEMENT)
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)

    def test_multi_module_scans_children(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(
                td, _POM_MULTI_MODULE_PARENT,
            )
            self._write_pom(
                td, _POM_NO_PLUGINS, subdir="core",
            )
            self._write_pom(
                td, _POM_WITH_SHADE, subdir="cli",
            )
            result = detect_repackaging_plugins(td)
        self.assertTrue(result.is_uber_jar)
        self.assertEqual(len(result.detections), 1)
        self.assertIn(
            "cli", result.detections[0].pom_path,
        )

    def test_specific_pom_subpath(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_pom(
                td, _POM_WITH_SHADE, subdir="sub",
            )
            result = detect_repackaging_plugins(
                td, pom_subpath="sub/pom.xml",
            )
        self.assertTrue(result.is_uber_jar)

    def test_malformed_pom(self):
        with tempfile.TemporaryDirectory() as td:
            pom = Path(td) / "pom.xml"
            pom.write_text(
                "<not valid xml",
                encoding="utf-8",
            )
            result = detect_repackaging_plugins(td)
        self.assertFalse(result.is_uber_jar)


# ============================================================
# Tests: DetectionResult
# ============================================================

class TestDetectionResult(unittest.TestCase):
    """Tests for DetectionResult dataclass."""

    def test_empty_result(self):
        r = DetectionResult()
        self.assertFalse(r.is_uber_jar)
        self.assertEqual(r.spdx_comment, "")
        self.assertEqual(r.plugin_ids, [])

    def test_spdx_comment_single(self):
        r = DetectionResult(detections=[
            PluginDetection(
                plugin_id="maven-shade-plugin",
                group_id="org.apache.maven.plugins",
                warning="shade detected",
                pom_path="/pom.xml",
            ),
        ])
        self.assertEqual(r.spdx_comment, "shade detected")

    def test_spdx_comment_multiple(self):
        r = DetectionResult(detections=[
            PluginDetection(
                plugin_id="maven-shade-plugin",
                group_id="org.apache.maven.plugins",
                warning="shade",
                pom_path="/pom.xml",
            ),
            PluginDetection(
                plugin_id="maven-assembly-plugin",
                group_id="org.apache.maven.plugins",
                warning="assembly",
                pom_path="/pom.xml",
            ),
        ])
        self.assertEqual(
            r.spdx_comment, "shade; assembly",
        )

    def test_plugin_ids(self):
        r = DetectionResult(detections=[
            PluginDetection(
                plugin_id="maven-shade-plugin",
                group_id="org.apache.maven.plugins",
                warning="shade",
                pom_path="/pom.xml",
            ),
        ])
        self.assertEqual(
            r.plugin_ids, ["maven-shade-plugin"],
        )


if __name__ == "__main__":
    unittest.main()
