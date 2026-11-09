#!/usr/bin/env python3

"""
Structured event reporting for Cordra scripts and batch helpers.

Trimmed port of cordra-config/scripts/lib/libreporting.py.

Libraries emit via Reporter; CLI entrypoints wire ConsoleReporter.

Levels (severity):
  debug, info, progress — operational output
  warning              — data quality; job continues
  error                — record/batch failure; job usually continues
  critical             — job must stop (config, Cordra connect, …)
"""

from __future__ import annotations

from typing import Any, Optional, Protocol


LEVELS = frozenset({"debug", "info", "progress", "warning", "error", "critical"})


class HarvestAbort(Exception):
    """Raised after a critical event; the job cannot continue."""


class Reporter(Protocol):
    def emit(
        self,
        level: str,
        message: str,
        *,
        category: Optional[str] = None,
        record_id: Optional[str] = None,
        stats: Optional[dict] = None,
        **extra: Any,
    ) -> None:
        ...


class NullReporter:
    def emit(
        self,
        level: str,
        message: str,
        *,
        category: Optional[str] = None,
        record_id: Optional[str] = None,
        stats: Optional[dict] = None,
        **extra: Any,
    ) -> None:
        return None


def format_event_message(
    level: str,
    message: str,
    *,
    category: Optional[str] = None,
    record_id: Optional[str] = None,
) -> str:
    if level == "warning" and category:
        prefix = f"    - WARNING [{category}]"
        if record_id:
            prefix += f" {record_id}"
        return f"{prefix}: {message}" if message else prefix
    if level == "critical":
        cat = f" [{category}]" if category else ""
        return f"    - CRITICAL{cat}: {message}"
    if level == "error":
        cat = f" [{category}]" if category else ""
        rid = f" {record_id}" if record_id else ""
        return f"    - ERROR{cat}{rid}: {message}"
    if level == "debug":
        return f"    - DEBUG: {message}"
    return message


class ConsoleReporter:
    """Print events to stdout."""

    def emit(
        self,
        level: str,
        message: str,
        *,
        category: Optional[str] = None,
        record_id: Optional[str] = None,
        stats: Optional[dict] = None,
        **extra: Any,
    ) -> None:
        if level not in LEVELS:
            level = "info"
        print(
            format_event_message(level, message, category=category, record_id=record_id),
            flush=True,
        )


def reporter_or_null(reporter: Optional[Reporter]) -> Reporter:
    return reporter if reporter is not None else NullReporter()


def emit_critical(
    reporter: Optional[Reporter],
    message: str,
    *,
    category: str = "fatal",
    record_id: Optional[str] = None,
    stats: Optional[dict] = None,
    **extra: Any,
) -> None:
    """Emit a critical event and abort."""
    rep = reporter_or_null(reporter)
    rep.emit(
        "critical",
        message,
        category=category,
        record_id=record_id,
        stats=stats,
        **extra,
    )
    raise HarvestAbort(message)
