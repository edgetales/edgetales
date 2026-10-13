"""Co-GM cockpit: a new character designed by the Co-GM. The profile waits in the
signal until the Narrator introduces the character by name; only then does it
become an ordinary NPC (the player never sees where it came from)."""
import pytest

import engine as E
from conftest import make_brain, make_npc, roll


CFG = E.EngineConfig()


@pytest.fixture
def prompts(ai, monkeypatch):
    seen = []

    def fake_narrator(client, prompt, game, config=None):
        seen.append(prompt)
        return ai.call_narrator(client, prompt, game, config)
    monkeypatch.setattr(E, "call_narrator", fake_narrator)
    return seen


def _odette(game, mode="fit", **kw):
    args = dict(name="Madame Odette", description="Wahrsagerin aus Soho mit Glasperlenschleier",
                agenda="Will das Register von St. Giles stehlen",
                instinct="lacht schrill, wenn sie lügt",
                secret="Sie ist Pemberton-Crakes Stalkerin",
                disposition="friendly", mode=mode)
    args.update(kw)
    return E.coop_add_new_npc(game, **args)


def _names(game):
    return [n["name"] for n in game.npcs]


# --- validation -----------------------------------------------------------------

@pytest.mark.parametrize("kw,err", [
    ({"name": ""}, "name_missing"),
    ({"name": " x "}, "name_missing"),
    ({"description": "  "}, "desc_missing"),
    ({"name": "Mara Voss"}, "name_taken"),          # existing NPC
    ({"name": "Elin"}, "name_taken"),               # the player character
    ({"mode": "later"}, "invalid"),
])
def test_validation(game, kw, err):
    sig, e = _odette(game, **kw)
    assert sig is None and e == err
    assert game.coop.get("signals", []) == []


def test_alias_and_pending_names_are_taken(game):
    game.npcs[0]["aliases"] = ["Die Hafenmeisterin"]
    assert _odette(game, name="Die Hafenmeisterin")[1] == "name_taken"
    assert _odette(game)[1] is None
    assert _odette(game)[1] == "name_taken"           # same name already waiting


def test_limit_of_waiting_characters(game):
    assert _odette(game, name="Odette")[1] is None
    assert _odette(game, name="Bartholomew Finch")[1] is None
    assert _odette(game, name="Cecily Marsh")[1] == "limit"


def test_generic_signal_api_rejects_new_npc(game):
    assert E.coop_add_signal(game, "new_npc", text="x") is None


def test_unknown_disposition_falls_back_to_neutral(game):
    sig, _ = _odette(game, disposition="loyal")
    assert sig["profile"]["disposition"] == "neutral"


# --- hidden until the entrance ----------------------------------------------------

def test_fit_character_waits_and_stays_hidden(game, ai, prompts):
    _odette(game)
    ai.narration = "Der Nebel liegt schwer über der Gasse."
    E.process_turn(None, game, "Ich warte", CFG)
    assert "A NEW character is waiting" in prompts[-1]
    assert "Will das Register von St. Giles stehlen" in prompts[-1]
    assert "never reveal it" in prompts[-1]
    assert "Madame Odette" not in _names(game)       # no NPC yet: no player-facing trace
    view = E.coop_public_view(game)
    assert view["signals"][0]["npc_name"] == "Madame Odette"
    assert E.coop_reveal(game)["items"] == []


def test_entrance_creates_npc_with_profile(game, ai, prompts):
    sig, _ = _odette(game)
    ai.narration = "Eine Frau mit Schleier tritt ein: Madame Odette, die Wahrsagerin."
    E.process_turn(None, game, "Ich warte", CFG)
    npc = next(n for n in game.npcs if n["name"] == "Madame Odette")
    assert npc["agenda"] == "Will das Register von St. Giles stehlen"
    assert npc["instinct"] == "lacht schrill, wenn sie lügt"
    assert npc["secrets"] == ["Sie ist Pemberton-Crakes Stalkerin"]
    assert npc["disposition"] == "friendly"
    assert npc["introduced"] and npc["status"] == "active" and npc["memory"]
    assert not any(s["id"] == sig["id"] for s in game.coop["signals"])
    E.process_turn(None, game, "Ich frage sie", CFG)
    assert "A NEW character" not in prompts[-1]


