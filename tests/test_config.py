"""
Tests for app/config.py — mode selection and config resolution.
"""

import tempfile
import unittest
from pathlib import Path

import yaml

from unittest.mock import patch

from app.config import (
    load_config,
    resolve_bisbom_cfg,
    resolve_paths,
    validate_build_profile,
    validate_repos,
    _is_nested_format,
    BUILD_TOOLS,
    BUILD_STRUCTURES,
    VALID_MODES,
    DEFAULT_MODE,
    _LANG_BISBOM_KEYS,
)


class TestResolveBisbomCfgLegacy(unittest.TestCase):
    """Tests for legacy flat config format."""

    def test_c_cpp_flat(self):
        config = {
            "bisbom": {
                "tracer": "bomtrace3",
                "raw_logfile": "/tmp/log",
            },
        }
        result = resolve_bisbom_cfg(config, "c-cpp")
        self.assertEqual(result["tracer"], "bomtrace3")

    def test_go_flat(self):
        config = {
            "bisbom_go": {
                "tracer": "bomtrace2 -c go.conf",
            },
        }
        result = resolve_bisbom_cfg(config, "go")
        self.assertEqual(
            result["tracer"], "bomtrace2 -c go.conf",
        )

    def test_rust_flat(self):
        config = {
            "bisbom_rust": {
                "tracer": "bomtrace2",
            },
        }
        result = resolve_bisbom_cfg(config, "rust")
        self.assertEqual(result["tracer"], "bomtrace2")

    def test_java_flat(self):
        config = {
            "bisbom_java": {
                "strace_opts": "-f -e trace=openat",
            },
        }
        result = resolve_bisbom_cfg(config, "java")
        self.assertIn("strace_opts", result)

    def test_unknown_lang_falls_back_to_bisbom(self):
        config = {
            "bisbom": {"tracer": "bomtrace3"},
        }
        result = resolve_bisbom_cfg(
            config, "python",
        )
        self.assertEqual(result["tracer"], "bomtrace3")

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            resolve_bisbom_cfg({}, "c-cpp")

    def test_default_mode_is_standalone(self):
        config = {
            "bisbom": {"tracer": "bomtrace3"},
        }
        # No 'mode' key — should use default
        result = resolve_bisbom_cfg(config, "c-cpp")
        self.assertEqual(result["tracer"], "bomtrace3")


class TestResolveOmniborCfgNested(unittest.TestCase):
    """Tests for nested mode config format."""

    def test_standalone_selected(self):
        config = {
            "mode": "standalone",
            "bisbom": {
                "standalone": {
                    "tracer": "bomtrace3",
                },
                "sidecar": {
                    "wrapper": "/opt/bomsh/hook.sh",
                },
            },
        }
        result = resolve_bisbom_cfg(config, "c-cpp")
        self.assertEqual(result["tracer"], "bomtrace3")

    def test_sidecar_selected(self):
        config = {
            "mode": "sidecar",
            "bisbom": {
                "standalone": {
                    "tracer": "bomtrace3",
                },
                "sidecar": {
                    "wrapper": "/opt/bomsh/hook.sh",
                },
            },
        }
        result = resolve_bisbom_cfg(config, "c-cpp")
        self.assertEqual(
            result["wrapper"], "/opt/bomsh/hook.sh",
        )

    def test_java_nested_sidecar(self):
        config = {
            "mode": "sidecar",
            "bisbom_java": {
                "standalone": {
                    "strace_opts": "-f -e openat",
                },
                "sidecar": {
                    "strategy": "maven_dep_tree",
                },
            },
        }
        result = resolve_bisbom_cfg(config, "java")
        self.assertEqual(
            result["strategy"], "maven_dep_tree",
        )

    def test_invalid_mode_raises(self):
        config = {
            "mode": "invalid",
            "bisbom": {"tracer": "bomtrace3"},
        }
        with self.assertRaises(ValueError) as ctx:
            resolve_bisbom_cfg(config, "c-cpp")
        self.assertIn("invalid", str(ctx.exception))

    def test_missing_mode_subkey_raises(self):
        config = {
            "mode": "sidecar",
            "bisbom": {
                "standalone": {
                    "tracer": "bomtrace3",
                },
                # no 'sidecar' sub-key
            },
        }
        with self.assertRaises(ValueError) as ctx:
            resolve_bisbom_cfg(config, "c-cpp")
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
        self.assertIn("c-cpp", _LANG_BISBOM_KEYS)
        self.assertIn("go", _LANG_BISBOM_KEYS)
        self.assertIn("rust", _LANG_BISBOM_KEYS)
        self.assertIn("java", _LANG_BISBOM_KEYS)


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


