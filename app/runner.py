"""
Command execution wrapper for OmniBOR Analysis.

Provides a unified interface for running shell commands
with logging and error reporting.
"""

import os
import subprocess


class CommandRunner:
    """Wraps subprocess execution with logging."""

    def run(self, cmd, cwd=None, description=""):
        """Run a shell command, print output, return exit code."""
        print(f"\n{'='*60}")
        print(f"  {description}")
        print(f"  CMD: {cmd}")
        print(f"  CWD: {cwd or os.getcwd()}")
        print(f"{'='*60}\n")
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
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
