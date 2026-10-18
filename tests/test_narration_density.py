"""Narration density: word budgets, beat priority, Director focus and per-NPC
Director notes only for NPCs that are in the scene."""
import engine as E
from conftest import make_brain, make_npc, roll


CFG = E.EngineConfig()


def _cast(game):
    game.npcs = [
        make_npc("npc_1", "Fergus Vermicelli"),
        make_npc("npc_2", "Inspektor Duff"),
        make_npc("npc_3", "Mrs. Hellebore"),
    ]
    game.director_guidance = {
        "narrator_guidance": "Mrs. Hellebore kommt die Treppe herunter. Ein Inspektor wird erwartet.",
        "npc_guidance": {
            "npc_1": "NOTE-FERGUS",
            "npc_2": "NOTE-DUFF",
            "npc_3": "NOTE-HELLEBORE",
        },
        "arc_notes": "ARC",
    }
    return game.npcs


def _dialog_brain():
    return make_brain(type="dialog", move="dialog", stat="none", dialog_only=True,
                      roll_needed=False, player_intent="Ich rede")


# --- per-NPC Director notes ----------------------------------------------------

def test_npc_notes_only_for_present_or_planned_npcs(game):
    fergus, duff, hellebore = _cast(game)
    p = E.build_dialog_prompt(game, _dialog_brain(), player_words="Hallo",
                              activated_npcs=[fergus], mentioned_npcs=[], config=CFG)
    assert "NOTE-FERGUS" in p                 # activated
    assert "NOTE-HELLEBORE" in p              # named in narrator_guidance
    assert "NOTE-DUFF" not in p               # absent; a bare title ("Inspektor") is no name
    assert "<director_guidance>" in p and "<arc_notes>ARC</arc_notes>" in p


def test_target_keeps_note_mentioned_does_not(game):
    fergus, duff, hellebore = _cast(game)
    game.director_guidance["narrator_guidance"] = "Ruhe im Keller."
    p = E.build_action_prompt(game, make_brain(target_npc="npc_2"), roll("WEAK_HIT"),
                              [], [], [], player_words="x",
                              activated_npcs=[], mentioned_npcs=[fergus], config=CFG)
    assert "NOTE-DUFF" in p                   # target
    assert "NOTE-FERGUS" not in p             # only mentioned (name-only in the prompt)
    assert "NOTE-HELLEBORE" not in p


def test_alias_in_guidance_counts(game):
    fergus, duff, hellebore = _cast(game)
    duff["aliases"] = ["der Kommissar"]
    game.director_guidance["narrator_guidance"] = "Der Kommissar platzt herein."
    p = E.build_dialog_prompt(game, _dialog_brain(), activated_npcs=[], mentioned_npcs=[],
                              config=CFG)
    assert "NOTE-DUFF" in p


def test_without_activation_data_all_notes_pass(game):
    _cast(game)
    p = E.build_dialog_prompt(game, _dialog_brain(), config=CFG)
    for note in ("NOTE-FERGUS", "NOTE-DUFF", "NOTE-HELLEBORE"):
        assert note in p


def test_turn_pipeline_drops_note_of_absent_npc(game, ai, monkeypatch):
    _cast(game)
    seen = []
    monkeypatch.setattr(E, "call_narrator", lambda c, prompt, g, config=None:
                        seen.append(prompt) or "Text.")
    ai.brain = _dialog_brain()
    E.process_turn(None, game, "Fergus, was ist hier los?", CFG)
    assert "NOTE-FERGUS" in seen[-1]
    assert "NOTE-DUFF" not in seen[-1]


def test_npc_named_in_ignores_titles_and_short_parts():
    npc = make_npc("npc_9", "Dr. Ada Lin")
    assert not E._npc_named_in(npc, "der doktor und ein dr. kommen")
    assert not E._npc_named_in(npc, "linoleum")
    assert E._npc_named_in(npc, "dr. ada lin wartet")


# --- word budgets and priority -------------------------------------------------

