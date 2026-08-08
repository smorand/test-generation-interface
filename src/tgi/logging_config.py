"""Reusable logging configuration with colors and file output."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.logging import RichHandler

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LOG_FORMAT = "%(module)s.%(funcName)s: %(message)s"
FILE_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s %(module)s.%(funcName)s: %(message)s"


def setup_logging(
    app_name: str = "app",
    level: LogLevel = "INFO",
    *,
    verbose: bool = False,
    quiet: bool = False,
    log_dir: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure logging with colors (console) and file output.

    Writes logs to <app_name>.log in the specified directory.
    Console output uses rich for colored, human-friendly display.

    Args:
        app_name: Application name, used for log file naming (<app_name>.log)
        level: Base log level (default: INFO)
        verbose: If True, set level to DEBUG (overrides level)
        quiet: If True, set level to WARNING (overrides level and verbose)
        log_dir: Directory for log files (default: current working directory)
        max_bytes: Rotate the log file once it reaches this size
        backup_count: How many rotated files to keep
    """
    if quiet:
        effective_level = "WARNING"
    elif verbose:
        effective_level = "DEBUG"
    else:
        effective_level = level

    directory = log_dir or Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"{app_name}.log"

    console = Console(stderr=True)
    console_handler = RichHandler(
        console=console,
        show_time=True,
        omit_repeated_times=False,  # repeat the timestamp on every line, never leave it blank
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        log_time_format="[ %Y-%m-%d %H:%M:%S ]",
    )
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # Rotating, so a long lived deployment cannot fill the disk with logs.
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT))
    file_handler.setLevel(effective_level)

    logging.basicConfig(
        level=effective_level,
        handlers=[console_handler, file_handler],
        force=True,
    )
