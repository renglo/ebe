"""Local JSONL activity store — one file per UTC day."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

from activity_store import ActivityStore


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


class ActivityStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / "activity"
        self.store = ActivityStore(self.directory)
        self._now = patch("activity_store._now_utc", return_value=utc(2026, 8, 16, 18, 0, 0))
        self._now.start()
        self.addCleanup(self._now.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_list_strips_detail(self):
        self.store.append(
            {
                "event_id": "e1",
                "ts": "2026-08-16T15:00:00Z",
                "event_type": "executed",
                "schd_jobs_id": "j1",
                "portfolio": "p",
                "org": "o",
                "schd_machine_id": "machine-a",
                "detail": {"output": {"ok": True}},
            }
        )
        items = self.store.list_recent(portfolio="p", org="o", schd_machine_id="machine-a")
        self.assertEqual(len(items), 1)
        self.assertNotIn("detail", items[0])
        self.assertTrue(items[0]["has_detail"])
        full = self.store.get("e1")
        self.assertEqual(full["detail"]["output"]["ok"], True)
        self.assertTrue((self.directory / "2026-08-16.jsonl").is_file())

    def test_other_org_hidden(self):
        self.store.append(
            {
                "event_id": "e1",
                "ts": "2026-08-16T15:00:00Z",
                "portfolio": "p",
                "org": "other",
                "schd_machine_id": "machine-a",
            }
        )
        items = self.store.list_recent(portfolio="p", org="o", schd_machine_id="machine-a")
        self.assertEqual(items, [])

    def test_one_file_per_day_no_global_cap(self):
        self.store.append({"event_id": "e-old", "ts": "2026-08-15T12:00:00Z"})
        self.store.append({"event_id": "e-new", "ts": "2026-08-16T12:00:00Z"})
        self.assertTrue((self.directory / "2026-08-15.jsonl").is_file())
        self.assertTrue((self.directory / "2026-08-16.jsonl").is_file())
        items = self.store.list_recent(days=2, limit=50)
        ids = [row["event_id"] for row in items]
        self.assertEqual(ids, ["e-new", "e-old"])


if __name__ == "__main__":
    unittest.main()
