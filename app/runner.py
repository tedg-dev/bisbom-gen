"""
Command execution wrapper for OmniBOR Analysis.

Provides a unified interface for running shell commands
with logging and error reporting.
"""

import os
import subprocess


class CommandRunner:
    """Wraps subprocess execution with logging."""

    def run(
        self, cmd, cwd=None, description="",
        env=None,
    ):
        """Run a shell command, print output, return exit code.

        Args:
            cmd: Shell command string.
            cwd: Working directory (default: current).
            description: Human-readable label for logging.
            env: Extra environment variables to merge with
                ``os.environ``.  ``None`` preserves the
                current environment unchanged.
        """
        print(f"\n{'='*60}")
        print(f"  {description}")
        print(f"  CMD: {cmd}")
        print(f"  CWD: {cwd or os.getcwd()}")
        if env:
            print(f"  ENV: {list(env.keys())}")
        print(f"{'='*60}\n")
        run_env = None
        if env:
            run_env = os.environ.copy()
            run_env.update(env)
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(
                "[ERROR] Command exited with "
                f"code {result.returncode}"
            )
        return result.returncode
