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

    def test_at_target_below_midpoint_votes_up(self):
        gate = self._make_gate(vote_buffer=10)
        # 2nd=900, 4th=700 → spread=200, 5%=10, midpoint=800
        # tolerance = max(10, 10) = 10, zone=790..810
        # tile-a=750 < 790 → up
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 750, "tile-w": 700,
        })
        assert gate.position == 3
        assert gate.get_direction() == "up"

    def test_at_target_above_midpoint_votes_down(self):
        gate = self._make_gate(vote_buffer=10)
        # 2nd=900, 4th=700 → midpoint=800, tolerance=10
        # tile-a=850 > 810 → down
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 850, "tile-w": 700,
        })
        assert gate.position == 3
        assert gate.get_direction() == "down"

    def test_at_target_near_midpoint_pauses(self):
        gate = self._make_gate(vote_buffer=10)
        # 2nd=900, 4th=700 → midpoint=800, tolerance=10, zone=790..810
        # tile-a=800 within zone → pause
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 800, "tile-w": 700,
        })
        assert gate.position == 3
        assert not gate._event.is_set()

    def test_percentage_tolerance_for_large_spread(self):
        gate = self._make_gate(vote_buffer=10)
        # 2nd=68000, 4th=59500 → spread=8500, 1.5%=127.5
        # tolerance = max(10, 127.5) = 127.5, midpoint=63750
        # zone ≈ 63622..63878
        gate.update_rankings({
            "tile-1": 70000, "tile-2": 68000, "tile-a": 63750, "tile-4": 59500,
        })
        # 63750 is inside zone → pause
        assert gate.position == 3
        assert not gate._event.is_set()

    def test_percentage_tolerance_outside_zone(self):
        gate = self._make_gate(vote_buffer=10)
        # spread=8500, tolerance≈127.5, midpoint=63750, zone≈63622..63878
        gate.update_rankings({
            "tile-1": 70000, "tile-2": 68000, "tile-a": 63500, "tile-4": 59500,
        })
        # 63500 < 63622 → up
        assert gate.position == 3
        assert gate.get_direction() == "up"

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

    def test_at_exact_tolerance_boundary_pauses(self):
        gate = self._make_gate(vote_buffer=10)
        # 2nd=900, 4th=700 → spread=200, tolerance=max(10,10)=10
        # midpoint=800, tile-a=790 = midpoint-10 → inside zone → pause
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 790, "tile-w": 700,
        })
        assert gate.position == 3
        assert not gate._event.is_set()

    def test_resume_when_midpoint_shifts(self):
        gate = self._make_gate(vote_buffer=10)

        # Initially paused at midpoint.
        # 2nd=900, 4th=700 → midpoint=800, tolerance=10
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 800, "tile-w": 700,
        })
        assert not gate._event.is_set()

        # 4th place drops to 600: midpoint=(900+600)/2=750
        # spread=300, 1.5%=4.5, tolerance=max(10,4.5)=10
        # tile-a=800 > 750+10=760 → vote down
        gate.update_rankings({"tile-w": 600})
        assert gate._event.is_set()
        assert gate.get_direction() == "down"

    def test_safety_resume_fallback(self):
        gate = RankGate("tile-a", rank_target=3, rank_resume=5, vote_buffer=10)
        gate.update_rankings({
            "tile-1": 1000, "tile-2": 900, "tile-3": 800,
            "tile-4": 700, "tile-5": 600, "tile-a": 500,
        })
        assert gate.position == 6
        # Beyond rank_resume (5), always vote up.
        assert gate.get_direction() == "up"

    def test_no_below_neighbor_falls_back_to_buffer(self):
        gate = self._make_gate(vote_buffer=10)
        # Only 2 tiles total, no 4th place neighbor.
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 800,
        })
        assert gate.position == 3
        # Falls back: above=900, our=800 < 900-10 → up
        assert gate.get_direction() == "up"

    def test_no_below_neighbor_close_to_above_pauses(self):
        gate = self._make_gate(vote_buffer=10)
        gate.update_rankings({
            "tile-x": 1000, "tile-y": 900, "tile-a": 895,
        })
        assert gate.position == 3
        # Falls back: above=900, our=895 >= 900-10 → pause
        assert not gate._event.is_set()


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
