"""Turn snapshot: single field spec, restore paths, log truncation, classification guard."""
import copy
import dataclasses

import engine as E
from conftest import make_npc, state_fingerprint


# Every GameState field must be classified: either restored from the turn snapshot
# or explicitly NOT turn-mutable. Adding a field to GameState without deciding
# where it belongs makes this test fail — that is the point.
NOT_TURN_MUTABLE = {
    # identity / setup
    "player_name", "character_concept", "setting_genre", "setting_tone",
    "setting_archetype", "setting_description", "edge", "heart", "iron", "shadow",
    "wits", "player_wishes", "content_lines", "backstory",
    # campaign-level (changed only by chapter/epilogue flows)
    "campaign_history", "chapter_number", "epilogue_text", "version_history",
    # handled specially: log tails / blueprint sub-keys / the snapshot itself
    "session_log", "narration_history", "story_blueprint", "last_turn_snapshot",
}


def test_every_gamestate_field_is_classified():
    fields = {f.name for f in dataclasses.fields(E.GameState)}
    in_spec = set(E._SNAPSHOT_SCALAR_FIELDS) | set(E._SNAPSHOT_DEEP_FIELDS)
    unclassified = fields - in_spec - NOT_TURN_MUTABLE
    assert not unclassified, f"Classify new GameState fields: {sorted(unclassified)}"
    assert not (in_spec & NOT_TURN_MUTABLE)


def test_snapshot_contains_spec_and_persisted_key_names(game):
    snap = E._build_turn_snapshot(game)
    for f in E._SNAPSHOT_SCALAR_FIELDS + E._SNAPSHOT_DEEP_FIELDS:
        assert f in snap
    # Key names are persisted in saves — must never change
    for k in ("bp_revealed", "bp_triggered_transitions", "bp_story_complete",
              "bp_triggered_director_phases", "session_log_tail",
              "narration_history_tail", "player_input", "brain", "roll", "narration"):
        assert k in snap


def test_snapshot_is_deep_copy(game):
    snap = E._build_turn_snapshot(game)
    game.npcs[0]["bond"] = 3
    game.clocks[0]["filled"] = 5
    assert snap["npcs"][0]["bond"] == 0
    assert snap["clocks"][0]["filled"] == 1


def test_restore_roundtrip_restores_all_turn_fields(game):
    before = state_fingerprint(game)
    snap = E._build_turn_snapshot(game)
    # Mutate everything a turn could touch
    game.health = 1; game.spirit = 2; game.supply = 0; game.momentum = -3
    game.scene_count += 1; game.chaos_factor = 9; game.crisis_mode = True
    game.current_location = "Anderswo"; game.time_of_day = "night"
    game.time_unchanged_scenes = 7
    game.npcs.append(make_npc("npc_2", "Neu"))
    game.clocks[0]["filled"] = 6
    game.director_guidance = {"narrator_guidance": "x"}
    game.scene_intensity_history.append("action")
    game.location_history.append("Die Taverne")
    game.story_blueprint["revealed"] = ["r1"]
    game.story_blueprint["story_complete"] = True
    game.story_blueprint["triggered_director_phases"] = ["climax"]
    game.session_log.append({"scene": 4, "summary": "neu"})
    game.narration_history.append({"scene": 4, "narration": "neu"})

    E._restore_snapshot(game, snap, logs=True)
    # last_turn_snapshot is not part of the restore
    assert state_fingerprint(game) == before


def test_restore_without_logs_keeps_turn_entries(game):
    snap = E._build_turn_snapshot(game)
    game.session_log.append({"scene": 4, "summary": "neu"})
    E._restore_snapshot(game, snap, logs=False)
    assert game.session_log[-1]["summary"] == "neu"


def test_restore_tolerates_old_snapshot_without_new_keys(game):
    snap = E._build_turn_snapshot(game)
    for k in ("time_unchanged_scenes", "bp_triggered_director_phases"):
        snap.pop(k)
    game.time_unchanged_scenes = 4
    E._restore_snapshot(game, snap, logs=False)
    assert game.time_unchanged_scenes == 4  # untouched, no KeyError


def test_truncate_log_first_turn_empty_before():
    entries = [{"scene": 1}]
    E._truncate_log_to_tail(entries, None)
    assert entries == []


def test_truncate_log_normal():
    tail = {"scene": 3}
    entries = [{"scene": 2}, copy.deepcopy(tail), {"scene": 4}]
    E._truncate_log_to_tail(entries, tail)
    assert entries == [{"scene": 2}, {"scene": 3}]


def test_truncate_log_at_cap_tail_trimmed_away_drops_only_turn_entry():
    # List was at MAX_SESSION_LOG and got trimmed; tail no longer findable
    entries = [{"scene": i} for i in range(10, 60)]
    E._truncate_log_to_tail(entries, {"scene": 999})
    assert len(entries) == 49 and entries[-1] == {"scene": 58}


def test_reapply_turn_structure(game):
    bg = make_npc("npc_2", "Jorin", status="background")
    game.npcs.append(bg)
    game.chaos_factor = 6
    brain = {"target_npc": "npc_2", "location_change": "Der Hafen",
             "time_progression": "moderate"}
    E._reapply_turn_structure(game, brain, chaos_interrupt="npc_action")
    assert game.scene_count == 4
    assert bg["status"] == "active"
    assert game.current_location == "Der Hafen"
    assert game.time_of_day == "late_evening"
    assert game.chaos_factor == 5


def test_rollback_on_error_restores_same_object(game):
    before = state_fingerprint(game)
    npcs_ref = game
    try:
        with E._rollback_on_error(game, "Test"):
            game.health = 0
            game.npcs.clear()
            raise ValueError("boom")
    except ValueError:
        pass
    assert game is npcs_ref
    assert state_fingerprint(game) == before


def test_rollback_on_error_no_exception_keeps_changes(game):
    with E._rollback_on_error(game, "Test"):
        game.health = 2
    assert game.health == 2
