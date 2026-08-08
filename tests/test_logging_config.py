"""Tests for the logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tgi.logging_config import setup_logging


def test_setup_logging_creates_a_rotating_file(tmp_path: Path) -> None:
    """Unbounded log files would eventually fill the disk of a long lived service."""
    setup_logging(app_name="tgi_test", log_dir=tmp_path, max_bytes=1024, backup_count=2)
    handlers = logging.getLogger().handlers
    rotating = [h for h in handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == 1024
    assert rotating[0].backupCount == 2
    assert (tmp_path / "tgi_test.log").exists()


def test_setup_logging_rotates_when_the_file_grows(tmp_path: Path) -> None:
    setup_logging(app_name="tgi_rot", log_dir=tmp_path, max_bytes=500, backup_count=1)
    logger = logging.getLogger("tgi.rotation.test")
    for i in range(200):
        logger.warning("ligne de log accentuee numero %d avec du contenu", i)
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert (tmp_path / "tgi_rot.log").exists()
    assert (tmp_path / "tgi_rot.log.1").exists()


def test_setup_logging_creates_a_missing_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "logs"
    setup_logging(app_name="tgi_mk", log_dir=target)
    assert (target / "tgi_mk.log").exists()


def test_setup_logging_writes_utf8(tmp_path: Path) -> None:
    """Windows defaults to cp1252, which would mangle French messages."""
    setup_logging(app_name="tgi_utf8", log_dir=tmp_path)
    logging.getLogger("tgi.utf8.test").warning("règle métier créée à l'étape")
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = (tmp_path / "tgi_utf8.log").read_text(encoding="utf-8")
    assert "règle métier créée" in content
