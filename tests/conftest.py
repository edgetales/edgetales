"""
Shared pytest fixtures for the EdgeTales engine test suite.

All tests run WITHOUT network access and WITHOUT an API key: every Anthropic
call is replaced by a deterministic fake. Run from the project root:

    pip install pytest jsonschema
    python -m pytest tests -q
"""
import logging
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Keep engine logging out of the project's logs/ directory: setup_file_logging()
# skips when the logger already has a handler.
_logger = logging.getLogger("rpg_engine")
if not _logger.handlers:
    _logger.addHandler(logging.NullHandler())

import engine as E  # noqa: E402


# ---------------------------------------------------------------------------
# Isolation: user data in a temp dir, fresh module-level caches/flags per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_engine(tmp_path, monkeypatch):
    users = tmp_path / "users"
    users.mkdir()
    monkeypatch.setattr(E, "USERS_DIR", users)
    monkeypatch.setattr(E, "GLOBAL_CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(E, "_NPC_ID_ENUM_DISABLED", False)
    E._SAVE_INFO_CACHE.clear()
    random.seed(1234)
    yield


# ---------------------------------------------------------------------------
# Fake AI layer
# ---------------------------------------------------------------------------

class FakeAI:
    """Replaces every AI call used by the turn pipelines.

    Attributes can be changed per test:
      brain        dict returned by call_brain (copied per call)
      narration    text returned by call_narrator
      metadata     dict returned by call_narrator_metadata (copied per call)
      fail_on      name of a call that should raise RuntimeError ("narrator", ...)
      roll         RollResult forced by roll_action (None = real dice)
    """

    def __init__(self):
        self.brain = make_brain()
        self.narration = "Der Wind trägt Salz vom Hafen herauf."
        self.metadata = make_metadata()
        self.fail_on = None
        self.roll = None
        self.calls = []

    def _maybe_fail(self, name):
        self.calls.append(name)
        if self.fail_on == name:
            raise RuntimeError(f"simulated {name} failure")

    def call_brain(self, client, game, msg, config=None):
        self._maybe_fail("brain")
        return dict(self.brain)

    def call_narrator(self, client, prompt, game, config=None):
        self._maybe_fail("narrator")
        return self.narration

    def call_narrator_metadata(self, client, narration, game, config=None):
        self._maybe_fail("metadata")
        import copy
        return copy.deepcopy(self.metadata)

    def call_revelation_check(self, *a, **k):
        self._maybe_fail("revelation")
        return False

    def roll_action(self, stat_name, stat_value, move):
        if self.roll is not None:
            r = self.roll
            return E.RollResult(r.d1, r.d2, r.c1, r.c2, stat_name, stat_value,
                                r.action_score, r.result, move, r.match)
        return E._real_roll_action(stat_name, stat_value, move)


if not hasattr(E, "_real_roll_action"):
    E._real_roll_action = E.roll_action


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(E, "call_brain", fake.call_brain)
    monkeypatch.setattr(E, "call_narrator", fake.call_narrator)
    monkeypatch.setattr(E, "call_narrator_metadata", fake.call_narrator_metadata)
    monkeypatch.setattr(E, "call_revelation_check", fake.call_revelation_check)
    monkeypatch.setattr(E, "roll_action", fake.roll_action)
    monkeypatch.setattr(E, "check_chaos_interrupt", lambda game: None)
    monkeypatch.setattr(E, "_tick_autonomous_clocks", lambda game: [])
    return fake


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def make_brain(**over):
    b = {
        "type": "action", "move": "face_danger", "stat": "iron", "approach": "",
        "target_npc": None, "dialog_only": False, "player_intent": "Ich klettere",
        "world_addition": None, "position": "risky", "effect": "standard",
        "dramatic_question": "", "location_change": None, "time_progression": "none",
    }
    b.update(over)
    return b


def make_metadata(**over):
    m = {"scene_context": "Spannung liegt in der Luft.", "location_update": None,
         "time_update": None, "memory_updates": [], "new_npcs": [], "npc_renames": [],
         "npc_details": [], "deceased_npcs": [], "lore_npcs": [], "exited_npc_ids": []}
    m.update(over)
    return m


def make_npc(npc_id="npc_1", name="Mara Voss", **over):
    n = {"id": npc_id, "name": name, "status": "active", "disposition": "neutral",
         "bond": 0, "bond_max": 4, "aliases": [], "introduced": True,
         "description": "Hafenmeisterin", "agenda": "", "instinct": "",
         "memory": [{"scene": 1, "event": f"{name} trifft den Spieler",
                     "emotional_weight": "neutral", "importance": 4,
                     "type": "observation"}]}
    n.update(over)
    E._ensure_npc_memory_fields(n)
    return n


def roll(result="MISS", c1=9, c2=9, d1=1, d2=1, stat_value=2, match=None):
    score = min(d1 + d2 + stat_value, 10)
    return E.RollResult(d1, d2, c1, c2, "iron", stat_value, score, result,
                        "face_danger", (c1 == c2) if match is None else match)


@pytest.fixture
def game():
    g = E.GameState(player_name="Elin", scene_count=3, current_location="Die Taverne",
                    time_of_day="evening", momentum=5)
    g.npcs = [make_npc()]
    g.clocks = [{"id": "clock_1", "name": "Sturmflut", "clock_type": "threat",
                 "segments": 6, "filled": 1, "owner": "world",
                 "trigger_description": "Das Hafenviertel läuft voll", "fired": False}]
    g.session_log = [{"scene": 3, "summary": "vorher", "move": "dialog",
                      "result": "dialog", "consequences": [], "clock_events": []}]
    g.narration_history = [{"scene": 3, "prompt_summary": "x", "narration": "alt"}]
    g.story_blueprint = {
        "structure_type": "3act",
        "acts": [
            {"phase": "setup", "title": "A", "goal": "g", "scene_range": [1, 6],
             "transition_trigger": "t", "mood": "m"},
            {"phase": "confrontation", "title": "B", "goal": "g", "scene_range": [7, 12],
             "transition_trigger": "t", "mood": "m"},
            {"phase": "climax", "title": "C", "goal": "g", "scene_range": [13, 16],
             "mood": "m"},
        ],
        "revelations": [],
    }
    return g


def state_fingerprint(g):
    """Comparable view of the complete GameState (for rollback assertions)."""
    import dataclasses
    import json
    d = dataclasses.asdict(g)
    return json.dumps(d, sort_keys=True, default=str)
