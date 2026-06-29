"""
Tests for app.pipeline.ivy_report_parser.

Fixtures mirror the real Ivy resolution-report XML schema validated in the
A9 design doc (§13.2).
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import ParseError

from app.pipeline.ivy_report_parser import (
    parse_ivy_report,
    build_capture,
    parse_ivy_report_dir,
)


_COMPILE_REPORT = """<?xml version="1.0"?>
<ivy-report>
  <info organisation="org.apache" module="myapp" revision="1.0"
        conf="compile"/>
  <dependencies>
    <module organisation="com.google.guava" name="guava">
      <revision name="32.1.3-jre">
        <caller organisation="org.apache" name="myapp"/>
      </revision>
    </module>
    <module organisation="com.google.guava" name="failureaccess">
      <revision name="1.0.1">
        <caller organisation="com.google.guava" name="guava"/>
      </revision>
    </module>
    <module organisation="junit" name="junit">
      <revision name="3.8" evicted="evicted: newer revision in compile">
        <caller organisation="org.apache" name="myapp"/>
      </revision>
      <revision name="4.13.2">
        <caller organisation="org.apache" name="myapp"/>
      </revision>
    </module>
  </dependencies>
</ivy-report>
"""

_TEST_REPORT = """<?xml version="1.0"?>
<ivy-report>
  <info organisation="org.apache" module="myapp" revision="1.0" conf="test"/>
  <dependencies>
    <module organisation="org.mockito" name="mockito-core">
      <revision name="5.0.0">
        <caller organisation="org.apache" name="myapp"/>
      </revision>
    </module>
  </dependencies>
