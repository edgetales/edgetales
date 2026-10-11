#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Tales - Narrative Solo RPG Engine
========================================
Core Module (Framework-Independent)
"""

import json
import copy
import re
import random
import math
import logging
import sys
import html
import os
import threading
from pathlib import Path
from datetime import datetime
import dataclasses
from dataclasses import dataclass, field
from typing import Optional

import anthropic

# PDF export
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    Paragraph, Spacer, PageBreak, HRFlowable,
    BaseDocTemplate, PageTemplate, Frame,
)

# Emoji/Unicode constants & languages — now defined in i18n.py
from i18n import E, LANGUAGES, t as _t

# Stop words library for NPC keyword filtering (zero-dependency, 34+ languages)
try:
    from stop_words import get_stop_words as _lib_get_stop_words
    _HAS_STOP_WORDS_LIB = True
except ImportError:
    _HAS_STOP_WORDS_LIB = False

# Name parser for title/honorific detection in NPC fuzzy matching
try:
    from nameparser.config import CONSTANTS as _NAMEPARSER_CONSTANTS
    _HAS_NAMEPARSER = True
except ImportError:
    _HAS_NAMEPARSER = False

# Random word generation for creativity seeds (output diversity)
try:
    from wonderwords import RandomWord as _RandomWord
    _rw = _RandomWord()
    _HAS_WONDERWORDS = True
except ImportError:
    _HAS_WONDERWORDS = False

# ===============================================================
# CONFIGURATION
# ===============================================================

VERSION = "0.9.99"
BRAIN_MODEL = "claude-haiku-5-5"
NARRATOR_MODEL = "claude-sonnet-5-5"
_SCRIPT_DIR = Path(__file__).resolve().parent
USERS_DIR = _SCRIPT_DIR / "users"
USERS_DIR.mkdir(exist_ok=True)
GLOBAL_CONFIG_FILE = _SCRIPT_DIR / "config.json"
LOG_DIR = _SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# --- Utility helpers ---

def _xa(s: str) -> str:
    """Escape a string for safe use as an XML attribute value.
    Converts " → &quot;, < → &lt;, > → &gt;, & → &amp;.
    Use for all AI-generated prose inserted into XML attribute positions."""
    return html.escape(str(s), quote=True)


def _scene_header(game: "GameState") -> str:
    """Build the escaped <world> and <character> opening lines shared by all narrator prompts.
    Attribute values are escaped via _xa(); element content via html.escape().
    Single source of truth — prevents genre/tone/player_name/description from breaking prompt XML."""
    return (
        f'<world genre="{_xa(game.setting_genre)}" tone="{_xa(game.setting_tone)}">'
        f'{html.escape(game.setting_description)}</world>\n'
        f'<character name="{_xa(game.player_name)}">'
        f'{html.escape(game.character_concept)}</character>'
    )


# --- Tuning constants ---
STAT_TARGET_SUM = 7                # Character stats must total this

# Primary stat per archetype (must be ≥ 2 after validation).
# Used by call_setup_brain for both prompt guidance and engine correction.
_ARCHETYPE_PRIMARY_STAT: dict[str, str] = {
    "outsider_loner": "shadow",
    "investigator":   "wits",
    "trickster":      "shadow",
    "protector":      "iron",
    "hardboiled":     "iron",
    "scholar":        "wits",
    "healer":         "heart",
    "inventor":       "wits",
    "artist":         "heart",
}

# Archetype-aware fallback stats (sum=7, primary≥2).
# Used when the AI returns an invalid stat total.
_ARCHETYPE_STAT_DEFAULTS: dict[str, dict] = {
    "outsider_loner": {"edge": 1, "heart": 1, "iron": 1, "shadow": 3, "wits": 1},
    "investigator":   {"edge": 1, "heart": 1, "iron": 1, "shadow": 1, "wits": 3},
    "trickster":      {"edge": 2, "heart": 1, "iron": 1, "shadow": 2, "wits": 1},
    "protector":      {"edge": 1, "heart": 2, "iron": 2, "shadow": 1, "wits": 1},
    "hardboiled":     {"edge": 1, "heart": 1, "iron": 3, "shadow": 1, "wits": 1},
    "scholar":        {"edge": 1, "heart": 1, "iron": 1, "shadow": 1, "wits": 3},
    "healer":         {"edge": 1, "heart": 3, "iron": 1, "shadow": 1, "wits": 1},
    "inventor":       {"edge": 2, "heart": 1, "iron": 1, "shadow": 1, "wits": 2},
    "artist":         {"edge": 1, "heart": 2, "iron": 1, "shadow": 1, "wits": 2},
    "_default":       {"edge": 1, "heart": 2, "iron": 1, "shadow": 1, "wits": 2},
}

MAX_ACTIVE_NPCS = 12               # Soft limit; excess NPCs get retired
MAX_ACTIVE_CLOCKS = 6              # Hard cap; Director cannot add clocks beyond this
ARC_MAX_CHARS = 300                # NPC arc length; longer Director arcs are trimmed at a sentence end
LOCATION_MAX_CHARS = 40            # Longer location strings are cut to a short place label
NPC_NAME_MAX_CHARS = 60            # Longer "names" are descriptions; cut at a word boundary
ARCHITECT_ATTEMPTS = 2             # Story Architect tries before the generic fallback blueprint (too few acts / unparseable)
ACT_MIN_SCENES = 2                 # Director act_transition is ignored earlier than this many scenes into an act's range
ACT_TRIGGER_DUE_SCENES = 2         # Within this many scenes of an act's range end, the trigger is "due": the Director runs once and steers toward it
NPC_STALE_SCENES = 8               # Scenes without any memory update before retirement-eligible
MAX_NPC_MEMORY_ENTRIES = 25        # Per NPC (total: observations + reflections)
MAX_NPC_OBSERVATIONS = 15          # Max observation memories per NPC
MAX_NPC_REFLECTIONS = 8            # Max reflection memories per NPC
MAX_NARRATION_HISTORY = 7          # Recent narrations kept for prompt context
MAX_NARRATION_CHARS = 1500         # Truncation per narration entry
MAX_SESSION_LOG = 50               # Scene log entries kept
REFLECTION_THRESHOLD = 30          # Importance accumulator threshold for reflection
MAX_ACTIVATED_NPCS = 4             # Max NPCs with full context in narrator prompt
NPC_ACTIVATION_THRESHOLD = 0.7     # Minimum score for full NPC activation
NPC_MENTION_THRESHOLD = 0.3        # Minimum score for NPC name mention
DIRECTOR_INTERVAL = 2              # Call director every N scenes (when no trigger)
MEMORY_RECENCY_DECAY = 0.92        # Exponential decay factor for memory recency
AUTONOMOUS_CLOCK_TICK_CHANCE = 0.20  # Per-scene chance each threat clock ticks autonomously
WEAK_HIT_CLOCK_TICK_CHANCE  = 0.50  # Chance a threat clock ticks on WEAK_HIT + risky position
DIRECTOR_MODEL = BRAIN_MODEL       # Director uses same model as Brain (Haiku)

# --- Max output tokens per call ---
# These are upper bounds, NOT cost drivers — you only pay for tokens actually generated.
# Structured Output calls (Brain, Director, Metadata, etc.) self-terminate when the
# JSON schema is complete; the limit just prevents truncated string fields.
# Narrator/Recap (free prose) self-regulate via prompt instructions.
_MAX_TOKENS_HAIKU  = 8192           # Haiku 4.5 model maximum
_MAX_TOKENS_SONNET = 8192           # Sonnet 4.5 model maximum
BRAIN_MAX_TOKENS       = _MAX_TOKENS_HAIKU    # call_brain (was 512)
SETUP_BRAIN_MAX_TOKENS = _MAX_TOKENS_HAIKU    # call_setup_brain (was 512)
RECAP_MAX_TOKENS       = _MAX_TOKENS_HAIKU    # call_recap (was 1200)
METADATA_MAX_TOKENS    = _MAX_TOKENS_HAIKU    # call_narrator_metadata (was 3500)
DIRECTOR_MAX_TOKENS    = _MAX_TOKENS_HAIKU    # call_director (was 6000)
CHAPTER_SUM_MAX_TOKENS = _MAX_TOKENS_HAIKU    # call_chapter_summary (was 1500)
CORRECTION_MAX_TOKENS  = _MAX_TOKENS_HAIKU    # call_correction_brain (was 1500)
OPENING_MAX_TOKENS          = _MAX_TOKENS_HAIKU    # call_opening_metadata (new)
REVELATION_CHECK_MAX_TOKENS = _MAX_TOKENS_HAIKU    # call_revelation_check (new)
COGM_QUESTION_MAX_TOKENS    = _MAX_TOKENS_HAIKU    # call_cogm_question (co-op mode)
NARRATOR_MAX_TOKENS   = _MAX_TOKENS_SONNET   # call_narrator (was 3500)
STORY_ARCH_MAX_TOKENS  = _MAX_TOKENS_SONNET   # call_story_architect (was 4000)

# --- Creativity seed (output diversity for character/scene generation) ---
_SEED_FALLBACK = [
    "amber", "coyote", "furnace", "silk", "glacier", "compass",
    "terracotta", "jasmine", "anvil", "cobalt", "driftwood", "saffron",
    "limestone", "falcon", "obsidian", "cedar", "mercury", "lantern",
    "basalt", "thistle", "copper", "monsoon", "flint", "orchid",
    "pewter", "canyon", "quartz", "ember", "mahogany", "coral",
]

def _creativity_seed(n: int = 3) -> str:
    """Generate random words to perturb LLM token probabilities for output diversity.
    Uses wonderwords library if available, otherwise falls back to built-in word list."""
    if _HAS_WONDERWORDS:
        try:
            words = [_rw.word(include_parts_of_speech=["nouns", "adjectives"],
                              word_min_length=4, word_max_length=12,
                              exclude_with_spaces=True)
                     for _ in range(n)]
            return " ".join(words)
        except Exception:
            pass
    return " ".join(random.sample(_SEED_FALLBACK, min(n, len(_SEED_FALLBACK))))

# --- Structured Output Schemas (constrained decoding, GA since Dec 2025) ---
# These schemas guarantee valid JSON from the API — no parsing, repair, or retry needed.
# Used with output_config={"format": {"type": "json_schema", "schema": <SCHEMA>}}

BRAIN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "type":               {"type": "string", "enum": ["action"]},
        "move":               {"type": "string", "enum": [
            "face_danger", "compel", "gather_information", "secure_advantage",
            "clash", "strike", "endure_harm", "endure_stress",
            "make_connection", "test_bond", "resupply", "world_shaping", "dialog",
        ]},
        "stat":               {"type": "string", "enum": [
            "edge", "heart", "iron", "shadow", "wits", "none",
        ]},
        "approach":           {"type": "string"},
        "target_npc":         {"type": ["string", "null"]},
        "dialog_only":        {"type": "boolean"},
        "player_intent":      {"type": "string"},
        "world_addition":     {"type": ["string", "null"]},
        "position":           {"type": "string", "enum": ["controlled", "risky", "desperate"]},
        "effect":             {"type": "string", "enum": ["limited", "standard", "great"]},
        "dramatic_question":  {"type": "string"},
        "location_change":    {"type": ["string", "null"]},
        "time_progression":   {"type": "string", "enum": ["none", "short", "moderate", "long"]},
    },
    "required": [
        "type", "move", "stat", "approach", "target_npc", "dialog_only",
        "player_intent", "world_addition", "position", "effect",
        "dramatic_question", "location_change", "time_progression",
    ],
    "additionalProperties": False,
}

SETUP_BRAIN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "character_name":      {"type": "string"},
        "character_concept":   {"type": "string"},
        "setting_description": {"type": "string"},
        "stats": {
            "type": "object",
            "properties": {
                "edge":   {"type": "integer"},
                "heart":  {"type": "integer"},
                "iron":   {"type": "integer"},
                "shadow": {"type": "integer"},
                "wits":   {"type": "integer"},
            },
            "required": ["edge", "heart", "iron", "shadow", "wits"],
            "additionalProperties": False,
        },
        "starting_location":   {"type": "string"},
        "opening_situation":   {"type": "string"},
    },
    "required": [
        "character_name", "character_concept", "setting_description",
        "stats", "starting_location", "opening_situation",
    ],
    "additionalProperties": False,
}

DIRECTOR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_summary":      {"type": "string"},
        "narrator_guidance":  {"type": "string"},
        "npc_guidance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id":   {"type": "string"},
                    "guidance": {"type": "string"},
                },
                "required": ["npc_id", "guidance"],
                "additionalProperties": False,
            },
        },
        "pacing": {"type": "string", "enum": [
            "tension_rising", "building", "climax", "breather", "resolution",
        ]},
        "npc_reflections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id":              {"type": "string"},
                    "reflection":          {"type": "string"},
                    "tone":                {"type": "string"},
                    "tone_key":            {"type": "string", "enum": [
                        "neutral", "curious", "wary", "suspicious", "grateful",
                        "terrified", "loyal", "conflicted", "betrayed", "devastated",
                        "euphoric", "defiant", "guilty", "protective", "angry",
                        "devoted", "impressed", "hopeful",
                    ]},
                    "about_npc":           {"type": ["string", "null"]},
                    "updated_description": {"type": ["string", "null"]},
                    "updated_agenda":      {"type": ["string", "null"]},
                    "updated_arc":         {"type": ["string", "null"]},
                    "agenda":              {"type": ["string", "null"]},
                    "instinct":            {"type": ["string", "null"]},
                    # Organic disposition shift driven by accumulated story development.
                    # "improve": one step toward loyal (hostile→distrustful→neutral→friendly→loyal)
                    # "worsen":  one step toward hostile
                    # null: no change (default — shifts are rare, not every reflection)
                    "disposition_shift":   {"type": ["string", "null"]},
                },
                "required": ["npc_id", "reflection", "tone", "tone_key",
                             "about_npc", "updated_description", "updated_agenda",
                             "updated_arc", "agenda", "instinct",
                             "disposition_shift"],
                "additionalProperties": False,
            },
        },
        "arc_notes": {"type": "string"},
        # Evidence sentence generated BEFORE the boolean — without it, smaller
        # models answered act_transition=false by default even when their own
        # arc_notes described the trigger as fulfilled.
        "act_transition_check": {"type": "string"},
        "act_transition": {"type": "boolean"},
        "new_clocks": {
            # Director-proposed threat clocks for genuinely new mid-game dangers.
            # Only populated when a concrete new threat has emerged that no existing
            # clock already tracks. Empty array is the default; clock spam is avoided
            # by the strict instruction in build_director_prompt.
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":                {"type": "string"},
                    "clock_type":          {"type": "string",
                                           "enum": ["threat", "scheme"]},
                    "segments":            {"type": "integer"},
                    "filled":              {"type": "integer"},
                    "trigger_description": {"type": "string"},
                    "owner":               {"type": "string"},
                },
                "required": ["name", "clock_type", "segments", "filled",
                             "trigger_description", "owner"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scene_summary", "narrator_guidance", "npc_guidance",
                  "pacing", "npc_reflections", "arc_notes", "act_transition_check",
                  "act_transition", "new_clocks"],
    "additionalProperties": False,
}

STORY_ARCHITECT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "central_conflict":  {"type": "string"},
        "antagonist_force":  {"type": "string"},
        "thematic_thread":   {"type": "string"},
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "phase":              {"type": "string"},
                    "title":              {"type": "string"},
                    "goal":               {"type": "string"},
                    "scene_range":        {"type": "array", "items": {"type": "integer"}},
                    "mood":               {"type": "string"},
                    "transition_trigger": {"type": "string"},
                },
                "required": ["phase", "title", "goal", "scene_range", "mood", "transition_trigger"],
                "additionalProperties": False,
            },
        },
        "revelations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":              {"type": "string"},
                    "content":         {"type": "string"},
                    "earliest_scene":  {"type": "integer"},
                    "dramatic_weight": {"type": "string", "enum": [
                        "low", "medium", "high", "critical",
                    ]},
                },
                "required": ["id", "content", "earliest_scene", "dramatic_weight"],
                "additionalProperties": False,
            },
        },
        "possible_endings": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "type":        {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["type", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["central_conflict", "antagonist_force", "thematic_thread", "acts",
                  "revelations", "possible_endings"],
    "additionalProperties": False,
}

CHAPTER_SUMMARY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title":              {"type": "string"},
        "summary":            {"type": "string"},
        "unresolved_threads": {"type": "array", "items": {"type": "string"}},
        "character_growth":   {"type": "string"},
        "npc_evolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string"},
                    "projection": {"type": "string"},
                },
                "required": ["name", "projection"],
                "additionalProperties": False,
            },
        },
        "thematic_question":  {"type": "string"},
        "post_story_location": {"type": "string"},
    },
    "required": ["title", "summary", "unresolved_threads", "character_growth",
                  "npc_evolutions", "thematic_question", "post_story_location"],
    "additionalProperties": False,
}

NARRATOR_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_context": {"type": "string", "minLength": 1},
        "location_update": {"type": ["string", "null"]},
        "time_update": {"type": ["string", "null"]},
        "memory_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id":           {"type": "string"},
                    "event":            {"type": "string"},
                    "emotional_weight": {"type": "string"},
                    "about_npc":        {"type": ["string", "null"]},
                    # absent=true: NPC is NOT physically present but was explicitly
                    # named in the narration with narratively significant off-screen
                    # development (e.g. confirmed transported, known to be in danger).
                    # Produces a low-importance "mention" memory; does not reactivate
                    # background NPCs or update last_location.
                    "absent":           {"type": ["boolean", "null"]},
                    # npc_id="NEW" → this memory belongs to a character introduced in
                    # the SAME response (new_npcs). new_npc_name carries the exact
                    # name used there; the engine resolves it after NPC creation.
                    "new_npc_name":     {"type": ["string", "null"]},
                },
                "required": ["npc_id", "event", "emotional_weight", "about_npc", "absent",
                             "new_npc_name"],
                "additionalProperties": False,
            },
        },
        "new_npcs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "description": {"type": "string"},
                    "disposition": {"type": "string"},
                    "deceased":    {"type": "boolean"},
                },
                "required": ["name", "description", "disposition"],
                "additionalProperties": False,
            },
        },
        "npc_renames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id":   {"type": "string"},
                    "new_name": {"type": "string"},
                },
                "required": ["npc_id", "new_name"],
                "additionalProperties": False,
            },
        },
        "npc_details": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id":      {"type": "string"},
                    "full_name":   {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
                "required": ["npc_id", "full_name", "description"],
                "additionalProperties": False,
            },
        },
        "deceased_npcs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id": {"type": "string"},
                },
                "required": ["npc_id"],
                "additionalProperties": False,
            },
        },
        "lore_npcs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "exited_npc_ids": {
            # npc_ids of NPCs who physically departed the scene (walked out, left through a
            # door, were escorted away). Used by the activation system to suppress
            # phantom-presence re-activation in the immediately following scene.
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["scene_context", "location_update", "time_update",
                  "memory_updates", "new_npcs", "npc_renames", "npc_details",
                  "deceased_npcs", "lore_npcs", "exited_npc_ids"],
    "additionalProperties": False,
}

# Schema for revelation confirmation check.
# Used by call_revelation_check() — determines whether the narrator actually wove
# the pending revelation into the narration before marking it as used.
REVELATION_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "revelation_confirmed": {
            "type": "boolean",
            "description": (
                "True if the narration clearly contains, implies, or meaningfully "
                "foreshadows the revelation content. False if the revelation is absent "
                "or only incidentally touched on."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "One sentence explaining why revelation_confirmed is True or False.",
        },
    },
    "required": ["revelation_confirmed", "reasoning"],
    "additionalProperties": False,
}

# Schema for the co-op Co-GM question (call_cogm_question). The question type
# (now/seed) is decided by the engine, not the model — see _cogm_next_question_type().
COGM_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "One sentence: the question for the Co-GM, in the narration language.",
        },
        "npc_id": {
            "type": "string",
            "description": "ID of the NPC the question is about, or an empty string.",
        },
        "seeds_surfaced": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs from <check_seeds> whose content clearly appears in the narration.",
        },
    },
    "required": ["question", "npc_id", "seeds_surfaced"],
    "additionalProperties": False,
}

# Schema for opening/chapter scene metadata extraction (full NPC schema + clocks).
# Used by call_opening_metadata() — replaces inline <game_data> JSON from narrator.
OPENING_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "npcs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "description": {"type": "string"},
                    "agenda":      {"type": "string"},
                    "instinct":    {"type": "string"},
                    "secrets":     {"type": "array", "items": {"type": "string"}},
                    "disposition": {"type": "string"},
                },
                "required": ["name", "description", "agenda", "instinct",
                             "secrets", "disposition"],
                "additionalProperties": False,
            },
        },
        "clocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":                {"type": "string"},
                    "clock_type":          {"type": "string"},
                    "segments":            {"type": "integer"},
                    "filled":              {"type": "integer"},
                    "trigger_description": {"type": "string"},
                    "owner":               {"type": "string"},
                },
                "required": ["name", "clock_type", "segments", "filled",
                             "trigger_description", "owner"],
                "additionalProperties": False,
            },
        },
        "location":      {"type": "string"},
        "scene_context":  {"type": "string", "minLength": 1},
        "time_of_day":    {"type": ["string", "null"]},
        "deceased_npcs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id": {"type": "string"},
                },
                "required": ["npc_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["npcs", "clocks", "location", "scene_context", "time_of_day",
                 "deceased_npcs"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------
# NPC ID ENUMS — per-call schemas that restrict NPC references to real IDs
# ---------------------------------------------------------------
# Structured Outputs can constrain a string to an enum. Every NPC reference the
# Extractor, Director and Brain return is restricted to known npc_ids, so they
# can no longer answer with names, invented slugs or comma lists — the root cause
# most of the fuzzy fallback layers exist for. The layers stay in place as
# defence in depth (legacy saves, static-schema fallback).
#
# Grammar-cache stability: Anthropic compiles each distinct schema once and caches
# it for 24h; a changed enum costs one extra compilation. The enum therefore
# covers the whole ID *range* npc_1..npc_N rounded up to NPC_ID_ENUM_BUCKET, plus
# any non-standard legacy IDs — so it only changes every 10 new NPCs, not on
# every creation, death or merge. Unassigned IDs in the range are never shown to
# the model; if one is returned anyway, _find_npc() finds nothing and the entry
# is skipped (existing technical-ID guards).
NPC_ID_ENUM_BUCKET = 10
NPC_REF_NEW = "NEW"   # memory_updates: character introduced in the same response

# Set to True for the rest of the process if the API ever rejects a dynamic enum
# schema — all calls then fall back to the static schemas (previous behaviour).
_NPC_ID_ENUM_DISABLED = False


def _npc_id_enum(game) -> list:
    """Stable, sorted list of allowed npc_id values for enum-constrained schemas."""
    ids = {n.get("id") for n in game.npcs if n.get("id")}
    max_num = 0
    for i in ids:
        m = re.fullmatch(r"npc_(\d+)", str(i))
        if m:
            max_num = max(max_num, int(m.group(1)))
    upper = max(NPC_ID_ENUM_BUCKET,
                math.ceil((max_num + 1) / NPC_ID_ENUM_BUCKET) * NPC_ID_ENUM_BUCKET)
    values = {f"npc_{k}" for k in range(1, upper + 1)} | {str(i) for i in ids}

    def _key(v):
        m = re.fullmatch(r"npc_(\d+)", v)
        return (0, int(m.group(1)), "") if m else (1, 0, v)
    return sorted(values, key=_key)


def _nullable_enum(values: list) -> dict:
    """String enum OR null (anyOf — counts as one union parameter)."""
    return {"anyOf": [{"type": "string", "enum": list(values)}, {"type": "null"}]}


def _metadata_schema_for(game) -> dict:
    """NARRATOR_METADATA_SCHEMA with every NPC reference constrained to real IDs."""
    ids = _npc_id_enum(game)
    sch = copy.deepcopy(NARRATOR_METADATA_SCHEMA)
    props = sch["properties"]
    mem = props["memory_updates"]["items"]["properties"]
    mem["npc_id"] = {"type": "string", "enum": ids + [NPC_REF_NEW]}
    mem["about_npc"] = _nullable_enum(ids)
    props["npc_renames"]["items"]["properties"]["npc_id"] = {"type": "string", "enum": ids}
    props["npc_details"]["items"]["properties"]["npc_id"] = {"type": "string", "enum": ids}
    props["deceased_npcs"]["items"]["properties"]["npc_id"] = {"type": "string", "enum": ids}
    props["exited_npc_ids"]["items"] = {"type": "string", "enum": ids}
    return sch


def _director_schema_for(game) -> dict:
    """DIRECTOR_OUTPUT_SCHEMA with NPC references constrained to real IDs."""
    ids = _npc_id_enum(game)
    sch = copy.deepcopy(DIRECTOR_OUTPUT_SCHEMA)
    props = sch["properties"]
    props["npc_guidance"]["items"]["properties"]["npc_id"] = {"type": "string", "enum": ids}
    refl = props["npc_reflections"]["items"]["properties"]
    refl["npc_id"] = {"type": "string", "enum": ids}
    refl["about_npc"] = _nullable_enum(ids)
    return sch


def _brain_schema_for(game) -> dict:
    """BRAIN_OUTPUT_SCHEMA with target_npc constrained to real IDs or null."""
    sch = copy.deepcopy(BRAIN_OUTPUT_SCHEMA)
    sch["properties"]["target_npc"] = _nullable_enum(_npc_id_enum(game))
    return sch


def _is_schema_rejection(e: Exception) -> bool:
    """True if a 400 error is about the output schema (not e.g. prompt length)."""
    msg = str(e).lower()
    return any(k in msg for k in ("schema", "grammar", "enum", "output_config",
                                  "json_schema", "anyof", "too complex"))


def _structured_create(client, dynamic_schema: dict, static_schema: dict,
                       max_retries: int = 2, **kwargs):
    """messages.create with a per-call (ID-enum) schema, falling back to the static
    schema — permanently for this process — if the API rejects the dynamic one."""
    global _NPC_ID_ENUM_DISABLED
    if not _NPC_ID_ENUM_DISABLED:
        try:
            return _api_create_with_retry(
                client, max_retries=max_retries,
                output_config={"format": {"type": "json_schema", "schema": dynamic_schema}},
                **kwargs)
        except anthropic.BadRequestError as e:
            if not _is_schema_rejection(e):
                raise
            _NPC_ID_ENUM_DISABLED = True
            log(f"[Schema] Dynamic NPC-ID enum schema rejected ({e}) — falling back to "
                f"static schemas for this process", level="warning")
    return _api_create_with_retry(
        client, max_retries=max_retries,
        output_config={"format": {"type": "json_schema", "schema": static_schema}},
        **kwargs)


def _resolve_new_npc_refs(mem_updates: list) -> list:
    """Turn npc_id="NEW" memory updates into name references for the NPCs created in
    the same metadata cycle (resolved downstream by _resolve_slug_refs/_find_npc).
    Drops NEW entries without a name. Strips the helper key new_npc_name."""
    out = []
    for u in mem_updates:
        if not isinstance(u, dict):
            continue
        name = u.pop("new_npc_name", None)
        if u.get("npc_id") == NPC_REF_NEW:
            if isinstance(name, str) and name.strip():
                u["npc_id"] = name.strip()
            else:
                log("[Metadata] Dropped memory_update with npc_id=NEW but no new_npc_name",
                    level="warning")
                continue
        out.append(u)
    return out


# --- NPC name matching: title/honorific filter ---
# Uses nameparser library (619 English titles) + German/French/Spanish/RPG additions.
# Prevents false positive fuzzy matches like "Mrs. Chen" ↔ "Mrs. Kowalski".
_NAME_TITLES_EXTRA = frozenset({
    # --- German titles & honorifics (not in nameparser) ---
    "herr", "frau", "fräulein", "doktor", "hauptmann", "leutnant",
    "feldwebel", "meister", "schwester", "bruder", "onkel", "tante",
    "oma", "opa", "alter", "alte", "junger", "junge", "der", "die", "das",
    # German academic & professional titles
    "dekan", "dekanin", "prodekan", "prodekanin",
    "rektor", "rektorin", "prorektor", "prorektorin",
    "dozent", "dozentin", "privatdozent", "privatdozentin",
    "referent", "referentin", "direktor", "direktorin",
    "intendant", "intendantin", "sekretär", "sekretärin",
    # French
    "monsieur", "madame", "mademoiselle",
    # Spanish
    "señor", "señora", "señorita", "don", "doña",
    # Generic descriptors that aren't identity-bearing
    "neighbor", "nachbar", "nachbarin", "stranger", "fremder", "fremde",
    "kunde", "kundin", "customer",
    # --- English RPG titles (Fantasy / Sci-Fi / Medieval, not in nameparser) ---
    # Magic users
    "wizard", "sorcerer", "sorceress", "mage", "warlock", "witch",
    "archmage", "enchantress", "enchanter", "necromancer", "conjurer",
    "alchemist", "spellcaster", "hierophant", "thaumaturge", "illusionist",
    # Classes / Archetypes
    "paladin", "cleric", "rogue", "assassin", "berserker",
    "barbarian", "gladiator", "champion", "sentinel", "guardian",
    "inquisitor", "templar", "crusader", "zealot",
    # Nobility / Feudal
    "duke", "duchess", "squire", "knight", "liege", "regent",
    "viceroy", "viscountess", "castellan", "seneschal", "steward",
    "chamberlain", "herald", "page", "grandmaster",
    # Spiritual / Mystical
    "shaman", "oracle", "prophet", "seer", "sage", "elder",
    "dragonlord", "mystic", "augur", "diviner",
    # Medieval — Common folk / Trades
    "peasant", "serf", "yeoman", "blacksmith", "fletcher",
    "armorer", "tanner", "reeve", "constable", "nun",
    # Sci-Fi — Military & Exotic
    "ensign", "marshal", "overseer", "commissioner", "agent",
    "technician", "operative", "warlord",
    "android", "cyborg", "clone", "emissary", "arbiter",
    "overlord", "archon", "praetor", "legate", "centurion",
    "tribune", "consul", "proconsul",
    # Eastern / Other cultural
    "shogun", "samurai", "daimyo", "ronin", "khan",
    "caliph", "emir", "shah", "pasha", "satrap",
    # Generic RPG descriptors used as titles
    "outcast", "exile", "vagrant", "pilgrim", "wanderer",
    "mercenary", "corsair", "privateer", "buccaneer",
    "taskmaster", "guildmaster", "headmaster",
    # --- German RPG titles (Fantasy / Sci-Fi / Mittelalter) ---
    # Adel & Feudalsystem
    "herzog", "herzogin", "graf", "gräfin", "fürst", "fürstin",
    "markgraf", "markgräfin", "landgraf", "ritter", "knappe",
    "edler", "edle", "junker", "vogt", "lehnsherr",
    "kronprinz", "kronprinzessin", "thronfolger", "regent", "regentin",
    "burgherr", "burgherrin", "kastellan",
    # Militär
    "marschall", "feldherr", "söldner", "söldnerin", "krieger", "kriegerin",
    "gardist", "gardistin", "wache", "wachmann", "rittmeister",
    "bannerherr", "bannerträger", "schildknappe",
    "landsknecht", "hauptfeldwebel", "stabsfeldwebel", "oberst",
    "kommandant", "kommandantin", "admiral", "admiralin",
    # Magie & Mystik
    "hexe", "hexer", "hexenmeister", "hexenmeisterin",
    "zauberer", "zauberin", "magier", "magierin",
    "nekromant", "nekromantin", "alchemist", "alchemistin",
    "druide", "druidin", "schamane", "schamanin",
    "beschwörer", "beschwörerin", "seher", "seherin",
    "orakel", "prophet", "prophetin", "mystiker", "mystikerin",
    "erzmagier", "erzmagierin", "thaumaturg",
    # Geistlichkeit
    "abt", "äbtissin", "prior", "priorin", "kaplan",
    "erzbischof", "diakon", "diakonin", "nonne", "mönch",
    "hohepriester", "hohepriesterin", "inquisitor", "inquisitorin",
    "templar", "kreuzritter", "ordensmeister",
    # Handwerk & Volk
    "bauer", "bäuerin", "schmied", "schmiedin", "gerber",
    "müller", "müllerin", "fischer", "jäger", "jägerin",
    "schäfer", "schäferin", "köhler", "krämer",
    # Sci-Fi deutsch
    "techniker", "technikerin", "ingenieur", "ingenieurin",
    "kanzler", "kanzlerin", "kommissar", "kommissarin",
    "inspektor", "inspektorin",
    # Östlich/exotisch (im deutschen RPG-Kontext)
    "kalif", "wesir", "sultanin", "pascha", "schah",
    # RPG-Generisch
    "meuchler", "meuchlerin", "waldläufer", "waldläuferin",
    "paladin", "paladinin", "barbar", "barbarin",
    "wächter", "wächterin", "hüter", "hüterin",
    "vagabund", "vagabundin", "pilger", "pilgerin",
    "gildenmeister", "gildenmeisterin", "grossmeister",
})
if _HAS_NAMEPARSER:
    # nameparser provides 619 titles: mr, mrs, dr, detective, officer, captain,
    # colonel, sergeant, professor, reverend, king, queen, duke, baron, etc.
    _NAME_TITLES = frozenset(_NAMEPARSER_CONSTANTS.titles) | _NAME_TITLES_EXTRA
else:
    # Fallback: compact manual list covering the most common cases
    _NAME_TITLES = frozenset({
        "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr.", "sir", "lady",
        "lord", "miss", "captain", "cpt", "lieutenant", "lt", "sergeant", "sgt",
        "officer", "detective", "professor", "prof", "father", "sister", "brother",
        "uncle", "aunt", "grandma", "grandpa", "old", "young", "the",
        "king", "queen", "prince", "princess", "duke", "duchess", "baron", "baroness",
        "count", "countess", "viscount", "marquis", "earl",
        "colonel", "commander", "general", "admiral", "major", "corporal", "private",
        "judge", "sheriff", "mayor", "governor", "senator", "chancellor",
        "priest", "priestess", "bishop", "cardinal", "reverend", "pastor",
        "rabbi", "imam", "monk", "abbot", "abbess",
        "ambassador", "consul", "envoy", "delegate",
    }) | _NAME_TITLES_EXTRA

# --- Importance scoring: emotional_weight → importance (1-10) ---
# Comprehensive taxonomy based on GoEmotions (Google, 27 categories),
# Plutchik's Wheel of Emotions (8 primaries × 3 intensities + dyads),
# and RPG-specific emotional states narrators commonly produce.
# Scale: 2=baseline, 3=mild, 4=moderate, 5=significant, 6=strong,
#        7=intense, 8=peak, 9=devastating, 10=character-defining
IMPORTANCE_MAP = {
    # === TIER 2: Baseline / Low engagement ===
    "neutral": 2, "polite": 2, "casual": 2, "indifferent": 2,
    "formal": 2, "calm": 2,
    "acceptance": 2,       # Plutchik: mild trust
    "serenity": 2,         # Plutchik: mild joy
    "pensiveness": 2,      # Plutchik: mild sadness
    "distraction": 2,      # Plutchik: mild surprise
    "stoic": 2,            # RPG: controlled non-reaction
    "calculating": 2,      # RPG: cold assessment
    # === TIER 3: Mild engagement ===
    "amused": 3, "curious": 3, "interested": 3, "pleased": 3,
    "amusement": 3,        # GoEmotions
    "approval": 3,         # GoEmotions
    "curiosity": 3,        # GoEmotions / Plutchik secondary
    "interest": 3,         # Plutchik: mild anticipation
    "realization": 3,      # GoEmotions: cognitive shift
    "surprise": 3,         # GoEmotions / Plutchik primary
    "relief": 3,           # GoEmotions: tension release
    "anticipation": 3,     # Plutchik primary
    "trust": 3,            # Plutchik primary: baseline trust
    "bored": 3,            # Plutchik: mild disgust
    "reluctant": 3,        # RPG: mild resistance
    "sentimental": 3,      # RPG: soft nostalgia
    "nostalgic": 3,        # RPG: looking back
    "merciful": 3,         # RPG: compassionate restraint
    # === TIER 4: Moderate tension / involvement ===
    "annoyed": 4, "wary": 4, "uneasy": 4, "concerned": 4,
    "frustrated": 4, "confused": 4, "nervous": 4,
    "annoyance": 4,        # GoEmotions / Plutchik: mild anger
    "caring": 4,           # GoEmotions: emotional investment
    "confusion": 4,        # GoEmotions: disorientation
    "disapproval": 4,      # GoEmotions / Plutchik dyad
    "embarrassment": 4,    # GoEmotions: social discomfort
    "nervousness": 4,      # GoEmotions: anxiety-lite
    "optimism": 4,         # GoEmotions / Plutchik dyad
    "apprehension": 4,     # Plutchik: mild fear
    "boredom": 4,          # Plutchik: mild disgust (can escalate)
    "vigilance": 4,        # Plutchik: intense anticipation
    "resolute": 4,         # RPG: firm but controlled
    "bitter": 4,           # RPG: lingering resentment
    "disdainful": 4,       # RPG: looking down
    "pleading": 4,         # RPG: asking, not yet desperate
    # === TIER 5: Significant emotional moment ===
    "grateful": 5, "impressed": 5, "suspicious": 5, "angry": 5,
    "disappointed": 5, "protective": 5, "trusting": 5,
    "hopeful": 5, "jealous": 5, "guilty": 5,
    "admiration": 5,       # GoEmotions / Plutchik: strong trust
    "anger": 5,            # GoEmotions / Plutchik primary
    "desire": 5,           # GoEmotions: strong wanting
    "disappointment": 5,   # GoEmotions: unmet expectations
    "disgust": 5,          # GoEmotions / Plutchik primary
    "excitement": 5,       # GoEmotions: heightened arousal
    "fear": 5,             # GoEmotions / Plutchik primary
    "gratitude": 5,        # GoEmotions: deep thankfulness
    "joy": 5,              # GoEmotions / Plutchik primary
    "love": 5,             # GoEmotions / Plutchik dyad
    "pride": 5,            # GoEmotions / Plutchik secondary
    "remorse": 5,          # GoEmotions / Plutchik dyad
    "sadness": 5,          # GoEmotions / Plutchik primary
    "contempt": 5,         # Plutchik dyad: disgust+anger
    "envy": 5,             # Plutchik secondary: sadness+anger
    "hope": 5,             # Plutchik secondary: anticipation+trust
    "submission": 5,       # Plutchik dyad: trust+fear
    "awe": 5,              # Plutchik dyad: fear+surprise
    "shame": 5,            # Plutchik tertiary: fear+disgust
    "determined": 5,       # RPG: strong resolve
    "urgent": 5,           # RPG: time pressure, high stakes demand
    "sympathetic": 5,      # RPG: emotional connection
    "longing": 5,          # RPG: deep desire
    "yearning": 5,         # RPG: intense wanting
    "reverent": 5,         # RPG: deep respect
    "resigned": 5,         # RPG: accepted defeat
    "mournful": 5,         # RPG: active grieving
    "remorseful": 5,       # RPG: deep regret
    # === TIER 6: Strong personal stake / internal conflict ===
    "defiant": 6, "loyal": 6, "conflicted": 6,
    "anxiety": 6,          # Plutchik: anticipation+fear, persistent
    "desperate": 6,        # RPG: high urgency, critical moments
    "hostile": 6,          # RPG: active aggression
    "humiliated": 6,       # RPG: deep shame + social component
    "menacing": 6,         # RPG: threatening presence
    "obsessed": 6,         # RPG: consuming fixation
    "paranoid": 6,         # RPG: fear+suspicion combo
    "vengeful": 6,         # RPG: seeking retribution
    "contemptuous": 6,     # RPG: active disdain
    "dominance": 6,        # Plutchik secondary: anger+trust
    "fatalism": 6,         # Plutchik secondary: resigned to fate
    "empowered": 6,        # RPG: surge of capability
    # === TIER 7: Intense / potentially transformative ===
    "awed": 7, "devoted": 7, "terrified": 7, "furious": 7,
    "heartbroken": 7, "inspired": 7, "grief": 7,
    "amazement": 7,        # Plutchik: intense surprise
    "delight": 7,          # Plutchik secondary: surprise+joy
    "loathing": 7,         # Plutchik: intense disgust
    "rage": 7,             # Plutchik: intense anger
    "terror": 7,           # Plutchik: intense fear
    "horrified": 7,        # RPG: witnessing something terrible
    "panicked": 7,         # RPG: loss of control through fear
    "tormented": 7,        # RPG: sustained suffering
    "triumphant": 7,       # RPG: peak victory moment
    "wrathful": 7,         # RPG: righteous/divine anger
    "bloodthirsty": 7,     # RPG: violent intent
    "ruthless": 7,         # RPG: cold extreme action
    "broken": 7,           # RPG: spirit crushed
    # === TIER 8: Peak emotional moments ===
    "euphoric": 8, "sworn": 8,
    "ecstasy": 8,          # Plutchik: intense joy
    "ecstatic": 8,         # variant of ecstasy
    "aggressiveness": 8,   # Plutchik dyad: anger+anticipation
    # === TIER 9-10: Life-altering / character-defining ===
    "betrayed": 9, "devastated": 9,
    "transformed": 10, "sacrificial": 10, "reborn": 10,
}

# DE → EN mapping for emotional_weight normalization (covers common Narrator outputs)
_EMOTION_DE_EN = {
    # Fear/anxiety family
    "angst": "terrified", "furcht": "fear", "panik": "panicked",
    "ängstlich": "nervous", "verängstigt": "terrified", "unheimlich": "uneasy",
    "besorgt": "concerned", "beunruhigt": "concerned", "beunruhigend": "uneasy",
    "nervös": "nervous", "ominös": "uneasy", "bedrohung": "suspicious",
    "bedrohlich": "menacing", "paranoia": "paranoid",
    # Anger family
    "wut": "rage", "zorn": "furious", "wütend": "angry",
    "rasend": "rage", "zornig": "wrathful", "gereizt": "annoyed",
    "verärgert": "annoyed", "genervt": "annoyed", "frustriert": "frustrated",
    "feindlich": "hostile", "feindselig": "hostile",
    "rachsüchtig": "vengeful", "verachtung": "contempt",
    "verächtlich": "contemptuous", "abscheu": "loathing",
    "ekel": "disgust", "angewidert": "disgust",
    # Sadness/despair family
    "verzweiflung": "devastated", "verzweifelt": "desperate",
    "trauer": "grief", "traurig": "sadness", "traurigkeit": "sadness",
    "schuld": "guilty", "schuldgefühl": "guilty",
    "scham": "shame", "beschämt": "shame",
    "resignation": "resigned", "resigniert": "resigned",
    "melancholie": "pensiveness", "melancholisch": "pensiveness",
    "gebrochen": "broken", "erschüttert": "devastated",
    "wehmut": "nostalgic", "wehmütig": "nostalgic",
    "sehnsucht": "longing", "sehnsüchtig": "yearning",
    "kummer": "mournful", "betrübt": "mournful",
    "reue": "remorse", "reuig": "remorseful",
    "demütigung": "humiliated", "gedemütigt": "humiliated",
    # Trust/loyalty family
    "vertrauen": "trust", "loyalität": "loyal", "loyal": "loyal",
    "pflicht": "loyal", "hingabe": "devoted",
    "bewunderung": "admiration", "respekt": "admiration",
    "ehrfurcht": "awe", "ehrfürchtig": "reverent",
    "liebe": "love", "zuneigung": "caring",
    "mitgefühl": "sympathetic", "mitleid": "sympathetic",
    "stolz": "pride",
    # Betrayal/conflict family
    "verrat": "betrayed", "misstrauen": "suspicious", "konflikt": "conflicted",
    "argwöhnisch": "suspicious", "argwohn": "suspicious",
    # Hope/relief/joy family
    "hoffnung": "hope", "hoffnungsvoll": "hopeful",
    "erleichterung": "relief", "erleichtert": "relief",
    "dankbar": "grateful", "dankbarkeit": "gratitude",
    "freude": "joy", "fröhlich": "joy", "glück": "joy",
    "begeistert": "excitement", "begeisterung": "excitement",
    "euphorisch": "euphoric", "euphorie": "euphoric",
    "triumph": "triumphant", "siegreich": "triumphant",
    "überrascht": "surprise", "überraschung": "surprise",
    "erstaunt": "amazement", "fasziniert": "amazement",
    "entzücken": "delight", "entzückt": "delight",
    # Protective/determined family
    "entschlossenheit": "determined", "entschlossen": "determined",
    "beschützerisch": "protective", "schützend": "protective",
    "trotzig": "defiant", "trotz": "defiant",
    "widerstand": "defiant", "unbeugsam": "defiant",
    "gnadenlos": "ruthless", "erbarmungslos": "ruthless",
    "barmherzig": "merciful", "gnädig": "merciful",
    "ermächtigt": "empowered",
    # Shock/confusion family
    "schock": "terrified", "schockiert": "horrified",
    "entsetzt": "horrified", "entsetzen": "terror",
    "verwirrung": "confusion", "verwirrt": "confused",
    "desorientierung": "confused",
    # Detachment family
    "gleichgültigkeit": "indifferent", "kälte": "indifferent",
    "kalt": "indifferent", "neutral": "neutral",
    "apathisch": "indifferent", "teilnahmslos": "indifferent",
    "gelassen": "calm", "gelassenheit": "serenity",
    "stoisch": "stoic",
    "gelangweilt": "bored", "langeweile": "boredom",
    # Intensity markers (map to their emotional core)
    "verzweifelte": "desperate", "existenzielle": "terrified",
    "tiefe": "devoted", "wachsende": "concerned",
    "dringend": "urgent", "dringlich": "urgent",
    "tragisch": "grief", "bitter": "bitter",
    "neidisch": "envy", "neid": "envy",
    "eifersucht": "jealous", "eifersüchtig": "jealous",
    "besessen": "obsessed", "besessenheit": "obsessed",
    "gequält": "tormented", "qual": "tormented",
    "flehend": "pleading", "flehentlich": "pleading",
    "drohend": "menacing", "bedrohend": "menacing",
    "blutdurstig": "bloodthirsty", "blutrünstig": "bloodthirsty",
    "unterwürfig": "submission", "unterworfen": "submission",
    # English words that appear but aren't in IMPORTANCE_MAP directly
    "desperation": "desperate", "dread": "terror", "horror": "horrified",
    "duty": "loyal",
    "guilt": "guilty", "loyalty": "loyal",
    "solidarity": "loyal", "respect": "admiration", "doubt": "suspicious",
    "hunger": "desire", "victory": "triumphant", "redemption": "devoted",
    "rupture": "betrayed", "reckoning": "conflicted",
    "defiance": "defiant",
    "panic": "panicked", "determination": "determined",
}

# Keywords that boost importance when found in event text
IMPORTANCE_BOOST_KEYWORDS = {
    7: ["saved", "death", "killed", "died", "life", "murder", "sacrifice"],
    5: ["secret", "revealed", "betrayed", "trust", "oath", "sworn", "love"],
    3: ["gift", "helped", "fought", "protected", "warned", "lied"],
}


def _get_user_dir(username: str) -> Path:
    return USERS_DIR / username


# Characters that must never appear in a user or save-slot name: path separators,
# Windows-reserved characters and control characters.
_INVALID_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def is_valid_username(name: str) -> bool:
    """True if name is safe to use as a directory name under USERS_DIR.
    Rejects path separators, '.', '..', leading dots and reserved characters so a
    crafted name can never create or delete directories outside users/."""
    if not name or name != name.strip() or len(name) > 64:
        return False
    if name.startswith(".") or _INVALID_NAME_RE.search(name):
        return False
    return True


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text to path atomically (temp file in the same directory + os.replace).
    A crash or power loss mid-write (Raspberry Pi!) leaves either the old or the new
    file on disk — never a truncated, unparseable JSON file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

def _get_save_dir(username: str) -> Path:
    return _get_user_dir(username) / "saves"

def _get_user_config_file(username: str) -> Path:
    return _get_user_dir(username) / "settings.json"

def _get_legacy_user_config_file(username: str) -> Path:
    """Legacy path for backward compatibility (pre-v0.9.8)."""
    return _get_user_dir(username) / "config.json"


# ===============================================================
# FILE LOGGING
# ===============================================================

def setup_file_logging():
    """Set up file logging to logs/ directory. One log file per day.
    Safe to call multiple times -- skips if handlers already exist.
    """
    logger = logging.getLogger("rpg_engine")

    # Prevent duplicate handlers on repeated calls
    if logger.handlers:
        return

    logger.setLevel(logging.DEBUG)

    today = datetime.now().strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"rpg_engine_{today}.log"

    # File handler (append mode -- continues existing daily log)
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s",
                                       datefmt="%Y-%m-%d %H:%M:%S"))

    # Console handler (preserves existing print-to-console behavior)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"=== Narrative RPG Engine session === Log: {log_path.name}")


def log(msg: str, level: str = "info"):
    """Log a message to both console and log file.
    Drop-in replacement for print() throughout the codebase.
    """
    logger = logging.getLogger("rpg_engine")
    if not logger.handlers:
        setup_file_logging()
    getattr(logger, level, logger.info)(msg)


CHATTERBOX_DEVICE_OPTIONS = {
    "Auto": "auto",
    "CPU": "cpu",
    "GPU (CUDA)": "cuda",
    "Apple Silicon (MPS)": "mps",
}

# Map narration language names to Chatterbox language_id codes
CHATTERBOX_LANG_MAP = {
    "German": "de", "English": "en", "Spanish": "es", "French": "fr",
    "Portuguese": "pt", "Italian": "it", "Dutch": "nl", "Russian": "ru",
    "Chinese (Mandarin)": "zh", "Japanese": "ja", "Korean": "ko",
    "Arabic": "ar", "Hindi": "hi", "Turkish": "tr", "Polish": "pl",
    "Swedish": "sv", "Danish": "da", "Vietnamese": None, "Thai": None,
    "Indonesian": None,
}

# Directory for user-uploaded voice reference samples
VOICE_DIR = _SCRIPT_DIR / "voices"
VOICE_DIR.mkdir(exist_ok=True)

# Map any AI-generated disposition to one of the 5 canonical values
_DISPOSITION_NORMALIZE = {
    # hostile
    "hostile": "hostile", "aggressive": "hostile", "antagonistic": "hostile",
    "hateful": "hostile", "violent": "hostile", "murderous": "hostile",
    "vengeful": "hostile", "enraged": "hostile",
    # distrustful
    "distrustful": "distrustful", "wary": "distrustful", "suspicious": "distrustful",
    "cautious": "distrustful", "guarded": "distrustful", "threatening": "distrustful",
    "menacing": "distrustful", "cold": "distrustful", "dismissive": "distrustful",
    "resentful": "distrustful", "annoyed": "distrustful", "bitter": "distrustful",
    "fearful": "distrustful", "afraid": "distrustful", "nervous": "distrustful",
    "terrified": "distrustful", "anxious": "distrustful", "scared": "distrustful",
    "uneasy": "distrustful", "reluctant": "distrustful", "skeptical": "distrustful",
    # neutral
    "neutral": "neutral", "indifferent": "neutral", "curious": "neutral",
    "amused": "neutral", "intrigued": "neutral", "professional": "neutral",
    "reserved": "neutral", "formal": "neutral", "uncertain": "neutral",
    "confused": "neutral", "surprised": "neutral", "pragmatic": "neutral",
    # friendly
    "friendly": "friendly", "sympathetic": "friendly", "helpful": "friendly",
    "warm": "friendly", "trusting": "friendly", "grateful": "friendly",
    "respectful": "friendly", "kind": "friendly", "hopeful": "friendly",
    "compassionate": "friendly", "cooperative": "friendly", "welcoming": "friendly",
    "caring": "friendly", "supportive": "friendly", "admiring": "friendly",
    # loyal
    "loyal": "loyal", "devoted": "loyal", "protective": "loyal",
    "loving": "loyal", "faithful": "loyal", "bonded": "loyal",
}

def _normalize_disposition(raw: str) -> str:
    """Normalize any AI-generated disposition to one of the 5 canonical values."""
    key = raw.lower().strip()
    return _DISPOSITION_NORMALIZE.get(key, "neutral")

def _normalize_npc_dispositions(npcs: list) -> None:
    """Normalize all NPC dispositions in-place to canonical values."""
    for n in npcs:
        if "disposition" in n:
            n["disposition"] = _normalize_disposition(n["disposition"])


# --- NPC name sanitization: strip parenthetical annotations ---
_ALIAS_HINT_RE = re.compile(
    r'\b(?:auch\s+bekannt\s+als|also\s+known\s+as|aka|genannt|called)\s+',
    re.IGNORECASE,
)

def _sanitize_npc_name(name: str) -> tuple[str, list[str]]:
    """Strip parenthetical annotations from NPC names.
    Returns (clean_name, extracted_aliases).

    Examples:
        'Cremin (auch bekannt als Cremon)' → ('Cremin', ['Cremon'])
        'Barrel (der Fass-Schläger)'       → ('Barrel', ['der Fass-Schläger'])
        'Hauptmann Krahe'                  → ('Hauptmann Krahe', [])
    """
    # Collapse whitespace; a whitespace-only name becomes "" (callers skip it)
    name = " ".join(str(name or "").split())
    if '(' not in name:
        return _cap_npc_name(name), []
    m = re.match(r'^(.+?)\s*\((.+)\)\s*$', name)
    if not m:
        return _cap_npc_name(name), []
    clean = m.group(1).strip()
    paren = m.group(2).strip()
    if not clean:
        return _cap_npc_name(name), []
    # Check for explicit alias hints ("auch bekannt als ...", "aka ...")
    alias_match = _ALIAS_HINT_RE.search(paren)
    if alias_match:
        alias = paren[alias_match.end():].strip().rstrip('.')
        return _cap_npc_name(clean), [_cap_npc_name(alias)] if alias else []
    # Generic parenthetical (epithet, descriptor) → usable as alias
    return _cap_npc_name(clean), [_cap_npc_name(paren)] if paren else []


def _cap_npc_name(name: str) -> str:
    """Cap an NPC name at NPC_NAME_MAX_CHARS, cutting at a word boundary. A model
    occasionally returns a whole description as the name."""
    if len(name) <= NPC_NAME_MAX_CHARS:
        return name
    head = name[:NPC_NAME_MAX_CHARS]
    space = head.rfind(" ")
    return (head[:space] if space >= NPC_NAME_MAX_CHARS // 2 else head).rstrip(" ,;:-")


def _apply_name_sanitization(npc: dict) -> None:
    """Sanitize an NPC's name in-place: strip parentheticals, add as aliases."""
    raw = npc.get("name", "")
    if '(' not in raw:
        return
    clean, extracted = _sanitize_npc_name(raw)
    if clean == raw:
        return
    npc["name"] = clean
    npc.setdefault("aliases", [])
    existing_lower = {a.lower() for a in npc["aliases"]}
    # Add old raw name as alias so searches still find it
    if raw.lower() not in existing_lower and raw.lower() != clean.lower():
        npc["aliases"].append(raw)
        existing_lower.add(raw.lower())
    # Add extracted aliases (the parenthetical content)
    for alias in extracted:
        if alias.lower() not in existing_lower and alias.lower() != clean.lower():
            npc["aliases"].append(alias)
            existing_lower.add(alias.lower())
    # Clean up self-aliases: name change may have made pre-existing aliases redundant
    clean_lower = clean.lower()
    npc["aliases"] = [a for a in npc["aliases"] if a.lower() != clean_lower]
    log(f"[NPC] Sanitized name: '{raw}' → '{clean}' (aliases: {npc['aliases']})")


def _normalize_for_match(s: str) -> str:
    """Normalize a name string for comparison only — stored names are never modified.
    Collapses hyphens, underscores, and whitespace variants to a single space,
    then lowercases and strips. This makes 'Wacholder-im-Schnee', 'Wacholder im Schnee',
    and 'wacholder_im_schnee' all compare equal, catching common AI spelling drift."""
    return re.sub(r'[\s\-_]+', ' ', s).lower().strip()


def _find_npc(game, npc_ref: str) -> Optional[dict]:
    """Find an NPC by ID, name, alias, or substring match.
    Search order: exact ID → normalized name → normalized alias → substring name → substring alias.
    Normalization via _normalize_for_match() collapses hyphens/underscores/whitespace so
    'Wacholder-im-Schnee', 'Wacholder im Schnee', and 'wacholder_im_schnee' all match.
    Brain sometimes returns a name string instead of an ID like 'npc_1'."""
    if not npc_ref:
        return None
    # Brain occasionally returns comma-separated IDs (e.g. "npc_3,npc_4") when a scene
    # involves multiple NPCs. _find_npc resolves a single target — take the first token.
    if "," in npc_ref:
        npc_ref = npc_ref.split(",")[0].strip()
        log(f"[NPC] _find_npc: multi-value target_npc truncated to first token: '{npc_ref}'")
        if not npc_ref:
            return None
    # 1. Try exact ID match
    for n in game.npcs:
        if n.get("id") == npc_ref:
            return n
    # 2. Normalized name match — collapses hyphens, underscores, whitespace variants
    ref_norm = _normalize_for_match(npc_ref)
    for n in game.npcs:
        if _normalize_for_match(n.get("name", "")) == ref_norm:
            return n
    # 3. Normalized alias match
    for n in game.npcs:
        for alias in n.get("aliases", []):
            if _normalize_for_match(alias) == ref_norm:
                return n
    # 3b. Title-aware core match: finds "Eva" when stored as "Dr. Eva", and vice versa.
    #     Strips _NAME_TITLES from both sides and compares the remaining name cores.
    #     Only fires when there is exactly ONE unambiguous match — if two NPCs share
    #     the same untitled core (e.g. two different "Smith"s with different titles),
    #     falls through to the substring check to avoid false positives.
    ref_core = " ".join(w for w in ref_norm.split() if w.rstrip(".") not in _NAME_TITLES)
    if ref_core:
        title_matches = []
        for n in game.npcs:
            name_norm = _normalize_for_match(n.get("name", ""))
            name_core = " ".join(w for w in name_norm.split() if w.rstrip(".") not in _NAME_TITLES)
            if name_core and name_core == ref_core and ref_norm != name_norm:
                title_matches.append(n)
                continue
            for alias in n.get("aliases", []):
                alias_norm = _normalize_for_match(alias)
                alias_core = " ".join(
                    w for w in alias_norm.split() if w.rstrip(".") not in _NAME_TITLES
                )
                if alias_core and alias_core == ref_core and ref_norm != alias_norm:
                    title_matches.append(n)
                    break
        if len(title_matches) == 1:
            log(f"[NPC] Title-aware match: '{npc_ref}' → '{title_matches[0]['name']}'")
            return title_matches[0]
    # 4. Substring fallback — ref is part of name or name is part of ref
    #    (handles "Krahe" matching "Hauptmann Krahe" and vice versa)
    #    v0.9.29: raised from 4→5 chars, title-only references rejected
    if len(ref_norm) >= 5:
        # Reject if the ref is ONLY titles/honorifics (e.g. "Mrs." alone)
        ref_words = set(ref_norm.split())
        if ref_words and ref_words <= _NAME_TITLES:
            return None

        best_match = None
        best_score = 0
        for n in game.npcs:
            name_norm = _normalize_for_match(n.get("name", ""))
            if ref_norm in name_norm or name_norm in ref_norm:
                score = min(len(ref_norm), len(name_norm))
                if score >= 5 and score > best_score:
                    best_score = score
                    best_match = n
                continue
            # Also check aliases for substring
            for alias in n.get("aliases", []):
                alias_norm = _normalize_for_match(alias)
                if ref_norm in alias_norm or alias_norm in ref_norm:
                    score = min(len(ref_norm), len(alias_norm))
                    if score >= 5 and score > best_score:
                        best_score = score
                        best_match = n
        if best_match:
            log(f"[NPC] Fuzzy matched '{npc_ref}' → '{best_match['name']}' (score={best_score})")
            return best_match
    return None


def _resolve_about_npc(game, raw: str, owner_id: str = None) -> Optional[str]:
    """Resolve an about_npc value (slug, name, or id) to a canonical npc_id.
    Returns the npc_id string if found, None otherwise.
    Prevents dangling slug references (e.g. 'leonhard' instead of 'npc_3')
    and self-references (an NPC's memory marked as being about itself)
    from being stored in memory entries."""
    if not raw:
        return None
    npc = _find_npc(game, raw)
    if npc:
        resolved = npc.get("id")
        if owner_id and resolved == owner_id:
            log(f"[NPC] about_npc self-reference rejected (owner={owner_id}, raw='{raw}')")
            return None
        if resolved != raw:
            log(f"[NPC] about_npc resolved '{raw}' → '{resolved}'")
        return resolved
    return None


def _next_npc_id(game) -> tuple[str, int]:
    """Determine the next available NPC ID. Returns (id_string, numeric_part)."""
    max_num = 0
    for n in game.npcs:
        m = re.match(r'npc_(\d+)', n.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    max_num += 1
    return f"npc_{max_num}", max_num


def _edit_distance_le1(a: str, b: str) -> bool:
    """Check if Levenshtein distance between a and b is ≤ 1.
    Catches single-char STT transcription errors (Chan→Chen, Wong→Wang)."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if a == b:
        return True
    if la == lb:
        # Substitution: exactly 1 position differs
        return sum(x != y for x, y in zip(a, b)) == 1
    # Insertion/deletion: shorter string + 1 char = longer string
    if la > lb:
        a, b = b, a  # a is now shorter
    j = diffs = 0
    for i in range(len(b)):
        if j < len(a) and a[j] == b[i]:
            j += 1
        else:
            diffs += 1
            if diffs > 1:
                return False
    return True


def _fuzzy_match_existing_npc(game, new_name: str) -> tuple:
    """Check if a 'new' NPC name fuzzy-matches an existing NPC.
    Handles identity reveals like 'Unbekannter Söldner' → 'Hauptmann Krahe'.
    Returns (matching_npc, match_type) or (None, None).
    match_type is 'identity' for normal matches or 'stt_variant' for edit-distance-1 matches.

    v0.9.29 safety rules:
    - Titles/honorifics (Mr., Mrs., Dr., Herr, Frau, Detective...) never count
      as match evidence — filtered via _NAME_TITLES (nameparser + DE/FR/ES)
    - Single shared word must be ≥5 chars (prevents surname-only false positives)
    - Substring matching requires the shorter string to be ≥5 chars
    """
    if not new_name or len(new_name.strip()) < 3:
        return None, None
    new_norm = _normalize_for_match(new_name)
    # Extract words, filtering out titles/honorifics
    new_words_raw = set(new_norm.split())
    new_words = {w for w in new_words_raw if w.rstrip(".") not in _NAME_TITLES}

    best_match = None
    best_score = 0
    best_type = "identity"  # default match type

    for n in game.npcs:
        name_norm = _normalize_for_match(n.get("name", ""))
        # Skip exact matches (handled elsewhere)
        if name_norm == new_norm:
            continue

        # 1. Substring check: "Krahe" ⊂ "Hauptmann Krahe" or vice versa
        #    Require the SHORTER string to be ≥5 chars to avoid title-only matches
        if new_norm in name_norm or name_norm in new_norm:
            shorter_len = min(len(new_norm), len(name_norm))
            if shorter_len >= 5 and shorter_len > best_score:
                best_score = shorter_len
                best_match = n
                best_type = "identity"
            continue

        # 2. Check aliases for substring match (same ≥5 rule)
        for alias in n.get("aliases", []):
            alias_norm = _normalize_for_match(alias)
            if alias_norm == new_norm:
                return n, "identity"  # Exact alias match — always definite
            if new_norm in alias_norm or alias_norm in new_norm:
                shorter_len = min(len(new_norm), len(alias_norm))
                if shorter_len >= 5 and shorter_len > best_score:
                    best_score = shorter_len
                    best_match = n
                    best_type = "identity"

        # 3. Significant word overlap (e.g. "Krahe" appears in "Hauptmann Krahe")
        #    Filter titles from BOTH sides before comparing
        name_words = {w for w in name_norm.split() if w.rstrip(".") not in _NAME_TITLES}
        alias_words = set()
        for alias in n.get("aliases", []):
            alias_words.update(
                w for w in _normalize_for_match(alias).split()
                if w.rstrip(".") not in _NAME_TITLES
            )
        all_words = name_words | alias_words

        overlap = new_words & all_words
        # Each overlapping word must be ≥5 chars ("Chen"=4 → rejected)
        significant_overlap = [w for w in overlap if len(w) >= 5]

        if significant_overlap:
            # If only 1 word overlaps, verify it's substantial relative to names
            if len(significant_overlap) == 1:
                word = significant_overlap[0]
                name_ratio = len(word) / max(len(name_norm), 1)
                new_ratio = len(word) / max(len(new_norm), 1)
                if max(name_ratio, new_ratio) < 0.4:
                    # Single short word in two long names — too risky
                    log(f"[NPC] Fuzzy match REJECTED: '{new_name}' ~ '{n['name']}' "
                        f"(single overlap '{word}' too small relative to names)")
                    continue

            score = sum(len(w) for w in significant_overlap)
            if score > best_score:
                best_score = score
                best_match = n

        # 4. STT variant check: edit distance ≤ 1 on name parts after title stripping.
        #    Catches transcription errors like "Mrs. Chan" → "Mrs. Chen", "Mr. Wang" → "Mr. Wong".
        #    Safety rules:
        #    - Titles (if present on both sides) must match
        #    - Each name-part word must be ≥ 3 chars
        #    - Single untitled word requires ≥ 5 chars (avoids "Ross" ↔ "Moss")
        #    - Number of name words must match
        ext_titles = {w.rstrip(".") for w in name_norm.split() if w.rstrip(".") in _NAME_TITLES}
        ext_name_words = sorted(w for w in name_norm.split() if w.rstrip(".") not in _NAME_TITLES)
        new_title_set = {w.rstrip(".") for w in new_norm.split() if w.rstrip(".") in _NAME_TITLES}
        new_name_words = sorted(w for w in new_norm.split() if w.rstrip(".") not in _NAME_TITLES)

        if ext_name_words and new_name_words and len(ext_name_words) == len(new_name_words):
            # Titles must be compatible: if both have titles, they must match
            titles_ok = True
            if new_title_set and ext_titles and new_title_set != ext_titles:
                titles_ok = False
            titles_match = bool(new_title_set and ext_titles and new_title_set == ext_titles)

            if titles_ok:
                exact = 0
                near = 0
                fail = False
                for nw, ew in zip(new_name_words, ext_name_words):
                    if nw == ew:
                        exact += 1
                    elif len(nw) >= 3 and len(ew) >= 3 and _edit_distance_le1(nw, ew):
                        near += 1
                    else:
                        fail = True
                        break

                if not fail and near >= 1:
                    accept = False
                    if titles_match:
                        accept = True  # "Mrs. Chan" ~ "Mrs. Chen"
                    elif exact >= 1:
                        accept = True  # "Tommy Chan" ~ "Tommy Chen"
                    elif len(new_name_words) == 1 and len(new_name_words[0]) >= 5:
                        accept = True  # "Kowalski" ~ "Kowalsky"
                    if accept:
                        stt_score = sum(len(w) for w in new_name_words) + 10  # bonus for STT match
                        if stt_score > best_score:
                            best_score = stt_score
                            best_match = n
                            best_type = "stt_variant"
                            log(f"[NPC] STT variant match: '{new_name}' ~ '{n['name']}' "
                                f"(edit distance ≤ 1)")

        # Also check aliases for STT variants
        for alias in n.get("aliases", []):
            alias_norm = _normalize_for_match(alias)
            a_titles = {w.rstrip(".") for w in alias_norm.split() if w.rstrip(".") in _NAME_TITLES}
            a_name_words = sorted(w for w in alias_norm.split() if w.rstrip(".") not in _NAME_TITLES)
            if a_name_words and new_name_words and len(a_name_words) == len(new_name_words):
                a_titles_ok = True
                if new_title_set and a_titles and new_title_set != a_titles:
                    a_titles_ok = False
                a_titles_match = bool(new_title_set and a_titles and new_title_set == a_titles)
                if a_titles_ok:
                    a_exact = a_near = 0
                    a_fail = False
                    for nw, aw in zip(new_name_words, a_name_words):
                        if nw == aw:
                            a_exact += 1
                        elif len(nw) >= 3 and len(aw) >= 3 and _edit_distance_le1(nw, aw):
                            a_near += 1
                        else:
                            a_fail = True
                            break
                    if not a_fail and a_near >= 1:
                        a_accept = a_titles_match or a_exact >= 1 or (len(new_name_words) == 1 and len(new_name_words[0]) >= 5)
                        if a_accept:
                            stt_score = sum(len(w) for w in new_name_words) + 10
                            if stt_score > best_score:
                                best_score = stt_score
                                best_match = n
                                best_type = "stt_variant"
                                log(f"[NPC] STT variant match via alias: '{new_name}' ~ alias '{alias}' of '{n['name']}'")

    if best_match:
        log(f"[NPC] Fuzzy match accepted: '{new_name}' → '{best_match['name']}' "
            f"(score={best_score}, type={best_type})")
    return best_match, best_type


def _merge_npc_identity(existing: dict, new_name: str, new_desc: str = "", game=None):
    """Merge a new identity into an existing NPC (identity reveal).
    Old name becomes an alias, new name becomes primary.
    Pass game to also update any clock whose owner string matches the old name."""
    old_name = existing["name"]
    # Strip parenthetical annotations from new name (e.g. "Cremin (auch bekannt als Cremon)")
    clean_name, extra_aliases = _sanitize_npc_name(new_name or "")
    new_name = clean_name
    if not new_name:
        log(f"[NPC] Identity merge skipped for '{old_name}': empty new name", level="warning")
        return
    # Guard: don't merge if names are identical after normalization
    if _normalize_for_match(old_name) == _normalize_for_match(new_name):
        log(f"[NPC] Identity merge skipped: '{old_name}' → '{new_name}' (same name)")
        return
    existing.setdefault("aliases", [])
    old_norm = _normalize_for_match(old_name)
    if old_name and old_norm not in {_normalize_for_match(a) for a in existing["aliases"]}:
        existing["aliases"].append(old_name)
    existing["name"] = new_name
    # Clean up: remove current name from aliases if present (prevents self-alias)
    new_norm = _normalize_for_match(new_name)
    existing["aliases"] = [a for a in existing["aliases"] if _normalize_for_match(a) != new_norm]
    # Add any aliases extracted from parenthetical
    for alias in extra_aliases:
        if (_normalize_for_match(alias) not in {_normalize_for_match(a) for a in existing["aliases"]}
                and _normalize_for_match(alias) != new_norm):
            existing["aliases"].append(alias)
    if new_desc and not existing.get("description"):
        existing["description"] = new_desc
    # Ensure active status (lore figures become active when their identity is revealed)
    if existing.get("status") in ("background", "lore"):
        _reactivate_npc(existing, reason=f"identity revealed as {new_name}")
    # Update any clock whose owner string still carries the old name.
    # Normalize both sides to catch whitespace/hyphen/case drift.
    if game is not None:
        old_name_norm = _normalize_for_match(old_name)
        for clock in game.clocks:
            if _normalize_for_match(clock.get("owner", "")) == old_name_norm:
                old_owner = clock["owner"]
                clock["owner"] = new_name
                log(f"[Clock] Owner updated on NPC rename: '{clock['name']}' "
                    f"'{old_owner}' → '{new_name}'")
    log(f"[NPC] Identity merged: '{old_name}' → '{new_name}' (aliases: {existing['aliases']})")
    # Another NPC may already carry the revealed name - same person, absorb it
    if game is not None:
        _absorb_duplicate_npc(game, existing, new_name)


def _description_match_existing_npc(game, new_desc: str, new_name_norm: str) -> Optional[dict]:
    """Check if a new NPC's description closely matches an existing NPC's description.
    This catches identity reveals where names share zero words but the character
    is clearly the same (e.g. "Sächsischer NVA-Kommandant" → "Hauptmann Rolf Ziegler"
    when both descriptions mention "NVA-Kommandant" + "Blockade" + "grau...").

    Returns the matching NPC dict or None. Only matches active/background NPCs."""
    if not new_desc or len(new_desc) < 10:
        return None

    # Extract significant words from new description (≥4 chars, no stopwords)
    new_words = {
        w.strip(".,;:!?\"'()-").lower()
        for w in new_desc.split()
        if len(w.strip(".,;:!?\"'()-")) >= 4
    }
    new_words -= _STOPWORDS
    if len(new_words) < 2:
        return None

    best_match = None
    best_score = 0

    for n in game.npcs:
        if n.get("status") not in ("active", "background", "lore"):
            continue
        # Don't match against the NPC being created (same name)
        if _normalize_for_match(n.get("name", "")) == new_name_norm:
            continue
        # Spatial guard: if existing NPC has a known location that differs from
        # the player's current location, they can't be the same person appearing here
        npc_loc = n.get("last_location", "").strip()
        current_loc = (game.current_location or "").strip()
        if npc_loc and current_loc and not _locations_match(npc_loc, current_loc):
            continue

        existing_desc = n.get("description", "")
        if not existing_desc:
            continue

        # Extract significant words from existing description
        existing_words = {
            w.strip(".,;:!?\"'()-").lower()
            for w in existing_desc.split()
            if len(w.strip(".,;:!?\"'()-")) >= 4
        }
        existing_words -= _STOPWORDS

        # Guard: strip words that appear in the candidate NPC's name/aliases
        # from the new description.  If the new desc says "Offizier, der vom
        # Page in bordeauxroter Livree flüstert", those name-words are a
        # *reference* to the existing NPC, not evidence of shared identity.
        _strip = set()
        for _src in [n.get("name", "")] + n.get("aliases", []):
            for _w in _src.split():
                _c = _w.strip(".,;:!?\"'()-").lower()
                if len(_c) >= 4:
                    _strip.add(_c)
        filtered_new = new_words - _strip
        if len(filtered_new) < 2:
            continue

        # Calculate overlap: exact match + substring matching
        exact_overlap = filtered_new & existing_words
        # Substring matches: if word A contains word B (or vice versa), count as partial
        # This catches typos like "Ostblockade" ~ "Ostbloc-Blockade" and
        # compound words like "NVA-Kommandant" matching across descriptions
        substring_matches = set()
        for nw in filtered_new - exact_overlap:
            for ew in existing_words - exact_overlap:
                # Check if one is a substring of the other (min 5 chars)
                if len(nw) >= 5 and len(ew) >= 5:
                    if nw in ew or ew in nw:
                        substring_matches.add(nw)
                        break
                    # Also check hyphen-split parts (e.g. "NVA-Kommandant")
                    nw_parts = set(p for p in nw.split("-") if len(p) >= 4)
                    ew_parts = set(p for p in ew.split("-") if len(p) >= 4)
                    if nw_parts & ew_parts:
                        substring_matches.add(nw)
                        break

        # Weighted overlap: exact=1.0, substring=0.5
        # Bonus: long compound terms (≥12 chars) count extra (very distinctive)
        long_exact = sum(1 for w in exact_overlap if len(w) >= 12)
        effective_overlap = len(exact_overlap) + long_exact * 0.5 + len(substring_matches) * 0.5
        total_matches = exact_overlap | substring_matches

        if effective_overlap < 2.0:  # Need at least 2 exact, or 1 long compound + 1 substring
            continue

        # Require meaningful overlap:
        # - ≥25% of shorter set with effective≥2.0, OR
        # - Any long compound match (≥12 chars) with effective≥2.0
        #   (a 12+ char compound like "NVA-Kommandant" is distinctive enough with support)
        min_set_size = min(len(filtered_new), len(existing_words))
        overlap_ratio = effective_overlap / max(min_set_size, 1)
        has_long_match = any(len(w) >= 12 for w in exact_overlap)

        meets_threshold = (
            (overlap_ratio >= 0.25 and effective_overlap >= 2.0)
            or (has_long_match and effective_overlap >= 2.0)
        )

        if meets_threshold and effective_overlap > best_score:
            best_score = effective_overlap
            best_match = n
            log(f"[NPC] Description match candidate: new='{new_desc[:50]}' ~ "
                f"existing='{n['name']}' desc='{existing_desc[:50]}' "
                f"(exact={exact_overlap}, substr={substring_matches}, "
                f"effective={effective_overlap:.1f}, ratio={overlap_ratio:.1%})")

    return best_match


def _is_descriptor_name(name: str) -> bool:
    """Return True if 'name' is a descriptor/placeholder rather than a proper name.
    Descriptors start with a definite/indefinite article or a generic unknown-marker.
    These NPCs are placeholders awaiting a real identity reveal, so rename guards
    should not block them.
    Examples that return True:  "The Stranger", "A Hooded Figure", "Unknown Man"
    Examples that return False: "John Hartley", "Captain Reade", "Prita Vasudeva"
    """
    if not name or not name.split():
        # A blank name is a placeholder by definition - it may receive a real name
        return True
    first = name.strip().split()[0].lower().rstrip(".,")
    return first in {
        # English articles / markers
        "the", "a", "an", "unknown", "unidentified",
        # German articles (all cases)
        "der", "die", "das", "des", "dem", "den",
        "ein", "eine", "eines", "einem", "einen",
        # French / Spanish (cover multilingual campaigns)
        "le", "la", "les", "un", "une", "el", "los", "las",
    }


def _is_title_only_difference(old_norm: str, new_norm: str) -> bool:
    """Return True if old_norm and new_norm share an identical non-title core —
    i.e. they differ only by title/honorific words such as Dr., Prof., Captain.
    Uses the engine-wide _NAME_TITLES set, which covers academic, military, nobility,
    and RPG-specific titles in English, German, French, and Spanish.

    When this returns True the two name variants refer to the same character and
    the difference is purely stylistic — the Extractor either added or omitted a
    title prefix.  The caller should keep whichever form is more complete (more
    total words) as primary and register the other as an alias.

    Both arguments must already be normalised via _normalize_for_match().
    """
    def _core(norm: str) -> str:
        return " ".join(w for w in norm.split() if w.rstrip(".") not in _NAME_TITLES)

    old_core = _core(old_norm)
    new_core = _core(new_norm)
    return bool(old_core and new_core and old_core == new_core)


def _process_npc_renames(game, json_text: str):
    """Process NPC rename/identity-reveal metadata from narrator <npc_rename> tag.
    Format: [{"npc_id": "npc_2", "new_name": "Hauptmann Krahe"}]"""
    try:
        renames = json.loads(json_text.strip())
        if not isinstance(renames, list):
            return
        for r in renames:
            if not isinstance(r, dict):
                continue
            r["new_name"] = _sanitize_npc_name(r.get("new_name") or "")[0]
            if not r["new_name"]:
                continue
            # Find the NPC to rename
            npc = _find_npc(game, r.get("npc_id", ""))
            if not npc and r.get("old_name"):
                npc = _find_npc(game, r["old_name"])
            if not npc:
                log(f"[NPC] Rename failed: could not find NPC '{r.get('npc_id', '')}' / '{r.get('old_name', '')}'",
                    level="warning")
                continue
            if npc.get("status") == "deceased":
                log(f"[NPC] Rename skipped for deceased NPC: {npc.get('name', '?')}")
                continue
            new_name = r["new_name"].strip()
            # Don't rename to player character (exact or partial match)
            new_norm = _normalize_for_match(new_name)
            player_norm = _normalize_for_match(game.player_name)
            if new_norm == player_norm or (set(new_norm.split()) & set(player_norm.split())):
                log(f"[NPC] Rename rejected: '{new_name}' matches player character")
                continue

            # Guard: reject renames that confuse two distinct established characters.
            # Trigger condition: NPC is established (has memories OR agenda set) AND its
            # current name is a proper name (not a descriptor placeholder like
            # "The Stranger" or "An Unknown Figure") AND the new name shares zero words
            # with the current name + all aliases.
            # When all three conditions hold, the Extractor has almost certainly
            # mis-mapped an NPC reference to the wrong slot — e.g. targeting an
            # established character because a different person was mentioned nearby.
            # In that case: reject the rename and create a new NPC stub instead so
            # the referenced character still enters the world correctly.
            # Descriptor-named NPCs (placeholders) are always allowed through because
            # they exist specifically to receive identity reveals.
            old_name = npc["name"]
            old_norm = _normalize_for_match(old_name)
            if old_norm != new_norm:
                is_established = bool(npc.get("memory")) or bool(npc.get("agenda"))
                if is_established and not _is_descriptor_name(old_name):
                    known_words = set(old_norm.split())
                    for _a in npc.get("aliases", []):
                        known_words |= set(_normalize_for_match(_a).split())
                    new_name_words = set(new_norm.split())
                    if not (new_name_words & known_words):
                        log(f"[NPC] npc_renames: REJECTED rename '{old_name}' → '{new_name}': "
                            f"established proper-named NPC with zero word overlap to new name "
                            f"— creating new NPC stub instead", level="warning")
                        if not _find_npc(game, new_name):
                            stub_desc = r.get("description", "").strip()
                            _npc_id, _ = _next_npc_id(game)
                            stub = {
                                "id": _npc_id,
                                "name": new_name,
                                "description": stub_desc,
                                "agenda": "", "instinct": "", "secrets": [],
                                "disposition": "neutral",
                                "bond": 0, "bond_max": 4,
                                "status": "active",
                                "memory": [],
                                "introduced": True,
                                "aliases": [],
                                "importance_accumulator": 0,
                                "last_reflection_scene": 0,
                                "last_memory_scene": 0,
                                "last_location": game.current_location or "",
                            }
                            game.npcs.append(stub)
                            log(f"[NPC] Created stub NPC '{new_name}' ({_npc_id}) "
                                f"from rejected rename")
                        else:
                            log(f"[NPC] npc_renames: stub skipped — '{new_name}' "
                                f"already exists")
                        continue

            # Title-only variant: names share the same non-title core but differ
            # only by a leading honorific (e.g. "Dr. Vasudeva" ↔ "Vasudeva",
            # or "Captain Reade" ↔ "Doktor Reade").  _merge_npc_identity would
            # silently overwrite the stored name even though both forms refer to
            # the same person.  Instead: keep the more complete form (more total
            # words) as primary and register the other as an alias.
            if old_norm != new_norm and _is_title_only_difference(old_norm, new_norm):
                titled = new_name if len(new_norm.split()) >= len(old_norm.split()) else old_name
                bare   = old_name if titled == new_name else new_name
                npc["name"] = titled
                npc.setdefault("aliases", [])
                bare_norm = _normalize_for_match(bare)
                existing_norms = {_normalize_for_match(a) for a in npc["aliases"]}
                if (bare_norm not in existing_norms
                        and bare_norm != _normalize_for_match(titled)):
                    npc["aliases"].append(bare)
                if npc.get("status") in ("background", "lore"):
                    _reactivate_npc(npc, reason="title variant reappeared")
                log(f"[NPC] npc_renames: title variant '{old_name}' ↔ '{new_name}' "
                    f"— primary='{titled}', alias='{bare}'")
                continue

            _merge_npc_identity(npc, new_name, r.get("description", ""), game=game)
            # Absorb any NPC whose name or alias matches the renamed-to name.
            # Alias matching is intentional: if another NPC already carries this name
            # as an alias, they are narratively the same person and should be merged.
            _absorb_duplicate_npc(game, npc, new_name)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Failed to process NPC renames: {e}", level="warning")


def _trim_to_sentence(text: str, limit: int) -> str:
    """Shorten text to at most `limit` chars, preferring the last sentence end;
    falls back to the last word boundary plus an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "),
              head.rfind("."), head.rfind("!"), head.rfind("?"))
    if cut >= limit // 3:
        return head[:cut + 1].strip()
    space = head[:limit - 1].rfind(" ")
    return (head[:space] if space > 0 else head[:limit - 1]).rstrip(" ,;:—–-") + "…"


def _is_complete_description(desc: str) -> bool:
    """Check if a description looks complete (not truncated mid-sentence).
    Incomplete descriptions are discarded in favor of the existing one."""
    if not desc or len(desc) < 10:
        return False
    return desc.rstrip().endswith(('.', '!', '?', '"', '»', '«', '…', ')', '–', '—'))


def _absorb_duplicate_npc(game, original: dict, merged_name: str):
    """After an identity reveal renames an NPC, check if a duplicate with the
    new name was already created by _process_new_npcs earlier in the same
    metadata cycle. If found, absorb its data and remove the duplicate.

    Example: Metadata Extractor sends both new_npcs=[{"name":"Finn"}] and
    npc_details=[{"npc_id":"npc_7","full_name":"Finn"}]. _process_new_npcs
    creates npc_8 "Finn", then _process_npc_details renames npc_7→"Finn".
    This function merges npc_8 back into npc_7 to prevent duplication.

    Merge direction: original keeps its ID (callers hold this reference), but if
    dup is the richer character (established bond, agenda, more memories), its
    substantive fields overwrite original's in-place. This handles rename scenarios
    where a thin descriptor-NPC ("Die Frau im Wollhut") is renamed to a name already
    carried by a rich established character ("Hanna") — the established character's
    data must win."""
    merged_norm = _normalize_for_match(merged_name)
    for dup in game.npcs:
        dup_name_norm = _normalize_for_match(dup.get("name", ""))
        dup_alias_norms = {_normalize_for_match(a) for a in dup.get("aliases", [])}
        dup_matches = (dup_name_norm == merged_norm or merged_norm in dup_alias_norms)
        if (dup is original
                or not dup_matches
                or dup.get("id") == original.get("id")):
            continue
        if dup.get("status") == "deceased" and original.get("status") != "deceased":
            continue        # a living character is never the dead one of the same name
        dup_id = dup.get("id", "?")
        dup_mems = dup.get("memory", [])

        # Determine which is the richer, more established character.
        # Score: memories count heavily, plus established relationship signals.
        # Computed BEFORE memory combination so the pre-merge state is compared.
        def _richness(n):
            return (len(n.get("memory", [])) * 2
                    + bool(n.get("agenda")) * 3
                    + bool(n.get("instinct")) * 3
                    + n.get("bond", 0) * 2
                    + bool(n.get("description")) * 1)

        dup_richer = _richness(dup) > _richness(original)

        # Transfer memories (always combine both sets)
        original.setdefault("memory", [])
        original["memory"].extend(dup_mems)

        # Absorb importance accumulator
        original["importance_accumulator"] = (
            original.get("importance_accumulator", 0)
            + dup.get("importance_accumulator", 0)
        )

        if dup_richer:
            # dup is the established character — its substantive fields win.
            # original keeps its ID, but gets dup's identity data in-place.
            if dup.get("description"):
                original["description"] = dup["description"]
            if dup.get("agenda"):
                original["agenda"] = dup["agenda"]
            if dup.get("instinct"):
                original["instinct"] = dup["instinct"]
            if dup.get("bond", 0) > original.get("bond", 0):
                original["bond"] = dup["bond"]
            if dup.get("disposition") and dup["disposition"] != "neutral":
                original["disposition"] = dup["disposition"]
            if dup.get("last_location"):
                original["last_location"] = dup["last_location"]
            if dup.get("secrets"):
                original.setdefault("secrets", [])
                original["secrets"].extend(
                    s for s in dup["secrets"] if s not in original["secrets"]
                )
            # Transfer reflection state so the merged NPC inherits dup's
            # reflection history — avoids a spurious re-reflection of content
            # that dup already processed.
            if dup.get("last_reflection_scene", 0) > original.get("last_reflection_scene", 0):
                original["last_reflection_scene"] = dup["last_reflection_scene"]
            if dup.get("_needs_reflection"):
                original["_needs_reflection"] = True
            log(f"[NPC] Absorb: dup '{dup.get('name', '?')}' ({dup_id}) was richer — "
                f"its fields promoted into original '{original['name']}' "
                f"({original.get('id', '?')})")
        else:
            # original is established — only fill empty fields from dup
            if not original.get("description") and dup.get("description"):
                original["description"] = dup["description"]
            if not original.get("agenda") and dup.get("agenda"):
                original["agenda"] = dup["agenda"]
            if not original.get("instinct") and dup.get("instinct"):
                original["instinct"] = dup["instinct"]
            if dup.get("last_location") and not original.get("last_location"):
                original["last_location"] = dup["last_location"]

        # Merge aliases from both sides (avoid self-aliases)
        original.setdefault("aliases", [])
        existing_norms = {_normalize_for_match(a) for a in original["aliases"]}
        original_name_norm = _normalize_for_match(original.get("name", ""))
        for alias in dup.get("aliases", []):
            alias_norm = _normalize_for_match(alias)
            if alias_norm not in existing_norms and alias_norm != original_name_norm:
                original["aliases"].append(alias)

        game.npcs.remove(dup)
        # Re-point memories about the absorbed NPC to the surviving one
        for other in game.npcs:
            for m in other.get("memory", []):
                if isinstance(m, dict) and m.get("about_npc") == dup_id:
                    m["about_npc"] = None if other is original else original.get("id")
        log(f"[NPC] Absorbed duplicate '{dup.get('name', '?')}' ({dup_id}) "
            f"into '{original['name']}' ({original.get('id', '?')}): "
            f"{len(dup_mems)} memories transferred, richer={'dup' if dup_richer else 'original'}")
        # Sanitize: strip parenthetical descriptor aliases the dup name may have introduced
        _apply_name_sanitization(original)
        # Consolidate: merged memory lists may now exceed MAX_NPC_MEMORY_ENTRIES
        _consolidate_memory(original)
        break  # Only one duplicate expected


def _process_npc_details(game, json_text: str, world_addition: str = ""):
    """Process NPC detail updates from narrator <npc_details> tag.
    Captures invented surnames, description changes, or other facts the narrator
    established for known NPCs (e.g. giving Randy the surname 'Cho',
    or updating Karla from 'pilot' to 'mechanic' after narrative reveal).
    world_addition: Brain's world_addition text, used as description fallback when
    the guard rejects an identity reveal and creates a stub with no description.

    Format: [{"npc_id": "npc_3", "full_name": "Randy Cho"}]
    or:     [{"npc_id": "npc_3", "full_name": "Randy Cho", "details": "24, lives in Apt 4B"}]
    or:     [{"npc_id": "npc_3", "description": "New description replacing old one"}]
    """
    try:
        details = json.loads(json_text.strip())
        if not isinstance(details, list):
            return
        for d in details:
            if not isinstance(d, dict):
                continue
            npc = _find_npc(game, d.get("npc_id", ""))
            if not npc:
                log(f"[NPC] npc_details: could not find NPC '{d.get('npc_id', '')}'",
                    level="warning")
                continue

            # Update full name if provided and different
            new_name = " ".join(str(d.get("full_name") or "").split())
            # Strip parenthetical annotations before comparison
            if new_name:
                new_name, paren_aliases = _sanitize_npc_name(new_name)
            else:
                paren_aliases = []
            if new_name and _normalize_for_match(new_name) != _normalize_for_match(npc["name"]):
                old_name = npc["name"]
                # Only update if the new name genuinely EXTENDS the old name
                # (old_norm is a substring of new_norm, e.g. "Randy" → "Randy Cho").
                # The reverse direction (new_norm in old_norm) was intentionally removed:
                # it would allow title-stripping ("Dr. Prita Vasudeva" → "Prita Vasudeva")
                # which is a name shortening, not an extension.
                old_norm = _normalize_for_match(old_name)
                new_norm = _normalize_for_match(new_name)
                if old_norm in new_norm:
                    npc.setdefault("aliases", [])
                    if old_name and _normalize_for_match(old_name) not in {_normalize_for_match(a) for a in npc["aliases"]}:
                        npc["aliases"].append(old_name)
                    npc["name"] = new_name
                    # Add any aliases extracted from parenthetical
                    existing_norms = {_normalize_for_match(a) for a in npc["aliases"]}
                    for alias in paren_aliases:
                        if (_normalize_for_match(alias) not in existing_norms
                                and _normalize_for_match(alias) != new_norm):
                            npc["aliases"].append(alias)
                    log(f"[NPC] Details update: '{old_name}' → '{new_name}' "
                        f"(surname established)")
                else:
                    # Title-only variant: names share the same non-title core but
                    # differ by a leading honorific.  _merge_npc_identity would
                    # overwrite the stored name even though both forms refer to
                    # the same person.  Keep the more complete form as primary
                    # and register the other as an alias.  This runs before the
                    # identity-reveal guard because title words produce partial
                    # word overlap which would otherwise let the guard pass and
                    # allow silent title-stripping.
                    if _is_title_only_difference(old_norm, new_norm):
                        titled = new_name if len(new_norm.split()) >= len(old_norm.split()) else old_name
                        bare   = old_name if titled == new_name else new_name
                        npc["name"] = titled
                        npc.setdefault("aliases", [])
                        bare_norm = _normalize_for_match(bare)
                        existing_norms = {_normalize_for_match(a) for a in npc["aliases"]}
                        if (bare_norm not in existing_norms
                                and bare_norm != _normalize_for_match(titled)):
                            npc["aliases"].append(bare)
                        # Also register any aliases extracted from parenthetical annotation
                        # in the incoming name (e.g. "Dr. Eva (auch: Doktorin Eva)")
                        titled_norm = _normalize_for_match(titled)
                        for alias in paren_aliases:
                            alias_pn = _normalize_for_match(alias)
                            if alias_pn not in existing_norms and alias_pn != titled_norm:
                                npc["aliases"].append(alias)
                        if npc.get("status") in ("background", "lore"):
                            _reactivate_npc(npc, reason="title variant reappeared")
                        log(f"[NPC] Details update: title variant '{old_name}' ↔ '{new_name}' "
                            f"— primary='{titled}', alias='{bare}'")
                    else:
                        # Treat as identity reveal: the extractor provided a valid
                        # npc_id, so we trust the association even when names differ
                        # completely (e.g. "Der Jungfahrer" → "Finn", "Der Fremde" →
                        # "Heinrich Blum").
                        #
                        # Guard: an NPC with existing memories or a set agenda is an
                        # established character the player already knows.  If the Brain
                        # maps such an NPC to a completely different name (zero shared
                        # words across name + all aliases), it has almost certainly
                        # confused two distinct characters — e.g. background NPC "Theo"
                        # (3 memories) mis-mapped to newly introduced "Klaus".
                        # NPCs with 0 memories AND no agenda are fresh stubs where a
                        # rename / reveal is plausible regardless of name overlap.
                        # Agenda check catches Opening Extractor NPCs: they are created
                        # with agenda/instinct set but may have no memories yet on the
                        # first turn of a chapter.
                        is_established = bool(npc.get("memory")) or bool(npc.get("agenda"))
                        if is_established:
                            known_words = set(_normalize_for_match(old_name).split())
                            for _a in npc.get("aliases", []):
                                known_words |= set(_normalize_for_match(_a).split())
                            new_name_words = set(_normalize_for_match(new_name).split())
                            if not (new_name_words & known_words):
                                log(f"[NPC] npc_details: REJECTED identity reveal "
                                    f"'{old_name}' → '{new_name}': NPC has memories and "
                                    f"zero word overlap to new name — creating new NPC "
                                    f"stub instead", level="warning")
                                # Only create stub if _process_new_npcs hasn't already
                                # added this NPC in the same metadata cycle.
                                if not _find_npc(game, new_name):
                                    # Use description from npc_details entry if present;
                                    # fall back to world_addition from Brain for new
                                    # characters the Extractor mis-routed here.
                                    stub_desc = d.get("description", "").strip()
                                    if not stub_desc and world_addition:
                                        # world_addition often reads "Character X, role..."
                                        # Use it verbatim as a rough description seed.
                                        stub_desc = world_addition.strip()
                                        log(f"[NPC] npc_details: using world_addition as "
                                            f"description fallback for stub '{new_name}'")
                                    _npc_id, _ = _next_npc_id(game)
                                    stub = {
                                        "id": _npc_id,
                                        "name": new_name,
                                        "description": stub_desc,
                                        "agenda": "", "instinct": "", "secrets": [],
                                        "disposition": "neutral",
                                        "bond": 0, "bond_max": 4,
                                        "status": "active",
                                        "memory": [],
                                        "introduced": True,
                                        "aliases": paren_aliases,
                                        "importance_accumulator": 0,
                                        "last_reflection_scene": 0,
                                        "last_memory_scene": 0,
                                        "last_location": game.current_location or "",
                                    }
                                    game.npcs.append(stub)
                                else:
                                    log(f"[NPC] npc_details: stub skipped — '{new_name}' "
                                        f"already exists from new_npcs")
                                continue

                        log(f"[NPC] npc_details: treating '{old_name}' → '{new_name}' "
                            f"as identity reveal "
                            f"({'established, word-overlap confirmed' if is_established else 'no memories/agenda, stub reveal'})")
                        _merge_npc_identity(npc, new_name, game=game)
                        # Check if _process_new_npcs already created a duplicate NPC
                        # with this name earlier in the same metadata cycle
                        _absorb_duplicate_npc(game, npc, new_name)

            # Any name change (surname, title variant, reveal) may now collide with
            # another NPC that already carries this name - they are the same person.
            if new_name and _normalize_for_match(npc["name"]) == _normalize_for_match(new_name):
                _absorb_duplicate_npc(game, npc, npc["name"])

            # Replace description if provided (for significant narrative changes,
            # e.g. "combat pilot" → "retired mechanic" after character reveal)
            new_desc = d.get("description", "").strip()
            if new_desc:
                old_desc = npc.get("description", "")
                if _is_complete_description(new_desc) or not old_desc:
                    npc["description"] = new_desc
                    log(f"[NPC] Description updated for {npc['name']}: "
                        f"'{old_desc[:50]}' → '{new_desc[:50]}'")
                else:
                    log(f"[NPC] Rejected truncated description for {npc['name']}: "
                        f"'{new_desc[:60]}' — keeping existing")
            # Append additional details (legacy format, non-breaking)
            extra = d.get("details", "").strip()
            if extra and extra not in (npc.get("description") or ""):
                existing = npc.get("description", "")
                if existing:
                    npc["description"] = f"{existing}. {extra}"
                else:
                    npc["description"] = extra
                log(f"[NPC] Details enriched for {npc['name']}: {extra[:80]}")

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Failed to process npc_details: {e}", level="warning")


def _process_new_npcs(game, json_text: str):
    """Add newly discovered NPCs from narrator <new_npcs> metadata."""
    try:
        new_npcs = json.loads(json_text.strip())
        if not isinstance(new_npcs, list):
            return

        existing_names = {_normalize_for_match(n["name"]) for n in game.npcs}

        player_norm = _normalize_for_match(game.player_name)
        player_parts = set(player_norm.split())

        for nd in new_npcs:
            if not isinstance(nd, dict):
                continue
            nd["name"] = " ".join(str(nd.get("name") or "").split())
            if not _sanitize_npc_name(nd["name"])[0]:
                log("[NPC] Skipping new NPC with empty name", level="warning")
                continue
            name_norm = _normalize_for_match(nd["name"])

            # Skip player character (exact match OR any name part overlap)
            name_parts = set(name_norm.split())
            if name_norm == player_norm or (name_parts & player_parts):
                log(f"[NPC] Skipping player character from new_npcs: '{nd['name']}'")
                continue

            # Check if this NPC already exists (normalized name match, possibly background)
            if name_norm in existing_names:
                # Reactivate background/lore/deceased NPCs that reappear in narration
                existing = next((n for n in game.npcs
                                 if _normalize_for_match(n["name"]) == name_norm), None)
                if existing and existing.get("status") in ("background", "lore"):
                    _reactivate_npc(existing, reason="reappeared in new_npcs")
                elif existing and existing.get("status") == "deceased":
                    _reactivate_npc(existing, reason="resurrected — exact name in new_npcs",
                                    force=True)
                continue

            # Fuzzy match: check if this "new" NPC is actually a known NPC
            # under a different name (identity reveal, nickname, etc.)
            fuzzy_hit, match_type = _fuzzy_match_existing_npc(game, nd["name"])
            if fuzzy_hit:
                # Never merge into deceased NPCs — treat as genuinely new character
                if fuzzy_hit.get("status") == "deceased":
                    log(f"[NPC] Fuzzy matched '{nd['name']}' to deceased "
                        f"'{fuzzy_hit['name']}' — creating new NPC instead")
                    fuzzy_hit = None
                    # Fall through to description match / new NPC creation
                else:
                    if match_type == "stt_variant":
                        # STT transcription variant (Chan→Chen, Wang→Wong): do NOT rename.
                        # Add the variant as alias so future exact-matches catch it.
                        fuzzy_hit.setdefault("aliases", [])
                        variant = nd["name"].strip()
                        if _normalize_for_match(variant) not in {_normalize_for_match(a) for a in fuzzy_hit["aliases"]}:
                            fuzzy_hit["aliases"].append(variant)
                            log(f"[NPC] Added STT variant as alias: '{variant}' → '{fuzzy_hit['name']}'")
                        if fuzzy_hit.get("status") in ("background", "lore"):
                            _reactivate_npc(fuzzy_hit, reason="STT variant reappeared")
                    elif _is_title_only_difference(
                            _normalize_for_match(fuzzy_hit["name"]),
                            _normalize_for_match(nd["name"])):
                        # Title-only variant (e.g. "Dr. Eva" ↔ "Eva"): do NOT rename.
                        # Keep the more complete form as primary; add the other as alias.
                        hit_norm = _normalize_for_match(fuzzy_hit["name"])
                        inc_norm = _normalize_for_match(nd["name"])
                        titled = nd["name"] if len(inc_norm.split()) >= len(hit_norm.split()) else fuzzy_hit["name"]
                        bare   = fuzzy_hit["name"] if titled == nd["name"] else nd["name"]
                        fuzzy_hit["name"] = _cap_npc_name(titled)
                        fuzzy_hit.setdefault("aliases", [])
                        bare_norm = _normalize_for_match(bare)
                        existing_alias_norms = {_normalize_for_match(a) for a in fuzzy_hit["aliases"]}
                        if (bare_norm not in existing_alias_norms
                                and bare_norm != _normalize_for_match(titled)):
                            fuzzy_hit["aliases"].append(bare)
                        if fuzzy_hit.get("status") in ("background", "lore"):
                            _reactivate_npc(fuzzy_hit, reason="title variant reappeared")
                        log(f"[NPC] Title variant via fuzzy: primary='{titled}', alias='{bare}'")
                    else:
                        _merge_npc_identity(fuzzy_hit, nd["name"], nd.get("description", ""), game=game)
                    existing_names.add(name_norm)
                    continue

            # Description-based dedup: if fuzzy name match failed, check if the
            # new NPC's description closely matches an existing NPC's description.
            # Catches cases like "Sächsischer NVA-Kommandant" → "Hauptmann Rolf Ziegler"
            # where names share zero words but descriptions overlap heavily.
            new_desc = nd.get("description", "")
            if new_desc and len(new_desc) >= 10:
                desc_hit = _description_match_existing_npc(game, new_desc, name_norm)
                if desc_hit:
                    # Never merge into deceased NPCs
                    if desc_hit.get("status") == "deceased":
                        log(f"[NPC] Description matched '{nd['name']}' to deceased "
                            f"'{desc_hit['name']}' — creating new NPC instead")
                    else:
                        log(f"[NPC] Description-based dedup: '{nd['name']}' matches "
                            f"'{desc_hit['name']}' — treating as identity reveal")
                        _merge_npc_identity(desc_hit, nd["name"], new_desc, game=game)
                        existing_names.add(name_norm)
                        continue

            # Assign ID
            npc_id, _ = _next_npc_id(game)

            # Sanitize name: strip parenthetical annotations → aliases
            clean_name, paren_aliases = _sanitize_npc_name(nd["name"].strip())

            # Build full NPC entry with defaults
            npc = {
                "id": npc_id,
                "name": clean_name,
                "description": nd.get("description", "").strip(),
                "agenda": "",
                "instinct": "",
                "secrets": [],
                "disposition": _normalize_disposition(nd.get("disposition", "neutral")),
                "bond": 0,
                "bond_max": 4,
                "status": "active",
                "memory": [],
                "introduced": True,  # They appeared in narration
                "aliases": paren_aliases,
                "importance_accumulator": 0,
                "last_reflection_scene": 0,
                "last_memory_scene": 0,
                "last_location": game.current_location or "",
            }

            game.npcs.append(npc)
            existing_names.add(name_norm)
            log(f"[NPC] New mid-game NPC: {npc['name']} ({npc_id}, {npc['disposition']})")

            # Safety net: create seed memory so NPC is never hollow
            # (narrator may forget <memory_updates> for new NPCs)
            seed_event = nd.get("description", "") or f"{npc['name']} appeared"
            seed_emotion = _normalize_disposition(nd.get("disposition", "neutral"))
            # Map dispositions to plausible emotional_weights
            _disp_to_emotion = {
                "hostile": "hostile", "distrustful": "suspicious",
                "neutral": "neutral", "friendly": "curious", "loyal": "trusting",
            }
            seed_emotion = _disp_to_emotion.get(seed_emotion, "neutral")
            seed_imp, seed_debug = score_importance(seed_emotion, seed_event, debug=True)
            # Ensure at least importance 3 for a first appearance
            seed_imp = max(seed_imp, 3)
            npc["memory"].append({
                "scene": game.scene_count,
                "event": seed_event,
                "emotional_weight": seed_emotion,
                "importance": seed_imp,
                "type": "observation",
                "_score_debug": f"auto-seed from new_npcs | {seed_debug}",
            })

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Failed to process new NPCs: {e}", level="warning")


def _process_lore_npcs(game, lore_list: list):
    """Register historically/narratively significant figures that are never physically
    present in any scene. Lore NPCs collect memories and appear in a slim narrator
    context block, but are never activated as scene participants.

    Status 'lore' behaves like 'background' in all UI paths (sidebar, entity
    highlighting) so the transition lore → active (e.g. time-travel, resurrection)
    requires no UI changes — just _reactivate_npc().
    """
    player_norm = _normalize_for_match(game.player_name)

    for entry in lore_list:
        if not isinstance(entry, dict):
            continue
        entry["name"] = " ".join(str(entry.get("name") or "").split())
        if not _sanitize_npc_name(entry["name"])[0]:
            continue
        name_norm = _normalize_for_match(entry["name"])

        # Never register the player character
        if name_norm == player_norm or (set(name_norm.split()) & set(player_norm.split())):
            log(f"[NPC] Lore: skipping player character '{entry['name']}'")
            continue

        # Already known under any status? Update description if richer, done.
        existing = _find_npc(game, entry["name"])
        if existing:
            if not existing.get("description") and entry.get("description"):
                existing["description"] = entry["description"].strip()
                log(f"[NPC] Lore: enriched description for existing NPC '{existing['name']}'")
            else:
                log(f"[NPC] Lore: '{entry['name']}' already known as '{existing['name']}' "
                    f"({existing.get('status')}) — skipped")
            continue

        npc_id, _ = _next_npc_id(game)
        clean_name, paren_aliases = _sanitize_npc_name(entry["name"].strip())
        npc = {
            "id": npc_id,
            "name": clean_name,
            "description": entry.get("description", "").strip(),
            "agenda": "",
            "instinct": "",
            "secrets": [],
            "disposition": "neutral",
            "bond": 0,
            "bond_max": 4,
            "status": "lore",
            "memory": [],
            "introduced": True,
            "aliases": paren_aliases,
            "importance_accumulator": 0,
            "last_reflection_scene": 0,
            "last_memory_scene": 0,
            "last_location": "",
        }
        game.npcs.append(npc)
        log(f"[NPC] Lore figure registered: {clean_name} ({npc_id})")


def _retire_distant_npcs(game, max_active: int = MAX_ACTIVE_NPCS):
    """Demote NPCs to 'background' if the active list exceeds the threshold,
    OR if they have been silent (no memory updates) for NPC_STALE_SCENES scenes
    and have no bond with the player.

    Background NPCs remain visible in the sidebar but are excluded from
    AI prompts and NPC agency checks to keep token budgets manageable."""
    active = [n for n in game.npcs if n.get("status") == "active"]

    # Staleness path: retire NPCs that have been narratively silent for too long,
    # independent of the active-count threshold. Guards:
    #   - bond == 0 (bonded NPCs may return; don't prematurely background them)
    #   - not introduced this scene or the previous one (grace period for new NPCs)
    #   - last_memory_scene tracked (NPCs without it are legacy saves — skip)
    #   - scene_count > NPC_STALE_SCENES (can't be stale in early game)
    if game.scene_count > NPC_STALE_SCENES:
        for npc in active:
            if npc.get("bond", 0) > 0:
                continue
            last_mem = npc.get("last_memory_scene")
            if last_mem is None:
                # Legacy NPC without tracking — fall back to last memory entry
                last_mem = max(
                    (m.get("scene") or 0 for m in npc.get("memory", [])
                     if isinstance(m, dict)),
                    default=0
                ) or 0
            if last_mem == 0:
                continue  # No memories yet — newly introduced, protect
            # Protect NPCs who received any memory this scene — covers both
            # freshly-created NPCs (seed memories from _process_new_npcs bypass
            # last_memory_scene) and NPCs just reactivated by activate_npcs_for_prompt
            # that got an Extractor memory update this turn.
            has_current_scene_memory = any(
                isinstance(m, dict) and m.get("scene") == game.scene_count
                for m in npc.get("memory", [])
            )
            if has_current_scene_memory:
                continue
            scenes_silent = game.scene_count - last_mem
            if scenes_silent >= NPC_STALE_SCENES:
                npc["status"] = "background"
                log(f"[NPC] Demoted to background (stale): {npc['name']} "
                    f"({scenes_silent} scenes without memory update)")
        # Refresh active list after staleness demotions
        active = [n for n in game.npcs if n.get("status") == "active"]

    if len(active) <= max_active:
        return

    # Count-based path: if still over threshold, score and demote least relevant.
    # Score: last memory scene (recency) + bond weight + current-scene bonus
    def relevance(npc):
        last_scene = max(
            (m.get("scene") or 0 for m in npc.get("memory", []) if isinstance(m, dict)),
            default=0
        ) or 0
        score = last_scene + npc.get("bond", 0) * 3
        # Protect NPCs introduced this scene or with no memories yet
        # (newly discovered NPCs shouldn't be immediately retired)
        if not npc.get("memory") or last_scene >= game.scene_count:
            score += 1000
        return score

    active.sort(key=relevance)

    # Demote the least relevant NPCs beyond the threshold
    to_demote = len(active) - max_active
    for npc in active[:to_demote]:
        npc["status"] = "background"
        log(f"[NPC] Demoted to background: {npc['name']}")


def _reactivate_npc(npc: dict, reason: str = "", force: bool = False):
    """Promote a background (or deceased with force=True) NPC back to active status.
    force=True enables resurrection of deceased NPCs (exact name match in narration)."""
    if npc.get("status") == "deceased":
        if force:
            npc["status"] = "active"
            log(f"[NPC] Resurrected deceased NPC: {npc['name']} (reason: {reason})")
        else:
            log(f"[NPC] Refused reactivation of deceased NPC: {npc.get('name', '?')}")
        return
    if npc.get("status") in ("background", "lore"):
        npc["status"] = "active"
        log(f"[NPC] Reactivated: {npc['name']} (reason: {reason})")


# ===============================================================
# NPC MEMORY SYSTEM — Importance, Retrieval, Consolidation
# ===============================================================

def score_importance(emotional_weight: str, event_text: str = "",
                     debug: bool = False):
    """Score the importance of a memory entry (1-10).
    Uses emotional_weight as primary signal, with keyword boosts from event text.
    Handles compound phrases, snake_case, and German emotional words.
    If debug=True, returns (score, explanation_string) instead of just score."""
    raw = emotional_weight.lower().strip()
    debug_info = ""

    # Direct hit — fast path
    if raw in IMPORTANCE_MAP:
        base = IMPORTANCE_MAP[raw]
        debug_info = f"direct:{raw}={base}"
    else:
        # Split compound phrases into individual tokens
        tokens = re.split(r'[_/,;:\s]+|(?:\s+und\s+)|(?:\s+and\s+)|'
                          r'(?:\s+gemischt\s+mit\s+)|(?:\s+vermischt\s+mit\s+)|'
                          r'(?:\s+mixed\s+with\s+)', raw)
        tokens = [t.strip() for t in tokens if len(t.strip()) >= 3]

        best = 3  # default
        best_token = "default"
        for token in tokens:
            # Try direct match
            if token in IMPORTANCE_MAP:
                if IMPORTANCE_MAP[token] > best:
                    best = IMPORTANCE_MAP[token]
                    best_token = f"token:{token}={best}"
                continue
            # Try DE→EN mapping
            mapped = _EMOTION_DE_EN.get(token)
            if mapped and mapped in IMPORTANCE_MAP:
                if IMPORTANCE_MAP[mapped] > best:
                    best = IMPORTANCE_MAP[mapped]
                    best_token = f"de2en:{token}→{mapped}={best}"
        base = best
        debug_info = best_token

    # Keyword boost from event text
    if event_text:
        event_lower = event_text.lower()
        for min_score, keywords in IMPORTANCE_BOOST_KEYWORDS.items():
            matched_kw = [kw for kw in keywords if kw in event_lower]
            if matched_kw:
                if min_score > base:
                    debug_info += f"+event:{matched_kw[0]}≥{min_score}"
                base = max(base, min_score)
                break

    result = min(10, base)
    if debug:
        return result, debug_info
    return result


def retrieve_memories(npc: dict, context_text: str = "", max_count: int = 5,
                      current_scene: int = 0,
                      present_npc_ids: set = None) -> list[dict]:
    """Retrieve the most relevant memories for an NPC using weighted scoring.
    Score = 0.40 × recency + 0.35 × importance + 0.25 × relevance
    If present_npc_ids is given, memories about those NPCs get a relevance boost.
    Always includes at least 1 reflection if available."""
    memories = npc.get("memory", [])
    if not memories:
        return []

    # Separate reflections and observations
    reflections = [m for m in memories if m.get("type") == "reflection"]
    observations = [m for m in memories if m.get("type") != "reflection"]

    # Context words for relevance scoring
    context_words = set()
    if context_text:
        context_words = {w.lower() for w in context_text.split() if len(w) >= 3}
    _present = present_npc_ids or set()

    def _score_memory(mem):
        """Calculate retrieval score for a single memory."""
        # Recency: exponential decay based on scene gap
        mem_scene = mem.get("scene") or 0
        scene_gap = max(0, current_scene - mem_scene)
        # Reflections get a recency floor (they don't decay as fast)
        if mem.get("type") == "reflection":
            recency = max(0.6, MEMORY_RECENCY_DECAY ** scene_gap)
        else:
            recency = MEMORY_RECENCY_DECAY ** scene_gap

        # Importance: normalized 0-1 from 1-10 scale
        importance = mem.get("importance", 3) / 10.0

        # Relevance: word overlap with context
        relevance = 0.0
        if context_words:
            event_words = {w.lower() for w in mem.get("event", "").split() if len(w) >= 3}
            overlap = context_words & event_words
            if overlap:
                relevance = min(1.0, len(overlap) / max(3, len(context_words)) * 2)

        # NPC-relationship boost: if this memory is about an NPC present in the scene,
        # it becomes more relevant (they're right there — the NPC would think of it)
        if _present and mem.get("about_npc") in _present:
            relevance = min(1.0, relevance + 0.6)

        return 0.40 * recency + 0.35 * importance + 0.25 * relevance

    # Score all memories
    scored = [(m, _score_memory(m)) for m in memories]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Ensure at least 1 reflection if available
    result = []
    reflection_included = False
    for mem, score in scored:
        if len(result) >= max_count:
            break
        result.append(mem)
        if mem.get("type") == "reflection":
            reflection_included = True

    # If no reflection was included but reflections exist, swap lowest-scored entry
    if not reflection_included and reflections and result:
        best_ref = max(reflections, key=lambda m: m.get("importance", 5))
        # Replace lowest-scored non-reflection if it scores lower
        worst_idx = len(result) - 1
        if result[worst_idx].get("type") != "reflection":
            result[worst_idx] = best_ref

    return result


def _consolidate_memory(npc: dict):
    """Intelligent memory consolidation replacing simple FIFO.
    Keeps: all reflections (max MAX_NPC_REFLECTIONS, newest) +
           observations sorted by importance then recency (max MAX_NPC_OBSERVATIONS).
    Total never exceeds MAX_NPC_MEMORY_ENTRIES."""
    memories = npc.get("memory", [])
    if len(memories) <= MAX_NPC_MEMORY_ENTRIES:
        return  # No consolidation needed

    reflections = [m for m in memories if m.get("type") == "reflection"]
    observations = [m for m in memories if m.get("type") != "reflection"]

    # Keep newest reflections up to limit
    kept_reflections = reflections[-MAX_NPC_REFLECTIONS:]

    # Budget for observations
    obs_budget = MAX_NPC_MEMORY_ENTRIES - len(kept_reflections)

    if len(observations) <= obs_budget:
        kept_observations = observations
    else:
        # Keep a mix: newest + highest importance
        # Split budget: 60% by recency, 40% by importance
        recency_budget = max(3, int(obs_budget * 0.6))
        importance_budget = obs_budget - recency_budget

        # Newest observations
        by_recency = sorted(observations, key=lambda m: m.get("scene") or 0, reverse=True)
        kept_by_recency = by_recency[:recency_budget]

        # Highest importance (excluding already kept)
        kept_ids = {id(m) for m in kept_by_recency}
        remaining = [m for m in observations if id(m) not in kept_ids]
        by_importance = sorted(remaining, key=lambda m: m.get("importance", 3), reverse=True)
        kept_by_importance = by_importance[:importance_budget]

        kept_observations = kept_by_recency + kept_by_importance

    # Combine and sort chronologically
    all_kept = kept_reflections + kept_observations
    all_kept.sort(key=lambda m: m.get("scene", 0) or 0)

    npc["memory"] = all_kept
    removed = len(memories) - len(all_kept)
    if removed > 0:
        log(f"[NPC] Consolidated {npc.get('name', '?')} memory: "
            f"{len(memories)} → {len(all_kept)} ({removed} removed, "
            f"{len(kept_reflections)} reflections, {len(kept_observations)} observations)")


# --- Stopwords (DE+EN) for NPC description comparison ---
# Used by _description_match_existing_npc() for duplicate detection.
_STOPWORDS: frozenset = frozenset()
if _HAS_STOP_WORDS_LIB:
    try:
        _STOPWORDS = frozenset(_lib_get_stop_words("de")) | frozenset(_lib_get_stop_words("en"))
    except Exception:
        pass
if not _STOPWORDS:
    _STOPWORDS = frozenset({
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "einem",
        "einen", "eines", "mit", "und", "oder", "für", "von", "vor", "bei", "aus",
        "auf", "nach", "über", "unter", "aber", "als", "wie", "nicht", "sich",
        "ist", "sind", "hat", "war", "wird", "kann", "sein", "ihre", "ihr",
        "noch", "nur", "auch", "schon", "sehr", "dann", "wenn", "dass",
        "the", "and", "for", "with", "from", "that", "this", "was", "are",
        "has", "had", "not", "but", "his", "her", "its", "who", "whom",
        "will", "can", "may", "been", "were", "into", "than", "then",
    })


# --- Cyrillic homoglyph replacement (LLMs occasionally mix Cyrillic lookalikes) ---
_CYRILLIC_TO_LATIN = str.maketrans({
    '\u0410': 'A', '\u0430': 'a',   # А/а
    '\u0412': 'B',                    # В
    '\u0415': 'E', '\u0435': 'e',   # Е/е
    '\u041A': 'K', '\u043A': 'k',   # К/к
    '\u041C': 'M', '\u043C': 'm',   # М/м
    '\u041D': 'H',                    # Н
    '\u041E': 'O', '\u043E': 'o',   # О/о
    '\u0420': 'P', '\u0440': 'p',   # Р/р
    '\u0421': 'C', '\u0441': 'c',   # С/с
    '\u0422': 'T', '\u0442': 't',   # Т/т
    '\u0423': 'Y', '\u0443': 'y',   # У/у
    '\u0425': 'X', '\u0445': 'x',   # Х/х
})
_CYRILLIC_RANGE = range(0x0400, 0x0500)  # Unicode Cyrillic block
_LATIN_RANGES = (range(0x0041, 0x005B), range(0x0061, 0x007B),  # Basic Latin A-Z, a-z
                 range(0x00C0, 0x0250))  # Latin Extended (ä, ö, ü, etc.)

def _is_cyrillic(ch: str) -> bool:
    return ord(ch) in _CYRILLIC_RANGE

def _is_latin(ch: str) -> bool:
    cp = ord(ch)
    return any(cp in r for r in _LATIN_RANGES)

def _fix_cyrillic_homoglyphs(text: str) -> str:
    """Context-aware replacement of Cyrillic lookalike characters in Latin text.
    Only replaces Cyrillic homoglyphs in MIXED-SCRIPT words (words containing both
    Latin and Cyrillic characters). Purely Cyrillic words (authentic Russian, Ukrainian,
    etc.) are left untouched. This handles:
    - 'kniест' (mixed Latin+Cyrillic) → 'kniest' (fixed)
    - 'Товарищ' (pure Cyrillic) → 'Товарищ' (untouched)
    - 'Der Солдат murmelte' → 'Der Солдат murmelte' (Cyrillic word preserved)
    """
    # Fast path: no Cyrillic characters at all
    if not any(_is_cyrillic(ch) for ch in text):
        return text

    result = []
    i = 0
    while i < len(text):
        # Collect a "word" (contiguous letters)
        if text[i].isalpha():
            word_start = i
            while i < len(text) and text[i].isalpha():
                i += 1
            word = text[word_start:i]
            # Check if this word has BOTH Latin and Cyrillic characters
            has_latin = any(_is_latin(ch) for ch in word)
            has_cyrillic = any(_is_cyrillic(ch) for ch in word)
            if has_latin and has_cyrillic:
                # Mixed-script word: replace Cyrillic homoglyphs with Latin
                result.append(word.translate(_CYRILLIC_TO_LATIN))
            else:
                # Pure Latin or pure Cyrillic: leave untouched
                result.append(word)
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


# --- TF-IDF NPC relevance scoring (zero-dependency implementation) ---
# Replaces keyword-based activation. TF-IDF automatically weights rare/distinctive
# words higher (proper nouns > common words), works across all languages.

def _compute_npc_tfidf_scores(npcs: list, query_text: str) -> dict[str, float]:
    """Compute TF-IDF cosine similarity between query text and each NPC profile.
    Returns {npc_id: similarity_score} with scores 0.0–1.0.
    Zero external dependencies — uses basic term frequency × inverse document frequency."""
    from collections import Counter

    def _tokenize(text: str) -> list[str]:
        return [w.lower().strip(".,;:!?\"'()-—–") for w in text.split()
                if len(w.strip(".,;:!?\"'()-—–")) >= 3]

    # Build NPC profile texts from all available identity + context signals
    profiles: dict[str, list[str]] = {}
    for npc in npcs:
        if npc.get("status") not in ("active", "background"):
            continue
        npc_id = npc.get("id", "")
        if not npc_id:
            continue
        parts = [
            npc.get("name", ""),
            " ".join(npc.get("aliases", [])),
            npc.get("description", ""),
            npc.get("agenda", ""),
        ]
        # Recent memories (last 5 observations) — captures evolving context
        for m in npc.get("memory", [])[-5:]:
            if isinstance(m, dict) and m.get("type") != "reflection":
                parts.append(m.get("event", ""))
        profiles[npc_id] = _tokenize(" ".join(parts))

    if not profiles:
        return {}

    # Tokenize query
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return {npc_id: 0.0 for npc_id in profiles}

    # Compute IDF across all documents (NPC profiles + query)
    all_docs = list(profiles.values()) + [query_tokens]
    n_docs = len(all_docs)
    doc_freq: dict[str, int] = {}
    for tokens in all_docs:
        for word in set(tokens):
            doc_freq[word] = doc_freq.get(word, 0) + 1
    idf = {word: math.log(n_docs / count) for word, count in doc_freq.items()}

    # TF-IDF vector + cosine similarity
    def _tfidf_vec(tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        total = len(tokens) or 1
        return {w: (c / total) * idf.get(w, 0) for w, c in tf.items()}

    def _cosine(a: dict, b: dict) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[w] * b[w] for w in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    q_vec = _tfidf_vec(query_tokens)
    return {npc_id: _cosine(q_vec, _tfidf_vec(tokens))
            for npc_id, tokens in profiles.items()}


def _ensure_npc_memory_fields(npc: dict):
    """Ensure NPC has all memory system fields (migration + new NPC creation)."""
    npc.setdefault("memory", [])
    npc.setdefault("importance_accumulator", 0)
    npc.setdefault("last_reflection_scene", 0)
    npc.setdefault("last_memory_scene", 0)   # Scene of last memory update (staleness tracking)
    npc.setdefault("last_location", "")  # Where NPC was last seen (spatial consistency)
    npc.setdefault("arc", "")           # Narrative trajectory — set by Director, evolves each reflection
    npc.setdefault("absent_until_scene", 0)  # Scene until which activation is suppressed (exit tracking)
    # Migrate existing memories: add importance and type if missing
    for m in npc["memory"]:
        if isinstance(m, dict):
            if "importance" not in m:
                m["importance"] = score_importance(
                    m.get("emotional_weight", "neutral"),
                    m.get("event", "")
                )
            if "type" not in m:
                m["type"] = "observation"


# ===============================================================
# NPC TF-IDF CONTEXT ACTIVATION
# ===============================================================

def activate_npcs_for_prompt(game, brain: dict, player_input: str) -> tuple[list[dict], list[dict], dict]:
    """Decide which NPCs get full context vs name-only mention in narrator prompt.
    Returns (activated_npcs, mentioned_npcs, activation_debug).
    activated = full context (memories, secrets, agenda)
    mentioned = name + disposition only
    activation_debug = {npc_name: {score, reasons, status}} for diagnostics"""
    target_id = brain.get("target_npc")

    # Build scan text from all available context
    # Use `or ""` pattern: brain.get(k, "") returns None when key exists with null value
    scan_parts = [
        player_input,
        brain.get("player_intent") or "",
        brain.get("approach") or "",
        game.current_scene_context or "",
        game.current_location or "",
    ]
    # Last 2 session log entries
    for s in game.session_log[-2:]:
        scan_parts.append(s.get("summary", ""))
    scan_text = " ".join(scan_parts).lower()

    # Compute TF-IDF similarity between scene context and each NPC profile (once)
    tfidf_scores = _compute_npc_tfidf_scores(game.npcs, scan_text)

    activated = []
    mentioned = []
    activation_debug = {}

    for npc in game.npcs:
        if npc.get("status") not in ("active", "background"):
            continue

        score = 0.0
        reasons = []
        npc_name = npc.get("name", "")
        npc_name_lower = npc_name.lower()

        # 1. Direct target from Brain (highest priority)
        if target_id and (npc.get("id") == target_id or npc_name_lower == target_id.lower()):
            score += 1.0
            reasons.append("target")

        # 2. Name mentioned in scan text
        if npc_name_lower in scan_text:
            score += 0.8
            reasons.append("name")
        else:
            # Check name parts (e.g. "Borin" in "Ich frage Borin")
            # Min-length 4 matches the exit-suppression check (line ~2570) and
            # avoids German articles/prepositions of length 3 ("der", "die", "von")
            # producing spurious activation scores.
            for part in npc_name_lower.split():
                if len(part) >= 4 and part in scan_text:
                    score += 0.6
                    reasons.append(f"part:{part}")
                    break

        # 3. Alias mentioned
        for alias in npc.get("aliases", []):
            if alias.lower() in scan_text:
                score += 0.7
                reasons.append(f"alias:{alias}")
                break

        # 4. TF-IDF content similarity (replaces keyword overlap)
        tfidf = tfidf_scores.get(npc.get("id", ""), 0.0)
        if tfidf > 0.05:  # Noise threshold
            tfidf_contrib = min(0.5, tfidf * 1.5)
            score += tfidf_contrib
            reasons.append(f"tfidf:{tfidf:.2f}")

        # 5. Location match
        npc_desc = (npc.get("description", "") + " " + npc.get("agenda", "")).lower()
        if game.current_location and game.current_location.lower() in npc_desc:
            score += 0.3
            reasons.append("location")

        # 6. Recent interaction bonus
        recent_scenes = [m.get("scene") or 0 for m in npc.get("memory", [])[-3:] if isinstance(m, dict)]
        if recent_scenes and max(recent_scenes) >= game.scene_count - 2:
            score += 0.2
            reasons.append("recent")

        # 7. Exit suppression: NPC physically departed the previous scene.
        # Suppress activation unless the player explicitly references them by name
        # (in player_input or brain intent — not in session_log summaries which always
        # contain NPC names and would otherwise cancel the suppression every turn).
        absent_until = npc.get("absent_until_scene", 0)
        if absent_until > game.scene_count:
            # Check for explicit reference in player input + brain intent only.
            # Name-parts check mirrors step-2 part: logic but uses min-length 4 (not 3)
            # to avoid common articles/prepositions ("der", "die", "von") clearing the flag.
            explicit_text = (player_input + " " + (brain.get("player_intent") or "")).lower()
            # is_target mirrors step-1 scoring: accepts both npc_id AND name string,
            # because Brain may return either format in the target_npc field.
            is_target = bool(target_id and (
                npc.get("id") == target_id
                or npc_name_lower == target_id.lower()
            ))
            explicitly_named = (
                npc_name_lower in explicit_text
                or any(len(part) >= 4 and part in explicit_text
                       for part in npc_name_lower.split())
                or any(alias.lower() in explicit_text
                       for alias in npc.get("aliases", []))
            )
            if is_target or explicitly_named:
                # NPC has returned — clear suppression flag
                npc["absent_until_scene"] = 0
                reasons.append("returned")
            else:
                # Hard suppression: force score to 0 so the NPC is neither
                # activated nor mentioned. A score > 0 could still land at
                # NPC_MENTION_THRESHOLD (0.3), putting the NPC in _scene_present_ids
                # and allowing the Extractor to write phantom memories.
                score = 0.0
                reasons.append("suppressed:absent")

        # Classify
        if score >= NPC_ACTIVATION_THRESHOLD:
            activated.append(npc)
            activation_debug[npc_name] = {"score": round(score, 2), "reasons": reasons, "status": "activated"}
            # Auto-reactivate background NPCs that are contextually relevant
            if npc.get("status") == "background":
                _reactivate_npc(npc, reason=f"context activation (score={score:.2f})")
        elif score >= NPC_MENTION_THRESHOLD:
            mentioned.append(npc)
            activation_debug[npc_name] = {"score": round(score, 2), "reasons": reasons, "status": "mentioned"}
        elif reasons:
            # Below threshold but had some signal — log for diagnostics
            activation_debug[npc_name] = {"score": round(score, 2), "reasons": reasons, "status": "inactive"}

    # Hard limit: max MAX_ACTIVATED_NPCS fully activated (beyond target)
    if len(activated) > MAX_ACTIVATED_NPCS:
        # Target NPC always stays, sort rest by relevance
        target_npc = _find_npc(game, target_id) if target_id else None
        non_target = [n for n in activated if n is not target_npc]
        # Keep target + top N-1 by bond/recency
        non_target.sort(key=lambda n: n.get("bond", 0), reverse=True)
        overflow = non_target[MAX_ACTIVATED_NPCS - (1 if target_npc else 0):]
        activated = [n for n in activated if n not in overflow]
        mentioned.extend(overflow)  # Demoted to mentioned

    # Recursive activation: if an activated NPC's secrets/agenda reference another NPC
    secondary_activated = []
    for npc in activated:
        ref_text = " ".join(npc.get("secrets", [])) + " " + npc.get("agenda", "")
        if ref_text.strip():
            for other in game.npcs:
                if other in activated or other in mentioned or other in secondary_activated:
                    continue
                if other.get("status") not in ("active", "background"):
                    continue
                # Respect exit suppression — don't resurrect a departed NPC via agenda references
                if other.get("absent_until_scene", 0) > game.scene_count:
                    continue
                other_name = other.get("name", "").lower()
                if other_name and other_name in ref_text.lower():
                    secondary_activated.append(other)
                    if len(secondary_activated) >= 1:  # Max 1 recursive
                        break
        if secondary_activated:
            break

    mentioned.extend(secondary_activated)

    log(f"[NPC Activation] Activated: {[n['name'] for n in activated]}, "
        f"Mentioned: {[n['name'] for n in mentioned]}")

    return activated, mentioned, activation_debug


# --- Kishōtenketsu tone mapping ---
# Probability of selecting Kishōtenketsu 4-act structure per tone
KISHOTENKETSU_PROBABILITY = {
    # Kishōtenketsu-preferred (70%)
    "melancholic": 0.70,
    "cozy": 0.70,
    "romantic": 0.70,
    "cheerful_funny": 0.70,
    "slice_of_life_90s": 0.70,
    "fairy_tale": 0.70,
    # Neutral (40%)
    "tragicomic": 0.40,
    "grounded_drama": 0.40,
    "absurd_grotesque": 0.40,
    # 3-Act preferred (15%)
    "dark_gritty": 0.15,
    "epic_heroic": 0.15,
    "slow_burn_horror": 0.15,
    "pulp": 0.15,
    "slapstick": 0.15,
}
KISHOTENKETSU_DEFAULT_PROBABILITY = 0.50  # For custom tones and "surprise"

# Chaos interrupt types
CHAOS_INTERRUPT_TYPES = [
    # Original 4
    "npc_unexpected",      # NPC shows up or acts against expectation
    "threat_escalation",   # A danger escalates or new threat emerges
    "twist",               # Something contradicts what was believed true
    "discovery",           # Unexpected clue, item, or revelation
    # Solo RPG literature (Mythic GME, Ironsworn/Starforged)
    "environment_shift",   # Environment changes dramatically (weather, collapse, phenomenon)
    "remote_event",        # News/signs of important events happening elsewhere
    "positive_windfall",   # Unexpected good fortune or lucky break
    "callback",            # A past action or decision has unexpected consequences now
    # Screenwriting theory (McKee, Aristotle, Snyder)
    "dilemma",             # Forced choice between competing values — no clean option
    "ticking_clock",       # Sudden time pressure or deadline changes the dynamic
]

# LANGUAGES is imported from i18n.py

# --- Character Creation Options -------
# GENRES, TONES, ARCHETYPES are now in i18n.py


def load_global_config() -> dict:
    """Load global server config (api_key, invite_code, enable_https, etc.)."""
    if GLOBAL_CONFIG_FILE.exists():
        try:
            return json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_global_config(cfg: dict):
    """Merge and save global config. Existing keys are preserved, passed keys are updated.
    Restricts file permissions to owner-only.
    """
    try:
        existing = load_global_config()
        existing.update(cfg)
        _atomic_write_text(GLOBAL_CONFIG_FILE, json.dumps(existing, indent=2, ensure_ascii=False))
        # Restrict permissions: owner read/write only (no group/others)
        try:
            import stat
            GLOBAL_CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except OSError:
            pass  # Windows doesn't support Unix permissions — skip silently
    except OSError:
        pass



def load_user_config(username: str) -> dict:
    """Load per-user settings (TTS, language, kid mode, etc.).
    Checks settings.json first, falls back to legacy config.json for backward compat.
    """
    cfg_file = _get_user_config_file(username)
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Backward compat: try legacy config.json
    legacy_file = _get_legacy_user_config_file(username)
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            # Migrate: write to new location, remove old file
            try:
                cfg_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                legacy_file.unlink()
                log(f"[Config] Migrated {username}/config.json → settings.json")
            except OSError:
                pass
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_user_config(username: str, cfg: dict):
    """Save per-user settings to settings.json."""
    cfg_file = _get_user_config_file(username)
    try:
        _atomic_write_text(cfg_file, json.dumps(cfg, indent=2, ensure_ascii=False))
    except OSError:
        pass


# ---------------------------------------------------------------
# USER MANAGEMENT
# ---------------------------------------------------------------

def list_users() -> list[dict]:
    """List all users. Returns list of dicts with 'name'."""
    users = []
    if USERS_DIR.exists():
        for p in sorted(USERS_DIR.iterdir()):
            if p.is_dir():
                users.append({"name": p.name})
    return users


def create_user(name: str) -> bool:
    """Create a new user directory with metadata.
    Returns False if the user already exists or the name is not a safe directory name."""
    if not is_valid_username(name):
        log(f"[User] Rejected invalid user name: {name!r}", level="warning")
        return False
    user_dir = _get_user_dir(name)
    if user_dir.exists():
        return False
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "saves").mkdir(exist_ok=True)
    meta = {"created": datetime.now().isoformat()}
    (user_dir / "user.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    log(f"[User] Created user: {name}")
    return True


def delete_user(name: str) -> bool:
    """Delete a user and all their data."""
    if not is_valid_username(name):
        log(f"[User] Refusing to delete invalid user name: {name!r}", level="warning")
        return False
    user_dir = _get_user_dir(name)
    if not user_dir.exists() or user_dir.resolve().parent != USERS_DIR.resolve():
        return False
    import shutil
    shutil.rmtree(user_dir)
    log(f"[User] Deleted user: {name}")
    return True


# ===============================================================
# ENGINE CONFIGURATION (replaces st.session_state for settings)
# ===============================================================

@dataclass
class EngineConfig:
    """Runtime configuration passed to engine functions.
    Replaces st.session_state lookups for narration_lang, kid_friendly, etc.
    The UI layer populates this from its own state management.
    """
    narration_lang: str = "Deutsch"   # Display label (key into LANGUAGES dict)
    kid_friendly: bool = False

# ===============================================================
# DATA MODELS
# ===============================================================

@dataclass
class GameState:
    player_name: str = "Namenlos"
    character_concept: str = ""
    setting_genre: str = ""
    setting_tone: str = ""
    setting_archetype: str = ""
    setting_description: str = ""
    edge: int = 1
    heart: int = 2
    iron: int = 1
    shadow: int = 1
    wits: int = 2
    health: int = 5
    spirit: int = 5
    supply: int = 5
    momentum: int = 2
    max_momentum: int = 10
    scene_count: int = 0
    current_location: str = ""
    current_scene_context: str = ""
    npcs: list = field(default_factory=list)
    clocks: list = field(default_factory=list)
    session_log: list = field(default_factory=list)
    narration_history: list = field(default_factory=list)  # Last N narrations for context
    story_blueprint: dict = field(default_factory=dict)  # Story arc structure
    crisis_mode: bool = False
    game_over: bool = False
    # v5.0: Narrative depth systems
    chaos_factor: int = 5          # 3-9, dynamic tension regulator
    scene_intensity_history: list = field(default_factory=list)  # Last 5: "action"/"breather"/"interrupt"
    # v5.3: Campaign mode
    campaign_history: list = field(default_factory=list)  # Summaries of past chapters
    chapter_number: int = 1
    # v5.7: Content boundaries & wishes
    player_wishes: str = ""    # Per-game: what player wants in the story
    content_lines: str = ""    # Per-game: hard content exclusions (Lines)
    # v5.8: Temporal & spatial consistency
    time_of_day: str = ""      # Coarse time: "early_morning","morning","midday","afternoon","evening","late_evening","night","deep_night"
    time_unchanged_scenes: int = 0   # Transient: scenes elapsed without a time_of_day change (not persisted)
    location_history: list = field(default_factory=list)  # Last 3 locations for continuity
    scenes_at_location: int = 0      # Scenes played at current_location since the last real move
    # v5.9: Epilogue system
    epilogue_shown: bool = False      # True after epilogue has been generated
    epilogue_dismissed: bool = False   # True if player chose "continue playing" instead of epilogue
    epilogue_text: str = ""           # Persisted: epilogue prose kept on disk so it survives ui.navigate.reload() between epilogue generation and new-chapter start; cleared by start_new_chapter() after use
    # v5.10: Backstory (canon past, preserved raw player input)
    backstory: str = ""        # Raw player-authored backstory — canon facts, NOT plot seeds
    # v5.11: Director guidance (stored between turns)
    director_guidance: dict = field(default_factory=dict)  # Last DirectorGuidance output
    # Persisted in SAVE_FIELDS. Full pre-turn snapshot for ## correction flow.
    # Allows one correction after reload (e.g. after accidental disconnect).
    last_turn_snapshot: Optional[dict] = field(default=None, repr=False)
    # Engine versions this save has been played with (oldest first). Carried in the
    # GameState so save_game() never has to re-read the previous save file.
    version_history: list = field(default_factory=list)
    # Co-op (Co-GM) mode: open question, pending answer, cockpit signals, planted
    # seeds. Persisted so seeds and long-running signals survive pauses, reloads and
    # chapters. Deliberately NOT part of the turn snapshot spec: the Co-GM edits it
    # live while turns run; the inputs a turn consumed are stored separately in
    # last_turn_snapshot["coop_inputs"]. See the CO-OP section.
    coop: dict = field(default_factory=dict)

    def get_stat(self, name: str) -> int:
        return getattr(self, name, 0)


@dataclass
class RollResult:
    d1: int; d2: int; c1: int; c2: int
    stat_name: str; stat_value: int; action_score: int
    result: str; move: str; match: bool = False


# ===============================================================
# CHAOS FACTOR SYSTEM
# ===============================================================

# Probability that a STRONG_HIT lowers the chaos factor by one. Strict Mythic
# lowers it on every success, which pins chaos at the minimum (0% interrupt
# chance) after two or three strong hits and drains tension from successful runs.
CHAOS_STRONG_HIT_DROP_CHANCE = 0.5


def update_chaos_factor(game: GameState, result: str):
    """Adjust chaos factor based on roll result.
    MISS: +1 (max 9). STRONG_HIT: -1 (min 3) with CHAOS_STRONG_HIT_DROP_CHANCE.
    WEAK_HIT: no change."""
    if result == "MISS":
        game.chaos_factor = min(9, game.chaos_factor + 1)
    elif result == "STRONG_HIT":
        if game.chaos_factor > 3 and random.random() < CHAOS_STRONG_HIT_DROP_CHANCE:
            game.chaos_factor -= 1


def check_chaos_interrupt(game: GameState) -> Optional[str]:
    """Roll against chaos factor to see if a scene interrupt triggers.
    Returns interrupt type string or None.
    Probability: d10 <= (chaos - 3), so chaos 3=0%, 4=10%, 5=20%, ... 9=60%
    """
    threshold = game.chaos_factor - 3
    if threshold <= 0:
        return None
    roll = random.randint(1, 10)
    if roll <= threshold:
        # Interrupt triggered -- reduce chaos by 1 (tension released)
        game.chaos_factor = max(3, game.chaos_factor - 1)
        return random.choice(CHAOS_INTERRUPT_TYPES)
    return None


# ===============================================================
# TEMPORAL & SPATIAL CONSISTENCY (v5.8)
# ===============================================================

TIME_PHASES = ["early_morning", "morning", "midday", "afternoon",
               "evening", "late_evening", "night", "deep_night"]
# A single Extractor time_update may move at most this many phases forward
# (wrapping past midnight). Larger jumps are 1-3 phases BACKWARD in disguise
# (e.g. deep_night → late_evening) and are rejected.
TIME_MAX_FORWARD_STEPS = 4
# After this many scenes without any time change, the engine advances one phase
# itself — time passes even when neither Brain nor Extractor notices it. Must be
# above TIME_STALE_THRESHOLD so the Narrator gets a chance to show it first.
TIME_AUTO_ADVANCE_SCENES = 7


def _is_forward_time(old: str, new: str) -> bool:
    """True if `new` lies 1..TIME_MAX_FORWARD_STEPS phases after `old` (cyclic).
    Unknown/empty old values accept any phase."""
    if old not in TIME_PHASES or new not in TIME_PHASES:
        return new in TIME_PHASES
    step = (TIME_PHASES.index(new) - TIME_PHASES.index(old)) % len(TIME_PHASES)
    return 1 <= step <= TIME_MAX_FORWARD_STEPS

# Scenes without a time_of_day change before stale-time nudges activate in the
# Narrator prompt and Director context.  Chosen to be earlier than the Elvira
# violation threshold (10) so the engine self-corrects before the warning fires.
TIME_STALE_THRESHOLD = 5

# Scenes at the same location before the Narrator is asked to open a natural path
# elsewhere and the Director gets a LOCATION RULE. The player still decides
# whether to move — the engine never relocates the character on its own.
LOCATION_STALE_THRESHOLD = 5

# TIME_LABELS (display) are now in i18n.py


def advance_time(game: GameState, progression: str):
    """Advance time_of_day based on Brain's time_progression assessment.
    Does nothing if time_of_day is unset (Narrator hasn't established it yet)."""
    if not game.time_of_day or progression in ("none", "short"):
        return
    try:
        idx = TIME_PHASES.index(game.time_of_day)
    except ValueError:
        return
    steps = {"moderate": 1, "long": 2}.get(progression, 0)
    if steps:
        new_idx = idx + steps
        # Wrap around: deep_night -> early_morning (new day)
        if new_idx >= len(TIME_PHASES):
            new_idx = new_idx - len(TIME_PHASES)
        game.time_of_day = TIME_PHASES[new_idx]
        game.time_unchanged_scenes = 0  # Brain-driven time advance counts as a reset


def _locations_match(loc_a: str, loc_b: str) -> bool:
    """Fuzzy location equality: two location strings are considered the same place
    if one's significant word-set is a subset of the other's.
    Handles AI-appended suffixes like 'Serges Heim in Lyon' vs 'Serges Heim',
    underscore variants, and minor word-order differences.
    Empty strings are treated as 'unknown / possibly here' → always True
    (backward-compat: NPCs without last_location are never wrongly excluded).
    Single-significant-word check uses prefix matching, not subset, to prevent
    a bare city name ('Lyon') from matching any location that mentions the city
    ('Serges Heim in Lyon', 'Gefängnis in Lyon')."""
    if not loc_a or not loc_b:
        return True
    # Stopwords to ignore when comparing (common in German & English location strings)
    _STOP = {"in", "im", "an", "am", "auf", "bei", "vor", "der", "die", "das",
              "des", "dem", "den", "von", "the", "of", "at", "in", "near"}
    def _wordlist(s: str) -> list:
        return [w.strip(".,;:!?\"'()").lower().replace("_", " ")
                for w in s.split()
                if w.strip(".,;:!?\"'()").lower() not in _STOP]
    wa, wb = _wordlist(loc_a), _wordlist(loc_b)
    if not wa or not wb:
        return True
    # Multi-word: subset check (shorter ⊆ longer)
    shorter, longer = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(shorter) >= 2:
        return set(shorter).issubset(set(longer))
    # Single significant word: only match if it's a left-aligned prefix of the longer.
    # 'Hintergasse' matches 'Hintergasse in Lyon' (prefix) but
    # 'Lyon' does NOT match 'Serges Heim in Lyon' (suffix/qualifier, not prefix).
    return shorter[0] == longer[0]


def _short_location_name(name: str) -> str:
    """Reduce a location to a short label. Models sometimes return a full
    description ("Colter-Zentrum, ein privates Büro in … — versteckt hinter …");
    such strings break scene markers and the fuzzy location matching.
    Cuts at the first descriptive separator once the name exceeds LOCATION_MAX_CHARS."""
    name = (name or "").replace("_", " ").strip()
    if len(name) <= LOCATION_MAX_CHARS:
        return name
    for sep in (" — ", " – ", " - ", ", ", "; ", " (", ": "):
        idx = name.find(sep)
        if 3 <= idx:
            name = name[:idx].strip()
            if len(name) <= LOCATION_MAX_CHARS:
                return name
    cut = name[:LOCATION_MAX_CHARS].rfind(" ")
    return (name[:cut] if cut > 3 else name[:LOCATION_MAX_CHARS]).rstrip(" ,;:—–-")


def update_location(game: GameState, new_location: str):
    """Update current location and maintain location history."""
    if not new_location:
        return
    # AI sometimes returns underscores instead of spaces / full descriptions
    new_location = _short_location_name(new_location)
    if not new_location or new_location == game.current_location:
        return
    # Skip if new_location is just a qualifier variant of the current location
    # (e.g. 'Serges Heim in Lyon' when current is 'Serges Heim' — no real move).
    # Prevents AI-appended city suffixes from overwriting the canonical name.
    if game.current_location and _locations_match(new_location, game.current_location):
        return
    if game.current_location:
        # Dedup: if current location is a fuzzy match of the last history entry,
        # replace it instead of appending (prevents drift variants and near-duplicates
        # like "Janas Büro" + "Janas privates Büro" both accumulating in history).
        if game.location_history and _locations_match(game.current_location, game.location_history[-1]):
            game.location_history[-1] = game.current_location
        else:
            game.location_history.append(game.current_location)
        game.location_history = game.location_history[-5:]
    game.current_location = new_location
    game.scenes_at_location = 0


def _apply_brain_location_time(game: GameState, brain: dict):
    """Apply location change and time progression from Brain results.
    Called before Narrator to update state for the prompt."""
    # AI sometimes returns string "null" instead of JSON null; guard against both
    loc = brain.get("location_change")
    if loc and loc != "null":
        update_location(game, loc)
    advance_time(game, brain.get("time_progression", "none"))


# ===============================================================
# SCENE / SEQUEL PACING SYSTEM
# ===============================================================

def get_pacing_hint(game: GameState) -> str:
    """Analyze recent scene intensity and suggest pacing.
    Returns 'action', 'breather', or 'neutral'.
    """
    history = game.scene_intensity_history[-5:]
    if not history:
        return "neutral"

    # Count consecutive action/interrupt scenes at the end
    consecutive_intense = 0
    for h in reversed(history):
        if h in ("action", "interrupt"):
            consecutive_intense += 1
        else:
            break

    # After 3+ intense scenes, suggest a breather
    if consecutive_intense >= 3:
        return "breather"
    # After 2+ breather scenes, nudge toward action
    consecutive_calm = 0
    for h in reversed(history):
        if h == "breather":
            consecutive_calm += 1
        else:
            break
    if consecutive_calm >= 2:
        return "action"
    return "neutral"


# ---------------------------------------------------------------
# TURN SNAPSHOT — single source of truth
# ---------------------------------------------------------------
# Every turn-mutable GameState field is listed exactly ONCE here. The snapshot
# builder, the correction restore and the momentum-burn restore are all derived
# from these specs, so a new field can no longer be forgotten in one of the paths
# (the root cause of several burn/correction bugs in 0.9.96).
#
# To add a turn-mutable field: append it to the matching tuple below. Nothing else.
# Snapshot key names are persisted in saves (last_turn_snapshot) — never rename them.

# Immutable values (int/str/bool) — copied as-is.
_SNAPSHOT_SCALAR_FIELDS = (
    "health", "spirit", "supply", "momentum", "max_momentum",
    "scene_count", "chaos_factor", "crisis_mode", "game_over",
    "epilogue_shown", "epilogue_dismissed",
    "current_location", "current_scene_context",
    "time_of_day", "time_unchanged_scenes", "scenes_at_location",
)
# Mutable containers — deep-copied on snapshot AND on restore.
_SNAPSHOT_DEEP_FIELDS = (
    "location_history", "npcs", "clocks", "director_guidance",
    "scene_intensity_history",
)
# story_blueprint sub-keys that mutate during a turn → snapshot key "bp_<key>".
# The rest of the blueprint (acts, conflict, endings, …) is immutable during a turn.
_SNAPSHOT_BP_KEYS = (
    "revealed",                    # mark_revelation_used()
    "triggered_transitions",       # _apply_director_guidance() / back-fill
    "story_complete",              # _check_story_completion()
    "triggered_director_phases",   # phase-trigger dedup in process_turn()
)
# Turn inputs filled in progressively by process_turn() (not restored).
_SNAPSHOT_TURN_INPUT_KEYS = ("player_input", "brain", "roll", "narration")


def _build_turn_snapshot(game: GameState) -> dict:
    """Build a complete snapshot of all turn-mutable GameState fields.
    Called at the start of process_turn() BEFORE any mutations.
    Used by the ## correction flow to fully restore pre-turn state.
    Also used as the authoritative basis for the burn pre_snapshot.
    Persisted via SAVE_FIELDS so a ## correction still works after a reload.
    Field lists: _SNAPSHOT_SCALAR_FIELDS / _SNAPSHOT_DEEP_FIELDS / _SNAPSHOT_BP_KEYS.
    """
    snap: dict = {}
    for f in _SNAPSHOT_SCALAR_FIELDS:
        snap[f] = getattr(game, f)
    for f in _SNAPSHOT_DEEP_FIELDS:
        snap[f] = copy.deepcopy(getattr(game, f))
    bp = game.story_blueprint or {}
    for k in _SNAPSHOT_BP_KEYS:
        val = bp.get(k)
        if k == "story_complete":
            snap["bp_story_complete"] = bool(val)
        else:
            snap[f"bp_{k}"] = list(val or [])
    # Log tails — the last entry BEFORE this turn. _restore_snapshot(logs=True)
    # pops everything appended after it.
    snap["session_log_tail"] = copy.deepcopy(game.session_log[-1]) if game.session_log else None
    snap["narration_history_tail"] = (copy.deepcopy(game.narration_history[-1])
                                      if game.narration_history else None)
    for k in _SNAPSHOT_TURN_INPUT_KEYS:
        snap[k] = "" if k == "player_input" else None
    return snap


def _truncate_log_to_tail(entries: list, tail: Optional[dict], max_pop: int = 3) -> None:
    """Pop entries appended after `tail` (the last pre-turn entry), in place.
    tail=None means the list was empty before the turn → everything after it is
    turn output. Bounded by max_pop so a list that was trimmed at its cap (tail no
    longer present) loses at most the turn's own entry instead of being wiped."""
    if tail is None:
        if len(entries) <= max_pop:
            entries.clear()
        else:
            entries.pop()
        return
    for i in range(1, min(max_pop, len(entries)) + 1):
        if entries[-i] == tail:
            del entries[len(entries) - i + 1:]
            return
    # Tail not found among the last entries (list trimmed at cap, or tail edited):
    # fall back to dropping exactly the turn's entry.
    if entries:
        entries.pop()


def _restore_snapshot(game: GameState, snap: dict, *, logs: bool) -> None:
    """Restore every turn-mutable field from a snapshot (spec-driven).
    logs=True additionally removes the session_log / narration_history entries the
    turn appended (## input_misread: the turn is re-run from scratch).
    logs=False keeps them (momentum burn: the turn's entries are edited in place).
    Missing keys (older saved snapshots) leave the current value untouched."""
    for f in _SNAPSHOT_SCALAR_FIELDS:
        if f in snap:
            setattr(game, f, snap[f])
    for f in _SNAPSHOT_DEEP_FIELDS:
        if f in snap and snap[f] is not None:
            setattr(game, f, copy.deepcopy(snap[f]))
    if game.story_blueprint is not None:
        for k in _SNAPSHOT_BP_KEYS:
            key = f"bp_{k}"
            if key not in snap:
                continue
            if k == "story_complete":
                if snap[key]:
                    game.story_blueprint["story_complete"] = True
                else:
                    game.story_blueprint.pop("story_complete", None)
            elif snap[key]:
                game.story_blueprint[k] = list(snap[key])
            else:
                # Empty pre-turn ≙ absent (all readers use .get(k) or []) — pop so a
                # restore reproduces the exact pre-turn blueprint.
                game.story_blueprint.pop(k, None)
    if logs:
        _truncate_log_to_tail(game.session_log, snap.get("session_log_tail"))
        _truncate_log_to_tail(game.narration_history, snap.get("narration_history_tail"))


def _reapply_turn_structure(game: GameState, brain: dict,
                            chaos_interrupt: Optional[str] = None) -> None:
    """Re-apply the structural effects of a turn after a pre-turn snapshot restore:
    scene advance, background→active reactivation of the targeted NPC, the Brain's
    location/time change, and the chaos release of a (reused) chaos interrupt.
    Used by process_momentum_burn() and the ## input_misread re-run so both paths
    stay in sync with process_turn()."""
    game.scene_count += 1
    tid = brain.get("target_npc")
    if tid:
        target = _find_npc(game, tid)
        if target and target.get("status") == "background":
            _reactivate_npc(target, reason=f"targeted by player in scene {game.scene_count}")
    _apply_brain_location_time(game, brain)
    if chaos_interrupt:
        # check_chaos_interrupt() releases one chaos point when it fires.
        game.chaos_factor = max(3, game.chaos_factor - 1)


class _rollback_on_error:
    """Context manager: if the wrapped block raises, restore the COMPLETE GameState
    to its state at entry and re-raise.

    Multi-call pipelines (Brain → Narrator → Extractor …) mutate the game between
    API calls. Without this, a failure halfway (API timeout, overload) left the
    state half-applied — scene already advanced, consequences already deducted —
    and the UI retry applied them a second time. The backup is a full deepcopy
    (a few ms), restored field-by-field into the SAME object so every caller
    reference (session storage, closures) stays valid."""

    def __init__(self, game: GameState, label: str):
        self.game = game
        self.label = label
        self.backup = None

    def __enter__(self):
        self.backup = copy.deepcopy(self.game)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and self.backup is not None:
            for f in dataclasses.fields(self.game):
                setattr(self.game, f.name, getattr(self.backup, f.name))
            log(f"[{self.label}] Failed ({exc_type.__name__}: {exc}) — "
                f"game state rolled back to pre-call state", level="warning")
        return False  # never swallow the exception


def record_scene_intensity(game: GameState, scene_type: str):
    """Record a scene's intensity type for pacing analysis.
    scene_type: 'action', 'breather', or 'interrupt'
    Keeps last 5 entries — matches get_pacing_hint() window.
    """
    game.scene_intensity_history.append(scene_type)
    if len(game.scene_intensity_history) > 5:
        game.scene_intensity_history = game.scene_intensity_history[-5:]


# ===============================================================
# KISHŌTENKETSU STRUCTURE SELECTION
# ===============================================================

def choose_story_structure(tone: str) -> str:
    """Choose between '3act' and 'kishotenketsu' based on tone probability.
    Returns '3act' or 'kishotenketsu'.
    """
    probability = KISHOTENKETSU_PROBABILITY.get(tone, KISHOTENKETSU_DEFAULT_PROBABILITY)
    return "kishotenketsu" if random.random() < probability else "3act"


# ===============================================================
# DICE & CONSEQUENCES
# ===============================================================

def roll_action(stat_name: str, stat_value: int, move: str) -> RollResult:
    """Ironsworn action roll: 1d6 + stat (max 10) vs two d10 challenge dice.
    RollResult keeps its d2 field for saves made with the former 2d6 roll;
    new rolls set it to 0 (see action_dice_text())."""
    d1, d2 = random.randint(1, 6), 0
    c1, c2 = random.randint(1, 10), random.randint(1, 10)
    score = min(d1 + d2 + stat_value, 10)
    if score > c1 and score > c2:
        result = "STRONG_HIT"
    elif score > c1 or score > c2:
        result = "WEAK_HIT"
    else:
        result = "MISS"
    return RollResult(d1, d2, c1, c2, stat_name, stat_value, score, result, move, match=(c1 == c2))


def action_dice_text(d1: int, d2: int = 0) -> str:
    """Action die (or dice) as shown in logs and the UI: "4" for the current 1d6
    roll, "3+5" for rolls stored before the switch from 2d6."""
    return f"{d1}+{d2}" if d2 else str(d1)


COMBAT_MOVES = {"clash", "strike"}
SOCIAL_MOVES = {"compel", "make_connection", "test_bond"}


def apply_consequences(game: GameState, roll: RollResult, brain: dict) -> tuple[list[str], list[dict]]:
    """Apply mechanical consequences. Position scales severity."""
    consequences = []
    clock_events = []
    tid = brain.get("target_npc")
    target = _find_npc(game, tid) if tid else None

    # Warn when a social move has no resolvable target — bond/disposition effects
    # are silently skipped, which is hard to spot without this log line.
    if roll.move in SOCIAL_MOVES and target is None:
        log(f"[Consequences] Social move '{roll.move}' has no resolvable target "
            f"(target_npc={tid!r}) — bond/disposition effects skipped", level="warning")

    position = brain.get("position", "risky")

    if roll.result == "MISS":
        if roll.move == "endure_harm":
            dmg = 2 if position == "desperate" else 1
            old = game.health
            game.health = max(0, game.health - dmg)
            if game.health < old:
                consequences.append(f"health -{old - game.health}")
        elif roll.move == "endure_stress":
            dmg = 2 if position == "desperate" else 1
            old = game.spirit
            game.spirit = max(0, game.spirit - dmg)
            if game.spirit < old:
                consequences.append(f"spirit -{old - game.spirit}")
        elif roll.move in COMBAT_MOVES:
            dmg = 3 if position == "desperate" else (1 if position == "controlled" else 2)
            old = game.health
            game.health = max(0, game.health - dmg)
            if game.health < old:
                consequences.append(f"health -{old - game.health}")
        elif roll.move in SOCIAL_MOVES:
            if target:
                old_bond = target["bond"]
                target["bond"] = max(0, target["bond"] - 1)
                if target["bond"] < old_bond:
                    consequences.append(f'{html.escape(target["name"])} bond -1')
            dmg = 2 if position == "desperate" else 1
            old = game.spirit
            game.spirit = max(0, game.spirit - dmg)
            if game.spirit < old:
                consequences.append(f"spirit -{old - game.spirit}")
        else:
            parts = []
            old_supply = game.supply
            game.supply = max(0, game.supply - 1)
            if game.supply < old_supply:
                parts.append(f"supply -{old_supply - game.supply}")
            if position == "desperate":
                old_health = game.health
                game.health = max(0, game.health - 2)
                if game.health < old_health:
                    parts.append(f"health -{old_health - game.health}")
            elif position != "controlled":
                old_health = game.health
                game.health = max(0, game.health - 1)
                if game.health < old_health:
                    parts.append(f"health -{old_health - game.health}")
            if parts:
                consequences.append(", ".join(parts))

        mom_loss = 3 if position == "desperate" else 2
        game.momentum = max(-6, game.momentum - mom_loss)
        consequences.append(f"momentum -{mom_loss}")

        for clock in game.clocks:
            if clock["clock_type"] == "threat" and clock["filled"] < clock["segments"]:
                ticks = 2 if position == "desperate" else 1
                clock["filled"] = min(clock["segments"], clock["filled"] + ticks)
                fired = clock["filled"] >= clock["segments"]
                if fired:
                    clock["fired"] = True
                    clock["fired_at_scene"] = game.scene_count
                clock_events.append({
                    "clock": clock["name"],
                    "trigger": clock.get("trigger_description", ""),
                    "source": "miss",
                    "ticks": ticks,
                    "fired": fired,
                })
                break

    elif roll.result == "WEAK_HIT":
        game.momentum = min(game.max_momentum, game.momentum + 1)
        if roll.move in {"make_connection"} and target:
            target["bond"] = min(target.get("bond_max", 4), target["bond"] + 1)
        # Combat moves: partial success still costs — you land the blow but take one too.
        # desperate: -2 (a brutal exchange); risky: -1 (standard cost of engagement);
        # controlled: no damage (you had the situation in hand — a graze at worst).
        if roll.move in COMBAT_MOVES and position != "controlled":
            dmg = 2 if position == "desperate" else 1
            old = game.health
            game.health = max(0, game.health - dmg)
            if game.health < old:
                consequences.append(f"health -{old - game.health}")

        # Recovery moves: partial restore on WEAK_HIT
        if roll.move == "endure_harm":
            old = game.health
            game.health = min(5, game.health + 1)
            if game.health > old:
                consequences.append(f"health +{game.health - old}")
        elif roll.move == "endure_stress":
            old = game.spirit
            game.spirit = min(5, game.spirit + 1)
            if game.spirit > old:
                consequences.append(f"spirit +{game.spirit - old}")
        elif roll.move == "resupply":
            old = game.supply
            game.supply = min(5, game.supply + 1)
            if game.supply > old:
                consequences.append(f"supply +{game.supply - old}")

        # Threat clock pressure on WEAK_HIT — the world moved while you were compromising.
        # controlled: no tick (you had the situation in hand).
        # risky:      50% chance of 1 tick (the gap you left may have been exploited).
        # desperate:  guaranteed 1 tick (even partial success here costs the world forward).
        if position != "controlled":
            should_tick = (position == "desperate") or (random.random() < WEAK_HIT_CLOCK_TICK_CHANCE)
            if should_tick:
                for clock in game.clocks:
                    if clock["clock_type"] == "threat" and clock["filled"] < clock["segments"]:
                        clock["filled"] = min(clock["segments"], clock["filled"] + 1)
                        fired = clock["filled"] >= clock["segments"]
                        if fired:
                            clock["fired"] = True
                            clock["fired_at_scene"] = game.scene_count
                        clock_events.append({
                            "clock": clock["name"],
                            "trigger": clock.get("trigger_description", ""),
                            "source": "weak_hit",
                            "fired": fired,
                        })
                        break

    else:  # STRONG_HIT
        effect = brain.get("effect", "standard")
        mom_gain = 3 if effect == "great" else 2
        game.momentum = min(game.max_momentum, game.momentum + mom_gain)
        if roll.move in {"make_connection", "test_bond"} and target:
            # Bond + disposition shifts only for relationship-focused moves, not transactional compel.
            # compel is a negotiation/coercion — succeeding does not deepen the relationship.
            # test_bond: surviving a crisis together deepens the bond the same way as
            # make_connection, but organically rather than intentionally.
            target["bond"] = min(target.get("bond_max", 4), target["bond"] + 1)
            shifts = {"hostile": "distrustful", "distrustful": "neutral",
                      "neutral": "friendly", "friendly": "loyal"}
            target["disposition"] = shifts.get(target["disposition"], target["disposition"])
        # Recovery moves: full restore on STRONG_HIT
        if roll.move == "endure_harm":
            gain = 2 if effect == "great" else 1
            old = game.health
            game.health = min(5, game.health + gain)
            if game.health > old:
                consequences.append(f"health +{game.health - old}")
        elif roll.move == "endure_stress":
            gain = 2 if effect == "great" else 1
            old = game.spirit
            game.spirit = min(5, game.spirit + gain)
            if game.spirit > old:
                consequences.append(f"spirit +{game.spirit - old}")
        elif roll.move == "resupply":
            gain = 2 if effect == "great" else 1
            old = game.supply
            game.supply = min(5, game.supply + gain)
            if game.supply > old:
                consequences.append(f"supply +{game.supply - old}")

    # --- Crisis check -----------------
    if game.health <= 0 and game.spirit <= 0:
        game.game_over = True
        game.crisis_mode = True
    elif game.health <= 0 or game.spirit <= 0:
        game.crisis_mode = True
    else:
        # Recovery: if both are above 0 again, exit crisis
        game.crisis_mode = False

    return consequences, clock_events


def _tick_autonomous_clocks(game: GameState) -> list:
    """Autonomously advance world threat clocks by chance each scene.
    Each unfilled world threat clock rolls AUTONOMOUS_CLOCK_TICK_CHANCE independently —
    simulates the world moving forward regardless of player roll results.
    NPC-owned clocks (scheme AND threat) are excluded — check_npc_agency() is
    their sole advancement mechanism (fires every 5 scenes). This prevents
    double-ticking on agency scenes where both functions would otherwise fire.
    Note: apply_consequences() already ticks the first available threat clock
    (regardless of owner) on a MISS, so NPC-owned threat clocks are not frozen
    on bad rolls — only autonomous random ticking is restricted.
    Returns a list of clock_event dicts (same format as apply_consequences)."""
    ticked = []
    for clock in game.clocks:
        if clock.get("clock_type") != "threat":
            continue
        if clock.get("filled", 0) >= clock.get("segments", 6):
            continue  # Already full
        if clock.get("owner", "") not in ("", "world"):
            continue  # NPC-owned clocks tick only via check_npc_agency
        if random.random() < AUTONOMOUS_CLOCK_TICK_CHANCE:
            clock["filled"] = min(clock["segments"], clock["filled"] + 1)
            triggered = clock["filled"] >= clock["segments"]
            if triggered:
                clock["fired"] = True
                clock["fired_at_scene"] = game.scene_count
            event = {
                "clock": clock["name"],
                "trigger": clock.get("trigger_description", ""),
                "autonomous": True,
            }
            if triggered:
                event["triggered"] = True
            ticked.append(event)
            status = "TRIGGERED" if triggered else f"{clock['filled']}/{clock['segments']}"
            log(f"[Clock] Autonomous tick: '{clock['name']}' → {status}")
    return ticked


CLOCK_MIN_SEGMENTS = 2
CLOCK_MAX_SEGMENTS = 10


def _sanitize_new_clock(c: dict) -> Optional[dict]:
    """Validate a clock proposed by a model (opening extractor, Director).
    Returns a clean clock dict without id, or None for an unusable proposal.
    A new clock never starts full: it would never fire (ticks skip full clocks)
    and the Narrator would never hear about it."""
    if not isinstance(c, dict):
        return None
    name = " ".join(str(c.get("name") or "").split())
    if not name:
        return None
    try:
        segments = int(c.get("segments", 6))
    except (TypeError, ValueError):
        segments = 6
    segments = max(CLOCK_MIN_SEGMENTS, min(CLOCK_MAX_SEGMENTS, segments))
    try:
        filled = int(c.get("filled", 0))
    except (TypeError, ValueError):
        filled = 0
    filled = max(0, min(filled, segments - 1))
    ctype = str(c.get("clock_type") or c.get("type") or "threat").strip().lower()
    if ctype not in ("threat", "scheme"):
        ctype = "threat"
    return {"name": name, "clock_type": ctype, "segments": segments, "filled": filled,
            "trigger_description": str(c.get("trigger_description") or ""),
            "owner": str(c.get("owner") or "world").strip() or "world",
            "fired": False}


def _sync_clock_owners(game: GameState, source: str = "Clock") -> None:
    """Point clock owners at the NPC's current name when the stored owner is one of
    its former names (aliases). Every rename path (identity reveal, surname,
    title variant, ## correction, duplicate absorb) runs before this, so callers
    sync once after a batch of NPC changes. An owner that is some NPC's current
    name is left alone."""
    current = {_normalize_for_match(n.get("name", "")) for n in game.npcs}
    alias_to_name: dict[str, str] = {}
    for npc in game.npcs:
        for alias in npc.get("aliases", []):
            alias_to_name.setdefault(_normalize_for_match(alias), npc["name"])
    for clock in game.clocks:
        owner = clock.get("owner", "")
        if not owner or owner == "world":
            continue
        norm = _normalize_for_match(owner)
        if norm in current:
            continue
        canonical = alias_to_name.get(norm)
        if canonical and canonical != owner:
            log(f"[{source}] Clock owner synced: '{clock.get('name')}' '{owner}' → '{canonical}'")
            clock["owner"] = canonical


def _purge_old_fired_clocks(game: GameState, keep_scenes: int = 3) -> None:
    """Remove fired clocks that triggered more than keep_scenes scenes ago.
    Fired clocks are kept briefly so the narrator and metadata extractor have
    short-term context (e.g. 'Spurensicherung arrived').  After keep_scenes
    they are pure noise and waste prompt tokens.
    Clocks without fired_at_scene (legacy saves) are purged immediately."""
    before = len(game.clocks)
    game.clocks = [
        c for c in game.clocks
        if not c.get("fired")
        or (game.scene_count - c.get("fired_at_scene", 0)) <= keep_scenes
    ]
    purged = before - len(game.clocks)
    if purged:
        log(f"[Clock] Purged {purged} expired fired clock(s) at scene {game.scene_count}")



def can_burn_momentum(game: "GameState", roll: "RollResult") -> str | None:
    """Check if momentum burn can upgrade the result. Returns new result or None.
    Does NOT mutate game state — actual burn happens in process_momentum_burn."""
    if game.momentum <= 0:
        return None
    if roll.result == "MISS" and game.momentum > roll.c1 and game.momentum > roll.c2:
        return "STRONG_HIT"
    if roll.result == "MISS" and (game.momentum > roll.c1 or game.momentum > roll.c2):
        return "WEAK_HIT"
    if roll.result == "WEAK_HIT" and game.momentum > roll.c1 and game.momentum > roll.c2:
        return "STRONG_HIT"
    return None


def check_npc_agency(game: GameState, tick: bool = True) -> tuple[list[str], list[dict]]:
    """Advance NPC-owned clocks on every 5th scene and return prompt strings + clock events.

    tick=False returns only the agenda prompt lines without advancing any clock —
    used by re-narration paths (## state_error correction) where the original turn
    already applied the agency ticks.

    Returns a (actions, clock_events) tuple so callers can log agency ticks alongside
    other clock events in session_log.  clock_events follow the same dict format as
    apply_consequences() and _tick_autonomous_clocks(), with source="npc_agency".
    """
    if game.scene_count % 5 != 0:
        return [], []
    actions: list[str] = []
    clock_events: list[dict] = []
    for npc in game.npcs:
        if npc.get("status") == "active" and npc.get("agenda"):
            actions.append(
                f'NPC "{npc["name"]}" pursues agenda "{npc["agenda"]}" {E["dash"]} concrete offscreen action.')
            # Build normalised name set for this NPC (canonical name + aliases).
            # Clock owner is written by the AI as a name string ("world" or NPC name),
            # never as a raw npc_id — so we must compare by name, not by id.
            if not tick:
                continue
            npc_norms = {_normalize_for_match(npc["name"])}
            npc_norms.update(_normalize_for_match(a) for a in npc.get("aliases", []))
            for clock in game.clocks:
                clock_owner = clock.get("owner", "")
                if (clock["clock_type"] in ("scheme", "threat")
                        and clock_owner not in ("", "world")
                        and _normalize_for_match(clock_owner) in npc_norms
                        and clock["filled"] < clock["segments"]):
                    clock["filled"] += 1
                    triggered = clock["filled"] >= clock["segments"]
                    if triggered:
                        clock["fired"] = True
                        clock["fired_at_scene"] = game.scene_count
                        actions.append(f'CLOCK FILLED "{clock["name"]}": {clock.get("trigger_description", "")}')
                    event: dict = {
                        "clock": clock["name"],
                        "trigger": clock.get("trigger_description", ""),
                        "source": "npc_agency",
                        "npc": npc["name"],
                    }
                    if triggered:
                        event["fired"] = True
                    clock_events.append(event)
                    status = "TRIGGERED" if triggered else f"{clock['filled']}/{clock['segments']}"
                    log(f"[Clock] NPC agency tick: '{clock['name']}' by '{npc['name']}' → {status}")
    return actions, clock_events


# ===============================================================
# AI CALLS
# ===============================================================

def _story_context_block(game: GameState) -> str:
    """Build compact story direction block for prompts."""
    if not game.story_blueprint or not game.story_blueprint.get("acts"):
        return ""
    act = get_current_act(game)
    bp = game.story_blueprint

    ending_hint = ""
    if bp.get("story_complete") and getattr(game, "epilogue_dismissed", False):
        ending_hint = (
            f'\n<story_ending>The planned arc is complete and the player chose to continue '
            f'beyond it (scene {game.scene_count}). Do NOT push toward a conclusion. '
            f'Follow the player\'s organic lead — new threads, consequences, and character '
            f'moments are all valid. Treat this as open-ended play.</story_ending>'
        )
    elif bp.get("story_complete"):
        endings = bp.get("possible_endings", [])
        ending_hint = f'\n<story_ending>Story has EXCEEDED its planned arc (scene {game.scene_count}). Guide toward a satisfying conclusion in the next 1-2 scenes. Possible endings: {", ".join(html.escape(e["type"]) for e in endings)}. Let player actions determine which ending, but actively weave toward closure.</story_ending>'
    elif act.get("approaching_end"):
        endings = bp.get("possible_endings", [])
        ending_hint = f'\n<story_ending>Story nearing conclusion. Possible endings: {", ".join(html.escape(e["type"]) for e in endings)}. Let player actions determine which.</story_ending>'

    structure = bp.get("structure_type", "3act")
    thematic = bp.get("thematic_thread", "")
    thematic_attr = f' thematic_thread="{_xa(thematic)}"' if thematic else ""

    # Revelation hint: separate element so the full content reaches the narrator
    # untruncated. Only the first pending revelation is surfaced per scene.
    pending = get_pending_revelations(game)
    rev_block = ""
    if pending:
        rev = pending[0]
        rev_block = (
            f'\n<revelation_ready weight="{rev["dramatic_weight"]}">'
            f'{html.escape(str(rev["content"]))}'
            f'</revelation_ready>'
        )

    # Due act trigger: hand the turning point to the Narrator directly. Director
    # guidance alone was crowded out by other rules (time, location), so the
    # act's core event never reached the page and acts only advanced via scene_range.
    trigger_block = ""
    if _act_trigger_due(game):
        trigger_block = (
            f'\n<act_turning_point>This act is about to end and its turning point has not'
            f' happened yet: {html.escape(act.get("transition_trigger", ""))} Move this scene'
            f' toward it as a concrete on-page moment the character can act on (plant the'
            f' find, bring the confrontation, put the decision in front of them). If the'
            f' player\'s action reaches it, let it happen fully on the page. Never make the'
            f' player\'s choices for them.</act_turning_point>'
        )

    return (
        f'<story_arc structure="{_xa(structure)}" act="{act["act_number"]}/{act["total_acts"]}"'
        f' phase="{_xa(act["phase"])}" progress="{act["progress"]}" mood="{_xa(act.get("mood",""))}"'
        f' conflict="{_xa(bp.get("central_conflict",""))}" act_goal="{_xa(act.get("goal",""))}"'
        f'{thematic_attr}/>'
        f'{rev_block}'
        f'{trigger_block}'
        f'{ending_hint}\n'
    )



def _recent_events_block(game: GameState) -> str:
    """Build compact factual timeline from session_log for narrator consistency.
    Uses Director's rich_summary when available, falls back to Brain's player_intent.
    Gives the narrator a factual backbone to prevent contradictions across scenes."""
    if not game.session_log or len(game.session_log) < 2:
        return ""
    # Skip the most recent entry (that's the current scene being narrated)
    entries = game.session_log[-8:-1] if len(game.session_log) > 1 else []
    if not entries:
        return ""
    lines = []
    for s in entries:
        summary = s.get("rich_summary") or s.get("summary", "")
        if summary:
            lines.append(f"Scene {s.get('scene', '?')}: {html.escape(summary[:120])}")
    if not lines:
        return ""
    return f"\n<recent_events>\n" + "\n".join(lines) + "\n</recent_events>"


def _narrator_clocks_block(game: GameState) -> str:
    """Compact active-threat block for Narrator prompts.
    Gives the Narrator awareness of active clocks and their urgency so that
    scene tone naturally reflects mounting pressure — without the Narrator
    needing to reference clocks explicitly.
    Only clocks with at least one filled segment are shown — unfilled clocks
    have no pressure value and would add noise."""
    active = [c for c in game.clocks
              if not c.get("fired") and c.get("segments", 0) > 0 and c.get("filled", 0) > 0]
    if not active:
        return ""
    lines = []
    for c in active:
        filled = c.get("filled", 0)
        segs   = c.get("segments", 6)
        pct    = filled / segs if segs else 0
        bar    = "●" * filled + "○" * (segs - filled)
        urgency = (
            "critical — trigger imminent" if pct >= 0.85 else
            "high — pressure is building"  if pct >= 0.65 else
            "moderate"                     if pct >= 0.40 else
            "low"
        )
        lines.append(f'- "{html.escape(c.get("name", "?"))}" {bar} {filled}/{segs} — {urgency}')
    return (
        "\n<active_threats>\n"
        "Let fill level shape atmospheric pressure — a nearly-full threat should feel imminent "
        "even if not directly addressed. Do NOT mention clocks, fill levels, or game terms.\n"
        + "\n".join(lines)
        + "\n</active_threats>"
    )


def _npc_relations_block(game: GameState, present_npc_ids: set) -> str:
    """Cross-relationship hints between NPCs present in this scene.
    Mines about_npc memories across all present NPCs (including the target NPC)
    to surface dynamics (alliances, tensions, history) the Narrator should reflect
    in how NPCs interact with each other — not just with the player.
    Note: target NPC's cross-relations also appear in _npc_block npc_views (TF-IDF
    scored); here they are selected by recency. Minor overlap, different angle."""
    if not present_npc_ids or len(present_npc_ids) < 2:
        return ""
    relations = []
    seen_pairs: set = set()
    for npc in game.npcs:
        npc_id = npc.get("id")
        if npc_id not in present_npc_ids:
            continue
        npc_name = npc.get("name", "?")
        _ensure_npc_memory_fields(npc)
        for m in reversed(npc.get("memory", [])):   # most recent first
            about = m.get("about_npc")
            if not about or about not in present_npc_ids or about == npc_id:
                continue
            pair_key = tuple(sorted((npc_id, about)))
            if pair_key in seen_pairs:
                continue                            # one entry per pair
            other = _find_npc(game, about)
            if not other:
                continue
            other_name = other.get("name", "?")
            event = m.get("event", "")[:90]
            ew    = m.get("emotional_weight", "")
            relations.append(
                f'- {html.escape(npc_name)} → {html.escape(other_name)}: '
                f'{html.escape(event)} ({ew})'
            )
            seen_pairs.add(pair_key)
            if len(relations) >= 6:                 # cap total entries
                break
        if len(relations) >= 6:
            break
    if not relations:
        return ""
    return (
        "\n<npc_dynamics>\n"
        "Relationship history between NPCs present — let this shape how they interact "
        "with each other, not only with the player.\n"
        + "\n".join(relations)
        + "\n</npc_dynamics>"
    )


# Minimum prefix length (tokens) Anthropic caches per model family. Shorter
# prefixes marked with cache_control are processed uncached — no error, no cache
# write surcharge — so marking a prompt that is (currently) below the floor is free.
CACHE_MIN_TOKENS = {
    "claude-haiku-5-5": 512,
    "claude-sonnet-5-5": 512,
    "claude-sonnet-4-6": 1024,
    "claude-haiku-4-5-20251001": 4096,
}


def _cached_system(text: str) -> list:
    """Wrap a STATIC system prompt as a cacheable content block (5-min ephemeral).
    Only use for system text that is identical across calls within a session —
    any per-turn value in the text turns every call into a cache miss.
    Structured-output schema changes do not invalidate the system-level cache."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _log_usage(kwargs: dict, response) -> None:
    """One log line per API call with token usage incl. prompt-cache reads/writes.
    Makes caching verifiable in the log (cache_read > 0 = hit)."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    model = str(kwargs.get("model", "?"))
    oc = kwargs.get("output_config") or {}
    effort = f" effort={oc['effort']}" if oc.get("effort") else ""
    c_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    c_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    log(f"[API] {model}{effort}: in={getattr(usage, 'input_tokens', 0)} "
        f"out={getattr(usage, 'output_tokens', 0)} "
        f"cache_read={c_read} cache_write={c_write}")


# ---------------------------------------------------------------
# MODEL SETTINGS — per-role model, effort and thinking (config.json)
# ---------------------------------------------------------------
# Call sites keep passing NARRATOR_MODEL / BRAIN_MODEL; these constants act as
# role tokens. _api_create_with_retry() swaps in the configured model and adds
# output_config.effort / thinking for that role. Empty or missing config values
# keep the API defaults, i.e. the previous behaviour.
#
#   config.json:  "narrator_model": "claude-sonnet-5-5",
#                 "narrator_effort": "high",          # low|medium|high|xhigh|max
#                 "narrator_thinking": "between_tools",  # disabled|adaptive|between_tools
#                 "brain_model" / "brain_effort" / "brain_thinking"  (same for Haiku calls)
#
# Model IDs are pinned snapshots — there is no "latest" alias. Switch models
# deliberately and compare with an Elvira run first.
MODEL_ROLES = ("narrator", "brain")
_MODEL_ROLE_BY_DEFAULT = {NARRATOR_MODEL: "narrator", BRAIN_MODEL: "brain"}
_ROLE_DEFAULT_MODEL = {"narrator": NARRATOR_MODEL, "brain": BRAIN_MODEL}
# Role defaults applied when config.json leaves the option empty. The brain role
# runs many short structured calls per turn — thinking only adds latency there.
_ROLE_DEFAULT_THINKING = {"brain": "disabled"}
# Narration quality benefits from high effort; the brain role keeps the API default.
_ROLE_DEFAULT_EFFORT = {"narrator": "high"}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
THINKING_MODES = ("disabled", "adaptive", "between_tools")

_MODEL_SETTINGS: Optional[dict] = None   # lazily loaded from config.json
_REJECTED_OPTIONS: set = set()           # {(role, "effort"|"thinking")} the API refused


def configure_models(cfg: Optional[dict] = None) -> dict:
    """Load per-role model settings from a config dict (default: config.json).
    Invalid effort/thinking values are ignored with a warning. Returns the settings."""
    global _MODEL_SETTINGS
    if cfg is None:
        cfg = load_global_config()
    settings = {}
    for role in MODEL_ROLES:
        model = str(cfg.get(f"{role}_model") or "").strip() or _ROLE_DEFAULT_MODEL[role]
        effort = str(cfg.get(f"{role}_effort") or "").strip().lower() or None
        thinking = str(cfg.get(f"{role}_thinking") or "").strip().lower() or None
        if effort and effort not in EFFORT_LEVELS:
            log(f"[Models] Ignoring invalid {role}_effort '{effort}' "
                f"(allowed: {', '.join(EFFORT_LEVELS)})", level="warning")
            effort = None
        if thinking and thinking not in THINKING_MODES:
            log(f"[Models] Ignoring invalid {role}_thinking '{thinking}' "
                f"(allowed: {', '.join(THINKING_MODES)})", level="warning")
            thinking = None
        # Empty or invalid values fall back to the role default (None = API default).
        effort = effort or _ROLE_DEFAULT_EFFORT.get(role)
        thinking = thinking or _ROLE_DEFAULT_THINKING.get(role)
        settings[role] = {"model": model, "effort": effort, "thinking": thinking}
    _MODEL_SETTINGS = settings
    _REJECTED_OPTIONS.clear()
    log("[Models] " + " | ".join(
        f"{r}={s['model']} effort={s['effort'] or 'default'} thinking={s['thinking'] or 'default'}"
        for r, s in settings.items()))
    return settings


def get_model_settings() -> dict:
    """Current per-role settings (loads config.json on first use)."""
    if _MODEL_SETTINGS is None:
        configure_models()
    return _MODEL_SETTINGS


def model_for(role: str) -> str:
    """Configured model ID for a role ("narrator" or "brain")."""
    return get_model_settings()[role]["model"]


def _apply_model_settings(kwargs: dict) -> tuple[dict, Optional[str]]:
    """Map a role-token model to the configured model and add effort/thinking.
    Returns (new_kwargs, role). Unknown models (e.g. explicit IDs) pass through."""
    role = _MODEL_ROLE_BY_DEFAULT.get(kwargs.get("model"))
    if role is None:
        return kwargs, None
    s = get_model_settings()[role]
    kw = dict(kwargs)
    kw["model"] = s["model"]
    if s["effort"] and (role, "effort") not in _REJECTED_OPTIONS:
        oc = dict(kw.get("output_config") or {})
        oc["effort"] = s["effort"]
        kw["output_config"] = oc
    if s["thinking"] and (role, "thinking") not in _REJECTED_OPTIONS:
        kw["thinking"] = {"type": s["thinking"]}
    return kw, role


def _rejected_option(e: Exception, kw: dict) -> Optional[str]:
    """Which injected option ("effort"/"thinking") a 400 error is about, if any."""
    msg = str(e).lower()
    if "effort" in msg and (kw.get("output_config") or {}).get("effort"):
        return "effort"
    if "thinking" in msg and kw.get("thinking"):
        return "thinking"
    return None


def _response_text(response) -> str:
    """Concatenated text of all text blocks. Newer models may return thinking
    blocks before the text, so content[0] is not necessarily the answer."""
    parts = [getattr(b, "text", "") for b in getattr(response, "content", None) or []
             if getattr(b, "type", "text") == "text"]
    return "".join(p for p in parts if p)


def _api_create_with_retry(client: anthropic.Anthropic, max_retries: int = 2, **kwargs):
    """Wrapper around client.messages.create with retry on transient API errors.
    Handles rate limits (429), server errors (500/502/503), and overloaded (529)
    with exponential backoff. JSON parsing retries remain in callers.
    529 uses a longer base wait (10s) — standard API overload needs more headroom
    than transient server errors (base 2s).
    Also applies the per-role model settings; if the API rejects an injected
    effort/thinking option, the call is retried without it and the option stays
    off for that role for the rest of the process."""
    import time as _time
    kwargs, role = _apply_model_settings(kwargs)
    attempt = -1
    while attempt < max_retries:
        attempt += 1
        try:
            response = client.messages.create(**kwargs)
            try:
                _log_usage(kwargs, response)
            except Exception:
                pass  # diagnostics must never break a call
            return response
        except anthropic.BadRequestError as e:
            opt = _rejected_option(e, kwargs) if role else None
            if opt is None:
                raise
            # Model does not support the configured option — drop it for this role
            # and retry immediately (does not count as a transient retry).
            _REJECTED_OPTIONS.add((role, opt))
            if opt == "effort":
                oc = {k: v for k, v in kwargs["output_config"].items() if k != "effort"}
                kwargs = {**kwargs, "output_config": oc} if oc else \
                    {k: v for k, v in kwargs.items() if k != "output_config"}
            else:
                kwargs = {k: v for k, v in kwargs.items() if k != "thinking"}
            log(f"[Models] API rejected {role}_{opt} for {kwargs.get('model')} — "
                f"continuing without it ({e})", level="warning")
            attempt -= 1
            continue
        except anthropic.APIStatusError as e:
            if attempt < max_retries and e.status_code in (429, 500, 502, 503, 529):
                # 529 = API overloaded: use longer base wait (10s, 20s, 30s cap, ...)
                # Other transient errors: standard exponential backoff (2s, 4s, 8s, ...)
                base = 10 if e.status_code == 529 else 2
                wait = min(base * (2 ** attempt), 30)
                log(f"[API] Error {e.status_code}, retry {attempt + 1}/{max_retries} in {wait}s",
                    level="warning")
                _time.sleep(wait)
                continue
            raise
        except anthropic.APIConnectionError as e:
            if attempt < max_retries:
                wait = 2 * (2 ** attempt)
                log(f"[API] Connection error, retry {attempt + 1}/{max_retries} in {wait}s: {e}",
                    level="warning")
                _time.sleep(wait)
                continue
            raise


def call_brain(client: anthropic.Anthropic, game: GameState, player_message: str,
               config: Optional[EngineConfig] = None) -> dict:
    log(f"[Brain] Scene {game.scene_count + 1} | Input: {player_message[:100]}")
    def _brain_npc_line(n):
        line = f'- {n["name"]} (id:{n["id"]}): {n["disposition"]}, bond={n["bond"]}/{n.get("bond_max",4)}, agenda="{n.get("agenda","")}"'
        if n.get("aliases"):
            line += f' aliases:{",".join(n["aliases"])}'
        return line
    npc_summary = "\n".join(
        _brain_npc_line(n)
        for n in game.npcs if n.get("status") == "active"
    ) or "(none)"
    # Background NPCs: condensed list so Brain can identify returning characters
    bg_npcs = [n for n in game.npcs if n.get("status") == "background"]
    bg_summary = "\n".join(
        f'- {n["name"]} (id:{n["id"]}): {n["disposition"]}, bond={n["bond"]}'
        + (f' aliases:{",".join(n["aliases"])}' if n.get("aliases") else '')
        for n in bg_npcs
    )
    if bg_summary:
        npc_summary += f"\n(background, not currently present but known):\n{bg_summary}"
    # Lore figures: named but never physically present — for reference/memory only
    lore_npcs = [n for n in game.npcs if n.get("status") == "lore"]
    lore_summary = "\n".join(
        f'- {n["name"]} (id:{n["id"]}): lore figure'
        + (f' aliases:{",".join(n["aliases"])}' if n.get("aliases") else '')
        for n in lore_npcs
    )
    if lore_summary:
        npc_summary += f"\n(lore, historically significant but never physically present):\n{lore_summary}"
    clock_summary = "\n".join(
        f'- {html.escape(c["name"])} ({c["clock_type"]}): {c["filled"]}/{c["segments"]}'
        for c in game.clocks if c["filled"] < c["segments"]
    ) or "(none)"
    last_scenes = "\n".join(
        f'Scene {s["scene"]}: {html.escape(s.get("rich_summary") or s["summary"])}' for s in game.session_log[-3:]
    ) or "(Start)"

    _cfg = config or EngineConfig()
    _brain_lang = get_narration_lang(_cfg)

    lang_rules = (f"- If the player's action implies moving to a NEW location, "
                  f"set location_change to a short location name in {_brain_lang}. null if staying.\n"
                  f"- ALSO check the scene context (ctx): if it describes the character being at a DIFFERENT "
                  f"location than the current loc, set location_change to match the actual location.\n"
                  f"- player_intent and location_change MUST be in {_brain_lang}")

    system = """<role>RPG engine parser. Convert player input to a game move.</role>
""" + _kid_friendly_block(_cfg) + _content_boundaries_block(game) + """<rules>
- Accept ALL player input including world-building declarations
- Pick the move that best fits the player's ACTION, not their words
- dialog = pure talking, no risk. Everything else = a move with a stat
- If <story_arc> is present, consider pacing: favor moves that advance the act goal
- Assess POSITION based on fictional circumstances (not player skill):
  controlled = advantage/safety, risky = uncertain/standard, desperate = severe disadvantage/high stakes
- Assess EFFECT based on potential impact:
  limited = minor even on success, standard = meaningful, great = could change everything
- Formulate a DRAMATIC QUESTION that this scene must answer (1 sentence, yes/no answerable)
- target_npc: the id (e.g. npc_3) of the ONE known NPC the action is directed at, taken from <npcs>. null if the action targets nobody or a character not in <npcs>. Never a name.
""" + lang_rules + """
- Assess time_progression: does this action take significant time? "none"=same moment, "short"=minutes, "moderate"=hours, "long"=half a day or more
</rules>
<moves>
face_danger:edge|heart|iron|shadow|wits
compel:heart|iron|shadow
gather_information:wits
secure_advantage:edge|heart|iron|shadow|wits
clash:iron|edge
strike:iron|edge
endure_harm:iron
endure_stress:heart
make_connection:heart
test_bond:heart
resupply:wits
world_shaping:wits|heart|shadow
dialog:none
</moves>
<stats>edge=speed/stealth heart=empathy/charm iron=force shadow=cunning wits=knowledge</stats>"""

    campaign_ctx = ""
    if game.campaign_history:
        campaign_ctx = f"\n<campaign>Chapter {game.chapter_number}. Previous: " + "; ".join(
            f'Ch{ch.get("chapter","?")}:{html.escape(ch.get("title",""))}'
            for ch in game.campaign_history[-3:]
        ) + "</campaign>"

    backstory_ctx = ""
    if getattr(game, 'backstory', ''):
        backstory_ctx = f"\n<backstory>{html.escape(game.backstory)}</backstory>"

    user_msg = f"""<state>
loc:{game.current_location} | ctx:{game.current_scene_context}
time:{game.time_of_day or 'unspecified'} | prev_locations:{', '.join(game.location_history[-3:]) or 'none'}
{game.player_name} H{game.health} Sp{game.spirit} Su{game.supply} M{game.momentum} chaos:{game.chaos_factor} | E{game.edge} H{game.heart} I{game.iron} Sh{game.shadow} W{game.wits}
</state>
<npcs>{npc_summary}</npcs>
<clocks>{clock_summary}</clocks>
<recent>{last_scenes}</recent>
{_story_context_block(game)}{campaign_ctx}{backstory_ctx}<input>{html.escape(player_message)}</input>"""

    try:
        response = _structured_create(
            client, _brain_schema_for(game), BRAIN_OUTPUT_SCHEMA, max_retries=2,
            model=BRAIN_MODEL, max_tokens=BRAIN_MAX_TOKENS,
            system=_cached_system(system),  # static per game (rules + boundaries)
            messages=[{"role": "user", "content": user_msg}],
        )
        result = json.loads(_response_text(response))
        log(f"[Brain] Result: move={result['move']}, pos={result['position']}, "
            f"effect={result['effect']}, intent={result['player_intent'][:60]}")
        return result
    except Exception as e:
        log(f"[Brain] Structured output failed ({type(e).__name__}: {e}), "
            f"falling back to dialog", level="warning")
        return {"type": "action", "move": "dialog", "dialog_only": True,
                "target_npc": None, "stat": "none", "approach": "",
                "player_intent": player_message, "world_addition": None,
                "position": "risky", "effect": "standard",
                "dramatic_question": "", "location_change": None,
                "time_progression": "none"}


def _normalize_stats(stats: dict, keys: tuple, target: int) -> dict:
    """Bring the stat sum to `target` in place (each stat 0-3): take from the
    highest stats or give to the lowest, one point at a time."""
    total = sum(stats[k] for k in keys)
    while total > target:
        k = max(keys, key=lambda x: stats[x])
        stats[k] -= 1
        total -= 1
    while total < target:
        candidates = [x for x in keys if stats[x] < 3]
        if not candidates:
            break
        k = min(candidates, key=lambda x: stats[x])
        stats[k] += 1
        total += 1
    return stats


def call_setup_brain(client: anthropic.Anthropic, creation_data: dict,
                     config: Optional[EngineConfig] = None) -> dict:
    """Generate character and world from creation choices."""
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    kf = _kid_friendly_block(_cfg)
    cb = _content_boundaries_block(creation_data=creation_data)
    system = f"""<role>RPG character/world generator.</role>
{kf}{cb}<rules>
- If player provides a name via character_name(USE EXACTLY), use it VERBATIM as character_name — even if it is a number, code, or unusual. Never modify, expand, or embellish it.
- character_concept = WHO the character is NOW (identity, role, current situation) — 1 sentence, no backstory
- Do NOT put backstory details (past events, relationships, family) into character_concept — the player's backstory is stored separately and will be provided to the narrator directly
- Stats MUST total exactly {STAT_TARGET_SUM}, each 0-3, matched to archetype
- starting_location = a SHORT place name (2-5 words, like a map label), no description, no commas — atmosphere belongs in setting_description
- Each archetype has a primary stat that MUST be at least 2: outsider_loner→shadow, investigator→wits, trickster→shadow, protector→iron, hardboiled→iron, scholar→wits, healer→heart, inventor→wits, artist→heart
- All text fields in {lang}
</rules>"""

    genre_info = creation_data.get('genre', 'dark_fantasy')
    if creation_data.get('genre_description'):
        genre_info = f"custom: {creation_data['genre_description']}"
    tone_info = creation_data.get('tone', 'dark_gritty')
    if creation_data.get('tone_description'):
        tone_info = f"custom: {creation_data['tone_description']}"
    name_override = creation_data.get('player_name', '')
    name_line = f"\ncharacter_name(USE EXACTLY): {name_override}" if name_override else ""
    raw_archetype = creation_data.get('archetype', 'outsider')
    archetype_info = "custom — derive archetype and stats entirely from player_input below" if raw_archetype == "custom" else raw_archetype
    seed = _creativity_seed()
    user_msg = f"""genre:{genre_info} tone:{tone_info} archetype:{archetype_info}{name_line}
player_input: {creation_data.get('custom_desc','')}
creativity_seed: {seed} (Use as loose inspiration for names, locations, and details — not literally, but as creative anchors to avoid generic defaults)"""

    log(f"[Setup] Generating character: genre={genre_info}, tone={tone_info}, "
        f"archetype={archetype_info!r}, "
        f"name_override={name_override!r}, "
        f"has_desc={bool(creation_data.get('custom_desc'))}, "
        f"has_wishes={bool(creation_data.get('wishes'))}, "
        f"creativity_seed={seed!r}")

    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=SETUP_BRAIN_MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema", "schema": SETUP_BRAIN_OUTPUT_SCHEMA}},
        )
        result = json.loads(_response_text(response))

        # --- Stat validation (two-layer: prompt + engine) ---
        # Structured outputs guarantee types but not cross-field constraints.
        stats = result["stats"]
        stat_keys = ("edge", "heart", "iron", "shadow", "wits")

        # Layer 0: Clamp each stat to valid range 0–3
        for k in stat_keys:
            stats[k] = max(0, min(3, stats[k]))

        # Layer 1: If sum is wrong, normalize to the target while keeping the AI's
        # weighting (resetting to archetype defaults discarded the character fit).
        total = sum(stats[k] for k in stat_keys)
        if total != STAT_TARGET_SUM:
            before = {k: stats[k] for k in stat_keys}
            _normalize_stats(stats, stat_keys, STAT_TARGET_SUM)
            log(f"[Setup] AI returned stats summing to {total}, normalized "
                f"{before} → {({k: stats[k] for k in stat_keys})}", level="warning")

        # Layer 2: Enforce primary stat ≥ 2 (skip for custom archetype)
        primary = _ARCHETYPE_PRIMARY_STAT.get(raw_archetype)
        if primary and stats.get(primary, 0) < 2:
            needed = 2 - stats[primary]
            for _ in range(needed):
                donor = max(
                    (s for s in stat_keys if s != primary and stats[s] > 1),
                    key=lambda s: stats[s], default=None,
                )
                if donor is None:
                    break
                stats[donor] -= 1
                stats[primary] += 1
            log(f"[Setup] primary-stat fix: {primary}→{stats[primary]} "
                f"for archetype '{raw_archetype}'", level="warning")

        result["starting_location"] = _short_location_name(result.get("starting_location", ""))
        log(f"[Setup] Success: name={result['character_name']!r}, "
            f"location={result['starting_location']!r}")
        return result

    except anthropic.APIError:
        # Invalid/expired key, network outage or persistent overload: the caller
        # must report it. A silent fallback character hid these errors entirely.
        raise
    except Exception as e:
        log(f"[Setup] Structured output failed ({type(e).__name__}: {e}), "
            f"using fallback", level="warning")
        fallback_name = name_override if name_override else "Namenlos"
        return {"character_name": fallback_name, "character_concept": "Ein Wanderer",
                "setting_description": "", "stats": {"edge":1,"heart":2,"iron":1,"shadow":1,"wits":2},
                "starting_location": "Unbekannter Ort", "opening_situation": "Eine Reise beginnt."}


def call_recap(client: anthropic.Anthropic, game: GameState,
               config: Optional[EngineConfig] = None) -> str:
    """Generate a 'previously on...' recap from the PLAYER'S perspective only."""
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    log_text = "; ".join(
        f'S{s["scene"]}:{s.get("rich_summary") or s["summary"]}({s["result"]})'
        for s in game.session_log[-15:]
    )
    # NPC text: Only player-visible info (no agenda, no secrets) and only introduced NPCs
    npc_text = ", ".join(
        f'{n["name"]}({n["disposition"]},B{n["bond"]})'
        for n in game.npcs if n.get("status") == "active" and n.get("introduced", True)
    ) or "(none)"
    # Last narrations for tone/content reference -- these ARE what the player saw
    recent_narrations = "\n---\n".join(
        entry.get("narration", "")[:800]
        for entry in game.narration_history[-5:]
    )
    # Story arc info: only act/phase, no central_conflict (that's director-level meta)
    arc_info = ""
    if game.story_blueprint and game.story_blueprint.get("acts"):
        act = get_current_act(game)
        structure = game.story_blueprint.get("structure_type", "3act")
        arc_info = (f"\nstory_arc({structure}): "
                    f"act={act['act_number']}/{act['total_acts']} "
                    f"phase={act['phase']} progress={act['progress']}")

    campaign_info = ""
    if game.campaign_history:
        campaign_info = f"\ncampaign: chapter {game.chapter_number} of {len(game.campaign_history) + 1}"
        for ch in game.campaign_history[-2:]:
            campaign_info += f"\n  prev: {ch.get('title', '')}: {ch.get('summary', '')[:200]}"

    for attempt in range(3):
        try:
            response = _api_create_with_retry(
                client, max_retries=1,
                model=BRAIN_MODEL, max_tokens=RECAP_MAX_TOKENS,
                system=f"""Recap an RPG story in {lang}. Second person singular.
- 4-6 sentences, atmospheric, no game mechanics
- Do NOT use markdown headings (#). Start directly with the recap text.
- Capture the MOOD and TONE of the genre
- Mention key NPCs and their relationship to the player
- End with the current situation/tension
- IMPORTANT: Recap from the PLAYER'S perspective ONLY. Only mention things the player has directly witnessed, experienced, or been told by NPCs in the scenes. NEVER reveal NPC agendas, secrets, behind-the-scenes events, or information the player character has not encountered yet.
- Base your recap primarily on the recent_scenes text, which is what the player actually experienced
- If this is a campaign with multiple chapters, briefly acknowledge the character's history
""" + _kid_friendly_block(_cfg) + _content_boundaries_block(game),
                messages=[{"role": "user", "content":
                           f"{game.player_name}{E['dash']}{game.character_concept}\n"
                           f"genre:{game.setting_genre} tone:{game.setting_tone}\n"
                           f"world:{game.setting_description}\n"
                           f"at:{game.current_location}\nlog:{log_text}\nnpcs:{npc_text}"
                           f"{arc_info}{campaign_info}\nnow:{game.current_scene_context}\n"
                           f"recent_scenes:\n{recent_narrations}"}],
            )
            return re.sub(r'\s*[—–]\s*', ' - ', _response_text(response))
        except Exception as e:
            log(f"[Recap] Attempt {attempt + 1}/3 failed: {e}", level="warning")
            if attempt < 2:
                import time as _time
                _time.sleep(2 ** attempt)
            if attempt == 2:
                return f"({game.player_name} recalls the recent events...)"


def call_story_architect(client: anthropic.Anthropic, game: GameState,
                         structure_type: str = "3act",
                         config: Optional[EngineConfig] = None) -> dict:
    """Generate a story blueprint. Supports 3-act and Kishōtenketsu (4-act)."""
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    kf = _kid_friendly_block(_cfg)
    cb = _content_boundaries_block(game)

    if structure_type == "kishotenketsu":
        system = f"""<role>Story architect for an RPG campaign. Create a Kishōtenketsu story blueprint.</role>
{kf}{cb}<rules>
- Design a 4-act Kishōtenketsu structure with ~20 total scenes
- Ki (Introduction): Establish the world, character, and everyday life
- Shō (Development): Deepen relationships, setting, and themes
- Ten (Twist): A surprising PERSPECTIVE SHIFT {E['dash']} not conflict escalation, but something seemingly unrelated that recontextualizes everything. This is the heart of Kishōtenketsu.
- Ketsu (Resolution): Reconcile the new understanding with what came before
- Each act has a GOAL the player should work toward, not a script
- Each act has a TRANSITION_TRIGGER: a narrative condition that signals this act is complete and the next should begin. This is a PLAYER ACTION or STORY EVENT, not a scene number. Example: "The player discovers the truth about the shrine" or "The protagonist's daily routine is disrupted by an outsider". The scene_range is a fallback estimate; the trigger is the real boundary. The trigger must be OBSERVABLE ON THE PAGE: something that visibly happens, is found, said or decided in a scene {E['dash']} never a purely inner realization, feeling or understanding, because nobody can tell when a thought has "happened". BAD: "The protagonist realizes the attack was a test". GOOD: "The protagonist finds the log entry proving the attack was a test". It must be ONE single event {E['dash']} not a chain of several required steps joined by "and" (BAD: "finds the file, deletes it, and sees the alarm go off").
- Include a THEMATIC_THREAD: the emotional/philosophical question that runs through the entire chapter as a vertical narrative layer. This connects to character_growth from previous chapters if available.
- Include 2-3 key revelations that can be woven in at appropriate moments
- Define 2-3 possible endings (harmony, bittersweet, melancholy)
- The blueprint is a COMPASS, not rails {E['dash']} player choices override everything
- If this is a continuing campaign (campaign_chapter > 1): build on unresolved threads from previous chapters, evolve existing relationships, introduce new conflicts that connect to the established world. Use previous character_growth and thematic_question to continue the emotional arc.
- All text fields in {lang}
- Use these phase names: ki_introduction, sho_development, ten_twist, ketsu_resolution
- dramatic_weight must be one of: low, medium, high, critical
</rules>"""
    else:
        system = f"""<role>Story architect for an RPG campaign. Create a flexible story blueprint.</role>
{kf}{cb}<rules>
- Design a 3-act structure with ~15-20 total scenes
- Each act serves a distinct narrative function:
  Setup: Establish the protagonist's WORKING ASSUMPTIONS about the conflict {E['dash']} the frame that will later be challenged or recontextualized.
  Confrontation: Deepen and complicate. Plant evidence that challenges the initial frame, even if the player cannot yet see the full picture.
  Climax: Force a REFRAMING {E['dash']} the resolution must answer a different question than Act 1 appeared to pose. Not just "does the protagonist win?" but "what does winning actually mean now?"
- Each act has a GOAL the player should work toward, not a script
- Each act has a TRANSITION_TRIGGER: a narrative condition that signals this act is complete and the next should begin. This is a PLAYER ACTION or STORY EVENT, not a scene number. Example: "Mike decides to cooperate with the authorities" or "The first repair attempt fails spectacularly". The scene_range is a fallback estimate; the trigger is the real boundary. The trigger must be OBSERVABLE ON THE PAGE: something that visibly happens, is found, said or decided in a scene {E['dash']} never a purely inner realization, feeling or understanding, because nobody can tell when a thought has "happened". BAD: "The protagonist realizes the attack was a test". GOOD: "The protagonist finds the log entry proving the attack was a test". It must be ONE single event {E['dash']} not a chain of several required steps joined by "and" (BAD: "finds the file, deletes it, and sees the alarm go off").
- The confrontation{E['arrow_r']}climax TRANSITION_TRIGGER must be a REFRAMING EVENT {E['dash']} not merely an escalation of existing tension, but a concrete discovery, confession or act that changes what the conflict is fundamentally about.
- central_conflict must have a SURFACE LAYER (what the conflict appears to be at the start) and a HIDDEN LAYER (what it turns out to actually be about). The hidden layer should emerge through Act 2 revelations and reframe the climax.
- THEMATIC_THREAD: A genuine open philosophical question {E['dash']} not a label ("loyalty") but an unresolved question ("Can loyalty survive when the person you are loyal to may not exist?"). It must surface implicitly in Act 1, be challenged in Act 2, and be CONFRONTED {E['dash']} not necessarily resolved {E['dash']} in Act 3.
- Include 2-3 key revelations that can be woven in at appropriate moments. At least one must be a PERCEPTION SHIFT {E['dash']} it changes how the player understands something already seen, not just adds new information.
- Define 2-3 possible endings. Each must address BOTH the external conflict outcome AND the thematic question {E['dash']} what does the protagonist understand at the end that they did not at the start? (e.g. hard-won, bittersweet, pyrrhic)
- The blueprint is a COMPASS, not rails {E['dash']} player choices override everything
- If this is a continuing campaign (campaign_chapter > 1): build on unresolved threads from previous chapters, evolve existing relationships, introduce new conflicts that connect to the established world. Use previous character_growth and thematic_question to continue the emotional arc.
- All text fields in {lang}
- Use these phase names: setup, confrontation, climax
- dramatic_weight must be one of: low, medium, high, critical
</rules>"""

    npc_text = ", ".join(n["name"] for n in game.npcs) if game.npcs else "none yet"
    campaign_ctx = ""
    if game.campaign_history:
        campaign_ctx = f"\ncampaign_chapter:{game.chapter_number}"
        for ch in game.campaign_history[-3:]:
            campaign_ctx += f"\n  prev_chapter_{ch.get('chapter','?')}: {ch.get('summary','')}"
            threads = ch.get("unresolved_threads", [])
            if threads:
                campaign_ctx += f" [threads: {'; '.join(threads)}]"
            growth = ch.get("character_growth", "")
            if growth:
                campaign_ctx += f" [growth: {growth}]"
            thematic = ch.get("thematic_question", "")
            if thematic:
                campaign_ctx += f" [thematic_question: {thematic}]"
    backstory_text = ""
    if getattr(game, 'backstory', ''):
        backstory_text = f"\nbackstory(canon past):{game.backstory}"
    user_msg = f"""genre:{game.setting_genre} tone:{game.setting_tone}
world:{game.setting_description}
character:{game.player_name} {E['dash']} {game.character_concept}
location:{game.current_location}
situation:{game.current_scene_context}
npcs:{npc_text}{campaign_ctx}{backstory_text}"""

    # Story Architect uses NARRATOR_MODEL (Sonnet) — called once per game/chapter,
    # cost is negligible (~$0.01), but quality of the blueprint shapes the entire story.
    # An unusable answer (too few acts, unparseable) gets ONE more attempt with an
    # explicit correction before the generic fallback blueprint is used — the model
    # occasionally collapses the structure into a single act.
    expected_acts = 4 if structure_type == "kishotenketsu" else 3
    attempt_msg = user_msg
    for attempt in range(1, ARCHITECT_ATTEMPTS + 1):
        try:
            response = _api_create_with_retry(
                client, max_retries=2,
                model=NARRATOR_MODEL, max_tokens=STORY_ARCH_MAX_TOKENS, system=system,
                messages=[{"role": "user", "content": attempt_msg}],
                output_config={"format": {"type": "json_schema", "schema": STORY_ARCHITECT_OUTPUT_SCHEMA}},
            )
            blueprint = json.loads(_response_text(response))
            blueprint["revealed"] = []  # Track which revelations have fired
            blueprint["structure_type"] = structure_type

            # Validate act count: schema can no longer enforce minItems ≥ 3 (API restriction).
            n_acts = len(blueprint.get("acts", []))
            if n_acts < expected_acts:
                log(f"[Story] Architect returned {n_acts} acts (expected {expected_acts}) "
                    f"on attempt {attempt}/{ARCHITECT_ATTEMPTS}", level="warning")
                attempt_msg = (user_msg + f"\n\nCORRECTION: your previous blueprint had {n_acts} "
                               f"act(s). The acts array MUST contain exactly {expected_acts} acts, "
                               f"one per phase, each with its own scene_range and transition_trigger.")
                continue

            log(f"[Story] Architect succeeded: "
                f"conflict={blueprint['central_conflict'][:80]}, "
                f"acts={len(blueprint['acts'])}, "
                f"revelations={len(blueprint.get('revelations', []))}"
                + (f" (attempt {attempt})" if attempt > 1 else ""))
            return blueprint

        except anthropic.APIError as e:
            # API-level failure: _api_create_with_retry already retried transient errors.
            log(f"[Story] Architect API error ({type(e).__name__}: {e})", level="warning")
            break
        except Exception as e:
            log(f"[Story] Architect answer unusable on attempt {attempt}/{ARCHITECT_ATTEMPTS} "
                f"({type(e).__name__}: {e})", level="warning")
    log("[Story] Architect failed — using context-aware fallback", level="warning")

    # Fallback: minimal context-aware blueprint in narration language.
    # Uses actual game info instead of generic English placeholder text.
    _loc_short = (game.current_location or "").split(",")[0].strip()[:40]  # Shorten long locations
    _genre_short = (game.setting_genre or "").split(",")[0].strip()[:30]

    # Language-aware fallback text
    _fb_texts = {
        "German": {
            "conflict": f"{game.player_name} steht vor einer unbekannten Bedrohung{' in ' + _loc_short if _loc_short else ''}.",
            "antagonist": f"Feindliche Kräfte{' in der ' + _genre_short + '-Welt' if _genre_short else ''}",
            "thematic": "Was ist der Preis des Überlebens?",
            "3act": [
                {"phase": "setup", "title": "Erste Schatten", "goal": "Die Bedrohung erkennen und Verbündete finden",
                 "scene_range": [1, 6], "mood": "mysterious", "transition_trigger": "Die Bedrohung wird konkret und der Protagonist entscheidet sich zu handeln"},
                {"phase": "confrontation", "title": "Eskalation", "goal": "Der Bedrohung direkt begegnen",
                 "scene_range": [7, 13], "mood": "tense", "transition_trigger": "Eine unerwartete Eskalation zwingt zur finalen Auseinandersetzung"},
                {"phase": "climax", "title": "Die Entscheidung", "goal": "Das Schicksal entscheiden",
                 "scene_range": [14, 20], "mood": "desperate", "transition_trigger": ""},
            ],
            "3act_endings": [
                {"type": "triumph", "description": "Sieg über die Bedrohung."},
                {"type": "bittersweet", "description": "Sieg, aber zu einem hohen Preis."},
                {"type": "tragedy", "description": "Untergang trotz des Kampfes."},
            ],
            "kish": [
                {"phase": "ki_introduction", "title": "Der Alltag", "goal": "Die Welt und ihre Menschen kennenlernen",
                 "scene_range": [1, 5], "mood": "contemplative", "transition_trigger": "Der Alltag wird durch ein unerwartetes Ereignis unterbrochen"},
                {"phase": "sho_development", "title": "Vertiefung", "goal": "Beziehungen und Muster vertiefen",
                 "scene_range": [6, 10], "mood": "intimate", "transition_trigger": "Ein scheinbar unzusammenhängendes Element taucht auf"},
                {"phase": "ten_twist", "title": "Die Wendung", "goal": "Eine unerwartete Perspektive verändert alles",
                 "scene_range": [11, 15], "mood": "surprising", "transition_trigger": "Die neue Perspektive wird erkannt und beginnt alles zu verändern"},
                {"phase": "ketsu_resolution", "title": "Versöhnung", "goal": "Das Neue mit dem Alten vereinen",
                 "scene_range": [16, 20], "mood": "reflective", "transition_trigger": ""},
            ],
            "kish_endings": [
                {"type": "harmony", "description": "Frieden und Verständnis."},
                {"type": "bittersweet", "description": "Erkenntnis um einen Preis."},
                {"type": "melancholy", "description": "Schöne Traurigkeit."},
            ],
        },
    }
    # Use German if available, otherwise English (neutral fallback)
    fb = _fb_texts.get(lang, None)
    if not fb:
        _conflict = f"A growing threat challenges {game.player_name}{' in ' + _loc_short if _loc_short else ''}."
        _antag = f"Opposing forces{' within the ' + _genre_short + ' world' if _genre_short else ''}"
    else:
        _conflict = fb["conflict"]
        _antag = fb["antagonist"]

    if structure_type == "kishotenketsu":
        return {
            "central_conflict": _conflict,
            "antagonist_force": _antag,
            "thematic_thread": fb.get("thematic", "What is the cost of understanding?") if fb else "What is the cost of understanding?",
            "structure_type": "kishotenketsu",
            "acts": fb["kish"] if fb else [
                {"phase": "ki_introduction", "title": "Daily Life", "goal": "Get to know the world",
                 "scene_range": [1, 5], "mood": "contemplative", "transition_trigger": "Daily life is disrupted by an unexpected event"},
                {"phase": "sho_development", "title": "Deepening", "goal": "Deepen relationships",
                 "scene_range": [6, 10], "mood": "intimate", "transition_trigger": "A seemingly unrelated element appears"},
                {"phase": "ten_twist", "title": "The Twist", "goal": "An unexpected perspective changes everything",
                 "scene_range": [11, 15], "mood": "surprising", "transition_trigger": "The new perspective is recognized"},
                {"phase": "ketsu_resolution", "title": "Reconciliation", "goal": "Unite the new with the old",
                 "scene_range": [16, 20], "mood": "reflective", "transition_trigger": ""},
            ],
            "revelations": [],
            "possible_endings": fb["kish_endings"] if fb else [
                {"type": "harmony", "description": "Peace and understanding."},
                {"type": "bittersweet", "description": "Insight at a cost."},
                {"type": "melancholy", "description": "Beautiful sadness."},
            ],
            "revealed": [],
        }
    else:
        return {
            "central_conflict": _conflict,
            "antagonist_force": _antag,
            "thematic_thread": fb.get("thematic", "What is the price of survival?") if fb else "What is the price of survival?",
            "structure_type": "3act",
            "acts": fb["3act"] if fb else [
                {"phase": "setup", "title": "First Shadows", "goal": "Discover the threat and find allies",
                 "scene_range": [1, 6], "mood": "mysterious", "transition_trigger": "The threat becomes concrete and the protagonist decides to act"},
                {"phase": "confrontation", "title": "Escalation", "goal": "Confront the threat directly",
                 "scene_range": [7, 13], "mood": "tense", "transition_trigger": "An unexpected escalation forces the final confrontation"},
                {"phase": "climax", "title": "The Decision", "goal": "Decide the fate",
                 "scene_range": [14, 20], "mood": "desperate", "transition_trigger": ""},
            ],
            "revelations": [],
            "possible_endings": fb["3act_endings"] if fb else [
                {"type": "triumph", "description": "Victory over the threat."},
                {"type": "bittersweet", "description": "Victory at a high cost."},
                {"type": "tragedy", "description": "Downfall despite the struggle."},
            ],
            "revealed": [],
        }


def _safe_sr(act: dict, fallback_start: int = 1) -> list:
    """Return a guaranteed 2-element [start, end] scene_range from an act dict.
    Guards against missing key, None, or a 1-element array — all possible when
    the Story Architect returns a malformed scene_range (schema can no longer
    enforce minItems: 2 / maxItems: 2 due to Anthropic API restrictions)."""
    sr = act.get("scene_range") or []
    if len(sr) >= 2:
        return [sr[0], sr[1]]
    if len(sr) == 1:
        return [sr[0], sr[0] + 5]
    return [fallback_start, fallback_start + 5]


def get_current_act(game: GameState) -> dict:
    """Determine which act the story is in based on transition triggers and scene count.
    Dual logic: (1) Check if Director has signaled an act transition via trigger fulfillment,
    tracked in story_blueprint['triggered_transitions']. (2) Fallback to scene_range.
    Special case: story_complete + epilogue_dismissed → synthetic 'aftermath' phase so the
    Director and Narrator stop pushing toward a climax the player already declined."""
    bp = game.story_blueprint
    if not bp or not bp.get("acts"):
        return {"phase": "setup", "title": "?", "goal": "?", "mood": "mysterious",
                "act_number": 1, "total_acts": 3, "progress": "early",
                "approaching_end": False, "transition_trigger": ""}

    # Player dismissed the epilogue and chose to keep playing: the planned arc is done.
    # Return a synthetic act so all consumers (Director trigger, prompt builders) see
    # "aftermath" instead of endlessly repeating "climax" or "story ending in 1-2 scenes".
    if bp.get("story_complete") and getattr(game, "epilogue_dismissed", False):
        acts = bp["acts"]
        return {
            "phase": "aftermath",
            "title": "Aftermath",
            "goal": "The planned arc has concluded. The player chose to continue. "
                    "Follow their lead organically — no forced conclusions.",
            "mood": "open",
            "act_number": len(acts),
            "total_acts": len(acts),
            "progress": "open",
            "approaching_end": False,
            "transition_trigger": "",
            "scene_range": [game.scene_count, game.scene_count + 99],
        }

    acts = bp["acts"]
    scene = game.scene_count
    triggered = set(bp.get("triggered_transitions") or [])

    # Determine current act: walk through acts, advancing past those whose
    # transition_trigger has been fulfilled OR whose scene_range has been exceeded
    current = acts[0]
    act_number = 1

    for i, act in enumerate(acts[:-1]):  # Last act has no transition_trigger
        trigger = act.get("transition_trigger", "")
        sr = _safe_sr(act, fallback_start=i * 5 + 1)
        act_id = f"act_{i}"

        # Act is complete if trigger was fulfilled OR we're past its scene_range
        if act_id in triggered or scene > sr[1]:
            # Move to next act
            if i + 1 < len(acts):
                current = acts[i + 1]
                act_number = i + 2
        else:
            # Still in this act
            current = act
            act_number = i + 1
            break

    # Estimate progress within act
    sr = _safe_sr(current, fallback_start=1)
    act_len = max(sr[1] - sr[0] + 1, 1)
    scenes_in = scene - sr[0] + 1
    if scenes_in <= act_len * 0.3:
        progress = "early"
    elif scenes_in <= act_len * 0.7:
        progress = "mid"
    else:
        progress = "late"

    # Check if we're in the final act and nearing the end
    approaching_end = (act_number == len(acts) and progress in ("mid", "late"))

    return {
        **current,
        "act_number": act_number,
        "total_acts": len(acts),
        "progress": progress,
        "approaching_end": approaching_end,
    }


def get_pending_revelations(game: GameState) -> list:
    """Get revelations that are ready to be introduced but haven't been yet."""
    bp = game.story_blueprint
    if not bp or not bp.get("revelations"):
        return []
    revealed = set(bp.get("revealed") or [])
    pending = []
    for rev in bp["revelations"]:
        if rev["id"] not in revealed and game.scene_count >= rev.get("earliest_scene", 999):
            pending.append(rev)
    return pending


def mark_revelation_used(game: GameState, rev_id: str):
    """Mark a revelation as revealed."""
    if game.story_blueprint:
        game.story_blueprint.setdefault("revealed", [])
        if rev_id not in game.story_blueprint["revealed"]:
            game.story_blueprint["revealed"].append(rev_id)


def get_narration_lang(config: EngineConfig) -> str:
    """Get the English name of the configured narration language."""
    return LANGUAGES.get(config.narration_lang, "German")


def _kid_friendly_block(config: EngineConfig) -> str:
    """Return kid-friendly prompt block if enabled, else empty string."""
    if not config.kid_friendly:
        return ""
    lang = get_narration_lang(config)
    return f"""
<kid_friendly_mode>
Content is for children age 8-12. Tone reference: Studio Ghibli, Avatar: The Last Airbender, Harry Potter (early books), Legend of Zelda, Pok\u00e9mon.
- VIOLENCE: Abstract only. Enemies are "defeated", "flee", "surrender", "fall asleep", "are knocked back", "vanish in a puff of smoke". NEVER describe blood, wounds, gore, graphic injury, or killing blows. Combat feels like an animated movie or cartoon.
- DEATH: Avoid character death. Defeated characters are captured, transformed, trapped, petrified, banished, or exhausted {E['dash']} not killed. If an NPC must "die", it happens offscreen, with dignity, and is framed gently. Prefer alternatives: turned to stone, put into enchanted sleep, disappeared into another realm.
- TONE: Always hopeful. Even in dark moments, there is a way forward. The world is fundamentally good, even if challenged by adversity. Despair is temporary, never absolute.
- PROBLEMS: Focus on age-appropriate challenges: puzzles, riddles, helping others, overcoming fears, building friendships, outsmarting villains, exploring mysterious places, rescuing someone in need, solving mysteries, earning trust, fixing what is broken.
- VILLAINS: Antagonists have understandable (even sympathetic) motives. Pure evil is rare {E['dash']} misunderstanding, loneliness, fear, grief, or misguided goals drive conflict. Redemption is possible.
- FORBIDDEN: Sexual or romantic content beyond innocent friendship, substance use, profanity, nihilism, psychological torture, body horror, existential dread, graphic descriptions of suffering or decay.
- LANGUAGE: Vivid and imaginative but accessible. Mix short punchy sentences with atmospheric description. Use wonder and curiosity as primary emotional drivers. All output in {lang}.
- REWARD cleverness, courage, empathy, and teamwork over brute force.
- CRISIS/FAILURE: Frame setbacks as challenges to overcome, not hopeless situations. "You stumble and fall" not "Pain explodes through your body". The character is exhausted, not broken.
</kid_friendly_mode>
"""


def _content_boundaries_block(game: Optional[GameState] = None,
                               creation_data: Optional[dict] = None) -> str:
    """Return content boundaries prompt block if any lines/wishes are set."""
    lines = ""
    wishes = ""
    if game:
        lines = getattr(game, 'content_lines', '') or ''
        wishes = getattr(game, 'player_wishes', '') or ''
    # Fallback to creation data (during character creation, game doesn't exist yet)
    if not lines and not wishes and creation_data:
        lines = creation_data.get("content_lines", "")
        wishes = creation_data.get("wishes", "")
    if not lines and not wishes:
        return ""
    parts = ["<content_boundaries>"]
    if lines:
        parts.append(
            "<lines>\n"
            "These topics MUST NOT appear in ANY form \u2014 not in narration, NPC dialog, "
            "backstories, world-building, descriptions, implied context, or metaphor. "
            "Treat them as non-existent in this world:\n"
            f"{html.escape(lines)}\n"
            "</lines>"
        )
    if wishes:
        parts.append(
            "<player_wishes>\n"
            "These are FUTURE story elements the player wants to ENCOUNTER during gameplay — "
            "things that DON'T EXIST YET but should appear over time. "
            "CRITICAL: These are NOT established facts about the character's past. "
            "Introduce at most ONE wish element per scene. "
            "Save the rest for later scenes — the player WANTS to be surprised by when and how they appear. "
            "The opening scene should focus on establishing the world and tension; "
            "wish elements work best when they emerge unexpectedly in later scenes. "
            "Think of these as seeds to plant across the ENTIRE story arc, not a checklist for scene one:\n"
            f"{html.escape(wishes)}\n"
            "</player_wishes>"
        )
    parts.append("</content_boundaries>")
    return "\n".join(parts)


def _backstory_block(game: Optional[GameState] = None) -> str:
    """Return backstory prompt block if player provided backstory text.
    Backstory = CANON PAST: established facts, relationships, events that already happened.
    Distinct from character_concept (present identity) and player_wishes (future elements)."""
    if not game:
        return ""
    backstory = getattr(game, 'backstory', '') or ''
    if not backstory.strip():
        return ""
    return (
        "<backstory>\n"
        "ESTABLISHED CANON — these are facts about the character's PAST that are ALREADY TRUE:\n"
        "- Characters mentioned here ALREADY EXIST in the world (family, mentors, rivals, etc.)\n"
        "- Do NOT re-introduce them as strangers. If they appear, they KNOW the player character.\n"
        "- Events described here ALREADY HAPPENED. Reference them as shared history, not new revelations.\n"
        "- Relationships described here ARE ESTABLISHED. A wife is already married, a mentor already known.\n"
        "- You may REFERENCE backstory naturally (memories, motivations, NPC dialog about the past) "
        "but never CONTRADICT or REWRITE it.\n"
        f"{html.escape(backstory)}\n"
        "</backstory>"
    )


def _status_context_block(game: Optional[GameState] = None) -> str:
    """Return a narrative status context block mapping h/sp/su values to physical/mental states.
    Only injected when game is present. Tells the Narrator what the numbers MEAN narratively
    so that prose stays coherent with mechanical state — without ever mentioning numbers."""
    if not game:
        return ""
    h, sp, su = game.health, game.spirit, game.supply

    health_desc = (
        "uninjured" if h >= 5 else
        "bruised — minor aches, nothing that slows them down" if h == 4 else
        "injured — clearly hurting, moving with effort" if h == 3 else
        "seriously wounded — every motion costs something" if h == 2 else
        "critically injured — barely holding together, on the edge of collapse" if h == 1 else
        "WOUNDED — at the limit, physical collapse imminent (flag already set)"
    )
    spirit_desc = (
        "steady and composed" if sp >= 5 else
        "mildly unsettled — small cracks under the surface" if sp == 4 else
        "shaken — stress is showing, focus is harder to maintain" if sp == 3 else
        "deeply troubled — holding on by a thread, doubt and fear are present" if sp == 2 else
        "near breaking — barely functioning, the weight is crushing" if sp == 1 else
        "BROKEN — at the limit, mental collapse imminent (flag already set)"
    )
    supply_desc = (
        "well-equipped" if su >= 5 else
        "adequate — supplies are fine for now" if su == 4 else
        "running low — rationing has begun, choices are being made" if su == 3 else
        "critically short — scarcity is a real pressure" if su == 2 else
        "nearly nothing — desperation is setting in" if su == 1 else
        "DEPLETED — out of resources (flag already set)"
    )

    return (
        "<character_state>\n"
        "Reflect these states through sensory detail, body language, and atmosphere. "
        "NEVER state numbers or game terms. Maintain consistency across scenes — "
        "do NOT describe the character as healthy if they are injured, or calm if they are shaken.\n"
        f"Physical: {health_desc}\n"
        f"Mental/Emotional: {spirit_desc}\n"
        f"Resources/Equipment: {supply_desc}\n"
        "</character_state>"
    )


def get_narrator_system(config: EngineConfig, game: Optional[GameState] = None) -> str:
    """Build narrator system prompt with configured language.
    NOTE: _status_context_block (character H/Sp/Su state) is intentionally excluded here
    and injected into each user prompt instead, so this system prompt stays fully static
    per session and qualifies for Anthropic prompt caching."""
    lang = get_narration_lang(config)
    kf = _kid_friendly_block(config)
    cb = _content_boundaries_block(game)
    bs = _backstory_block(game)
    # Tone authority block — makes the player's chosen tone the dominant stylistic register.
    # Injected as a first-class element before <rules> so it outranks generic style defaults.
    tone_block = ""
    if game and getattr(game, "setting_tone", ""):
        tone_block = (
            f'\n<tone_authority tone="{_xa(game.setting_tone)}">'
            f'This is the player\'s chosen creative register for the entire story. '
            f'It governs sentence rhythm, scene energy, what details get highlighted, '
            f'how NPCs behave, and what makes a moment land. Every scene must feel it. '
            f'Follow <director_guidance> for narrative direction, but never let it '
            f'override or dilute the tone.</tone_authority>'
        )
    _quote_rule = (
        "- DIALOG QUOTES: Use German quotation marks exclusively. "
        "Opening quote: \u201e (lower-9, U+201E). Closing quote: \u201c (upper-6, U+201C). "
        "Pattern: \u201eText.\u201c \u2014 NEVER use guillemets (\u00bb\u00ab), straight ASCII quotes (\"), or any other style."
        if lang == "German" else
        "- DIALOG QUOTES: Use English curly double quotes exclusively. "
        "Opening: \u201c (U+201C). Closing: \u201d (U+201D). "
        "Pattern: \u201cText.\u201d \u2014 NEVER use guillemets, straight ASCII quotes (\"), or any other style."
    )
    return f"""<role>Narrator of an immersive RPG. All output in {lang}, second person singular.</role>
{kf}{cb}{bs}{tone_block}
<rules>
- NEVER mention dice, stats, numbers, or game mechanics
- NEVER use internal clock names in prose (e.g. "Mob Clock", "Betrayal Clock"). Threat pressure from clocks must be expressed through atmosphere, NPC behavior, and sensation — never by naming the clock.
{_quote_rule}
- MISS: concrete failure, situation worsens, NO silver linings
- WEAK_HIT: success at tangible cost
- STRONG_HIT: clean success
- NPCs act per their disposition and memories
- Introduce new NAMED characters through action and dialog. An NPC's agenda and instinct are their engine {E['dash']} let those drives shape how they behave, what they pursue, what they avoid. Distinct voice comes from specifics: vocabulary level, sentence rhythm, and what a character deflects or refuses to acknowledge. One physical trait or habitual gesture makes them tangible.
- NPC IDENTITY LAYERS: Each NPC carries two distinct layers. `instinct` is their fundamental wiring {E['dash']} how they are built, their default reaction under pressure (stable, rarely changes). `arc` is where they are in their development {E['dash']} what the story has already made of them (shifts as events accumulate). When both are present: let `instinct` determine HOW they react; let `arc` inform WHERE they are emotionally. The same instinct ("deflects with sarcasm") plays completely differently depending on arc ("beginning to trust Janus despite himself" vs "has decided Janus is too dangerous to help further"). Never flatten arc into instinct or vice versa.
- NPC EMOTIONAL RANGE: Emotional control is one option, not the default. An NPC's instinct may produce volatile, disproportionate, or irrational responses {E['dash']} sudden rage, visible panic, bitter sarcasm, stubborn silence, reckless bravado, tearful collapse, uncontrollable dark humor. Do NOT smooth all NPCs toward composure. A scene with three NPCs should not have three composed people {E['dash']} let the instinct field determine the emotional register, not a generic assumption of adult self-control.
- BACKSTORY CANON: If <backstory> is present, treat it as ESTABLISHED HISTORY. People mentioned there (family, friends, rivals) are ALREADY KNOWN to the player character {E['dash']} if they appear, they recognize the player and vice versa. NEVER introduce a backstory character as a stranger or reinterpret established relationships. Backstory events ALREADY HAPPENED {E['dash']} reference them as shared memory, not new plot. GRAMMATICAL GENDER: If the backstory uses gendered language for the player character (e.g. feminine "Spezialistin", "sie", "ihre" in German), that establishes the player character's gender for ALL narration — use consistent gendered forms throughout, regardless of any gender signal in the character_concept or player input. Backstory gender takes absolute priority over character_concept gender when they conflict.
- NPC BACKSTORY: An NPC may only reference people, events, or relationships that appear in their description, agenda, arc, or a prior scene. Do NOT invent family members, past colleagues, formative events, or personal history for an NPC that was not established anywhere in the story. If an NPC's profile is sparse, let that sparseness show — give them presence through behavior and reaction, not through newly invented biography.
- Describe only sensory impressions, never player thoughts
- SENSORY RANGE: Don't default to sight {E['dash']} include at least one non-visual sense per scene (a specific sound, smell, texture, or temperature). These anchor scenes in memory more durably than visual description alone.
- WORLD PERIPHERY: Once per scene, let one small background detail exist that has nothing to do with the player's immediate action {E['dash']} a sound from another room, a stranger's exchange, a worn object, weather shifting outside. Brief, never explained. It signals the world continues beyond this moment.
- PHRASE VARIETY: The construction "[noun] of a [person], who [relative clause]" — in German: "mit dem [abstract noun] eines/einer [noun], die/der [relative clause]" (e.g. "with the calm of a man who...", "with the stillness of a woman who...") — is a known stylistic crutch. AVOID it as a default: treat it as last resort, not a template. Use it AT MOST ONCE per response, and ONLY if no natural alternative fits. CROSS-RESPONSE: Check the preceding narrations visible in this conversation — if this pattern appeared there, do NOT use it in this response at all. SPECIFIC OVERUSE: The abstract noun "Tonfall" (tone of voice) has its own limit — if it appeared in any recent narration, replace it with something physical or behavioral. This pattern appears almost exclusively in NPC dialog attribution ("he said with the calm of a man who...") — prefer instead: a physical action before or after the speech ("He set the phone down. 'The pallets left at six.'"), a simple adverb ("He said it flatly."), a fragment of unattributed speech, or a body-registered reaction ("Her shoulders didn't move. 'That's not how it works.'"). The skeleton is detectable even when the content changes — "tone of voice / evenness / rhythm / matter-of-factness" are the same structure dressed differently. ATMOSPHERIC MOTIFS: The same risk applies to recurring sensory or mood anchors. A single dominant motif — silence, darkness, cold, a specific sound — can become the atmospheric default when it fits the tone too well. CROSS-RESPONSE: Scan the preceding narrations. If the same motif (e.g. "Stille", "Dunkelheit", "Kälte") has anchored the last two or more scenes, it is now a crutch. Replace it with a different sensory dimension: if silence has dominated, anchor the next scene in temperature, texture, or smell instead. The tone does not require the same motif every time — it requires SPECIFICITY. A horror scene built on heat and the smell of machine oil is more unsettling than the tenth scene ending in a new kind of silence. BODY AND PROP MOTIFS: The same applies to recurring physical details — an injury or pain the character carries, a reflexive gesture (a hand resting on a weapon), a recurring object. Mention such a detail at most once per response, and only when something about it changes or matters in this scene; if it already appeared in the previous narration and nothing changed, leave it out.
- SCENE CONTINUITY: Begin in motion, not in setup. The player is still in the same body, the same emotional state as the last scene ended. Do NOT open with a fresh establishing paragraph. SAME LOCATION: Open with at most one sentence that holds the atmosphere or emotional residue of the previous scene's end — a sensation still in the air, a silence not yet broken, a weight not yet lifted — before moving into the player's action. This is not recap; it is continuity of experience. It should work as a bridge even if the player's action is very brief or sparse. NEW LOCATION (player has moved — compare <location> with <prev_locations>): Open with one brief sensory impression of the new space (a sound, smell, texture, or quality of light) that grounds the reader without summarizing what came before. The new place simply exists, indifferent to what preceded it; the character carries the previous moment in their body. Example: a character arriving somewhere unfamiliar after a tense moment elsewhere — the ambient sounds and physical details of the new space are registered first, through senses still sharpened by what just happened.
- EMOTIONAL CARRY-THROUGH: If the previous scene ended with a significant emotional beat (betrayal, loss, triumph, relief, intimacy, shock), open this scene with that weight still present in the character's body language, perception, and attention. Emotional states do not reset between scenes. Show it through sensation and behavior, not through narration — the character did not process it yet.
- SCENE ENDING: Close each narration on an open moment — not a plot cliffhanger, not a resolved beat, but a suspension that makes the NEXT scene feel anchored rather than arbitrary. The character should be mid-breath, not concluded. No option lists, no suggested actions. VARY the kind of ending from scene to scene: (a) the character's unresolved inner state, (b) a concrete image or sound left hanging, (c) an NPC's unanswered line or gesture, (d) a small physical action still in progress. CROSS-RESPONSE: do not repeat the kind of ending used in the previous narration, and use (a) at most every other scene. Keep the final sentence short — one clause, ideally under 20 words; avoid long trailing constructions that weigh two possibilities ("...and you don't know whether X or Y").
- 2-4 paragraphs
- TEMPORAL CONSISTENCY: If <time> is provided, maintain that time period. Time only moves FORWARD (never backward). If you mention specific times, they must be later than any previously mentioned time. Do NOT invent specific clock times unless narratively important {E['dash']} prefer atmospheric time cues (moonlight, sunset glow, morning mist). CRITICAL: Each scene transition represents minutes to hours of in-world time, NOT days or years. Events from recent scenes just happened {E['dash']} signs don't weather, wounds are fresh, sent NPCs are still en route or just arrived. Never describe recent events or objects as aged, decayed, or long-past unless the player explicitly time-skips. TEMPORAL TEXTURE: Even in a static location where nothing moves (a besieged trench, a locked room, a stakeout), time still passes through the world. Every 2–3 scenes, anchor one detail to the shifting day: a quality of light changing (afternoon glare giving way to a cooler, flatter grey), a temperature shift (the ground cooling under your hands), a change in ambient sound (fewer birds, different distant guns, the quality of silence shifting). These do not need to be prominent — a single phrase suffices. They exist so the story does not feel frozen.
- SPATIAL CONSISTENCY: The <location> tag shows where the player currently IS. If <prev_locations> is provided, the player has LEFT those places. NEVER place the player back at a previous location unless they explicitly travel there. If an NPC has a last_seen attribute showing a DIFFERENT location than the player's current <location>, that NPC is NOT physically present {E['dash']} they cannot be heard through walls, seen, or interact directly. They can only appear if they plausibly traveled to the player's location (and the narration should describe their arrival). NPCs without last_seen or with last_seen matching <location> ARE present and can interact normally.
- If <story_arc> is present, steer scenes toward the act goal and mood. If <story_arc> contains a thematic_thread, let it surface periodically through NPC dialog, character reactions, or incidental observations {E['dash']} not as lecture or internal monologue, but as a question the world keeps quietly asking. Not every scene, but it should feel like a recurring undercurrent.
- If revelation_ready is set, weave it into the scene naturally (through NPC dialog, discovered evidence, or environmental storytelling) {E['dash']} NEVER dump exposition
- If <story_ending> is present, build toward a satisfying conclusion
- If <director_guidance> is present, follow its narrative direction. It provides strategic story guidance — use it to inform the scene's direction, NPC behavior, and pacing, while maintaining your creative voice and atmospheric style.
- If <npc_note> is present for an NPC, use it to guide that NPC's behavior and emotional state in this scene.
- If <position> is present, scale danger and atmosphere accordingly:
  controlled = calm tension, player has advantage
  risky = uncertain, things could go either way
  desperate = visceral danger, everything on the line
- If <pacing> suggests "breather", shift to a quieter, reflective tone (campfire moment, quiet conversation, calm before the storm). Still advance the story, but lower intensity.
- If <chaos_interrupt> is present, weave the specified disruption naturally into the scene. For type="dilemma", present the forced choice clearly so the player must decide next turn. For type="ticking_clock", establish the deadline or urgency so it shapes future actions. For type="positive_windfall", make it feel earned by the world, not a gift from nowhere.
- If <dramatic_question> is present, the scene should address this question (resolve or deepen it)
- If story_arc structure="kishotenketsu" and phase="ten_twist": focus on perspective SHIFT, not conflict escalation. Something seemingly unrelated recontextualizes everything.
- If story_arc structure="kishotenketsu" and phase="ketsu_resolution": the ten_twist's perspective shift has already landed — this act is CONSEQUENCE, not continued reflection. The player has absorbed the recontextualization. Each narration must now move toward something irreversible: a choice made, a system changed, a relationship permanently altered, a door closed. Do NOT keep circling the same existential insight. If the previous scene ended on reflection, this scene ends on action or consequence. The world should be visibly different by the end of this act than it was at the start of it.
- If <recent_events> is present, treat it as ESTABLISHED FACTS. These events already happened in previous scenes. NEVER contradict them {E['dash']} if an NPC was seen alive, they are alive; if a box was empty, it was empty; if a character said something, they said it. You may add new revelations or reinterpretations, but the physical facts of past scenes are canon.
- If <active_threats> is present, let the urgency level shape the atmospheric pressure of the scene. A "critical" threat should make the air feel close and time scarce. Do NOT name clocks, fill bars, or game mechanics {E['dash']} translate pressure into sensation, behavior, and detail.
- If <arc_notes> is present, use it as background awareness of where the story stands. Let it inform emotional undertone without quoting or summarizing it directly.
- If <npc_dynamics> is present, let the relationship history between NPCs shape how they speak to and about each other {E['dash']} eye contact, tone, small avoidances, or unspoken tension. Do not narrate the relationship directly; let it surface through behavior.
- PRECISION: Every sentence must earn its place {E['dash']} carry new information, advance tension, reveal character, or deepen atmosphere. Cut filler. A shorter scene with density beats a longer scene with padding. Avoid generic atmospheric throat-clearing ("The air hung heavy", "Silence stretched between them") unless it is doing specific work.
- PURE PROSE ONLY: Output ONLY narrative text. No JSON, no XML tags, no metadata, no code blocks, no markdown formatting (no *italics*, no **bold**, no # headings). Do NOT prefix your response with role labels like "Narrator:" or any heading. Do NOT append game mechanic annotations like [CLOCK CREATED: ...], [THREAT: ...], [SCENE CONTEXT: ...], or any bracketed labels — these are handled internally. Begin immediately with narrative text. Your entire response is visible to the player.
</rules>
<player_authorship>
- The PLAYER IS the character. If <player_words> is provided, these are CANONICAL.
- DIALOG: The narration MUST SHOW the player character speaking. Include their words as quoted dialog in the scene (with speech tags/body language). The player's speech MUST appear in the text BEFORE NPCs react to it.
- PRESERVE EXACTLY: Keep the player's word choices, names, spelling, and phrasing intact. If the player writes a wrong name, a typo, slang, or informal language, that IS what the character said {E['dash']} reproduce it faithfully. NEVER correct names, fix factual errors, convert numbers to words, or "improve" the player's language. The ONLY permitted changes are adding punctuation and capitalizing sentence starts.
- DESCRIBED SPEECH: If the player describes speaking WITHOUT giving exact words (e.g. "I ask him about Thornhill" or "I describe the suspect"), narrate this as INDIRECT SPEECH or brief summary {E['dash']} do NOT invent specific quoted dialog for the player character. Write "You ask him about Thornhill" or "You describe the suspect", then show the NPC's reaction. NEVER put invented words in the player character's mouth.
- ACTIONS: The narration MUST SHOW the player character performing the described action. You may add sensory detail and atmosphere, but the core action stays as stated and must be visible in the text.
- NEVER skip the player's contribution. NEVER jump straight to NPC reactions without first showing what the player character said or did.
- NPCs REACT to what the player actually said/did, not to a reinterpretation.
</player_authorship>
<style>The player is inside the world, not watching it. Integrate what the player brings seamlessly, as if it was always there.</style>"""


def call_narrator(client: anthropic.Anthropic, prompt: str,
                  game: Optional[GameState] = None,
                  config: Optional[EngineConfig] = None) -> str:
    """Narrator call with conversation memory for style consistency.
    The system prompt is sent as a cacheable content block (cache_control: ephemeral).
    Since _status_context_block is injected into user prompts instead, the system prompt
    is fully static per session — same text on every turn, maximising cache hit rate.
    Cache lifetime: 5 minutes, refreshed on each hit. Break-even at the 2nd hit."""
    log(f"[Narrator] Calling narrator (prompt: {len(prompt)} chars)")
    messages = []

    # Include last 3 narrations as conversation context.
    # Most recent narration is kept in full (scene continuation needs complete context);
    # older entries are truncated to MAX_NARRATION_CHARS to control prompt size.
    if game and game.narration_history:
        history_slice = game.narration_history[-3:]
        for i, entry in enumerate(history_slice):
            is_most_recent = (i == len(history_slice) - 1)
            narr_text = entry["narration"] if is_most_recent else entry["narration"][:MAX_NARRATION_CHARS]
            messages.append({"role": "user", "content": entry.get("prompt_summary",
                             "Continue the story.")})
            messages.append({"role": "assistant", "content": narr_text})

    # Current prompt
    messages.append({"role": "user", "content": prompt})

    # System prompt as cacheable content block.
    # cache_control: ephemeral = 5-minute server-side cache, refreshed on each hit.
    # Requires the system text to be identical across calls — guaranteed because
    # _status_context_block was moved to user prompts, leaving system fully static.
    system = _cached_system(get_narrator_system(config or EngineConfig(), game))

    response = _api_create_with_retry(
        client, max_retries=5,
        model=NARRATOR_MODEL, max_tokens=NARRATOR_MAX_TOKENS,
        system=system,
        messages=messages,
    )
    raw = _response_text(response)
    stop = response.stop_reason

    # Handle truncation: clean up to last complete sentence
    if stop == "max_tokens":
        log(f"[Narrator] WARNING: Response truncated at max_tokens ({len(raw)} chars)",
            level="warning")
        raw = _salvage_truncated_narration(raw)
    else:
        # Detect mid-sentence/mid-word cutoff despite end_turn (rare Sonnet bug)
        _prose = raw[:raw.find('<game_data>')] if '<game_data>' in raw else raw
        _stripped = _prose.rstrip()
        if _stripped and _stripped[-1] not in '.!?"\u201c\u201d\u00bb\u00ab\u2026)\u2013\u2014*':
            log(f"[Narrator] WARNING: Response appears truncated despite end_turn "
                f"({len(raw)} chars, ends with '{_stripped[-20:]}')", level="warning")
            raw = _salvage_truncated_narration(raw)

    log(f"[Narrator] Raw response ({len(raw)} chars): {raw[:500]}")
    # Log if game_data present (opening scene/chapter only)
    if '<game_data>' in raw:
        log(f"[Narrator] Found <game_data> tag (opening/chapter scene)")
    # Fix Cyrillic homoglyphs (LLMs occasionally emit е instead of e, с instead of s, etc.)
    raw = _fix_cyrillic_homoglyphs(raw)
    return raw


def _salvage_truncated_narration(raw: str) -> str:
    """Clean up a truncated narrator response so it ends at a natural break.
    Preserves any complete game_data tag (opening scenes), trims prose to last full sentence."""
    # Check for incomplete game_data at the end (tag opened but not closed)
    last_open = raw.rfind('<game_data>')
    if last_open != -1 and raw.find('</game_data>', last_open) == -1:
        raw = raw[:last_open].rstrip()
        log(f"[Narrator] Removed incomplete <game_data> from truncated response")

    # Find the prose portion (before any game_data tag)
    prose_end = len(raw)
    idx = raw.find('<game_data>')
    if idx != -1 and idx < prose_end:
        prose_end = idx

    prose = raw[:prose_end]
    metadata = raw[prose_end:]

    # Trim prose to last complete sentence
    # Look for sentence-ending punctuation followed by space or quote or end
    last_sentence = -1
    for pattern in ['. ', '." ', '."\n', '."', '.»', '.\n\n',
                    '! ', '!" ', '!"', '!\n\n',
                    '? ', '?" ', '?"', '?\n\n',
                    '…', '…"', '… ']:
        idx = prose.rfind(pattern)
        if idx != -1:
            end = idx + len(pattern)
            if end > last_sentence:
                last_sentence = end

    # Also check for sentence ending at very end of prose
    stripped = prose.rstrip()
    if stripped and stripped[-1] in '.!?':
        last_sentence = max(last_sentence, len(stripped))
    if stripped.endswith(('."', '!"', '?"', '.»', '!»', '?»')):
        last_sentence = max(last_sentence, len(stripped))

    # Keep trimmed version if we preserve at least 30 chars of prose
    if last_sentence > 30 and last_sentence < len(prose):
        trimmed = prose[:last_sentence].rstrip()
        log(f"[Narrator] Trimmed truncated prose: {len(prose)} → {len(trimmed)} chars")
        prose = trimmed

    return prose + metadata


def call_narrator_metadata(client: anthropic.Anthropic, narration: str,
                           game: GameState,
                           config: Optional[EngineConfig] = None) -> dict:
    """Extract structured metadata from narrator prose via Haiku (Two-Call pattern).
    Returns guaranteed-valid dict matching NARRATOR_METADATA_SCHEMA."""
    lang = get_narration_lang(config or EngineConfig())

    # Build compact NPC reference list for the extractor
    # Include location + short description to help disambiguate similar names
    npc_refs = []
    for n in game.npcs:
        if n.get("status") not in ("active", "background", "deceased", "lore"):
            continue
        entry = f'{n["id"]}={html.escape(n["name"])}'
        if n.get("aliases"):
            entry += f' (aka {html.escape(", ".join(n["aliases"]))})'
        if n.get("status") == "deceased":
            entry += ' [DECEASED]'
        elif n.get("status") == "lore":
            entry += ' [LORE]'
        # Location hint for spatial disambiguation
        npc_loc = n.get("last_location", "")
        if npc_loc:
            entry += f' [at:{html.escape(npc_loc)}]'
        # Short description for identity disambiguation
        desc = n.get("description", "")
        if desc:
            entry += f' — {html.escape(desc[:60])}'
        npc_refs.append(entry)

    system = f"""You are a metadata extractor for an RPG engine. Analyze the narration and extract game state changes.
All text fields (event, description, scene_context) MUST be in {lang}.
scene_context: 1 sentence capturing current situation AND dominant mood/tension — not just where/who, but the atmosphere. Example: "Negotiations at a standstill, the guard's suspicion barely concealed." Extract from the narration; do not invent.
emotional_weight must be ONE of: neutral, curious, wary, angry, grateful, suspicious, terrified, loyal, conflicted, betrayed, devastated, euphoric.
disposition must be ONE of: neutral, friendly, distrustful, hostile, loyal.
time_update must be ONE of: early_morning, morning, midday, afternoon, evening, late_evening, night, deep_night — or null if no time change. Detect time shifts from ANY atmospheric cue in the narration, not only explicit clock references. Qualifying signals include: light quality changing (dimming, brightening, lengthening shadows, flat grey replacing direct sunlight), temperature shift (air cooling, ground still warm from earlier sun), ambient sound changing (different insect or bird pattern, silence taking on a different character, guns sounding farther or nearer), or a character noticing the time implicitly ("it had grown darker", "the cold was settling in"). Do NOT require the words "evening" or "night" — sensory evidence is sufficient. Also advance by one phase when the scene covers activity that plainly takes an hour or more (a long search, waiting, travel, extended work), even without light or sound cues. Return null only when the scene is explicitly immediate (seconds after the last scene) with no environmental time signal and no time-consuming activity.
location_update: new location name if the character MOVED to a different place, null if they stayed. IMPORTANT: if no movement occurred, always return null — do NOT add city names, qualifiers, or extra words to the existing location. If a move did occur, use the exact place name as it appears in the narration (short and specific, e.g. "The Cathedral", not "The Cathedral in Lyon").
npc_renames: for identity REVEALS — when an NPC's true or personal name is established for the first time. Covers: spy unmasked, alias discovered, AND descriptor-named NPCs who receive a real name (e.g. "The Woman in the Wool Hat" → "Hanna", "The Unknown Man" → "Klaus", "The Engineer" → "Sara Novak"). Use the npc_id of the descriptor NPC from the known list and set new_name to the revealed personal name. NOT for surname additions to an already-named NPC (use npc_details for that).
npc_details: for newly established facts about ALREADY KNOWN NPCs only (surname addition, role change). full_name if name extended, description if role/situation changed. NEVER use npc_details to introduce a character who is new to the story — even if they share role similarities with an existing NPC. Characters new to the story always go into new_npcs with a full description.
new_npcs: ONLY for characters who are PHYSICALLY PRESENT in the scene AND actively interacting (speaking, acting, reacting). They must NOT already be in the known NPC list. NEVER include the player character. NEVER include:
- Characters who are only MENTIONED in conversation, stories, or memories
- Deceased persons (people discussed as dead, seen only in photos/flashbacks)
- Historical or absent figures (people talked about but not physically there)
- Unnamed characters described only by role ("a waiter", "some guard") unless they speak or interact meaningfully
If a NAMED person is mentioned in dialog but a DIFFERENT unnamed person is physically present, create the NPC for the PHYSICAL person with their own appropriate name/description — do NOT assign the mentioned person's name to the physical person's description.
description must be a PHYSICAL/ROLE description (appearance, occupation, species), NOT what they did in this scene.
deceased (in new_npcs): set to true if this newly introduced NPC dies in the same scene they first appear. They cannot be added to deceased_npcs by npc_id (no ID has been assigned yet), so this flag is the only way to record an introduction-and-death in the same scene. Omit or set false if they survive.
memory_updates: for EACH NPC who participated in or witnessed this scene. Use their npc_id from the known list. For a character you are introducing in THIS response (listed in new_npcs), set npc_id to "NEW" and new_npc_name to exactly the name you used in new_npcs; for every other entry new_npc_name is null. NEVER create memory_updates for the player character. NEVER create memory_updates for NPCs marked [DECEASED]. For NPCs physically present and alive in the scene, use absent=false (the default case). EXCEPTION — absent=true: You MAY add a single memory_update with absent=true for an off-screen NPC if ALL of the following apply: (1) the narration EXPLICITLY names them, (2) their off-screen situation changed in a narratively significant way (e.g. confirmed transported, captured, endangered, made a decision that affects the story), (3) they are a named NPC already tracked in the known list — lore NPCs are excluded (they have their own tracking system); do not use for unnamed or vaguely-described characters. Limit: at most 2 absent=true entries per scene. Absent memories must describe what happened TO or ABOUT the NPC, not the player's reaction to it. Do NOT use absent=true for NPCs who are merely mentioned in passing conversation.
NPC DISAMBIGUATION: The known_npcs list shows each NPC's last known location [at:...] and a short description. When the narration uses a name or descriptor that could match multiple NPCs, prefer the NPC whose location matches <current_location> or who is described as being physically present. An NPC [at:FarAwayPlace] is unlikely to appear at <current_location> without the narration explicitly describing their arrival.
about_npc (in memory_updates): If the memory is primarily ABOUT ANOTHER NPC (not the player), set about_npc to that other NPC's npc_id from the known list (characters new in this scene cannot be referenced here — use null). Examples: NPC A is told something about NPC B → memory on A with about_npc=B's id. NPC A witnesses NPC B doing something → memory on A with about_npc=B's id. If the memory is about the player or a general event, set about_npc to null.
IMPORTANT: If the player directly tells an NPC something about another NPC (gossip, warning, lie, compliment, romantic suggestion), this MUST be captured as its own memory_update with about_npc set — even if other events also happened to that NPC in the same scene. An NPC can have multiple memories per scene if distinctly different events occurred.
deceased_npcs: list NPCs (by npc_id) whose death is DEPICTED BY THE NARRATOR as it happens. This includes BOTH explicit deaths AND deaths described through physical sensation or literary language. Qualifying descriptions include: they collapse / are killed / stop breathing / go limp / their movement stops and does not resume / resistance ceases permanently / consumed by fire / destroyed / pulled under with no return described / body goes still / the struggle ended. LITERARY deaths count: e.g. "the legs kicked twice and then were still" or "the resistance left them" or "they ceased" — if the prose makes clear that a living character has become permanently non-living, mark them deceased. The death does not need to use the words "dead" or "died" — physical cessation described as final qualifies.
CRITICAL: Do NOT mark an NPC as deceased if their death is only CLAIMED, REPORTED, or ALLEGED by another character in dialog (e.g. someone says "Leo is dead"). Dialog claims about death are unreliable — characters lie, bluff, or may be wrong. Only narrator-confirmed deaths count — the player character need not have directly witnessed the death; it suffices that the narrator depicts or unambiguously confirms the outcome (e.g. an NPC goes permanently silent after a lethal event at their location, the narrator describes the absence of a presence that was there before). Never include NPCs already marked [DECEASED].
lore_npcs: ONLY for named persons established in this scene as historically or narratively significant, but who have NEVER been and are NOT NOW physically present. Use this for dead mentors whose legacy drives the story, missing persons whose fate is central, historical figures whose past actions echo into the present. Rules: (1) They must be NAMED and clearly significant — not just mentioned in passing. (2) Do NOT use for corpses or physically present characters — use new_npcs for those, even if dead. (3) Do NOT include NPCs already marked [LORE] or any other marker in the known_npcs list — they are already tracked. (4) Only add when the narration establishes them as relevant to the ongoing story. NPCs marked [LORE] in known_npcs can receive memory_updates using their npc_id.
exited_npc_ids: list the npc_id of each NPC whose PHYSICAL DEPARTURE from the scene was explicitly described in this narration — they walked out, left through a door, were escorted away, said goodbye and left. Use their npc_id from the known_npcs list. Do NOT include: NPCs who are merely mentioned or talked about; NPCs who were never present; NPCs who only paused at a door but the narration ends with them still present. Empty list if no explicit departures occurred.
CROSS-FIELD CONSISTENCY — check before submitting: If your scene_context describes an NPC as dying or dead (e.g. "while X dies", "X's last breath", "X stirbt", "während X stirbt", "X ist tot", "X's breathing stops", "X ceased", "X's struggle ended"), that NPC MUST appear in deceased_npcs. Your own scene_context is authoritative evidence — if you wrote that someone is in the act of dying there, they belong in deceased_npcs. This catches slow or literary deaths that span multiple scenes: even if the character was only "dying" last turn, once the final cessation is depicted (breathing stops, body stills, the transition completes), mark them deceased now."""

    # Static per session (only the narration language varies per game) → cacheable.
    # Cached from 512 tokens on Haiku 5.5 (see CACHE_MIN_TOKENS); on models with a
    # higher floor the marker costs nothing and the prompt is processed uncached.
    system = _cached_system(system)

    prompt = f"""<narration>{narration}</narration>
<player_character>{html.escape(game.player_name)}</player_character>
<known_npcs>{chr(10).join(npc_refs) if npc_refs else '(none)'}</known_npcs>
<current_location>{html.escape(game.current_location or 'unknown')}</current_location>
<current_time>{html.escape(game.time_of_day or 'unknown')}</current_time>
Extract all metadata from the narration above. Remember: {html.escape(game.player_name)} is the PLAYER CHARACTER, not an NPC."""

    try:
        dyn_schema = _metadata_schema_for(game)
        response = _structured_create(
            client, dyn_schema, NARRATOR_METADATA_SCHEMA, max_retries=2,
            model=BRAIN_MODEL, max_tokens=METADATA_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        metadata = json.loads(_response_text(response))
        # Guard: schema minLength:1 is not enforced server-side when the model
        # returns an empty string due to a transient glitch.  One retry is
        # sufficient — if it fails again the exception fallback below handles it.
        if not metadata.get("scene_context", "").strip():
            log("[Metadata] scene_context empty on first attempt — retrying", level="warning")
            response2 = _structured_create(
                client, dyn_schema, NARRATOR_METADATA_SCHEMA, max_retries=1,
                model=BRAIN_MODEL, max_tokens=METADATA_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            metadata2 = json.loads(_response_text(response2))
            if metadata2.get("scene_context", "").strip():
                metadata = metadata2
                log("[Metadata] scene_context recovered on retry")
            else:
                log("[Metadata] scene_context still empty after retry — keeping first result",
                    level="warning")
        log(f"[Metadata] Extracted: {len(metadata.get('memory_updates', []))} memories, "
            f"{len(metadata.get('new_npcs', []))} new NPCs, "
            f"{len(metadata.get('lore_npcs', []))} lore figures, "
            f"{len(metadata.get('deceased_npcs', []))} deceased, "
            f"{len(metadata.get('exited_npc_ids', []))} exited, "
            f"loc={metadata.get('location_update')}, time={metadata.get('time_update')}")
        return metadata
    except Exception as e:
        log(f"[Metadata] Extraction failed: {e}", level="warning")
        return {"scene_context": "", "location_update": None, "time_update": None,
                "memory_updates": [], "new_npcs": [], "npc_renames": [], "npc_details": [],
                "deceased_npcs": [], "lore_npcs": [], "exited_npc_ids": []}


def call_revelation_check(client: anthropic.Anthropic, narration: str,
                          revelation: dict,
                          config: Optional[EngineConfig] = None) -> bool:
    """Check whether the narrator actually wove a pending revelation into the narration.

    Called after call_narrator_metadata() when pending_revs was non-empty.
    Returns True if the revelation was meaningfully present (and should be marked used),
    False if the narrator skipped or barely touched it (stays pending for next scene).

    Uses Haiku + Structured Outputs — fast, cheap, single boolean output.
    On any failure, returns True (safe default: avoid infinite pending loops).
    """
    lang = get_narration_lang(config or EngineConfig())
    rev_content = revelation.get("content", "")
    rev_weight = revelation.get("dramatic_weight", "medium")

    system = (
        f"You are a story-consistency checker for an RPG engine. "
        f"Your task is to determine whether a specific revelation was meaningfully "
        f"present in a narrator's prose passage.\n\n"
        f"A revelation is considered CONFIRMED (revelation_confirmed=true) when:\n"
        f"- The core insight or twist is clearly present in the narration, OR\n"
        f"- It is strongly and unambiguously foreshadowed (not just vaguely hinted), OR\n"
        f"- A character explicitly reveals information that matches the revelation content.\n\n"
        f"A revelation is NOT confirmed (revelation_confirmed=false) when:\n"
        f"- The narration does not touch on the revelation at all, OR\n"
        f"- Only a very superficial or incidental reference appears that a reader "
        f"would not recognise as the revelation.\n\n"
        f"The narration is in {lang}. Reason in {lang} if helpful, but the JSON fields "
        f"must always be populated."
    )

    prompt = (
        f"<revelation weight=\"{rev_weight}\">{html.escape(rev_content)}</revelation>\n\n"
        f"<narration>{narration}</narration>\n\n"
        f"Was this revelation meaningfully present in the narration above?"
    )

    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=REVELATION_CHECK_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {
                "type": "json_schema",
                "schema": REVELATION_CHECK_SCHEMA,
            }},
        )
        result = json.loads(_response_text(response))
        confirmed = result.get("revelation_confirmed", True)
        reasoning = result.get("reasoning", "")
        log(f"[Revelation] Check for '{revelation.get('id', '?')}': "
            f"confirmed={confirmed} — {reasoning}")
        return confirmed
    except Exception as e:
        log(f"[Revelation] Check failed ({type(e).__name__}: {e}), "
            f"defaulting to confirmed=True to avoid pending loop", level="warning")
        return True


def call_opening_metadata(client: anthropic.Anthropic, narration: str,
                          game: GameState,
                          config: Optional[EngineConfig] = None,
                          known_npcs: Optional[list] = None) -> dict:
    """Extract structured opening/chapter metadata via Haiku Structured Outputs.

    Replaces inline <game_data> JSON from the narrator.  Produces full NPC
    schema (agenda, instinct, secrets) plus clocks, location, scene_context,
    and time_of_day — guaranteed-valid JSON matching OPENING_METADATA_SCHEMA.

    For chapter openings, *known_npcs* is the list of returning NPCs so the
    extractor only creates entries for genuinely NEW characters.
    """
    lang = get_narration_lang(config or EngineConfig())

    # Build known-NPC reference for chapter openings
    known_block = "(none)"
    if known_npcs:
        parts = []
        for n in known_npcs:
            entry = f'{html.escape(n.get("name", "?"))} ({n.get("disposition", "neutral")})'
            if n.get("aliases"):
                entry += f' aka {html.escape(", ".join(n["aliases"]))}'
            parts.append(entry)
        known_block = "\n".join(parts)

    system = f"""You are a game-state extractor for an RPG engine. Analyse the opening narration and extract ALL characters and world elements into structured data.
All text fields MUST be in {lang}.

NPCs:
- Extract EVERY named character who appears in the narration (speaking, acting, described).
- NEVER include the player character ({game.player_name}).
- Each NPC needs: name, a one-sentence PHYSICAL/ROLE description (appearance, occupation — NOT actions), agenda (hidden goal driving their behaviour), instinct (typical reaction when challenged or stressed), secrets (1-2 hidden facts the player doesn't know yet), disposition (neutral|friendly|distrustful|hostile|loyal).
- For agenda/instinct/secrets: infer plausible values from the narration context, genre ({game.setting_genre}), and tone ({game.setting_tone}). Be specific and narratively interesting.
- instinct is the NPC's psychological signature under real pressure — what they specifically do when their normal strategy fails, what betrays them, what is slightly irrational but inevitable given who they are. It is NOT job demeanor, genre convention, or generic adult competence. BAD: "stays calm under pressure" / "methodical and efficient" / "evaluates consequences before acting" — these describe a role, not a person. GOOD: "goes very quiet and hyper-precise when cornered — precision as a defense mechanism" / "agrees in the moment, then quietly does exactly what he intended" / "deflects with dark humor until something breaks, then overcorrects with raw honesty". SELF-CHECK before writing each instinct: could this apply to any competent professional in this genre? If yes, go deeper — find the specific human underneath the competence. IMPORTANT: what you see in the narration is situational behavior, not wiring — a character who appears composed in a tense scene may have barely-controlled panic underneath; infer the person, not the performance.
- Do NOT extract NPCs that are already in the known NPC list below.

Clocks:
- Extract threat clocks mentioned or implied. A threat clock tracks a looming danger.
- Each clock: name, clock_type (usually "threat"), segments (4-8), filled (typically 1 for new clocks), trigger_description (what happens when filled), owner ("world" or NPC name).
- If no clock is obvious, create one based on the central tension of the scene.

Location: the specific location where the scene takes place.
scene_context: 1 sentence capturing the current situation AND dominant mood/tension — not just where/who, but the atmosphere. Example: "Strangers in a hostile tavern, an uneasy truce already fraying at the edges." Extract from the narration; do not invent.
time_of_day: one of early_morning|morning|midday|afternoon|evening|late_evening|night|deep_night, or null if unclear.
deceased_npcs: list any characters from the npcs list above who die in this opening scene. Write the character's FULL NAME exactly as it appears in the npcs list above — do NOT invent IDs like "npc_1". Only include characters whose death is clearly depicted in the narration — not characters merely mentioned as dead before the scene, or historical figures. Leave empty if no one dies.

<known_npcs>
{known_block}
</known_npcs>"""

    prompt = f"""<narration>{narration}</narration>
<player_character>{html.escape(game.player_name)}</player_character>
<current_location>{html.escape(game.current_location or 'unknown')}</current_location>
Extract all NPCs, clocks, location, scene context, and time of day from the opening narration above."""

    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=OPENING_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {
                "type": "json_schema",
                "schema": OPENING_METADATA_SCHEMA,
            }},
        )
        data = json.loads(_response_text(response))
        log(f"[OpeningMeta] Extracted: {len(data.get('npcs', []))} NPCs, "
            f"{len(data.get('clocks', []))} clocks, "
            f"loc={data.get('location')}, time={data.get('time_of_day')}")
        return data
    except Exception as e:
        log(f"[OpeningMeta] Extraction failed: {e}", level="warning")
        return {"npcs": [], "clocks": [], "location": "",
                "scene_context": "", "time_of_day": None, "deceased_npcs": []}


def _resolve_slug_refs(game: GameState, mem_updates: list, fresh_npcs: list):
    """Rewrite memory_update npc_ids that are snake_case slugs for freshly created NPCs.

    When the Metadata Extractor creates new_npcs AND memory_updates in the same
    response, it can't know the assigned npc_ids. It invents slugs like
    'frau_seidlitz' or 'moderator_headset'. This function matches those slugs
    against the NPCs just created by _process_new_npcs using word-set overlap.

    Example: 'moderator_headset' → words {'moderator','headset'}
             'Moderator mit Headset' → words {'moderator','mit','headset'}
             All ref words found → match → rewrite npc_id to assigned ID.
    """
    # Build lookup: word-set → npc for freshly created NPCs
    # Also build name-slug → npc for exact slug matches
    known_ids = {n["id"] for n in game.npcs}

    for u in mem_updates:
        ref = u.get("npc_id", "")
        if not ref:
            continue
        # Already resolvable? Skip.
        if ref in known_ids or any(n.get("name", "").lower() == ref.lower() for n in game.npcs):
            continue
        # Normalize: underscores to spaces, lowercase, split into words
        ref_words = set(ref.lower().replace("_", " ").split())
        if not ref_words:
            continue

        best_npc = None
        best_score = 0
        for npc in fresh_npcs:
            npc_words = set(npc["name"].lower().split())
            # All ref words must appear in the NPC name
            if ref_words <= npc_words:
                # Score: proportion of NPC name words covered (prefer tighter matches)
                score = len(ref_words) / len(npc_words) if npc_words else 0
                if score > best_score:
                    best_score = score
                    best_npc = npc
            # Also check aliases
            for alias in npc.get("aliases", []):
                alias_words = set(alias.lower().split())
                if ref_words <= alias_words:
                    score = len(ref_words) / len(alias_words) if alias_words else 0
                    if score > best_score:
                        best_score = score
                        best_npc = npc

        if best_npc and best_score > 0:
            log(f"[Metadata] Resolved slug '{ref}' → '{best_npc['name']}' "
                f"({best_npc['id']}, score={best_score:.2f})")
            u["npc_id"] = best_npc["id"]


def _apply_narrator_metadata(game: GameState, metadata: dict,
                              scene_present_ids: set = None,
                              world_addition: str = ""):
    """Apply structured metadata from the metadata extractor to game state.
    scene_present_ids: set of NPC IDs that were activated or mentioned in the scene.
    If provided, deceased reports are restricted to present NPCs (prevents
    false positives from dialog claims like 'Leo ist tot').
    world_addition: Brain's world_addition text, threaded to _process_npc_details
    as a description fallback for stubs created by the identity-reveal guard."""
    # Scene context (always present)
    ctx = metadata.get("scene_context", "").strip()
    if ctx:
        game.current_scene_context = ctx
    else:
        log("[Metadata] scene_context empty — current_scene_context unchanged", level="warning")

    # Location update — count this scene at the current place first; a real move
    # (here or via the Brain before the Narrator) resets the counter.
    game.scenes_at_location += 1
    new_loc = metadata.get("location_update")
    if new_loc and new_loc.strip().lower() not in ("none", "null", "same", ""):
        update_location(game, new_loc.strip())

    # Time update
    new_time = (metadata.get("time_update") or "").strip().lower().replace(" ", "_")
    if new_time in TIME_PHASES and new_time != game.time_of_day \
            and _is_forward_time(game.time_of_day, new_time):
        game.time_of_day = new_time
        game.time_unchanged_scenes = 0
    else:
        if new_time in TIME_PHASES and new_time != game.time_of_day:
            log(f"[Time] Rejected backward time_update {game.time_of_day} → {new_time}",
                level="warning")
        game.time_unchanged_scenes += 1
        if game.time_of_day in TIME_PHASES and \
                game.time_unchanged_scenes >= TIME_AUTO_ADVANCE_SCENES:
            old_time = game.time_of_day
            advance_time(game, "moderate")
            log(f"[Time] Auto-advanced {old_time} → {game.time_of_day} after "
                f"{TIME_AUTO_ADVANCE_SCENES} scenes without a time change")

    # NPC renames (delegate to existing logic via JSON roundtrip)
    renames = metadata.get("npc_renames", [])
    # Capture lore IDs BEFORE renames run — _process_npc_renames → _merge_npc_identity
    # can promote lore→active, which would make the ID invisible to the guard's
    # pre_turn_lore_ids exemption if captured afterward.
    pre_lore_ids = {n["id"] for n in game.npcs if n.get("status") == "lore"}
    if renames:
        _process_npc_renames(game, json.dumps(renames, ensure_ascii=False))

    # New NPCs
    new_npcs = metadata.get("new_npcs", [])
    pre_npc_ids = {n["id"] for n in game.npcs}
    if new_npcs:
        _process_new_npcs(game, json.dumps(new_npcs, ensure_ascii=False))
    # Snapshot after new_npcs but before lore so slug resolution only matches
    # freshly-created physical NPCs, not lore figures added afterward.
    post_new_npc_ids = {n["id"] for n in game.npcs}

    # Resolve the intro_deceased list early (name-matching window is valid here),
    # but the actual _process_deceased_npcs call is deferred until AFTER
    # _apply_memory_updates(). Reason: _apply_memory_updates() resurrects any
    # NPC marked deceased if the extractor wrote memories for them (force=True).
    # An NPC that was created and killed in the same scene legitimately has
    # memories — they should be stored, but the NPC must end up deceased.
    intro_deceased = []
    for nd in new_npcs:
        if nd.get("deceased"):
            matched = next(
                (n for n in game.npcs
                 if n["id"] not in pre_npc_ids
                 and n["id"] in post_new_npc_ids
                 and _normalize_for_match(n["name"]) == _normalize_for_match(nd["name"])),
                None,
            )
            if matched:
                intro_deceased.append({"npc_id": matched["id"]})
                log(f"[NPC] New NPC '{matched['name']}' flagged deceased=true in same scene")

    # Lore figures (historically significant, never physically present)
    lore_npcs = metadata.get("lore_npcs", [])
    if lore_npcs:
        _process_lore_npcs(game, lore_npcs)

    # Resolve memory_update references that use invented snake_case slugs
    # for NPCs that were just created in this same metadata cycle.
    # The Extractor can't know the assigned npc_ids for new NPCs, so it
    # invents slugs like "frau_seidlitz" or "moderator_headset" instead.
    # npc_id="NEW" entries (enum schema) → name refs for the NPCs just created
    mem_updates = _resolve_new_npc_refs(metadata.get("memory_updates", []) or [])
    if mem_updates and new_npcs:
        freshly_created = [n for n in game.npcs if n["id"] not in pre_npc_ids
                           and n["id"] in post_new_npc_ids]
        if freshly_created:
            _resolve_slug_refs(game, mem_updates, freshly_created)

    # NPC details (sanitize nulls → empty strings before delegation)
    details = metadata.get("npc_details", [])
    if details:
        for d in details:
            if d.get("full_name") is None:
                d["full_name"] = ""
            if d.get("description") is None:
                d["description"] = ""
        _process_npc_details(game, json.dumps(details, ensure_ascii=False), world_addition=world_addition)

    # Deceased NPCs reported for THIS scene are marked after the memory updates
    # (see below): _apply_memory_updates() resurrects NPCs that are deceased when
    # it stores a memory for them — correct for NPCs who died in an earlier scene
    # and reappear, but it undid every death whose dying moment got a memory.
    deceased = metadata.get("deceased_npcs", [])

    # Exit tracking: mark NPCs who physically departed the scene as suppressed for
    # the next scene. activate_npcs_for_prompt() will skip 'recent' re-activation
    # for these NPCs unless the player explicitly references them.
    exited_ids = metadata.get("exited_npc_ids", [])
    for npc_id in exited_ids:
        npc = _find_npc(game, npc_id)
        if npc and npc.get("status") in ("active", "background"):
            npc["absent_until_scene"] = game.scene_count + 1
            log(f"[Metadata] NPC '{npc['name']}' exited scene — "
                f"activation suppressed until scene {npc['absent_until_scene']}")

    # Memory updates (mem_updates was already read above for slug resolution;
    # same list reference — _resolve_slug_refs may have patched npc_ids in-place)
    if mem_updates:
        _apply_memory_updates(game, json.dumps(mem_updates, ensure_ascii=False),
                              scene_present_ids=scene_present_ids,
                              pre_turn_npc_ids=pre_npc_ids,
                              pre_turn_lore_ids=pre_lore_ids)

    # Deferred: mark NPCs killed in this scene (known NPCs and NPCs created AND
    # killed in the same scene) as deceased. Must run after _apply_memory_updates()
    # — that function resurrects any deceased NPC it finds memories for
    # (force=True). Running before it would have the marking silently undone.
    # The memories ARE valid (the NPC acted in the scene); the NPC just has to
    # end up deceased afterward.
    if deceased:
        _process_deceased_npcs(game, deceased, scene_present_ids=scene_present_ids)
    if intro_deceased:
        _process_deceased_npcs(game, intro_deceased, scene_present_ids=scene_present_ids)

    # Fallback death detection: catches off-screen deaths that the extractor's
    # physically-witnessed rule would miss (e.g. death heard but not seen by the
    # player character). Runs after all memories are stored so cross-NPC signals
    # are complete. See _check_death_corroboration() for threshold logic.
    _check_death_corroboration(game)

    # Staleness retirement: demote NPCs that have been narratively silent for
    # NPC_STALE_SCENES scenes regardless of active count. Runs here so that
    # last_memory_scene is fully updated for this turn before the check fires.
    # Also serves as the primary hook for sessions that rarely add new NPCs
    # (the _process_new_npcs call-site would miss most turns without this).
    _retire_distant_npcs(game)
    # Renames/merges above may have left clock owners on a former name
    _sync_clock_owners(game, "Metadata")


def _process_deceased_npcs(game: GameState, deceased_list: list,
                           scene_present_ids: set = None):
    """Mark NPCs as deceased based on metadata extractor report.
    Sets status='deceased' — this excludes them from all active processing:
    prompts, memories, reflections, sidebar, reactivation.
    If scene_present_ids is provided, only NPCs that were activated OR mentioned
    in this scene can be marked deceased. This prevents false positives from
    dialog claims (e.g. an NPC saying 'Leo is dead') while still allowing
    deaths of NPCs who were scene-relevant but below full activation threshold."""
    for entry in deceased_list:
        npc_id = entry.get("npc_id", "")
        if not npc_id:
            continue
        npc = _find_npc(game, npc_id)
        if not npc:
            log(f"[NPC] Deceased report for unknown NPC: '{npc_id}'", level="warning")
            continue
        if npc.get("status") == "deceased":
            continue  # Already marked
        # Presence guard: NPC must have been in-scene to die on-screen
        if scene_present_ids is not None and npc["id"] not in scene_present_ids:
            # Allow if NPC was just introduced this scene (walk-in + die edge case).
            # Off-screen mentions (type "mention") are not presence — otherwise a
            # dialog claim about an absent NPC would pass the guard.
            has_current_scene_memory = any(
                m.get("scene") == game.scene_count and m.get("type") != "mention"
                for m in npc.get("memory", [])
            )
            if not has_current_scene_memory:
                log(f"[NPC] Deceased report REJECTED for '{npc['name']}' — "
                    f"not present in scene {game.scene_count} (likely a dialog claim)",
                    level="warning")
                continue
        old_status = npc.get("status", "active")
        npc["status"] = "deceased"
        log(f"[NPC] Marked as deceased: {npc['name']} ({npc['id']}, was {old_status})")


def _check_death_corroboration(game: GameState):
    """Fallback death detection for off-screen deaths the metadata extractor missed.

    The primary deceased_npcs detection requires a physically-witnessed death.
    This catches the complementary case: an NPC dies off-screen (e.g. heard but
    not seen), but two independent memory signals written in the same scene
    corroborate it:

      Cross-NPC vote: another NPC wrote an observation about NPC X this scene with
        importance >= 9 and emotional_weight in {betrayed, devastated} via about_npc.
      Self-vote: NPC X's own observation this scene has importance >= 9 and
        emotional_weight == devastated (total devastation, near-exclusive to death).

    Threshold: at least 1 cross-NPC vote AND total votes >= 2.
    This prevents false positives from a single traumatic-but-non-lethal event
    (e.g. a massive betrayal that devastates only one side).

    Known edge case: a catastrophic betrayal (not death) where NPC A writes a
    memory about NPC X with about_npc=X + w=betrayed/devastated + imp=9 AND NPC X
    writes a self-memory with w=devastated + imp=9 (about=null) will trigger the
    threshold. In practice the extractor tends to use w=betrayed (not devastated)
    for the victim's own reaction, or sets about_npc to the betrayer — making this
    pattern rare. If it occurs, ## correction resolves it.

    Only observation-type memories are evaluated — reflections are Director-generated
    and must not contribute to death detection.

    Called at the end of _apply_narrator_metadata(), after both _process_deceased_npcs
    and _apply_memory_updates have run, so all memories for the scene are stored and
    any extractor-driven resurrections have already completed.
    """
    scene = game.scene_count
    cross_votes: dict[str, int] = {}  # npc_id → votes from other NPCs' observations
    self_votes: dict[str, int] = {}   # npc_id → votes from the NPC's own observations

    for npc in game.npcs:
        if npc.get("status") == "deceased":
            continue  # already handled by primary mechanism; skip as memory writer
        for mem in npc.get("memory", []):
            if mem.get("scene") != scene:
                continue
            if mem.get("type") == "reflection":
                continue  # Director-generated; not an extractor death signal

            about = mem.get("about_npc")
            imp = mem.get("importance", 0)
            weight = mem.get("emotional_weight", "")

            # Cross-NPC vote: NPC A observed something about NPC B with death-tier signal
            if (about
                    and about != npc.get("id")
                    and imp >= 9
                    and weight in {"betrayed", "devastated"}):
                cross_votes[about] = cross_votes.get(about, 0) + 1

            # Self-vote: NPC's own observation at maximum devastation (no about_npc)
            # "devastated" alone at imp=9 is near-exclusive to death or irreversible loss
            if (not about
                    and imp >= 9
                    and weight == "devastated"):
                self_votes[npc["id"]] = self_votes.get(npc["id"], 0) + 1

    # Apply threshold: at least 1 cross-NPC vote required; total must reach 2
    for npc_id in set(cross_votes) | set(self_votes):
        cv = cross_votes.get(npc_id, 0)
        sv = self_votes.get(npc_id, 0)
        if cv >= 1 and (cv + sv) >= 2:
            target = _find_npc(game, npc_id)
            if target and target.get("status") != "deceased":
                old_status = target.get("status", "active")
                target["status"] = "deceased"
                log(f"[NPC] Death corroborated by memory signals: '{target['name']}' "
                    f"(cross_votes={cv}, self_votes={sv}, "
                    f"scene={scene}, was {old_status})")


# ===============================================================
# DIRECTOR AGENT — Lazy story steering, summaries, reflections
# ===============================================================

DIRECTOR_SYSTEM = """You are the Director of a solo RPG story. You do NOT write narration.
Your job is strategic: analyze what just happened and guide what should happen next.

Think like a showrunner, not a writer:
- What tensions are building? What should pay off soon?
- Which NPCs have untapped potential? Who should appear next?
- Is the pacing right? Does the player need a breather or escalation?
- Are there narrative threads that risk being forgotten?
- How do NPCs feel about EACH OTHER, not just the player? NPC-to-NPC dynamics
  (alliances, rivalries, attraction, distrust) create a living world.

IMPORTANT: NPCs may have aliases (listed as "aka" in the NPC list or "aliases" in
reflect tags). All aliases refer to the SAME character — treat them as one person.
Memories may use any of the NPC's names interchangeably. When writing reflections,
use the NPC's current primary name consistently.

For NPC reflections: Synthesize their accumulated memories into a higher-level
insight about how they view the player character. Write in the story language.
Focus on relationship evolution, not event recaps. If an NPC's memories show
strong feelings about another NPC, the reflection can be about that relationship.

Be SPECIFIC in narrator_guidance. Not "make things interesting" but
"Borin should test the player's loyalty with a dangerous request before
revealing the secret passage."

Clocks represent threats and world events with a fill level (e.g. 3/6).
They advance on a MISS (guaranteed), on a WEAK_HIT at risky/desperate position
(probabilistic), and autonomously as the world moves forward. When a clock is
full, its trigger fires as a hard narrative event —
not optional, not avoidable. Reference clocks in arc_notes and narrator_guidance
when they are ≥50% filled or have recently ticked — they signal what is at stake
and what is coming. A nearly-full clock should create visible narrative pressure.
CRITICAL: When referencing clocks in narrator_guidance or arc_notes, NEVER use
the clock's internal name (e.g. "Mob Clock", "Betrayal Clock"). Describe the
threat or consequence in narrative terms instead — "the mob is getting closer",
"betrayal feels imminent" — so the Narrator can translate this into atmosphere
without leaking game-mechanical labels into prose.

When phase="aftermath": the planned story arc has concluded and the player chose
to keep playing. Do NOT suggest wrapping up or pushing toward a final scene.
Instead: surface consequences of past events, develop NPC relationships, introduce
organic new tensions. Think "Season 2 setup", not "Season 1 finale". """


def _act_trigger_due(game: GameState) -> Optional[str]:
    """Act id (e.g. "act_1") whose transition_trigger is due, else None.
    Due = the current act has a trigger, is not the final act, has not been
    triggered yet, and the story is within ACT_TRIGGER_DUE_SCENES scenes of the
    act's scene_range end. Without steering, triggers phrased as story events were
    rarely produced on the page and acts only advanced via the scene-range fallback."""
    bp = game.story_blueprint or {}
    acts = bp.get("acts") or []
    if not acts or bp.get("story_complete"):
        return None
    act = get_current_act(game)
    idx = act.get("act_number", 1) - 1
    if idx >= len(acts) - 1 or not act.get("transition_trigger"):
        return None
    act_id = f"act_{idx}"
    if act_id in (bp.get("triggered_transitions") or []):
        return None
    sr = _safe_sr(act, fallback_start=1)
    if 0 <= sr[1] - game.scene_count <= ACT_TRIGGER_DUE_SCENES:
        return act_id
    return None


def _mark_director_reason(game: GameState, reason: Optional[str]) -> None:
    """Record once-only Director reasons so _should_call_director() does not re-fire
    them: "phase:<phase>" → "<phase>", "act_due:<act_id>" → "due:<act_id>" in
    story_blueprint["triggered_director_phases"] (restored by turn snapshots)."""
    if not reason or game.story_blueprint is None:
        return
    if reason.startswith("phase:"):
        key = reason[len("phase:"):]
    elif reason.startswith("act_due:"):
        key = "due:" + reason[len("act_due:"):]
    else:
        return
    game.story_blueprint.setdefault("triggered_director_phases", []).append(key)


def _should_call_director(game: GameState, roll_result: str = "",
                          chaos_used: bool = False,
                          new_npcs_found: bool = False,
                          revelation_used: bool = False) -> Optional[str]:
    """Decide whether to call the Director after this scene.
    Director runs lazily — not every turn, only when valuable.
    Returns a reason string if Director should run, None otherwise."""
    # 1. Significant game events → always
    if roll_result == "MISS":
        return "miss"
    if chaos_used:
        return "chaos"
    if new_npcs_found:
        return "new_npcs"
    if revelation_used:
        return "revelation"

    # 2. Any NPC needs reflection — pick the one with the highest accumulator so the
    # trigger label reflects the most-pending NPC (build_director_prompt includes all of them).
    reflection_npcs = [
        npc for npc in game.npcs
        if npc.get("_needs_reflection") and npc.get("status") in ("active", "background")
    ]
    if reflection_npcs:
        top = max(reflection_npcs, key=lambda n: n.get("importance_accumulator", 0))
        return f"reflection:{top.get('name', '?')}"

    # 3. Act phase change — Director is especially valuable in high-stakes phases.
    # "resolution" = 3-act finale; "ketsu_resolution" = kishotenketsu finale;
    # "ten_twist" = the perspective-shift act that precedes it.
    # Deduplication: fire at most once per phase. Once triggered, the phase is
    # recorded in story_blueprint["triggered_director_phases"] and silenced until
    # the act advances (new blueprint) or a ## correction restores an earlier snapshot.
    if game.story_blueprint and game.story_blueprint.get("acts"):
        act = get_current_act(game)
        phase = act.get("phase", "")
        if phase in ("climax", "resolution", "ten_twist", "ketsu_resolution"):
            already_fired = set(game.story_blueprint.get("triggered_director_phases") or [])
            if phase not in already_fired:
                return f"phase:{phase}"
        # Act trigger due → run once per act so the Director can steer toward it.
        # _mark_director_reason() records "due:<act_id>" in triggered_director_phases.
        due = _act_trigger_due(game)
        if due and f"due:{due}" not in (game.story_blueprint.get("triggered_director_phases") or []):
            return f"act_due:{due}"

    # 4. Regular interval
    if game.scene_count > 0 and game.scene_count % DIRECTOR_INTERVAL == 0:
        return "interval"

    return None


def build_director_prompt(game: GameState, latest_narration: str,
                          config: Optional[EngineConfig] = None) -> str:
    """Build the Director analysis prompt."""
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)

    # Recent session log
    log_entries = []
    for s in game.session_log[-8:]:
        entry = f'Scene {s.get("scene", "?")}: {s.get("summary", "")} → {s.get("result", "")}'
        if s.get("dramatic_question"):
            entry += f' (Q: {s["dramatic_question"]})'
        log_entries.append(entry)
    log_text = "\n".join(log_entries) or "(start)"

    # NPCs needing reflection or profile completion (empty agenda/instinct)
    reflection_blocks = []
    for n in game.npcs:
        needs_profile_flag = (
            not n.get("agenda", "").strip() or not n.get("instinct", "").strip()
        )
        if not n.get("_needs_reflection") and not needs_profile_flag:
            continue
        if n.get("status") not in ("active", "background"):
            continue
        _ensure_npc_memory_fields(n)
        # Include both observations and absent-mention memories so the Director
        # can reflect on off-screen NPC developments (e.g. Eli confirmed transported).
        # Mentions have low importance (3) and are visually distinct — the Director
        # prompt already shows emotional_weight which signals the memory origin.
        recent_obs = [m for m in n.get("memory", [])
                      if m.get("type") in ("observation", "mention")][-8:]
        mem_text = "; ".join(
            f'{m.get("event", "")}({m.get("emotional_weight", "")})' for m in recent_obs
        )
        # Include last reflection so Director can build on it, not repeat it
        prev_reflections = [m for m in n.get("memory", [])
                            if m.get("type") == "reflection"]
        prev_ref_text = ""
        prev_tone_text = ""
        if prev_reflections:
            escaped = _xa(prev_reflections[-1].get("event", "")[:200])
            prev_ref_text = f' last_reflection="{escaped}"'
            # Expose both arc dimensions so the Director has full context to evolve from:
            #   last_tone     — narrative compound (e.g. "protective_guilt"): emotional register / arc texture
            #   last_tone_key — enum word (e.g. "conflicted"): machine-readable reference for tone_key evolution
            # Fallback for old saves predating the dual-tone system: use emotional_weight as compound;
            # skip last_tone_key if tone_key field absent.
            prev_tone_compound = prev_reflections[-1].get("tone") or prev_reflections[-1].get("emotional_weight", "")
            prev_tone_key_val  = prev_reflections[-1].get("tone_key", "")
            prev_tone_text = ""
            if prev_tone_compound:
                prev_tone_text += f' last_tone="{_xa(prev_tone_compound)}"'
            if prev_tone_key_val:
                prev_tone_text += f' last_tone_key="{_xa(prev_tone_key_val)}"'
        npc_desc = _xa(n.get("description", ""))
        # Flag NPCs that lack agenda/instinct so Director can suggest them
        needs_profile = ""
        if not n.get("agenda", "").strip() or not n.get("instinct", "").strip():
            needs_profile = ' needs_profile="true"'
        # Include aliases so Director knows all names for this NPC
        alias_attr = ""
        if n.get("aliases"):
            escaped_aliases = _xa(", ".join(n["aliases"]))
            alias_attr = f' aliases="{escaped_aliases}"'
        # Expose instinct (stable wiring) and arc (current trajectory) so the
        # Director can evolve arc without rewriting instinct.
        instinct_attr = f' instinct="{_xa(n.get("instinct", ""))}"' if n.get("instinct", "").strip() else ""
        arc_attr      = f' arc="{_xa(n.get("arc", ""))}"'           if n.get("arc",      "").strip() else ""
        reflection_blocks.append(
            f'<reflect npc_id="{n.get("id","")}" name="{_xa(n.get("name",""))}"'
            f'{alias_attr} '
            f'disposition="{n.get("disposition","")}" bond="{n.get("bond",0)}" '
            f'description="{npc_desc}"{instinct_attr}{arc_attr}{prev_ref_text}{prev_tone_text}{needs_profile}>'
            f'{html.escape(mem_text)}</reflect>'
        )
    reflection_section = "\n".join(reflection_blocks)

    # Story arc info
    story_info = ""
    transition_trigger = ""
    if game.story_blueprint and game.story_blueprint.get("acts"):
        act = get_current_act(game)
        bp = game.story_blueprint
        transition_trigger = act.get("transition_trigger", "")
        thematic = bp.get("thematic_thread", "")
        scene_range = _safe_sr(act, fallback_start=1)
        past_range = game.scene_count > scene_range[1]
        past_range_attr = ' PAST_RANGE="true"' if past_range else ""
        story_info = (
            f'\n<story_arc structure="{_xa(bp.get("structure_type", "3act"))}" '
            f'act="{act["act_number"]}/{act["total_acts"]}" phase="{_xa(act["phase"])}" '
            f'progress="{act["progress"]}" '
            f'current_scene="{game.scene_count}" scene_range="{scene_range[0]}-{scene_range[1]}"'
            f'{past_range_attr} '
            f'conflict="{_xa(bp.get("central_conflict", ""))}"'
        )
        if thematic:
            story_info += f' thematic_thread="{_xa(thematic)}"'
        story_info += '/>'
        if transition_trigger:
            _due_attr = ' due="true"' if _act_trigger_due(game) else ""
            story_info += (
                f'\n<transition_trigger act="{act["act_number"]}"{_due_attr}>'
                f'{html.escape(transition_trigger)}</transition_trigger>'
            )

    # Active NPC overview (include descriptions and aliases so Director stays consistent)
    def _director_npc_line(n):
        aka = f' aka {", ".join(n["aliases"])}' if n.get("aliases") else ""
        desc = f' | {n["description"][:80]}' if n.get("description") else ""
        return (f'- {n["name"]}({n.get("id","")}){aka} {n["disposition"]} '
                f'B{n.get("bond",0)} status={n.get("status","active")}{desc}')
    npc_overview = "\n".join(
        _director_npc_line(n)
        for n in game.npcs
        if n.get("status") in ("active", "background", "lore")
    ) or "(none)"

    # Clocks overview — active clocks with fill bar; fired clocks compact
    active_clocks = [c for c in game.clocks if not c.get("fired")]
    fired_clocks  = [c for c in game.clocks if c.get("fired")]
    clocks_lines = []
    clock_cap_note = (f"({len(active_clocks)}/{MAX_ACTIVE_CLOCKS} active — "
                      f"{'cap reached, do NOT add new clocks' if len(active_clocks) >= MAX_ACTIVE_CLOCKS else f'{MAX_ACTIVE_CLOCKS - len(active_clocks)} slot(s) remaining'})")
    for c in active_clocks:
        filled  = c.get("filled", 0)
        segs    = c.get("segments", 6)
        bar     = "█" * filled + "░" * (segs - filled)
        pct     = int(filled / segs * 100) if segs else 0
        ctype   = c.get("clock_type", "threat")
        trigger = c.get("trigger_description", "")
        clocks_lines.append(f'- {c["name"]} [{ctype}] {bar} {filled}/{segs} ({pct}%) — {trigger}')
    if fired_clocks:
        clocks_lines.append("fired (already triggered, no longer active):")
        for c in fired_clocks:
            clocks_lines.append(f'  - {c["name"]}: {c.get("trigger_description", "")}')
    _slots_free = MAX_ACTIVE_CLOCKS - len(active_clocks)
    clock_cap_rule = (
        f" CLOCK CAP REACHED ({len(active_clocks)}/{MAX_ACTIVE_CLOCKS}): new_clocks MUST be an "
        f"empty array in this run — express new dangers through narrator_guidance instead."
        if _slots_free <= 0 else
        f" Only {_slots_free} more clock(s) fit under the cap of {MAX_ACTIVE_CLOCKS}.")
    clocks_block = (f"<clocks {clock_cap_note}>\n" + "\n".join(clocks_lines) + "\n</clocks>"
                    if clocks_lines else "")

    # Current time context for Director — includes stale counter when frozen
    _stale = game.time_unchanged_scenes
    if game.time_of_day:
        _stale_attr = f' stale_scenes="{_stale}"' if _stale >= TIME_STALE_THRESHOLD else ""
        _time_block = f'\n<current_time{_stale_attr}>{html.escape(game.time_of_day)}</current_time>'
    else:
        _time_block = ""
    if game.current_location:
        _loc_stale = game.scenes_at_location
        _loc_attr = (f' stale_scenes="{_loc_stale}"'
                     if _loc_stale >= LOCATION_STALE_THRESHOLD else "")
        _time_block += (f'\n<current_location{_loc_attr}>'
                        f'{html.escape(game.current_location)}</current_location>')

    return f"""<setting genre="{_xa(game.setting_genre)}" tone="{_xa(game.setting_tone)}"/>{_time_block}

<scene_history>
{log_text}
</scene_history>

<latest_scene>
{html.escape(latest_narration[:1000])}
</latest_scene>

<npcs>
{npc_overview}
</npcs>

{clocks_block}
{story_info}
{reflection_section}

<task>
Analyze the latest scene and provide strategic guidance in {lang}.
LANGUAGE RULE: Every text field you write MUST be in {lang}. This is an absolute requirement — do not use English for any field value, not even partially or for a single sentence. If the narration language is German, write all guidance, reflections, descriptions, and summaries in German.
Reflections and narrator_guidance MUST be in {lang}.
TONE RULE: narrator_guidance and npc_guidance MUST honor the story's tone ("{_xa(game.setting_tone)}"). Do not steer the story toward a register that contradicts it — a comedy tone requires comedy-compatible beats, a dark tone requires weight, etc.

Field instructions:
- scene_summary: 2-3 sentence summary of what happened and WHY it matters (in {lang})
- narrator_guidance: Specific direction for the next 1-2 scenes (in {lang}). When relevant, anchor the guidance to the thematic_thread from <story_arc> — surface the aspect of it most alive in the current moment. TIME RULE: If <current_time stale_scenes> is present in context, time of day has not visibly advanced for that many scenes — your narrator_guidance MUST include a directive to anchor the next scene with at least one concrete atmospheric time cue (a shift in light quality, temperature, or ambient sound). LOCATION RULE: If <current_location stale_scenes> is present, the story has stayed at one place for that many scenes — your narrator_guidance MUST name a concrete reason or opportunity to move to a different place (a lead, a summons, a threat, a need), unless the current confrontation must resolve there first. The player decides whether to go. TRIGGER RULE: If <transition_trigger due="true"> is present and act_transition is false, the act is about to end without its core event — your narrator_guidance MUST steer the next scene toward that core event as a concrete on-page moment (a discovery, a confrontation, a confession, an arrival or a decision put to the player), in the established tone and without making the player's choice for them. FINAL ACT RULE: When phase is "ketsu_resolution" or "resolution", the insight and revelation phase is over. narrator_guidance MUST push toward a concrete, irreversible action or choice — not toward further reflection on what has already been established. Each scene in the final act should change something permanently: a decision made, a door closed, a relationship transformed. If the player has been circling the same existential question for two or more scenes, name that directly in your guidance and force a new variable into the scene.
- npc_guidance: Array of {{"npc_id": "npc_1", "guidance": "what this NPC should do/feel next"}} — guidance text in {lang}
- pacing: one of tension_rising, building, climax, breather, resolution
- npc_reflections: Only for NPCs listed in <reflect> tags. NPCs with status=lore or status=deceased appear in the overview for context only — NEVER include them in npc_reflections. Each object has:
  - npc_id: the NPC's ID from the <reflect> tag
  - reflection: 1-2 sentence higher-level insight (in {lang})
  - tone: 1-3 lowercase English words, underscore-separated, capturing the emotional shift (e.g. 'protective_guilt', 'reluctant_trust')
  - tone_key: ONE word from the enum (neutral, curious, wary, suspicious, grateful, terrified, loyal, conflicted, betrayed, devastated, euphoric, defiant, guilty, protective, angry, devoted, impressed, hopeful)
  - updated_description: STRICTLY in {lang}. Max 100 characters. Role + key visual traits + personality. Keep physical details like age, hair, build. Do NOT start with the NPC's name. NO actions, NO posture. Example: 'Grumpy dwarf blacksmith with burn scars, secretly loyal'. null if unchanged.
  - updated_agenda: If this NPC's goals have fundamentally shifted due to recent story events (defeat, revelation, betrayal, alliance formed), write their new driving goal (max 10 words, in {lang}). Use this when the old agenda is clearly obsolete — e.g. an NPC who sought to destroy the player now seeks to understand them. null if the existing agenda still applies.
  - updated_arc: The NPC's current narrative trajectory — what the story has made of them so far. 1-2 sentences in {lang}, at most {ARC_MAX_CHARS} characters, from an inside perspective (their emotional state and what they have become, not what they will do next). Expected to change every reflection as the story develops. The <reflect> tag shows the current arc if set — build on it, deepen it, or shift it based on what just happened. Distinct from instinct (stable wiring) and npc_guidance (scene instruction). Good: "Has seen enough of Janus's chaos to stop treating him as a variable — now calculating whether trust is a liability or an asset." Bad (scene behavior, not trajectory): "Is nervous and looking for an exit." null only if the NPC has had zero meaningful story interaction.
  - about_npc: If this reflection is primarily about the NPC's feelings toward ANOTHER NPC (not the player), set to that NPC's npc_id. Example: Sophie reflects on her growing attraction to Bruce → about_npc="npc_2". null if the reflection is about the player or general.
  - agenda: NPC's hidden goal (max 8 words, only if needs_profile="true"), null otherwise
  - instinct: NPC's psychological signature under real pressure (max 8 words, only if needs_profile="true"), null otherwise. NOT job demeanor or genre convention — the specific human underneath: what they do when their strategy fails, what betrays them, what is slightly irrational but inevitable. BAD: "stays calm under pressure" / "methodical and efficient" / "evaluates before acting". GOOD: "goes quiet and hyper-precise when cornered" / "agrees then quietly does what he intended" / "dark humor until something breaks, then overcorrects". Base on this NPC's description and story observations. IMPORTANT: instinct is set ONCE (first reflection, needs_profile=true) and never updated — it is the NPC's wiring, not their mood.
  - disposition_shift: Set to "improve" or "worsen" ONLY when the NPC's accumulated story arc clearly justifies a one-step organic change in their relationship to the player — e.g. an NPC who has consistently helped and trusted over many scenes should shift from neutral to friendly, or a betrayal should shift from friendly to neutral. This is NOT a reward for a single good roll; it reflects a relationship that has genuinely changed through narrative accumulation. Leave null in the vast majority of cases. One step only per reflection. The direction must match the tone of the reflection.
- arc_notes: Brief story arc progress observation
- act_transition_check: One sentence (in English) written BEFORE deciding act_transition. Name the CORE EVENT of <transition_trigger> — the single central story development it describes, ignoring secondary details, exact wording and named specifics — then state in which recent scene (<scene_history> or <latest_scene>) that core event happened in any form, or what is still missing. Empty string if there is no <transition_trigger>.
- act_transition: true if act_transition_check found the core event in the story, even partially, in different words, or via other characters or means than the trigger names (do not wait for a perfect match). If the trigger lists several elements, the act turns once its central discovery or decision has happened — the elements may be spread over several scenes, and secondary details (exact numbers, follow-up steps) are not required. Also true if PAST_RANGE="true" and the trigger's spirit has been approximately met. false only if the core event has clearly not happened yet. Your arc_notes and act_transition must agree: if arc_notes describe the trigger's situation as reached, act_transition is true. The scene_range is only a fallback — content-driven transitions produce better pacing.
- new_clocks: Propose new threat clocks ONLY when ALL conditions are met: (1) a concrete new danger has emerged in the last 1-2 scenes that is NOT already tracked by an existing clock in <clocks>, (2) the threat is specific enough to have a concrete, narratively meaningful trigger_description (what happens when the clock fills), (3) the threat is genuinely new — not a re-framing of an existing one. Leave this array EMPTY when any condition is unmet. When creating a clock: name (short, evocative), clock_type ("threat" or "scheme"), segments (4–8 based on urgency — 4 for imminent, 6 for medium, 8 for slow-burn), filled (1 to show the threat has already begun, 0 only if it is entirely latent), trigger_description (the concrete consequence when filled), owner ("world" or the NPC name driving this threat). Maximum 2 new clocks per Director run — default is empty array.{clock_cap_rule}

If a <reflect> tag has a last_reflection attribute, write a NEW insight that builds on, deepens, or contradicts it. Do NOT repeat the same theme or emotional tone. If last_tone is present, use it as the emotional register to evolve from — the texture and arc direction of the previous state. If last_tone_key is present, use it as the enum category to move away from when choosing the new tone_key (avoid repeating the identical value unless deliberate stagnation is the point).
</task>"""


def call_director(client: anthropic.Anthropic, game: GameState,
                  latest_narration: str,
                  config: Optional[EngineConfig] = None) -> dict:
    """Call the Director agent for scene analysis and story guidance.
    Returns a dict with guidance fields, or empty dict on failure."""
    log(f"[Director] Analyzing scene {game.scene_count}")

    prompt = build_director_prompt(game, latest_narration, config)

    try:
        response = _structured_create(
            client, _director_schema_for(game), DIRECTOR_OUTPUT_SCHEMA, max_retries=1,
            model=DIRECTOR_MODEL, max_tokens=DIRECTOR_MAX_TOKENS,
            system=_cached_system(DIRECTOR_SYSTEM),
            messages=[{"role": "user", "content": prompt}],
        )
        guidance = json.loads(_response_text(response))

        # Convert npc_guidance from array (schema) to dict (internal format)
        # Array format: [{"npc_id": "npc_1", "guidance": "..."}]
        # Dict format:  {"npc_1": "..."} — used by narrator prompts and savegames
        if isinstance(guidance.get("npc_guidance"), list):
            guidance["npc_guidance"] = {
                item["npc_id"]: item["guidance"]
                for item in guidance["npc_guidance"]
                if item.get("npc_id") and item.get("guidance")
            }

        log(f"[Director] Guidance: pacing={guidance.get('pacing','?')}, "
            f"reflections={len(guidance.get('npc_reflections', []))}, "
            f"summary={guidance.get('scene_summary', '')[:80]}")
        return guidance
    except Exception as e:
        log(f"[Director] Structured output failed ({type(e).__name__}: {e}), "
            f"continuing without guidance", level="warning")
        return {}


_SENTENCE_ENDS = ('.', '!', '?', '"', '»', '…', ')', '–', '—')

def _truncate_to_last_sentence(text: str) -> str:
    """Truncate text to the last complete sentence.
    Scans backwards for the last sentence-terminating character.
    Returns empty string if no terminator is found (fully truncated)."""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in _SENTENCE_ENDS:
            return text[:i + 1]
    return ""


def _apply_director_guidance(game: GameState, guidance: dict):
    """Apply Director guidance to game state: store guidance, apply reflections,
    update session log with rich summary."""
    if not guidance:
        # API failure — reset any stuck _needs_reflection flags so we don't loop
        # on a zombie trigger (Director keeps firing every turn but always fails).
        for npc in game.npcs:
            if npc.get("_needs_reflection") and npc.get("status") in ("active", "background"):
                npc["_needs_reflection"] = False
                npc["importance_accumulator"] = 0
                log(f"[Director] Reset _needs_reflection for {npc.get('name','?')} "
                    f"(guidance empty — API failure or empty response)")
        return

    # Store guidance for next narrator call.
    # act_transition and npc_reflections (diagnostic subset) are stored here so
    # the session log (Elvira) can read them after run_deferred_director() returns.
    # Only npc_id/tone/tone_key/updated_arc are kept — the prose reflection and
    # write-back fields (agenda, instinct, updated_description) are already applied
    # to NPC memory and do not need to travel through director_guidance further.
    game.director_guidance = {
        "narrator_guidance": guidance.get("narrator_guidance", ""),
        "npc_guidance":      guidance.get("npc_guidance", {}),
        "pacing":            guidance.get("pacing", ""),
        "arc_notes":         guidance.get("arc_notes", ""),
        "act_transition":    guidance.get("act_transition"),
        "act_transition_check": guidance.get("act_transition_check", ""),
        "npc_reflections": [
            {
                "npc_id":           r.get("npc_id", ""),
                "tone":             r.get("tone", ""),
                "tone_key":         r.get("tone_key", ""),
                "updated_arc":      r.get("updated_arc"),
                "disposition_shift": r.get("disposition_shift"),
            }
            for r in (guidance.get("npc_reflections") or [])
        ],
        # Diagnostic only — actual clock objects are appended to game.clocks below.
        # Stored here so Elvira session log can record which clocks were created.
        "new_clocks": guidance.get("new_clocks") or [],
    }

    # Handle act transition: Director signals that the current act's
    # transition_trigger has been fulfilled → mark in blueprint
    if game.story_blueprint and guidance.get("act_transition_check"):
        log(f"[Director] act_transition={bool(guidance.get('act_transition'))} — "
            f"{guidance['act_transition_check'][:200]}")
    if guidance.get("act_transition") and game.story_blueprint:
        bp = game.story_blueprint
        # Normalize None → [] before setdefault, since setdefault only fires when
        # the key is absent — a null value from the Architect would slip through.
        if bp.get("triggered_transitions") is None:
            bp["triggered_transitions"] = []
        bp.setdefault("triggered_transitions", [])
        acts = bp.get("acts", [])
        act = get_current_act(game)
        act_idx = act.get("act_number", 1) - 1

        # Guard: the final act has no transition_trigger by design.
        # If the Director fires act_transition=true while in the final act
        # (e.g. with PAST_RANGE=true), silently ignore — recording it would
        # pollute triggered_transitions without any effect on get_current_act().
        cur_sr = _safe_sr(acts[act_idx], fallback_start=act_idx * 5 + 1) \
            if act_idx < len(acts) else [1, 20]
        if act_idx >= len(acts) - 1:
            log(f"[Director] Ignoring act_transition=true for final act "
                f"(act_{act_idx}) — final acts have no transition by design")
        elif game.scene_count < cur_sr[0] + ACT_MIN_SCENES:
            # Premature: e.g. act_0 "fulfilled" right after the opening scene would
            # skip the whole introduction. scene_range still advances the act later.
            log(f"[Director] Ignoring premature act_transition for act_{act_idx} at scene "
                f"{game.scene_count} (earliest {cur_sr[0] + ACT_MIN_SCENES})")
        else:
            # Back-fill: any intermediate acts skipped via scene_range fallback
            # (never explicitly triggered) should be marked before recording this one.
            # Without this, triggered_transitions can have gaps (e.g. act_0, act_2)
            # that make diagnostics misleading.
            for i in range(act_idx):
                prev_id = f"act_{i}"
                if prev_id not in bp["triggered_transitions"]:
                    sr = _safe_sr(acts[i], fallback_start=i * 5 + 1) if i < len(acts) else [1, 20]
                    if game.scene_count > sr[1]:
                        bp["triggered_transitions"].append(prev_id)
                        log(f"[Director] Back-filled skipped act: {prev_id} "
                            f"(scene {game.scene_count} > range end {sr[1]})")
                        if game.session_log:
                            game.session_log[-1].setdefault("act_transitions", []).append(prev_id)

            act_id = f"act_{act_idx}"
            if act_id not in bp["triggered_transitions"]:
                bp["triggered_transitions"].append(act_id)
                trigger_text = act.get("transition_trigger", "?")
                log(f"[Director] Act transition triggered: act {act.get('act_number')} "
                    f"'{act.get('phase')}' → trigger fulfilled: '{trigger_text[:80]}'")
                # Annotate session_log so act transitions are visible in session JSON.
                if game.session_log:
                    game.session_log[-1].setdefault("act_transitions", []).append(act_id)
    # Enrich the latest session log entry with Director's summary
    scene_summary = guidance.get("scene_summary", "")
    if scene_summary and game.session_log:
        if not scene_summary.rstrip().endswith(_SENTENCE_ENDS):
            scene_summary = _truncate_to_last_sentence(scene_summary)
            if scene_summary:
                log("[Director] rich_summary truncated to last complete sentence")
            else:
                log("[Director] rich_summary fully truncated — skipped, Brain summary kept",
                    level="warning")
        if scene_summary:
            game.session_log[-1]["rich_summary"] = scene_summary

    # Apply NPC reflections
    # Only NPCs whose reflection was actually stored count as "addressed" for the fallback below.
    # Reflections rejected as empty or truncated must NOT count — otherwise the fallback skips
    # them and _needs_reflection stays True permanently (infinite Director loop).
    # Duplicate-entry guard: check successfully_reflected_ids at loop entry — a duplicate entry
    # is only skipped once the first entry has been successfully stored. This allows a second
    # duplicate entry to be tried if the first was rejected (empty/truncated reflection), which
    # is strictly safer than the alternative (blocking on first seen, even if first failed).
    successfully_reflected_ids: set = set()
    for ref in guidance.get("npc_reflections", []):
        npc_id = ref.get("npc_id", "")
        if npc_id in successfully_reflected_ids:
            log(f"[Director] Skipped duplicate reflection entry for {npc_id} "
                f"(already successfully stored in this Director run)", level="warning")
            continue
        npc = _find_npc(game, npc_id)
        if not npc:
            continue
        # Guard: only active/background NPCs may receive Director reflections.
        # Lore and deceased NPCs appear in the Director's npc_overview but have
        # no <reflect> tags — if the Director hallucinates a reflection entry for
        # them anyway (e.g. tone="absent", arc=null), discard it here.
        if npc.get("status") not in ("active", "background"):
            log(f"[Director] Skipped reflection for '{npc.get('name', '?')}' "
                f"— status='{npc.get('status', '?')}' not eligible for reflections",
                level="warning")
            continue
        _ensure_npc_memory_fields(npc)

        reflection_text = ref.get("reflection", "")
        if not reflection_text:
            continue
        # Reject truncated reflections (max_tokens cutoff)
        if not reflection_text.rstrip().endswith(_SENTENCE_ENDS):
            log(f"[Director] Rejected truncated reflection for {npc.get('name','?')}: "
                f"'{reflection_text[:60]}'", level="warning")
            continue

        npc["memory"].append({
            "scene": game.scene_count,  # Track when reflection was generated
            "event": reflection_text,
            "emotional_weight": ref.get("tone_key") or "reflective",  # Enum-constrained single English word for scoring
            "tone": ref.get("tone", ""),        # Narrative compound (e.g. "protective_guilt") for arc tracking
            "tone_key": ref.get("tone_key", ""),  # Machine-readable single word from enum (mirrors emotional_weight)
            "importance": 8,  # Reflections are always important
            "type": "reflection",
            "about_npc": _resolve_about_npc(game, ref.get("about_npc"), owner_id=npc.get("id")),
        })
        npc["_needs_reflection"] = False
        npc["importance_accumulator"] = 0
        npc["last_reflection_scene"] = game.scene_count
        npc["last_memory_scene"] = game.scene_count
        successfully_reflected_ids.add(npc_id)

        # Fill empty agenda/instinct if Director suggested them
        suggested_agenda = (ref.get("agenda") or "").strip()
        suggested_instinct = (ref.get("instinct") or "").strip()
        if suggested_agenda and not npc.get("agenda", "").strip():
            npc["agenda"] = suggested_agenda
            log(f"[Director] Agenda set for {npc['name']}: '{suggested_agenda}'")
        if suggested_instinct and not npc.get("instinct", "").strip():
            npc["instinct"] = suggested_instinct
            log(f"[Director] Instinct set for {npc['name']}: '{suggested_instinct}'")

        # updated_agenda: overwrite only when goals have fundamentally shifted
        # updated_arc: always write — arc is the character's narrative trajectory,
        # expected to evolve every reflection. updated_instinct no longer exists;
        # instinct is locked after initial fill via suggested_instinct.
        new_agenda = (ref.get("updated_agenda") or "").strip()
        new_arc    = (ref.get("updated_arc")    or "").strip()
        if new_agenda:
            old_agenda = npc.get("agenda", "")
            npc["agenda"] = new_agenda
            log(f"[Director] Agenda updated for {npc['name']}: "
                f"'{old_agenda[:60]}' → '{new_agenda}'")
        if new_arc:
            # Over-long arcs (common in German) are trimmed at a sentence end instead
            # of being discarded — dropping them lost the NPC's development entirely.
            if len(new_arc) > ARC_MAX_CHARS:
                trimmed = _trim_to_sentence(new_arc, ARC_MAX_CHARS)
                log(f"[Director] Arc for {npc['name']} trimmed "
                    f"{len(new_arc)} → {len(trimmed)} chars")
                new_arc = trimmed
            old_arc = npc.get("arc", "")
            npc["arc"] = new_arc
            log(f"[Director] Arc updated for {npc['name']}: "
                f"'{old_arc[:60]}' → '{new_arc[:60]}'")

        # Update description if Director provided a meaningful character description
        new_desc = (ref.get("updated_description") or "").strip()
        # Safety net: strip prompt-leak prefixes the AI may copy literally
        new_desc = re.sub(r'^(?:SIDEBAR\s*(?:LABEL)?[:\-—]\s*)', '', new_desc, flags=re.IGNORECASE).strip()
        # Strip redundant NPC name prefix ("Detective Vance:", "Sarah Vance –", etc.)
        npc_name = npc.get("name", "")
        if npc_name:
            # Match full name or any single word from the name, followed by : or – or -
            name_parts = [re.escape(npc_name)] + [re.escape(p) for p in npc_name.split() if len(p) > 2]
            name_pattern = '|'.join(name_parts)
            new_desc = re.sub(
                rf'^(?:{name_pattern})(?:\s+(?:{name_pattern}))*\s*[:\-—]\s*',
                '', new_desc, count=1, flags=re.IGNORECASE
            ).strip()
        if new_desc and len(new_desc) > 10:
            # Reject scene snapshots: too long
            if len(new_desc) > 200:
                log(f"[Director] Rejected description for {npc['name']}: "
                    f"too long ({len(new_desc)} chars), likely scene snapshot")
            elif not _is_complete_description(new_desc) and npc.get("description", ""):
                log(f"[Director] Rejected truncated description for {npc['name']}: "
                    f"'{new_desc[:60]}' — keeping existing")
            else:
                old_desc = npc.get("description", "")
                npc["description"] = new_desc
                log(f"[Director] Description updated for {npc['name']}: "
                    f"'{old_desc[:60]}' → '{new_desc[:60]}'")

        # Apply organic disposition shift when Director signals it.
        # Shifts are rare — only when the accumulated arc genuinely warrants a step
        # change. Guards: only valid shift values accepted; cannot exceed the poles
        # (hostile can only worsen to itself, loyal can only improve to itself).
        disp_shift = (ref.get("disposition_shift") or "").strip().lower()
        if disp_shift in ("improve", "worsen"):
            improve_steps = {
                "hostile": "distrustful", "distrustful": "neutral",
                "neutral": "friendly", "friendly": "loyal",
            }
            worsen_steps = {v: k for k, v in improve_steps.items()}
            old_disp = npc.get("disposition", "neutral")
            if disp_shift == "improve":
                new_disp = improve_steps.get(old_disp)
            else:
                new_disp = worsen_steps.get(old_disp)
            if new_disp and new_disp != old_disp:
                npc["disposition"] = new_disp
                log(f"[Director] Disposition shift for {npc['name']}: "
                    f"{old_disp} → {new_disp} (Director: {disp_shift})")
            else:
                log(f"[Director] Disposition shift '{disp_shift}' for "
                    f"{npc['name']} skipped — already at pole ({old_disp})")

        # Consolidate after adding reflection
        _consolidate_memory(npc)

        log(f"[Director] Reflection for {npc['name']}: {reflection_text[:80]}")

    # Fallback: reset _needs_reflection for any NPCs the Director didn't successfully address.
    # "Successfully addressed" means the reflection passed all checks and was stored.
    # NPCs whose reflection was rejected (empty/truncated) are NOT in successfully_reflected_ids
    # and must be reset here.
    # The accumulator is also reset: if it stays >= REFLECTION_THRESHOLD, _apply_memory_updates()
    # would immediately re-set _needs_reflection on the very next memory addition, turning the
    # fallback into a one-scene respite and creating an infinite Director loop.
    for npc in game.npcs:
        if npc.get("_needs_reflection") and npc.get("id", "") not in successfully_reflected_ids:
            npc["_needs_reflection"] = False
            npc["importance_accumulator"] = 0
            log(f"[Director] Reset stale _needs_reflection for {npc.get('name','?')} "
                f"(reflection not produced or rejected)")

    # New clocks proposed by the Director.
    # Deduplicate by normalised name to prevent the Director from re-creating a
    # clock that was already added by call_opening_metadata or a previous Director run.
    # ID assignment mirrors _process_game_data so clock IDs stay consistent.
    new_clocks = guidance.get("new_clocks") or []
    if new_clocks:
        active_clock_count = sum(1 for c in game.clocks if not c.get("fired"))
        if active_clock_count >= MAX_ACTIVE_CLOCKS:
            log(f"[Director] Clock cap reached ({active_clock_count}/{MAX_ACTIVE_CLOCKS}) "
                f"— skipping {len(new_clocks)} proposed clock(s)", level="warning")
            new_clocks = []
        else:
            # Limit new additions to not exceed the cap
            slots_free = MAX_ACTIVE_CLOCKS - active_clock_count
            if len(new_clocks) > slots_free:
                log(f"[Director] Clock cap: trimming proposed clocks from "
                    f"{len(new_clocks)} to {slots_free}")
                new_clocks = new_clocks[:slots_free]
        existing_names = {
            _normalize_for_match(c.get("name", "")) for c in game.clocks
        }
        max_clock_num = 0
        for c in game.clocks:
            cid_match = re.match(r'clock_(\d+)', str(c.get("id", "")))
            if cid_match:
                max_clock_num = max(max_clock_num, int(cid_match.group(1)))
        added = []
        for c in new_clocks:
            clean = _sanitize_new_clock(c)
            if clean is None:
                continue
            name = clean["name"]
            if _normalize_for_match(name) in existing_names:
                log(f"[Director] Skipped duplicate clock: '{name}' already tracked",
                    level="warning")
                continue
            max_clock_num += 1
            clock_entry = {"id": f"clock_{max_clock_num}", **clean, "fired_at_scene": 0}
            game.clocks.append(clock_entry)
            existing_names.add(_normalize_for_match(name))
            added.append(name)
        if added:
            log(f"[Director] Added {len(added)} new clock(s): {added}")

    _sync_clock_owners(game, "Director")
    log(f"[Director] Guidance applied: pacing={guidance.get('pacing', '?')}")


def reset_stale_reflection_flags(game: GameState) -> None:
    """Reset _needs_reflection and importance_accumulator for NPCs whose Director turn was
    skipped because a newer turn superseded it (race condition: player sent a new message
    before the background Director task could run).

    Without this reset, the flags remain True permanently — the Director is triggered every
    subsequent scene, but is always superseded again, creating a zombie-reflection loop that
    never produces output and causes log noise.

    Called from the UI layer (_bg_director early-return path) when _director_gen mismatch
    prevents the Director from running."""
    for npc in game.npcs:
        if npc.get("_needs_reflection") and npc.get("status") in ("active", "background"):
            npc["_needs_reflection"] = False
            npc["importance_accumulator"] = 0
            log(f"[Director] Reset stale reflection flag for {npc.get('name', '?')} "
                f"(Director skipped — superseded by newer turn)")


# ===============================================================
# PROMPT BUILDERS
# ===============================================================

def _time_ctx(game: "GameState") -> str:
    """Escaped <time> element, or empty string if time_of_day is unset.
    When time_of_day has not advanced for TIME_STALE_THRESHOLD or more scenes,
    appends an inline directive so the Narrator includes at least one concrete
    atmospheric cue that marks time as passing (light quality, temperature, sound).
    This self-correction fires before the Elvira violation threshold (10 scenes)."""
    if not game.time_of_day:
        return ""
    stale = game.time_unchanged_scenes
    if stale >= TIME_STALE_THRESHOLD:
        hint = (f" — static for {stale} scenes: include one concrete atmospheric"
                f" cue this scene showing time has passed"
                f" (shift in light quality, temperature, or ambient sound)")
        return f'\n<time>{html.escape(game.time_of_day)}{hint}</time>'
    return f'\n<time>{html.escape(game.time_of_day)}</time>'


def _loc_hist(game: "GameState") -> str:
    """Escaped <prev_locations> element (empty if location_history is empty), plus a
    <location_stale> directive once the story has stayed LOCATION_STALE_THRESHOLD or
    more scenes at the current place: the Narrator opens a natural path elsewhere
    but never moves the character without the player's choice."""
    out = ""
    if game.location_history:
        locs = ", ".join(html.escape(loc) for loc in game.location_history[-3:])
        out = f'\n<prev_locations>{locs}</prev_locations>'
    stale = game.scenes_at_location
    if stale >= LOCATION_STALE_THRESHOLD:
        out += (f'\n<location_stale scenes="{stale}">The story has stayed at this location'
                f' for {stale} scenes. Open a natural path elsewhere in this scene: a lead'
                f' that points to another place, a summons, a threat that makes staying'
                f' costly, or a need that can only be met somewhere else. If the current'
                f' confrontation must resolve here, resolve it and plant the exit for'
                f' afterwards. Offer the path — never move the character without the'
                f' player\'s choice.</location_stale>')
    return out


def build_new_game_prompt(game: GameState) -> str:
    crisis = "\n<crisis>Character at breaking point.</crisis>" if game.crisis_mode else ""
    story = _story_context_block(game)
    seed = _creativity_seed()
    log(f"[Narrator] Opening creativity_seed={seed!r}")
    return f"""<scene type="opening">
{_scene_header(game)}
<location>{html.escape(game.current_location)}</location>{_loc_hist(game)}{_time_ctx(game)}
<situation>{html.escape(game.current_scene_context)}</situation>{crisis}
{_status_context_block(game)}{story}</scene>
<task>
Opening scene: 3-4 paragraphs. Introduce 2 NPCs through action/dialog. Immediate tension. Create one threat clock.
IMPORTANT: The <character> above is the PLAYER CHARACTER (the "you" in narration). Do NOT include them as an NPC. NPCs are OTHER people the player meets.
If <backstory> exists in system context, treat those facts as established canon — reference naturally but don't retell.
If player_wishes exist, do NOT address them in the opening — save them for later scenes. Focus on world and conflict first.
creativity_seed: {seed} (Use as loose inspiration for NPC names, locations, and scene details — not literally, but as creative anchors to avoid generic defaults)
</task>"""


def _npc_block(game: GameState, target_id: Optional[str],
               context_text: str = "",
               present_npc_ids: set = None) -> str:
    """Build full context block for the target NPC using weighted memory retrieval."""
    target = _find_npc(game, target_id) if target_id else None
    if not target:
        return ""
    _ensure_npc_memory_fields(target)
    # Retrieve best memories using weighted scoring
    memories = retrieve_memories(target, context_text=context_text,
                                max_count=5, current_scene=game.scene_count,
                                present_npc_ids=present_npc_ids)
    # Separate reflections and observations for structured display
    reflections = [m for m in memories if m.get("type") == "reflection"]
    observations = [m for m in memories if m.get("type") != "reflection"]

    # Build memory text
    mem_parts = []
    if reflections:
        ref_text = " | ".join(m.get("event", "") for m in reflections)
        mem_parts.append(f"insight: {ref_text}")
    if observations:
        obs_text = " | ".join(
            f'{m.get("event","")}({m.get("emotional_weight","")})' for m in observations
        )
        mem_parts.append(f"recent: {obs_text}")

    # NPC-to-NPC views: memories about other NPCs present in the scene
    if present_npc_ids:
        npc_view_parts = []
        for m in memories:
            about = m.get("about_npc")
            if about and about in present_npc_ids:
                # Find the referenced NPC's name for readability
                ref_npc = _find_npc(game, about)
                ref_name = ref_npc["name"] if ref_npc else about
                npc_view_parts.append(
                    f'{ref_name}: {m.get("event", "")[:80]}({m.get("emotional_weight", "")})')
        if npc_view_parts:
            mem_parts.append(f"npc_views: {' | '.join(npc_view_parts)}")

    mem_str = "\n".join(mem_parts) if mem_parts else "(no memories)"

    secs = json.dumps(target.get("secrets", []), ensure_ascii=False)
    aliases_attr = f' aliases="{_xa(",".join(target["aliases"]))}"' if target.get("aliases") else ""
    arc_line = f"\narc:{html.escape(target.get('arc', ''))}" if target.get("arc", "").strip() else ""
    return f"""<target_npc name="{_xa(target['name'])}" disposition="{target['disposition']}" bond="{target['bond']}/{target.get('bond_max',4)}"{aliases_attr}>
agenda:{html.escape(target.get('agenda',''))} instinct:{html.escape(target.get('instinct',''))}{arc_line}
{html.escape(mem_str)}
secrets(weave subtly,never reveal):{html.escape(secs)}
</target_npc>"""


def _activated_npcs_block(activated: list[dict], target_id: Optional[str],
                          game: GameState, context_text: str = "",
                          present_npc_ids: set = None) -> str:
    """Build context blocks for activated NPCs (not the target — those get _npc_block).
    Lighter context than target: name, disposition, bond, and 1-2 key memories."""
    parts = []
    for npc in activated:
        # Skip target NPC (handled by _npc_block)
        if target_id and (npc.get("id") == target_id or
                          npc.get("name", "").lower() == str(target_id).lower()):
            continue
        _ensure_npc_memory_fields(npc)
        # Get 2 best memories
        memories = retrieve_memories(npc, context_text=context_text,
                                     max_count=2, current_scene=game.scene_count,
                                     present_npc_ids=present_npc_ids)
        mem_hint = ""
        if memories:
            reflections = [m for m in memories if m.get("type") == "reflection"]
            if reflections:
                mem_hint = f' insight="{_xa(reflections[0].get("event","")[:80])}"'
            else:
                ew = memories[0].get("emotional_weight", "")
                ev = memories[0].get("event", "")[:60]
                mem_hint = f' recent="{_xa(f"{ev}({ew})")}"'

        # Spatial hint: show last location if different from player's current location
        loc_hint = ""
        npc_loc = npc.get("last_location", "")
        player_loc = game.current_location or ""
        if npc_loc and player_loc and not _locations_match(npc_loc, player_loc):
            loc_hint = f' last_seen="{_xa(npc_loc)}"'

        arc_hint = f' arc="{_xa(npc.get("arc","")[:120])}"' if npc.get("arc", "").strip() else ""
        parts.append(
            f'<activated_npc name="{_xa(npc["name"])}" disposition="{npc["disposition"]}" '
            f'bond="{npc["bond"]}"{arc_hint}{mem_hint}{loc_hint}/>'
        )
    return "\n".join(parts)


def _known_npcs_string(mentioned: list[dict], game: GameState,
                       exclude_ids: set = None) -> str:
    """Build compact known-NPCs line for name-only mentions.
    Also includes remaining active/background NPCs not in activated or mentioned."""
    exclude_ids = exclude_ids or set()
    player_loc = (game.current_location or "").lower()
    parts = []

    def _npc_entry(n):
        entry = f'{html.escape(n["name"])}({n["disposition"]})'
        if n.get("status") == "background":
            entry += "[bg]"
        # Spatial hint: show last location if different from player
        npc_loc = n.get("last_location", "")
        if npc_loc and player_loc and not _locations_match(npc_loc, player_loc):
            entry += f'[at:{html.escape(npc_loc)}]'
        return entry

    # Mentioned NPCs (scored but below activation threshold)
    for n in mentioned:
        if n.get("id") in exclude_ids:
            continue
        parts.append(_npc_entry(n))
        exclude_ids.add(n.get("id"))

    # Remaining active NPCs not yet included
    for n in game.npcs:
        if n.get("id") in exclude_ids:
            continue
        if n.get("status") not in ("active", "background"):
            continue
        parts.append(_npc_entry(n))
    return ", ".join(parts) or "none"


def _lore_figures_block(game: GameState) -> str:
    """Build a slim context block for lore figures — named persons who are narratively
    significant but never physically present. Gives the Narrator just enough context
    to handle references without cluttering the scene NPC slots."""
    lore = [n for n in game.npcs if n.get("status") == "lore"]
    if not lore:
        return ""
    parts = []
    for n in lore:
        entry = html.escape(n["name"])
        if n.get("description"):
            entry += f": {html.escape(n['description'][:80])}"
        if n.get("aliases"):
            entry += f" (aka {html.escape(', '.join(n['aliases'][:2]))})"
        parts.append(entry)
    return f"\n<lore_figures>{'; '.join(parts)}</lore_figures>"


def _pacing_block(game: GameState, chaos_interrupt: Optional[str] = None,
                  dramatic_question: str = "") -> str:
    """Build pacing/chaos/dramatic_question block for prompts."""
    parts = []
    pacing = get_pacing_hint(game)
    if pacing != "neutral":
        parts.append(f'<pacing type="{pacing}"/>')
    if dramatic_question:
        parts.append(f'<dramatic_question>{html.escape(dramatic_question)}</dramatic_question>')
    if chaos_interrupt:
        interrupt_descriptions = {
            "npc_unexpected": "An NPC arrives unexpectedly or acts completely against their established pattern",
            "threat_escalation": "An existing danger escalates dramatically or a new threat emerges from nowhere",
            "twist": "Something believed to be true is revealed as false, or an ally shows hidden motives",
            "discovery": "An unexpected object, clue, or piece of information falls into the player's hands",
            "environment_shift": "The environment changes dramatically — sudden weather, structural collapse, fire, flood, unnatural darkness, or a strange phenomenon alters the scene conditions",
            "remote_event": "News arrives or signs appear that something important happened elsewhere — an ally is in trouble, a faction made a move, or a place the player knows has changed",
            "positive_windfall": "An unexpected piece of good fortune — a hidden cache, an uninvited ally, a lucky coincidence, or a momentary reprieve from danger",
            "callback": "A consequence of a past action catches up — a previous decision backfires or pays off, an old debt is called in, or a forgotten detail becomes suddenly relevant",
            "dilemma": "The scene presents the character with a forced choice between two things they value — there is no clean option, only sacrifice and consequence. Make BOTH options tangible and costly",
            "ticking_clock": "A sudden time pressure or deadline is introduced — something must happen soon or an opportunity is lost, a threat becomes unstoppable, or a situation becomes irreversible",
        }
        desc = interrupt_descriptions.get(chaos_interrupt, "Something unexpected disrupts the scene")
        parts.append(f'<chaos_interrupt type="{chaos_interrupt}">{desc}</chaos_interrupt>')
    return "\n".join(parts)


def _npcs_present_string(game: GameState) -> str:
    """Build <npcs_present> content including aliases so Narrator recognizes known NPCs."""
    player_loc = (game.current_location or "").lower()
    parts = []
    for n in game.npcs:
        if n.get("status") != "active":
            continue
        entry = f'{html.escape(n["name"])}:{n["disposition"]}'
        if n.get("aliases"):
            entry += f'(aka {html.escape(",".join(n["aliases"]))})'
        npc_loc = n.get("last_location", "")
        if npc_loc and player_loc and not _locations_match(npc_loc, player_loc):
            entry += f'[at:{html.escape(npc_loc)}]'
        parts.append(entry)
    return ", ".join(parts) or "none"


def _clock_fired_block(events: Optional[list]) -> str:
    """<clock_fired> elements for clocks that filled during this scene.
    Clock events use "fired" (consequences, NPC agency) or "triggered"
    (autonomous ticks). Without this the Narrator never learned about clocks that
    filled through autonomous ticks, WEAK_HIT ticks or dialog-scene NPC agency —
    the threat completed without ever happening in the story."""
    seen, out = set(), []
    for e in events or []:
        if not (e.get("fired") or e.get("triggered")):
            continue
        name = e.get("clock", "")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(f'\n<clock_fired name="{_xa(name)}">{html.escape(e.get("trigger", ""))} '
                   f'— this happens NOW, within this scene: show it concretely on the page, '
                   f'without game terms.</clock_fired>')
    return "".join(out)


def build_dialog_prompt(game: GameState, brain: dict, player_words: str = "",
                        chaos_interrupt: Optional[str] = None,
                        activated_npcs: list = None, mentioned_npcs: list = None,
                        config: Optional[EngineConfig] = None,
                        npc_agency: Optional[list] = None,
                        clock_events: Optional[list] = None) -> str:
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    context_text = f"{player_words} {brain.get('player_intent') or ''} {game.current_scene_context or ''}"

    # Collect IDs of all NPCs present in the scene (for NPC-to-NPC memory boost)
    target_id = brain.get("target_npc")
    _present_ids = set()
    if target_id:
        t = _find_npc(game, target_id)
        if t:
            _present_ids.add(t.get("id"))
    if activated_npcs:
        _present_ids.update(n.get("id") for n in activated_npcs if n.get("id"))

    npc = _npc_block(game, target_id, context_text=context_text,
                     present_npc_ids=_present_ids)

    # Three-tier NPC display
    if activated_npcs is not None:
        # New system: activated NPCs get context, rest are just names
        activated_block = _activated_npcs_block(activated_npcs, target_id, game,
                                                context_text, present_npc_ids=_present_ids)
        exclude_ids = {n.get("id") for n in activated_npcs}
        if target_id:
            t = _find_npc(game, target_id)
            if t:
                exclude_ids.add(t.get("id"))
        known_str = _known_npcs_string(mentioned_npcs or [], game, exclude_ids)
        npcs_section = ""
        if activated_block:
            npcs_section += f"\n{activated_block}"
        npcs_section += f"\n<known_npcs>{known_str}</known_npcs>"
        npcs_section += _lore_figures_block(game)
    else:
        # Fallback: old behavior
        all_npcs = _npcs_present_string(game)
        npcs_section = f"\n<npcs_present>{all_npcs}</npcs_present>"
        npcs_section += _lore_figures_block(game)

    wa = brain.get("world_addition", "")
    wl = f'\n<world_add>{html.escape(wa)}</world_add>' if wa else ""
    crisis = '\n<crisis/>' if game.crisis_mode else ""
    pw = f'\n<player_words>{html.escape(player_words)}</player_words>' if player_words else ""
    pacing = _pacing_block(game, chaos_interrupt, brain.get("dramatic_question", ""))

    # Director guidance injection
    director_block = ""
    dg = game.director_guidance
    if dg:
        if dg.get("narrator_guidance"):
            director_block = f'\n<director_guidance>{html.escape(dg["narrator_guidance"])}</director_guidance>'
        # NPC-specific guidance — independent of narrator_guidance
        for npc_id, guidance in dg.get("npc_guidance", {}).items():
            director_block += f'\n<npc_note for="{npc_id}">{html.escape(guidance)}</npc_note>'
        if dg.get("arc_notes"):                      # independent — survives empty narrator_guidance
            director_block += f'\n<arc_notes>{html.escape(dg["arc_notes"])}</arc_notes>'

    agency = (f'\n<npc_agency>{"| ".join(html.escape(a) for a in npc_agency)}</npc_agency>'
              if npc_agency else "")
    fired = _clock_fired_block(clock_events)

    return f"""<scene type="dialog" n="{game.scene_count}">
{_scene_header(game)}
<intent>{html.escape(brain.get('player_intent', ''))}</intent>{pw}
<location>{html.escape(game.current_location)}</location>{_loc_hist(game)}{_time_ctx(game)}
{npc}{npcs_section}{wl}{crisis}{agency}{fired}
{pacing}{director_block}{_coop_block(game)}
{_status_context_block(game)}{_story_context_block(game)}{_recent_events_block(game)}{_narrator_clocks_block(game)}{_npc_relations_block(game, _present_ids)}</scene>
<task>2-3 paragraphs of immersive narration. Let the world breathe around the conversation — small details of place, light, sound, and texture that make this moment feel inhabited. Something between the characters should shift by the end. Let the current act's mood (from <story_arc>) shape the undertone of the exchange — even a quiet conversation carries the weight of the surrounding phase. If <director_guidance> is present, follow its direction while maintaining your creative voice.</task>"""


def build_action_prompt(game: GameState, brain: dict, roll: RollResult,
                        consequences: list, clock_events: list, npc_agency: list,
                        player_words: str = "",
                        chaos_interrupt: Optional[str] = None,
                        activated_npcs: list = None, mentioned_npcs: list = None,
                        config: Optional[EngineConfig] = None,
                        world_events: Optional[list] = None) -> str:
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    context_text = f"{player_words} {brain.get('player_intent') or ''} {game.current_scene_context or ''}"

    # Collect IDs of all NPCs present in the scene (for NPC-to-NPC memory boost)
    target_id = brain.get("target_npc")
    _present_ids = set()
    if target_id:
        t = _find_npc(game, target_id)
        if t:
            _present_ids.add(t.get("id"))
    if activated_npcs:
        _present_ids.update(n.get("id") for n in activated_npcs if n.get("id"))

    npc = _npc_block(game, target_id, context_text=context_text,
                     present_npc_ids=_present_ids)

    # Three-tier NPC display
    if activated_npcs is not None:
        activated_block = _activated_npcs_block(activated_npcs, target_id, game,
                                                context_text, present_npc_ids=_present_ids)
        exclude_ids = {n.get("id") for n in activated_npcs}
        if target_id:
            t = _find_npc(game, target_id)
            if t:
                exclude_ids.add(t.get("id"))
        known_str = _known_npcs_string(mentioned_npcs or [], game, exclude_ids)
        npcs_section = ""
        if activated_block:
            npcs_section += f"\n{activated_block}"
        npcs_section += f"\n<known_npcs>{known_str}</known_npcs>"
        npcs_section += _lore_figures_block(game)
    else:
        all_npcs = _npcs_present_string(game)
        npcs_section = f"\n<npcs_present>{all_npcs}</npcs_present>"
        npcs_section += _lore_figures_block(game)

    wa = brain.get("world_addition", "")
    wl = f'\n<world_add>{html.escape(wa)}</world_add>' if wa else ""
    pw = f'\n<player_words>{html.escape(player_words)}</player_words>' if player_words else ""

    position = brain.get("position", "risky")
    effect = brain.get("effect", "standard")

    match_tag = ' match="true"' if roll.match else ''
    if roll.result == "MISS":
        clk = "".join(f' clock_triggered="{_xa(e["clock"])}:{_xa(e["trigger"])}"' for e in clock_events)
        match_hint = ' A MATCH \u2014 the situation escalates dramatically, a fateful twist makes everything worse.' if roll.match else ''
        constraint = f'<result type="MISS"{match_tag} consequences="{",".join(consequences)}"{clk}>Concrete failure — the situation worsens. Make it hurt: physical, emotional, or narrative cost. A new complication emerges that creates fresh pressure or danger.{match_hint}</r>'
    elif roll.result == "WEAK_HIT":
        match_hint = ' A MATCH \u2014 despite the cost, something unexpected and significant happens, a twist of fate.' if roll.match else ''
        cons_attr = f' consequences="{",".join(consequences)}"' if consequences else ''
        constraint = f'<result type="WEAK_HIT"{match_tag}{cons_attr}>Success, but at a cost that matters — not just physical damage, but something lost, compromised, or complicated.{match_hint}</r>'
    else:
        match_hint = ' A MATCH \u2014 an unexpected boon, a fateful revelation, or a dramatic advantage beyond the clean success.' if roll.match else ''
        cons_attr = f' consequences="{",".join(consequences)}"' if consequences else ''
        constraint = f'<result type="STRONG_HIT"{match_tag}{cons_attr}>Clean success — but even victory has texture. A detail, reaction, or consequence that makes the win feel earned and opens what comes next.{match_hint}</r>'

    position_tag = f'<position level="{position}" effect="{effect}"/>'

    status_flags = []
    if game.health <= 0: status_flags.append("WOUNDED")
    if game.spirit <= 0: status_flags.append("BROKEN")
    if game.supply <= 0: status_flags.append("DEPLETED")
    if game.game_over:
        status_flags.append("FINAL_SCENE:dramatic ending,character falls,make it meaningful")
    elif game.crisis_mode:
        status_flags.append("CRISIS:desperate,world closing in")

    flags = f'\n<flags>{",".join(status_flags)}</flags>' if status_flags else ""
    agency = f'\n<npc_agency>{"| ".join(html.escape(a) for a in npc_agency)}</npc_agency>' if npc_agency else ""
    # MISS already names its clock events in clock_triggered; other results (WEAK_HIT
    # tick) and autonomous world ticks get explicit <clock_fired> elements.
    fired = _clock_fired_block(([] if roll.result == "MISS" else list(clock_events or []))
                               + list(world_events or []))
    pacing = _pacing_block(game, chaos_interrupt, brain.get("dramatic_question", ""))

    # Director guidance injection
    director_block = ""
    dg = game.director_guidance
    if dg:
        if dg.get("narrator_guidance"):
            director_block = f'\n<director_guidance>{html.escape(dg["narrator_guidance"])}</director_guidance>'
        # NPC-specific guidance — independent of narrator_guidance
        for npc_id, guidance in dg.get("npc_guidance", {}).items():
            director_block += f'\n<npc_note for="{npc_id}">{html.escape(guidance)}</npc_note>'
        if dg.get("arc_notes"):                      # independent — survives empty narrator_guidance
            director_block += f'\n<arc_notes>{html.escape(dg["arc_notes"])}</arc_notes>'

    return f"""<scene type="action" n="{game.scene_count}">
{_scene_header(game)}
<intent>{html.escape(brain.get('player_intent', ''))} ({html.escape(brain.get('approach', ''))})</intent>{pw}
{constraint}
{position_tag}
<status h="{game.health}" sp="{game.spirit}" su="{game.supply}" m="{game.momentum}"/>
<location>{html.escape(game.current_location)}</location>{_loc_hist(game)}{_time_ctx(game)}
{npc}{npcs_section}{wl}{flags}{agency}{fired}
{pacing}{director_block}{_coop_block(game)}
{_status_context_block(game)}{_story_context_block(game)}{_recent_events_block(game)}{_narrator_clocks_block(game)}{_npc_relations_block(game, _present_ids)}</scene>
<task>2-4 paragraphs of immersive narration. Let the roll consequence open new story questions rather than just closing old ones — the scene should end in motion, with something shifted. Let the current act's mood (from <story_arc>) shape the texture of this moment — a STRONG_HIT in a desperate phase still tastes of the surrounding darkness. If <director_guidance> is present, follow its direction while maintaining your creative voice.</task>"""


# ===============================================================
# CO-OP MODE (CO-GM)
# ===============================================================
# Asymmetric co-op: a Player (host, owns the save) and a Co-GM (guest) who plays
# no character. After each scene the Co-GM answers one question (NOW: used in the
# next scene, SEED: stored and surfaced later) and can send Director's Cockpit
# signals. Everything the Co-GM contributes lives in game.coop (persisted):
#
#   question  {id, text, type, npc_id, scene, status: open|answered|passed}
#   answer    {question_id, question, text, passed}        NOW answer for next scene
#   signals   [{id, type, value, text, npc_id, scenes_left, scene}]
#   seeds     [{id, kind, question, text, npc_id, scene, used, used_scene}]
#   recent_questions [str]   counter int   partner str (last Co-GM)
#
# Turn flow: _coop_begin_turn() moves the pending answer and due signals into
# game.coop["_turn"] (and last_turn_snapshot["coop_inputs"] for ## corrections and
# momentum burns); the prompt builders render it via _coop_block(); the transactional
# wrappers remove "_turn" again. After narration the UI calls
# generate_cogm_question(), which also marks seeds the narration surfaced.
# The live session (who is online, who is waiting) is UI state — the engine only
# knows the content.

COGM_TEXT_MAX = 300                # Max chars of one Co-GM answer / cockpit text
COGM_MAX_SIGNALS = 12              # Queued cockpit signals (once + running)
COGM_MAX_SEEDS = 40                # Stored seeds (oldest used ones dropped first)
COGM_SEEDS_IN_PROMPT = 3           # Unused seeds offered to the Narrator per scene
COGM_SEED_MIN_AGE = 2              # Scenes before a SEED answer may surface
COGM_RECENT_QUESTIONS = 6          # Previous questions shown to avoid repeats
COGM_SEED_EVERY = 3                # Every 3rd question is a SEED question
COGM_PRESSURE_SCENES = 2           # Duration of the "Clock is ticking" signal

# Cockpit signal catalog. Design rule: every option is either concrete (the player
# notices it in the next scene) or free text written by the Co-GM - nothing that
# only shifts style. slot: "impulse" signals shape the next scene and only ONE can
# be pending per scene (a new one replaces it); "background" signals work slowly
# or atmospherically and are not limited. kind: once (next scene) | duration (scenes) | persistent
# (until removed, one per NPC) | single (one instance replaces the last) | seed
# (stored as a seed, see coop_add_signal). needs: what the signal carries besides
# its type (None | text | optional_text | value | npc | npc_text). Prompt texts are
# English instructions for the Narrator; {npc}/{text}/{value} are filled in, and
# "prompt_empty" is used when an optional text was left empty.
COGM_SIGNALS = {
    # Free direction
    "direction":         {"slot": "impulse", "kind": "once", "needs": "text",
                          "prompt": "Make this happen in this scene, in your own words and in a way that fits the story so far: {text}"},
    # Characters
    "push_npc":          {"slot": "impulse", "kind": "once", "needs": "npc",
                          "prompt": "Bring {npc} into this scene - they appear, call or clearly make themselves felt. You decide how."},
    "npc_line":          {"slot": "impulse", "kind": "once", "needs": "npc_text",
                          "prompt": "Let {npc} say or do this in this scene, in their own voice - adapt the wording to the moment, keep the intent: {text}"},
    "secret_intent":     {"slot": "background", "kind": "persistent", "needs": "npc_text",
                          "prompt": "Hidden intention of {npc}: {text}. Build it up slowly over many scenes through small, consistent hints - never state it outright and never resolve it suddenly."},
    # World (rumor/secret/false trail are stored as seeds)
    "plant_detail":      {"slot": "impulse", "kind": "once", "needs": "text",
                          "prompt": "Place this concrete detail in the scene, unremarked - the protagonist may or may not notice it: {text}"},
    "rumor":             {"slot": "background", "kind": "seed", "needs": "text"},
    "plant_secret":      {"slot": "background", "kind": "seed", "needs": "text"},
    "false_trail":       {"slot": "background", "kind": "seed", "needs": "text"},
    "weather":           {"slot": "background", "kind": "single", "needs": "value",
                          "values": ("rain", "heat", "fog", "night", "storm", "clear", "snow", "wind"),
                          "prompt": "Weather and light: {value}. Let it be present in the scene."},
    # Twists
    "disruption":        {"slot": "impulse", "kind": "once", "needs": "optional_text",
                          "prompt": "Something unexpected bursts into this scene: {text}",
                          "prompt_empty": "Something unexpected bursts into this scene - a person, an event or a discovery that changes the situation. You decide what."},
    "clock_ticking":     {"slot": "impulse", "kind": "duration", "scenes": COGM_PRESSURE_SCENES, "needs": None,
                          "prompt": "Time pressure: make it clear that something is happening elsewhere and time is running out - without naming its cause."},
    "earned_rest":       {"slot": "impulse", "kind": "once", "needs": None,
                          "prompt": "The protagonist has been through something hard. Offer something warm in this scene - a small victory, a kind gesture, a moment of calm."},
    "cliffhanger":       {"slot": "impulse", "kind": "once", "needs": None,
                          "prompt": "End this scene on a cliffhanger - an open threat, a revelation cut short or a question that demands an answer."},
}

# Seed kinds → how the Narrator should treat them
_COGM_SEED_NOTES = {
    "answer": "a hidden truth planted earlier",
    "now": "a detail meant for an earlier scene that did not fit yet",
    "rumor": "a rumour that exists in the world - let someone mention or hint at it",
    "plant_secret": "an unresolved mystery - hint at it, never solve it",
    "false_trail": "a red herring - present it as possibly significant; it leads nowhere and must never be revealed as false",
}

# Signals the cockpit's environment controls own — cleared when a co-op session ends
_COGM_SESSION_ONLY_SIGNALS = ("weather", "clock_ticking")


def coop_state(game: GameState) -> dict:
    """Return game.coop with all keys present (creates them on first use)."""
    if not isinstance(game.coop, dict):
        game.coop = {}
    c = game.coop
    c.setdefault("question", None)
    c.setdefault("answer", None)
    c.setdefault("signals", [])
    c.setdefault("seeds", [])
    c.setdefault("recent_questions", [])
    c.setdefault("counter", 0)
    c.setdefault("partner", "")
    return c


def _coop_next_id(c: dict, prefix: str) -> str:
    c["counter"] = int(c.get("counter", 0)) + 1
    return f"{prefix}{c['counter']}"


def _coop_clean_text(text) -> str:
    """Collapse whitespace and cap Co-GM text (prompt budget)."""
    text = " ".join(str(text or "").split())
    return text[:COGM_TEXT_MAX]


def _coop_npc_name(game: GameState, npc_ref: str) -> str:
    if npc_ref == "player":
        return game.player_name
    npc = _find_npc(game, npc_ref) if npc_ref else None
    return npc.get("name", npc_ref) if npc else ""


def coop_waiting_for_cogm(game: GameState) -> bool:
    """True while the current Co-GM question is still unanswered."""
    q = coop_state(game).get("question")
    return bool(q and q.get("status") == "open")


def coop_set_question(game: GameState, text: str, qtype: str = "now",
                      npc_id: str = "") -> Optional[dict]:
    """Set the open question for the Co-GM (replaces any previous one)."""
    c = coop_state(game)
    text = _coop_clean_text(text)
    if not text:
        c["question"] = None
        return None
    if npc_id and not _find_npc(game, npc_id):
        npc_id = ""
    q = {"id": _coop_next_id(c, "q"), "text": text,
         "type": "seed" if qtype == "seed" else "now",
         "npc_id": npc_id, "scene": game.scene_count, "status": "open"}
    c["question"] = q
    c["recent_questions"] = (c["recent_questions"] + [text])[-COGM_RECENT_QUESTIONS:]
    return q


def coop_submit_answer(game: GameState, text: str = "", passed: bool = False) -> bool:
    """Record the Co-GM's answer to the open question (or a pass).
    NOW answers wait in game.coop["answer"] for the next scene; SEED answers are
    stored as seeds right away. Returns False if no question is open."""
    c = coop_state(game)
    q = c.get("question")
    if not q or q.get("status") != "open":
        return False
    text = _coop_clean_text(text)
    if not text:
        passed = True
    q["status"] = "passed" if passed else "answered"
    if q.get("type") == "seed":
        if not passed:
            _coop_add_seed(c, "answer", text, question=q.get("text", ""),
                           npc_id=q.get("npc_id", ""), scene=game.scene_count,
                           chapter=game.chapter_number)
        c["answer"] = None
    else:
        c["answer"] = {"question_id": q["id"], "question": q.get("text", ""),
                       "text": "" if passed else text, "passed": passed}
    return True


def _coop_add_seed(c: dict, kind: str, text: str, question: str = "",
                   npc_id: str = "", scene: int = 0, chapter: int = 1) -> dict:
    seed = {"id": _coop_next_id(c, "s"), "kind": kind, "question": question,
            "text": text, "npc_id": npc_id, "scene": scene, "chapter": chapter,
            "used": False, "used_scene": None}
    c["seeds"].append(seed)
    if len(c["seeds"]) > COGM_MAX_SEEDS:
        used = [s for s in c["seeds"] if s.get("used")]
        drop = used[0] if used else c["seeds"][0]
        c["seeds"].remove(drop)
    return seed


def coop_add_signal(game: GameState, sig_type: str, value: str = "", text: str = "",
                    npc_id: str = "") -> Optional[dict]:
    """Queue a Director's Cockpit signal. Returns the stored signal (or seed for
    rumor/secret/false trail), None if invalid. Validation is strict because the
    input comes straight from the UI."""
    spec = COGM_SIGNALS.get(sig_type)
    if not spec:
        return None
    c = coop_state(game)
    needs = spec.get("needs")
    value = str(value or "").strip().lower()
    text = _coop_clean_text(text)
    with_npc = needs in ("npc", "npc_text")
    if needs == "value" and value not in spec.get("values", ()):
        return None
    if needs in ("text", "npc_text") and not text:
        return None
    if with_npc and not _find_npc(game, npc_id):
        return None
    if spec["kind"] == "seed":
        return _coop_add_seed(c, sig_type, text, scene=game.scene_count,
                              chapter=game.chapter_number)
    is_impulse = spec.get("slot") == "impulse"
    if is_impulse:
        # One impulse per scene: a new impulse replaces the pending one
        c["signals"] = [s for s in c["signals"] if not s.get("impulse")]
    else:
        # One background signal per type - or per type and NPC for characters
        c["signals"] = [s for s in c["signals"]
                        if not (s.get("type") == sig_type
                                and (not with_npc or s.get("npc_id") == npc_id))]
    if len(c["signals"]) >= COGM_MAX_SIGNALS:
        return None
    sig = {"id": _coop_next_id(c, "c"), "type": sig_type, "impulse": is_impulse, "value": value,
           "text": text if needs in ("text", "npc_text", "optional_text") else "",
           "npc_id": npc_id if with_npc else "",
           "scenes_left": spec.get("scenes") if spec["kind"] == "duration" else None,
           "scene": game.scene_count}
    c["signals"].append(sig)
    return sig


def coop_remove_signal(game: GameState, item_id: str) -> bool:
    """Remove a queued signal or an unused planted seed (rumor/secret/false trail)."""
    c = coop_state(game)
    before = len(c["signals"]) + len(c["seeds"])
    c["signals"] = [s for s in c["signals"] if s.get("id") != item_id]
    c["seeds"] = [s for s in c["seeds"]
                  if not (s.get("id") == item_id and not s.get("used")
                          and s.get("kind") in ("rumor", "plant_secret", "false_trail"))]
    return len(c["signals"]) + len(c["seeds"]) < before


def coop_start_session(game: GameState, partner: str) -> None:
    """Mark the save as played in co-op with `partner` (the Co-GM's user name)."""
    c = coop_state(game)
    c["partner"] = partner
    c["questions_asked"] = 0


def coop_end_session(game: GameState) -> None:
    """Co-op session ended (pause, solo, Co-GM left). Planted content and story arc
    permissions stay part of the world; the open question and the cockpit's
    environment controls (weather, running tension signals) are dropped, because
    nobody is left to answer or change them."""
    c = coop_state(game)
    ans = c.get("answer")
    if ans and not ans.get("passed") and ans.get("text"):
        # An answer the Co-GM already gave is kept: it can still surface later
        q = c.get("question") or {}
        _coop_add_seed(c, "now", ans["text"], question=ans.get("question", ""),
                       npc_id=q.get("npc_id", ""), scene=game.scene_count + 1,
                       chapter=game.chapter_number)
    c["question"] = None
    c["answer"] = None
    c["signals"] = [s for s in c["signals"] if s.get("type") not in _COGM_SESSION_ONLY_SIGNALS]


def _coop_eligible_seeds(game: GameState, c: dict) -> list:
    """Unused seeds the next scene may use. Seeds from an earlier chapter are
    always old enough (scene numbers restart per chapter). Seeds offered least
    often come first, so a seed the story never finds a place for does not block
    newer ones forever."""
    out = []
    for s in c.get("seeds", []):
        if s.get("used"):
            continue
        min_age = COGM_SEED_MIN_AGE if s.get("kind") == "answer" else 1
        same_chapter = int(s.get("chapter") or 1) >= game.chapter_number
        # Age measured against the scene about to be narrated
        if same_chapter and game.scene_count + 1 - int(s.get("scene") or 0) < min_age:
            continue
        if s.get("npc_id") and not _find_npc(game, s["npc_id"]):
            continue
        out.append(s)
    out.sort(key=lambda s: int(s.get("offered") or 0))      # stable: oldest first on ties
    return out[:COGM_SEEDS_IN_PROMPT]


def _coop_begin_turn(game: GameState) -> Optional[dict]:
    """Take the Co-GM inputs this scene consumes and expose them to the prompt
    builders via game.coop["_turn"]. An unanswered question counts as a pass.
    Returns the inputs (stored in last_turn_snapshot by the caller) or None."""
    if not game.coop:
        return None
    c = coop_state(game)
    inputs = {"answer": None, "signals": [], "seeds": []}
    q = c.get("question")
    if q and q.get("status") == "open":
        q["status"] = "passed"
        if q.get("type") == "now":
            c["answer"] = {"question_id": q["id"], "question": q.get("text", ""),
                           "text": "", "passed": True}
    ans = c.get("answer")
    if ans:
        inputs["answer"] = dict(ans)
        c["answer"] = None
        if not ans.get("passed") and ans.get("text"):
            # A NOW answer the player's action makes unusable must not be forced —
            # keep it as a seed; the question call marks it used if it surfaced.
            seed = _coop_add_seed(c, "now", ans["text"], question=ans.get("question", ""),
                                  npc_id=(q or {}).get("npc_id", ""), scene=game.scene_count + 1,
                                  chapter=game.chapter_number)
            seed["injected"] = True                   # reached the Narrator in its scene
            inputs["answer"]["seed_id"] = seed["id"]
    keep = []
    for s in c.get("signals", []):
        spec = COGM_SIGNALS.get(s.get("type"), {})
        if spec.get("needs") in ("npc", "npc_text") and not _find_npc(game, s.get("npc_id", "")):
            continue                                  # NPC gone (merged/removed)
        if spec.get("kind") in ("persistent", "single"):
            npc = _find_npc(game, s.get("npc_id", "")) if s.get("npc_id") else None
            if npc and npc.get("status") == "deceased":
                continue                              # arc permission ends with the NPC
            inputs["signals"].append(dict(s))
            keep.append(s)
        elif spec.get("kind") == "duration":
            inputs["signals"].append(dict(s))
            left = int(s.get("scenes_left") or 1) - 1
            if left > 0:
                s["scenes_left"] = left
                s["impulse"] = False          # still running, but the slot is free again
                keep.append(s)
        else:
            inputs["signals"].append(dict(s))        # once: consumed now
    c["signals"] = keep
    offered = [s for s in _coop_eligible_seeds(game, c)
               if s["id"] != (inputs["answer"] or {}).get("seed_id")]
    for s in offered:
        s["offered"] = int(s.get("offered") or 0) + 1
    inputs["seeds"] = [dict(s) for s in offered]
    if not (inputs["answer"] or inputs["signals"] or inputs["seeds"]):
        return None
    c["_turn"] = inputs
    return inputs


def _coop_resume_turn(game: GameState, inputs: Optional[dict]) -> None:
    """Re-expose a turn's consumed Co-GM inputs (## correction, momentum burn)."""
    if inputs:
        coop_state(game)["_turn"] = copy.deepcopy(inputs)


def _coop_drop_turn(game: GameState) -> None:
    """Remove the turn-transient inputs without logging (correction, burn)."""
    if isinstance(game.coop, dict):
        game.coop.pop("_turn", None)


def _coop_end_turn(game: GameState) -> None:
    """Drop the turn-transient inputs and note them in the session log."""
    if not isinstance(game.coop, dict):
        return
    inputs = game.coop.pop("_turn", None)
    if inputs and game.session_log:
        entry = {}
        if inputs.get("answer"):
            a = inputs["answer"]
            entry["answer"] = {"question": a.get("question", ""), "text": a.get("text", ""),
                               "passed": bool(a.get("passed")), "seed_id": a.get("seed_id", "")}
        if inputs.get("signals"):
            entry["signals"] = [s.get("type") for s in inputs["signals"]]
        if inputs.get("seeds"):
            entry["seeds_offered"] = [s.get("id") for s in inputs["seeds"]]
        game.session_log[-1]["cogm"] = entry


def _coop_signal_prompt(game: GameState, s: dict) -> str:
    spec = COGM_SIGNALS.get(s.get("type"), {})
    tmpl = spec.get("prompt", "")
    if not s.get("text") and spec.get("prompt_empty"):
        tmpl = spec["prompt_empty"]
    if not tmpl:
        return ""
    return tmpl.format(npc=_coop_npc_name(game, s.get("npc_id", "")),
                       text=s.get("text", ""), value=s.get("value", ""))


def _coop_block(game: GameState) -> str:
    """Narrator prompt block for the Co-GM inputs of the current turn ("" if none)."""
    inputs = (game.coop or {}).get("_turn") if isinstance(game.coop, dict) else None
    if not inputs:
        return ""
    parts = []
    a = inputs.get("answer")
    if a:
        if a.get("passed") or not a.get("text"):
            parts.append(f'<co_gm_input question="{_xa(a.get("question", ""))}">'
                         f'[Co-GM had no input] - decide freely.</co_gm_input>')
        else:
            parts.append(f'<co_gm_input question="{_xa(a.get("question", ""))}">'
                         f'{html.escape(a["text"])}</co_gm_input>')
    seeds = inputs.get("seeds") or []
    if seeds:
        lines = []
        for s in seeds:
            about = _coop_npc_name(game, s.get("npc_id", ""))
            about_attr = f' about="{_xa(about)}"' if about else ""
            q_attr = f' asked="{_xa(s["question"])}"' if s.get("question") else ""
            note = _COGM_SEED_NOTES.get(s.get("kind"), _COGM_SEED_NOTES["answer"])
            lines.append(f'<seed kind="{_xa(note)}"{about_attr}{q_attr}>'
                         f'{html.escape(s.get("text", ""))}</seed>')
        parts.append('<co_gm_seeds rule="Planted details. Use at most ONE, only if this scene '
                     'naturally touches its subject - most scenes use none. Weave it in '
                     'subtly, never announce it.">\n' + "\n".join(lines) + "\n</co_gm_seeds>")
    sigs = []
    for s in inputs.get("signals") or []:
        txt = _coop_signal_prompt(game, s)
        if txt:
            sigs.append(f'<signal type="{_xa(s.get("type", ""))}">{html.escape(txt)}</signal>')
    if sigs:
        parts.append("<co_gm_cockpit>\n" + "\n".join(sigs) + "\n</co_gm_cockpit>")
    if not parts:
        return ""
    rule = ("A human co-game-master shapes this story with you. Treat their input as "
            "established world truth for this scene and weave it in naturally. Never "
            "mention the co-game-master or that anything was suggested. Co-game-master input "
            "shapes the world, other characters and events - never the protagonist's own "
            "actions, words, thoughts or decisions; those stay entirely the player's. If the "
            "protagonist's action makes a <co_gm_input> answer impossible to use now, do not force it. "
            "Content boundaries and kid-friendly rules always override co-game-master input.")
    return f'\n<co_gm rule="{_xa(rule)}">\n' + "\n".join(parts) + "\n</co_gm>"


def _cogm_next_question_type(game: GameState) -> str:
    """Every COGM_SEED_EVERY-th question is a SEED question (deterministic mix);
    the first question of a session is always NOW so the Co-GM sees an effect."""
    asked = int(coop_state(game).get("questions_asked", 0))
    return "seed" if asked % COGM_SEED_EVERY == COGM_SEED_EVERY - 1 else "now"


def call_cogm_question(client: anthropic.Anthropic, game: GameState, narration: str,
                       qtype: str, check_seeds: list,
                       config: Optional[EngineConfig] = None) -> dict:
    """Haiku + Structured Outputs: write the next Co-GM question and report which
    of `check_seeds` the narration surfaced. Raises on API failure (caller decides)."""
    lang = get_narration_lang(config or EngineConfig())
    c = coop_state(game)
    if qtype == "seed":
        type_rule = (
            "Write a SEED question: ask about an inner state, a hidden history or a latent "
            "detail that is not yet relevant but could become powerful later "
            "(e.g. an NPC's deepest fear or regret, what a place is hiding, what happened "
            "here before the protagonist arrived).")
    else:
        type_rule = (
            "Write a NOW question: ask about something specific that is narratively open "
            "right now and that the next scene can use - an unexpected arrival, a "
            "character's true motive, an object's significance, a hidden detail of this "
            "place.")
    system = (
        "You support a human Co-Game-Master (Co-GM) in a solo role-playing game. The Co-GM "
        "plays no character; after each scene they answer one question that adds a detail "
        "to the world, which the narrator then weaves into the story as a surprise for "
        "the player.\n\n"
        f"{type_rule}\n\n"
        "Rules:\n"
        "- One sentence, specific to the narration below. Something an improv partner "
        "would love to answer.\n"
        "- Never ask what happens next or what the protagonist does - that is the player's job.\n"
        "- Never ask about mechanics, numbers, stats or dice.\n"
        "- Do not repeat or closely paraphrase a question from <recent_questions>.\n"
        "- npc_id: the ID of the NPC the question is about (from <npcs>), else \"\".\n"
        "- seeds_surfaced: IDs from <check_seeds> whose content clearly appears in the "
        "narration (not just a vague overlap). Empty list if none.\n"
        f"- Write the question in {lang}."
    )
    npcs = [n for n in game.npcs if n.get("status") in ("active", "background")][:12]
    npc_lines = "\n".join(
        f'<npc id="{_xa(n.get("id", ""))}">{html.escape(n.get("name", ""))}: '
        f'{html.escape((n.get("description") or "")[:120])}</npc>' for n in npcs)
    recent = "\n".join(f"- {html.escape(q)}" for q in c.get("recent_questions", []))
    seeds = "\n".join(f'<seed id="{_xa(s["id"])}">{html.escape(s.get("text", ""))}</seed>'
                      for s in check_seeds)
    prompt = (
        f"<protagonist>{html.escape(game.player_name)}: "
        f"{html.escape(game.character_concept[:200])}</protagonist>\n"
        f"<location>{html.escape(game.current_location)}</location>\n"
        f"<npcs>\n{npc_lines}\n</npcs>\n"
        f"<recent_questions>\n{recent}\n</recent_questions>\n"
        f"<check_seeds>\n{seeds}\n</check_seeds>\n\n"
        f"<narration>{narration}</narration>\n\n"
        f"Write the next {qtype.upper()} question for the Co-GM."
    )
    response = _api_create_with_retry(
        client, max_retries=2,
        model=BRAIN_MODEL, max_tokens=COGM_QUESTION_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": COGM_QUESTION_SCHEMA}},
    )
    return json.loads(_response_text(response))


def generate_cogm_question(client: anthropic.Anthropic, game: GameState, narration: str,
                           config: Optional[EngineConfig] = None) -> Optional[dict]:
    """After a narration in an active co-op session: mark surfaced seeds and set
    the next Co-GM question. Returns the question, or None if the call failed
    (the UI then simply does not wait for the Co-GM this scene)."""
    c = coop_state(game)
    qtype = _cogm_next_question_type(game)
    # Seeds the scene could have used: last turn's offered seeds + its NOW answer
    last = (game.session_log[-1].get("cogm") if game.session_log else None) or {}
    offered = set(last.get("seeds_offered", []))
    now_seed = (last.get("answer") or {}).get("seed_id")
    if now_seed:
        offered.add(now_seed)
    check = [s for s in c["seeds"] if not s.get("used") and s["id"] in offered]
    try:
        result = call_cogm_question(client, game, narration, qtype, check, config)
    except Exception as e:
        log(f"[CoGM] Question call failed ({type(e).__name__}: {e})", level="warning")
        c["question"] = None
        return None
    check_ids = {s["id"] for s in check}
    for s in c["seeds"]:
        if s["id"] in check_ids and s["id"] in (result.get("seeds_surfaced") or []):
            s["used"] = True
            s["used_scene"] = game.scene_count
            log(f"[CoGM] Seed {s['id']} surfaced in scene {game.scene_count}")
    q = coop_set_question(game, result.get("question", ""), qtype, result.get("npc_id", ""))
    if q:
        c["questions_asked"] = int(c.get("questions_asked", 0)) + 1
        log(f"[CoGM] {qtype.upper()} question: {q['text'][:100]}")
    return q


def coop_reveal(game: GameState) -> dict:
    """"Behind the scenes": what the Co-GM contributed that already happened in
    the story — every NOW answer (used in the scene it was given for) and every
    seed, rumour, secret or false trail that surfaced. Unsurfaced content is
    only counted, so the reveal never spoils what is still to come."""
    c = coop_state(game)
    items, hidden = [], 0
    for s in c["seeds"]:
        kind = s.get("kind", "answer")
        if kind == "now" and s.get("injected") and not s.get("used"):
            scene = s.get("scene")                    # given to the Narrator for this scene
        elif s.get("used"):
            scene = s.get("used_scene")
        else:
            hidden += 1
            continue
        items.append({"chapter": int(s.get("chapter") or 1), "scene": int(scene or 0),
                      "kind": kind, "question": s.get("question", ""),
                      "text": s.get("text", ""),
                      "npc_name": _coop_npc_name(game, s.get("npc_id", ""))})
    items.sort(key=lambda i: (i["chapter"], i["scene"]))
    return {"items": items, "hidden": hidden, "partner": c.get("partner", "")}


def coop_pending_impulse(game: GameState) -> Optional[dict]:
    """The impulse queued for the next scene, or None (slot free)."""
    if not isinstance(game.coop, dict):
        return None
    return next((s for s in game.coop.get("signals", []) if s.get("impulse")), None)


def coop_public_view(game: GameState) -> dict:
    """What the Co-GM's cockpit lists: running signals and unused planted lore
    (with display names). The Narrator-only seed texts of SEED answers are shown
    too — the Co-GM wrote them."""
    c = coop_state(game)
    impulse, background = None, []
    for s in c["signals"]:
        item = {**s, "npc_name": _coop_npc_name(game, s.get("npc_id", ""))}
        if s.get("impulse"):
            impulse = item
        else:
            background.append(item)
    seeds = [dict(s) for s in c["seeds"] if not s.get("used")]
    return {"impulse": impulse, "signals": background, "seeds": seeds}


# ===============================================================
# RESPONSE PARSER
# ===============================================================

def _process_game_data(game: GameState, data: dict, force_npcs: bool = True):
    """Process structured game_data from narrator response (opening scene).
    Shared logic for both tagged and untagged game_data extraction.
    If force_npcs=False, only sets game.npcs when currently empty (fallback parsing)."""
    if data.get("npcs"):
        # Determine starting ID counter from existing NPCs
        max_num = 0
        for n in game.npcs:
            id_match = re.match(r'npc_(\d+)', str(n.get("id", "")))
            if id_match:
                max_num = max(max_num, int(id_match.group(1)))
        # Drop unnamed entries and same-name duplicates within the opening list
        _seen_names = set()
        _clean_npcs = []
        for nd in data["npcs"]:
            if not isinstance(nd, dict):
                continue
            nd["name"] = " ".join(str(nd.get("name") or "").split())
            if "(" not in nd["name"]:
                nd["name"] = _cap_npc_name(nd["name"])   # parentheticals: sanitized below
            _norm = _normalize_for_match(_sanitize_npc_name(nd["name"])[0])
            if not _norm or _norm in _seen_names:
                log(f"[NPC] Opening game_data: skipped {'unnamed' if not _norm else 'duplicate'} "
                    f"NPC '{nd['name'][:60]}'", level="warning")
                continue
            _seen_names.add(_norm)
            nd["disposition"] = _normalize_disposition(str(nd.get("disposition") or "neutral"))
            _clean_npcs.append(nd)
        data["npcs"] = _clean_npcs
        for nd in data["npcs"]:
            # Assign consistent NPC ID if missing or non-standard format
            if not nd.get("id") or not re.match(r'^npc_\d+$', str(nd.get("id", ""))):
                max_num += 1
                nd["id"] = f"npc_{max_num}"
            else:
                # Track AI-provided IDs to avoid collisions
                id_match = re.match(r'npc_(\d+)', nd["id"])
                if id_match:
                    max_num = max(max_num, int(id_match.group(1)))
            nd.setdefault("status", "active")
            nd.setdefault("bond", 0)
            nd.setdefault("bond_max", 4)
            nd.setdefault("memory", [])
            nd.setdefault("introduced", False)
            nd.setdefault("aliases", [])
            nd.setdefault("importance_accumulator", 0)
            nd.setdefault("last_reflection_scene", 0)
            nd.setdefault("last_memory_scene", 0)
            nd.setdefault("last_location", game.current_location or "")
            nd.setdefault("arc", "")           # Narrative trajectory — set by Director on first reflection
            nd.setdefault("absent_until_scene", 0)  # Exit suppression — always 0 for opening NPCs
            nd["memory"] = [
                m if isinstance(m, dict) else {"scene": 0, "event": str(m), "emotional_weight": "neutral"}
                for m in nd["memory"]
            ]
            # Score opening scene memories for importance (diagnostic consistency)
            for m in nd["memory"]:
                if isinstance(m, dict) and "importance" not in m:
                    ew = m.get("emotional_weight", "neutral")
                    ev = m.get("event", "")
                    imp, dbg = score_importance(ew, ev, debug=True)
                    m["importance"] = imp
                    m["type"] = m.get("type", "observation")
                    m["_score_debug"] = f"opening game_data | {dbg}"
            # Safety net: create seed memory for hollow opening NPCs (no memories
            # provided by the opening extractor).  Mirrors _process_new_npcs logic:
            # ensures last_memory_scene is set, the established-character guard in
            # _process_npc_renames/_process_npc_details can protect them, and the
            # Director can include them in reflections on the first cycle.
            if not nd["memory"]:
                # Use description as seed event if available; fall back to the name.
                # Note: _apply_name_sanitization runs after this loop, so we strip
                # any parenthetical annotation from the fallback string manually.
                _raw_seed_name = nd.get("name", "?")
                _clean_seed_name = _raw_seed_name.split("(")[0].strip() if "(" in _raw_seed_name else _raw_seed_name
                seed_event = nd.get("description", "") or f"{_clean_seed_name} appeared"
                seed_disp  = _normalize_disposition(nd.get("disposition", "neutral"))
                _disp_to_emotion = {
                    "hostile": "hostile", "distrustful": "suspicious",
                    "neutral": "neutral", "friendly": "curious", "loyal": "trusting",
                }
                seed_emotion = _disp_to_emotion.get(seed_disp, "neutral")
                seed_imp, seed_dbg = score_importance(seed_emotion, seed_event, debug=True)
                seed_imp = max(seed_imp, 3)
                nd["memory"].append({
                    "scene": game.scene_count,
                    "event": seed_event,
                    "emotional_weight": seed_emotion,
                    "importance": seed_imp,
                    "type": "observation",
                    "_score_debug": f"auto-seed from opening game_data | {seed_dbg}",
                })
                nd["last_memory_scene"] = game.scene_count
        # Filter out NPCs that match the player character name
        player_norm = _normalize_for_match(game.player_name)
        data["npcs"] = [
            n for n in data["npcs"]
            if _normalize_for_match(n.get("name", "")) != player_norm
        ]
        # Sanitize NPC names: strip parenthetical annotations → aliases
        for nd in data["npcs"]:
            _apply_name_sanitization(nd)
        if force_npcs or not game.npcs:
            game.npcs = data["npcs"]
            log(f"[NPC] Opening game_data: set {len(game.npcs)} NPCs: {[n.get('name','?') for n in game.npcs]}")
    if data.get("clocks"):
        existing_ids = {c.get("id") for c in game.clocks if c.get("id")}
        # Determine starting clock ID counter from existing clocks
        max_clock_num = 0
        for c in game.clocks:
            cid_match = re.match(r'clock_(\d+)', str(c.get("id", "")))
            if cid_match:
                max_clock_num = max(max_clock_num, int(cid_match.group(1)))
        sanitized = []
        for c in data["clocks"]:
            clean = _sanitize_new_clock(c)
            if clean is None:
                log(f"[Clock] Skipped unusable clock proposal: {c!r}"[:200], level="warning")
                continue
            # Keep a valid AI-provided ID, otherwise assign the next one
            cid = c.get("id") if isinstance(c, dict) else None
            if not cid or not re.match(r'^clock_\d+$', str(cid)):
                max_clock_num += 1
                cid = f"clock_{max_clock_num}"
            sanitized.append({"id": cid, **clean})
        data["clocks"] = sanitized
        new_clocks = [c for c in data["clocks"] if c.get("id") not in existing_ids]
        if new_clocks:
            game.clocks.extend(new_clocks)
            log(f"[Clock] Added {len(new_clocks)} new clocks (skipped {len(data['clocks']) - len(new_clocks)} duplicates)")
    if data.get("location"):
        update_location(game, data["location"])
    if data.get("scene_context"):
        game.current_scene_context = data["scene_context"]
    if data.get("time_of_day") and data["time_of_day"] in TIME_PHASES:
        game.time_of_day = data["time_of_day"]
        game.time_unchanged_scenes = 0


def parse_narrator_response(game: GameState, raw: str) -> str:
    """Parse narrator response: extract game_data (opening scenes) and clean prose.
    Metadata extraction (memory_updates, scene_context, NPCs, etc.) is handled
    separately by call_narrator_metadata() — this function only strips leaked
    metadata from the prose to keep it player-facing clean."""
    narration = raw

    # --- 0) Strip accidental role-label prefix (e.g. "Narrator:" in English) ---
    # Sonnet occasionally prefixes responses with the role name from the system prompt.
    narration = re.sub(r'^\s*Narrator:\s*', '', narration, flags=re.IGNORECASE)

    # --- 1) Tagged game_data (opening scene / new chapter) ---
    gd = re.search(r'<game_data>([\s\S]*?)</game_data>', narration)
    if gd:
        log(f"[Parser] Step 1: Found <game_data> tag ({len(gd.group(1))} chars)")
        try:
            data = json.loads(gd.group(1))
            if game.scene_count <= 1:
                _process_game_data(game, data)
            else:
                log(f"[Parser] Step 1: Mid-game <game_data> detected (scene {game.scene_count}), "
                    f"using force_npcs=False to prevent NPC list replacement")
                _process_game_data(game, data, force_npcs=False)
        except (json.JSONDecodeError, KeyError) as e:
            log(f"[Parser] Step 1: Failed to parse game_data JSON: {e}", level="warning")
        narration = re.sub(r'<game_data>[\s\S]*?</game_data>', '', narration).strip()

    # --- 1.5) Untagged game_data (Narrator omitted XML tags) ---
    if not gd:
        npcs_obj_match = re.search(r'\{[\s\S]*?"npcs"\s*:\s*\[', narration)
        if npcs_obj_match:
            log(f"[Parser] Step 1.5: Found untagged game_data JSON at pos {npcs_obj_match.start()}")
            start = npcs_obj_match.start()
            try:
                decoder = json.JSONDecoder()
                data, end_idx = decoder.raw_decode(narration, start)
                if isinstance(data, dict) and (data.get("npcs") or data.get("clocks")):
                    _process_game_data(game, data)
                    narration = (narration[:start].rstrip() + "\n" + narration[start + end_idx:].lstrip()).strip()
            except (json.JSONDecodeError, ValueError) as e:
                log(f"[Parser] Step 1.5: Failed to parse untagged game_data: {e}", level="warning")

    # --- 2) Strip all XML metadata tags (narrator may still emit them from history) ---
    narration = re.sub(r'<(?:npc_rename|new_npcs|npc_details|memory_updates|scene_context|'
                       r'location_update|time_update|game_data)>[\s\S]*?</(?:npc_rename|new_npcs|'
                       r'npc_details|memory_updates|scene_context|location_update|time_update|'
                       r'game_data)>', '', narration).strip()
    # Strip prompt-echo tags (narrator sometimes echoes input XML)
    narration = re.sub(r'</?(?:task|scene|world|character|situation|conflict|possible_endings|'
                       r'session_log|npc|returning_npc|campaign_history|chapter|story_arc|'
                       r'story_ending|momentum_burn|revelation_ready)[^>]*>', '', narration).strip()

    # --- 3) Strip code fences ---
    narration = re.sub(r'```(?:\w+)?\s*[\s\S]*?```', '', narration).strip()
    narration = re.sub(r'^\s*```(?:\w+)?\s*$', '', narration, flags=re.MULTILINE).strip()

    # --- 4) Strip JSON arrays/objects that leaked into prose ---
    narration = re.sub(r'\[[\s]*\{[^[\]]*"(?:npc_id|event|emotional_weight)"[\s\S]*$',
                       '', narration).strip()
    narration = re.sub(r'\{[^{}]*"(?:scene_context|location|npc_id)"[^{}]*\}', '', narration).strip()

    # --- 5) Strip bracket-format metadata labels ---
    narration = re.sub(
        r'^\[(?:memory[_\s-]*updates?|scene[_\s-]*context|new[_\s-]*npcs?|npc[_\s-]*renames?|'
        r'npc[_\s-]*details?|location[_\s-]*update?|time[_\s-]*update?|game[_\s-]*data)\].*$',
        '', narration, flags=re.IGNORECASE | re.MULTILINE).strip()

    # --- 6) Strip markdown metadata labels (Scene Context:, etc.) ---
    meta_match = re.search(
        r'^[*_#\s]*(scene[\s_-]*context|memory[\s_-]*updates?|szenenkontext|location)\s*[*_#]*\s*[:=]\s*',
        narration, re.IGNORECASE | re.MULTILINE,
    )
    if meta_match:
        narration = narration[:meta_match.start()].rstrip()

    # --- 7) Strip trailing JSON lines ---
    lines = narration.rstrip().split('\n')
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if last.startswith(('{', '[')):
            lines.pop()
            continue
        clean_last = re.sub(r'^[\s*_#]+', '', last)
        if re.match(r'^(scene[\s_-]*context|memory[\s_-]*updates?|location|szenenkontext)\s*[:=]',
                    clean_last, re.IGNORECASE):
            lines.pop()
            continue
        break
    narration = '\n'.join(lines).rstrip()

    # --- 7.5) Strip bold-bracket game mechanic annotations ---
    # Sonnet (especially in English) emits annotations like:
    #   **[THREAT CLOCK CREATED: Corporate Trace - 0/4]**
    #   **[CLOCK ADVANCE: +1]**  *[Scene context: ...]*
    # These must be removed BEFORE step 8 strips the ** markers — otherwise the
    # bracket content would survive and appear as plain text in the output.
    narration = re.sub(r'\*{1,3}\[[^\]]+\]\*{1,3}', '', narration).strip()
    # Also catch unbolded bare [ANNOTATION: ...] lines (e.g. after ** stripping in history)
    narration = re.sub(
        r'^\s*\[[A-Z][A-Z0-9 _\-]*:?[^\]]*\]\s*$',
        '', narration, flags=re.MULTILINE).strip()

    # --- 8) Strip markdown artifacts ---
    narration = re.sub(r'^\s*[-*_]{3,}\s*$', '', narration, flags=re.MULTILINE).strip()
    narration = re.sub(r'\s*\*{1,3}\s*$', '', narration, flags=re.MULTILINE).rstrip()
    # Strip markdown emphasis: ***bold-italic***, **bold**, *italic*
    narration = re.sub(r'\*{3}(.+?)\*{3}', r'\1', narration)
    narration = re.sub(r'\*{2}(.+?)\*{2}', r'\1', narration)
    narration = re.sub(r'\*(.+?)\*', r'\1', narration)
    # Strip orphaned asterisks (unclosed emphasis: opening * without matching close)
    narration = re.sub(r'(?<!\*)\*(?!\*)', '', narration)

    # --- 8.5) Normalize em-dash spacing, then replace with regular hyphen ---
    # First ensure exactly one space on each side (handles "A—B", "A— B", "A —B"),
    # then convert em-dash (—) and en-dash (–) to a spaced hyphen for cleaner rendering.
    narration = re.sub(r'\s*[—–]\s*', ' - ', narration)

    # --- 9) Normalize NPC dispositions ---
    _normalize_npc_dispositions(game.npcs)

    # --- 10) Mark NPCs as introduced if their name appears in visible text ---
    narration_lower = narration.lower()
    for npc in game.npcs:
        if not npc.get("introduced", False) and npc.get("name"):
            name = npc["name"].strip()
            if not name:
                continue
            # Check full name first
            if name.lower() in narration_lower:
                npc["introduced"] = True
                continue
            # Check individual name parts (e.g. "Totewald" from
            # "Geschäftsführer Clemens Totewald") — min 4 chars to avoid
            # matching generic words like "der", "von"; skip known titles
            for part in name.split():
                part_clean = part.strip(".,;:!?\"'()-").lower()
                if len(part_clean) >= 4 and part_clean not in _NAME_TITLES \
                        and part_clean in narration_lower:
                    npc["introduced"] = True
                    break

    # Summary log
    active = [n for n in game.npcs if n.get("status") == "active"]
    background = [n for n in game.npcs if n.get("status") == "background"]
    lore = [n for n in game.npcs if n.get("status") == "lore"]
    introduced = [n for n in active if n.get("introduced", False)]
    log(f"[Parser] Done. NPCs total={len(game.npcs)} active={len(active)} background={len(background)} "
        f"lore={len(lore)} introduced={len(introduced)}: {[n['name'] for n in introduced]}")

    # Safety: if parser stripped everything, return a minimal fallback
    if not narration.strip():
        log("[Parser] WARNING: Narration empty after parsing — returning raw text excerpt", level="warning")
        for para in raw.split('\n\n'):
            clean_para = para.strip()
            if clean_para and not clean_para.startswith(('<', '{', '[', '```')):
                narration = clean_para
                break
        if not narration.strip():
            narration = "(The narrator pauses, gathering thoughts...)"

    return narration


def _apply_memory_updates(game: GameState, json_text: str,
                          scene_present_ids: set = None,
                          pre_turn_npc_ids: set = None,
                          pre_turn_lore_ids: set = None):
    """Apply NPC memory updates from JSON text with importance scoring and consolidation.

    scene_present_ids: set of NPC IDs activated or mentioned in this scene (from
        activate_npcs_for_prompt). When provided together with pre_turn_npc_ids,
        memory updates for NPCs that were NOT present in the scene are rejected —
        this prevents the Metadata Extractor from hallucinating memories for absent NPCs.
    pre_turn_npc_ids: set of NPC IDs that existed BEFORE this turn's new_npcs were added.
        Required to allow memories for freshly-created NPCs (who are absent from
        scene_present_ids because they weren't known at activation time) and for
        auto-created stubs inside this function (pre_turn_npc_ids=None for those).
        Lore NPCs are always exempt — they accumulate memories regardless of presence.
    pre_turn_lore_ids: set of NPC IDs that had status="lore" at the START of this
        metadata cycle (before _process_new_npcs may have promoted them to active).
        Exempts lore→active transitions from the presence guard — a figure that just
        physically appeared for the first time legitimately gets a memory even if
        activate_npcs_for_prompt didn't know about them yet.
    """
    try:
        updates = json.loads(json_text.strip())
        if not isinstance(updates, list):
            return
        for u in updates:
            if not isinstance(u, dict) or "npc_id" not in u:
                continue
            npc = _find_npc(game, u["npc_id"])
            is_absent_mention = bool(u.get("absent"))

            # Fuzzy fallback: try word-overlap matching before creating a stub
            # v0.9.29: additional first-name mismatch guard
            if not npc and u["npc_id"] and u["npc_id"] not in ("world", "player", ""):
                fuzzy_candidate, _ = _fuzzy_match_existing_npc(game, u["npc_id"])
                if fuzzy_candidate:
                    # Safety: if both names have 2+ words, verify first names aren't
                    # completely different (prevents "Marissa Chen" → "Mrs. Chen")
                    ref_parts = u["npc_id"].strip().split()
                    match_parts = fuzzy_candidate["name"].strip().split()
                    if len(ref_parts) >= 2 and len(match_parts) >= 2:
                        ref_first = ref_parts[0].lower().strip(".")
                        match_first = match_parts[0].lower().strip(".")
                        if (ref_first not in _NAME_TITLES
                                and match_first not in _NAME_TITLES
                                and ref_first != match_first
                                and ref_first not in match_first
                                and match_first not in ref_first):
                            log(f"[NPC] memory_update fuzzy REJECTED: '{u['npc_id']}' ~ "
                                f"'{fuzzy_candidate['name']}' (first-name mismatch: "
                                f"'{ref_first}' vs '{match_first}')")
                            fuzzy_candidate = None
                    if fuzzy_candidate:
                        npc = fuzzy_candidate
                        log(f"[NPC] memory_update fuzzy-matched '{u['npc_id']}' → '{npc['name']}'")

            # Auto-create NPC stub if not found (safety net when <new_npcs> was omitted).
            # Exception: absent=true entries reference off-screen NPCs that are already
            # tracked — never create a new stub for an absent mention.
            if (not npc and u["npc_id"] and u["npc_id"] not in ("world", "player", "")
                    and not u.get("absent")):
                npc_name = u["npc_id"]
                # Skip technical ID references (e.g. "npc_4") — this is a Narrator
                # reference error to an existing NPC, not a new character
                if re.match(r'^npc_\d+$', npc_name, re.IGNORECASE):
                    log(f"[NPC] Skipping auto-stub for technical ID reference: "
                        f"{npc_name}", level="warning")
                    continue
                # Humanize snake_case names: "frau_seidlitz" → "Frau Seidlitz"
                # Defense-in-depth: if _find_npc underscore normalization missed,
                # at least the stub gets a readable display name.
                if "_" in npc_name and " " not in npc_name:
                    npc_name = npc_name.replace("_", " ").title()
                npc_name = _sanitize_npc_name(npc_name)[0]
                if not npc_name or npc_name.upper() == "NEW":
                    log(f"[NPC] Skipping auto-stub for unusable reference {u['npc_id']!r}",
                        level="warning")
                    continue
                # Guard: if an NPC with this name or alias already exists, route
                # the memory update to them instead of creating a duplicate stub.
                # _find_npc covers exact name, aliases, and substring — so this
                # also handles cases where the name is only an alias of an NPC.
                existing_by_name = _find_npc(game, npc_name)
                if existing_by_name:
                    npc = existing_by_name
                    # Do NOT call _reactivate_npc here — the presence guard below
                    # must run first.  If the guard passes, the background-NPC branch
                    # inside `if npc:` reactivates correctly.  If the guard blocks the
                    # update, we must not have promoted the NPC's status unnecessarily.
                    log(f"[NPC] Auto-stub suppressed: '{npc_name}' matched existing "
                        f"'{npc['name']}' ({npc.get('id', '?')}) by name/alias")
                elif (_normalize_for_match(npc_name) != _normalize_for_match(game.player_name)
                        and not (set(_normalize_for_match(npc_name).split())
                                 & set(_normalize_for_match(game.player_name).split()))):
                    npc_id, _ = _next_npc_id(game)
                    npc = {
                        "id": npc_id,
                        "name": npc_name,
                        "description": "",
                        "agenda": "", "instinct": "", "secrets": [],
                        "disposition": "neutral",
                        "bond": 0, "bond_max": 4,
                        "status": "active",
                        "memory": [],
                        "introduced": True,
                        "aliases": [],
                        "importance_accumulator": 0,
                        "last_reflection_scene": 0,
                        "last_memory_scene": 0,
                        "last_location": game.current_location or "",
                    }
                    game.npcs.append(npc)
                    log(f"[NPC] Auto-created stub NPC from memory_update: {npc_name}")

            # Absent mention for unknown NPC — no auto-stub created, log and skip.
            if is_absent_mention and not npc:
                npc_ref = u.get("npc_id", "?")
                log(f"[NPC] absent mention SKIPPED — npc_id '{npc_ref}' not found "
                    f"and no auto-stub for absent entries", level="warning")
                continue

            # Presence guard: reject memory updates for NPCs that were not in this
            # scene.  Conditions for rejection (ALL must be true):
            #   - scene_present_ids is provided (guard is active)
            #   - NPC not in scene_present_ids (not activated or mentioned)
            #   - NPC is not currently lore (lore always accumulates memories)
            #   - NPC was not lore at the START of this cycle (pre_turn_lore_ids
            #     exemption: lore→active transitions get their first-appearance memory)
            #   - NPC is not deceased (deceased NPCs are excluded from activate_npcs_for_prompt
            #     by design, so they can never enter scene_present_ids — blocking them here
            #     would permanently prevent resurrection via memory_updates)
            #   - pre_turn_npc_ids is provided AND the NPC was known before this turn
            #     (freshly-created NPCs and auto-stubs are always allowed through)
            #   EXCEPTION: absent=true entries bypass the presence guard (handled below).
            if (npc
                    and not is_absent_mention
                    and scene_present_ids is not None
                    and npc["id"] not in scene_present_ids
                    and npc.get("status") not in ("lore", "deceased")
                    and (pre_turn_lore_ids is None or npc["id"] not in pre_turn_lore_ids)
                    and pre_turn_npc_ids is not None
                    and npc["id"] in pre_turn_npc_ids):
                log(f"[NPC] memory_update SKIPPED for '{npc['name']}' ({npc['id']}) — "
                    f"not present in scene {game.scene_count} (extractor hallucination)",
                    level="warning")
                continue

            if npc:
                # absent=true: NPC was mentioned off-screen with narrative significance.
                # Conditions for using the absent (mention) path — ALL must hold:
                #   (a) Extractor flagged absent=true
                #   (b) NPC is not deceased (out of story — no updates)
                #   (c) NPC is not lore (already presence-guard-exempt; lore NPCs use the
                #       normal path so they receive full importance + accumulator weight)
                if (is_absent_mention
                        and npc.get("status") != "deceased"
                        and npc.get("status") != "lore"):
                    # Rate-limit: max 1 absent-mention per NPC per scene,
                    # and max 2 absent-mentions globally per scene.
                    absent_this_scene = sum(
                        1 for m in npc.get("memory", [])
                        if isinstance(m, dict)
                        and m.get("scene") == game.scene_count
                        and m.get("type") == "mention"
                    )
                    total_absent_this_scene = sum(
                        1 for n in game.npcs
                        for m in n.get("memory", [])
                        if isinstance(m, dict)
                        and m.get("scene") == game.scene_count
                        and m.get("type") == "mention"
                    )
                    if absent_this_scene > 0 or total_absent_this_scene >= 2:
                        log(f"[NPC] absent mention SKIPPED for '{npc.get('name','?')}' — "
                            f"cap reached (total absent this scene: {total_absent_this_scene})",
                            level="warning")
                        continue
                    # Absent mentions: do NOT reactivate background NPCs, do NOT
                    # update last_location — the NPC stayed where they were.
                    _ensure_npc_memory_fields(npc)
                    npc["memory"].append({
                        "scene": game.scene_count,
                        "event": u.get("event", ""),
                        "emotional_weight": u.get("emotional_weight", "neutral"),
                        "importance": 3,   # Fixed low importance — weak off-screen signal
                        "type": "mention",
                        "about_npc": _resolve_about_npc(game, u.get("about_npc"),
                                                        owner_id=npc.get("id")),
                    })
                    # Absent mentions do not drive Director reflections — importance
                    # accumulator intentionally not incremented.
                    npc["last_memory_scene"] = game.scene_count
                    _consolidate_memory(npc)
                    log(f"[NPC] Absent mention memory for {npc.get('name','?')} "
                        f"(scene {game.scene_count}): {u.get('event','')[:60]}")
                    continue
                elif is_absent_mention and npc.get("status") == "deceased":
                    log(f"[NPC] absent mention SKIPPED for '{npc.get('name','?')}' — deceased",
                        level="warning")
                    continue
                # else: absent=true for lore NPCs, or absent=false — fall through to normal path

                # Normal path: NPC physically present in scene.
                # Resurrect deceased NPCs if the extractor reports them as active
                # (exact npc_id match = extractor considers them physically present)
                if npc.get("status") == "deceased":
                    _reactivate_npc(npc, reason="memory_update for deceased NPC — "
                                    "resurrection detected", force=True)
                # Reactivate background NPCs that appear in current scene.
                # Lore NPCs are intentionally NOT reactivated here — they accumulate
                # memories without becoming active (only new_npcs triggers lore → active).
                elif npc.get("status") == "background":
                    _reactivate_npc(npc, reason="memory_update in current scene")
                # Ensure memory system fields exist
                _ensure_npc_memory_fields(npc)

                event_text = u.get("event", "")
                emotional = u.get("emotional_weight", "neutral")
                importance, score_debug = score_importance(emotional, event_text, debug=True)

                npc["memory"].append({
                    "scene": game.scene_count,
                    "event": event_text,
                    "emotional_weight": emotional,
                    "importance": importance,
                    "type": "observation",
                    "about_npc": _resolve_about_npc(game, u.get("about_npc"), owner_id=npc.get("id")),
                    "_score_debug": score_debug,
                })
                npc["last_memory_scene"] = game.scene_count

                # Update importance accumulator for reflection triggering
                npc["importance_accumulator"] = npc.get("importance_accumulator", 0) + importance
                # Track where this NPC was last seen (spatial consistency).
                # Only update for NPCs physically present in the scene (in scene_present_ids).
                # NPCs only mentioned in dialog or remote (e.g. in a different time period)
                # receive memory entries but must NOT have their location overwritten with
                # the player's current location — they stayed where they were.
                # Exemption: lore→active transitions (npc_id in pre_turn_lore_ids).
                # These NPCs physically appeared this scene but were not in scene_present_ids
                # (built before the metadata cycle) — _reactivate_npc does not set
                # last_location, so without this exemption they would remain at ""
                # despite arriving on-screen.
                if game.current_location and (
                    scene_present_ids is None
                    or npc["id"] in scene_present_ids
                    or (pre_turn_lore_ids is not None and npc["id"] in pre_turn_lore_ids)
                ):
                    npc["last_location"] = game.current_location
                if npc["importance_accumulator"] >= REFLECTION_THRESHOLD:
                    if not npc.get("_needs_reflection"):
                        log(f"[NPC] {npc['name']} needs reflection "
                            f"(accumulator={npc['importance_accumulator']})")
                    npc["_needs_reflection"] = True

                # Consolidate memory (replaces simple FIFO)
                _consolidate_memory(npc)

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Memory update failed: {e}", level="warning")



# ===============================================================
# SAVE / LOAD
# ===============================================================

SAVE_FIELDS = [
    "player_name", "character_concept", "setting_genre", "setting_tone", "setting_archetype",
    "setting_description", "edge", "heart", "iron", "shadow", "wits",
    "health", "spirit", "supply", "momentum", "max_momentum", "scene_count",
    "current_location", "current_scene_context", "npcs", "clocks",
    "session_log", "narration_history", "story_blueprint", "crisis_mode", "game_over",
    # v5.0
    "chaos_factor", "scene_intensity_history",
    # v5.3: Campaign
    "campaign_history", "chapter_number",
    # v5.7: Content boundaries
    "player_wishes", "content_lines",
    # v5.8: Temporal & spatial consistency
    "time_of_day", "location_history", "scenes_at_location",
    # v5.9: Epilogue system
    "epilogue_shown",
    "epilogue_dismissed",
    "epilogue_text",           # Persisted to survive reload between epilogue generation and new-chapter start; cleared by start_new_chapter() after use
    # v5.10: Backstory
    "backstory",
    # v5.11: Director guidance
    "director_guidance",
    # v5.12: Last turn snapshot (persisted to allow ## correction after reload)
    "last_turn_snapshot",
    # 0.9.96: version history lives in GameState (no read-before-write in save_game)
    "version_history",
    # Co-op mode: Co-GM question/answer, cockpit signals, planted seeds
    "coop",
]

# Compact JSON for game saves and chapter archives: no indentation/spaces. Saves
# carry the whole chat history and are written twice per turn — compact output is
# markedly smaller and faster to write on a Pi's SD card. Pretty-print for manual
# inspection with:  python -m json.tool users/<name>/saves/<slot>.json
_SAVE_JSON_KW = {"ensure_ascii": False, "separators": (",", ":")}

def save_game(game: GameState, username: str, chat_messages: list = None,
              name: str = "autosave") -> Path:
    """Save game state and chat history. UI layer must provide username and chat_messages."""
    save_dir = _get_save_dir(username)
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{name}.json"
    # Version history travels with the GameState: new games start with an empty
    # list, chapters and "Save As" copies inherit it — no read of the old file.
    if not game.version_history or game.version_history[-1] != VERSION:
        game.version_history.append(VERSION)
    data = {"saved_at": datetime.now().isoformat()}
    data["engine_version"] = VERSION
    data.update({k: getattr(game, k) for k in SAVE_FIELDS})
    # last_turn_snapshot may contain a RollResult dataclass — serialize to plain dict
    if data.get("last_turn_snapshot") and data["last_turn_snapshot"].get("roll") is not None:
        data["last_turn_snapshot"] = dict(data["last_turn_snapshot"])
        data["last_turn_snapshot"]["roll"] = dataclasses.asdict(data["last_turn_snapshot"]["roll"])
    # Chat history for visual restoration (strip audio binary data and transient recaps)
    raw_messages = chat_messages or []
    data["chat_messages"] = [
        {k: v for k, v in msg.items() if k not in ("audio_bytes", "audio_format")}
        for msg in raw_messages
        if not msg.get("recap")
    ]
    _atomic_write_text(path, json.dumps(data, **_SAVE_JSON_KW))
    log(f"[Save] Game saved: {username}/{name} (Scene {game.scene_count}, {len(data['chat_messages'])} chat msgs)")
    return path


def load_game(username: str, name: str = "autosave") -> tuple[Optional[GameState], list]:
    """Load game state and chat history. Returns (game, chat_messages)."""
    save_dir = _get_save_dir(username)
    path = save_dir / f"{name}.json"
    if not path.exists():
        log(f"[Load] Save not found: {username}/{name}", level="warning")
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log(f"[Load] Save unreadable: {username}/{name} ({type(e).__name__}: {e})", level="warning")
        return None, []
    game = GameState()
    for k, v in data.items():
        if k not in ("saved_at", "chat_messages") and hasattr(game, k):
            setattr(game, k, v)
    # Backward compatibility: saves before version_history existed carried only
    # engine_version (or nothing). Seed the list so history is not lost.
    if not isinstance(game.version_history, list):
        game.version_history = []
    if not game.version_history and data.get("engine_version"):
        game.version_history = [data["engine_version"]]
    # Co-op state: older saves have none; a turn-transient key never survives a load
    if not isinstance(game.coop, dict):
        game.coop = {}
    game.coop.pop("_turn", None)
    # Reconstruct RollResult dataclass from plain dict (was serialized in save_game)
    if (game.last_turn_snapshot is not None
            and isinstance(game.last_turn_snapshot.get("roll"), dict)):
        r = game.last_turn_snapshot["roll"]
        game.last_turn_snapshot["roll"] = RollResult(**r)
    # Normalize dispositions from older saves that may have non-canonical values
    _normalize_npc_dispositions(game.npcs)
    # Backward compatibility: older saves don't have 'introduced' flag -- assume all existing NPCs were introduced
    for npc in game.npcs:
        npc.setdefault("introduced", True)
    # Backward compatibility: older saves don't have 'aliases' field
    for npc in game.npcs:
        npc.setdefault("aliases", [])
    # Clean up self-aliases (bug in older versions: current name ended up in aliases list)
    for npc in game.npcs:
        name_norm = _normalize_for_match(npc.get("name", ""))
        npc["aliases"] = [a for a in npc.get("aliases", []) if _normalize_for_match(a) != name_norm]
    # Backward compatibility: migrate old "inactive" status to "background" (three-tier NPC system v0.9.14)
    for npc in game.npcs:
        if npc.get("status") == "inactive":
            npc["status"] = "background"
    # Backward compatibility: migrate NPC memory system fields (v5.11)
    for npc in game.npcs:
        _ensure_npc_memory_fields(npc)
    # Reconstruct _needs_reflection from importance_accumulator on load.
    # The flag itself is not persisted (it was previously stripped on load), but the
    # accumulator IS saved — so we can deterministically reconstruct it.
    # Without this, a saved NPC with accumulator >= REFLECTION_THRESHOLD would lose
    # its pending reflection after a reload and only re-trigger if new memories arrived.
    for npc in game.npcs:
        if npc.get("importance_accumulator", 0) >= REFLECTION_THRESHOLD:
            npc["_needs_reflection"] = True
        else:
            npc.pop("_needs_reflection", None)
    # Clean up legacy 'last_seen' field (replaced by 'last_location' in v0.9.14+)
    for npc in game.npcs:
        npc.pop("last_seen", None)
    # Backward compatibility: older saves don't have 'absent_until_scene' field
    for npc in game.npcs:
        npc.setdefault("absent_until_scene", 0)
    # Repair: generate seed memory for NPCs that have none (older saves, data loss)
    for npc in game.npcs:
        if (npc.get("status") in ("active", "background")
                and not npc.get("memory")
                and npc.get("introduced")):
            desc = npc.get("description", "")
            seed_event = desc or f"{npc.get('name', 'Unknown')} appeared"
            disp = npc.get("disposition", "neutral")
            _disp_to_emotion = {
                "hostile": "hostile", "distrustful": "suspicious",
                "neutral": "neutral", "friendly": "curious", "loyal": "trusting",
            }
            seed_emotion = _disp_to_emotion.get(disp, "neutral")
            seed_imp, seed_debug = score_importance(seed_emotion, seed_event, debug=True)
            seed_imp = max(seed_imp, 3)
            npc.setdefault("memory", [])
            npc["memory"].append({
                "scene": 0,
                "event": seed_event,
                "emotional_weight": seed_emotion,
                "importance": seed_imp,
                "type": "observation",
                "_score_debug": f"load-repair seed | {seed_debug}",
            })
            log(f"[Load] Repaired empty memory for '{npc.get('name', '?')}' "
                f"({npc.get('id', '?')}) — added seed from description")
    # Sanitize NPC names: strip parenthetical annotations from older saves
    for npc in game.npcs:
        _apply_name_sanitization(npc)
    # Backward compatibility: older saves don't have location_history/time_of_day
    if game.location_history is None:
        game.location_history = []
    if game.time_of_day is None:
        game.time_of_day = ""
    # Repair clocks with unusable numbers (would divide by zero in the sidebar)
    for clock in game.clocks:
        try:
            clock["segments"] = max(1, int(clock.get("segments", 6)))
        except (TypeError, ValueError):
            clock["segments"] = 6
        try:
            clock["filled"] = max(0, min(int(clock.get("filled", 0)), clock["segments"]))
        except (TypeError, ValueError):
            clock["filled"] = 0
    # Backward compatibility: backfill fired=True for fully filled clocks in older saves
    for clock in game.clocks:
        if clock.get("filled", 0) >= clock.get("segments", 1) and "fired" not in clock:
            clock["fired"] = True
        # Normalize fired=None (written by older extractor code) to fired=False
        if clock.get("fired") is None:
            clock["fired"] = False
        # fired_at_scene=0 means "fire scene unknown" — _purge_old_fired_clocks
        # will remove it on the next turn (0 is always > keep_scenes scenes ago)
        if clock.get("fired") and "fired_at_scene" not in clock:
            clock["fired_at_scene"] = 0
    # Repair clock owners that still carry a stale NPC name (saves from before the
    # live sync below, or renames that predate it).
    _sync_clock_owners(game, "Load")
    # Normalize story_blueprint null fields: Story Architect occasionally returns
    # triggered_transitions/story_complete/revealed as JSON null instead of omitting them,
    # causing set(None) → TypeError in get_current_act, _check_story_completion,
    # get_pending_revelations, and _build_turn_snapshot.
    if game.story_blueprint:
        if game.story_blueprint.get("triggered_transitions") is None:
            game.story_blueprint.pop("triggered_transitions", None)
        if game.story_blueprint.get("story_complete") is None:
            game.story_blueprint.pop("story_complete", None)
        if game.story_blueprint.get("revealed") is None:
            game.story_blueprint.pop("revealed", None)
    chat_messages = data.get("chat_messages", [])
    log(f"[Load] Game loaded: {username}/{name} ({game.player_name}, Scene {game.scene_count}, {len(chat_messages)} chat msgs)")
    return game, chat_messages


def list_saves(username: str) -> list[str]:
    save_dir = _get_save_dir(username)
    if not save_dir.exists():
        return []
    return sorted([p.stem for p in save_dir.glob("*.json")])


# Save-slot metadata cache: path → (mtime_ns, size, info). The sidebar lists every
# slot on each render; without the cache every full save file (chat history
# included, often several MB) was re-parsed each time — slow on a Raspberry Pi.
_SAVE_INFO_CACHE: dict[str, tuple[int, int, dict]] = {}
_SAVE_INFO_CACHE_LOCK = threading.Lock()


def get_save_info(username: str, name: str) -> dict | None:
    """Read save metadata without loading full game state.
    Returns dict with player_name, scene_count, saved_at, chapter_number or None.
    Results are cached per file and invalidated by mtime/size changes."""
    path = _get_save_dir(username) / f"{name}.json"
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    with _SAVE_INFO_CACHE_LOCK:
        cached = _SAVE_INFO_CACHE.get(key)
    if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return dict(cached[2])
    info = _read_save_info(path, name)
    if info.get("saved_at"):  # don't cache unreadable/partial files
        with _SAVE_INFO_CACHE_LOCK:
            _SAVE_INFO_CACHE[key] = (st.st_mtime_ns, st.st_size, info)
    return dict(info)


def _read_save_info(path: Path, name: str) -> dict:
    """Parse save metadata from disk (uncached helper for get_save_info)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "name": name,
            "player_name": data.get("player_name", "?"),
            "scene_count": data.get("scene_count", 0),
            "chapter_number": data.get("chapter_number", 1),
            "saved_at": data.get("saved_at", ""),
            "setting_genre": data.get("setting_genre", ""),
            "setting_tone": data.get("setting_tone", ""),
            "setting_archetype": data.get("setting_archetype", ""),
            "character_concept": data.get("character_concept", ""),
            "backstory": data.get("backstory", ""),
            "player_wishes": data.get("player_wishes", ""),
            "content_lines": data.get("content_lines", ""),
            "engine_version": data.get("engine_version", ""),
            "version_history": data.get("version_history", []),
        }
    except Exception:
        return {"name": name, "player_name": "?", "scene_count": 0,
                "chapter_number": 1, "saved_at": "", "setting_genre": "",
                "setting_tone": "", "setting_archetype": "",
                "character_concept": "", "backstory": "", "player_wishes": "",
                "content_lines": "",
                "engine_version": "", "version_history": []}


def list_saves_with_info(username: str) -> list[dict]:
    """List all saves with metadata, sorted by saved_at descending (newest first)."""
    saves = list_saves(username)
    infos = []
    for name in saves:
        info = get_save_info(username, name)
        if info:
            infos.append(info)
    # Sort: newest first
    infos.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
    return infos


def delete_save(username: str, name: str) -> bool:
    """Delete a save file and its chapter archives. Returns True if deleted, False if not found."""
    path = _get_save_dir(username) / f"{name}.json"
    if path.exists():
        path.unlink()
        delete_chapter_archives(username, name)
        log(f"[Save] Deleted: {username}/{name}")
        return True
    return False


# ===============================================================
# CHAPTER ARCHIVES (separate files per chapter for read-only replay)
# ===============================================================

def save_chapter_archive(username: str, save_name: str, chapter_number: int,
                         chat_messages: list, title: str = "") -> Path:
    """Archive chat messages for a completed chapter as a separate file."""
    chapter_dir = _get_save_dir(username) / "chapters" / save_name
    chapter_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "chapter": chapter_number,
        "title": title or f"Chapter {chapter_number}",
        "archived_at": datetime.now().isoformat(),
        "chat_messages": [
            {k: v for k, v in msg.items() if k not in ("audio_bytes", "audio_format")}
            for msg in chat_messages if not msg.get("recap")
        ],
    }
    path = chapter_dir / f"chapter_{chapter_number}.json"
    _atomic_write_text(path, json.dumps(data, **_SAVE_JSON_KW))
    log(f"[ChapterArchive] Saved ch{chapter_number} for {username}/{save_name} "
        f"({len(data['chat_messages'])} msgs, title={title!r})")
    return path


def load_chapter_archive(username: str, save_name: str, chapter_number: int) -> tuple[list, str]:
    """Load archived chat messages for a chapter. Returns (chat_messages, title)."""
    path = _get_save_dir(username) / "chapters" / save_name / f"chapter_{chapter_number}.json"
    if not path.exists():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("chat_messages", []), data.get("title", "")
    except (json.JSONDecodeError, OSError) as e:
        log(f"[ChapterArchive] Load failed ch{chapter_number}: {e}", level="warning")
        return [], ""


def list_chapter_archives(username: str, save_name: str) -> list[dict]:
    """List available chapter archives for a save. Returns [{"chapter": 1, "title": "..."}, ...]."""
    chapter_dir = _get_save_dir(username) / "chapters" / save_name
    if not chapter_dir.exists():
        return []
    archives = []
    for f in chapter_dir.iterdir():
        m = re.match(r"chapter_(\d+)\.json", f.name)
        if m:
            ch_num = int(m.group(1))
            title = ""
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                title = data.get("title", "")
            except (json.JSONDecodeError, OSError):
                pass
            archives.append({"chapter": ch_num, "title": title})
    archives.sort(key=lambda x: x["chapter"])
    return archives


def delete_chapter_archives(username: str, save_name: str):
    """Delete all chapter archives for a save slot."""
    chapter_dir = _get_save_dir(username) / "chapters" / save_name
    if chapter_dir.exists():
        import shutil
        shutil.rmtree(chapter_dir, ignore_errors=True)
        log(f"[ChapterArchive] Deleted archives: {username}/{save_name}")


def replace_chapter_archives(username: str, src_save: str, dst_save: str) -> None:
    """Make dst_save's chapter archives an exact copy of src_save's ("Save As").
    No-op when both names are the same: deleting first would wipe the very archives
    that are about to be copied."""
    if src_save == dst_save:
        return
    delete_chapter_archives(username, dst_save)
    copy_chapter_archives(username, src_save, dst_save)


def copy_chapter_archives(username: str, src_save: str, dst_save: str):
    """Copy all chapter archives from one save slot to another.
    Destination directory is created if it does not exist.
    If source does not exist, this is a no-op.
    """
    import shutil
    src_dir = _get_save_dir(username) / "chapters" / src_save
    dst_dir = _get_save_dir(username) / "chapters" / dst_save
    if not src_dir.exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in src_dir.iterdir():
        shutil.copy2(f, dst_dir / f.name)
    log(f"[ChapterArchive] Copied archives: {username}/{src_save} → {dst_save} "
        f"({len(list(src_dir.iterdir()))} file(s))")


# ===============================================================
# STORY EXPORT (PDF)
# ===============================================================

# --- PDF styling constants ---
_PDF_COLOR_DARK = HexColor("#1a1a2e")
_PDF_COLOR_ACCENT = HexColor("#6a4c93")
_PDF_COLOR_MUTED = HexColor("#666666")
_PDF_COLOR_RULE = HexColor("#cccccc")
_PDF_COLOR_ORNAMENT = HexColor("#999999")


def _pdf_styles():
    """Build paragraph styles for the story PDF."""
    base = getSampleStyleSheet()
    _add = base.add
    _add(ParagraphStyle("StoryTitle", fontName="Times-Bold", fontSize=24,
                        leading=30, alignment=TA_CENTER,
                        textColor=_PDF_COLOR_DARK, spaceAfter=6))
    _add(ParagraphStyle("StorySubtitle", fontName="Times-Italic", fontSize=13,
                        leading=18, alignment=TA_CENTER,
                        textColor=_PDF_COLOR_ACCENT, spaceAfter=4))
    _add(ParagraphStyle("StoryMeta", fontName="Times-Roman", fontSize=10,
                        leading=14, alignment=TA_CENTER,
                        textColor=_PDF_COLOR_MUTED, spaceAfter=20))
    _add(ParagraphStyle("SectionHeading", fontName="Times-Bold", fontSize=14,
                        leading=20, textColor=_PDF_COLOR_DARK,
                        spaceBefore=16, spaceAfter=8))
    _add(ParagraphStyle("CharInfo", fontName="Times-Roman", fontSize=11,
                        leading=16, textColor=_PDF_COLOR_DARK, spaceAfter=3))
    _add(ParagraphStyle("StoryBody", fontName="Times-Roman", fontSize=11,
                        leading=17, alignment=TA_JUSTIFY,
                        textColor=_PDF_COLOR_DARK, spaceAfter=12))
    _add(ParagraphStyle("Ornament", fontName="Times-Roman", fontSize=12,
                        leading=16, alignment=TA_CENTER,
                        textColor=_PDF_COLOR_ORNAMENT,
                        spaceBefore=6, spaceAfter=6))
    return base


def _pdf_escape(text: str) -> str:
    """Escape text for ReportLab XML paragraphs."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_page_footer(canvas, doc):
    """Draw footer on every page: branding left, page number right."""
    canvas.saveState()
    w = A4[0]
    canvas.setStrokeColor(_PDF_COLOR_RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 15 * mm, w - 20 * mm, 15 * mm)
    canvas.setFont("Times-Italic", 8)
    canvas.setFillColor(_PDF_COLOR_MUTED)
    canvas.drawString(20 * mm, 11 * mm, "Story experienced with EdgeTales")
    canvas.drawRightString(w - 20 * mm, 11 * mm, f"{doc.page}")
    canvas.restoreState()


def _clean_for_export(text: str) -> str:
    """Remove Markdown formatting and code blocks for export."""
    # Remove fenced code blocks (```json ... ``` etc.)
    text = re.sub(r'```[\w]*\s*\n?[\s\S]*?```', '', text)
    # Remove inline code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remove bold/italic markers
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # Remove markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def export_story_pdf(game: GameState, messages: list, lang: str = "de") -> bytes:
    """Build a PDF export of the story. Returns PDF bytes.

    Content: title page with character info, then AI narrations only
    (after first scene marker, skips creation flow / recaps / system messages).
    Every page has a footer: "Story experienced with EdgeTales" + page number.
    """
    esc = _pdf_escape
    styles = _pdf_styles()
    buf = io.BytesIO()

    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=20 * mm, bottomMargin=22 * mm)
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="story", frames=frame,
                                       onPage=_pdf_page_footer)])

    elements: list = []
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

    # ── Title page ──────────────────────────────────────────
    elements.append(Spacer(1, 30 * mm))
    elements.append(Paragraph(esc(game.player_name), styles["StoryTitle"]))
    elements.append(Paragraph(esc(_t("export.subtitle", lang)),
                              styles["StorySubtitle"]))
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph("\u2014\u2014\u2014  \u2022  \u2014\u2014\u2014",
                              styles["Ornament"]))
    elements.append(Spacer(1, 6 * mm))

    if game.character_concept:
        elements.append(Paragraph(
            esc(_clean_for_export(game.character_concept)), styles["CharInfo"]))
        elements.append(Spacer(1, 3 * mm))
    if game.setting_description:
        elements.append(Paragraph(
            esc(_clean_for_export(game.setting_description)), styles["CharInfo"]))
        elements.append(Spacer(1, 3 * mm))
    if game.current_location:
        loc = _t("export.location", lang)
        elements.append(Paragraph(
            f"<b>{esc(loc)}:</b> {esc(game.current_location)}",
            styles["CharInfo"]))

    attr = _t("export.attributes", lang,
              edge=game.edge, heart=game.heart, iron=game.iron,
              shadow=game.shadow, wits=game.wits)
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(esc(attr), styles["CharInfo"]))

    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph(
        esc(_t("export.exported_at", lang, timestamp=timestamp)),
        styles["StoryMeta"]))

    # ── Story pages ─────────────────────────────────────────
    elements.append(PageBreak())
    elements.append(Paragraph(esc(_t("export.story", lang)),
                              styles["SectionHeading"]))
    elements.append(HRFlowable(width="100%", thickness=0.5,
                               color=_PDF_COLOR_RULE,
                               spaceBefore=2, spaceAfter=12))

    _skip_pfx = ("*Spielstand geladen", "*Spiel", "*Game loaded", "*Game ")
    _skip_has = ("Spielstand geladen", "Game loaded")

    scene_num = 0
    story_started = False
    content_written = False
    for msg in messages:
        if msg.get("scene_marker"):
            story_started = True
            scene_num += 1
            if scene_num > 1:
                elements.append(Spacer(1, 3 * mm))
                elements.append(Paragraph("\u2022  \u2022  \u2022",
                                          styles["Ornament"]))
                elements.append(Spacer(1, 1 * mm))
            continue
        if not story_started:
            continue
        if msg.get("role") != "assistant":
            continue
        if msg.get("recap"):
            continue
        content = msg.get("content", "")
        if any(content.startswith(p) for p in _skip_pfx) \
                or any(s in content[:80] for s in _skip_has):
            continue
        clean = _clean_for_export(content)
        if not clean:
            continue
        for para in clean.split("\n\n"):
            para = para.strip()
            if para:
                elements.append(Paragraph(esc(para), styles["StoryBody"]))
                content_written = True

    # No narration found — save was created without message history (e.g. test bot).
    if not content_written:
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph(
            esc(_t("export.no_content", lang)), styles["StoryMeta"]))

    # ── End ─────────────────────────────────────────────────
    elements.append(Spacer(1, 8 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5,
                               color=_PDF_COLOR_RULE,
                               spaceBefore=8, spaceAfter=8))
    footer = _t("export.footer", lang, scenes=game.scene_count)
    elements.append(Paragraph(esc(footer), styles["StoryMeta"]))

    doc.build(elements)
    return buf.getvalue()


# ===============================================================
# GAME LOOP
# ===============================================================

def start_new_game(client: anthropic.Anthropic, creation_data: dict,
                   config: Optional[EngineConfig] = None,
                   username: str = "") -> tuple[GameState, str]:
    """Create character from guided creation data, generate opening scene."""
    log(f"[NewGame] Starting new game: genre={creation_data.get('genre')}, tone={creation_data.get('tone')}")
    # Use pre-generated setup from confirm screen if available (avoids regeneration bug)
    if "setup" in creation_data:
        setup = creation_data["setup"]
        log("[NewGame] Using pre-generated setup from confirm screen")
    else:
        setup = call_setup_brain(client, creation_data, config)
    stats = setup.get("stats", {"edge":1,"heart":2,"iron":1,"shadow":1,"wits":2})

    genre = creation_data.get("genre", "dark_fantasy")
    if genre == "custom" and creation_data.get("genre_description"):
        genre = creation_data["genre_description"]

    tone = creation_data.get("tone", "dark_gritty")
    if tone == "custom" and creation_data.get("tone_description"):
        tone = creation_data["tone_description"]

    archetype = creation_data.get("archetype", "")

    game = GameState(
        player_name=setup.get("character_name", "Namenlos"),
        character_concept=setup.get("character_concept", ""),
        setting_genre=genre,
        setting_tone=tone,
        setting_archetype=archetype,
        setting_description=setup.get("setting_description", ""),
        edge=stats.get("edge", 1), heart=stats.get("heart", 2),
        iron=stats.get("iron", 1), shadow=stats.get("shadow", 1),
        wits=stats.get("wits", 2),
        health=5, spirit=5, supply=5, momentum=2,
        scene_count=1,
        current_location=setup.get("starting_location", "Unbekannter Ort"),
        current_scene_context=setup.get("opening_situation", ""),
        chaos_factor=5,
        scene_intensity_history=[],
        player_wishes=creation_data.get("wishes", ""),
        content_lines=creation_data.get("content_lines", ""),
        backstory=creation_data.get("backstory", "") or creation_data.get("custom_desc", ""),
    )
    log(f"[NewGame] Character created: {game.player_name} at {game.current_location}")

    # Persist content_lines to user config (auto-fill for next game)
    if username:
        cfg = load_user_config(username)
        cfg["content_lines"] = game.content_lines
        save_user_config(username, cfg)

    # Choose story structure based on tone probability (needed before parallel calls)
    structure = choose_story_structure(tone)

    # Prepare narrator prompt before launching parallel calls
    narrator_prompt = build_new_game_prompt(game)

    # --- Parallel execution: Narrator + Story Architect simultaneously ---
    # The Story Architect uses genre/tone/setting/character from the GameState,
    # which is fully populated from setup brain. It only gets "none yet" for NPCs
    # (populated after narrator parse), but the blueprint is about story arcs and
    # conflict structure — NPC names don't influence its quality.
    from concurrent.futures import ThreadPoolExecutor

    def _run_narrator():
        return call_narrator(client, narrator_prompt, game, config)

    def _run_architect():
        return call_story_architect(client, game, structure_type=structure, config=config)

    raw = None
    blueprint = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_narrator = pool.submit(_run_narrator)
        fut_architect = pool.submit(_run_architect)
        # Wait for both — exceptions are re-raised on .result()
        raw = fut_narrator.result()
        blueprint = fut_architect.result()

    narration = parse_narrator_response(game, raw)
    game.story_blueprint = blueprint

    # Extract NPCs, clocks, location, scene_context via Structured Outputs.
    # Replaces the old inline <game_data> approach — narrator now writes pure prose.
    opening_data = call_opening_metadata(client, narration, game, config)
    _process_game_data(game, opening_data)

    # Guard: call_opening_metadata swallows all exceptions and returns an empty
    # fallback dict — game.npcs being empty here means the call silently failed.
    # Retry once so a transient API error doesn't produce an NPC-less session.
    if not game.npcs:
        log("[NewGame] WARNING: call_opening_metadata returned 0 NPCs — retrying",
            level="warning")
        opening_data = call_opening_metadata(client, narration, game, config)
        _process_game_data(game, opening_data)
        if not game.npcs:
            log("[NewGame] ERROR: call_opening_metadata retry yielded 0 NPCs — "
                "session will proceed without NPC system data", level="error")

    # Opening-scene NPCs are extracted FROM the narration — they are introduced
    # by definition. _process_game_data defaults to introduced=False (legacy),
    # but parse_narrator_response step 10 can't check them because game.npcs
    # was empty when it ran. Mark them now so the sidebar shows them immediately.
    for npc in game.npcs:
        npc["introduced"] = True

    # Deceased NPCs in the opening scene (e.g. someone killed right in front of
    # the player as a dramatic opener). NPCs are extracted first (with full
    # agenda/instinct/secrets) so the data is preserved even after marking deceased.
    # No scene_present_ids guard needed — everything in the opening is witnessed.
    opening_deceased = opening_data.get("deceased_npcs", [])
    if opening_deceased:
        _process_deceased_npcs(game, opening_deceased)

    # Record opening as neutral intensity
    record_scene_intensity(game, "action")

    # Store in narration history for context continuity
    game.narration_history.append({
        "scene": game.scene_count,
        "prompt_summary": f"Opening scene: {game.player_name} in {game.current_location}",
        "narration": narration,
    })
    game.session_log.append({"scene": 1, "summary": "Game start", "result": "opening",
                             "consequences": [], "clock_events": [],
                             "dramatic_question": "", "chaos_interrupt": None})
    # Note: UI layer handles save_game()
    return game, narration


def _campaign_history_block(game: GameState) -> str:
    """Build campaign history context for prompts."""
    if not game.campaign_history:
        return ""
    parts = [f'<campaign_history chapters="{len(game.campaign_history)}">']
    for ch in game.campaign_history[-3:]:  # Last 3 chapters for context
        parts.append(f'  <chapter n="{ch.get("chapter", "?")}" title="{_xa(ch.get("title", ""))}">'
                     f'{html.escape(ch.get("summary", ""))}</chapter>')
    parts.append('</campaign_history>')
    return "\n".join(parts)


def call_chapter_summary(client: anthropic.Anthropic, game: GameState,
                          config: Optional[EngineConfig] = None,
                          epilogue_text: str = "") -> dict:
    """Generate a summary of the completed chapter for campaign history."""
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    log_text = "; ".join(
        f'S{s["scene"]}:{s["summary"]}({s["result"]})'
        for s in game.session_log[-20:]
    )
    npc_text = ", ".join(
        f'{n["name"]}({n["disposition"]},B{n["bond"]})'
        for n in game.npcs if n.get("status") == "active"
    ) or "(none)"

    bp = game.story_blueprint or {}
    conflict = bp.get("central_conflict", "")

    # If an epilogue was generated, include it as the definitive story ending.
    # This ensures the chapter summary reflects what actually happened (post-mission,
    # post-resolution) rather than the mid-action state captured in session_log/context.
    epilogue_block = (f"\n<epilogue>This is how the story ended — treat it as the "
                      f"authoritative final state when summarizing:\n{html.escape(epilogue_text)}\n</epilogue>"
                      if epilogue_text.strip() else "")

    epilogue_location_hint = (
        "- \"post_story_location\": Where the protagonist physically is at the END of the epilogue "
        "(e.g. their home city in 2026, a tavern, a ship at sea). Extract this from the epilogue text. "
        "If no epilogue is provided, infer the most plausible location after the story's conclusion."
        if epilogue_text.strip() else
        "- \"post_story_location\": Where the protagonist most plausibly ends up after the story's conclusion. "
        "Infer from the session log and situation."
    )

    try:
        response = _api_create_with_retry(
            client, max_retries=1,
            model=BRAIN_MODEL, max_tokens=CHAPTER_SUM_MAX_TOKENS,
            system=f"""Summarize an RPG chapter for campaign continuity.
- Write in {lang}
- "title": A short evocative title for this chapter (3-6 words)
- "summary": 3-4 sentences capturing key events, character growth, and how the chapter ended. If an <epilogue> is provided, make sure the summary reflects the story's actual conclusion, not the mid-action state.
- "unresolved_threads": List of 1-3 open plot threads or tensions that could carry into the next chapter. If an <epilogue> is provided, base these on what was left unresolved AFTER the epilogue — not on in-progress mission steps.
- "character_growth": 1 sentence on how the protagonist changed
- "npc_evolutions": For each important NPC, project how they might have changed after the chapter's events. This is a PROJECTION for the time skip between chapters — not what happened, but what COULD plausibly have happened in the weeks/months after. Focus on relationship shifts, attitude changes, new circumstances. Only include NPCs who were meaningfully involved in the chapter.
- "thematic_question": The core emotional/philosophical question this chapter raised but did not fully answer. This carries the vertical (emotional) narrative across chapters. Example: "Can you fix the damage caused by good intentions?" or "Is loyalty earned through competence or compassion?"
{epilogue_location_hint}
""" + _kid_friendly_block(_cfg) + _content_boundaries_block(game),
            messages=[{"role": "user", "content":
                       f"character:{game.player_name} {E['dash']} {game.character_concept}\n"
                       f"genre:{game.setting_genre} tone:{game.setting_tone}\n"
                       f"world:{game.setting_description}\n"
                       f"conflict:{conflict}\n"
                       f"log:{log_text}\nnpcs:{npc_text}\n"
                       f"location:{game.current_location}\n"
                       f"situation:{game.current_scene_context}"
                       f"{epilogue_block}"}],
            output_config={"format": {"type": "json_schema", "schema": CHAPTER_SUMMARY_OUTPUT_SCHEMA}},
        )
        data = json.loads(_response_text(response))
        data["chapter"] = game.chapter_number
        data["scenes"] = game.scene_count
        return data
    except Exception as e:
        log(f"[ChapterSummary] Structured output failed ({type(e).__name__}: {e}), "
            f"using fallback", level="warning")
        return {
            "chapter": game.chapter_number,
            "title": f"Chapter {game.chapter_number}",
            "summary": f"{game.player_name} had an adventure in {game.current_location}.",
            "unresolved_threads": [],
            "character_growth": "",
            "npc_evolutions": [],
            "thematic_question": "",
            "post_story_location": game.current_location,
            "scenes": game.scene_count,
        }


def build_epilogue_prompt(game: GameState) -> str:
    """Build prompt for generating an epilogue that wraps up the story."""
    campaign = _campaign_history_block(game)
    bp = game.story_blueprint or {}
    endings = bp.get("possible_endings", [])
    endings_text = ", ".join(
        f'{e["type"]}: {e.get("description", "")}'
        for e in endings
    ) if endings else "open"
    conflict = bp.get("central_conflict", "")

    npc_block = "\n".join(
        f'<npc name="{_xa(n["name"])}" disposition="{n["disposition"]}" bond="{n["bond"]}/{n.get("bond_max",4)}">'
        f'{html.escape(n.get("description",""))}</npc>'
        for n in game.npcs if n.get("status") == "active"
    )

    log_text = "; ".join(
        f'S{s["scene"]}:{s.get("rich_summary") or s["summary"]}({s["result"]})'
        for s in game.session_log[-15:]
    )

    return f"""<scene type="epilogue">
{_scene_header(game)}
<location>{html.escape(game.current_location)}</location>
<situation>{html.escape(game.current_scene_context)}</situation>
<conflict>{html.escape(conflict)}</conflict>
<possible_endings>{html.escape(endings_text)}</possible_endings>
{npc_block}
{campaign}
<session_log>{html.escape(log_text)}</session_log>
</scene>
<task>
Write a beautiful EPILOGUE for this story (4-6 paragraphs). This is NOT a new scene — no dice, no mechanics.
- PERSPECTIVE: Second person singular ("you") throughout — the player remains the protagonist. Do NOT shift to third person.
- Reflect on the character's journey and growth
- Give closure to the most important NPC relationships (reference them by name)
- Resolve or acknowledge the central conflict based on what actually happened
- Match the tone of the story — if it was dark, the ending can be bittersweet; if hopeful, it can be warm
- End with a final image or moment that captures the essence of this adventure
- Do NOT introduce new conflicts or cliffhangers — this is closure
- No metadata blocks, no game_data, no memory_updates — pure narrative prose only
</task>"""


def generate_epilogue(client: anthropic.Anthropic, game: GameState,
                      config: Optional[EngineConfig] = None) -> tuple[GameState, str]:
    """Generate an epilogue for the completed story. Returns (game, epilogue_text)."""
    log(f"[Epilogue] Generating epilogue for {game.player_name} (chapter {game.chapter_number}, scene {game.scene_count})")

    raw = call_narrator(client, build_epilogue_prompt(game), game, config)

    # Clean the response — strip any metadata that might leak through
    narration = raw
    # Remove known metadata XML tags (paired)
    narration = re.sub(r'<(?:game_data|new_npcs|memory_updates|scene_context)>.*?</(?:game_data|new_npcs|memory_updates|scene_context)>', '', narration, flags=re.DOTALL)
    # Remove known self-closing/unpaired metadata tags only (not ALL XML — narrator
    # may use tags like <sigh> or <emphasis> as stylistic prose elements)
    narration = re.sub(r'</?(?:game_data|new_npcs|memory_updates|scene_context|task|scene|world|character|situation|conflict|possible_endings|session_log|npc|returning_npc|campaign_history|chapter|story_arc|story_ending|momentum_burn)[^>]*>', '', narration)
    # Remove lines that start with [ or { (trailing JSON metadata)
    # Use MULTILINE so each line is checked independently (DOTALL would eat everything)
    narration = re.sub(r'^\s*[\[{].*$', '', narration, flags=re.MULTILINE)
    # Strip redundant "Epilog/Epilogue" heading the narrator likes to add
    # (the scene marker already labels this section visually)
    narration = re.sub(
        r'^\s*#*\s*\*{0,3}\s*(?:Epilog(?:ue)?|Épilogue|Epílogo|Epilogo)\s*\*{0,3}\s*\n+',
        '', narration, count=1, flags=re.IGNORECASE
    )
    narration = narration.strip()

    narration = re.sub(r'\s*[—–]\s*', ' - ', narration)

    if not narration:
        narration = "(The narrator pauses, then offers a quiet reflection on the journey...)"

    game.epilogue_shown = True
    game.epilogue_text = narration  # Persisted in SAVE_FIELDS — consumed and cleared by start_new_chapter()
    log(f"[Epilogue] Generated ({len(narration)} chars)")
    return game, narration


def build_new_chapter_prompt(game: GameState) -> str:
    """Build opening prompt for a new chapter in an ongoing campaign."""
    campaign = _campaign_history_block(game)
    npc_block = "\n".join(
        f'<returning_npc id="{n["id"]}" name="{_xa(n["name"])}" disposition="{n["disposition"]}" '
        f'bond="{n["bond"]}/{n.get("bond_max",4)}"'
        + (f' aliases="{_xa(",".join(n["aliases"]))}"' if n.get("aliases") else '')
        + f'>{html.escape(n.get("description",""))}</returning_npc>'
        for n in game.npcs if n.get("status") == "active"
    )
    bg_npcs = [n for n in game.npcs if n.get("status") == "background"]
    if bg_npcs:
        bg_parts = []
        for n in bg_npcs:
            entry = html.escape(n["name"]) + f'({n["disposition"]})'
            if n.get("aliases"):
                entry += f'[aka {html.escape(",".join(n["aliases"]))}]'
            bg_parts.append(entry)
        bg_names = ", ".join(bg_parts)
        npc_block += f'\n<background_npcs>Known but not recently active: {bg_names}</background_npcs>'
    lore_npcs_ch = [n for n in game.npcs if n.get("status") == "lore"]
    if lore_npcs_ch:
        lore_parts = []
        for n in lore_npcs_ch:
            entry = html.escape(n["name"])
            if n.get("description"):
                entry += f': {html.escape(n["description"][:60])}'
            lore_parts.append(entry)
        npc_block += f'\n<lore_figures>{"; ".join(lore_parts)}</lore_figures>'

    # NPC evolutions from the most recent chapter summary (time skip hints)
    evolutions_block = ""
    if game.campaign_history:
        last_ch = game.campaign_history[-1]
        evolutions = last_ch.get("npc_evolutions", [])
        if evolutions:
            evo_lines = "\n".join(
                f'  {html.escape(e["name"])}: {html.escape(e["projection"])}'
                for e in evolutions if e.get("name") and e.get("projection")
            )
            evolutions_block = f'\n<npc_evolutions hint="These are PROJECTIONS of how NPCs may have changed during the time skip. Use as inspiration, not as hard facts.">\n{evo_lines}\n</npc_evolutions>'

    story = _story_context_block(game)
    seed = _creativity_seed()
    log(f"[Narrator] Chapter {game.chapter_number} opening creativity_seed={seed!r}")

    return f"""<scene type="chapter_opening" chapter="{game.chapter_number}">
{_scene_header(game)}
<location>{html.escape(game.current_location)}</location>{_time_ctx(game)}
<situation>{html.escape(game.current_scene_context)}</situation>
{campaign}
{npc_block}{evolutions_block}
{_status_context_block(game)}{story}</scene>
<task>
Chapter {game.chapter_number} opening: 3-4 paragraphs. This is a NEW chapter in an ongoing campaign.
- Reference the character's history and relationships naturally (don't recap everything, just hint)
- Some time has passed since last chapter. Show how the world/relationships evolved
- Use <npc_evolutions> as hints for how NPCs may have changed — show their evolution through behavior, dialog, and atmosphere rather than exposition
- Introduce a NEW tension or situation that builds on unresolved threads
- Returning NPCs should feel familiar but may have changed
- Introduce 1-2 NEW NPCs alongside returning characters
- Create one new threat clock for this chapter
IMPORTANT: The <character> above is the PLAYER CHARACTER. Do NOT include them as an NPC.
creativity_seed: {seed} (Use as loose inspiration for NPC names, locations, and scene details — not literally, but as creative anchors to avoid generic defaults)
</task>"""


def start_new_chapter(client: anthropic.Anthropic, game: GameState,
                      config: Optional[EngineConfig] = None,
                      username: str = "") -> tuple[GameState, str]:
    """Transactional wrapper — see _start_new_chapter_impl(). On any exception the
    GameState is rolled back to its state at call time (_rollback_on_error)."""
    with _rollback_on_error(game, "Chapter"):
        return _start_new_chapter_impl(client=client, game=game, config=config, username=username)


def _absorb_returning_npc(target: dict, old: dict) -> None:
    """Move a returning NPC's history into the NPC the chapter-opening extractor
    created for the same person (matched by name or alias). The extractor entry
    keeps its new-chapter ID, fresh description, disposition and secrets; the
    returning NPC contributes memories, bond, reflection rhythm, its locked
    instinct, arc, agenda (if the extractor gave none) and aliases."""
    old_mem = [m for m in old.get("memory", []) if isinstance(m, dict)]
    if old_mem:
        target["memory"] = old_mem + [m for m in target.get("memory", []) if m not in old_mem]
    target["bond"] = max(target.get("bond", 0), old.get("bond", 0))
    target["importance_accumulator"] = (target.get("importance_accumulator", 0)
                                        + old.get("importance_accumulator", 0))
    target["last_reflection_scene"] = max(target.get("last_reflection_scene", 0),
                                          old.get("last_reflection_scene", 0))
    if old.get("instinct"):                      # instinct is locked once set
        target["instinct"] = old["instinct"]
    if old.get("arc") and not target.get("arc"):
        target["arc"] = old["arc"]
    if old.get("agenda") and not target.get("agenda"):
        target["agenda"] = old["agenda"]
    if not target.get("secrets") and old.get("secrets"):
        target["secrets"] = old["secrets"]
    target.setdefault("aliases", [])
    existing = {_normalize_for_match(a) for a in target["aliases"]}
    canonical = _normalize_for_match(target["name"])
    for alias in old.get("aliases", []):
        a_norm = _normalize_for_match(alias)
        if a_norm not in existing and a_norm != canonical:
            target["aliases"].append(alias)
            existing.add(a_norm)
    target["introduced"] = True
    _consolidate_memory(target)


def _start_new_chapter_impl(client: anthropic.Anthropic, game: GameState,
                      config: Optional[EngineConfig] = None,
                      username: str = "") -> tuple[GameState, str]:
    """Start a new chapter: keep character/world/NPCs, reset mechanics, new story arc."""
    log(f"[Campaign] Starting chapter {game.chapter_number + 1} for {game.player_name}")

    # Generate chapter summary before resetting.
    # Pass the epilogue text (if generated) so the summary reflects the story's
    # actual conclusion — not the mid-action state in session_log/current_scene_context.
    epilogue_text = getattr(game, "epilogue_text", "")
    chapter_summary = call_chapter_summary(client, game, config, epilogue_text=epilogue_text)
    game.campaign_history.append(chapter_summary)
    # Clear epilogue_text now that it has been consumed — prevents it from
    # bleeding into the chapter-3 summary if the player starts yet another chapter.
    game.epilogue_text = ""

    # Advance chapter
    game.chapter_number += 1

    # Reset mechanics
    game.health = 5
    game.spirit = 5
    game.supply = 5
    game.momentum = 2
    game.scene_count = 1
    game.chaos_factor = 5
    game.crisis_mode = False
    game.game_over = False
    game.epilogue_shown = False
    game.epilogue_dismissed = False
    game.clocks = []
    game.session_log = []
    game.narration_history = []
    game.scene_intensity_history = []
    game.story_blueprint = {}  # Cleared; new blueprint generated after opening scene
    game.time_of_day = ""      # Reset -- new chapter, new time context
    game.time_unchanged_scenes = 0
    game.location_history = []  # Reset -- new chapter, fresh location tracking
    game.scenes_at_location = 0
    game.director_guidance = {}  # Reset -- old pacing/guidance shouldn't carry over

    # Reset exit-suppression flags: scene_count resets to 1 at chapter start, so any
    # absent_until_scene value from the previous chapter (e.g. 21) would be > 1..20
    # throughout the entire new chapter — permanently suppressing NPCs. Clear all flags.
    for npc in game.npcs:
        npc["absent_until_scene"] = 0

    # Retire dead or irrelevant NPCs to background before new chapter
    for npc in game.npcs:
        # Deceased NPCs stay deceased — skip them entirely
        if npc.get("status") == "deceased":
            continue
        if npc.get("status") != "active":
            continue
        # Low-engagement NPCs: no bond, minimal memories, no agenda (filler NPCs)
        is_filler = (npc.get("bond", 0) == 0
                     and len(npc.get("memory", [])) <= 1
                     and not npc.get("agenda", "").strip())
        if is_filler:
            npc["status"] = "background"
            log(f"[Campaign] Retired NPC to background at chapter boundary: "
                f"{npc['name']} (low-engagement filler)")

    # Keep NPCs but consolidate memories (keep significant ones across chapters)
    for npc in game.npcs:
        if npc.get("memory") and len(npc["memory"]) > 5:
            # Keep the 5 most impactful memories (by importance score, then recency)
            scored = sorted(
                npc["memory"],
                key=lambda m: (m.get("importance", score_importance(m.get("emotional_weight", "neutral"), m.get("event", ""))),
                               m.get("scene") or 0),
                reverse=True
            )
            npc["memory"] = sorted(scored[:5], key=lambda m: m.get("scene", 0) or 0)
        # Run full consolidation to ensure memory limits are respected
        _consolidate_memory(npc)

    # Rebase scene-relative NPC fields: scene_count restarts at 1, so carried-over
    # memories with chapter-N scene numbers would otherwise collide with new-chapter
    # scenes (burn memory purge and death corroboration filter by scene == current),
    # get a permanent recency of 1.0 (negative gap clamped to 0), and block staleness
    # retirement. Scene 0 = "before this chapter" (same convention as seed memories).
    for npc in game.npcs:
        for m in npc.get("memory", []):
            if isinstance(m, dict):
                m["scene"] = 0
        npc["last_memory_scene"] = 0
        npc["last_reflection_scene"] = 0

    # A ## correction must never roll back into the previous chapter's last turn.
    game.last_turn_snapshot = None

    # Update situation context for new chapter
    threads = chapter_summary.get("unresolved_threads", [])
    if threads:
        game.current_scene_context = f"New chapter. Open threads: {'; '.join(threads[:3])}"
    else:
        game.current_scene_context = "A new chapter begins."

    # Update location to where the protagonist actually ended up (from epilogue or inference).
    # This prevents the new chapter opening from anchoring to a mid-action location.
    post_location = chapter_summary.get("post_story_location", "").strip()
    if post_location:
        post_location = _short_location_name(post_location)
        log(f"[Campaign] Location updated to post-story position: {post_location!r}")
        game.current_location = post_location

    # Save returning NPCs before extraction replaces them (active + background + deceased)
    returning_npcs = [dict(n) for n in game.npcs
                      if n.get("status") in ("active", "background", "deceased", "lore")]

    # Choose story structure for new chapter (needed before parallel calls)
    structure = choose_story_structure(game.setting_tone)

    # Prepare narrator prompt before parallel calls
    chapter_prompt = build_new_chapter_prompt(game)

    # --- Parallel execution: Narrator + Story Architect simultaneously ---
    # The architect gets the pre-parse state (returning NPCs, current context),
    # which is actually ideal for campaign continuity. The blueprint is about
    # story arcs, not NPC details.
    # We use copy.copy(game) so parse_narrator_response's mutations don't race
    # with the architect's reads.
    from concurrent.futures import ThreadPoolExecutor

    architect_game = copy.copy(game)  # Shallow copy — frozen view for architect

    def _run_narrator():
        return call_narrator(client, chapter_prompt, game, config)

    def _run_architect():
        return call_story_architect(client, architect_game, structure_type=structure, config=config)

    raw = None
    blueprint = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_narrator = pool.submit(_run_narrator)
        fut_architect = pool.submit(_run_architect)
        raw = fut_narrator.result()
        blueprint = fut_architect.result()

    narration = parse_narrator_response(game, raw)
    game.story_blueprint = blueprint

    # Extract NEW NPCs, clocks, location, scene_context via Structured Outputs.
    # Pass returning NPCs as known_npcs so extractor only creates genuinely new entries.
    opening_data = call_opening_metadata(client, narration, game, config,
                                         known_npcs=returning_npcs)

    # Process new NPCs: clear game.npcs, let _process_game_data assign IDs and
    # defaults, then merge returning NPCs back.
    game.npcs = []
    _process_game_data(game, opening_data)

    # Guard: if scene_context is still the placeholder text the call silently failed.
    # We cannot use `if not game.current_scene_context:` here — the placeholder set
    # above ("New chapter. Open threads:..." / "A new chapter begins.") is already
    # non-empty, so a silently-failing call leaves it unchanged rather than empty.
    # Solution: capture the placeholder before _process_game_data and compare after.
    _chapter_ctx_placeholder = (
        f"New chapter. Open threads: {'; '.join(threads[:3])}" if threads
        else "A new chapter begins."
    )
    if game.current_scene_context == _chapter_ctx_placeholder:
        log("[Chapter] WARNING: call_opening_metadata returned no scene_context — retrying",
            level="warning")
        opening_data = call_opening_metadata(client, narration, game, config,
                                             known_npcs=returning_npcs)
        game.npcs = []
        _process_game_data(game, opening_data)
        if game.current_scene_context == _chapter_ctx_placeholder:
            log("[Chapter] ERROR: call_opening_metadata retry yielded no scene_context — "
                "chapter will proceed with incomplete metadata", level="error")

    # Chapter-opening NPCs extracted from narration are introduced by definition
    for npc in game.npcs:
        npc["introduced"] = True

    # Merge: re-add returning NPCs that weren't re-introduced by the extractor.
    # NOTE: Do NOT check by old ID here. _process_game_data() just reassigned IDs
    # starting from npc_1 into the now-empty game.npcs, so old IDs from previous
    # chapter will collide with freshly assigned ones (e.g. old Birte = npc_1 vs
    # new "stranger" = npc_1). Name-based dedup is the only correct check.
    new_npc_names = {_normalize_for_match(n["name"]) for n in game.npcs}
    id_remap = {}  # old_id → new_id; needed to fix about_npc references below
    for old_npc in returning_npcs:
        # Extractor re-created this NPC under the same name: keep ONE entry (the
        # extractor's, it carries the new chapter's ID) and move the returning NPC's
        # history into it. Previously the returning NPC was simply dropped — its
        # memories, bond, instinct and arc were lost and about_npc refs went stale.
        if _normalize_for_match(old_npc["name"]) in new_npc_names:
            same = next((n for n in game.npcs
                         if _normalize_for_match(n["name"]) == _normalize_for_match(old_npc["name"])),
                        None)
            if same is not None and same is not old_npc:
                _absorb_returning_npc(same, old_npc)
                id_remap[old_npc["id"]] = same["id"]
                log(f"[Campaign] Returning NPC '{old_npc['name']}' re-extracted by name — "
                    f"history merged into {same['id']}")
            continue

        # Alias-based dedup: the extractor may have introduced the returning NPC
        # under one of its aliases (e.g. returning NPC is "Ein erschöpfter Reiter"
        # with alias "Dragoner Fink", but extractor created a hollow "Dragoner Fink").
        # In that case we merge the returning NPC's history into the hollow one
        # rather than adding a duplicate.
        old_npc_norm = _normalize_for_match(old_npc["name"])
        old_aliases_norm = {
            _normalize_for_match(a) for a in old_npc.get("aliases", [])
            if len(a.strip()) >= 4  # skip 1-3 char noise entries (e.g. "ok", "er")
        }
        alias_hit = None
        for extractor_npc in game.npcs:
            ext_name_norm = _normalize_for_match(extractor_npc["name"])
            ext_aliases_norm = {_normalize_for_match(a) for a in extractor_npc.get("aliases", [])}
            # Match in either direction: returning alias == extractor name, OR
            # returning name == extractor alias
            if ext_name_norm in old_aliases_norm or old_npc_norm in ext_aliases_norm:
                alias_hit = extractor_npc
                break

        if alias_hit:
            # Rename hollow extractor NPC to the canonical returning name;
            # extractor name becomes an alias automatically.
            old_id = old_npc["id"]
            _merge_npc_identity(alias_hit, old_npc["name"], game=game)
            _absorb_returning_npc(alias_hit, old_npc)
            # Register id_remap so about_npc references get rewritten below
            id_remap[old_id] = alias_hit["id"]
            new_npc_names.add(_normalize_for_match(old_npc["name"]))
            log(f"[Campaign] Alias-merged returning NPC '{old_npc['name']}' ({old_id}) "
                f"into extractor NPC now named '{alias_hit['name']}' ({alias_hit['id']})")
            continue

        # Assign a fresh ID to avoid collisions with extractor-assigned IDs
        old_id = old_npc["id"]
        fresh_id, _ = _next_npc_id(game)
        id_remap[old_id] = fresh_id
        old_npc["id"] = fresh_id
        old_npc["introduced"] = True  # Player knows them from previous chapter
        game.npcs.append(old_npc)
        new_npc_names.add(_normalize_for_match(old_npc["name"]))

    # Fix stale about_npc references across all NPC memories.
    # Returning NPCs carry memories from the previous chapter whose about_npc values
    # reference old IDs. After the ID reassignment above those IDs no longer exist
    # (or worse, point to different NPCs), breaking the NPC-to-NPC memory relevance
    # boost in retrieve_memories(). Rewrite every stale reference in one pass.
    if id_remap:
        for npc in game.npcs:
            for mem in npc.get("memory", []):
                old_about = mem.get("about_npc")
                if old_about and old_about in id_remap:
                    mem["about_npc"] = id_remap[old_about]

    # Seed location_history with the new chapter's starting location
    if game.current_location and not game.location_history:
        game.location_history.append(game.current_location)

    # Deceased NPCs in the chapter opening. Processed after the merge loop so
    # returning NPCs are already in game.npcs and reachable by name.
    # No scene_present_ids guard — everything in the opening is witnessed.
    opening_deceased = opening_data.get("deceased_npcs", [])
    if opening_deceased:
        _process_deceased_npcs(game, opening_deceased)

    # Record opening
    record_scene_intensity(game, "action")
    game.narration_history.append({
        "scene": game.scene_count,
        "prompt_summary": f"Chapter {game.chapter_number} opening: {game.player_name} in {game.current_location}",
        "narration": narration,
    })
    game.session_log.append({"scene": 1, "summary": f"Chapter {game.chapter_number} begins",
                             "result": "opening", "consequences": [], "clock_events": [],
                             "dramatic_question": "", "chaos_interrupt": None})

    # Persist content_lines to user config (auto-fill for next game)
    if username and game.content_lines:
        cfg = load_user_config(username)
        cfg["content_lines"] = game.content_lines
        save_user_config(username, cfg)

    # Note: UI layer handles save_game()
    return game, narration


def process_turn(client: anthropic.Anthropic, game: GameState,
                 player_message: str,
                 config: Optional[EngineConfig] = None) -> tuple[GameState, str, Optional[RollResult], Optional[dict], Optional[dict]]:
    """Transactional wrapper — see _process_turn_impl(). On any exception the
    GameState is rolled back to its state at call time (_rollback_on_error)."""
    with _rollback_on_error(game, "Turn"):
        result = _process_turn_impl(client=client, game=game, player_message=player_message, config=config)
        _coop_end_turn(game)
        return result


def _process_turn_impl(client: anthropic.Anthropic, game: GameState,
                 player_message: str,
                 config: Optional[EngineConfig] = None) -> tuple[GameState, str, Optional[RollResult], Optional[dict], Optional[dict]]:
    log(f"[Turn] Scene {game.scene_count + 1} | Player: {player_message[:100]}")

    # Housekeeping: remove fired clocks that are old enough to no longer
    # provide useful narrator context (keeps prompt lean across long chapters)
    _purge_old_fired_clocks(game)

    # Snapshot BEFORE any mutation — used by ## correction flow and burn
    game.last_turn_snapshot = _build_turn_snapshot(game)
    game.last_turn_snapshot["player_input"] = player_message
    # Co-op: consume the Co-GM's answer and due cockpit signals for this scene.
    # Stored in the snapshot so ## corrections and momentum burns re-use them.
    game.last_turn_snapshot["coop_inputs"] = _coop_begin_turn(game)

    brain = call_brain(client, game, player_message, config)
    game.last_turn_snapshot["brain"] = dict(brain)

    # Reactivate background NPC if Brain targets one
    tid = brain.get("target_npc")
    if tid:
        target = _find_npc(game, tid)
        if target and target.get("status") == "background":
            _reactivate_npc(target, reason=f"targeted by player in scene {game.scene_count + 1}")

    # Apply location change and time progression from Brain
    _apply_brain_location_time(game, brain)

    # NPC Activation — determine who gets full context in prompt
    activated_npcs, mentioned_npcs, npc_activation_debug = activate_npcs_for_prompt(game, brain, player_message)
    # For deceased-NPC guard: include both activated (full context) and mentioned
    # (name in prompt) NPCs.  Mentioned NPCs are scene-relevant (TF-IDF ≥ 0.3) and
    # can legitimately die on-screen even without full activation.
    _scene_present_ids = {n["id"] for n in activated_npcs} | {n["id"] for n in mentioned_npcs}

    # Track pending revelations before narration
    pending_revs = get_pending_revelations(game)

    # Check chaos interrupt (before scene processing)
    chaos_interrupt = check_chaos_interrupt(game)

    # Dialog
    if brain.get("dialog_only") or brain.get("move") == "dialog":
        game.scene_count += 1
        # Clock movement of this scene is decided BEFORE narration so the Narrator
        # can show it (NPC agency on agency scenes, autonomous world ticks).
        npc_agency, agency_clock_events = check_npc_agency(game)
        auto_clock_events = _tick_autonomous_clocks(game)
        prompt = build_dialog_prompt(game, brain, player_words=player_message,
                                     chaos_interrupt=chaos_interrupt,
                                     activated_npcs=activated_npcs,
                                     mentioned_npcs=mentioned_npcs,
                                     config=config, npc_agency=npc_agency,
                                     clock_events=auto_clock_events)
        raw = call_narrator(client, prompt, game, config)
        narration = parse_narrator_response(game, raw)
        if game.last_turn_snapshot is not None:
            game.last_turn_snapshot["narration"] = narration
        metadata = call_narrator_metadata(client, narration, game, config)
        _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids,
                                  world_addition=brain.get("world_addition", "") or "")
        # Mark first pending revelation as used only if the narrator actually wove it in.
        # Capture the result so the Director knows whether a real revelation occurred.
        revelation_confirmed = False
        if pending_revs:
            revelation_confirmed = call_revelation_check(
                client, narration, pending_revs[0], config)
            if revelation_confirmed:
                mark_revelation_used(game, pending_revs[0]["id"])
        # Record pacing
        scene_type = "interrupt" if chaos_interrupt else "breather"
        record_scene_intensity(game, scene_type)
        game.narration_history.append({
            "scene": game.scene_count,
            "prompt_summary": f"Dialog: {brain.get('player_intent', player_message)[:80]}",
            "narration": narration,
        })
        if len(game.narration_history) > MAX_NARRATION_HISTORY:
            game.narration_history = game.narration_history[-MAX_NARRATION_HISTORY:]
        game.session_log.append({"scene": game.scene_count,
                                 "summary": brain.get("player_intent", player_message),
                                 "move": brain.get("move", "dialog"),
                                 "result": "dialog", "consequences": [], "clock_events": [],
                                 "dramatic_question": brain.get("dramatic_question", ""),
                                 "chaos_interrupt": chaos_interrupt,
                                 "npc_activation": npc_activation_debug})
        if len(game.session_log) > MAX_SESSION_LOG:
            game.session_log = game.session_log[-MAX_SESSION_LOG:]
        # Log revelation check result so it is visible in session JSON and Elvira output.
        # Only written when a pending revelation existed — omitted entirely on clean turns.
        if pending_revs and game.session_log:
            game.session_log[-1]["revelation_check"] = {
                "id": pending_revs[0].get("id"),
                "confirmed": revelation_confirmed,
            }
        # NPC agency + autonomous ticks were applied before narration (see above)
        if agency_clock_events and game.session_log:
            game.session_log[-1]["clock_events"].extend(agency_clock_events)
        if auto_clock_events and game.session_log:
            game.session_log[-1]["clock_events"].extend(auto_clock_events)
        # Check story completion
        _check_story_completion(game)

        # Director — deferred to UI layer for non-blocking display
        director_ctx = None
        director_reason = _should_call_director(game, roll_result="dialog",
                                  chaos_used=bool(chaos_interrupt),
                                  new_npcs_found=bool(metadata.get("new_npcs")),
                                  revelation_used=revelation_confirmed)
        if director_reason:
            director_ctx = {"narration": narration, "config": config}
            if game.session_log:
                game.session_log[-1]["director_trigger"] = director_reason
            # Mark phase trigger used so _should_call_director() doesn't re-fire
            # every subsequent turn while the act stays in the same finale phase.
            _mark_director_reason(game, director_reason)
        else:
            log(f"[Director] Skipped (no trigger at scene {game.scene_count})")

        # Note: UI layer handles save_game()
        return game, narration, None, None, director_ctx

    # Action
    game.scene_count += 1
    stat_name = brain.get("stat", "wits")
    roll = roll_action(stat_name, game.get_stat(stat_name), brain.get("move", "face_danger"))
    _raw = roll.d1 + roll.d2 + roll.stat_value
    _score_str = f"{_raw}→10(cap)" if _raw > 10 else str(roll.action_score)
    log(f"[Roll] {roll.move} ({roll.stat_name}={roll.stat_value}): "
        f"{action_dice_text(roll.d1, roll.d2)}+{roll.stat_value}={_score_str} "
        f"vs [{roll.c1},{roll.c2}] \u2192 {roll.result}")
    if roll.match:
        log(f"[Turn] MATCH! Both challenge dice show {roll.c1} \u2014 {roll.result}")
    if game.last_turn_snapshot is not None:
        game.last_turn_snapshot["roll"] = roll

    # Check burn possibility BEFORE consequences reduce momentum
    burn_info = None
    if roll.result in ("MISS", "WEAK_HIT") and game.momentum > 0:
        potential_burn = can_burn_momentum(game, roll)
        if potential_burn:
            # Use last_turn_snapshot as authoritative pre_snapshot — taken before
            # any mutations (including _apply_brain_location_time and scene_count++)
            burn_info = {
                "roll": roll,
                "new_result": potential_burn,
                "cost": game.momentum,
                "brain": dict(brain),
                "player_words": player_message,
                "chaos_interrupt": chaos_interrupt,
                "pre_snapshot": game.last_turn_snapshot,
            }

    consequences, clock_events = apply_consequences(game, roll, brain)
    npc_agency, agency_clock_events = check_npc_agency(game)
    # Autonomous world ticks happen BEFORE narration so a clock that fills now
    # reaches the Narrator (<clock_fired>) instead of completing off-page.
    auto_clock_events = _tick_autonomous_clocks(game)
    prompt = build_action_prompt(game, brain, roll, consequences, clock_events, npc_agency,
                                player_words=player_message, chaos_interrupt=chaos_interrupt,
                                activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                config=config, world_events=auto_clock_events)
    raw = call_narrator(client, prompt, game, config)
    narration = parse_narrator_response(game, raw)
    if game.last_turn_snapshot is not None:
        game.last_turn_snapshot["narration"] = narration
    metadata = call_narrator_metadata(client, narration, game, config)
    _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids,
                              world_addition=brain.get("world_addition", "") or "")
    # Update chaos factor based on result
    update_chaos_factor(game, roll.result)
    # Record pacing
    scene_type = "interrupt" if chaos_interrupt else "action"
    record_scene_intensity(game, scene_type)
    # Mark first pending revelation as used only if the narrator actually wove it in.
    # Capture the result so the Director knows whether a real revelation occurred.
    revelation_confirmed = False
    if pending_revs:
        revelation_confirmed = call_revelation_check(
            client, narration, pending_revs[0], config)
        if revelation_confirmed:
            mark_revelation_used(game, pending_revs[0]["id"])
    game.narration_history.append({
        "scene": game.scene_count,
        "prompt_summary": f"Action ({roll.result}): {brain.get('player_intent', player_message)[:80]}",
        "narration": narration,
    })
    if len(game.narration_history) > MAX_NARRATION_HISTORY:
        game.narration_history = game.narration_history[-MAX_NARRATION_HISTORY:]
    game.session_log.append({"scene": game.scene_count,
                             "summary": brain.get("player_intent", player_message),
                             "move": brain.get("move", "face_danger"),
                             "result": roll.result, "consequences": consequences,
                             "clock_events": clock_events,
                             "position": brain.get("position", "risky"),
                             "effect": brain.get("effect", "standard"),
                             "dramatic_question": brain.get("dramatic_question", ""),
                             "chaos_interrupt": chaos_interrupt,
                             "target_npc": brain.get("target_npc"),
                             "npc_activation": npc_activation_debug})
    if len(game.session_log) > MAX_SESSION_LOG:
        game.session_log = game.session_log[-MAX_SESSION_LOG:]
    # Post-hoc: annotate unresolved social-move target so the warning is visible in
    # session_log["warnings"] (and therefore Elvira's engine_log) — not in consequences[]
    # which is Narrator-visible. apply_consequences() already logs this via log(..., warning),
    # but that only reaches the file logger, not the session JSON.
    if roll.move in SOCIAL_MOVES:
        _tid = brain.get("target_npc")
        if _tid and not _find_npc(game, _tid):
            game.session_log[-1].setdefault("warnings", []).append(
                f"social_target_unresolved:{_tid!r}"
            )
    # Log revelation check result so it is visible in session JSON and Elvira output.
    # Only written when a pending revelation existed — omitted entirely on clean turns.
    if pending_revs and game.session_log:
        game.session_log[-1]["revelation_check"] = {
            "id": pending_revs[0].get("id"),
            "confirmed": revelation_confirmed,
        }
    # Autonomous ticks were applied before narration (see above)
    if agency_clock_events and game.session_log:
        game.session_log[-1]["clock_events"].extend(agency_clock_events)
    if auto_clock_events and game.session_log:
        game.session_log[-1]["clock_events"].extend(auto_clock_events)
    # Check story completion
    _check_story_completion(game)

    # Director — deferred to UI layer for non-blocking display
    director_ctx = None
    director_reason = _should_call_director(game, roll_result=roll.result,
                              chaos_used=bool(chaos_interrupt),
                              new_npcs_found=bool(metadata.get("new_npcs")),
                              revelation_used=revelation_confirmed)
    if director_reason:
        director_ctx = {"narration": narration, "config": config}
        # Store trigger reason in session_log for diagnostics
        if game.session_log:
            game.session_log[-1]["director_trigger"] = director_reason
        # Mark phase trigger used so _should_call_director() doesn't re-fire
        # every subsequent turn while the act stays in the same finale phase.
        _mark_director_reason(game, director_reason)
    else:
        log(f"[Director] Skipped (no trigger at scene {game.scene_count})")

    # Note: UI layer handles save_game()
    return game, narration, roll, burn_info, director_ctx


def run_deferred_director(client: anthropic.Anthropic, game: GameState,
                          director_ctx: dict):
    """Run the Director call that was deferred from process_turn.
    Called by the UI layer AFTER rendering narration for non-blocking display.
    Modifies game state in-place (adds guidance + reflections)."""
    try:
        narration = director_ctx["narration"]
        config = director_ctx.get("config")
        guidance = call_director(client, game, narration, config)
        # Transactional: a failure halfway through applying guidance must not leave
        # half-updated NPCs/clocks behind.
        with _rollback_on_error(game, "Director"):
            _apply_director_guidance(game, guidance)
    except Exception as e:
        log(f"[Director] Deferred call failed gracefully: {e}", level="warning")



def _check_story_completion(game: GameState):
    """Check if the story has reached its natural end point.

    Three-stage trigger to avoid premature epilogue offers mid-mission:

    PRIMARY: The penultimate act must have a recorded transition in
    triggered_transitions — meaning the Director confirmed the final act was
    narratively entered — AND scene_count has reached the final act's
    scene_range end. Final acts have no transition_trigger by design, so
    the penultimate act's transition is the only reliable signal that the
    resolution phase is genuinely underway.

    SCENE-RANGE BACK-FILL: If scene_count has reached final_end but the Director
    never returned act_transition=true (e.g. all Director runs were superseded by
    fast play), transitions are derived from scene_range alone and added to
    triggered_transitions. The primary check is then re-evaluated. This prevents
    the epilogue from being permanently suppressed when the race-condition fix
    (reset_stale_reflection_flags) cleared Director contexts before they ran.

    FALLBACK: If no Director-confirmed transition exists and scene_count is
    still below final_end (back-fill not yet eligible), story_complete fires at
    final_end + 5 as a final safety net. The +5 buffer is intentionally generous
    because Kishōtenketsu structures naturally run longer than 3-act ones.

    Once set, story_complete is never unset here (Director or ## correction
    may still clear it via snapshot restore).
    """
    if not game.story_blueprint or not game.story_blueprint.get("acts"):
        return
    # Already set — nothing to do
    if game.story_blueprint.get("story_complete"):
        return
    acts = game.story_blueprint["acts"]
    if not acts:
        return
    final_act = acts[-1]
    final_end = _safe_sr(final_act, fallback_start=14)[1]

    # Primary: penultimate act was Director-confirmed → final act narratively entered
    # Use `or []` to guard against triggered_transitions=None (can occur when the
    # Story Architect returns the field as null instead of omitting it entirely)
    bp = game.story_blueprint
    triggered = set(bp.get("triggered_transitions") or [])
    penultimate_id = f"act_{len(acts) - 2}"
    final_act_entered = len(acts) >= 2 and penultimate_id in triggered

    # Scene-range back-fill: if the scene count has reached (or passed) the final act's
    # range end but the Director never returned act_transition=true (e.g. all Director
    # runs were superseded by fast play), derive transitions from scene_range alone.
    # This mirrors the back-fill in _apply_director_guidance and runs at most once per
    # game — only when primary check fails AND scene_count >= final_end.
    if not final_act_entered and game.scene_count >= final_end:
        if bp.get("triggered_transitions") is None:
            bp["triggered_transitions"] = []
        for i, act in enumerate(acts[:-1]):  # all acts except the final one
            act_id = f"act_{i}"
            sr = _safe_sr(act, fallback_start=i * 5 + 1)
            if game.scene_count > sr[1] and act_id not in bp["triggered_transitions"]:
                bp["triggered_transitions"].append(act_id)
                log(f"[Story] Back-filled transition: {act_id} "
                    f"(scene {game.scene_count} > range end {sr[1]}, Director never confirmed)")
        # Re-evaluate with the back-filled set
        triggered = set(bp.get("triggered_transitions") or [])
        final_act_entered = len(acts) >= 2 and penultimate_id in triggered

    if final_act_entered and game.scene_count >= final_end:
        bp["story_complete"] = True
        log(f"[Story] Complete: final act entered ('{penultimate_id}' triggered) "
            f"+ scene {game.scene_count} >= range end {final_end}")
        return

    # Fallback: significantly past the final range with no Director confirmation
    if game.scene_count >= final_end + 5:
        bp["story_complete"] = True
        log(f"[Story] Complete (fallback): scene {game.scene_count} >= "
            f"final_end+5 ({final_end + 5}), no Director confirmation")



# ===============================================================
# CORRECTION SCHEMA + FLOW  (## prefix)
# ===============================================================

CORRECTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "correction_source": {
            "type": "string",
            "enum": ["input_misread", "state_error"],
        },
        # input_misread: how the input SHOULD have been understood
        "corrected_input": {"type": "string"},
        # input_misread: does the corrected interpretation need a different stat?
        "reroll_needed": {"type": "boolean"},
        "corrected_stat": {
            "type": "string",
            "enum": ["edge", "heart", "iron", "shadow", "wits", "none"],
        },
        # What the narrator should keep in mind when rewriting
        "narrator_guidance": {"type": "string"},
        # Whether a Director run is worthwhile (e.g. NPC state changed)
        "director_useful": {"type": "boolean"},
        # Ordered list of atomic state patches to apply after restore
        "state_ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "npc_edit",        # patch fields on existing NPC
                            "npc_split",       # existing NPC → two separate NPCs
                            "npc_merge",       # two NPCs → one (second removed)
                            "location_edit",   # overwrite current_location
                            "scene_context",   # overwrite current_scene_context
                            "time_edit",       # overwrite time_of_day
                            "backstory_append",# append text to game.backstory
                        ],
                    },
                    # op=npc_edit / npc_split / npc_merge: id of affected NPC
                    "npc_id": {"type": ["string", "null"]},
                    # op=npc_split: name/desc for the NEW second NPC
                    "split_name": {"type": ["string", "null"]},
                    "split_description": {"type": ["string", "null"]},
                    # op=npc_merge: id of the NPC to absorb into npc_id
                    "merge_source_id": {"type": ["string", "null"]},
                    # op=npc_edit: dict of fields to overwrite (null for non-edit ops)
                    "fields": {
                        "type": ["object", "null"],
                        "properties": {
                            "name": {"type": ["string", "null"]},
                            "description": {"type": ["string", "null"]},
                            "disposition": {"type": ["string", "null"]},
                            "agenda": {"type": ["string", "null"]},
                            "instinct": {"type": ["string", "null"]},
                            "aliases": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                            },
                            "bond": {"type": ["integer", "null"]},
                            "status": {"type": ["string", "null"]},
                        },
                        "required": ["name", "description", "disposition",
                                     "agenda", "instinct", "aliases", "bond",
                                     "status"],
                        "additionalProperties": False,
                    },
                    # op=location_edit / scene_context / time_edit / backstory_append
                    "value": {"type": ["string", "null"]},
                },
                "required": ["op", "npc_id", "split_name", "split_description",
                             "merge_source_id", "fields", "value"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "correction_source", "corrected_input", "reroll_needed",
        "corrected_stat", "narrator_guidance", "director_useful", "state_ops",
    ],
    "additionalProperties": False,
}


def call_correction_brain(client: anthropic.Anthropic, game: GameState,
                           correction_text: str,
                           config: Optional[EngineConfig] = None) -> dict:
    """Analyse a ## correction request against the last turn snapshot.
    Returns a structured ops-dict that _apply_correction() will execute."""
    snap = game.last_turn_snapshot
    if not snap:
        raise ValueError("No last_turn_snapshot available for correction")

    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)

    # Build concise NPC summary for the model
    def _npc_line(n):
        aka = f' aliases:{json.dumps(n["aliases"], ensure_ascii=False)}' if n.get("aliases") else ""
        return (f'id:{n["id"]} name:"{n["name"]}"{aka} '
                f'disposition:{n["disposition"]} '
                f'desc:"{n.get("description","")[:120]}"')
    npc_lines = "\n".join(_npc_line(n) for n in game.npcs) or "(none)"

    # Represent the last turn compactly
    brain = snap.get("brain") or {}
    roll = snap.get("roll")
    roll_summary = (
        f"{roll.result} ({roll.move}, {roll.stat_name}={roll.stat_value}, "
        f"action_die={action_dice_text(roll.d1, roll.d2)} vs c1={roll.c1}/c2={roll.c2})"
        if roll else "dialog (no roll)"
    )

    system = f"""<role>RPG correction analyser. A player has used ## to correct something about the last scene.</role>
<rules>
- Determine whether the error is "input_misread" (Brain misunderstood WHAT the player did/said/thought)
  OR "state_error" (the game world facts are wrong: wrong NPC, location, relationship, timeline).
- For input_misread: rephrase the player's ORIGINAL input as it should have been understood → corrected_input.
  Set reroll_needed=true only if the correction would change which stat applies.
- For state_error: produce the minimal set of state_ops to fix the world facts.
- narrator_guidance: one concise sentence telling the Narrator what to change in the rewrite.
- director_useful: true if NPC state was meaningfully changed (split/merge/disposition change).
- All text fields in {lang}.
- If correction_source=input_misread and no state changes are needed, return state_ops=[].
- If correction_source=state_error, corrected_input="" and reroll_needed=false.
- NPC DEATH: If the player states an NPC is dead/deceased, use op="npc_edit" with fields.status="deceased".
  Do NOT write death annotations like "VERSTORBEN" or "DECEASED" into fields.description — the status
  field is the correct and only mechanism. Set fields.description=null to leave it unchanged.
- NPC RENAME: If the player explicitly renames an NPC (e.g. "Benenne X in Y um" / "Rename X to Y" /
  "X heißt jetzt Y"), use op="npc_edit" with fields.name="Y". The engine will automatically move the
  old name into aliases — you must NOT add it to fields.aliases yourself, and you must NOT put the new
  name into fields.aliases. Set fields.aliases=null to leave aliases unchanged.
</rules>"""

    user_msg = f"""## correction from player: {correction_text}

<last_turn>
player_input: {snap.get("player_input", "")}
brain_interpretation: move={brain.get("move","?")} stat={brain.get("stat","?")} intent={brain.get("player_intent","")[:200]}
roll: {roll_summary}
narration (first 600 chars): {(snap.get("narration") or "")[:600]}
</last_turn>

<current_state>
location: {game.current_location}
scene_context: {game.current_scene_context[:200]}
time: {game.time_of_day}
npcs:
{npc_lines}
</current_state>"""

    log(f"[Correction] Analysing: {correction_text[:100]}")
    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=CORRECTION_MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema",
                                      "schema": CORRECTION_OUTPUT_SCHEMA}},
        )
        result = json.loads(_response_text(response))
        log(f"[Correction] source={result['correction_source']} "
            f"reroll={result['reroll_needed']} ops={len(result['state_ops'])}")
        return result
    except Exception as e:
        log(f"[Correction] Brain failed ({type(e).__name__}: {e}), "
            f"falling back to no-op state_error", level="warning")
        return {
            "correction_source": "state_error",
            "corrected_input": "",
            "reroll_needed": False,
            "corrected_stat": "none",
            "narrator_guidance": correction_text,
            "director_useful": False,
            "state_ops": [],
        }


def _apply_correction_ops(game: GameState, ops: list) -> None:
    """Apply the atomic state_ops returned by call_correction_brain."""
    for op_dict in ops:
        op = op_dict.get("op")

        if op == "npc_edit":
            npc = _find_npc(game, op_dict.get("npc_id", ""))
            if npc and op_dict.get("fields"):
                allowed = {"name", "description", "disposition", "agenda",
                           "instinct", "aliases", "bond", "status"}
                # Filter out null values (schema requires all keys, null = unchanged)
                edits = {k: v for k, v in op_dict["fields"].items()
                         if k in allowed and v is not None}
                # Validate status values to prevent garbage
                if "status" in edits:
                    valid_statuses = {"active", "background", "inactive", "deceased", "lore"}
                    if edits["status"] not in valid_statuses:
                        log(f"[Correction] npc_edit: ignoring invalid status "
                            f"'{edits['status']}' for {npc.get('name','?')}", level="warning")
                        del edits["status"]
                    elif edits["status"] == "inactive":
                        edits["status"] = "background"  # legacy value — three-tier system
                if "disposition" in edits:
                    edits["disposition"] = _normalize_disposition(str(edits["disposition"]))
                if "bond" in edits:
                    try:
                        edits["bond"] = max(0, min(int(edits["bond"]), npc.get("bond_max", 4)))
                    except (TypeError, ValueError):
                        del edits["bond"]
                if "aliases" in edits and not isinstance(edits["aliases"], list):
                    del edits["aliases"]
                if "name" in edits:
                    edits["name"] = _sanitize_npc_name(str(edits["name"]))[0]
                    if not edits["name"]:
                        log(f"[Correction] npc_edit: ignoring empty name for {npc.get('name','?')}",
                            level="warning")
                        del edits["name"]
                # Capture old name BEFORE applying edits — needed for alias bookkeeping
                old_name = npc["name"] if "name" in edits else None
                # If renaming, discard any aliases Haiku may have supplied in the same op.
                # The engine owns alias bookkeeping for renames — Haiku's aliases would
                # overwrite the existing list before the engine can preserve the old name.
                if old_name:
                    edits.pop("aliases", None)
                for k, v in edits.items():
                    npc[k] = v
                # NPC rename bookkeeping: move old name into aliases, clean up new name
                if old_name and old_name != npc["name"]:
                    npc.setdefault("aliases", [])
                    old_norm = _normalize_for_match(old_name)
                    # Add old name as alias if not already present
                    if not any(_normalize_for_match(a) == old_norm for a in npc["aliases"]):
                        npc["aliases"].append(old_name)
                    # Remove new name from aliases if Haiku put it there anyway
                    new_norm = _normalize_for_match(npc["name"])
                    npc["aliases"] = [a for a in npc["aliases"]
                                      if _normalize_for_match(a) != new_norm]
                    log(f"[Correction] npc_edit: renamed '{old_name}' → '{npc['name']}' "
                        f"(old name added to aliases)")
                    # "X is actually Y" where Y already exists: same person - absorb
                    _absorb_duplicate_npc(game, npc, npc["name"])
                # If marked deceased, scrub common death annotations from description
                elif edits.get("status") == "deceased":
                    npc["description"] = re.sub(
                        r'[\.\s]*(?:VERSTORBEN|DECEASED|TOT|DEAD)\s*[\.\,]?',
                        '', npc.get("description", ""), flags=re.IGNORECASE
                    ).strip().rstrip('.,').strip()
                    log(f"[Correction] npc_edit: {npc['name']} marked deceased "
                        f"(description cleaned)")
                elif edits:
                    log(f"[Correction] npc_edit: {npc['name']} fields={list(edits.keys())}")

        elif op == "npc_split":
            existing = _find_npc(game, op_dict.get("npc_id", ""))
            if existing:
                new_name = _sanitize_npc_name(str(op_dict.get("split_name") or ""))[0] or "Unknown"
                new_desc = op_dict.get("split_description") or ""
                clash = _find_npc(game, new_name)
                if clash and clash is not existing:
                    log(f"[Correction] npc_split skipped: '{new_name}' already exists "
                        f"({clash.get('id')})", level="warning")
                    continue
                new_id, _ = _next_npc_id(game)
                new_npc = {
                    "id": new_id,
                    "name": new_name,
                    "description": new_desc,
                    "disposition": "neutral",
                    "bond": 0,
                    "bond_max": 4,
                    "status": "active",
                    "introduced": True,
                    "memory": [],
                    "aliases": [],
                    "details": {},
                    "agenda": "",
                    "instinct": "",
                    "last_location": game.current_location,
                }
                _ensure_npc_memory_fields(new_npc)
                game.npcs.append(new_npc)
                log(f"[Correction] npc_split: '{existing['name']}' → also '{new_name}' ({new_id})")

        elif op == "npc_merge":
            target = _find_npc(game, op_dict.get("npc_id", ""))
            source = _find_npc(game, op_dict.get("merge_source_id", ""))
            if target and source and target is not source:
                # Smart merge direction: the NPC with richer data survives.
                # The AI often gets target/source backwards — e.g. merging a
                # well-described NPC INTO an empty stub. We score both and swap
                # if the "source" is actually the richer NPC.
                def _npc_richness(n):
                    return (len(n.get("memory", []))
                            + (3 if n.get("description") else 0)
                            + (2 if n.get("agenda") else 0)
                            + (1 if n.get("instinct") else 0))
                if _npc_richness(source) > _npc_richness(target):
                    log(f"[Correction] npc_merge: swapping direction — "
                        f"'{source['name']}' is richer than '{target['name']}'")
                    target, source = source, target
                # Absorb memories and aliases, then remove source
                target.setdefault("memory", []).extend(source.get("memory", []))
                target_alias_norms = {_normalize_for_match(a) for a in target.get("aliases", [])}
                for alias in source.get("aliases", []):
                    if _normalize_for_match(alias) not in target_alias_norms:
                        target.setdefault("aliases", []).append(alias)
                        target_alias_norms.add(_normalize_for_match(alias))
                if _normalize_for_match(source["name"]) not in target_alias_norms:
                    target.setdefault("aliases", []).append(source["name"])
                # Inherit description/agenda/instinct if target lacks them
                if not target.get("description") and source.get("description"):
                    target["description"] = source["description"]
                if not target.get("agenda") and source.get("agenda"):
                    target["agenda"] = source["agenda"]
                if not target.get("instinct") and source.get("instinct"):
                    target["instinct"] = source["instinct"]
                # Sanitize: strip any parenthetical annotations the source name
                # may have introduced as aliases (e.g. "Ein Mann im braunen Wams")
                _apply_name_sanitization(target)
                # Re-point references to the absorbed NPC: about_npc tags in other
                # NPCs' memories and clock ownership (owner is stored as a name).
                src_id, tgt_id = source["id"], target["id"]
                src_norms = {_normalize_for_match(source["name"])}
                src_norms.update(_normalize_for_match(a) for a in source.get("aliases", []))
                for other in game.npcs:
                    for m in other.get("memory", []):
                        if isinstance(m, dict) and m.get("about_npc") == src_id:
                            m["about_npc"] = None if other is target else tgt_id
                for clock in game.clocks:
                    if _normalize_for_match(clock.get("owner", "")) in src_norms:
                        clock["owner"] = target["name"]
                target["bond"] = max(target.get("bond", 0), source.get("bond", 0))
                _consolidate_memory(target)
                game.npcs = [n for n in game.npcs if n["id"] != source["id"]]
                log(f"[Correction] npc_merge: '{source['name']}' absorbed into '{target['name']}'")

        elif op == "location_edit":
            if op_dict.get("value"):
                game.current_location = _short_location_name(str(op_dict["value"]))
                log(f"[Correction] location → {game.current_location}")

        elif op == "scene_context":
            if op_dict.get("value"):
                game.current_scene_context = op_dict["value"]
                log(f"[Correction] scene_context updated")

        elif op == "time_edit":
            _tv = str(op_dict.get("value") or "").strip().lower().replace(" ", "_")
            if _tv in TIME_PHASES:
                game.time_of_day = _tv
                game.time_unchanged_scenes = 0
                log(f"[Correction] time_of_day → {game.time_of_day}")

        elif op == "backstory_append":
            if op_dict.get("value"):
                sep = "\n" if game.backstory else ""
                game.backstory += sep + op_dict["value"]
                log(f"[Correction] backstory appended")
    _sync_clock_owners(game, "Correction")


def _restore_from_snapshot(game: GameState, snap: dict) -> None:
    """Fully restore all turn-mutable GameState fields from a last_turn_snapshot,
    including removal of the turn's session_log / narration_history entries.
    Used by the ## correction flow for input_misread corrections."""
    _restore_snapshot(game, snap, logs=True)
    log("[Correction] State fully restored from snapshot")


def process_correction(client: anthropic.Anthropic, game: GameState,
                        correction_text: str,
                        config: Optional[EngineConfig] = None
                        ) -> tuple[GameState, str, Optional[dict]]:
    """Transactional wrapper — see _process_correction_impl(). On any exception the
    GameState is rolled back to its state at call time (_rollback_on_error)."""
    with _rollback_on_error(game, "Correction"):
        _coop_resume_turn(game, (game.last_turn_snapshot or {}).get("coop_inputs"))
        try:
            result = _process_correction_impl(client=client, game=game, correction_text=correction_text, config=config)
            # An input_misread re-run replaced the turn's session_log entry — log the
            # Co-GM inputs again so surfaced seeds are still recognised afterwards
            _coop_end_turn(game)
            return result
        finally:
            _coop_drop_turn(game)


def _process_correction_impl(client: anthropic.Anthropic, game: GameState,
                        correction_text: str,
                        config: Optional[EngineConfig] = None
                        ) -> tuple[GameState, str, Optional[dict]]:
    """Handle a ## correction request.
    Returns (game, rewritten_narration, director_ctx).
    The caller (UI layer) must:
      - replace the last narrator chat message with the returned narration
      - run the deferred director if director_ctx is not None
      - call save_game() after display
    """
    snap = game.last_turn_snapshot
    if not snap:
        log("[Correction] No snapshot available — cannot correct", level="warning")
        return game, "(Keine Korrektur möglich — kein letzter Zug im Speicher.)", None

    _cfg = config or EngineConfig()
    agency_clock_events: list[dict] = []  # populated by check_npc_agency() in input_misread re-runs
    auto_clock_events: list[dict] = []    # autonomous ticks of an input_misread re-run

    # Step 1: Analyse the correction
    analysis = call_correction_brain(client, game, correction_text, _cfg)
    source = analysis["correction_source"]

    # Step 2a: input_misread → full state restore, then re-run Brain + optional Roll
    if source == "input_misread":
        _restore_from_snapshot(game, snap)
        corrected_input = analysis.get("corrected_input") or snap.get("player_input", "")

        # Re-run Brain with the corrected input interpretation
        brain = call_brain(client, game, corrected_input, _cfg)
        # Scene advance + targeted-NPC reactivation + location/time (shared helper)
        _reapply_turn_structure(game, brain)

        if analysis.get("reroll_needed") and brain.get("stat", "none") != "none":
            # Full action path with new roll
            stat_name = brain.get("stat", "wits")
            roll = roll_action(stat_name, game.get_stat(stat_name), brain.get("move", "face_danger"))
            _raw = roll.d1 + roll.d2 + roll.stat_value
            _score_str = f"{_raw}→10(cap)" if _raw > 10 else str(roll.action_score)
            log(f"[Roll] {roll.move} ({roll.stat_name}={roll.stat_value}): "
                f"{action_dice_text(roll.d1, roll.d2)}+{roll.stat_value}={_score_str} "
                f"vs [{roll.c1},{roll.c2}] \u2192 {roll.result} (correction re-roll)")
            consequences, clock_events = apply_consequences(game, roll, brain)
            npc_agency, agency_clock_events = check_npc_agency(game)
            # The restore rolled back the original turn's world ticks — roll them again
            auto_clock_events = _tick_autonomous_clocks(game)
            activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(game, brain, corrected_input)
            prompt = build_action_prompt(game, brain, roll, consequences, clock_events, npc_agency,
                                         player_words=corrected_input, config=_cfg,
                                         activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                         world_events=auto_clock_events)
        else:
            # Dialog / intent-only path — no new roll. NPC agency and world ticks of
            # the original turn were rolled back with the clocks — apply them again.
            roll = None
            npc_agency, agency_clock_events = check_npc_agency(game)
            auto_clock_events = _tick_autonomous_clocks(game)
            activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(game, brain, corrected_input)
            prompt = build_dialog_prompt(game, brain, player_words=corrected_input,
                                         activated_npcs=activated_npcs,
                                         mentioned_npcs=mentioned_npcs, config=_cfg,
                                         npc_agency=npc_agency, clock_events=auto_clock_events)

    # Step 2b: state_error → patch state in-place, no re-roll
    # IMPORTANT: do NOT call apply_consequences() here — consequences from the
    # original turn are already baked into the GameState.  Re-applying would
    # double-deduct health/spirit/supply/momentum and double-tick clocks.
    else:
        roll = snap.get("roll")           # keep original roll (may be None for dialog)
        brain = snap.get("brain") or {}   # keep original brain output
        _apply_correction_ops(game, analysis.get("state_ops", []))
        activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(
            game, brain, snap.get("player_input", ""))
        # Read original consequences from session_log for prompt-building only
        _last_log = game.session_log[-1] if game.session_log else {}
        if roll:
            consequences = _last_log.get("consequences", [])
            clock_events = _last_log.get("clock_events", [])
            # tick=False: the original turn already advanced NPC-owned clocks —
            # re-ticking here would double-advance them on every 5th scene.
            npc_agency, _ = check_npc_agency(game, tick=False)
            prompt = build_action_prompt(game, brain, roll, consequences, clock_events, npc_agency,
                                         player_words=snap.get("player_input", ""), config=_cfg,
                                         activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs)
        else:
            prompt = build_dialog_prompt(game, brain, player_words=snap.get("player_input", ""),
                                         activated_npcs=activated_npcs,
                                         mentioned_npcs=mentioned_npcs, config=_cfg)

    # Step 3: Narrator rewrite — inject correction context
    correction_tag = (
        f"\n<correction_context>{html.escape(analysis['narrator_guidance'])}</correction_context>"
        f"\n<correction_instruction>Rewrite the scene incorporating the correction above. "
        f"Same events and outcome — only adjust what the correction requires.</correction_instruction>"
    )
    prompt = prompt + correction_tag

    raw = call_narrator(client, prompt, game, _cfg)
    narration = parse_narrator_response(game, raw)

    # Update snapshot with rewritten narration so a follow-up ## works correctly
    if game.last_turn_snapshot is not None:
        game.last_turn_snapshot["narration"] = narration
        if source == "input_misread":
            game.last_turn_snapshot["brain"] = dict(brain)
            game.last_turn_snapshot["roll"] = roll

    # Step 4: Metadata extraction (new NPCs, memories etc. from rewritten scene)
    _scene_present_ids = {n["id"] for n in activated_npcs} | {n["id"] for n in mentioned_npcs}
    metadata = call_narrator_metadata(client, narration, game, _cfg)
    _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids,
                              world_addition=brain.get("world_addition", "") or "")

    # Step 5: Update session_log / narration_history
    intent = brain.get("player_intent", snap.get("player_input", ""))[:80]
    narration_entry = {
        "scene": game.scene_count,
        "prompt_summary": f"[corrected] {intent}",
        "narration": narration,
    }

    if source == "input_misread":
        # Full re-run after rollback: chaos/intensity need fresh recording
        if roll:
            update_chaos_factor(game, roll.result)
            scene_type = "action"
        else:
            scene_type = "breather"
        record_scene_intensity(game, scene_type)
        # _restore_from_snapshot popped the old entries → append new ones
        game.narration_history.append(narration_entry)
        if len(game.narration_history) > MAX_NARRATION_HISTORY:
            game.narration_history = game.narration_history[-MAX_NARRATION_HISTORY:]
        game.session_log.append({
            "scene": game.scene_count,
            "summary": f"[corrected] {intent}",
            "move": brain.get("move", "dialog"),
            "result": roll.result if roll else "dialog",
            "consequences": [],
            "clock_events": [],
            "dramatic_question": brain.get("dramatic_question", ""),
            "chaos_interrupt": None,
            "npc_activation": "",
        })
        if len(game.session_log) > MAX_SESSION_LOG:
            game.session_log = game.session_log[-MAX_SESSION_LOG:]
        if agency_clock_events and game.session_log:
            game.session_log[-1]["clock_events"].extend(agency_clock_events)
        if auto_clock_events and game.session_log:
            game.session_log[-1]["clock_events"].extend(auto_clock_events)
        # The restore also rolled back story_complete — re-evaluate for this scene
        _check_story_completion(game)
    else:
        # state_error: no rollback → chaos/intensity already recorded by original turn.
        # Only update narration text; preserve original consequences/clock_events.
        if game.narration_history:
            game.narration_history[-1] = narration_entry
        else:
            game.narration_history.append(narration_entry)
        if game.session_log:
            game.session_log[-1]["summary"] = f"[corrected] {intent}"
        else:
            game.session_log.append({
                "scene": game.scene_count,
                "summary": f"[corrected] {intent}",
                "move": brain.get("move", "dialog"),
                "result": roll.result if roll else "dialog",
                "consequences": [],
                "clock_events": [],
                "dramatic_question": brain.get("dramatic_question", ""),
                "chaos_interrupt": None,
                "npc_activation": "",
            })
        # Note: agency_clock_events are intentionally NOT extended here.
        # state_error preserves the original turn's session_log entry, which already
        # received the agency tick events from the original process_turn() call.
        # Extending again would produce duplicate clock_events entries.

    # Step 6: Director — only when useful and NPC state changed
    director_ctx = None
    if analysis.get("director_useful"):
        director_reason = _should_call_director(
            game, roll_result=roll.result if roll else "dialog",
            chaos_used=False,
            new_npcs_found=bool(metadata.get("new_npcs")),
            revelation_used=False,
        )
        if director_reason:
            director_ctx = {"narration": narration, "config": _cfg}
            log(f"[Correction] Director queued (reason: {director_reason})")
            _mark_director_reason(game, director_reason)

    log(f"[Correction] Complete: source={source}, rewrite done")
    return game, narration, director_ctx


def process_momentum_burn(client: anthropic.Anthropic, game: GameState,
                          old_roll: RollResult, new_result: str,
                          brain_data: dict, player_words: str = "",
                          config: Optional[EngineConfig] = None,
                          pre_snapshot: Optional[dict] = None,
                          chaos_interrupt: Optional[str] = None) -> tuple[GameState, str]:
    """Transactional wrapper — see _process_momentum_burn_impl(). On any exception the
    GameState is rolled back to its state at call time (_rollback_on_error)."""
    with _rollback_on_error(game, "Burn"):
        _coop_resume_turn(game, (pre_snapshot or {}).get("coop_inputs"))
        try:
            return _process_momentum_burn_impl(client=client, game=game, old_roll=old_roll, new_result=new_result, brain_data=brain_data, player_words=player_words, config=config, pre_snapshot=pre_snapshot, chaos_interrupt=chaos_interrupt)
        finally:
            _coop_drop_turn(game)


def _process_momentum_burn_impl(client: anthropic.Anthropic, game: GameState,
                          old_roll: RollResult, new_result: str,
                          brain_data: dict, player_words: str = "",
                          config: Optional[EngineConfig] = None,
                          pre_snapshot: Optional[dict] = None,
                          chaos_interrupt: Optional[str] = None) -> tuple[GameState, str]:
    """Re-narrate a scene after momentum burn upgrades the result.
    Fully restores game state from pre_snapshot before applying new consequences."""
    # NPC memories from the pre-burn narration disappear with the full NPC restore
    # below (the snapshot predates them) — no separate purge needed.
    # --- Restore state from pre-consequence snapshot ---
    # Spec-driven full restore (all turn-mutable fields). logs=False: the turn's
    # session_log / narration_history entries are edited in place further below.
    _restore_snapshot(game, pre_snapshot, logs=False)
    # Re-apply the structural effects of the turn that the pre-turn snapshot rolled
    # back (scene advance, targeted-NPC reactivation, Brain location/time change,
    # chaos release of a reused interrupt) — shared with the ## re-run path.
    _reapply_turn_structure(game, brain_data, chaos_interrupt)
    # The original turn marked its once-only Director reason (phase:/act_due:) in
    # triggered_director_phases; the blueprint restore above removed that mark while
    # the deferred Director for this turn still runs — re-mark it, otherwise the same
    # phase/act trigger fires a second time on the next turn.
    if game.session_log:
        _mark_director_reason(game, game.session_log[-1].get("director_trigger"))

    # Reset momentum to burn-reset value (Ironsworn: cost of burning is momentum → 2)
    # This must happen before apply_consequences so the upgraded result's momentum
    # gain (+2/+3) is applied on top of the reset value, not on top of the old peak.
    game.momentum = 2
    log(f"[Burn] Fully restored state from snapshot: H{game.health} Sp{game.spirit} Su{game.supply} Chaos{game.chaos_factor} | Momentum reset to 2")

    # Create upgraded roll
    upgraded = RollResult(old_roll.d1, old_roll.d2, old_roll.c1, old_roll.c2,
                          old_roll.stat_name, old_roll.stat_value, old_roll.action_score,
                          new_result, old_roll.move, old_roll.match)

    # Apply new consequences
    consequences, clock_events = apply_consequences(game, upgraded, brain_data)
    # NPC agency ticks were rolled back with the clocks — re-apply them for this scene
    npc_agency, agency_clock_events = check_npc_agency(game)
    # Autonomous world ticks were rolled back as well — roll them again, before
    # narration so a filling clock reaches the Narrator.
    auto_clock_events = _tick_autonomous_clocks(game)
    # Re-run NPC activation for the re-narrated scene
    activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(game, brain_data, player_words)
    prompt = build_action_prompt(game, brain_data, upgraded, consequences, clock_events, npc_agency,
                                player_words=player_words, chaos_interrupt=chaos_interrupt,
                                activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                config=config, world_events=auto_clock_events)
    prompt = prompt.replace('<task>', '<momentum_burn>Character digs deep, turns the tide.</momentum_burn>\n<task>')

    raw = call_narrator(client, prompt, game, config)
    narration = parse_narrator_response(game, raw)
    metadata = call_narrator_metadata(client, narration, game, config)
    _scene_present_ids = {n["id"] for n in activated_npcs} | {n["id"] for n in mentioned_npcs}
    _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids,
                              world_addition=brain_data.get("world_addition", "") or "")

    # Update chaos after burn (new result counts)
    update_chaos_factor(game, new_result)
    clock_events = clock_events + agency_clock_events + auto_clock_events

    # Keep the correction snapshot in sync with what the player now sees, so a
    # follow-up ## state_error correction re-narrates the upgraded result.
    if game.last_turn_snapshot is not None:
        game.last_turn_snapshot["roll"] = upgraded
        game.last_turn_snapshot["narration"] = narration

    # Replace last narration history entry with burned version
    if game.narration_history:
        game.narration_history[-1] = {
            "scene": game.scene_count,
            "prompt_summary": f"Momentum burn ({new_result}): {brain_data.get('player_intent', '')[:80]}",
            "narration": narration,
        }

    # Update last log entry
    if game.session_log:
        game.session_log[-1]["result"] = new_result
        game.session_log[-1]["consequences"] = consequences
        game.session_log[-1]["clock_events"] = clock_events
        game.session_log[-1]["chaos_interrupt"] = chaos_interrupt
        # revelation_check was computed for the pre-burn narration, which is now discarded.
        # The blueprint restore above already un-marked the revelation (bp_revealed reset to
        # pre-snapshot). Remove the stale field so the log does not claim a confirmed
        # revelation that was never checked against the new narration.
        # The revelation stays pending and will be re-checked on the next turn.
        game.session_log[-1].pop("revelation_check", None)

    # story_complete was rolled back with the blueprint — re-evaluate for this scene
    _check_story_completion(game)

    # Note: UI layer handles save_game()
    return game, narration

