"""
Language validation for OmniBOR analysis.

Checks that a repository's primary languages are supported by the
current OmniBOR/bomsh installation before cloning.
"""

# Supported languages in OmniBOR config format
SUPPORTED_LANGUAGES = frozenset({
    "c-cpp",
    "rust",
    "go",
    "java",
})

# GitHub language name → OmniBOR config value mapping
GITHUB_TO_CONFIG = {
    "c": "c-cpp",
    "c++": "c-cpp",
    "rust": "rust",
    "go": "go",
    "java": "java",
    "kotlin": "java",  # Builds with Maven/Gradle
    "scala": "java",   # Builds with Maven/Gradle
}

# Languages that are often mixed with supported languages
# (not primary, but acceptable as secondary)
MIXED_LANGUAGES = frozenset({
    "shell",
    "makefile",
    "cmake",
    "m4",
    "assembly",
    "objective-c",  # Often in C projects
    "objective-c++",
})


def map_github_language(github_lang):
    """Map a GitHub language name to OmniBOR config value.

    Args:
        github_lang: Language name from GitHub API (e.g., "C++")

    Returns:
        OmniBOR config value (e.g., "c-cpp") or None if unsupported
    """
    if not github_lang:
        return None
    return GITHUB_TO_CONFIG.get(github_lang.lower())


def validate_repo_languages(languages_dict):
    """Validate that a repo's languages are supported.

    Args:
        languages_dict: Dict from GitHub API /repos/{owner}/{repo}/languages
            e.g., {"C": 500000, "Shell": 10000, "Makefile": 5000}

    Returns:
        tuple: (is_valid, primary_lang, detected_config, unsupported_list)
            - is_valid: True if primary language is supported
            - primary_lang: The primary language (highest byte count)
            - detected_config: The mapped config value (e.g., "c-cpp")
            - unsupported_list: List of unsupported source languages found
    """
    if not languages_dict:
        return False, None, None, []

    # Sort by byte count (highest first)
    sorted_langs = sorted(
        languages_dict.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    primary_lang = sorted_langs[0][0] if sorted_langs else None
    detected_config = map_github_language(primary_lang)

    # Find unsupported source languages (excluding mixed/build langs)
    unsupported = []
    for lang, _ in sorted_langs:
        lang_lower = lang.lower()
        if lang_lower not in MIXED_LANGUAGES:
            mapped = map_github_language(lang)
            if mapped is None:
                unsupported.append(lang)

    is_valid = detected_config in SUPPORTED_LANGUAGES

    return is_valid, primary_lang, detected_config, unsupported


def format_validation_error(
    repo_name, primary_lang, unsupported_list, languages_dict
):
    """Format a validation error message.

    Args:
        repo_name: Name of the repository
        primary_lang: The primary detected language
        unsupported_list: List of unsupported languages
        languages_dict: Full language breakdown from GitHub

    Returns:
        Formatted error message string
    """
    lines = [
        f"[ERROR] Repository '{repo_name}' uses unsupported languages.",
        "",
        "Detected languages (by bytes):",
    ]

    total_bytes = sum(languages_dict.values())
    for lang, bytes_count in sorted(
        languages_dict.items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        pct = (bytes_count / total_bytes * 100) if total_bytes else 0
        mapped = map_github_language(lang)
        status = "✓" if mapped else "✗"
        lines.append(f"  {status} {lang}: {pct:.1f}%")

    lines.extend([
        "",
        f"Primary language: {primary_lang}",
        f"Unsupported: {', '.join(unsupported_list)}",
        "",
        "OmniBOR currently supports: C, C++, Rust, Go, Java",
        "",
        "To force analysis anyway, use: --force",
    ])

    return "\n".join(lines)
