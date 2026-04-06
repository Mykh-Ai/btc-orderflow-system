from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import DATE_FORMAT, ScopeInfo


class ScopeDiscoveryError(RuntimeError):
    """Raised when bundle scope cannot be discovered from local review folders."""


def discover_scope(input_root: str | Path, output_root: str | Path) -> ScopeInfo:
    in_root = Path(input_root)
    out_root = Path(output_root)
    if not in_root.exists():
        raise ScopeDiscoveryError(f"input root does not exist: {in_root}")
    review_dirs: list[Path] = []
    for child in sorted(in_root.iterdir()):
        if not child.is_dir():
            continue
        try:
            datetime.strptime(child.name, DATE_FORMAT)
        except ValueError:
            continue
        review_dirs.append(child)
    if not review_dirs:
        raise ScopeDiscoveryError(f"no valid daily review folders found under: {in_root}")
    return ScopeInfo(
        input_root=in_root,
        output_root=out_root,
        review_dirs=review_dirs,
        scope_start=review_dirs[0].name,
        scope_end=review_dirs[-1].name,
    )
