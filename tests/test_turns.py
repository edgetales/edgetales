"""Turn pipelines with a fake AI: process_turn, momentum burn, ## correction,
chapter start — including transactional rollback on mid-pipeline failures."""
import pytest

import engine as E
from conftest import make_brain, make_metadata, make_npc, roll, state_fingerprint


CFG = E.EngineConfig()


# --- process_turn -----------------------------------------------------------

def test_action_turn_advances_scene_and_logs(game, ai):
    ai.roll = roll("STRONG_HIT", c1=2, c2=3, d1=5, d2=4)
    g, narration, r, burn, _ = E.process_turn(None, game, "Ich klettere", CFG)
    assert g.scene_count == 4
    assert r.result == "STRONG_HIT" and burn is None
    assert g.session_log[-1]["scene"] == 4
    assert g.narration_history[-1]["narration"] == narration
    assert g.last_turn_snapshot["scene_count"] == 3
    assert g.last_turn_snapshot["player_input"] == "Ich klettere"


def test_dialog_turn(game, ai):
    ai.brain = make_brain(move="dialog", stat="none", dialog_only=True)
    g, _, r, burn, _ = E.process_turn(None, game, "Hallo", CFG)
    assert r is None and burn is None
    assert g.session_log[-1]["result"] == "dialog"


@pytest.mark.parametrize("fail_on", ["brain", "narrator", "metadata"])
def test_turn_failure_rolls_back_everything(game, ai, fail_on):
    ai.roll = roll("MISS")
    ai.fail_on = fail_on
    before = state_fingerprint(game)
    with pytest.raises(RuntimeError):
        E.process_turn(None, game, "Ich klettere", CFG)
    # scene not advanced, no consequences, no snapshot overwrite, no log entry
    assert state_fingerprint(game) == before


def test_retry_after_failure_applies_consequences_once(game, ai):
    ai.roll = roll("MISS")
    ai.fail_on = "metadata"
    with pytest.raises(RuntimeError):
        E.process_turn(None, game, "Ich klettere", CFG)
    ai.fail_on = None
    E.process_turn(None, game, "Ich klettere", CFG)
    assert game.scene_count == 4
    assert game.health == 4  # risky MISS on face_danger: -1 health exactly once
    assert len(game.session_log) == 2


# --- momentum burn ----------------------------------------------------------

def _miss_with_burn(game, ai, **brain_over):
    game.momentum = 10
    ai.roll = roll("MISS", c1=9, c2=9)
    ai.brain = make_brain(**brain_over)
    g, _, r, burn, _ = E.process_turn(None, game, "Ich renne", CFG)
    assert burn and burn["new_result"] == "STRONG_HIT"
    return g, burn


def _do_burn(game, burn):
    return E.process_momentum_burn(
        None, game, burn["roll"], burn["new_result"], burn["brain"],
        player_words=burn["player_words"], config=CFG,
        pre_snapshot=burn["pre_snapshot"], chaos_interrupt=burn["chaos_interrupt"])


def test_burn_keeps_scene_location_time(game, ai):
    g, burn = _miss_with_burn(game, ai, location_change="Der Hafen",
                              time_progression="moderate")
    g, _ = _do_burn(g, burn)
    assert g.scene_count == 4
    assert g.current_location == "Der Hafen"
    assert g.time_of_day == "late_evening"
    assert g.session_log[-1]["result"] == "STRONG_HIT"
    assert g.session_log[-1]["scene"] == 4
    assert len(g.session_log) == 2
    assert g.last_turn_snapshot["roll"].result == "STRONG_HIT"
    assert g.momentum == 4  # reset to 2 + strong hit +2


def test_burn_reactivates_targeted_background_npc(game, ai):
    game.npcs.append(make_npc("npc_2", "Jorin", status="background"))
    g, burn = _miss_with_burn(game, ai, target_npc="npc_2")
    g, _ = _do_burn(g, burn)
    assert E._find_npc(g, "npc_2")["status"] == "active"


def test_burn_failure_restores_post_turn_state(game, ai):
    g, burn = _miss_with_burn(game, ai)
    before = state_fingerprint(g)
    ai.fail_on = "narrator"
    with pytest.raises(RuntimeError):
        _do_burn(g, burn)
    assert state_fingerprint(g) == before


def test_burn_after_save_load_roundtrip(game, ai):
    """pre_snapshot survives JSON persistence (RollResult reconstruction)."""
    g, burn = _miss_with_burn(game, ai)
    E.create_user("u")
    E.save_game(g, "u", [], "slot")
    loaded, _ = E.load_game("u", "slot")
    burn["pre_snapshot"] = loaded.last_turn_snapshot
    loaded, _ = _do_burn(loaded, burn)
    assert loaded.scene_count == 4


