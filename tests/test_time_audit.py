"""Timing evidence is attributed without changing or estimating the live clock."""
from copy import deepcopy
import unittest

from audit_game_time import audit, utc


def event(seq, kind, stamp, **data):
    return {"seq": seq, "kind": kind, "utc": stamp, "data": data}


class TimeAuditTests(unittest.TestCase):
    def fixture(self):
        return [
            event(0, "game_started", "2026-09-08T00:00:00Z", schema=1, total_seconds=3600),
            event(1, "turn_observed", "2026-09-08T00:00:10Z", ply=1,
                  observed_utc="2026-09-07T19:00:00-05:00"),
            event(2, "query_started", "2026-09-08T00:00:11Z", ply=1),
            event(3, "query_completed", "2026-09-08T00:00:26Z", ply=1,
                  elapsed_seconds=15, error=None),
            event(4, "decision", "2026-09-08T00:00:30Z", ply=1, move="e7e5"),
            event(5, "verification", "2026-09-08T00:03:00Z", ply=1,
                  charged_through_utc="2026-09-08T00:01:00Z",
                  verified_utc="2026-09-08T00:01:05Z", charged_seconds=60,
                  excluded_verification_seconds=5),
            event(6, "turn_observed", "2026-09-08T00:03:01Z", ply=3,
                  observed_utc="2026-09-08T00:01:05Z"),
            event(7, "note", "2026-09-08T02:00:00Z", ply=3,
                  note="Paused awaiting the user; this note alone changes no charge"),
        ], {"player_side": "black", "san": ["e4", "e5", "Nf3"]}

    def test_offsets_late_settlement_and_active_pause_do_not_inflate_charge(self):
        events, game = self.fixture()
        original = deepcopy(events)
        report = audit(events, game)
        row = report["turns"][0]
        self.assertEqual(row["move"], "1... e5")
        self.assertEqual(row["charged_seconds"], 60)
        self.assertEqual(row["observation_to_record_seconds"], 10)
        self.assertEqual(row["decision_to_charge_endpoint_seconds"], 30)
        self.assertEqual(row["charge_endpoint_to_record_seconds"], 120)
        self.assertEqual(report["totals"]["query_wall_seconds"], 15)
        self.assertEqual(report["totals"]["nonquery_remainder_seconds"], 45)
        self.assertEqual(report["excluded_unsettled_turns"], [{"ply": 3, "move_number": 2}])
        self.assertEqual(events, original)

    def test_refunds_are_explicit_and_cutoff_ignores_later_settled_moves(self):
        events, game = self.fixture()
        events += [
            event(8, "verification", "2026-09-08T02:02:00Z", ply=3,
                  charged_through_utc="2026-09-08T02:01:05Z", charged_seconds=7200),
            event(9, "user_time_refund", "2026-09-08T02:03:00Z", ply=1, seconds=8),
            event(10, "user_time_refund", "2026-09-08T02:03:01Z", ply=3, seconds=7000),
        ]
        report = audit(events, game, through_move=1)
        self.assertEqual(report["totals"]["net_charged_seconds"], 52)
        self.assertEqual(report["totals"]["charged_seconds"], 60)
        self.assertEqual(report["totals"]["refunded_seconds"], 8)
        self.assertEqual(report["totals"]["turn_count"], 1)
        self.assertEqual(audit(events, game)["totals"]["net_charged_seconds"], 252)

    def test_missing_decision_is_not_fabricated_and_clock_discrepancy_is_visible(self):
        events, game = self.fixture()
        events[4]["kind"] = "note"
        events[5]["data"]["charged_seconds"] = 65
        events[3]["data"]["error"] = "query failed after spending time"
        report = audit(events, game)
        row = report["turns"][0]
        self.assertIsNone(row["decision_utc"])
        self.assertIsNone(row["decision_to_charge_endpoint_seconds"])
        self.assertEqual(row["charged_minus_active_wall_seconds"], 5)
        self.assertEqual(report["totals"]["query_errors"], 1)
        self.assertEqual(report["totals"]["query_wall_seconds"], 15)

    def test_explicit_pause_is_excluded_from_stage_intervals_without_erasing_thinking(self):
        events, game = self.fixture()
        # Pause after the decision at 00:00:40, resume five minutes later;
        # the accepted move is twenty seconds after resumption.
        extension = event(5, "user_time_extension", "2026-09-08T00:05:40Z", ply=1,
                          paused_utc="2026-09-08T00:00:40Z",
                          resumed_utc="2026-09-07T19:05:40-05:00",
                          excluded_pause_seconds=300, extra_seconds=900)
        events.insert(5, extension)
        events[6]["data"]["charged_through_utc"] = "2026-09-08T00:06:00Z"
        events[6]["utc"] = "2026-09-08T00:06:05Z"
        events = events[:7]
        for seq, item in enumerate(events):
            item["seq"] = seq
        report = audit(events, game)
        row = report["turns"][0]
        self.assertEqual(row["charged_seconds"], 60)
        self.assertEqual(row["chargeable_wall_seconds"], 60)
        self.assertEqual(row["decision_to_charge_endpoint_seconds"], 30)
        self.assertEqual(row["excluded_pause_seconds"], 300)
        self.assertEqual(row["refunded_seconds"], 0)
        self.assertEqual(report["totals"]["excluded_pause_seconds"], 300)

    def test_naive_timestamps_and_broken_sequences_fail(self):
        with self.assertRaises(ValueError):
            utc("2026-09-08T00:00:00")
        events, game = self.fixture()
        events[2]["seq"] = 90
        with self.assertRaises(ValueError):
            audit(events, game)


if __name__ == "__main__":
    unittest.main()
