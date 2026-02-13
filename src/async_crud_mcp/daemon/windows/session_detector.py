"""Windows session detection via WTS API.

This module provides user session detection for Windows using the
Windows Terminal Services (WTS) API via pywin32.

Usage:
    from session_detector import get_active_sessions, is_user_session_active

    # Get all active users
    users = get_active_sessions()
    print(f"Active users: {users}")

    # Check specific user
    if is_user_session_active("alice"):
        print("Alice is logged in")

Requirements:
    pip install pywin32
"""

import sys
from typing import List

if sys.platform != "win32":
    raise ImportError("This module is Windows-only")

import win32ts


def get_active_sessions() -> List[str]:
    """Return list of usernames with active login sessions.

    Uses WTS API to enumerate sessions. Only returns users with
    WTSActive or WTSConnected state (logged in and session usable).

    Returns:
        List of lowercase usernames with active sessions

    Example:
        >>> get_active_sessions()
        ['alice', 'bob']
    """
    try:
        sessions = win32ts.WTSEnumerateSessions(
            win32ts.WTS_CURRENT_SERVER_HANDLE
        )
        active_users = []

        for session in sessions:
            # WTSActive = user logged in and session is active
            # WTSConnected = session connected (RDP reconnected, etc.)
            if session['State'] in (win32ts.WTSActive, win32ts.WTSConnected):
                try:
                    username = win32ts.WTSQuerySessionInformation(
                        win32ts.WTS_CURRENT_SERVER_HANDLE,
                        session['SessionId'],
                        win32ts.WTSUserName
                    )
                    if username:
                        active_users.append(username.lower())
                except Exception:
                    continue

        return active_users
    except ImportError:
        # pywin32 not available
        return []
    except Exception:
        return []


def is_user_session_active(username: str) -> bool:
    """Check if a specific user has an active session.

    Args:
        username: OS username to check (case-insensitive)

    Returns:
        True if user has an active login session

    Example:
        >>> is_user_session_active("Alice")
        True
    """
    return username.lower() in get_active_sessions()


def get_session_details(username: str) -> dict:
    """Get detailed session information for a user.

    Args:
        username: OS username to look up

    Returns:
        Dict with session details or empty dict if not found
    """
    try:
        sessions = win32ts.WTSEnumerateSessions(
            win32ts.WTS_CURRENT_SERVER_HANDLE
        )

        for session in sessions:
            try:
                session_user = win32ts.WTSQuerySessionInformation(
                    win32ts.WTS_CURRENT_SERVER_HANDLE,
                    session['SessionId'],
                    win32ts.WTSUserName
                )
                if session_user and session_user.lower() == username.lower():
                    state_map = {
                        win32ts.WTSActive: "active",
                        win32ts.WTSConnected: "connected",
                        win32ts.WTSConnectQuery: "connect_query",
                        win32ts.WTSShadow: "shadow",
                        win32ts.WTSDisconnected: "disconnected",
                        win32ts.WTSIdle: "idle",
                        win32ts.WTSListen: "listen",
                        win32ts.WTSReset: "reset",
                        win32ts.WTSDown: "down",
                        win32ts.WTSInit: "init",
                    }
                    return {
                        "username": session_user,
                        "session_id": session['SessionId'],
                        "state": state_map.get(session['State'], "unknown"),
                        "state_code": session['State'],
                        "is_active": session['State'] in (
                            win32ts.WTSActive,
                            win32ts.WTSConnected
                        ),
                    }
            except Exception:
                continue

        return {}
    except Exception:
        return {}


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Windows Session Detector")
    parser.add_argument("--user", "-u", help="Check specific user")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.user:
        if args.json:
            details = get_session_details(args.user)
            print(json.dumps(details, indent=2))
        else:
            active = is_user_session_active(args.user)
            print(f"{args.user}: {'active' if active else 'inactive'}")
    else:
        users = get_active_sessions()
        if args.json:
            print(json.dumps({"active_users": users}, indent=2))
        else:
            print(f"Active users: {', '.join(users) or 'none'}")
