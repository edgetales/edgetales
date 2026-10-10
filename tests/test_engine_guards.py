"""Engine guards: arc trimming, clock-cap rule, stat normalization, short locations,
forward-only time updates."""
import engine as E
from conftest import make_metadata


# --- arc trimming --------------------------------------------------------------

def test_trim_to_sentence_prefers_sentence_end():
    first = "Der erste Satz beschreibt die innere Lage der Figur vollständig."
    text = first + " " + "Zweiter Satz " * 40 + "endet hier."
    out = E._trim_to_sentence(text, 120)
    assert out == first


def test_trim_to_sentence_falls_back_to_word_boundary():
    text = "wort " * 100
    out = E._trim_to_sentence(text, 50)
    assert len(out) <= 50 and out.endswith("…") and "  " not in out


def test_trim_to_sentence_keeps_short_text():
    assert E._trim_to_sentence("  Kurz.  ", 300) == "Kurz."


def test_long_director_arc_is_trimmed_not_rejected(game):
    long_arc = ("Mara hat gelernt, dass jede Hilfe einen Preis hat. "
                + "Sie beobachtet den Fremden mit wachsender Faszination und Misstrauen " * 6)
    assert len(long_arc) > E.ARC_MAX_CHARS
    E._apply_director_guidance(game, {
        "narrator_guidance": "", "npc_guidance": [], "pacing": "steady", "arc_notes": "",
        "act_transition": False, "scene_summary": "", "new_clocks": [],
        "npc_reflections": [{"npc_id": "npc_1",
                             "reflection": "Mara misstraut dem Fremden, seit er ihr half.",
                             "tone": "wachsam",
                             "tone_key": "wary", "updated_arc": long_arc}]})
    arc = game.npcs[0].get("arc", "")
    assert arc and len(arc) <= E.ARC_MAX_CHARS
    assert arc.startswith("Mara hat gelernt")


# --- clock cap rule in the Director prompt ---------------------------------------

def _fill_clocks(game, n):
    game.clocks = [{"id": f"c{i}", "name": f"Uhr {i}", "clock_type": "threat", "segments": 6,
                    "filled": 1, "owner": "world", "trigger_description": "x", "fired": False}
                   for i in range(n)]


def test_director_prompt_states_cap_when_full(game):
    _fill_clocks(game, E.MAX_ACTIVE_CLOCKS)
    prompt = E.build_director_prompt(game, "Text")
    assert "CLOCK CAP REACHED" in prompt and "new_clocks MUST be an empty array" in prompt


def test_director_prompt_states_free_slots(game):
    _fill_clocks(game, E.MAX_ACTIVE_CLOCKS - 2)
    prompt = E.build_director_prompt(game, "Text")
    assert "CLOCK CAP REACHED" not in prompt
    assert "Only 2 more clock(s) fit" in prompt


# --- stat normalization ----------------------------------------------------------

KEYS = ("edge", "heart", "iron", "shadow", "wits")


def test_normalize_stats_reduces_highest_first():
    stats = {"edge": 1, "heart": 2, "iron": 1, "shadow": 2, "wits": 3}   # 9
    E._normalize_stats(stats, KEYS, 7)
    assert sum(stats.values()) == 7
    assert stats["wits"] == 2 and all(0 <= v <= 3 for v in stats.values())


def test_normalize_stats_raises_lowest_first():
    stats = {"edge": 0, "heart": 1, "iron": 1, "shadow": 1, "wits": 2}   # 5
    E._normalize_stats(stats, KEYS, 7)
    assert sum(stats.values()) == 7 and stats["edge"] >= 1
    assert all(0 <= v <= 3 for v in stats.values())


# --- short location names --------------------------------------------------------

def test_short_location_name_cuts_description():
    long = ("Colter-Sicherheitszentrum, ein privates Incident-Response-Büro in "
            "Charlottenburg — versteckt hinter fünf Proxy-Schichten")
    assert E._short_location_name(long) == "Colter-Sicherheitszentrum"


def test_short_location_name_keeps_short_names():
    assert E._short_location_name("Der Hafen") == "Der Hafen"
    assert E._short_location_name("serverraum_ost") == "serverraum ost"


def test_update_location_stores_short_label(game):
    E.update_location(game, "Rübenfeld-Sekurität Headquarters, Kreuzberg, Berlin — ein grauer Bunker")
    assert game.current_location == "Rübenfeld-Sekurität Headquarters"


# --- forward-only time ------------------------------------------------------------

def test_is_forward_time():
    assert E._is_forward_time("late_evening", "night")
    assert E._is_forward_time("deep_night", "early_morning")      # past midnight
    assert E._is_forward_time("", "morning")                      # unknown start
    assert not E._is_forward_time("deep_night", "late_evening")    # backward
    assert not E._is_forward_time("morning", "morning")


def test_backward_time_update_is_rejected(game):
    game.time_of_day = "deep_night"
    game.time_unchanged_scenes = 2
    E._apply_narrator_metadata(game, make_metadata(time_update="late_evening"))
    assert game.time_of_day == "deep_night"
    assert game.time_unchanged_scenes == 3


def test_forward_time_update_is_applied(game):
    game.time_of_day = "deep_night"
    game.time_unchanged_scenes = 4
    E._apply_narrator_metadata(game, make_metadata(time_update="early_morning"))
    assert game.time_of_day == "early_morning" and game.time_unchanged_scenes == 0
