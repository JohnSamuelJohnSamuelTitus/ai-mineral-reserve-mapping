"""Safe managed filesystem operations with path-traversal, file-size, and disk guardrails."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UnsafePathError(ValueError):
    """Raised when a path escapes the managed data directory or uses invalid segments."""


class StorageLimitError(RuntimeError):
    """Raised when file size or free disk space violates safety guardrails."""


def sanitize_filename(name: str, *, fallback: str = "artifact") -> str:
    """Strip path separators and coerce filename into safe ASCII tokens."""
    base = Path(name).name.strip()
    cleaned = _SAFE_SEGMENT_RE.sub("_", base).strip("._")
    if not cleaned:
        return fallback
    return cleaned[:120]


def resolve_safe_path(base_dir: Path, *parts: str) -> Path:
    """Resolve a path strictly inside `base_dir`, rejecting traversal attempts."""
    if not parts:
        raise UnsafePathError("At least one relative path segment is required")
    base_resolved = base_dir.resolve()
    candidate = base_resolved
    for part in parts:
        if not part or "\x00" in part:
            raise UnsafePathError("Empty or null-byte path segment rejected")
        p = Path(part)
        if p.is_absolute() or ".." in p.parts:
            raise UnsafePathError(f"Path traversal or absolute segment rejected: '{part}'")
        candidate = (candidate / part).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise UnsafePathError(
            f"Resolved path '{candidate}' escapes managed root '{base_resolved}'"
        ) from exc
    return candidate


def check_free_disk_space(target_dir: Path, *, min_free_gb: float = 2.0, required_mb: float = 0.0) -> float:
    """Return available disk space (GB) after ensuring safety headroom remains."""
    target_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target_dir)
    free_gb = usage.free / (1024**3)
    projected_free_gb = (usage.free - required_mb * (1024**2)) / (1024**3)
    if projected_free_gb < min_free_gb:
        raise StorageLimitError(
            f"Insufficient free disk space on {target_dir.drive or target_dir}: "
            f"{free_gb:.2f} GB free, {required_mb:.1f} MB needed, "
            f"minimum headroom {min_free_gb:.2f} GB."
        )
    return round(free_gb, 3)


def validate_file_size(size_bytes: int, *, max_mb: float) -> None:
    """Enforce maximum upload or download byte limit."""
    max_bytes = int(max_mb * 1024 * 1024)
    if size_bytes <= 0:
        raise StorageLimitError("File payload is empty (0 bytes)")
    if size_bytes > max_bytes:
        raise StorageLimitError(
            f"File size {size_bytes / (1024 * 1024):.2f} MB exceeds limit of {max_mb:.1f} MB"
        )


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest using bounded 1 MB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def managed_temp_dir(prefix: str = "mineral_proc_") -> Iterator[Path]:
    """Create a temporary directory and guarantee cleanup after processing."""
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        yield Path(tmp)