def test_tasks_use_word_budgets_not_paragraphs(game):
    _cast(game)
    lo, hi = E.NARRATION_WORDS["dialog"]
    p = E.build_dialog_prompt(game, _dialog_brain(), config=CFG)
    assert f"About {lo}-{hi} words" in p

    routine = make_brain(move="gather_information", stat="wits", roll_needed=False)
    assert E.is_routine_action(routine)
    lo, hi = E.NARRATION_WORDS["routine"]
    assert f"About {lo}-{hi} words" in E.build_dialog_prompt(game, routine, config=CFG)

    lo, hi = E.NARRATION_WORDS["action"]
    p = E.build_action_prompt(game, make_brain(), roll("MISS"), [], [], [], config=CFG)
    assert f"About {lo}-{hi} words" in p
    assert "paragraphs of immersive narration" not in p

    lo, hi = E.NARRATION_WORDS["opening"]
    assert f"About {lo}-{hi} words" in E.build_new_game_prompt(game)
    game.chapter_number = 2
    assert f"About {lo}-{hi} words" in E.build_new_chapter_prompt(game)


def test_budgets_are_ordered():
    for kind, (lo, hi) in E.NARRATION_WORDS.items():
        assert 0 < lo < hi, kind
    assert E.NARRATION_WORDS["routine"][1] <= E.NARRATION_WORDS["action"][1]


def test_narrator_system_has_focus_rule(game):
    s = E.get_narrator_system(CFG, game)
    assert "LENGTH & FOCUS" in s
    assert "DEFERRED" in s
    assert "- 2-4 paragraphs" not in s
    assert "WORLD PERIPHERY" not in s
    assert "Never repeat a time or weather cue" in s


# --- readable prose --------------------------------------------------------------

def test_narrator_system_has_prose_style_before_rules(game):
    s = E.get_narrator_system(CFG, game)
    assert "<prose_style>" in s and s.index("<prose_style>") < s.index("<rules>")
    assert "Every detail reads as a clue" in s
    assert "at most two incidental details" in s
    assert "„Sie wird blass. Dann lächelt sie.“" in s   # German examples


def test_prose_style_examples_follow_narration_language(game):
    s = E.get_narrator_system(E.EngineConfig(narration_lang="English"), game)
    assert "She goes pale. Then she smiles." in s
    assert "Sie wird blass" not in s
    # languages without own examples fall back to English
    assert "She goes pale" in E._prose_style_block("French")


def test_atmosphere_mandates_are_softened(game):
    s = E.get_narrator_system(CFG, game)
    assert "Describe only sensory impressions" not in s
    assert "include at least one non-visual sense per scene" not in s
    assert "or deepen atmosphere" not in s
    assert "translate pressure into sensation" not in s
    assert "Every 2–3 scenes, anchor one detail" not in s


def test_long_player_speech_is_quoted_in_part(game):
    s = E.get_narrator_system(CFG, game)
    assert "LONG SPEECH" in s
    assert "shorten by leaving out, never by rewording" in s
    assert "PRESERVE EXACTLY" in s


def test_tasks_ask_for_readable_not_immersive_narration(game):
    _cast(game)
    p = E.build_dialog_prompt(game, _dialog_brain(), config=CFG)
    assert "of clear, readable narration" in p
    assert "immersive narration" not in p
    p = E.build_action_prompt(game, make_brain(), roll("STRONG_HIT"), [], [], [], config=CFG)
    assert "tastes of the surrounding darkness" not in p
    assert "sensory detail, body language, and atmosphere" not in p


def test_director_prompt_limits_guidance(game):
    p = E.build_director_prompt(game, "Eine Szene.", CFG)
    assert "FOCUS RULE" in p
    assert "at most ONE concrete new event" in p
    assert "leave absent NPCs out" in p


def test_legacy_name_keyed_note_of_activated_npc_passes(game):
    fergus, duff, hellebore = _cast(game)
    game.director_guidance["npc_guidance"] = {"Fergus Vermicelli": "NOTE-LEGACY"}
    game.director_guidance["narrator_guidance"] = "Ruhe."
    p = E.build_dialog_prompt(game, _dialog_brain(), activated_npcs=[fergus],
                              mentioned_npcs=[], config=CFG)
    assert "NOTE-LEGACY" in p
