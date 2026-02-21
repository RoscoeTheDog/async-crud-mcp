"""Loguru logging setup for async-crud-mcp daemon.

This module provides standardized logging configuration using Loguru.
All daemon components MUST use Loguru for logging.

Usage:
    from .logging_setup import setup_logging, get_logger

    # At startup
    setup_logging()

    # In modules
    logger = get_logger(__name__)
    logger.info("Processing request", request_id="abc123")

Features:
    - Async-safe with enqueue=True
    - Automatic rotation (10 MB) and retention (7 days)
    - Colored console output for development
    - JSON file output for production
    - Context-bound loggers for request tracking

Requirements:
    pip install loguru
"""

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from .paths import get_logs_dir

# Default console format with colors
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# Simple format without colors (for file output)
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | "
    "{level: <8} | "
    "{name}:{function}:{line} | "
    "{message}"
)


def setup_logging(
    log_level: str | None = None,
    console: bool = True,
    file: bool = True,
    log_dir: Path | None = None,
    serialize_file: bool = True,
    diagnose_console: bool = True,
    diagnose_file: bool = False,
    service_mode: bool = False,
) -> None:
    """Configure logging with console and file handlers.

    Uses ``enqueue=True`` for thread-safe async writes. Callers MUST call
    ``await logger.complete()`` before process exit to drain the queue
    and ensure final log messages are written to disk.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Defaults to DEBUG for development/service visibility.
        console: Enable console (stderr) output.
        file: Enable file output.
        log_dir: Directory for log files (default: auto-detect using paths.py).
        serialize_file: Use JSON format for file logs.
        diagnose_console: Show variable values in console tracebacks.
        diagnose_file: Show variable values in file tracebacks (security risk!).
        service_mode: When True, skip console handler if stdout is None or
            not a tty (e.g., running as a Windows service).

    Example:
        >>> setup_logging()  # Use defaults
        >>> setup_logging(log_level="DEBUG", file=False)  # Console only
        >>> setup_logging(service_mode=True)  # File-only in service context
    """
    # Remove default handler
    logger.remove()

    # Default log level - DEBUG for development and service visibility
    if log_level is None:
        log_level = "DEBUG"

    # Console handler (development)
    # Skip in service mode when stdout is unavailable or not a tty
    if console and not (service_mode and (sys.stdout is None or not sys.stdout.isatty())):
        logger.add(
            sys.stderr,
            format=CONSOLE_FORMAT,
            level=log_level,
            colorize=True,
            backtrace=True,
            diagnose=diagnose_console,
            enqueue=True,  # Async-safe - CRITICAL for async operations
        )

    # File handler (production)
    if file:
        if log_dir is None:
            # Default to platform-appropriate logs directory
            log_dir = get_logs_dir()
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        logger.add(
            str(log_dir / "server.log"),
            level=log_level,
            format=FILE_FORMAT,
            rotation="10 MB",
            retention="7 days",
            compression="gz",
            serialize=serialize_file,  # JSON output
            enqueue=True,  # Async-safe
            backtrace=True,
            diagnose=diagnose_file,  # SECURITY: False in production
        )


def get_logger(name: str, **context: Any) -> "logger":
    """Get a context-bound logger.

    Args:
        name: Logger name (usually __name__)
        **context: Additional context to bind to all log messages

    Returns:
        Logger instance with bound context

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing")

        >>> logger = get_logger(__name__, request_id="abc123")
        >>> logger.info("Processing")  # Includes request_id in output
    """
    return logger.bind(name=name, **context)


def add_request_context(request_id: str, **extra: Any) -> "logger":
    """Create a logger with request context for tracing.

    Args:
        request_id: Unique request identifier
        **extra: Additional context (user_id, session_id, etc.)

    Returns:
        Logger with request context bound

    Example:
        >>> req_logger = add_request_context("req-123", user_id="alice")
        >>> req_logger.info("Processing request")
    """
    return logger.bind(request_id=request_id, **extra)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Logging Setup Test")
    parser.add_argument("--level", default="DEBUG", help="Log level")
    parser.add_argument("--no-file", action="store_true", help="Disable file")
    args = parser.parse_args()

    setup_logging(
        log_level=args.level,
        file=not args.no_file,
        log_dir=Path("./logs"),
    )

    log = get_logger(__name__)
    log.debug("Debug message")
    log.info("Info message")
    log.warning("Warning message")
    log.error("Error message")

    # Test with context
    req_log = add_request_context("test-123", user="alice")
    req_log.info("Request processed")
