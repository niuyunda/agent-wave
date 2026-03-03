"""Shared pull request status models."""

from __future__ import annotations

from enum import Enum


class PrStatus(str, Enum):
    """Normalized PR status values used across layers."""

    WAITING = "waiting"
    NEEDS_WORK = "needs_work"
    DONE = "done"
    CLOSED = "closed"
