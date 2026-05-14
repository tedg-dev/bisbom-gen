"""
Tests for app/config.py — mode selection and config resolution.
"""

import unittest

from unittest.mock import patch

from app.config import (
    resolve_omnibor_cfg,
    resolve_paths,
    _is_nested_format,
    VALID_MODES,
    DEFAULT_MODE,
    _LANG_OMNIBOR_KEYS,
)


class TestResolveOmniborCfgLegacy(unittest.TestCase):
    """Tests for legacy flat config format."""

    def test_c_cpp_flat(self):
        config = {
            "omnibor": {
                "tracer": "bomtrace3",
                "raw_logfile": "/tmp/log",
            },
        }
        result = resolve_omnibor_cfg(config, "c-cpp")
        self.assertEqual(result["tracer"], "bomtrace3")

    def test_go_flat(self):
        config = {
            "omnibor_go": {
                "tracer": "bomtrace2 -c go.conf",
            },
        }
        result = resolve_omnibor_cfg(config, "go")
        self.assertEqual(
            result["tracer"], "bomtrace2 -c go.conf",
        )

    def test_rust_flat(self):
        config = {
            "omnibor_rust": {
                "tracer": "bomtrace2",
            },
        }
        result = resolve_omnibor_cfg(config, "rust")
        self.assertEqual(result["tracer"], "bomtrace2")

    def test_java_flat(self):
        config = {
            "omnibor_java": {
                "strace_opts": "-f -e trace=openat",
            },
        }
        result = resolve_omnibor_cfg(config, "java")
        self.assertIn("strace_opts", result)

    def test_unknown_lang_falls_back_to_omnibor(self):
        config = {
            "omnibor": {"tracer": "bomtrace3"},
        }
        result = resolve_omnibor_cfg(
            config, "python",
        )
        self.assertEqual(result["tracer"], "bomtrace3")

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            resolve_omnibor_cfg({}, "c-cpp")

    def test_default_mode_is_standalone(self):
        config = {
            "omnibor": {"tracer": "bomtrace3"},
        }
        # No 'mode' key — should use default
        result = resolve_omnibor_cfg(config, "c-cpp")
        self.assertEqual(result["tracer"], "bomtrace3")


class TestResolveOmniborCfgNested(unittest.TestCase):
    """Tests for nested mode config format."""

    def test_standalone_selected(self):
        config = {
            "mode": "standalone",
            "omnibor": {
                "standalone": {
                    "tracer": "bomtrace3",
                },
                "sidecar": {
                    "wrapper": "/opt/bomsh/hook.sh",
                },
            },
        }
        result = resolve_omnibor_cfg(config, "c-cpp")
        self.assertEqual(result["tracer"], "bomtrace3")

    def test_sidecar_selected(self):
        config = {
            "mode": "sidecar",
            "omnibor": {
                "standalone": {
                    "tracer": "bomtrace3",
                },
                "sidecar": {
                    "wrapper": "/opt/bomsh/hook.sh",
                },
            },
        }
        result = resolve_omnibor_cfg(config, "c-cpp")
        self.assertEqual(
            result["wrapper"], "/opt/bomsh/hook.sh",
        )

    def test_java_nested_sidecar(self):
        config = {
            "mode": "sidecar",
            "omnibor_java": {
                "standalone": {
                    "strace_opts": "-f -e openat",
                },
                "sidecar": {
                    "strategy": "maven_dep_tree",
                },
            },
        }
        result = resolve_omnibor_cfg(config, "java")
        self.assertEqual(
            result["strategy"], "maven_dep_tree",
        )

    def test_invalid_mode_raises(self):
        config = {
            "mode": "invalid",
            "omnibor": {"tracer": "bomtrace3"},
        }
        with self.assertRaises(ValueError) as ctx:
            resolve_omnibor_cfg(config, "c-cpp")
        self.assertIn("invalid", str(ctx.exception))

    def test_missing_mode_subkey_raises(self):
        config = {
            "mode": "sidecar",
            "omnibor": {
                "standalone": {
                    "tracer": "bomtrace3",
                },
                # no 'sidecar' sub-key
            },
        }
        with self.assertRaises(ValueError) as ctx:
            resolve_omnibor_cfg(config, "c-cpp")
        self.assertIn("sidecar", str(ctx.exception))


