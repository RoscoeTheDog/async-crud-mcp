"""Cross-platform user session detection via polling.

This module provides user session detection for Windows, macOS, and Linux
using polling-based methods (no notification hooks that users could disable).

Usage:
    from session_detector import get_active_sessions, is_user_session_active

    # Get all active users
    users = get_active_sessions()
    print(f"Active users: {users}")

    # Check specific user
    if is_user_session_active("alice"):
        print("Alice is logged in")

Platform Detection Methods:
    - Windows: WTS API via pywin32
    - macOS: /dev/console ownership
    - Linux: /run/user/{uid} directories (systemd-logind)
"""

import sys
from typing import List


def get_active_sessions() -> List[str]:
    """Return list of usernames with active login sessions.

    Uses polling-based detection (no hooks/notifications to disable).
    Minimal overhead - suitable for 3-second polling intervals.

    Returns:
        List of lowercase usernames with active sessions
    """
    if sys.platform == "win32":
        return _get_windows_sessions()
    elif sys.platform == "darwin":
        return _get_macos_sessions()
    else:
        return _get_linux_sessions()


def _get_windows_sessions() -> List[str]:
    """Detect active Windows sessions via WTS API."""
    try:
        import win32ts

        sessions = win32ts.WTSEnumerateSessions(
            win32ts.WTS_CURRENT_SERVER_HANDLE
        )
        active_users = []

        for session in sessions:
            # WTSActive = user logged in and session is active
            # WTSConnected = session connected (RDP reconnected, etc.)
            if session['State'] in (win32ts.WTSActive, win32ts.WTSConnected):
                try:
                    session_id = int(session['SessionId'])
                    username = win32ts.WTSQuerySessionInformation(
                        win32ts.WTS_CURRENT_SERVER_HANDLE,
                        session_id,
                        win32ts.WTSUserName
                    )
                    if username:
                        active_users.append(username.lower())
                except Exception:
                    continue

        return active_users
    except ImportError:
        # pywin32 not available (shouldn't happen on Windows)
        return []


def _get_macos_sessions() -> List[str]:
    """Detect active macOS sessions via console user check."""
    import subprocess

    try:
        # Get current console user (GUI login)
        result = subprocess.run(
            ['stat', '-f', '%Su', '/dev/console'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            console_user = result.stdout.strip()
            # Ignore system users
            if console_user not in ('root', '_windowserver', 'loginwindow'):
                return [console_user.lower()]
    except Exception:
        pass

    return []


def _get_linux_sessions() -> List[str]:
    """Detect active Linux sessions via /run/user directories.

    /run/user/{uid} exists when user has an active session via systemd-logind.
    This is the most reliable method and doesn't require D-Bus.
    """
    from pathlib import Path
    import pwd

    active_users = []
    run_user = Path('/run/user')

    if run_user.exists():
        for uid_dir in run_user.iterdir():
            try:
                uid = int(uid_dir.name)
                # Skip system users (UID < 1000 on most systems)
                if uid >= 1000:
                    user_info = pwd.getpwuid(uid)
                    active_users.append(user_info.pw_name.lower())
            except (ValueError, KeyError):
                continue

    return active_users


def is_user_session_active(username: str) -> bool:
    """Check if a specific user has an active session.

    Args:
        username: OS username to check (case-insensitive)

    Returns:
        True if user has an active login session
    """
    return username.lower() in get_active_sessions()


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Session Detector")
    parser.add_argument("--user", "-u", help="Check specific user")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.user:
        active = is_user_session_active(args.user)
        if args.json:
            print(json.dumps({"username": args.user, "active": active}))
        else:
            print(f"{args.user}: {'active' if active else 'inactive'}")
    else:
        users = get_active_sessions()
        if args.json:
            print(json.dumps({"active_users": users, "platform": sys.platform}))
        else:
            print(f"Platform: {sys.platform}")
            print(f"Active users: {', '.join(users) or 'none'}")
