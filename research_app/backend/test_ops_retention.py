"""Retention planning and ops status summaries stay safe and deterministic."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.aihf_ops as ops
import scripts.aihf_retention as retention

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)


def _write(path: Path, when: datetime, payload: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_plan_selects_stale_files_and_keeps_newest_per_directory(tmp_path: Path):
    root = tmp_path / "logs"
    stale_sim = _write(root / "simulations" / "sim-1.log", NOW - timedelta(days=40), b"a" * 10)
    newest_sim = _write(root / "simulations" / "sim-2.log", NOW - timedelta(days=20), b"b" * 20)
    stale_ops = _write(root / "ops" / "old-analysis.json", NOW - timedelta(days=45), b"c" * 30)
    newest_ops = _write(root / "ops" / "new-analysis.md", NOW - timedelta(days=2), b"d" * 40)

    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=10_000,
    )

    assert {item.file.relative for item in plan.selected} == {
        "simulations/sim-1.log",
        "ops/old-analysis.json",
    }
    assert plan.total_bytes == 100
    assert plan.selected_bytes == 40
    assert plan.remaining_bytes == 60
    assert stale_sim.exists() and newest_sim.exists() and stale_ops.exists() and newest_ops.exists()

    only_root = tmp_path / "only-stale"
    only_file = _write(only_root / "daily" / "2026-01-01.json", NOW - timedelta(days=90), b"keep")
    only_stale = retention.build_retention_plan(
        only_root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=10_000,
    )
    assert only_stale.selected == ()
    assert only_file.exists()


def test_plan_deletes_oldest_files_to_fit_budget_but_not_recent_ones(tmp_path: Path):
    root = tmp_path / "logs"
    _write(root / "simulations" / "oldest.log", NOW - timedelta(days=10), b"a" * 1000)
    _write(root / "simulations" / "middle.log", NOW - timedelta(days=9), b"b" * 1000)
    _write(root / "simulations" / "newest.log", NOW - timedelta(days=8), b"c" * 1000)

    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=2000,
    )

    assert [item.file.relative for item in plan.selected] == ["simulations/oldest.log"]
    assert plan.remaining_bytes == 2000
    assert plan.over_budget is False

    recent = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=20,
        max_total_bytes=2000,
    )
    assert recent.selected == ()
    assert recent.over_budget is True


def test_plan_respects_minimum_age_when_keep_days_is_lower(tmp_path: Path):
    root = tmp_path / "logs"
    _write(root / "simulations" / "older-recent.log", NOW - timedelta(hours=12), b"a" * 10)
    _write(root / "simulations" / "newest.log", NOW - timedelta(hours=2), b"b" * 10)

    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=0,
        min_age_days=1,
        max_total_bytes=10_000,
    )

    assert plan.selected == ()


def test_plan_skips_symlinks_and_apply_never_follows_them(tmp_path: Path):
    root = tmp_path / "logs"
    target = _write(tmp_path / "outside.log", NOW - timedelta(days=40), b"secret")
    link = root / "simulations" / "sim-link.log"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    stale = _write(root / "simulations" / "sim-old.log", NOW - timedelta(days=40), b"old")
    _write(root / "simulations" / "sim-new.log", NOW - timedelta(days=1), b"new")

    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=10_000,
    )

    assert [item.file.relative for item in plan.selected] == ["simulations/sim-old.log"]
    assert any(item["path"] == "simulations/sim-link.log" for item in plan.skipped)
    result = retention.apply_retention(plan)
    assert result.deleted == ("simulations/sim-old.log",)
    assert result.errors == ()
    assert not stale.exists()
    assert link.is_symlink()
    assert target.read_bytes() == b"secret"


def test_apply_skips_file_changed_after_planning(tmp_path: Path):
    root = tmp_path / "logs"
    stale = _write(root / "simulations" / "sim-old.log", NOW - timedelta(days=40), b"old")
    newest = _write(root / "simulations" / "sim-new.log", NOW - timedelta(days=1), b"new")
    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=10_000,
    )

    with stale.open("ab") as handle:
        handle.write(b"-changed")

    result = retention.apply_retention(plan)

    assert result.deleted == ()
    assert result.errors == ({"path": "simulations/sim-old.log", "reason": "changed_since_planning"},)
    assert stale.exists() and newest.exists()


def test_plan_skips_symlinked_managed_directory_and_apply_cannot_escape(tmp_path: Path):
    root = tmp_path / "logs"
    root.mkdir()
    outside = tmp_path / "outside"
    target = _write(outside / "sim-old.log", NOW - timedelta(days=40), b"secret")
    (root / "simulations").symlink_to(outside, target_is_directory=True)

    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=10_000,
    )

    assert plan.files == ()
    assert plan.selected == ()
    assert plan.skipped == ({"path": "simulations", "reason": "managed_directory_symlink"},)
    result = retention.apply_retention(plan)
    assert result.deleted == ()
    assert result.errors == ()
    assert target.read_bytes() == b"secret"


def test_plan_rejects_symlinked_root_and_apply_cannot_escape(tmp_path: Path):
    external = tmp_path / "external"
    target = _write(external / "simulations" / "sim-old.log", NOW - timedelta(days=40), b"secret")
    root = tmp_path / "logs"
    root.symlink_to(external, target_is_directory=True)

    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=10_000,
    )

    assert plan.files == ()
    assert plan.selected == ()
    assert plan.skipped == ({"path": ".", "reason": "root_symlink"},)
    result = retention.apply_retention(plan)
    assert result.deleted == ()
    assert result.errors == ()
    assert target.read_bytes() == b"secret"


def test_cmd_retention_is_dry_run_by_default_and_apply_removes_planned_file(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "logs"
    stale = _write(root / "simulations" / "sim-old.log", NOW - timedelta(days=40), b"old")
    newest = _write(root / "simulations" / "sim-new.log", NOW - timedelta(days=1), b"new")
    plan_file = tmp_path / "approved-plan.json"
    monkeypatch.setattr(ops, "LOG_DIR", root)
    monkeypatch.setattr(retention, "_utcnow", lambda: NOW)

    args = SimpleNamespace(
        keep_days=30,
        min_age_days=1,
        max_total_mb=512.0,
        apply=False,
        json=False,
        plan_file=None,
    )
    assert ops.cmd_retention(args) == 0
    output = capsys.readouterr().out
    assert "dry run" in output
    assert stale.exists() and newest.exists()

    args.plan_file = plan_file
    assert ops.cmd_retention(args) == 0
    output = capsys.readouterr().out
    assert f"saved reviewed plan: {plan_file}" in output
    assert plan_file.exists()

    args.apply = True
    assert ops.cmd_retention(args) == 0
    output = capsys.readouterr().out
    assert "deleted 1 of 1 planned files" in output
    assert not stale.exists()
    assert newest.exists()


def test_apply_deletes_only_the_reviewed_plan_snapshot(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "logs"
    old_ops = _write(root / "ops" / "old.json", NOW - timedelta(days=40), b"old")
    protected_ops = _write(root / "ops" / "new.md", NOW - timedelta(days=2), b"new")
    _write(root / "simulations" / "sim-new.log", NOW - timedelta(days=1), b"new")
    plan_file = tmp_path / "approved-plan.json"
    monkeypatch.setattr(ops, "LOG_DIR", root)
    monkeypatch.setattr(retention, "_utcnow", lambda: NOW)
    args = SimpleNamespace(
        keep_days=0,
        min_age_days=1,
        max_total_mb=512.0,
        apply=False,
        json=False,
        plan_file=plan_file,
    )

    assert ops.cmd_retention(args) == 0
    saved = json.loads(plan_file.read_text(encoding="utf-8"))
    assert [item["path"] for item in saved["selected"]] == ["ops/old.json"]

    newer_ops = _write(root / "ops" / "newest.md", NOW, b"newest")
    late_stale = _write(root / "simulations" / "late-old.log", NOW - timedelta(days=40), b"late")
    capsys.readouterr()
    args.apply = True

    assert ops.cmd_retention(args) == 0
    assert not old_ops.exists()
    assert protected_ops.exists() and newer_ops.exists() and late_stale.exists()


def test_apply_requires_plan_file_and_rejects_a_different_root(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "logs"
    stale = _write(root / "simulations" / "sim-old.log", NOW - timedelta(days=40), b"old")
    plan_file = tmp_path / "approved-plan.json"
    plan = retention.build_retention_plan(root, now=NOW)
    retention.save_plan(plan, plan_file)
    monkeypatch.setattr(ops, "LOG_DIR", root)

    args = SimpleNamespace(
        keep_days=30,
        min_age_days=1,
        max_total_mb=512.0,
        apply=True,
        json=False,
        plan_file=None,
    )
    assert ops.cmd_retention(args) == 2
    assert "requires --plan-file" in capsys.readouterr().err
    assert stale.exists()

    other = tmp_path / "other-logs"
    monkeypatch.setattr(ops, "LOG_DIR", other)
    args.plan_file = plan_file
    assert ops.cmd_retention(args) == 2
    assert "does not match" in capsys.readouterr().err
    assert stale.exists()


def test_load_plan_rejects_unsafe_tampered_paths(tmp_path: Path):
    root = tmp_path / "logs"
    _write(root / "simulations" / "sim-old.log", NOW - timedelta(days=40), b"old")
    plan_file = tmp_path / "approved-plan.json"
    retention.save_plan(retention.build_retention_plan(root, now=NOW), plan_file)
    payload = json.loads(plan_file.read_text(encoding="utf-8"))
    payload["files"][0]["path"] = "simulations/../../outside.log"
    plan_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe retention plan path"):
        retention.load_plan(plan_file)


def test_status_report_includes_runtime_last_run_failure_and_retention(tmp_path: Path):
    root = tmp_path / "logs"
    _write(root / "simulations" / "sim-1.log", NOW - timedelta(days=40), b"x" * 10)
    _write(root / "simulations" / "sim-2.log", NOW - timedelta(days=2), b"x" * 5)
    _write(root / "ops" / "latest.json", NOW - timedelta(days=1), b"x" * 20)
    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=1024,
    )
    system = {
        "simulations": {"completed": 3, "failed": 1, "running": 0, "pending": 0},
        "cache_jobs": {"active": 0, "total": 2},
        "startup_recovery": {"orphaned_simulations_recovered": 0},
    }
    runs = [
        {
            "id": 9,
            "status": "failed",
            "start_date": "2026-01-02",
            "end_date": "2026-01-05",
            "error_message": "provider timeout\nretry later",
        },
        {"id": 8, "status": "completed", "start_date": "2025-12-01", "end_date": "2025-12-05"},
    ]

    lines = ops.build_status_report(system, runs, plan)
    text = "\n".join(lines)

    assert "last run: 9 failed 2026-01-02..2026-01-05" in text
    assert "simulations: completed=3 failed=1 running=0 pending=0" in text
    assert "latest failure: run 9 failed 2026-01-02..2026-01-05: provider timeout retry later" in text
    assert "cache jobs: active=0 total=2" in text
    assert "retention: 1 candidate(s), 10 B; managed=35 B across 3 file(s), within 1024 B budget" in text


def test_status_report_does_not_claim_no_failures_when_recent_window_is_clean(tmp_path: Path):
    plan = retention.build_retention_plan(tmp_path / "empty", now=NOW)
    system = {
        "simulations": {"completed": 50, "failed": 1, "running": 0, "pending": 0},
        "cache_jobs": {"active": 0, "total": 0},
        "startup_recovery": {},
    }
    runs = [{"id": 100 - index, "status": "completed", "start_date": "2026-01-02", "end_date": "2026-01-05"} for index in range(50)]

    text = "\n".join(ops.build_status_report(system, runs, plan))

    assert "latest failure: not in the recent 50 runs; see simulation history" in text
    assert "latest failure: none" not in text


def test_status_report_uses_current_budget_pressure_not_projected_remaining(tmp_path: Path):
    root = tmp_path / "logs"
    _write(root / "simulations" / "oldest.log", NOW - timedelta(days=10), b"a" * 1000)
    _write(root / "simulations" / "middle.log", NOW - timedelta(days=9), b"b" * 1000)
    _write(root / "simulations" / "newest.log", NOW - timedelta(days=8), b"c" * 1000)
    plan = retention.build_retention_plan(
        root,
        now=NOW,
        keep_days=30,
        min_age_days=1,
        max_total_bytes=2000,
    )
    assert plan.over_budget is False
    assert plan.current_over_budget is True
    system = {
        "simulations": {"completed": 1, "failed": 0, "running": 0, "pending": 0},
        "cache_jobs": {"active": 0, "total": 0},
        "startup_recovery": {},
    }

    text = "\n".join(ops.build_status_report(system, [], plan))

    assert "managed=3000 B across 3 file(s), OVER BUDGET 2000 B budget" in text
