"""Core mechanics: dice, consequences, momentum burn eligibility, clocks, correction ops."""
import engine as E
from conftest import make_npc, roll


def test_roll_action_outcomes(monkeypatch):
    seq = iter([5, 3, 4])  # action die, c1, c2
    monkeypatch.setattr(E.random, "randint", lambda a, b: next(seq))
    r = E._real_roll_action("iron", 2, "clash")
    assert r.action_score == 7 and r.d2 == 0 and r.result == "STRONG_HIT" and not r.match


def test_roll_action_uses_one_d6(monkeypatch):
    calls = []
    def randint(a, b):
        calls.append((a, b))
        return b
    monkeypatch.setattr(E.random, "randint", randint)
    r = E._real_roll_action("iron", 3, "clash")
    assert calls == [(1, 6), (1, 10), (1, 10)]
    assert r.action_score == 9 and r.result == "MISS" and r.match   # 6+3 vs 10|10


def test_action_dice_text_old_and_new():
    assert E.action_dice_text(4) == "4" and E.action_dice_text(4, 0) == "4"
    assert E.action_dice_text(3, 5) == "3+5"                         # pre-switch saves


def test_miss_consequences_and_clock_tick(game):
    cons, events = E.apply_consequences(game, roll("MISS"), {"position": "desperate"})
    assert game.health == 3 and game.supply == 4
    assert game.momentum == 2  # 5 - 3
    assert events and events[0]["ticks"] == 2 and game.clocks[0]["filled"] == 3


def test_game_over_when_both_tracks_zero(game):
    game.health = 1; game.spirit = 0
    E.apply_consequences(game, roll("MISS"), {"position": "risky"})
    assert game.game_over and game.crisis_mode


def test_strong_hit_social_bond_and_disposition(game):
    r = roll("STRONG_HIT", c1=1, c2=2)
    r = E.RollResult(r.d1, r.d2, r.c1, r.c2, "heart", 2, 10, "STRONG_HIT", "make_connection")
    E.apply_consequences(game, r, {"target_npc": "npc_1", "effect": "standard"})
    assert game.npcs[0]["bond"] == 1 and game.npcs[0]["disposition"] == "friendly"


def test_can_burn_momentum(game):
    game.momentum = 10
    assert E.can_burn_momentum(game, roll("MISS", c1=9, c2=9)) == "STRONG_HIT"
    game.momentum = 5
    assert E.can_burn_momentum(game, roll("MISS", c1=4, c2=9)) == "WEAK_HIT"
    game.momentum = 0
    assert E.can_burn_momentum(game, roll("MISS", c1=1, c2=1)) is None


def test_npc_agency_tick_flag(game):
    game.scene_count = 10
    game.npcs[0]["agenda"] = "Macht"
    game.clocks = [{"id": "c", "name": "Plan", "clock_type": "scheme", "segments": 4,
                    "filled": 0, "owner": "Mara Voss", "trigger_description": "x"}]
    actions, events = E.check_npc_agency(game, tick=False)
    assert actions and not events and game.clocks[0]["filled"] == 0
    actions, events = E.check_npc_agency(game)
    assert events and game.clocks[0]["filled"] == 1


def test_clock_without_trigger_description_does_not_crash(game):
    game.clocks[0].pop("trigger_description")
    E.apply_consequences(game, roll("MISS"), {"position": "risky"})


def test_correction_merge_repoints_refs(game):
    game.npcs = [
        make_npc("npc_1", "Mara Voss", bond=1),
        make_npc("npc_2", "Die Frau am Kai", bond=2, memory=[]),
        make_npc("npc_3", "Jorin", memory=[{"scene": 2, "event": "sah sie",
                                            "about_npc": "npc_2", "importance": 4,
                                            "type": "observation"}]),
    ]
    game.clocks = [{"id": "c", "name": "X", "clock_type": "scheme", "segments": 4,
                    "filled": 0, "owner": "Die Frau am Kai", "trigger_description": "x"}]
    E._apply_correction_ops(game, [{"op": "npc_merge", "npc_id": "npc_1",
                                    "merge_source_id": "npc_2"}])
    ids = [n["id"] for n in game.npcs]
    assert ids == ["npc_1", "npc_3"]
    assert game.npcs[1]["memory"][0]["about_npc"] == "npc_1"
    assert game.clocks[0]["owner"] == "Mara Voss"
    assert game.npcs[0]["bond"] == 2


def test_correction_edit_and_split_validation(game):
    E._apply_correction_ops(game, [
        {"op": "npc_edit", "npc_id": "npc_1",
         "fields": {"bond": 99, "disposition": "Freundlich", "status": "inactive",
                    "aliases": "kein-array"}},
        {"op": "npc_split", "npc_id": "npc_1", "split_name": "Zwilling"},
        {"op": "time_edit", "value": "Banane"},
    ])
    n = game.npcs[0]
    assert n["bond"] == 4 and n["status"] == "background"
    assert isinstance(n["aliases"], list)
    split = game.npcs[-1]
    assert split["id"] == "npc_2" and "importance_accumulator" in split
    assert game.time_of_day == "evening"
