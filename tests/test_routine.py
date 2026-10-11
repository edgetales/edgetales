"""Routine actions (Brain roll_needed=false): no dice, no consequences, no momentum,
narrated as a clean success. Combat, endure moves and desperate positions always roll."""
import pytest

import engine as E
from conftest import make_brain, roll, state_fingerprint


CFG = E.EngineConfig()


def _routine_brain(**over):
    base = dict(move="gather_information", stat="wits", roll_needed=False,
                position="controlled", player_intent="Ich sehe mich im Raum um")
    base.update(over)
    return make_brain(**base)


@pytest.fixture
def prompts(ai, monkeypatch):
    seen = []

    def narrator(client, prompt, game, config=None):
        seen.append(prompt)
        return ai.call_narrator(client, prompt, game, config)
    monkeypatch.setattr(E, "call_narrator", narrator)
    return seen


@pytest.fixture
def no_dice(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("routine action must not roll")
    monkeypatch.setattr(E, "roll_action", boom)


# --- classification -------------------------------------------------------------

@pytest.mark.parametrize("brain, routine", [
    (dict(move="face_danger", roll_needed=False, position="risky"), True),
    (dict(move="gather_information", roll_needed=False, position="controlled"), True),
    (dict(move="face_danger", roll_needed=True, position="risky"), False),
    (dict(move="face_danger", position="risky"), False),             # old snapshot: rolls
    (dict(move="face_danger", roll_needed=None, position="risky"), False),
    (dict(move="clash", roll_needed=False, position="risky"), False),
    (dict(move="strike", roll_needed=False, position="controlled"), False),
    (dict(move="endure_harm", roll_needed=False, position="risky"), False),
    (dict(move="endure_stress", roll_needed=False, position="risky"), False),
    (dict(move="face_danger", roll_needed=False, position="desperate"), False),
    (dict(move="dialog", roll_needed=False, dialog_only=True), False),
])
def test_routine_classification(brain, routine):
    assert E.is_routine_action(brain) is routine
    assert E.needs_roll(brain) is (not routine and not E.is_dialog_turn(brain))


def test_dialog_never_rolls():
    assert not E.needs_roll({"move": "dialog", "dialog_only": True, "roll_needed": True})
    assert not E.needs_roll({"move": "face_danger", "dialog_only": True})


# --- turn pipeline ------------------------------------------------------------------

def test_routine_turn_has_no_roll_and_no_consequences(game, ai, prompts, no_dice):
    ai.brain = _routine_brain()
    before = (game.health, game.spirit, game.supply, game.momentum, game.chaos_factor,
              [c["filled"] for c in game.clocks])
    g, narration, r, burn, _ = E.process_turn(None, game, "Ich sehe mich um", CFG)
    assert r is None and burn is None
    assert (g.health, g.spirit, g.supply, g.momentum, g.chaos_factor,
            [c["filled"] for c in g.clocks]) == before
    assert g.scene_count == 4
    log = g.session_log[-1]
    assert log["result"] == "routine" and log["move"] == "gather_information"
    assert log["consequences"] == []
    assert g.narration_history[-1]["prompt_summary"].startswith("Routine:")
    assert g.last_turn_snapshot.get("roll") is None
    assert '<scene type="routine"' in prompts[-1]
    assert "succeeds without a roll" in prompts[-1]


def test_dialog_prompt_is_unchanged(game, ai, prompts):
    ai.brain = make_brain(move="dialog", stat="none", dialog_only=True, roll_needed=False)
    E.process_turn(None, game, "Hallo", CFG)
    assert '<scene type="dialog"' in prompts[-1]
    assert "succeeds without a roll" not in prompts[-1]
    assert game.session_log[-1]["result"] == "dialog"


@pytest.mark.parametrize("over", [
    dict(move="clash", stat="iron"),
    dict(position="desperate"),
    dict(move="endure_harm", stat="iron"),
])
def test_brain_cannot_skip_roll_for_combat_or_desperate(game, ai, over):
    ai.brain = _routine_brain(**over)
    ai.roll = roll("MISS")
    _, _, r, _, _ = E.process_turn(None, game, "x", CFG)
    assert r is not None and r.result == "MISS"
    assert game.session_log[-1]["result"] == "MISS"


def test_routine_then_risky_turn_rolls_again(game, ai, no_dice, monkeypatch):
    ai.brain = _routine_brain()
    E.process_turn(None, game, "Ich gehe zur Tür", CFG)
    monkeypatch.setattr(E, "roll_action", ai.roll_action)
    ai.brain = make_brain(roll_needed=True)
    ai.roll = roll("WEAK_HIT")
    _, _, r, _, _ = E.process_turn(None, game, "Ich klettere", CFG)
    assert r.result == "WEAK_HIT"


def test_routine_turn_failure_rolls_back(game, ai):
    ai.brain = _routine_brain()
    ai.fail_on = "metadata"
    before = state_fingerprint(game)
    with pytest.raises(RuntimeError):
        E.process_turn(None, game, "x", CFG)
    assert state_fingerprint(game) == before


# --- ## corrections -------------------------------------------------------------------

def _patch_correction(monkeypatch, analysis):
    monkeypatch.setattr(E, "call_correction_brain", lambda *a, **k: dict(analysis))


def test_input_misread_to_routine_does_not_reroll(game, ai, prompts, monkeypatch):
    ai.roll = roll("MISS")
    E.process_turn(None, game, "Ich greife an", CFG)
    _patch_correction(monkeypatch, {
        "correction_source": "input_misread", "corrected_input": "Ich öffne die Tür",
        "reroll_needed": True, "corrected_stat": "wits",
        "narrator_guidance": "nur die Tür", "director_useful": False, "state_ops": []})
    ai.brain = _routine_brain()
    monkeypatch.setattr(E, "roll_action",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rolled")))
    g, _, _ = E.process_correction(None, game, "Ich wollte nur die Tür öffnen", CFG)
    assert g.session_log[-1]["result"] == "routine"
    assert g.health == 5                       # MISS consequence undone
    assert g.last_turn_snapshot["roll"] is None
    assert '<scene type="routine"' in prompts[-1]


def test_state_error_after_routine_keeps_routine_prompt(game, ai, prompts, monkeypatch):
    ai.brain = _routine_brain()
    E.process_turn(None, game, "Ich sehe mich um", CFG)
    _patch_correction(monkeypatch, {
        "correction_source": "state_error", "corrected_input": "",
        "reroll_needed": False, "corrected_stat": "none",
        "narrator_guidance": "anderer Raum", "director_useful": False, "state_ops": []})
    E.process_correction(None, game, "falscher Raum", CFG)
    assert '<scene type="routine"' in prompts[-1]
    assert game.session_log[-1]["result"] == "routine"


# --- persistence / schema ---------------------------------------------------------------

def test_routine_turn_survives_save_load(game, ai, no_dice):
    ai.brain = _routine_brain()
    E.process_turn(None, game, "x", CFG)
    E.create_user("u")
    E.save_game(game, "u", [], "slot")
    loaded, _ = E.load_game("u", "slot")
    assert loaded.session_log[-1]["result"] == "routine"
    assert loaded.last_turn_snapshot["brain"]["roll_needed"] is False


def test_roll_needed_is_required_in_brain_schema():
    assert "roll_needed" in E.BRAIN_OUTPUT_SCHEMA["required"]
    assert E.BRAIN_OUTPUT_SCHEMA["properties"]["roll_needed"] == {"type": "boolean"}