</ivy-report>
"""


def _info_only(conf_attr):
    return (
        '<ivy-report><info organisation="o" module="m" revision="1"'
        + conf_attr
        + "/><dependencies/></ivy-report>"
    )


class TestParseIvyReport(unittest.TestCase):
    """Tests for parse_ivy_report()."""

    def setUp(self):
        self.report = parse_ivy_report(_COMPILE_REPORT)
        self.deps = {d["artifactId"]: d for d in self.report["deps"]}

    def test_root_and_conf(self):
        self.assertEqual(self.report["root"], ("org.apache", "myapp"))
        self.assertEqual(self.report["root_version"], "1.0")
        self.assertEqual(self.report["conf"], "compile")
        self.assertEqual(self.report["scope"], "compile")

    def test_evicted_revision_skipped(self):
        # junit 3.8 is evicted; only 4.13.2 survives.
        self.assertEqual(self.deps["junit"]["version"], "4.13.2")
        self.assertEqual(len(self.report["deps"]), 3)

    def test_direct_dependency(self):
        guava = self.deps["guava"]
        self.assertTrue(guava["direct"])
        self.assertIsNone(guava["parent"])
        self.assertEqual(guava["version"], "32.1.3-jre")
        self.assertEqual(guava["groupId"], "com.google.guava")
        self.assertEqual(guava["packaging"], "jar")

    def test_transitive_dependency_parent(self):
        fa = self.deps["failureaccess"]
        self.assertFalse(fa["direct"])
        self.assertEqual(fa["parent"], "guava")

    def test_scope_runtime(self):
        rep = parse_ivy_report(_info_only(' conf="runtime"'))
        self.assertEqual(rep["scope"], "runtime")

    def test_scope_provided(self):
        rep = parse_ivy_report(_info_only(' conf="provided"'))
        self.assertEqual(rep["scope"], "provided")

    def test_scope_test(self):
        rep = parse_ivy_report(_info_only(' conf="test"'))
        self.assertEqual(rep["scope"], "test")

    def test_scope_unknown_defaults_compile(self):
        rep = parse_ivy_report(_info_only(' conf="weirdconf"'))
        self.assertEqual(rep["scope"], "compile")

    def test_scope_missing_conf_defaults_compile(self):
        rep = parse_ivy_report(_info_only(""))
        self.assertEqual(rep["scope"], "compile")

    def test_no_info_yields_empty_root(self):
        rep = parse_ivy_report("<ivy-report><dependencies/></ivy-report>")
        self.assertEqual(rep["root"], (None, None))
        self.assertEqual(rep["deps"], [])

    def test_invalid_xml_raises(self):
        with self.assertRaises(ParseError):
            parse_ivy_report("<not-closed")


class TestBuildCapture(unittest.TestCase):
    """Tests for build_capture()."""

    def test_single_module_shape(self):
        cap = build_capture([parse_ivy_report(_COMPILE_REPORT)])
        self.assertEqual(cap["tool"], "ivy")
        self.assertEqual(len(cap["modules"]), 1)
        mod = cap["modules"][0]
        self.assertEqual(mod["key"], "org.apache:myapp")
        self.assertEqual(mod["version"], "1.0")
        self.assertEqual(len(mod["deps"]), 3)

    def test_test_conf_dropped(self):
        cap = build_capture([
            parse_ivy_report(_COMPILE_REPORT),
            parse_ivy_report(_TEST_REPORT),
        ])
        names = {d["artifactId"] for d in cap["modules"][0]["deps"]}
        self.assertNotIn("mockito-core", names)
        self.assertIn("guava", names)

    def test_dedupe_ors_direct(self):
        # Same dep appears transitive in one conf, direct in another;
        # merged entry must be direct.
        transitive = {
            "conf": "runtime", "scope": "runtime",
            "root": ("o", "m"), "root_version": "1",
            "deps": [{
                "groupId": "g", "artifactId": "a", "version": "1",
                "packaging": "jar", "scope": "runtime",
                "direct": False, "parent": "x",
            }],
        }
        direct = {
            "conf": "compile", "scope": "compile",
            "root": ("o", "m"), "root_version": "1",
            "deps": [{
                "groupId": "g", "artifactId": "a", "version": "1",
                "packaging": "jar", "scope": "compile",
                "direct": True, "parent": None,
            }],
        }
        cap = build_capture([transitive, direct])
        deps = cap["modules"][0]["deps"]
        self.assertEqual(len(deps), 1)
        self.assertTrue(deps[0]["direct"])

    def test_empty_reports(self):
        cap = build_capture([])
        mod = cap["modules"][0]
        self.assertEqual(mod["key"], "")
        self.assertEqual(mod["deps"], [])


class TestParseIvyReportDir(unittest.TestCase):
    """Tests for parse_ivy_report_dir()."""

    def _write(self, tmp, name, text):
        (Path(tmp) / name).write_text(text, encoding="utf-8")

    def test_parses_and_filters(self):
        with TemporaryDirectory() as tmp:
            self._write(tmp, "org.apache-myapp-compile.xml", _COMPILE_REPORT)
            self._write(tmp, "org.apache-myapp-test.xml", _TEST_REPORT)
            self._write(tmp, "other.xml", "<foo><bar/></foo>")
            self._write(tmp, "bad.xml", "<not-closed")
            cap = parse_ivy_report_dir(tmp)
        mod = cap["modules"][0]
        self.assertEqual(cap["tool"], "ivy")
        self.assertEqual(mod["key"], "org.apache:myapp")
        names = {d["artifactId"] for d in mod["deps"]}
        self.assertEqual(names, {"guava", "failureaccess", "junit"})
        self.assertNotIn("mockito-core", names)

    def test_empty_dir(self):
        with TemporaryDirectory() as tmp:
            cap = parse_ivy_report_dir(tmp)
        self.assertEqual(cap["tool"], "ivy")
        self.assertEqual(cap["modules"][0]["deps"], [])

    def test_unreadable_entry_skipped(self):
        # A directory matching *.xml triggers the OSError read path;
        # one unreadable entry must not abort the whole capture.
        with TemporaryDirectory() as tmp:
            self._write(
                tmp, "org.apache-myapp-compile.xml", _COMPILE_REPORT,
            )
            (Path(tmp) / "isdir.xml").mkdir()
            cap = parse_ivy_report_dir(tmp)
        names = {d["artifactId"] for d in cap["modules"][0]["deps"]}
        self.assertEqual(names, {"guava", "failureaccess", "junit"})


if __name__ == "__main__":
    unittest.main()
