"""Autonomous agent helpers (s11).

Task board scanning and claiming are now on TaskManager itself
(scan_unclaimed, claim_task). This module is kept for reference
but the canonical implementations live in tools/task_board.py.
"""

from __future__ import annotations

# All functionality has been moved to TaskManager.scan_unclaimed()
# and TaskManager.claim_task() which are atomic and lock-protected.
# See tools/task_board.py.
