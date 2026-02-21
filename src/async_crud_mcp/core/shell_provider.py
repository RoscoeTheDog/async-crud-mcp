"""Cross-platform shell detection for subprocess execution.

Mirrors Claude Code's approach: always use bash (even on Windows via Git Bash)
so that shell syntax (pipes, &&, env vars, redirections) works identically
across platforms.
"""

import os
import shutil
import sys
from pathlib import Path


class ShellNotFoundError(RuntimeError):
    """Raised when no suitable shell binary can be located."""


class ShellProvider:
    """Cross-platform bash detection for subprocess execution."""

    def __init__(self) -> None:
        self._shell_path: str | None = None

    @property
    def shell_path(self) -> str:
        """Return cached shell path, detecting on first access."""
        if self._shell_path is None:
            self._shell_path = self._detect_shell()
        return self._shell_path

    def _detect_shell(self) -> str:
        if sys.platform == "win32":
            return self._find_windows_bash()
        return self._find_posix_shell()

    def _find_windows_bash(self) -> str:
        # 1. Explicit env var (matches Claude Code convention)
        env_path = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
        if env_path and os.path.isfile(env_path):
            return env_path

        # 2. bash on PATH (e.g. Git Bash already in PATH)
        bash_on_path = shutil.which("bash")
        if bash_on_path:
            return bash_on_path

        # 3. Derive from git location: git.exe -> ../../bin/bash.exe
        git_path = shutil.which("git")
        if git_path:
            git_dir = Path(git_path).resolve().parent
            # git.exe is usually in Git/cmd/ or Git/bin/
            for relative in (
                git_dir.parent / "bin" / "bash.exe",
                git_dir / "bash.exe",
            ):
                if relative.is_file():
                    return str(relative)

        # 4. Known installation paths
        for known in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.isfile(known):
                return known

        raise ShellNotFoundError(
            "Git Bash not found. Install Git for Windows: "
            "https://git-scm.com/downloads/win"
        )

    def _find_posix_shell(self) -> str:
        # 1. User's login shell if it's bash or zsh
        login_shell = os.environ.get("SHELL", "")
        if login_shell and os.path.isfile(login_shell):
            shell_name = os.path.basename(login_shell)
            if shell_name in ("bash", "zsh"):
                return login_shell

        # 2. bash on PATH
        bash_on_path = shutil.which("bash")
        if bash_on_path:
            return bash_on_path

        # 3. Well-known fallbacks
        for fallback in ("/bin/bash", "/bin/sh"):
            if os.path.isfile(fallback):
                return fallback

        raise ShellNotFoundError(
            "No suitable shell found. Ensure bash is installed and on PATH."
        )

    def build_exec_args(self, command: str) -> list[str]:
        """Return args list for anyio subprocess: [bash_path, '-c', command]."""
        return [self.shell_path, "-c", command]
