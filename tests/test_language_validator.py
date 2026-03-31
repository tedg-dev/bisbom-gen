"""Tests for language validation."""

from app.pipeline.language_validator import (
    SUPPORTED_LANGUAGES,
    map_github_language,
    validate_repo_languages,
    format_validation_error,
)


class TestMapGithubLanguage:
    """Tests for map_github_language."""

    def test_c_maps_to_c_cpp(self):
        assert map_github_language("C") == "c-cpp"
        assert map_github_language("c") == "c-cpp"

    def test_cpp_maps_to_c_cpp(self):
        assert map_github_language("C++") == "c-cpp"
        assert map_github_language("c++") == "c-cpp"

    def test_rust_maps_to_rust(self):
        assert map_github_language("Rust") == "rust"
        assert map_github_language("rust") == "rust"

    def test_go_maps_to_go(self):
        assert map_github_language("Go") == "go"
        assert map_github_language("go") == "go"

    def test_java_maps_to_java(self):
        assert map_github_language("Java") == "java"
        assert map_github_language("java") == "java"

    def test_kotlin_maps_to_java(self):
        assert map_github_language("Kotlin") == "java"

    def test_scala_maps_to_java(self):
        assert map_github_language("Scala") == "java"

    def test_unsupported_returns_none(self):
        assert map_github_language("Python") is None
        assert map_github_language("JavaScript") is None
        assert map_github_language("TypeScript") is None
        assert map_github_language("Ruby") is None

    def test_empty_returns_none(self):
        assert map_github_language("") is None
        assert map_github_language(None) is None


class TestValidateRepoLanguages:
    """Tests for validate_repo_languages."""

    def test_c_repo_is_valid(self):
        langs = {"C": 500000, "Shell": 10000, "Makefile": 5000}
        valid, primary, config, unsupported = validate_repo_languages(langs)
        assert valid is True
        assert primary == "C"
        assert config == "c-cpp"
        assert unsupported == []

    def test_rust_repo_is_valid(self):
        langs = {"Rust": 100000, "Shell": 1000}
        valid, primary, config, unsupported = validate_repo_languages(langs)
        assert valid is True
        assert primary == "Rust"
        assert config == "rust"

    def test_go_repo_is_valid(self):
        langs = {"Go": 200000, "Makefile": 5000}
        valid, primary, config, unsupported = validate_repo_languages(langs)
        assert valid is True
        assert primary == "Go"
        assert config == "go"

    def test_java_repo_is_valid(self):
        langs = {"Java": 300000, "Shell": 2000}
        valid, primary, config, unsupported = validate_repo_languages(langs)
        assert valid is True
        assert primary == "Java"
        assert config == "java"

    def test_python_repo_is_invalid(self):
        langs = {"Python": 100000, "Shell": 5000}
        valid, primary, config, unsupported = validate_repo_languages(langs)
        assert valid is False
        assert primary == "Python"
        assert config is None
        assert "Python" in unsupported

    def test_mixed_with_unsupported_secondary(self):
        # C repo with some Python scripts
        langs = {"C": 500000, "Python": 50000, "Shell": 10000}
        valid, primary, config, unsupported = validate_repo_languages(langs)
        assert valid is True
        assert primary == "C"
        assert config == "c-cpp"
        # Python is listed as unsupported secondary
        assert "Python" in unsupported

    def test_empty_dict_is_invalid(self):
        valid, primary, config, unsupported = validate_repo_languages({})
        assert valid is False
        assert primary is None

    def test_none_is_invalid(self):
        valid, primary, config, unsupported = validate_repo_languages(None)
        assert valid is False
        assert primary is None


class TestFormatValidationError:
    """Tests for format_validation_error."""

    def test_formats_error_message(self):
        langs = {"Python": 100000, "Shell": 5000}
        msg = format_validation_error(
            "my-repo", "Python", ["Python"], langs
        )
        assert "my-repo" in msg
        assert "Python" in msg
        assert "unsupported" in msg.lower()
        assert "--force" in msg

    def test_includes_percentages(self):
        langs = {"Python": 80000, "JavaScript": 20000}
        msg = format_validation_error(
            "test", "Python", ["Python", "JavaScript"], langs
        )
        assert "80.0%" in msg
        assert "20.0%" in msg


class TestSupportedLanguages:
    """Tests for SUPPORTED_LANGUAGES constant."""

    def test_contains_expected_languages(self):
        assert "c-cpp" in SUPPORTED_LANGUAGES
        assert "rust" in SUPPORTED_LANGUAGES
        assert "go" in SUPPORTED_LANGUAGES
        assert "java" in SUPPORTED_LANGUAGES

    def test_is_frozen(self):
        assert isinstance(SUPPORTED_LANGUAGES, frozenset)
