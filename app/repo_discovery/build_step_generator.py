"""
Build step generation — generates build commands per build system.
"""


class BuildStepGenerator:
    """Generates build commands based on build system type."""

    _RECIPES = {
        "autoconf": "_autoconf",
        "cmake": "_cmake",
        "meson": "_meson",
        "perl-configure": "_perl_configure",
        "auto-configure": "_auto_configure",
        "configure-only": "_configure_only",
        "make-only": "_make_only",
    }

    def generate(self, build_system, flags):
        """Return a list of shell commands to build."""
        method_name = self._RECIPES.get(
            build_system
        )
        if method_name:
            method = getattr(self, method_name)
            return method(flags)
        return self._unknown(flags)

    @staticmethod
    def _autoconf(flags):
        steps = ["autoreconf -fi"]
        cmd = "./configure"
        if flags:
            cmd += " " + " ".join(flags)
        steps.append(cmd)
        steps.append("make -j$(nproc)")
        return steps

    @staticmethod
    def _cmake(flags):
        base = (
            "mkdir -p build && cd build && cmake .."
        )
        if flags:
            base += " " + " ".join(flags)
        return [base, "make -C build -j$(nproc)"]

    @staticmethod
    def _meson(_flags):
        return [
            "meson setup build",
            "ninja -C build",
        ]

    @staticmethod
    def _perl_configure(_flags):
        return ["./config", "make -j$(nproc)"]

    @staticmethod
    def _auto_configure(_flags):
        return ["auto/configure", "make -j$(nproc)"]

    @staticmethod
    def _configure_only(flags):
        cmd = "./configure"
        if flags:
            cmd += " " + " ".join(flags)
        return [cmd, "make -j$(nproc)"]

    @staticmethod
    def _make_only(_flags):
        return ["make -j$(nproc)"]

    @staticmethod
    def _unknown(_flags):
        return [
            "# TODO: determine build steps manually",
            "make -j$(nproc)",
        ]
