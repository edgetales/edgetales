"""Scenario sharing: opening-state capture and copying a save's start to another user."""
import json

import engine as E


CFG = E.EngineConfig()

OPENING_CHAT = [
    {"scene_marker": "Szene 1 - Die Taverne"},
    {"role": "assistant", "content": "Der Regen trommelt auf das Dach."},
]


def _opening(game):
    """Turn the shared fixture into a fresh chapter-1 opening."""
    game.scene_count = 1
    game.chapter_number = 1
    game.session_log = [{"scene": 1, "summary": "Game start", "result": "opening",
                         "consequences": [], "clock_events": [],
                         "dramatic_question": "", "chaos_interrupt": None}]
    game.narration_history = [{"scene": 1, "prompt_summary": "Opening",
                               "narration": OPENING_CHAT[1]["content"]}]
    game.last_turn_snapshot = None
    return game


def _users(*names):
    for n in names:
        E.create_user(n)


def test_first_save_captures_opening(game):
    _users("lars")
    E.save_game(_opening(game), "lars", OPENING_CHAT, "autosave")
    op = game.opening_state
    assert op and op["fields"]["scene_count"] == 1
    assert op["chat_messages"] == OPENING_CHAT
    # never nested, no turn snapshot, no live Co-GM state
    assert not set(op["fields"]) & E._OPENING_EXCLUDED_FIELDS
    info = E.get_save_info("lars", "autosave")
    assert info["has_opening"] is True


def test_opening_not_captured_mid_game(game):
    _users("lars")
    E.save_game(game, "lars", [], "slot")  # fixture: scene 3, dialog log
    assert game.opening_state is None
    assert E.get_save_info("lars", "slot")["has_opening"] is False
    assert E.copy_scenario_to_user("lars", "slot", "jana") is None


def test_opening_survives_turns_and_is_not_overwritten(game, ai):
    _users("lars")
    E.save_game(_opening(game), "lars", list(OPENING_CHAT), "autosave")
    captured = json.dumps(game.opening_state, sort_keys=True, default=str)
    E.process_turn(None, game, "Ich klettere", CFG)
    E.save_game(game, "lars", OPENING_CHAT + [{"role": "user", "content": "Ich klettere"}],
                "autosave")
    g2, _ = E.load_game("lars", "autosave")
    assert json.dumps(g2.opening_state, sort_keys=True, default=str) == captured
    assert g2.scene_count == 2


def test_copy_sends_start_state_without_inputs(game, ai):
    _users("lars", "jana")
    E.save_game(_opening(game), "lars", list(OPENING_CHAT), "autosave")
    E.process_turn(None, game, "Ich klettere", CFG)
    game.coop = {"partner": "jana", "seeds": [{"text": "x"}]}
    E.save_game(game, "lars", OPENING_CHAT + [{"role": "user", "content": "Ich klettere"},
                                              {"role": "assistant", "content": "Weiter."}],
                "autosave")

    name = E.copy_scenario_to_user("lars", "autosave", "jana")
    assert name == "Elin"
    g, chat = E.load_game("jana", name)
    assert g.player_name == "Elin"
    assert g.scene_count == 1
    assert len(g.session_log) == 1 and g.session_log[0]["result"] == "opening"
    assert g.last_turn_snapshot is None
    assert g.coop == {}
    assert g.npcs and g.npcs[0]["name"] == game.npcs[0]["name"]
    assert chat == OPENING_CHAT
    # the recipient can pass the scenario on
    assert g.opening_state and E.get_save_info("jana", name)["has_opening"]
    # the sender's save is untouched
    g_src, _ = E.load_game("lars", "autosave")
    assert g_src.scene_count == 2


def test_copy_never_overwrites_existing_slot(game):
    _users("lars", "jana")
    E.save_game(_opening(game), "lars", list(OPENING_CHAT), "autosave")
    assert E.copy_scenario_to_user("lars", "autosave", "jana") == "Elin"
    assert E.copy_scenario_to_user("lars", "autosave", "jana") == "Elin_2"
    assert E.copy_scenario_to_user("lars", "autosave", "jana") == "Elin_3"


def test_old_save_still_at_opening_can_be_shared(game, tmp_path):
    _users("lars", "jana")
    E.save_game(_opening(game), "lars", list(OPENING_CHAT), "old")
    # simulate a save written before opening_state existed
    path = E._get_save_dir("lars") / "old.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("opening_state")
    path.write_text(json.dumps(data), encoding="utf-8")
    E._SAVE_INFO_CACHE.clear()
    assert E.get_save_info("lars", "old")["has_opening"] is True
    name = E.copy_scenario_to_user("lars", "old", "jana")
    g, chat = E.load_game("jana", name)
    assert g.scene_count == 1 and chat == OPENING_CHAT


def test_copy_rejects_unknown_or_invalid_recipient(game):
    _users("lars")
    E.save_game(_opening(game), "lars", list(OPENING_CHAT), "autosave")
    assert E.copy_scenario_to_user("lars", "autosave", "nobody") is None
    assert E.copy_scenario_to_user("lars", "autosave", "../evil") is None
    assert E.copy_scenario_to_user("lars", "missing", "lars") is None


def test_safe_save_name():
    assert E._safe_save_name("Pebby McGonagall") == "Pebby_McGonagall"
    assert E._safe_save_name("a/b\\c.d") == "a_b_c_d"
    assert E._safe_save_name("") == "scenario"
    assert E._safe_save_name("autosave") == "scenario"
    assert len(E._safe_save_name("x" * 200)) <= E.SAVE_NAME_MAX_CHARS