def test_extractor_entry_gets_the_profile_no_duplicate(game, ai):
    _odette(game)
    ai.narration = "Madame Odette lächelt dich an."
    ai.metadata["new_npcs"] = [{"name": "Madame Odette", "description": "Eine Fremde",
                                "disposition": "distrustful"}]
    E.process_turn(None, game, "Ich warte", CFG)
    odettes = [n for n in game.npcs if n["name"] == "Madame Odette"]
    assert len(odettes) == 1
    assert odettes[0]["description"].startswith("Wahrsagerin")
    assert odettes[0]["disposition"] == "friendly"
    assert odettes[0]["agenda"]


def test_name_check_respects_word_boundaries(game, ai):
    _odette(game, name="Bo", description="Ein Hafenjunge")
    ai.narration = "Der Boden knarrt unter deinen Stiefeln."
    E.process_turn(None, game, "Ich warte", CFG)
    assert "Bo" not in _names(game)


# --- "now" mode -------------------------------------------------------------------

def test_now_uses_the_impulse_slot(game, ai, prompts):
    E.coop_add_signal(game, "cliffhanger")
    sig, _ = _odette(game, mode="now")
    assert sig["impulse"]
    assert E.coop_pending_impulse(game)["type"] == "new_npc"   # replaced the cliffhanger
    ai.narration = "Madame Odette stößt die Tür auf."
    E.process_turn(None, game, "Ich warte", CFG)
    assert "Introduce this NEW character in this scene" in prompts[-1]
    assert "Madame Odette" in _names(game)
    assert game.coop["signals"] == []


def test_now_character_that_did_not_appear_waits_as_fit(game, ai, prompts):
    sig, _ = _odette(game, mode="now")
    ai.narration = "Niemand kommt."
    E.process_turn(None, game, "Ich warte", CFG)
    back = [s for s in game.coop["signals"] if s["id"] == sig["id"]]
    assert back and not back[0]["impulse"] and back[0]["mode"] == "fit"
    assert E.coop_pending_impulse(game) is None
    E.process_turn(None, game, "Ich warte weiter", CFG)
    assert "A NEW character is waiting" in prompts[-1]


def test_waiting_character_gets_nudged(game, ai, prompts):
    _odette(game)
    ai.narration = "Stille."
    for _ in range(E.COGM_NPC_NUDGE_SCENES):
        E.process_turn(None, game, "Ich warte", CFG)
    assert "create a natural opening" not in prompts[-1]
    E.process_turn(None, game, "Ich warte", CFG)
    assert "create a natural opening for them in this scene" in prompts[-1]


def test_removing_a_waiting_character(game):
    sig, _ = _odette(game)
    assert E.coop_remove_signal(game, sig["id"])
    assert game.coop["signals"] == []


# --- ## correction / momentum burn ------------------------------------------------

def _misread(monkeypatch):
    monkeypatch.setattr(E, "call_correction_brain", lambda *a, **k: {
        "correction_source": "input_misread", "corrected_input": "Ich rede",
        "reroll_needed": False, "corrected_stat": "none", "narrator_guidance": "g",
        "director_useful": False, "state_ops": []})


def test_correction_without_entrance_puts_character_back(game, ai, monkeypatch):
    sig, _ = _odette(game)
    ai.narration = "Madame Odette tritt aus dem Nebel."
    E.process_turn(None, game, "Ich warte", CFG)
    assert "Madame Odette" in _names(game)
    _misread(monkeypatch)
    ai.brain = make_brain(move="dialog", stat="none", dialog_only=True)
    ai.narration = "Du redest mit dir selbst."
    E.process_correction(None, game, "Ich wollte reden", CFG)
    assert "Madame Odette" not in _names(game)
    assert any(s["id"] == sig["id"] for s in game.coop["signals"])


def test_correction_keeping_the_entrance_creates_one_npc(game, ai, monkeypatch):
    _odette(game)
    ai.narration = "Madame Odette tritt aus dem Nebel."
    E.process_turn(None, game, "Ich warte", CFG)
    _misread(monkeypatch)
    ai.brain = make_brain(move="dialog", stat="none", dialog_only=True)
    E.process_correction(None, game, "Ich wollte reden", CFG)
    assert _names(game).count("Madame Odette") == 1
    assert not any(s.get("type") == "new_npc" for s in game.coop["signals"])


def test_session_end_keeps_waiting_character(game):
    _odette(game)
    E.coop_end_session(game)
    assert game.coop["signals"][0]["type"] == "new_npc"


def test_new_npc_survives_save_load(game):
    _odette(game)
    E.create_user("tester")
    E.save_game(game, "tester", [], "slot")
    loaded, _ = E.load_game("tester", "slot")
    assert loaded.coop["signals"][0]["profile"]["name"] == "Madame Odette"
