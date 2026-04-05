import threading

from autopaint.monitor import RankGate, _process_tiles


# ---------------------------------------------------------------------------
# RankGate — position computation
# ---------------------------------------------------------------------------


class TestRankGatePosition:
    def test_initial_position_is_none(self):
        gate = RankGate("tile-a")
        assert gate.position is None

    def test_position_single_tile(self):
        gate = RankGate("tile-a")
        gate.update_rankings({"tile-a": 100})
        assert gate.position == 1

    def test_position_first_place(self):
        gate = RankGate("tile-a")
        gate.update_rankings({"tile-a": 1000, "tile-b": 500, "tile-c": 300})
        assert gate.position == 1

    def test_position_third_place(self):
        gate = RankGate("tile-a")
        gate.update_rankings({"tile-x": 1000, "tile-y": 900, "tile-a": 800})
        assert gate.position == 3

    def test_position_updates_incrementally(self):
        gate = RankGate("tile-a")
        gate.update_rankings({"tile-x": 1000, "tile-y": 900, "tile-a": 800})
        assert gate.position == 3

        # tile-a gets more votes via a patch.
        gate.update_rankings({"tile-a": 1100})
        assert gate.position == 1


# ---------------------------------------------------------------------------
# RankGate — direction logic
# ---------------------------------------------------------------------------


class TestRankGateDirection:
    def _make_gate(self, rank_target=3, vote_buffer=50):
        return RankGate("tile-a", rank_target=rank_target, vote_buffer=vote_buffer)

    def test_below_target_votes_up(self):
        gate = self._make_gate()
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-z": 800,
            "tile-w": 700, "tile-a": 600,
        })
        assert gate.position == 5
        assert gate.get_direction() == "up"

    def test_at_target_big_gap_votes_up(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 800,
        })
        # gap = 900 - 800 = 100 > buffer 50 → vote up
        assert gate.position == 3
        assert gate.get_direction() == "up"

    def test_at_target_close_to_above_pauses(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 860,
        })
        # gap = 900 - 860 = 40 < buffer 50 → pause
        assert gate.position == 3
        assert not gate._event.is_set()

    def test_above_target_votes_down(self):
        gate = self._make_gate()
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 1100,
        })
        assert gate.position == 1
        assert gate.get_direction() == "down"

    def test_second_place_votes_down(self):
        gate = self._make_gate()
        gate.update_rankings({
            "tile-x": 1000, "tile-a": 950, "tile-z": 800,
        })
        assert gate.position == 2
        assert gate.get_direction() == "down"

    def test_at_exact_buffer_boundary_pauses(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 850,
        })
        # gap = 900 - 850 = 50, NOT < buffer → pause
        assert gate.position == 3
        assert not gate._event.is_set()

    def test_resume_after_gap_opens(self):
        gate = self._make_gate(vote_buffer=50)

        # Initially paused.
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 860,
        })
        assert not gate._event.is_set()

        # 2nd place gains votes, gap opens.
        gate.update_rankings({"tile-y": 950})
        # gap = 950 - 860 = 90 > buffer 50 → resume up
        assert gate._event.is_set()
        assert gate.get_direction() == "up"

    def test_safety_resume_fallback(self):
        gate = RankGate("tile-a", rank_target=3, rank_resume=5, vote_buffer=50)
        gate.update_rankings({
            "tile-1": 1000, "tile-2": 900, "tile-3": 800,
            "tile-4": 700, "tile-5": 600, "tile-a": 500,
        })
        assert gate.position == 6
        # Beyond rank_resume (5), always vote up.
        assert gate.get_direction() == "up"


# ---------------------------------------------------------------------------
# RankGate — top1 strategy
# ---------------------------------------------------------------------------


