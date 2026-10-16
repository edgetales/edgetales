"""Engine guards: arc trimming, clock-cap rule, stat normalization, short locations,
forward-only time updates."""
import engine as E
from conftest import make_metadata, make_npc


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


def test_time_auto_advances_after_long_standstill(game):
    game.time_of_day = "deep_night"
    game.time_unchanged_scenes = E.TIME_AUTO_ADVANCE_SCENES - 1
    E._apply_narrator_metadata(game, make_metadata(time_update=None))
    assert game.time_of_day == "early_morning"
    assert game.time_unchanged_scenes == 0


def test_no_auto_advance_before_threshold(game):
    game.time_of_day = "evening"
    game.time_unchanged_scenes = E.TIME_AUTO_ADVANCE_SCENES - 3
    E._apply_narrator_metadata(game, make_metadata(time_update=None))
    assert game.time_of_day == "evening"


def _guidance(**over):
    g = {"narrator_guidance": "", "npc_guidance": [], "pacing": "steady", "arc_notes": "",
         "act_transition": True, "scene_summary": "", "new_clocks": [], "npc_reflections": []}
    g.update(over)
    return g


def test_premature_act_transition_is_ignored(game):
    game.scene_count = 1
    E._apply_director_guidance(game, _guidance())
    assert not game.story_blueprint.get("triggered_transitions")


def test_act_transition_after_min_scenes_is_recorded(game):
    game.scene_count = 1 + E.ACT_MIN_SCENES
    E._apply_director_guidance(game, _guidance())
    assert game.story_blueprint["triggered_transitions"] == ["act_0"]


# --- stale location -----------------------------------------------------------------

def test_scenes_at_location_counts_and_resets_on_move(game):
    game.current_location = "Hafenkneipe"
    game.scenes_at_location = 0
    E._apply_narrator_metadata(game, make_metadata())
    E._apply_narrator_metadata(game, make_metadata())
    assert game.scenes_at_location == 2
    E._apply_narrator_metadata(game, make_metadata(location_update="Lagerhaus 7"))
    assert game.current_location == "Lagerhaus 7" and game.scenes_at_location == 0


def test_brain_move_counts_the_new_scene(game):
    game.current_location = "Hafenkneipe"
    game.scenes_at_location = 6
    E._apply_brain_location_time(game, {"location_change": "Lagerhaus 7"})
    E._apply_narrator_metadata(game, make_metadata())
    assert game.scenes_at_location == 1


def test_qualifier_variant_is_not_a_move(game):
    game.current_location = "Hafenkneipe"
    game.scenes_at_location = 3
    E._apply_narrator_metadata(game, make_metadata(location_update="Hafenkneipe in Hamburg"))
    assert game.scenes_at_location == 4


def test_location_stale_hint_in_narrator_and_director(game):
    game.current_location = "Hafenkneipe"
    game.scenes_at_location = E.LOCATION_STALE_THRESHOLD - 1
    assert "<location_stale" not in E._loc_hist(game)
    assert 'stale_scenes' not in E.build_director_prompt(game, "Text").split("<scene_history>")[0]
    game.scenes_at_location = E.LOCATION_STALE_THRESHOLD
    assert f'<location_stale scenes="{E.LOCATION_STALE_THRESHOLD}">' in E._loc_hist(game)
    assert (f'<current_location stale_scenes="{E.LOCATION_STALE_THRESHOLD}">Hafenkneipe'
            in E.build_director_prompt(game, "Text"))


# --- chaos damping ------------------------------------------------------------------

def test_strong_hit_lowers_chaos_only_with_chance(game, monkeypatch):
    game.chaos_factor = 5
    monkeypatch.setattr(E.random, "random", lambda: E.CHAOS_STRONG_HIT_DROP_CHANCE)
    E.update_chaos_factor(game, "STRONG_HIT")
    assert game.chaos_factor == 5
    monkeypatch.setattr(E.random, "random", lambda: 0.0)
    E.update_chaos_factor(game, "STRONG_HIT")
    assert game.chaos_factor == 4


