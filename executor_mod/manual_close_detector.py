from __future__ import annotations

from typing import Any, Dict


def tick(
    st: Dict[str, Any],
    pos: Dict[str, Any],
    api: Any,
    margin_policy: Any,
    env: Dict[str, Any],
    now_s: float,
) -> bool:
    return False
