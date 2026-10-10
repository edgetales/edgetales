"""Save/load, compact JSON, version history, atomic writes, save-info cache, user names."""
import json
import os

import pytest

import engine as E
from conftest import roll


def _save(game, name="slot", user="u"):
    E.create_user(user)
    return E.save_game(game, user, [{"role": "assistant", "content": "x"},
                                    {"role": "assistant", "content": "r", "recap": True}], name)


def test_roundtrip_with_snapshot_roll(game):
    game.last_turn_snapshot = E._build_turn_snapshot(game)
    game.last_turn_snapshot["roll"] = roll("WEAK_HIT", c1=3, c2=9)
    _save(game)
    g2, msgs = E.load_game("u", "slot")
    assert g2.scene_count == game.scene_count
    assert isinstance(g2.last_turn_snapshot["roll"], E.RollResult)
    assert g2.last_turn_snapshot["roll"].result == "WEAK_HIT"
    assert msgs == [{"role": "assistant", "content": "x"}]  # recap stripped
    # The in-memory snapshot must not have been converted by save_game
    assert isinstance(game.last_turn_snapshot["roll"], E.RollResult)


def test_save_is_compact_json(game):
    p = _save(game)
    text = p.read_text(encoding="utf-8")
    assert "\n" not in text and '": ' not in text
    json.loads(text)


def test_version_history_in_state_no_duplicates(game):
    _save(game)
    _save(game)
    assert game.version_history == [E.VERSION]
    g2, _ = E.load_game("u", "slot")
    assert g2.version_history == [E.VERSION]


def test_version_history_carried_over_from_old_save(game):
    game.version_history = ["0.9.90", "0.9.95"]
    _save(game)
    g2, _ = E.load_game("u", "slot")
    assert g2.version_history == ["0.9.90", "0.9.95", E.VERSION]


def test_old_save_without_version_history_is_backfilled(game):
    p = _save(game)
    data = json.loads(p.read_text(encoding="utf-8"))
    data.pop("version_history")
    data["engine_version"] = "0.9.80"
    p.write_text(json.dumps(data), encoding="utf-8")
    g2, _ = E.load_game("u", "slot")
    assert g2.version_history == ["0.9.80"]


def test_new_game_does_not_inherit_slot_history(game):
    game.version_history = ["0.9.1"]
    _save(game)
    fresh = E.GameState(player_name="Neu", scene_count=1)
    E.save_game(fresh, "u", [], "slot")
    assert fresh.version_history == [E.VERSION]


def test_corrupt_save_returns_none(game):
    p = _save(game)
    p.write_text("{kaputt", encoding="utf-8")
    assert E.load_game("u", "slot") == (None, [])


def test_atomic_write_leaves_no_temp_files(game):
    p = _save(game)
    leftovers = [f for f in os.listdir(p.parent) if f.endswith(".tmp")]
    assert leftovers == []
    assert E.list_saves("u") == ["slot"]


def test_atomic_write_keeps_old_file_on_serialization_error(game, monkeypatch):
    p = _save(game)
    old = p.read_text(encoding="utf-8")

    def boom(path, text):
        raise OSError("disk full")
    monkeypatch.setattr(E, "_atomic_write_text", boom)
    with pytest.raises(OSError):
        E.save_game(game, "u", [], "slot")
    assert p.read_text(encoding="utf-8") == old


def test_save_info_cache_invalidates_on_change(game):
    _save(game)
    assert E.get_save_info("u", "slot")["scene_count"] == 3
    game.scene_count = 9
    p = _save(game)
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 1_000_000))
    assert E.get_save_info("u", "slot")["scene_count"] == 9


def test_list_saves_with_info_sorted(game):
    _save(game, "a")
    _save(game, "b")
    names = [i["name"] for i in E.list_saves_with_info("u")]
    assert set(names) == {"a", "b"}


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "a\\b", ".hidden", "", " x",
                                 "x ", "a:b", "a*b", "x" * 65])
def test_invalid_usernames_rejected(bad):
    assert not E.is_valid_username(bad)
    assert not E.create_user(bad)


def test_delete_user_refuses_traversal():
    assert not E.delete_user("..")
    assert E.USERS_DIR.exists()


def test_valid_username_lifecycle():
    assert E.create_user("Anna Lena")
    assert not E.create_user("Anna Lena")
    assert E.delete_user("Anna Lena")


def test_chapter_archive_roundtrip():
    E.create_user("u")
    E.save_chapter_archive("u", "slot", 1, [{"role": "assistant", "content": "c"}], title="T")
    msgs, title = E.load_chapter_archive("u", "slot", 1)
    assert title == "T" and msgs[0]["content"] == "c"
    assert E.list_chapter_archives("u", "slot") == [{"chapter": 1, "title": "T"}]


def test_replace_chapter_archives_same_slot_keeps_archives():
    E.create_user("u")
    E.save_chapter_archive("u", "camp", 1, [{"role": "assistant", "content": "c1"}], title="T1")
    E.replace_chapter_archives("u", "camp", "camp")          # "Save As" under own name
    assert E.list_chapter_archives("u", "camp") == [{"chapter": 1, "title": "T1"}]


def test_replace_chapter_archives_copies_and_drops_stale():
    E.create_user("u")
    E.save_chapter_archive("u", "src", 1, [{"role": "assistant", "content": "a"}], title="A")
    E.save_chapter_archive("u", "dst", 2, [{"role": "assistant", "content": "old"}], title="Old")
    E.replace_chapter_archives("u", "src", "dst")
    assert E.list_chapter_archives("u", "dst") == [{"chapter": 1, "title": "A"}]
    assert E.list_chapter_archives("u", "src") == [{"chapter": 1, "title": "A"}]