def test_chaos_bounds(game, monkeypatch):
    monkeypatch.setattr(E.random, "random", lambda: 0.0)
    game.chaos_factor = 3
    E.update_chaos_factor(game, "STRONG_HIT")
    assert game.chaos_factor == 3
    game.chaos_factor = 9
    E.update_chaos_factor(game, "MISS")
    assert game.chaos_factor == 9
    E.update_chaos_factor(game, "WEAK_HIT")
    assert game.chaos_factor == 9


def test_act_transition_check_precedes_boolean_and_is_kept(game):
    props = list(E.DIRECTOR_OUTPUT_SCHEMA["properties"])
    assert props.index("act_transition_check") == props.index("act_transition") - 1
    assert "act_transition_check" in E.DIRECTOR_OUTPUT_SCHEMA["required"]
    game.scene_count = 1 + E.ACT_MIN_SCENES
    E._apply_director_guidance(game, _guidance(act_transition_check="Core event happened in scene 3."))
    assert game.director_guidance["act_transition_check"] == "Core event happened in scene 3."
    assert game.story_blueprint["triggered_transitions"] == ["act_0"]


# --- act trigger due ----------------------------------------------------------------

def test_act_trigger_due_window(game):
    game.scene_count = 6 - E.ACT_TRIGGER_DUE_SCENES - 1      # before the window
    assert E._act_trigger_due(game) is None
    game.scene_count = 6 - E.ACT_TRIGGER_DUE_SCENES          # window opens
    assert E._act_trigger_due(game) == "act_0"
    game.story_blueprint["triggered_transitions"] = ["act_0"]
    assert E._act_trigger_due(game) is None                   # already transitioned


def test_act_trigger_due_never_for_final_act(game):
    game.scene_count = 15                                      # climax act, no trigger
    assert E._act_trigger_due(game) is None


def test_act_due_director_fires_once_per_act(game):
    game.scene_count = 5                                       # odd → no interval run
    reason = E._should_call_director(game)
    assert reason == "act_due:act_0"
    E._mark_director_reason(game, reason)
    assert "due:act_0" in game.story_blueprint["triggered_director_phases"]
    # act_due never fires again; scene 5 is a delivery scene, so the check follows
    assert E._should_call_director(game) == "act_check:act_0"


# --- act trigger delivery --------------------------------------------------------

def test_act_trigger_stage_escalates_to_deliver(game):
    end = 6                                                    # act 0 range end
    game.scene_count = end - E.ACT_TRIGGER_DUE_SCENES - 1
    assert E._act_trigger_stage(game) is None
    game.scene_count = end - E.ACT_TRIGGER_DUE_SCENES
    assert E._act_trigger_stage(game) == "steer"
    for scene in range(end - E.ACT_TRIGGER_DELIVER_SCENES, end + 1):
        game.scene_count = scene
        assert E._act_trigger_stage(game) == "deliver"
    game.story_blueprint["triggered_transitions"] = ["act_0"]
    assert E._act_trigger_stage(game) is None


def test_narrator_gets_deliver_block_in_last_scenes(game):
    game.story_blueprint["acts"][0]["transition_trigger"] = "Die Schwester bringt die Pläne."
    game.scene_count = 6 - E.ACT_TRIGGER_DUE_SCENES
    steer = E._story_context_block(game)
    assert "<act_turning_point>" in steer and 'stage="deliver"' not in steer
    game.scene_count = 6
    deliver = E._story_context_block(game)
    assert '<act_turning_point stage="deliver">' in deliver
    assert "HAPPENS IN THIS SCENE" in deliver and "Die Schwester bringt die Pläne." in deliver


def test_deliver_stage_marked_in_director_prompt(game):
    game.scene_count = 6
    assert '<transition_trigger act="1" due="true" stage="deliver">' in \
        E.build_director_prompt(game, "Text")


