import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autopaint.store import Store


def _make_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


class TestStoreInit:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "subdir" / "test.db"
        store = _make_store(tmp_path)
        store.close()

    def test_tables_created(self, tmp_path):
        store = _make_store(tmp_path)

        # Should not raise.
        store.set_cooldown("abc", "2099-01-01T00:00:00Z")
        store.set_value("key", "val")
        store.close()


class TestSessionCooldowns:
    def test_set_and_get_cooldown(self, tmp_path):
        store = _make_store(tmp_path)
        future = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()

        store.set_cooldown("session-1", future)
        remaining = store.get_cooldown_remaining("session-1")

        assert 298 < remaining <= 300
        store.close()

    def test_expired_cooldown_returns_zero(self, tmp_path):
        store = _make_store(tmp_path)
        past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

        store.set_cooldown("session-1", past)
        assert store.get_cooldown_remaining("session-1") == 0.0
        store.close()

    def test_unknown_session_returns_zero(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_cooldown_remaining("nonexistent") == 0.0
        store.close()

    def test_clear_cooldown(self, tmp_path):
        store = _make_store(tmp_path)
        future = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()

        store.set_cooldown("session-1", future)
        store.clear_cooldown("session-1")

        assert store.get_cooldown_remaining("session-1") == 0.0
        store.close()

    def test_overwrite_cooldown(self, tmp_path):
        store = _make_store(tmp_path)
        old = (datetime.now(timezone.utc) + timedelta(seconds=100)).isoformat()
        new = (datetime.now(timezone.utc) + timedelta(seconds=500)).isoformat()

        store.set_cooldown("session-1", old)
        store.set_cooldown("session-1", new)

        remaining = store.get_cooldown_remaining("session-1")
        assert remaining > 400
        store.close()

    def test_invalid_date_returns_zero(self, tmp_path):
        store = _make_store(tmp_path)
        store.set_cooldown("session-1", "not-a-date")

        assert store.get_cooldown_remaining("session-1") == 0.0
        store.close()


class TestKeyValue:
    def test_set_and_get(self, tmp_path):
        store = _make_store(tmp_path)
        store.set_value("rate", "3.14")
        assert store.get_value("rate") == "3.14"
        store.close()

    def test_default_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_value("missing") is None
        assert store.get_value("missing", "fallback") == "fallback"
        store.close()

    def test_overwrite(self, tmp_path):
        store = _make_store(tmp_path)
        store.set_value("rate", "1.0")
        store.set_value("rate", "2.0")
        assert store.get_value("rate") == "2.0"
        store.close()


class TestPersistence:
    def test_survives_reopen(self, tmp_path):
        db_path = tmp_path / "persist.db"

        store = Store(db_path)
        store.set_value("learned_rate", "4.5")
        future = (datetime.now(timezone.utc) + timedelta(seconds=200)).isoformat()
        store.set_cooldown("sess-1", future)
        store.close()

        store2 = Store(db_path)
        assert store2.get_value("learned_rate") == "4.5"
        assert store2.get_cooldown_remaining("sess-1") > 100
        store2.close()
