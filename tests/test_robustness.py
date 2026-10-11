"""Robustness against malformed model output (found by Monte-Carlo simulation):
blank/over-long NPC names, renames onto existing names, unusable clocks,
non-canonical dispositions, stale clock owners."""
import json

import engine as E
from conftest import make_metadata, make_npc


CFG = E.EngineConfig()


def _meta(game, **over):
    E._apply_narrator_metadata(game, make_metadata(**over), scene_present_ids=set())


def _names(game):
    return [n["name"] for n in game.npcs]


# --- NPC names ----------------------------------------------------------------

def test_blank_new_npc_names_are_skipped(game):
    before = len(game.npcs)
    _meta(game, new_npcs=[{"name": "   ", "description": "x", "disposition": "neutral"},
                          {"name": "", "description": "x", "disposition": "neutral"}])
    assert len(game.npcs) == before


def test_blank_rename_and_details_are_ignored(game):
    _meta(game, npc_renames=[{"npc_id": "npc_1", "new_name": "   "}],
          npc_details=[{"npc_id": "npc_1", "full_name": "  ", "description": None}])
    assert _names(game) == ["Mara Voss"]


def test_descriptor_check_survives_blank_name():
    assert E._is_descriptor_name("   ") is True


def test_turn_with_blank_named_npc_does_not_crash(game, ai):
    game.npcs.append(make_npc("npc_2", "   "))              # legacy/corrupt save
    ai.metadata = make_metadata(npc_renames=[{"npc_id": "npc_2", "new_name": "Ilse"}])
    E.process_turn(None, game, "x", CFG)
    assert E._find_npc(game, "npc_2")["name"] == "Ilse"


def test_overlong_names_are_capped(game):
    long_name = "Der alte Mann mit dem grauen Hut, der jeden Abend am Hafen sitzt und wartet"
    _meta(game, new_npcs=[{"name": long_name, "description": "x", "disposition": "neutral"}])
    created = game.npcs[-1]["name"]
    assert len(created) <= E.NPC_NAME_MAX_CHARS and long_name.startswith(created)
    assert E._cap_npc_name("X" * 300) == "X" * E.NPC_NAME_MAX_CHARS


def test_memory_auto_stub_skips_unusable_references(game):
    before = len(game.npcs)
    _meta(game, memory_updates=[{"npc_id": "   ", "event": "e", "emotional_weight": "neutral",
                                 "about_npc": None, "absent": None, "new_npc_name": None}])
    assert len(game.npcs) == before


# --- duplicates -----------------------------------------------------------------

def test_details_rename_onto_existing_name_absorbs_duplicate(game):
    game.npcs.append(make_npc("npc_2", "Mara"))
    game.npcs.append(make_npc("npc_3", "Mara Voss Brandt"))
    # npc_2 "Mara" gets the surname "Voss" - but "Mara Voss" already exists
    _meta(game, npc_details=[{"npc_id": "npc_2", "full_name": "Mara Voss", "description": ""}])
    assert _names(game).count("Mara Voss") == 1


def test_correction_rename_onto_existing_name_absorbs_duplicate(game):
    game.npcs.append(make_npc("npc_2", "Die Fremde"))
    E._apply_correction_ops(game, [{"op": "npc_edit", "npc_id": "npc_2",
                                    "fields": {"name": "Mara Voss"}}])
    assert [n["name"] for n in game.npcs].count("Mara Voss") == 1
    assert len(game.npcs) == 1


def test_correction_rename_ignores_blank_name(game):
    E._apply_correction_ops(game, [{"op": "npc_edit", "npc_id": "npc_1", "fields": {"name": "  "}}])
    assert _names(game) == ["Mara Voss"]


def test_absorb_never_swallows_a_deceased_namesake(game):
    game.npcs.append(make_npc("npc_2", "Ilse", status="deceased"))
    game.npcs.append(make_npc("npc_3", "Die Wirtin"))
    E._apply_correction_ops(game, [{"op": "npc_edit", "npc_id": "npc_3", "fields": {"name": "Ilse"}}])
    assert E._find_npc(game, "npc_2")["status"] == "deceased"
    assert len(game.npcs) == 3


def test_absorb_repoints_about_npc_references(game):
    game.npcs.append(make_npc("npc_2", "Die Fremde"))
    game.npcs.append(make_npc("npc_3", "Ilse"))
    game.npcs[0]["memory"].append({"scene": 2, "event": "sah Ilse", "emotional_weight": "neutral",
                                   "importance": 3, "type": "observation", "about_npc": "npc_3"})
    E._apply_correction_ops(game, [{"op": "npc_edit", "npc_id": "npc_2", "fields": {"name": "Ilse"}}])
    survivor = next(n for n in game.npcs if n["name"] == "Ilse")
    assert game.npcs[0]["memory"][-1]["about_npc"] == survivor["id"]


