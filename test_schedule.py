"""Table tests for EventBridge rate()/cron() wall-clock matching."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from schedule import expression_is_due


def utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class RateTests(unittest.TestCase):
    def test_every_1_minute(self):
        now = utc(2026, 8, 16, 12, 7)
        self.assertTrue(expression_is_due("rate(1 minute)", now))

    def test_every_5_minutes(self):
        self.assertTrue(expression_is_due("rate(5 minutes)", utc(2026, 8, 16, 12, 0)))
        self.assertTrue(expression_is_due("rate(5 minutes)", utc(2026, 8, 16, 12, 15)))
        self.assertFalse(expression_is_due("rate(5 minutes)", utc(2026, 8, 16, 12, 7)))

    def test_every_15_minutes(self):
        self.assertTrue(expression_is_due("rate(15 minutes)", utc(2026, 8, 16, 12, 45)))
        self.assertFalse(expression_is_due("rate(15 minutes)", utc(2026, 8, 16, 12, 10)))

    def test_every_1_hour(self):
        self.assertTrue(expression_is_due("rate(1 hour)", utc(2026, 8, 16, 9, 0)))
        self.assertFalse(expression_is_due("rate(1 hour)", utc(2026, 8, 16, 9, 1)))

    def test_every_1_day_rate(self):
        self.assertTrue(expression_is_due("rate(1 day)", utc(2026, 8, 16, 0, 0)))
        self.assertFalse(expression_is_due("rate(1 day)", utc(2026, 8, 16, 0, 1)))
        self.assertFalse(expression_is_due("rate(1 day)", utc(2026, 8, 16, 12, 0)))


class CronTests(unittest.TestCase):
    def test_catalog_midnight_utc(self):
        expr = "cron(0 0 * * ? *)"
        self.assertTrue(expression_is_due(expr, utc(2026, 8, 16, 0, 0)))
        self.assertFalse(expression_is_due(expr, utc(2026, 8, 16, 0, 1)))
        self.assertFalse(expression_is_due(expr, utc(2026, 8, 16, 9, 0)))

    def test_weekdays_nine_utc(self):
        expr = "cron(0 9 ? * MON-FRI *)"
        monday = utc(2026, 8, 17, 9, 0)
        saturday = utc(2026, 8, 15, 9, 0)
        self.assertEqual(monday.strftime("%a"), "Mon")
        self.assertEqual(saturday.strftime("%a"), "Sat")
        self.assertTrue(expression_is_due(expr, monday))
        self.assertFalse(expression_is_due(expr, saturday))
        self.assertFalse(expression_is_due(expr, utc(2026, 8, 17, 9, 5)))

    def test_step_minutes(self):
        expr = "cron(*/15 * * * ? *)"
        self.assertTrue(expression_is_due(expr, utc(2026, 8, 16, 3, 0)))
        self.assertTrue(expression_is_due(expr, utc(2026, 8, 16, 3, 30)))
        self.assertFalse(expression_is_due(expr, utc(2026, 8, 16, 3, 7)))

    def test_unknown_expression(self):
        self.assertFalse(expression_is_due("at(2026-08-16T12:00:00)", utc(2026, 8, 16, 12, 0)))


if __name__ == "__main__":
    unittest.main()