def test_director_checks_every_delivery_scene_once(game):
    game.story_blueprint["triggered_director_phases"] = ["due:act_0"]
    game.scene_count = 5                                       # odd → no interval run
    reason = E._should_call_director(game)
    assert reason == "act_check:act_0"
    E._mark_director_reason(game, reason)
    assert "check:act_0:5" in game.story_blueprint["triggered_director_phases"]
    assert E._should_call_director(game) is None              # once per scene
    game.scene_count = 7 - 1                                   # next delivery scene (6)
    assert E._should_call_director(game) == "act_check:act_0"   # before the interval run
    game.story_blueprint["triggered_transitions"] = ["act_0"]
    game.scene_count = 5
    assert E._should_call_director(game) is None              # delivered → no more checks


# --- remote contacts and object NPCs ----------------------------------------------

def test_lore_figure_listed_in_new_npcs_becomes_active(game):
    game.npcs.append(make_npc("npc_2", "Sam Okafor", status="lore"))
    E._process_new_npcs(game, '[{"name": "Sam Okafor", "description": "Kollege am Funk",'
                              ' "disposition": "friendly"}]')
    sam = E._find_npc(game, "Sam Okafor")
    assert sam["status"] == "active"
    assert sum(1 for n in game.npcs if n["name"] == "Sam Okafor") == 1


def test_due_trigger_marked_in_director_prompt(game):
    game.scene_count = 2
    assert '<transition_trigger act="1">' in E.build_director_prompt(game, "Text")
    game.scene_count = 6 - E.ACT_TRIGGER_DUE_SCENES            # steer stage
    assert '<transition_trigger act="1" due="true">' in E.build_director_prompt(game, "Text")


def test_mark_director_reason_phase_and_others(game):
    E._mark_director_reason(game, "phase:climax")
    E._mark_director_reason(game, "interval")
    E._mark_director_reason(game, None)
    assert game.story_blueprint["triggered_director_phases"] == ["climax"]


def test_due_trigger_reaches_narrator_story_block(game):
    game.story_blueprint["acts"][0]["transition_trigger"] = "Elin findet den Schlüssel."
    game.scene_count = 2
    assert "<act_turning_point>" not in E._story_context_block(game)
    game.scene_count = 6 - E.ACT_TRIGGER_DUE_SCENES            # steer stage
    block = E._story_context_block(game)
    assert "<act_turning_point>" in block and "Elin findet den Schlüssel." in block


# --- setup brain error handling ---------------------------------------------------

class _FailingClient:
    def __init__(self, exc):
        self._exc = exc
        self.messages = self

    def create(self, **kwargs):
        raise self._exc


def test_setup_brain_reraises_api_errors(monkeypatch):
    import httpx, pytest
    monkeypatch.setattr(E, "_api_create_with_retry",
                        lambda client, **kw: client.messages.create(**kw))
    exc = E.anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    with pytest.raises(E.anthropic.APIConnectionError):
        E.call_setup_brain(_FailingClient(exc), {"genre": "dark_fantasy", "tone": "dark_gritty",
                                                 "archetype": "outsider_loner"})


def test_setup_brain_falls_back_on_unusable_output(monkeypatch):
    monkeypatch.setattr(E, "_api_create_with_retry",
                        lambda client, **kw: client.messages.create(**kw))
    setup = E.call_setup_brain(_FailingClient(ValueError("bad json")),
                               {"genre": "dark_fantasy", "tone": "dark_gritty",
                                "archetype": "outsider_loner", "player_name": "Kaelen"})
    assert setup["starting_location"] and sum(setup["stats"].values()) == E.STAT_TARGET_SUM


# --- same-scene death of a known NPC ---------------------------------------------

def test_known_npc_dying_with_memory_stays_deceased(game):
    npc = game.npcs[0]
    md = make_metadata(
        deceased_npcs=[{"npc_id": npc["id"]}],
        memory_updates=[{"npc_id": npc["id"], "event": "Mara bricht tödlich getroffen zusammen",
                         "emotional_weight": "terrified", "about_npc": None, "absent": False}])
    E._apply_narrator_metadata(game, md, scene_present_ids={npc["id"]})
    assert npc["status"] == "deceased"
    assert any("zusammen" in m["event"] for m in npc["memory"])


