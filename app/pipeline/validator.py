"""
Dependency validation for OmniBOR Analysis.

Checks that required system packages are installed before
attempting an instrumented build.  Uses the ``PackageResolver``
abstraction so the check works on Debian/Ubuntu, RHEL/Fedora,
and Alpine.
"""


class DependencyValidator:
    """Checks that required packages are installed before build.

    Reads the ``apt_deps`` list from a repo's config entry and
    verifies each package is installed using the injected
    ``PackageResolver``.
    """

    def __init__(self, resolver=None):
        if resolver is None:
            from app.spdx.package_resolver import (
                auto_detect_resolver,
            )
            resolver = auto_detect_resolver()
        self._resolver = resolver

    def validate(self, repo_cfg):
        """Check all apt_deps are installed.

        Returns (ok, missing) where ok is True if all
        deps are present, and missing is a list of
        package names that are not installed.
        """
        apt_deps = repo_cfg.get("apt_deps", [])
        if not apt_deps:
            return True, []

        missing = []
        for pkg in apt_deps:
            if not self._resolver.is_package_installed(pkg):
                missing.append(pkg)

        if missing:
            hint = self._resolver.install_hint(missing)
            print(
                f"\n[ERROR] Missing {len(missing)} "
                "required package(s):"
            )
            for pkg in missing:
                print(f"  - {pkg}")
            print(
                f"\nInstall them with:\n"
                f"  {hint}\n"
                "\nOr add them to the Dockerfile and "
                "rebuild the image.\n"
            )
            return False, missing

        print(
            f"[OK] All {len(apt_deps)} "
            "system dependencies verified"
        )
        return True, []
