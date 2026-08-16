"""Local JSONL activity log under ebe/tmp. Never Dynamo or S3.

One file per UTC day (tmp/activity/YYYY-MM-DD.jsonl). Appends never
truncate older days; a new file starts at midnight automatically.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now_utc().strftime("%Y-%m-%d")


def _parse_ts(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def compact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    row = dict(entry)
    has_detail = bool(row.pop("detail", None) is not None or row.get("has_detail"))
    row.pop("detail", None)
    if has_detail:
        row["has_detail"] = True
    return row


class ActivityStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        ts = _parse_ts(str(entry.get("ts") or "")) or _now_utc()
        day = ts.strftime("%Y-%m-%d")
        path = self._day_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def list_recent(
        self,
        *,
        days: int = 7,
        limit: int = 100,
        event_type: str = "",
        schd_jobs_id: str = "",
        portfolio: str = "",
        org: str = "",
        schd_machine_id: str = "",
    ) -> list[dict[str, Any]]:
        days = max(1, min(int(days or 7), 31))
        limit = max(1, min(int(limit or 100), 500))
        cutoff = _now_utc() - timedelta(days=days)
        event_filter = (event_type or "").strip()
        job_filter = (schd_jobs_id or "").strip()
        portfolio_filter = (portfolio or "").strip()
        org_filter = (org or "").strip()
        machine_filter = (schd_machine_id or "").strip()

        matched: list[dict[str, Any]] = []
        for entry in reversed(self._read_days(days)):
            ts = _parse_ts(str(entry.get("ts") or ""))
            if ts and ts < cutoff:
                continue
            if event_filter and str(entry.get("event_type") or "") != event_filter:
                continue
            if job_filter and str(entry.get("schd_jobs_id") or "") != job_filter:
                continue
            if portfolio_filter and str(entry.get("portfolio") or "") != portfolio_filter:
                continue
            if org_filter and str(entry.get("org") or "") != org_filter:
                continue
            if machine_filter and str(entry.get("schd_machine_id") or "") != machine_filter:
                continue
            matched.append(compact_entry(entry))
            if len(matched) >= limit:
                break
        return matched

    def get(self, event_id: str) -> dict[str, Any] | None:
        wanted = str(event_id or "").strip()
        if not wanted:
            return None
        for entry in reversed(self._read_days(31)):
            if str(entry.get("event_id") or "") == wanted:
                return entry
        return None

    def _day_path(self, day: str) -> Path:
        return self.directory / f"{day}.jsonl"

    def _day_files(self, days: int) -> list[Path]:
        if not self.directory.is_dir():
            return []
        names = []
        today = _now_utc().date()
        for offset in range(days):
            names.append((today - timedelta(days=offset)).strftime("%Y-%m-%d"))
        files = []
        for name in names:
            path = self._day_path(name)
            if path.is_file():
                files.append(path)
        return files

    def _read_days(self, days: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in reversed(self._day_files(days)):
            rows.extend(self._read_file(path))
        return rows

    def _read_file(self, path: Path) -> list[dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