def test_earlier_dead_npc_with_new_memory_is_resurrected(game):
    npc = game.npcs[0]
    npc["status"] = "deceased"
    md = make_metadata(memory_updates=[{"npc_id": npc["id"], "event": "Mara steht in der Tür",
                                        "emotional_weight": "calm", "about_npc": None,
                                        "absent": False}])
    E._apply_narrator_metadata(game, md, scene_present_ids=set())
    assert npc["status"] == "active"


def test_absent_mention_does_not_confirm_death(game):
    game.npcs.append(make_npc("npc_2", "Leo Brandt"))
    leo = game.npcs[-1]
    md = make_metadata(
        deceased_npcs=[{"npc_id": "npc_2"}],
        memory_updates=[{"npc_id": "npc_2", "event": "Jorin behauptet, Leo sei tot",
                         "emotional_weight": "grief", "about_npc": None, "absent": True}])
    E._apply_narrator_metadata(game, md, scene_present_ids={game.npcs[0]["id"]})
    assert leo["status"] != "deceased"


# --- Story Architect retry ----------------------------------------------------------

def _architect_reply(n_acts):
    import json, types
    acts = [{"phase": f"p{i}", "title": "T", "goal": "g", "scene_range": [i * 5 + 1, i * 5 + 5],
             "mood": "m", "transition_trigger": "x"} for i in range(n_acts)]
    bp = {"central_conflict": "Konflikt", "antagonist_force": "", "thematic_thread": "",
          "acts": acts, "revelations": [], "possible_endings": []}
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(bp))])


def test_architect_retries_once_on_too_few_acts(game, monkeypatch):
    replies = iter([_architect_reply(1), _architect_reply(3)])
    msgs = []
    def fake(client, **kw):
        msgs.append(kw["messages"][0]["content"])
        return next(replies)
    monkeypatch.setattr(E, "_api_create_with_retry", fake)
    bp = E.call_story_architect(None, game, structure_type="3act")
    assert len(bp["acts"]) == 3 and bp["central_conflict"] == "Konflikt"
    assert len(msgs) == 2 and "CORRECTION" in msgs[1] and "CORRECTION" not in msgs[0]


def test_architect_falls_back_after_two_bad_answers(game, monkeypatch):
    calls = []
    monkeypatch.setattr(E, "_api_create_with_retry",
                        lambda client, **kw: calls.append(1) or _architect_reply(1))
    bp = E.call_story_architect(None, game, structure_type="3act")
    assert len(calls) == E.ARCHITECT_ATTEMPTS
    assert len(bp["acts"]) >= 3                    # generic fallback blueprint


def test_prompts_require_deliverable_triggers_and_live_contacts():
    import inspect
    architect = inspect.getsource(E.call_story_architect)
    assert architect.count("DELIVERABLE BY THE WORLD") == 2        # 3-act and Kishōtenketsu
    extractor = inspect.getsource(E.call_narrator_metadata)
    assert "REMOTE PARTICIPATION" in extractor and "NEVER objects, traces" in extractor
    assert "LORE FIGURES TAKING PART" in extractor


# --- NPC description completeness ------------------------------------------------

def test_description_without_final_period_is_complete():
    # Complete noun phrases without end punctuation used to be discarded as truncated.
    assert E._is_complete_description("Junger Wachtmeister mit zu tief sitzender Mütze")
    assert E._is_complete_description("Schwerfälliger Wirt mit mehligen Händen und müden Augen")
    assert E._is_complete_description("Former pilot, now a tired mechanic.")


def test_dangling_descriptions_are_rejected():
    assert not E._is_complete_description("Junger Wachtmeister mit zu tief sitzender Mütze, der")
    assert not E._is_complete_description("Bote der Polizeidirektion in Uniform mit")
    assert not E._is_complete_description("Former pilot, now a tired mechanic and")
    assert not E._is_complete_description("Fischhändler am Fenstertisch,")
    assert not E._is_complete_description("kurz")


def test_finish_description_adds_period_only_when_missing():
    assert E._finish_description("Müder Wirt") == "Müder Wirt."
    assert E._finish_description("Müder Wirt.") == "Müder Wirt."
    assert E._finish_description("Er fragt: »Wer?«") == "Er fragt: »Wer?«"