# --- ## correction ----------------------------------------------------------

def _patch_correction(monkeypatch, analysis):
    monkeypatch.setattr(E, "call_correction_brain", lambda *a, **k: dict(analysis))


def test_input_misread_replaces_turn(game, ai, monkeypatch):
    ai.roll = roll("MISS")
    E.process_turn(None, game, "Ich greife an", CFG)
    assert game.scene_count == 4 and len(game.session_log) == 2
    _patch_correction(monkeypatch, {
        "correction_source": "input_misread", "corrected_input": "Ich rede",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "reden statt kämpfen", "director_useful": False,
        "state_ops": []})
    ai.brain = make_brain(move="dialog", stat="none", dialog_only=True)
    g, _, _ = E.process_correction(None, game, "Ich wollte reden", CFG)
    assert g.scene_count == 4
    assert len(g.session_log) == 2
    assert g.session_log[-1]["result"] == "dialog"
    assert g.health == 5  # MISS consequence undone


def test_input_misread_on_first_turn(ai, monkeypatch):
    """Correction of the very first turn (empty log before) must not keep the old entry."""
    g = E.GameState(player_name="Elin", scene_count=1, current_location="Hof")
    ai.roll = roll("MISS")
    E.process_turn(None, g, "x", CFG)
    assert len(g.session_log) == 1
    _patch_correction(monkeypatch, {
        "correction_source": "input_misread", "corrected_input": "y",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "g", "director_useful": False, "state_ops": []})
    ai.brain = make_brain(move="dialog", stat="none", dialog_only=True)
    E.process_correction(None, g, "y", CFG)
    assert len(g.session_log) == 1 and len(g.narration_history) == 1


def test_state_error_does_not_retick_npc_agency(game, ai, monkeypatch):
    game.scene_count = 4  # next turn = scene 5 → agency tick
    game.npcs[0]["agenda"] = "Hafen kontrollieren"
    game.clocks.append({"id": "clock_2", "name": "Plan", "clock_type": "scheme",
                        "segments": 6, "filled": 0, "owner": "Mara Voss",
                        "trigger_description": "x", "fired": False})
    ai.roll = roll("STRONG_HIT", c1=1, c2=2, d1=6, d2=6)
    E.process_turn(None, game, "x", CFG)
    assert game.clocks[-1]["filled"] == 1
    _patch_correction(monkeypatch, {
        "correction_source": "state_error", "corrected_input": "",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "g", "director_useful": False, "state_ops": []})
    E.process_correction(None, game, "falscher Ort", CFG)
    assert game.clocks[-1]["filled"] == 1


def test_correction_failure_rolls_back(game, ai, monkeypatch):
    ai.roll = roll("MISS")
    E.process_turn(None, game, "x", CFG)
    before = state_fingerprint(game)
    _patch_correction(monkeypatch, {
        "correction_source": "input_misread", "corrected_input": "y",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "g", "director_useful": False, "state_ops": []})
    ai.fail_on = "narrator"
    with pytest.raises(RuntimeError):
        E.process_correction(None, game, "y", CFG)
    assert state_fingerprint(game) == before


# --- chapter start ----------------------------------------------------------

def _patch_chapter(monkeypatch, fail=False):
    monkeypatch.setattr(E, "call_chapter_summary", lambda *a, **k: {
        "title": "Kapitel", "summary": "s", "unresolved_threads": [],
        "character_growth": "", "npc_evolutions": [], "thematic_question": "",
        "post_story_location": ""})
    monkeypatch.setattr(E, "call_story_architect", lambda *a, **k: {})

    def opening(*a, **k):
        if fail:
            raise RuntimeError("opening failed")
        return {"npcs": [], "clocks": [], "location": "Neuer Ort",
                "scene_context": "Neubeginn", "time_of_day": "morning",
                "deceased_npcs": []}
    monkeypatch.setattr(E, "call_opening_metadata", opening)


def test_new_chapter_rebases_memories_and_clears_snapshot(game, ai, monkeypatch):
    ai.roll = roll("MISS")
    game.scene_count = 20
    E.process_turn(None, game, "x", CFG)
    assert game.last_turn_snapshot is not None
    _patch_chapter(monkeypatch)
    g, _ = E.start_new_chapter(None, game, CFG, "u")
    assert g.chapter_number == 2
    assert g.last_turn_snapshot is None
    for npc in g.npcs:
        assert npc["last_memory_scene"] == 0
        assert all(m["scene"] == 0 for m in npc["memory"])


def test_new_chapter_failure_rolls_back(game, ai, monkeypatch):
    _patch_chapter(monkeypatch, fail=True)
    before = state_fingerprint(game)
    with pytest.raises(RuntimeError):
        E.start_new_chapter(None, game, CFG, "u")
    assert game.chapter_number == 1
    assert state_fingerprint(game) == before