class TestValidateBuildProfile(unittest.TestCase):
    """Tests for validate_build_profile()."""

    def test_minimal_valid(self):
        validate_build_profile(
            {"tool": "maven", "structure": "single-module"},
            "r",
        )

    def test_full_valid(self):
        validate_build_profile(
            {
                "tool": "gradle",
                "structure": "multi-module",
                "dsl": "groovy",
                "tool_version": "8.13",
                "traits": ["dependency-management"],
            },
            "r",
        )

    def test_not_a_dict(self):
        with self.assertRaises(ValueError):
            validate_build_profile(["tool"], "r")

    def test_bad_tool(self):
        with self.assertRaises(ValueError) as ctx:
            validate_build_profile(
                {"tool": "bazel",
                 "structure": "single-module"},
                "r",
            )
        self.assertIn("tool", str(ctx.exception))

    def test_bad_structure(self):
        with self.assertRaises(ValueError) as ctx:
            validate_build_profile(
                {"tool": "maven", "structure": "mono"},
                "r",
            )
        self.assertIn("structure", str(ctx.exception))

    def test_dsl_non_str(self):
        with self.assertRaises(ValueError):
            validate_build_profile(
                {"tool": "gradle",
                 "structure": "multi-module",
                 "dsl": 42},
                "r",
            )

    def test_tool_version_non_str(self):
        # An unquoted YAML float like 8.13 must be rejected.
        with self.assertRaises(ValueError):
            validate_build_profile(
                {"tool": "gradle",
                 "structure": "multi-module",
                 "tool_version": 8.13},
                "r",
            )

    def test_java_home_valid(self):
        validate_build_profile(
            {
                "tool": "gradle",
                "structure": "single-module",
                "java_home": "/usr/lib/jvm/java-17-openjdk-amd64",
            },
            "r",
        )

    def test_java_home_non_str(self):
        with self.assertRaises(ValueError) as ctx:
            validate_build_profile(
                {"tool": "gradle",
                 "structure": "single-module",
                 "java_home": 17},
                "r",
            )
        self.assertIn("java_home", str(ctx.exception))

    def test_traits_not_list(self):
        with self.assertRaises(ValueError):
            validate_build_profile(
                {"tool": "maven",
                 "structure": "single-module",
                 "traits": "reactor"},
                "r",
            )

    def test_traits_non_str_element(self):
        with self.assertRaises(ValueError):
            validate_build_profile(
                {"tool": "maven",
                 "structure": "single-module",
                 "traits": ["ok", 3]},
                "r",
            )


class TestValidateRepos(unittest.TestCase):
    """Tests for validate_repos()."""

    def test_non_dict_config(self):
        self.assertEqual(validate_repos("x"), "x")

    def test_no_repos_section(self):
        cfg = {"test": True}
        self.assertIs(validate_repos(cfg), cfg)

    def test_repos_not_dict(self):
        cfg = {"repos": []}
        self.assertIs(validate_repos(cfg), cfg)

    def test_valid_repos(self):
        cfg = {
            "repos": {
                "a": {
                    "build_profile": {
                        "tool": "go",
                        "structure": "single-module",
                    },
                },
            },
        }
        self.assertIs(validate_repos(cfg), cfg)

    def test_missing_build_profile_raises(self):
        cfg = {"repos": {"a": {"url": "x"}}}
        with self.assertRaises(ValueError) as ctx:
            validate_repos(cfg)
        self.assertIn("build_profile", str(ctx.exception))

    def test_repo_not_dict_raises(self):
        cfg = {"repos": {"a": "not-a-dict"}}
        with self.assertRaises(ValueError):
            validate_repos(cfg)

    def test_invalid_profile_propagates(self):
        cfg = {
            "repos": {
                "a": {"build_profile": {"tool": "nope"}},
            },
        }
        with self.assertRaises(ValueError):
            validate_repos(cfg)


class TestLoadConfigValidation(unittest.TestCase):
    """Tests for validation wiring in load_config()."""

    def _write(self, data):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        )
        yaml.dump(data, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_real_config_validates(self):
        config = load_config()
        self.assertIn("repos", config)
        for name, cfg in config["repos"].items():
            self.assertIn(
                "build_profile", cfg,
                f"{name} missing build_profile",
            )
            prof = cfg["build_profile"]
            self.assertIn(prof["tool"], BUILD_TOOLS)
            self.assertIn(
                prof["structure"], BUILD_STRUCTURES
            )

    def test_invalid_repo_raises_on_load(self):
        path = self._write({"repos": {"a": {"url": "x"}}})
        try:
            with self.assertRaises(ValueError):
                load_config(path)
        finally:
            path.unlink()

    def test_validate_false_skips(self):
        path = self._write({"repos": {"a": {"url": "x"}}})
        try:
            cfg = load_config(path, validate=False)
            self.assertIn("repos", cfg)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
