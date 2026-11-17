"""Safe retention planning for local ops and simulation logs.

Planning is side-effect free. ``apply_retention`` only unlinks regular files
that are still inside a managed directory under the planned root.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

MANAGED_PATTERNS = {
    "simulations": ("*.log",),
    "ops": ("*.json", "*.md"),
    "daily": ("*.json", "*.md"),
}
DEFAULT_KEEP_DAYS = 30
DEFAULT_MIN_AGE_DAYS = 1
DEFAULT_MAX_TOTAL_MB = 512
PLAN_SCHEMA = "aihf-retention-plan-v1"
ACTIVE_SIMULATION_STATUSES = ("pending", "running", "cancelling")
SIMULATION_LOG_PATTERN = re.compile(r"sim-(\d+)\.log")


class RetentionStateError(ValueError):
    """Retention could not verify runtime state required for safe deletion."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ManagedFile:
    path: Path
    relative: str
    size: int
    mtime_ns: int
    modified: datetime
    directory: str

    def as_dict(self) -> dict:
        return {
            "path": self.relative,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "modified": self.modified.isoformat(),
            "directory": self.directory,
        }


@dataclass(frozen=True)
class Selection:
    file: ManagedFile
    reason: str

    def as_dict(self) -> dict:
        return self.file.as_dict() | {"reason": self.reason}


@dataclass(frozen=True)
class RetentionPlan:
    root: Path
    generated_at: datetime
    keep_days: int
    min_age_days: int
    max_total_bytes: int
    files: tuple[ManagedFile, ...]
    selected: tuple[Selection, ...]
    skipped: tuple[dict, ...]
    total_bytes: int
    selected_bytes: int
    remaining_bytes: int
    over_budget: bool
    active_simulation_ids: tuple[int, ...] = ()

    @property
    def current_over_budget(self) -> bool:
        return self.total_bytes > self.max_total_bytes

    def as_dict(self) -> dict:
        return {
            "root": str(self.root),
            "generated_at": self.generated_at.isoformat(),
            "keep_days": self.keep_days,
            "min_age_days": self.min_age_days,
            "max_total_bytes": self.max_total_bytes,
            "total_files": len(self.files),
            "total_bytes": self.total_bytes,
            "selected_files": len(self.selected),
            "selected_bytes": self.selected_bytes,
            "remaining_bytes": self.remaining_bytes,
            "current_over_budget": self.current_over_budget,
            "over_budget": self.over_budget,
            "selected": [item.as_dict() for item in self.selected],
            "skipped": list(self.skipped),
            "active_simulation_ids": list(self.active_simulation_ids),
        }


@dataclass(frozen=True)
class ApplyResult:
    deleted: tuple[str, ...]
    errors: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {"deleted": list(self.deleted), "errors": list(self.errors)}