# --- NEW-reference memory updates (ID-enum schema path) ----------------------

def test_new_npc_reference_gets_memory(game, ai):
    ai.metadata = make_metadata(
        new_npcs=[{"name": "Kapitän Brask", "description": "Seemann",
                   "disposition": "neutral"}],
        memory_updates=[{"npc_id": "NEW", "new_npc_name": "Kapitän Brask",
                         "event": "Brask mustert den Fremden", "emotional_weight": "wary",
                         "about_npc": None, "absent": False},
                        {"npc_id": "NEW", "new_npc_name": None, "event": "verloren",
                         "emotional_weight": "neutral", "about_npc": None, "absent": False}])
    ai.roll = roll("STRONG_HIT", c1=1, c2=2, d1=6, d2=6)
    g, *_ = E.process_turn(None, game, "x", CFG)
    brask = E._find_npc(g, "Kapitän Brask")
    assert brask is not None
    assert any("mustert" in m["event"] for m in brask["memory"])
    assert not any(m.get("event") == "verloren" for n in g.npcs for m in n["memory"])


def test_burn_keeps_once_only_director_mark(game, ai):
    # Scene 4 lies inside act 0's trigger-due window → act_due fires once per act.
    game.momentum = 10
    ai.roll = roll("WEAK_HIT", c1=9, c2=3)
    ai.brain = make_brain()
    g, _, r, burn, dctx = E.process_turn(None, game, "Ich renne", CFG)
    assert dctx and g.session_log[-1]["director_trigger"] == "act_due:act_0"
    assert burn and burn["new_result"] == "STRONG_HIT"
    g, _ = _do_burn(g, burn)
    assert g.story_blueprint["triggered_director_phases"] == ["due:act_0"]
    assert E._should_call_director(g, roll_result="STRONG_HIT") != "act_due:act_0"


def _patch_chapter_with(monkeypatch, opening_npcs, post_location=""):
    monkeypatch.setattr(E, "call_chapter_summary", lambda *a, **k: {
        "title": "Kapitel", "summary": "s", "unresolved_threads": [],
        "character_growth": "", "npc_evolutions": [], "thematic_question": "",
        "post_story_location": post_location})
    monkeypatch.setattr(E, "call_story_architect", lambda *a, **k: {})
    monkeypatch.setattr(E, "call_opening_metadata", lambda *a, **k: {
        "npcs": [dict(n) for n in opening_npcs], "clocks": [], "location": "",
        "scene_context": "Neubeginn", "time_of_day": "morning", "deceased_npcs": []})


def test_new_chapter_same_name_npc_keeps_history(game, ai, monkeypatch):
    mara = game.npcs[0]
    mara.update(bond=3, instinct="wird still und präzise", arc="Sie misstraut allen.",
                agenda="den Hafen schützen")
    mara["memory"] = [{"scene": 2, "event": "Mara rettet Elin", "importance": 8,
                       "emotional_weight": "grateful", "type": "observation"}]
    _patch_chapter_with(monkeypatch, [{"name": mara["name"], "description": "neu",
                                       "agenda": "", "instinct": "ruhig", "secrets": [],
                                       "disposition": "friendly"}])
    g, _ = E.start_new_chapter(None, game, CFG, "u")
    same = [n for n in g.npcs if n["name"] == "Mara Voss"]
    assert len(same) == 1
    m = same[0]
    assert m["bond"] == 3 and m["instinct"] == "wird still und präzise"
    assert m["arc"] == "Sie misstraut allen." and m["agenda"] == "den Hafen schützen"
    assert any(x["event"] == "Mara rettet Elin" for x in m["memory"])


def test_new_chapter_post_story_location_is_shortened(game, ai, monkeypatch):
    long_loc = ("Die alte Leuchtturmwärterhütte am Nordkap, ein windschiefer Bau aus "
                "Treibholz und Teerpappe hoch über der Brandung")
    _patch_chapter_with(monkeypatch, [], post_location=long_loc)
    g, _ = E.start_new_chapter(None, game, CFG, "u")
    assert len(g.current_location) <= E.LOCATION_MAX_CHARS
    assert g.current_location.startswith("Die alte Leuchtturmwärterhütte")


# --- clock events reach the Narrator ----------------------------------------------

def _capture_prompts(monkeypatch, ai):
    prompts = []
    def narrator(client, prompt, game, config=None):
        prompts.append(prompt)
        return ai.narration
    monkeypatch.setattr(E, "call_narrator", narrator)
    return prompts