class TestRankGateTop1:
    def _make_gate(self, vote_buffer=50):
        return RankGate("tile-a", top1=True, vote_buffer=vote_buffer)

    def test_not_first_votes_up(self):
        gate = self._make_gate()
        gate.update_rankings({"tile-x": 1000, "tile-a": 500})
        assert gate.position == 2
        assert gate.get_direction() == "up"

    def test_first_small_lead_votes_up(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({"tile-a": 1000, "tile-x": 980})
        # lead = 20 < buffer 50 → keep voting
        assert gate.position == 1
        assert gate.get_direction() == "up"

    def test_first_big_lead_pauses(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({"tile-a": 1000, "tile-x": 900})
        # lead = 100 > buffer 50 → pause
        assert gate.position == 1
        assert not gate._event.is_set()

    def test_first_exact_buffer_pauses(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({"tile-a": 1050, "tile-x": 1000})
        # lead = 50, not > buffer → still voting
        assert gate.get_direction() == "up"

    def test_first_one_over_buffer_pauses(self):
        gate = self._make_gate(vote_buffer=50)
        gate.update_rankings({"tile-a": 1051, "tile-x": 1000})
        # lead = 51 > buffer 50 → pause
        assert not gate._event.is_set()

    def test_resumes_when_2nd_catches_up(self):
        gate = self._make_gate(vote_buffer=50)

        # Paused with big lead.
        gate.update_rankings({"tile-a": 1000, "tile-x": 900})
        assert not gate._event.is_set()

        # 2nd place catches up.
        gate.update_rankings({"tile-x": 960})
        # lead = 40 < buffer 50 → resume
        assert gate._event.is_set()
        assert gate.get_direction() == "up"

    def test_never_votes_down(self):
        gate = self._make_gate()
        gate.update_rankings({"tile-a": 1000, "tile-x": 500})
        # Even with huge lead, direction is None (pause) not "down".
        direction = gate._compute_direction()
        assert direction in ("up", None)


# ---------------------------------------------------------------------------
# RankGate — get_direction blocking
# ---------------------------------------------------------------------------


class TestRankGateBlocking:
    def test_get_direction_blocks_when_paused(self):
        gate = RankGate("tile-a", rank_target=3, vote_buffer=50)
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 860,
        })
        # Should be paused.
        assert not gate._event.is_set()

        result = []

        def try_get():
            result.append(gate.get_direction())

        thread = threading.Thread(target=try_get)
        thread.start()
        thread.join(timeout=0.5)

        # Thread should still be blocked.
        assert thread.is_alive()
        assert result == []

        # Unblock by opening gap.
        gate.update_rankings({"tile-y": 1000})
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert result == ["up"]


# ---------------------------------------------------------------------------
# _process_tiles
# ---------------------------------------------------------------------------


class TestProcessTiles:
    def test_snapshot_updates_gate(self):
        gate = RankGate("tile-a")
        data = {
            "tiles": [
                {"id": "tile-a", "vote_count": "500"},
                {"id": "tile-b", "vote_count": "1000"},
            ]
        }
        _process_tiles(gate, data)
        assert gate.position == 2

    def test_patch_updates_gate(self):
        gate = RankGate("tile-a")
        gate.update_rankings({"tile-a": 500, "tile-b": 1000})

        patch_data = {
            "upserts": [
                {"id": "tile-a", "vote_count": "1100"},
            ]
        }
        _process_tiles(gate, patch_data, patch=True)
        assert gate.position == 1

    def test_empty_tiles_ignored(self):
        gate = RankGate("tile-a")
        _process_tiles(gate, {"tiles": []})
        assert gate.position is None

    def test_missing_fields_skipped(self):
        gate = RankGate("tile-a")
        data = {
            "tiles": [
                {"id": "tile-a"},  # missing vote_count
                {"vote_count": "100"},  # missing id
                {"id": "tile-b", "vote_count": "200"},
            ]
        }
        _process_tiles(gate, data)
        # Only tile-b was processed, tile-a not found.
        assert gate.position is None

    def test_vote_count_parsed_as_int(self):
        gate = RankGate("tile-a")
        data = {
            "tiles": [
                {"id": "tile-a", "vote_count": "12345"},
            ]
        }
        _process_tiles(gate, data)
        assert gate._rankings["tile-a"] == 12345