def save_plan(plan: RetentionPlan, path: str | Path) -> Path:
    """Persist the exact reviewed target set for a later ``--apply``."""
    target = Path(path)
    payload = {
        "schema": PLAN_SCHEMA,
        **plan.as_dict(),
        "files": [item.as_dict() for item in plan.files],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_plan(path: str | Path, *, expected_root: str | Path | None = None) -> RetentionPlan:
    """Load a saved plan without rescanning; apply only the reviewed targets."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported retention plan schema")
    root = Path(payload["root"])
    if expected_root is not None and Path(os.path.abspath(root)) != Path(os.path.abspath(expected_root)):
        raise ValueError(f"retention plan root {root} does not match {expected_root}")
    files = tuple(_file_from_dict(root, item) for item in payload.get("files", []))
    by_relative = {item.relative: item for item in files}
    if len(by_relative) != len(files):
        raise ValueError("retention plan contains duplicate files")
    selected: list[Selection] = []
    seen: set[str] = set()
    for entry in payload.get("selected", []):
        relative = str(entry.get("path", ""))
        if relative in seen:
            raise ValueError("retention plan contains duplicate selections")
        item = by_relative.get(relative)
        if item is None:
            raise ValueError(f"retention plan selection is not in files: {relative}")
        selected.append(Selection(item, str(entry.get("reason", "saved_plan"))))
        seen.add(relative)
    max_total_bytes = int(payload["max_total_bytes"])
    active_simulation_ids = tuple(sorted({int(value) for value in payload.get("active_simulation_ids", [])}))
    total_bytes = sum(item.size for item in files)
    selected_bytes = sum(item.file.size for item in selected)
    remaining_bytes = total_bytes - selected_bytes
    return RetentionPlan(
        root=root,
        generated_at=datetime.fromisoformat(payload["generated_at"]),
        keep_days=int(payload["keep_days"]),
        min_age_days=int(payload["min_age_days"]),
        max_total_bytes=max_total_bytes,
        files=files,
        selected=tuple(selected),
        skipped=tuple(payload.get("skipped", [])),
        total_bytes=total_bytes,
        selected_bytes=selected_bytes,
        remaining_bytes=remaining_bytes,
        over_budget=remaining_bytes > max_total_bytes,
        active_simulation_ids=active_simulation_ids,
    )


def load_active_simulation_run_ids(fund_db: str | Path) -> frozenset[int]:
    """Read pending/running/cancelling run IDs without opening the database writable."""
    path = Path(fund_db)
    if not path.exists():
        return frozenset()
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
            rows = connection.execute(
                f"SELECT id FROM sim_run WHERE status IN ({','.join('?' for _ in ACTIVE_SIMULATION_STATUSES)})",
                ACTIVE_SIMULATION_STATUSES,
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: sim_run" in str(exc):
            return frozenset()
        raise RetentionStateError(f"could not read active simulation state from {path}: {type(exc).__name__}") from exc
    except sqlite3.Error as exc:
        raise RetentionStateError(f"could not read active simulation state from {path}: {type(exc).__name__}") from exc
    return frozenset(int(row[0]) for row in rows)


def _file_from_dict(root: Path, entry: dict) -> ManagedFile:
    relative = str(entry.get("path", ""))
    rel_path = Path(relative)
    directory = str(entry.get("directory", ""))
    if not relative or rel_path.is_absolute() or ".." in rel_path.parts or len(rel_path.parts) != 2 or rel_path.parts[0] != directory or directory not in MANAGED_PATTERNS or not any(rel_path.match(pattern) for pattern in MANAGED_PATTERNS[directory]):
        raise ValueError(f"unsafe retention plan path: {relative!r}")
    return ManagedFile(
        path=root / rel_path,
        relative=relative,
        size=int(entry["size"]),
        mtime_ns=int(entry["mtime_ns"]),
        modified=datetime.fromisoformat(entry["modified"]),
        directory=directory,
    )


def build_retention_plan(
    root: str | Path,
    *,
    now: datetime | None = None,
    keep_days: int = DEFAULT_KEEP_DAYS,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_MB * 1024 * 1024,
    active_simulation_ids: set[int] | frozenset[int] | tuple[int, ...] = (),
) -> RetentionPlan:
    """Return a deterministic deletion plan without changing the filesystem."""
    if keep_days < 0 or min_age_days < 0 or max_total_bytes < 0:
        raise ValueError("retention values must be non-negative")
    root_path = Path(root)
    generated_at = now or _utcnow()
    files, skipped = _scan(root_path)
    active_ids = tuple(sorted({int(value) for value in active_simulation_ids}))
    active_lookup = set(active_ids)
    newest_by_directory: dict[str, ManagedFile] = {}
    for item in files:
        current = newest_by_directory.get(item.directory)
        if current is None or (item.modified, item.relative) > (current.modified, current.relative):
            newest_by_directory[item.directory] = item
    protected = {item.path for item in newest_by_directory.values()}
    active_paths = {item.path for item in files if _simulation_log_run_id(item) in active_lookup}
    skipped.extend({"path": item.relative, "reason": "active_simulation"} for item in files if item.path in active_paths)

    selected: dict[Path, Selection] = {}
    age_cutoff = generated_at - timedelta(days=keep_days)
    minimum_cutoff = generated_at - timedelta(days=min_age_days)
    effective_age_cutoff = min(age_cutoff, minimum_cutoff)
    for item in files:
        if item.path not in protected and item.path not in active_paths and item.modified < effective_age_cutoff:
            selected[item.path] = Selection(item, "older_than_keep_days")

    remaining = sum(item.size for item in files if item.path not in selected)
    if remaining > max_total_bytes:
        for item in files:
            if remaining <= max_total_bytes:
                break
            if item.path in protected or item.path in active_paths or item.path in selected:
                continue
            if item.modified < minimum_cutoff:
                selected[item.path] = Selection(item, "size_budget")
                remaining -= item.size

    ordered = tuple(selected[item.path] for item in files if item.path in selected)
    total_bytes = sum(item.size for item in files)
    selected_bytes = sum(item.file.size for item in ordered)
    return RetentionPlan(
        root=root_path,
        generated_at=generated_at,
        keep_days=keep_days,
        min_age_days=min_age_days,
        max_total_bytes=max_total_bytes,
        files=tuple(files),
        selected=ordered,
        skipped=tuple(skipped),
        total_bytes=total_bytes,
        selected_bytes=selected_bytes,
        remaining_bytes=total_bytes - selected_bytes,
        over_budget=remaining > max_total_bytes,
        active_simulation_ids=active_ids,
    )


def _scan(root: Path) -> tuple[list[ManagedFile], list[dict]]:
    if root.is_symlink():
        return [], [{"path": ".", "reason": "root_symlink"}]
    if not root.exists():
        return [], []
    files: list[ManagedFile] = []
    skipped: list[dict] = []
    for directory, patterns in MANAGED_PATTERNS.items():
        base = root / directory
        if base.is_symlink():
            skipped.append({"path": directory, "reason": "managed_directory_symlink"})
            continue
        if not base.exists():
            continue
        if not base.is_dir():
            skipped.append({"path": directory, "reason": "not_a_directory"})
            continue
        for pattern in patterns:
            for path in sorted(base.glob(pattern)):
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    skipped.append({"path": relative, "reason": "symlink"})
                    continue
                if not path.is_file():
                    skipped.append({"path": relative, "reason": "not_a_regular_file"})
                    continue
                try:
                    stat = path.stat()
                except OSError as exc:
                    skipped.append({"path": relative, "reason": f"stat_failed: {type(exc).__name__}"})
                    continue
                files.append(
                    ManagedFile(
                        path=path,
                        relative=relative,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        modified=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                        directory=directory,
                    )
                )
    files.sort(key=lambda item: (item.modified, item.relative))
    return files, skipped


def apply_retention(plan: RetentionPlan) -> ApplyResult:
    """Delete only the still-valid files selected by ``build_retention_plan``."""
    return apply_retention_with_state(plan, active_simulation_ids=plan.active_simulation_ids)


def apply_retention_with_state(
    plan: RetentionPlan,
    *,
    active_simulation_ids: set[int] | frozenset[int] | tuple[int, ...],
) -> ApplyResult:
    """Delete planned files after re-checking current active simulation state."""
    root = Path(os.path.abspath(plan.root))
    active_lookup = {int(value) for value in active_simulation_ids}
    deleted: list[str] = []
    errors: list[dict] = []
    for selection in plan.selected:
        item = selection.file
        path = Path(item.path)
        if _simulation_log_run_id(item) in active_lookup:
            errors.append({"path": item.relative, "reason": "active_simulation"})
            continue
        failure = _apply_guard(root, item)
        if failure is not None:
            errors.append({"path": item.relative, "reason": failure})
            continue
        try:
            path.unlink()
        except OSError as exc:
            errors.append({"path": item.relative, "reason": f"unlink_failed: {type(exc).__name__}"})
            continue
        deleted.append(item.relative)
    return ApplyResult(tuple(deleted), tuple(errors))


def _simulation_log_run_id(item: ManagedFile) -> int | None:
    if item.directory != "simulations":
        return None
    match = SIMULATION_LOG_PATTERN.fullmatch(Path(item.relative).name)
    return int(match.group(1)) if match else None


def _apply_guard(root: Path, item: ManagedFile) -> str | None:
    if root.is_symlink():
        return "root_symlink"
    path = Path(item.path)
    if path.is_symlink():
        return "symlink"
    try:
        path_abs = Path(os.path.abspath(path))
        path_abs.relative_to(root)
    except ValueError:
        return "outside_root"
    if path_abs != root / item.relative:
        return "relative_path_mismatch"
    if path_abs.relative_to(root).parts[0] not in MANAGED_PATTERNS:
        return "outside_managed_directories"
    if (root / path_abs.relative_to(root).parts[0]).is_symlink():
        return "managed_directory_symlink"
    if not path_abs.is_file():
        return "not_a_regular_file"
    stat = path_abs.stat()
    if stat.st_size != item.size or stat.st_mtime_ns != item.mtime_ns:
        return "changed_since_planning"
    return None


def format_bytes(value: int) -> str:
    if value < 1024 * 1024:
        return f"{value} B"
    if value < 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MiB"
    return f"{value / (1024 * 1024 * 1024):.1f} GiB"


def format_plan(plan: RetentionPlan, applied: ApplyResult | None = None) -> list[str]:
    lines = [
        f"managed logs: {len(plan.files)} file(s), {format_bytes(plan.total_bytes)} under {plan.root}",
        f"policy: keep {plan.keep_days}d, min age {plan.min_age_days}d, budget {format_bytes(plan.max_total_bytes)}",
        (f"retention: {len(plan.selected)} candidate(s), {format_bytes(plan.selected_bytes)}; " f"projected remaining={format_bytes(plan.remaining_bytes)}" + (" (OVER BUDGET)" if plan.over_budget else "")),
    ]
    for selection in plan.selected[:20]:
        lines.append(f"  - {selection.file.relative} ({format_bytes(selection.file.size)}, {selection.reason})")
    if len(plan.selected) > 20:
        lines.append(f"  - ... {len(plan.selected) - 20} more")
    active_protected = sum(item.get("reason") == "active_simulation" for item in plan.skipped)
    if active_protected:
        lines.append(f"protected: {active_protected} active simulation log(s)")
    if plan.skipped:
        lines.append(f"skipped: {len(plan.skipped)} protected or unsafe path(s)")
    if applied is None:
        lines.append("dry run: no files were deleted (rerun with --apply after approval)")
    else:
        lines.append(f"deleted {len(applied.deleted)} of {len(plan.selected)} planned files")
        for error in applied.errors:
            lines.append(f"  ! {error['path']}: {error['reason']}")
    return lines