class TestIsNestedFormat(unittest.TestCase):
    """Tests for _is_nested_format()."""

    def test_flat_dict(self):
        self.assertFalse(
            _is_nested_format({"tracer": "bomtrace3"})
        )

    def test_nested_standalone(self):
        self.assertTrue(
            _is_nested_format({
                "standalone": {"tracer": "bomtrace3"},
            })
        )

    def test_nested_sidecar(self):
        self.assertTrue(
            _is_nested_format({
                "sidecar": {"wrapper": "/opt/hook"},
            })
        )

    def test_not_a_dict(self):
        self.assertFalse(_is_nested_format("string"))
        self.assertFalse(_is_nested_format(None))
        self.assertFalse(_is_nested_format(42))


class TestConstants(unittest.TestCase):
    """Tests for config constants."""

    def test_valid_modes(self):
        self.assertIn("standalone", VALID_MODES)
        self.assertIn("sidecar", VALID_MODES)

    def test_default_mode(self):
        self.assertEqual(DEFAULT_MODE, "standalone")

    def test_lang_keys_cover_all_languages(self):
        self.assertIn("c-cpp", _LANG_OMNIBOR_KEYS)
        self.assertIn("go", _LANG_OMNIBOR_KEYS)
        self.assertIn("rust", _LANG_OMNIBOR_KEYS)
        self.assertIn("java", _LANG_OMNIBOR_KEYS)


class TestResolvePaths(unittest.TestCase):
    """Tests for resolve_paths()."""

    def test_defaults_populated(self):
        paths = resolve_paths({})
        self.assertIn("go_root", paths)
        self.assertIn("cargo_home", paths)
        self.assertIn("java_home", paths)
        self.assertIn("bomsh_dir", paths)

    def test_config_takes_precedence(self):
        config = {
            "paths": {
                "go_root": "/custom/go",
            },
        }
        paths = resolve_paths(config)
        self.assertEqual(paths["go_root"], "/custom/go")

    @patch.dict(
        "os.environ",
        {"GOROOT": "/env/go"},
        clear=False,
    )
    def test_env_var_used(self):
        paths = resolve_paths({})
        self.assertEqual(paths["go_root"], "/env/go")

    @patch.dict(
        "os.environ",
        {"GOROOT": "/env/go"},
        clear=False,
    )
    def test_config_beats_env(self):
        config = {
            "paths": {
                "go_root": "/cfg/go",
            },
        }
        paths = resolve_paths(config)
        self.assertEqual(
            paths["go_root"], "/cfg/go",
        )

    def test_tilde_expanded(self):
        config = {
            "paths": {
                "cargo_home": "~/my_cargo",
            },
        }
        paths = resolve_paths(config)
        self.assertNotIn("~", paths["cargo_home"])

    def test_existing_paths_preserved(self):
        config = {
            "paths": {
                "repos_dir": "/workspace/repos",
                "output_dir": "/workspace/output",
            },
        }
        paths = resolve_paths(config)
        self.assertEqual(
            paths["repos_dir"], "/workspace/repos",
        )
        self.assertEqual(
            paths["output_dir"], "/workspace/output",
        )

    def test_default_go_root(self):
        paths = resolve_paths({})
        self.assertEqual(
            paths["go_root"], "/usr/local/go",
        )

    def test_default_bomsh_dir(self):
        paths = resolve_paths({})
        self.assertEqual(
            paths["bomsh_dir"], "/opt/bomsh",
        )


if __name__ == "__main__":
    unittest.main()