def _fill_world_clock(game):
    """Stand-in for an autonomous tick that fills the world clock this scene."""
    events = []
    for c in game.clocks:
        if c.get("owner") in ("", "world") and not c.get("fired"):
            c["filled"] = c["segments"]; c["fired"] = True
            c["fired_at_scene"] = game.scene_count
            events.append({"clock": c["name"], "trigger": c.get("trigger_description", ""),
                           "autonomous": True, "triggered": True})
    return events


def test_autonomous_clock_fill_reaches_narrator_in_action(game, ai, monkeypatch):
    prompts = _capture_prompts(monkeypatch, ai)
    monkeypatch.setattr(E, "_tick_autonomous_clocks", _fill_world_clock)
    ai.roll = roll("STRONG_HIT", c1=1, c2=2, d1=6, d2=6)
    E.process_turn(None, game, "x", CFG)
    assert '<clock_fired name="Sturmflut">Das Hafenviertel läuft voll' in prompts[-1]


def test_autonomous_clock_fill_reaches_narrator_in_dialog(game, ai, monkeypatch):
    prompts = _capture_prompts(monkeypatch, ai)
    monkeypatch.setattr(E, "_tick_autonomous_clocks", _fill_world_clock)
    ai.brain = make_brain(type="dialog", move="dialog", dialog_only=True, stat=None)
    E.process_turn(None, game, "Hallo Mara", CFG)
    assert '<clock_fired name="Sturmflut">' in prompts[-1]
    assert sum(1 for e in game.session_log[-1]["clock_events"] if e.get("triggered")) == 1


def test_weak_hit_clock_fill_reaches_narrator(game, ai, monkeypatch):
    prompts = _capture_prompts(monkeypatch, ai)
    game.clocks[0]["filled"] = 5                          # 5/6 → desperate WEAK_HIT fills it
    ai.brain = make_brain(position="desperate")
    ai.roll = roll("WEAK_HIT", c1=9, c2=1, d1=3, d2=3)
    E.process_turn(None, game, "x", CFG)
    assert game.clocks[0]["fired"]
    assert '<clock_fired name="Sturmflut">' in prompts[-1]


def test_dialog_npc_agency_reaches_narrator(game, ai, monkeypatch):
    prompts = _capture_prompts(monkeypatch, ai)
    game.scene_count = 4                                   # dialog scene 5 → agency scene
    game.npcs[0]["agenda"] = "Hafen kontrollieren"
    game.clocks.append({"id": "clock_2", "name": "Plan", "clock_type": "scheme",
                        "segments": 2, "filled": 1, "owner": "Mara Voss",
                        "trigger_description": "Mara übernimmt den Hafen", "fired": False})
    ai.brain = make_brain(type="dialog", move="dialog", dialog_only=True, stat=None)
    E.process_turn(None, game, "Hallo Mara", CFG)
    assert "<npc_agency>" in prompts[-1] and 'CLOCK FILLED &quot;Plan&quot;' in prompts[-1]
    assert [e["clock"] for e in game.session_log[-1]["clock_events"]] == ["Plan"]


# --- ## input_misread re-run completes the turn -----------------------------------

def test_input_misread_rerun_reapplies_agency_and_world_ticks(game, ai, monkeypatch):
    game.scene_count = 4
    game.npcs[0]["agenda"] = "Hafen kontrollieren"
    game.clocks.append({"id": "clock_2", "name": "Plan", "clock_type": "scheme",
                        "segments": 6, "filled": 0, "owner": "Mara Voss",
                        "trigger_description": "x", "fired": False})
    ai.roll = roll("STRONG_HIT", c1=1, c2=2, d1=6, d2=6)
    E.process_turn(None, game, "x", CFG)
    assert game.clocks[-1]["filled"] == 1
    ticks = []
    monkeypatch.setattr(E, "_tick_autonomous_clocks", lambda g: ticks.append(g.scene_count) or [])
    _patch_correction(monkeypatch, {
        "correction_source": "input_misread", "corrected_input": "ich rede nur",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "g", "director_useful": False, "state_ops": []})
    E.process_correction(None, game, "war nur Gerede", CFG)
    assert game.clocks[-1]["filled"] == 1                  # agency re-applied once, not lost
    assert ticks == [5]                                     # world ticks rolled for the scene


def test_input_misread_rerun_rechecks_story_completion(game, ai, monkeypatch):
    game.scene_count = 15                                   # re-run scene 16 = final range end
    ai.roll = roll("STRONG_HIT", c1=1, c2=2, d1=6, d2=6)
    E.process_turn(None, game, "x", CFG)
    assert game.story_blueprint.get("story_complete")
    _patch_correction(monkeypatch, {
        "correction_source": "input_misread", "corrected_input": "y",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "g", "director_useful": False, "state_ops": []})
    E.process_correction(None, game, "y", CFG)
    assert game.story_blueprint.get("story_complete")
