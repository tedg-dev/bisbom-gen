"""
Dependency validation for OmniBOR Analysis.

Checks that required apt packages are installed before
attempting an instrumented build.
"""

from app.runner import CommandRunner


class DependencyValidator:
    """Checks that required apt packages are installed before build.

    Reads the apt_deps list from a repo's config entry and
    verifies each package is installed via dpkg-query.
    """

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

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
            rc = self.runner.run(
                f"dpkg-query -W -f='${{Status}}' "
                f"{pkg} 2>/dev/null "
                "| grep -q 'install ok installed'",
                description=(
                    f"Checking dependency: {pkg}"
                ),
            )
            if rc != 0:
                missing.append(pkg)

        if missing:
            print(
                f"\n[ERROR] Missing {len(missing)} "
                "required package(s):"
            )
            for pkg in missing:
                print(f"  - {pkg}")
            print(
                "\nInstall them with:\n"
                f"  apt-get install -y "
                f"{' '.join(missing)}\n"
                "\nOr add them to the Dockerfile's "
                "apt-get install list and rebuild "
                "the image.\n"
            )
            return False, missing

        print(
            f"[OK] All {len(apt_deps)} "
            "apt dependencies verified"
        )
        return True, []