def test_correction_split_does_not_duplicate(game):
    game.npcs.append(make_npc("npc_2", "Ilse"))
    E._apply_correction_ops(game, [{"op": "npc_split", "npc_id": "npc_1", "split_name": "Ilse"}])
    assert _names(game).count("Ilse") == 1


def test_correction_location_is_shortened(game):
    long_loc = "Das alte Lagerhaus am Kai, wo die Schmuggler ihre Ware vor dem Zoll verstecken"
    E._apply_correction_ops(game, [{"op": "location_edit", "value": long_loc}])
    assert len(game.current_location) <= E.LOCATION_MAX_CHARS


def test_opening_npcs_are_cleaned(game):
    game.npcs = []
    E._process_game_data(game, {"npcs": [
        {"name": "Ilse", "description": "d", "disposition": "Freundlich"},
        {"name": "ilse", "description": "d", "disposition": "neutral"},
        {"name": "   ", "description": "d", "disposition": "neutral"}]})
    assert _names(game) == ["Ilse"]
    assert game.npcs[0]["disposition"] in {"hostile", "distrustful", "neutral", "friendly", "loyal"}


# --- clocks -----------------------------------------------------------------------

def test_clock_sanitizer():
    assert E._sanitize_new_clock({"name": "  "}) is None
    c = E._sanitize_new_clock({"name": "Flut", "clock_type": "Bedrohung", "segments": 0, "filled": 9})
    assert c["clock_type"] == "threat" and c["segments"] == E.CLOCK_MIN_SEGMENTS
    assert c["filled"] == c["segments"] - 1 and c["fired"] is False
    big = E._sanitize_new_clock({"name": "X", "segments": "viele", "filled": None})
    assert big["segments"] == 6 and big["filled"] == 0


def test_director_clock_never_starts_full(game):
    game.clocks = []
    E._apply_director_guidance(game, {"new_clocks": [
        {"name": "Razzia", "clock_type": "threat", "segments": 4, "filled": 10,
         "trigger_description": "t", "owner": "world"}]})
    clock = game.clocks[-1]
    assert clock["filled"] < clock["segments"] and not clock["fired"]


def test_opening_clocks_are_sanitized(game):
    game.clocks = []
    E._process_game_data(game, {"clocks": [
        {"name": "Flut", "clock_type": "Bedrohung", "segments": 0, "filled": 3,
         "trigger_description": "t", "owner": ""},
        {"name": "", "clock_type": "threat", "segments": 6, "filled": 0,
         "trigger_description": "t", "owner": "world"}]})
    assert len(game.clocks) == 1
    c = game.clocks[0]
    assert c["id"].startswith("clock_") and c["segments"] >= 2 and c["filled"] < c["segments"]
    assert c["clock_type"] == "threat" and c["owner"] == "world"


def test_load_repairs_zero_segment_clock(game):
    game.clocks.append({"id": "clock_9", "name": "Kaputt", "clock_type": "threat",
                        "segments": 0, "filled": 2, "owner": "world", "fired": False})
    E.create_user("u")
    E.save_game(game, "u", [], "slot")
    loaded, _ = E.load_game("u", "slot")
    broken = next(c for c in loaded.clocks if c["id"] == "clock_9")
    assert broken["segments"] >= 1 and broken["filled"] <= broken["segments"]


def test_clock_owner_follows_rename_live(game):
    game.npcs.append(make_npc("npc_2", "Mara"))
    game.clocks.append({"id": "clock_2", "name": "Plan", "clock_type": "scheme", "segments": 4,
                        "filled": 0, "owner": "Mara", "trigger_description": "x", "fired": False})
    game.npcs[0]["name"] = "Hafenmeisterin"                  # avoid absorbing into npc_1
    _meta(game, npc_details=[{"npc_id": "npc_2", "full_name": "Mara Kessler", "description": ""}])
    assert game.clocks[-1]["owner"] == "Mara Kessler"


def test_metadata_json_roundtrip_after_cleanup(game):
    _meta(game, new_npcs=[{"name": "Ilse (die Wirtin)", "description": "x", "disposition": "loyal"}])
    json.dumps(game.npcs)
    assert game.npcs[-1]["name"] == "Ilse" and "die Wirtin" in game.npcs[-1]["aliases"]


def test_overlong_name_reappearing_is_not_recreated(game):
    long_name = "x" * 70
    _meta(game, new_npcs=[{"name": long_name, "description": "x", "disposition": "neutral"}])
    _meta(game, new_npcs=[{"name": long_name + "yy", "description": "x", "disposition": "neutral"}])
    E._process_lore_npcs(game, [{"name": long_name + "z", "description": "x"}])
    assert len([n for n in game.npcs if n["name"].startswith("xxx")]) == 1
