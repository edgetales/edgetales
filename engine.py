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
from pathlib import Path
from datetime import datetime
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

VERSION = "0.9.83"
BRAIN_MODEL = "claude-haiku-4-5-20251001"
NARRATOR_MODEL = "claude-sonnet-4-6"
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
MAX_NPC_MEMORY_ENTRIES = 25        # Per NPC (total: observations + reflections)
MAX_NPC_OBSERVATIONS = 15          # Max observation memories per NPC
MAX_NPC_REFLECTIONS = 8            # Max reflection memories per NPC
MAX_NARRATION_HISTORY = 6          # Recent narrations kept for prompt context
MAX_NARRATION_CHARS = 1500         # Truncation per narration entry
MAX_SESSION_LOG = 50               # Scene log entries kept
REFLECTION_THRESHOLD = 30          # Importance accumulator threshold for reflection
MAX_ACTIVATED_NPCS = 3             # Max NPCs with full context in narrator prompt
NPC_ACTIVATION_THRESHOLD = 0.7     # Minimum score for full NPC activation
NPC_MENTION_THRESHOLD = 0.3        # Minimum score for NPC name mention
DIRECTOR_INTERVAL = 3              # Call director every N scenes (when no trigger)
MEMORY_RECENCY_DECAY = 0.92        # Exponential decay factor for memory recency
AUTONOMOUS_CLOCK_TICK_CHANCE = 0.20  # Per-scene chance each threat clock ticks autonomously
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
NARRATOR_MAX_TOKENS    = _MAX_TOKENS_SONNET   # call_narrator (was 3500)
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
                    "updated_instinct":    {"type": ["string", "null"]},
                    "agenda":              {"type": ["string", "null"]},
                    "instinct":            {"type": ["string", "null"]},
                },
                "required": ["npc_id", "reflection", "tone", "tone_key",
                             "about_npc", "updated_description", "updated_agenda",
                             "updated_instinct", "agenda", "instinct"],
                "additionalProperties": False,
            },
        },
        "arc_notes": {"type": "string"},
        "act_transition": {"type": "boolean"},
    },
    "required": ["scene_summary", "narrator_guidance", "npc_guidance",
                  "pacing", "npc_reflections", "arc_notes", "act_transition"],
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
        "scene_context": {"type": "string"},
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
                },
                "required": ["npc_id", "event", "emotional_weight", "about_npc"],
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
    },
    "required": ["scene_context", "location_update", "time_update",
                  "memory_updates", "new_npcs", "npc_renames", "npc_details",
                  "deceased_npcs", "lore_npcs"],
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
        "scene_context":  {"type": "string"},
        "time_of_day":    {"type": ["string", "null"]},
    },
    "required": ["npcs", "clocks", "location", "scene_context", "time_of_day"],
    "additionalProperties": False,
}

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
    if not name or '(' not in name:
        return name.strip(), []
    m = re.match(r'^(.+?)\s*\((.+)\)\s*$', name)
    if not m:
        return name.strip(), []
    clean = m.group(1).strip()
    paren = m.group(2).strip()
    if not clean:
        return name.strip(), []
    # Check for explicit alias hints ("auch bekannt als ...", "aka ...")
    alias_match = _ALIAS_HINT_RE.search(paren)
    if alias_match:
        alias = paren[alias_match.end():].strip().rstrip('.')
        return clean, [alias] if alias else []
    # Generic parenthetical (epithet, descriptor) → usable as alias
    return clean, [paren] if paren else []


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
    new_name = new_name.strip()
    # Strip parenthetical annotations from new name (e.g. "Cremin (auch bekannt als Cremon)")
    clean_name, extra_aliases = _sanitize_npc_name(new_name)
    new_name = clean_name
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


def _process_npc_renames(game, json_text: str):
    """Process NPC rename/identity-reveal metadata from narrator <npc_rename> tag.
    Format: [{"npc_id": "npc_2", "new_name": "Hauptmann Krahe"}]"""
    try:
        renames = json.loads(json_text.strip())
        if not isinstance(renames, list):
            return
        for r in renames:
            if not isinstance(r, dict) or not r.get("new_name"):
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
            _merge_npc_identity(npc, new_name, r.get("description", ""), game=game)
            # Absorb any NPC whose name or alias matches the renamed-to name.
            # Alias matching is intentional: if another NPC already carries this name
            # as an alias, they are narratively the same person and should be merged.
            _absorb_duplicate_npc(game, npc, new_name)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Failed to process NPC renames: {e}", level="warning")


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
        log(f"[NPC] Absorbed duplicate '{dup.get('name', '?')}' ({dup_id}) "
            f"into '{original['name']}' ({original.get('id', '?')}): "
            f"{len(dup_mems)} memories transferred, richer={'dup' if dup_richer else 'original'}")
        # Sanitize: strip parenthetical descriptor aliases the dup name may have introduced
        _apply_name_sanitization(original)
        # Consolidate: merged memory lists may now exceed MAX_NPC_MEMORY_ENTRIES
        _consolidate_memory(original)
        break  # Only one duplicate expected


def _process_npc_details(game, json_text: str):
    """Process NPC detail updates from narrator <npc_details> tag.
    Captures invented surnames, description changes, or other facts the narrator
    established for known NPCs (e.g. giving Randy the surname 'Cho',
    or updating Karla from 'pilot' to 'mechanic' after narrative reveal).

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
            new_name = d.get("full_name", "").strip()
            # Strip parenthetical annotations before comparison
            if new_name:
                new_name, paren_aliases = _sanitize_npc_name(new_name)
            else:
                paren_aliases = []
            if new_name and _normalize_for_match(new_name) != _normalize_for_match(npc["name"]):
                old_name = npc["name"]
                # Only update if the new name is an EXTENSION of the old name
                # (e.g. "Randy" → "Randy Cho"), not a completely different name
                old_norm = _normalize_for_match(old_name)
                new_norm = _normalize_for_match(new_name)
                if old_norm in new_norm or new_norm in old_norm:
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
                    # Treat as identity reveal: the extractor provided a valid
                    # npc_id, so we trust the association even when names differ
                    # completely (e.g. "Der Jungfahrer" → "Finn")
                    log(f"[NPC] npc_details: treating '{old_name}' → '{new_name}' "
                        f"as identity reveal (names too different for extension)")
                    _merge_npc_identity(npc, new_name, game=game)
                    # Check if _process_new_npcs already created a duplicate NPC
                    # with this name earlier in the same metadata cycle
                    _absorb_duplicate_npc(game, npc, new_name)

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
            if not isinstance(nd, dict) or not nd.get("name"):
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

        # Check if active NPC count exceeds soft limit
        _retire_distant_npcs(game)

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
        if not isinstance(entry, dict) or not entry.get("name"):
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
            "last_location": "",
        }
        game.npcs.append(npc)
        log(f"[NPC] Lore figure registered: {clean_name} ({npc_id})")


def _retire_distant_npcs(game, max_active: int = MAX_ACTIVE_NPCS):
    """Demote NPCs to 'background' if the active list exceeds the threshold.
    Background NPCs remain visible in the sidebar but are excluded from
    AI prompts and NPC agency checks to keep token budgets manageable."""
    active = [n for n in game.npcs if n.get("status") == "active"]
    if len(active) <= max_active:
        return

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
    npc.setdefault("last_location", "")  # Where NPC was last seen (spatial consistency)
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
            for part in npc_name_lower.split():
                if len(part) >= 3 and part in scan_text:
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
    "serious_balanced": 0.40,
    "absurd_grotesque": 0.40,
    # 3-Act preferred (15%)
    "dark_gritty": 0.15,
    "epic_heroic": 0.15,
    "slow_burn_horror": 0.15,
    "tarantino": 0.15,
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
        GLOBAL_CONFIG_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
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
        cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
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
    """Create a new user directory with metadata."""
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
    user_dir = _get_user_dir(name)
    if not user_dir.exists():
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
    location_history: list = field(default_factory=list)  # Last 3 locations for continuity
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

def update_chaos_factor(game: GameState, result: str):
    """Adjust chaos factor based on roll result."""
    if result == "MISS":
        game.chaos_factor = min(9, game.chaos_factor + 1)
    elif result == "STRONG_HIT":
        game.chaos_factor = max(3, game.chaos_factor - 1)
    # WEAK_HIT: no change


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


def update_location(game: GameState, new_location: str):
    """Update current location and maintain location history."""
    if not new_location:
        return
    # AI sometimes returns underscores instead of spaces in location names
    new_location = new_location.replace("_", " ").strip()
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


def _build_turn_snapshot(game: GameState) -> dict:
    """Build a complete snapshot of all turn-mutable GameState fields.
    Called at the start of process_turn() BEFORE any mutations.
    Used by the ## correction flow to fully restore pre-turn state.
    Also used as the authoritative basis for the burn pre_snapshot.
    NOT persisted to disk — transient only.
    """
    # Snapshot the mutable sub-fields of story_blueprint that can change during a turn:
    # - "revealed": revelation IDs marked used by mark_revelation_used()
    # - "triggered_transitions": act transition IDs set by _apply_director_guidance()
    # - "story_complete": set by _check_story_completion()
    # The rest of story_blueprint (acts, conflict, endings, …) is immutable during a turn.
    bp = game.story_blueprint or {}
    return {
        # Resource tracks
        "health": game.health,
        "spirit": game.spirit,
        "supply": game.supply,
        "momentum": game.momentum,
        "max_momentum": game.max_momentum,
        # Counters & flags
        "scene_count": game.scene_count,
        "chaos_factor": game.chaos_factor,
        "crisis_mode": game.crisis_mode,
        "game_over": game.game_over,
        "epilogue_shown": game.epilogue_shown,
        "epilogue_dismissed": game.epilogue_dismissed,
        # Spatial / temporal
        "current_location": game.current_location,
        "current_scene_context": game.current_scene_context,
        "time_of_day": game.time_of_day,
        "location_history": list(game.location_history),
        # Narrative state — deepcopy because these are mutable nested structures
        "npcs": copy.deepcopy(game.npcs),
        "clocks": copy.deepcopy(game.clocks),
        "director_guidance": copy.deepcopy(game.director_guidance),
        "scene_intensity_history": list(game.scene_intensity_history),
        # Blueprint sub-fields that mutate during a turn
        "bp_revealed": list(bp.get("revealed") or []),
        "bp_triggered_transitions": list(bp.get("triggered_transitions") or []),
        "bp_story_complete": bp.get("story_complete") or False,
        # Log tails — only last entry needed for restore/replace
        "session_log_tail": copy.deepcopy(game.session_log[-1]) if game.session_log else None,
        "narration_history_tail": copy.deepcopy(game.narration_history[-1]) if game.narration_history else None,
        # Turn inputs — filled in progressively by process_turn()
        "player_input": "",   # set immediately in process_turn
        "brain": None,          # set after Brain call
        "roll": None,           # set after roll (None for dialog turns)
        "narration": None,      # set after Narrator call
    }

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
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    c1, c2 = random.randint(1, 10), random.randint(1, 10)
    score = min(d1 + d2 + stat_value, 10)
    if score > c1 and score > c2:
        result = "STRONG_HIT"
    elif score > c1 or score > c2:
        result = "WEAK_HIT"
    else:
        result = "MISS"
    return RollResult(d1, d2, c1, c2, stat_name, stat_value, score, result, move, match=(c1 == c2))


COMBAT_MOVES = {"clash", "strike"}
SOCIAL_MOVES = {"compel", "make_connection", "test_bond"}


def apply_consequences(game: GameState, roll: RollResult, brain: dict) -> tuple[list[str], list[dict]]:
    """Apply mechanical consequences. Position scales severity."""
    consequences = []
    clock_events = []
    tid = brain.get("target_npc")
    target = _find_npc(game, tid) if tid else None

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
                if clock["filled"] >= clock["segments"]:
                    clock["fired"] = True
                    clock["fired_at_scene"] = game.scene_count
                    clock_events.append({"clock": clock["name"], "trigger": clock["trigger_description"]})
                break

    elif roll.result == "WEAK_HIT":
        game.momentum = min(game.max_momentum, game.momentum + 1)
        if roll.move in {"make_connection"} and target:
            target["bond"] = min(target.get("bond_max", 4), target["bond"] + 1)
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

    else:  # STRONG_HIT
        effect = brain.get("effect", "standard")
        mom_gain = 3 if effect == "great" else 2
        game.momentum = min(game.max_momentum, game.momentum + mom_gain)
        if roll.move in {"make_connection", "compel"} and target:
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
    """Autonomously advance threat clocks by chance each scene.
    Each unfilled threat clock rolls AUTONOMOUS_CLOCK_TICK_CHANCE independently —
    simulates the world moving forward regardless of player roll results.
    NPC-owned scheme clocks are excluded (they tick via check_npc_agency instead).
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
                "trigger": clock["trigger_description"],
                "autonomous": True,
            }
            if triggered:
                event["triggered"] = True
            ticked.append(event)
            status = "TRIGGERED" if triggered else f"{clock['filled']}/{clock['segments']}"
            log(f"[Clock] Autonomous tick: '{clock['name']}' → {status}")
    return ticked


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


def check_npc_agency(game: GameState) -> list[str]:
    if game.scene_count % 5 != 0:
        return []
    actions = []
    for npc in game.npcs:
        if npc.get("status") == "active" and npc.get("agenda"):
            actions.append(
                f'NPC "{npc["name"]}" pursues agenda "{npc["agenda"]}" {E["dash"]} concrete offscreen action.')
            # Build normalised name set for this NPC (canonical name + aliases).
            # Clock owner is written by the AI as a name string ("world" or NPC name),
            # never as a raw npc_id — so we must compare by name, not by id.
            npc_norms = {_normalize_for_match(npc["name"])}
            npc_norms.update(_normalize_for_match(a) for a in npc.get("aliases", []))
            for clock in game.clocks:
                clock_owner = clock.get("owner", "")
                if (clock["clock_type"] == "scheme"
                        and clock_owner not in ("", "world")
                        and _normalize_for_match(clock_owner) in npc_norms
                        and clock["filled"] < clock["segments"]):
                    clock["filled"] += 1
                    if clock["filled"] >= clock["segments"]:
                        clock["fired"] = True
                        clock["fired_at_scene"] = game.scene_count
                        actions.append(f'CLOCK FILLED "{clock["name"]}": {clock["trigger_description"]}')
    return actions


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

    return (
        f'<story_arc structure="{_xa(structure)}" act="{act["act_number"]}/{act["total_acts"]}"'
        f' phase="{_xa(act["phase"])}" progress="{act["progress"]}" mood="{_xa(act.get("mood",""))}"'
        f' conflict="{_xa(bp.get("central_conflict",""))}" act_goal="{_xa(act.get("goal",""))}"'
        f'{thematic_attr}/>'
        f'{rev_block}'
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


def _api_create_with_retry(client: anthropic.Anthropic, max_retries: int = 2, **kwargs):
    """Wrapper around client.messages.create with retry on transient API errors.
    Handles rate limits (429), server errors (500/502/503), and overloaded (529)
    with exponential backoff. JSON parsing retries remain in callers.
    529 uses a longer base wait (10s) — standard API overload needs more headroom
    than transient server errors (base 2s)."""
    import time as _time
    for attempt in range(max_retries + 1):
        try:
            return client.messages.create(**kwargs)
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
    ) or "(keine)"
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
    ) or "(keine)"
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
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=BRAIN_MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema", "schema": BRAIN_OUTPUT_SCHEMA}},
        )
        result = json.loads(response.content[0].text)
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
        result = json.loads(response.content[0].text)

        # --- Stat validation (two-layer: prompt + engine) ---
        # Structured outputs guarantee types but not cross-field constraints.
        stats = result["stats"]
        stat_keys = ("edge", "heart", "iron", "shadow", "wits")

        # Layer 0: Clamp each stat to valid range 0–3
        for k in stat_keys:
            stats[k] = max(0, min(3, stats[k]))

        # Layer 1: If sum is wrong, reset to archetype-aware defaults
        total = sum(stats[k] for k in stat_keys)
        if total != STAT_TARGET_SUM:
            log(f"[Setup] AI returned stats summing to {total}, "
                f"resetting to archetype defaults for '{raw_archetype}'", level="warning")
            stats = dict(_ARCHETYPE_STAT_DEFAULTS.get(raw_archetype,
                         _ARCHETYPE_STAT_DEFAULTS["_default"]))
            result["stats"] = stats

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

        log(f"[Setup] Success: name={result['character_name']!r}, "
            f"location={result['starting_location']!r}")
        return result

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
    ) or "(keine)"
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
            return re.sub(r'\s*[—–]\s*', ' - ', response.content[0].text)
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
- Each act has a TRANSITION_TRIGGER: a narrative condition that signals this act is complete and the next should begin. This is a PLAYER ACTION or STORY EVENT, not a scene number. Example: "The player discovers the truth about the shrine" or "The protagonist's daily routine is disrupted by an outsider". The scene_range is a fallback estimate; the trigger is the real boundary.
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
- Each act has a TRANSITION_TRIGGER: a narrative condition that signals this act is complete and the next should begin. This is a PLAYER ACTION or STORY EVENT, not a scene number. Example: "Mike decides to cooperate with the authorities" or "The first repair attempt fails spectacularly". The scene_range is a fallback estimate; the trigger is the real boundary.
- The confrontation{E['arrow_r']}climax TRANSITION_TRIGGER must be a REFRAMING EVENT {E['dash']} not merely an escalation of existing tension, but a discovery or realization that changes what the conflict is fundamentally about.
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
    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=NARRATOR_MODEL, max_tokens=STORY_ARCH_MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema", "schema": STORY_ARCHITECT_OUTPUT_SCHEMA}},
        )
        blueprint = json.loads(response.content[0].text)
        blueprint["revealed"] = []  # Track which revelations have fired
        blueprint["structure_type"] = structure_type
        log(f"[Story] Architect succeeded: "
            f"conflict={blueprint['central_conflict'][:80]}, "
            f"acts={len(blueprint['acts'])}, "
            f"revelations={len(blueprint.get('revelations', []))}")
        return blueprint

    except Exception as e:
        log(f"[Story] Architect failed ({type(e).__name__}: {e}), "
            f"using context-aware fallback", level="warning")

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
        sr = act.get("scene_range", [1, 20])
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
    sr = current.get("scene_range", [1, 20])
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
    """Build narrator system prompt with configured language."""
    lang = get_narration_lang(config)
    kf = _kid_friendly_block(config)
    cb = _content_boundaries_block(game)
    bs = _backstory_block(game)
    sc = _status_context_block(game)
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
{kf}{cb}{bs}{sc}{tone_block}
<rules>
- NEVER mention dice, stats, numbers, or game mechanics
{_quote_rule}
- MISS: concrete failure, situation worsens, NO silver linings
- WEAK_HIT: success at tangible cost
- STRONG_HIT: clean success
- NPCs act per their disposition and memories
- Introduce new NAMED characters through action and dialog. An NPC's agenda and instinct are their engine {E['dash']} let those drives shape how they behave, what they pursue, what they avoid. Distinct voice comes from specifics: vocabulary level, sentence rhythm, and what a character deflects or refuses to acknowledge. One physical trait or habitual gesture makes them tangible.
- BACKSTORY CANON: If <backstory> is present, treat it as ESTABLISHED HISTORY. People mentioned there (family, friends, rivals) are ALREADY KNOWN to the player character {E['dash']} if they appear, they recognize the player and vice versa. NEVER introduce a backstory character as a stranger or reinterpret established relationships. Backstory events ALREADY HAPPENED {E['dash']} reference them as shared memory, not new plot.
- Describe only sensory impressions, never player thoughts
- SENSORY RANGE: Don't default to sight {E['dash']} include at least one non-visual sense per scene (a specific sound, smell, texture, or temperature). These anchor scenes in memory more durably than visual description alone.
- WORLD PERIPHERY: Once per scene, let one small background detail exist that has nothing to do with the player's immediate action {E['dash']} a sound from another room, a stranger's exchange, a worn object, weather shifting outside. Brief, never explained. It signals the world continues beyond this moment.
- SCENE CONTINUITY: Begin in motion, not in setup. The player is still in the same body, the same emotional state as the last scene ended. Do NOT open with a fresh establishing paragraph when the last scene ended mid-action or mid-conversation — unless the player has moved to a new location (compare <location> with <prev_locations>), in which case briefly ground them in the new space before continuing the thread.
- EMOTIONAL CARRY-THROUGH: If the previous scene ended with a significant emotional beat (betrayal, loss, triumph, relief, intimacy, shock), open this scene with that weight still present in the character's body language, perception, and attention. Emotional states do not reset between scenes. Show it through sensation and behavior, not through narration — the character did not process it yet.
- End scenes OPEN {E['dash']} no option lists, no suggested actions
- 2-4 paragraphs
- TEMPORAL CONSISTENCY: If <time> is provided, maintain that time period. Time only moves FORWARD (never backward). If you mention specific times, they must be later than any previously mentioned time. Do NOT invent specific clock times unless narratively important {E['dash']} prefer atmospheric time cues (moonlight, sunset glow, morning mist). CRITICAL: Each scene transition represents minutes to hours of in-world time, NOT days or years. Events from recent scenes just happened {E['dash']} signs don't weather, wounds are fresh, sent NPCs are still en route or just arrived. Never describe recent events or objects as aged, decayed, or long-past unless the player explicitly time-skips.
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
- If <recent_events> is present, treat it as ESTABLISHED FACTS. These events already happened in previous scenes. NEVER contradict them {E['dash']} if an NPC was seen alive, they are alive; if a box was empty, it was empty; if a character said something, they said it. You may add new revelations or reinterpretations, but the physical facts of past scenes are canon.
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
    """Narrator call with conversation memory for style consistency."""
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

    response = _api_create_with_retry(
        client, max_retries=5,
        model=NARRATOR_MODEL, max_tokens=NARRATOR_MAX_TOKENS,
        system=get_narrator_system(config or EngineConfig(), game),
        messages=messages,
    )
    raw = response.content[0].text
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
time_update must be ONE of: early_morning, morning, midday, afternoon, evening, late_evening, night, deep_night — or null if no time change.
location_update: new location name if the character MOVED to a different place, null if they stayed. IMPORTANT: if no movement occurred, always return null — do NOT add city names, qualifiers, or extra words to the existing location. If a move did occur, use the exact place name as it appears in the narration (short and specific, e.g. "Die Kathedrale", not "Die Kathedrale in Lyon").
npc_renames: for identity REVEALS — when an NPC's true or personal name is established for the first time. Covers: spy unmasked, alias discovered, AND descriptor-named NPCs who receive a real name (e.g. "Die Frau im Wollhut" → "Hanna", "Der unbekannte Mann" → "Klaus", "Die Technikerin" → "Sara Novak"). Use the npc_id of the descriptor NPC from the known list and set new_name to the revealed personal name. NOT for surname additions to an already-named NPC (use npc_details for that).
npc_details: for newly established facts (surname, role change). full_name if name extended, description if role/situation changed.
new_npcs: ONLY for characters who are PHYSICALLY PRESENT in the scene AND actively interacting (speaking, acting, reacting). They must NOT already be in the known NPC list. NEVER include the player character. NEVER include:
- Characters who are only MENTIONED in conversation, stories, or memories
- Deceased persons (people discussed as dead, seen only in photos/flashbacks)
- Historical or absent figures (people talked about but not physically there)
- Unnamed characters described only by role ("a waiter", "some guard") unless they speak or interact meaningfully
If a NAMED person is mentioned in dialog but a DIFFERENT unnamed person is physically present, create the NPC for the PHYSICAL person with their own appropriate name/description — do NOT assign the mentioned person's name to the physical person's description.
description must be a PHYSICAL/ROLE description (appearance, occupation, species), NOT what they did in this scene.
memory_updates: for EACH NPC who participated in or witnessed this scene. Use their npc_id from the known list. NEVER create memory_updates for the player character. NEVER create memory_updates for NPCs marked [DECEASED] or for absent characters — only for NPCs physically present and alive in the scene.
NPC DISAMBIGUATION: The known_npcs list shows each NPC's last known location [at:...] and a short description. When the narration uses a name or descriptor that could match multiple NPCs, prefer the NPC whose location matches <current_location> or who is described as being physically present. An NPC [at:FarAwayPlace] is unlikely to appear at <current_location> without the narration explicitly describing their arrival.
about_npc (in memory_updates): If the memory is primarily ABOUT ANOTHER NPC (not the player), set about_npc to that other NPC's npc_id. Examples: NPC A is told something about NPC B → memory on A with about_npc=B's id. NPC A witnesses NPC B doing something → memory on A with about_npc=B's id. If the memory is about the player or a general event, set about_npc to null.
IMPORTANT: If the player directly tells an NPC something about another NPC (gossip, warning, lie, compliment, romantic suggestion), this MUST be captured as its own memory_update with about_npc set — even if other events also happened to that NPC in the same scene. An NPC can have multiple memories per scene if distinctly different events occurred.
deceased_npcs: list NPCs (by npc_id) whose death is DEPICTED BY THE NARRATOR as it happens. This includes BOTH explicit deaths AND deaths described through physical sensation or literary language. Qualifying descriptions include: they collapse / are killed / stop breathing / go limp / their movement stops and does not resume / resistance ceases permanently / consumed by fire / destroyed / pulled under with no return described / body goes still / the struggle ended. LITERARY deaths count: e.g. "the legs kicked twice and then were still" or "the resistance left them" or "they ceased" — if the prose makes clear that a living character has become permanently non-living, mark them deceased. The death does not need to use the words "dead" or "died" — physical cessation described as final qualifies.
CRITICAL: Do NOT mark an NPC as deceased if their death is only CLAIMED, REPORTED, or ALLEGED by another character in dialog (e.g. someone says "Leo ist tot"). Dialog claims about death are unreliable information — characters lie, bluff, or may be wrong. Only narrator-described, physically-witnessed deaths count. Never include NPCs already marked [DECEASED].
lore_npcs: ONLY for named persons established in this scene as historically or narratively significant, but who have NEVER been and are NOT NOW physically present. Use this for dead mentors whose legacy drives the story, missing persons whose fate is central, historical figures whose past actions echo into the present. Rules: (1) They must be NAMED and clearly significant — not just mentioned in passing. (2) Do NOT use for corpses or physically present characters — use new_npcs for those, even if dead. (3) Do NOT include NPCs already marked [LORE] or any other marker in the known_npcs list — they are already tracked. (4) Only add when the narration establishes them as relevant to the ongoing story. NPCs marked [LORE] in known_npcs can receive memory_updates using their npc_id."""

    prompt = f"""<narration>{narration}</narration>
<player_character>{html.escape(game.player_name)}</player_character>
<known_npcs>{chr(10).join(npc_refs) if npc_refs else '(none)'}</known_npcs>
<current_location>{html.escape(game.current_location or 'unknown')}</current_location>
<current_time>{html.escape(game.time_of_day or 'unknown')}</current_time>
Extract all metadata from the narration above. Remember: {html.escape(game.player_name)} is the PLAYER CHARACTER, not an NPC."""

    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=METADATA_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {
                "type": "json_schema",
                "schema": NARRATOR_METADATA_SCHEMA,
            }},
        )
        metadata = json.loads(response.content[0].text)
        log(f"[Metadata] Extracted: {len(metadata.get('memory_updates', []))} memories, "
            f"{len(metadata.get('new_npcs', []))} new NPCs, "
            f"{len(metadata.get('lore_npcs', []))} lore figures, "
            f"{len(metadata.get('deceased_npcs', []))} deceased, "
            f"loc={metadata.get('location_update')}, time={metadata.get('time_update')}")
        return metadata
    except Exception as e:
        log(f"[Metadata] Extraction failed: {e}", level="warning")
        return {"scene_context": "", "location_update": None, "time_update": None,
                "memory_updates": [], "new_npcs": [], "npc_renames": [], "npc_details": [],
                "deceased_npcs": [], "lore_npcs": []}


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
        result = json.loads(response.content[0].text)
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
- Do NOT extract NPCs that are already in the known NPC list below.

Clocks:
- Extract threat clocks mentioned or implied. A threat clock tracks a looming danger.
- Each clock: name, clock_type (usually "threat"), segments (4-8), filled (typically 1 for new clocks), trigger_description (what happens when filled), owner ("world" or NPC name).
- If no clock is obvious, create one based on the central tension of the scene.

Location: the specific location where the scene takes place.
scene_context: 1 sentence capturing the current situation AND dominant mood/tension — not just where/who, but the atmosphere. Example: "Strangers in a hostile tavern, an uneasy truce already fraying at the edges." Extract from the narration; do not invent.
time_of_day: one of early_morning|morning|midday|afternoon|evening|late_evening|night|deep_night, or null if unclear.

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
        data = json.loads(response.content[0].text)
        log(f"[OpeningMeta] Extracted: {len(data.get('npcs', []))} NPCs, "
            f"{len(data.get('clocks', []))} clocks, "
            f"loc={data.get('location')}, time={data.get('time_of_day')}")
        return data
    except Exception as e:
        log(f"[OpeningMeta] Extraction failed: {e}", level="warning")
        return {"npcs": [], "clocks": [], "location": "",
                "scene_context": "", "time_of_day": None}


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
                              scene_present_ids: set = None):
    """Apply structured metadata from the metadata extractor to game state.
    scene_present_ids: set of NPC IDs that were activated or mentioned in the scene.
    If provided, deceased reports are restricted to present NPCs (prevents
    false positives from dialog claims like 'Leo ist tot')."""
    # Scene context (always present)
    ctx = metadata.get("scene_context", "").strip()
    if ctx:
        game.current_scene_context = ctx

    # Location update
    new_loc = metadata.get("location_update")
    if new_loc and new_loc.strip().lower() not in ("none", "null", "same", ""):
        update_location(game, new_loc.strip())

    # Time update
    new_time = metadata.get("time_update")
    if new_time and new_time.strip().lower().replace(" ", "_") in TIME_PHASES:
        game.time_of_day = new_time.strip().lower().replace(" ", "_")

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

    # Lore figures (historically significant, never physically present)
    lore_npcs = metadata.get("lore_npcs", [])
    if lore_npcs:
        _process_lore_npcs(game, lore_npcs)

    # Resolve memory_update references that use invented snake_case slugs
    # for NPCs that were just created in this same metadata cycle.
    # The Extractor can't know the assigned npc_ids for new NPCs, so it
    # invents slugs like "frau_seidlitz" or "moderator_headset" instead.
    mem_updates = metadata.get("memory_updates", [])
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
        _process_npc_details(game, json.dumps(details, ensure_ascii=False))

    # Deceased NPCs — processed before memory updates so status is set first.
    # Note: _apply_memory_updates() intentionally resurrects deceased NPCs when
    # the extractor reports memories for them (= narrator depicted them alive).
    deceased = metadata.get("deceased_npcs", [])
    if deceased:
        _process_deceased_npcs(game, deceased, scene_present_ids=scene_present_ids)

    # Memory updates (mem_updates was already read above for slug resolution;
    # same list reference — _resolve_slug_refs may have patched npc_ids in-place)
    if mem_updates:
        _apply_memory_updates(game, json.dumps(mem_updates, ensure_ascii=False),
                              scene_present_ids=scene_present_ids,
                              pre_turn_npc_ids=pre_npc_ids,
                              pre_turn_lore_ids=pre_lore_ids)


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
            # Allow if NPC was just introduced this scene (walk-in + die edge case)
            has_current_scene_memory = any(
                m.get("scene") == game.scene_count
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
They advance when the player fails rolls OR autonomously as the world moves
forward. When a clock is full, its trigger fires as a hard narrative event —
not optional, not avoidable. Reference clocks in arc_notes and narrator_guidance
when they are ≥50% filled or have recently ticked — they signal what is at stake
and what is coming. A nearly-full clock should create visible narrative pressure.

When phase="aftermath": the planned story arc has concluded and the player chose
to keep playing. Do NOT suggest wrapping up or pushing toward a final scene.
Instead: surface consequences of past events, develop NPC relationships, introduce
organic new tensions. Think "Season 2 setup", not "Season 1 finale". """


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
    if game.story_blueprint and game.story_blueprint.get("acts"):
        act = get_current_act(game)
        if act.get("phase") in ("climax", "resolution", "ten_twist", "ketsu_resolution"):
            return f"phase:{act['phase']}"

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

    # NPCs needing reflection
    reflection_blocks = []
    for n in game.npcs:
        if not n.get("_needs_reflection"):
            continue
        if n.get("status") not in ("active", "background"):
            continue
        _ensure_npc_memory_fields(n)
        recent_obs = [m for m in n.get("memory", [])
                      if m.get("type") == "observation"][-8:]
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
            # Show previous tone so Director can evolve the emotional arc
            prev_tone = prev_reflections[-1].get("emotional_weight", "")
            if prev_tone:
                prev_tone_text = f' last_tone="{_xa(prev_tone)}"'
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
        reflection_blocks.append(
            f'<reflect npc_id="{n.get("id","")}" name="{_xa(n.get("name",""))}"'
            f'{alias_attr} '
            f'disposition="{n.get("disposition","")}" bond="{n.get("bond",0)}" '
            f'description="{npc_desc}"{prev_ref_text}{prev_tone_text}{needs_profile}>'
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
        scene_range = act.get("scene_range", [1, 20])
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
            story_info += (
                f'\n<transition_trigger act="{act["act_number"]}">'
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
    clocks_block = "<clocks>\n" + "\n".join(clocks_lines) + "\n</clocks>" if clocks_lines else ""

    return f"""<setting genre="{_xa(game.setting_genre)}" tone="{_xa(game.setting_tone)}"/>

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
- narrator_guidance: Specific direction for the next 1-2 scenes (in {lang}). When relevant, anchor the guidance to the thematic_thread from <story_arc> — surface the aspect of it most alive in the current moment.
- npc_guidance: Array of {{"npc_id": "npc_1", "guidance": "what this NPC should do/feel next"}} — guidance text in {lang}
- pacing: one of tension_rising, building, climax, breather, resolution
- npc_reflections: Only for NPCs listed in <reflect> tags. Each object has:
  - npc_id: the NPC's ID from the <reflect> tag
  - reflection: 1-2 sentence higher-level insight (in {lang})
  - tone: 1-3 lowercase English words, underscore-separated, capturing the emotional shift (e.g. 'protective_guilt', 'reluctant_trust')
  - tone_key: ONE word from the enum (neutral, curious, wary, suspicious, grateful, terrified, loyal, conflicted, betrayed, devastated, euphoric, defiant, guilty, protective, angry, devoted, impressed, hopeful)
  - updated_description: STRICTLY in {lang}. Max 100 characters. Role + key visual traits + personality. Keep physical details like age, hair, build. Do NOT start with the NPC's name. NO actions, NO posture. Example: 'Grumpy dwarf blacksmith with burn scars, secretly loyal'. null if unchanged.
  - updated_agenda: If this NPC's goals have fundamentally shifted due to recent story events (defeat, revelation, betrayal, alliance formed), write their new driving goal (max 10 words, in {lang}). Use this when the old agenda is clearly obsolete — e.g. an NPC who sought to destroy the player now seeks to understand them. null if the existing agenda still applies.
  - updated_instinct: Same as updated_agenda but for behavioral pattern. null if unchanged.
  - about_npc: If this reflection is primarily about the NPC's feelings toward ANOTHER NPC (not the player), set to that NPC's npc_id. Example: Sophie reflects on her growing attraction to Bruce → about_npc="npc_2". null if the reflection is about the player or general.
  - agenda: NPC's hidden goal (max 8 words, only if needs_profile="true"), null otherwise
  - instinct: NPC's default behavior pattern (max 8 words, only if needs_profile="true"), null otherwise
- arc_notes: Brief story arc progress observation
- act_transition: Evaluate whether the current act's <transition_trigger> has been fulfilled by recent events. Set to true if:
  (a) the narrative condition described in the trigger has clearly been met, OR
  (b) the story has moved PAST the act's scene_range (PAST_RANGE="true") and the trigger's spirit has been approximately met.
  Set to false only if the trigger condition is clearly unmet AND we are still within scene_range. The scene_range is a fallback — content-driven transitions via this flag produce better pacing.

If a <reflect> tag has a last_reflection attribute, write a NEW insight that builds on, deepens, or contradicts it. Do NOT repeat the same theme or emotional tone. If last_tone is present, evolve the emotion — show how the NPC's feelings have shifted, intensified, or transformed since then.
</task>"""


def call_director(client: anthropic.Anthropic, game: GameState,
                  latest_narration: str,
                  config: Optional[EngineConfig] = None) -> dict:
    """Call the Director agent for scene analysis and story guidance.
    Returns a dict with guidance fields, or empty dict on failure."""
    log(f"[Director] Analyzing scene {game.scene_count}")

    prompt = build_director_prompt(game, latest_narration, config)

    try:
        response = _api_create_with_retry(
            client, max_retries=1,
            model=DIRECTOR_MODEL, max_tokens=DIRECTOR_MAX_TOKENS,
            system=DIRECTOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": DIRECTOR_OUTPUT_SCHEMA}},
        )
        guidance = json.loads(response.content[0].text)

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

    # Store guidance for next narrator call
    game.director_guidance = {
        "narrator_guidance": guidance.get("narrator_guidance", ""),
        "npc_guidance": guidance.get("npc_guidance", {}),
        "pacing": guidance.get("pacing", ""),
        "arc_notes": guidance.get("arc_notes", ""),
    }

    # Handle act transition: Director signals that the current act's
    # transition_trigger has been fulfilled → mark in blueprint
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
        if act_idx >= len(acts) - 1:
            log(f"[Director] Ignoring act_transition=true for final act "
                f"(act_{act_idx}) — final acts have no transition by design")
        else:
            # Back-fill: any intermediate acts skipped via scene_range fallback
            # (never explicitly triggered) should be marked before recording this one.
            # Without this, triggered_transitions can have gaps (e.g. act_0, act_2)
            # that make diagnostics misleading.
            for i in range(act_idx):
                prev_id = f"act_{i}"
                if prev_id not in bp["triggered_transitions"]:
                    sr = acts[i].get("scene_range", [1, 20]) if i < len(acts) else [1, 20]
                    if game.scene_count > sr[1]:
                        bp["triggered_transitions"].append(prev_id)
                        log(f"[Director] Back-filled skipped act: {prev_id} "
                            f"(scene {game.scene_count} > range end {sr[1]})")

            act_id = f"act_{act_idx}"
            if act_id not in bp["triggered_transitions"]:
                bp["triggered_transitions"].append(act_id)
                trigger_text = act.get("transition_trigger", "?")
                log(f"[Director] Act transition triggered: act {act.get('act_number')} "
                    f"'{act.get('phase')}' → trigger fulfilled: '{trigger_text[:80]}'")

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
    successfully_reflected_ids: set = set()
    for ref in guidance.get("npc_reflections", []):
        npc_id = ref.get("npc_id", "")
        npc = _find_npc(game, npc_id)
        if not npc:
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
            "emotional_weight": ref.get("tone", "reflective"),  # Narrative compound (e.g. "protective_guilt")
            "tone": ref.get("tone", ""),        # Preserve narrative compound separately for arc tracking
            "tone_key": ref.get("tone_key", ""),  # Machine-readable single word from enum
            "importance": 8,  # Reflections are always important
            "type": "reflection",
            "about_npc": _resolve_about_npc(game, ref.get("about_npc"), owner_id=npc.get("id")),
        })
        npc["_needs_reflection"] = False
        npc["importance_accumulator"] = 0
        npc["last_reflection_scene"] = game.scene_count
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

        # updated_agenda / updated_instinct: always overwrite when provided
        # (for NPCs whose goals have fundamentally shifted due to story events)
        new_agenda = (ref.get("updated_agenda") or "").strip()
        new_instinct = (ref.get("updated_instinct") or "").strip()
        if new_agenda:
            old_agenda = npc.get("agenda", "")
            npc["agenda"] = new_agenda
            log(f"[Director] Agenda updated for {npc['name']}: "
                f"'{old_agenda[:60]}' → '{new_agenda}'")
        if new_instinct:
            old_instinct = npc.get("instinct", "")
            npc["instinct"] = new_instinct
            log(f"[Director] Instinct updated for {npc['name']}: "
                f"'{old_instinct[:60]}' → '{new_instinct}'")

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
    """Escaped <time> element, or empty string if time_of_day is unset."""
    return f'\n<time>{html.escape(game.time_of_day)}</time>' if game.time_of_day else ""


def _loc_hist(game: "GameState") -> str:
    """Escaped <prev_locations> element, or empty string if location_history is empty."""
    if not game.location_history:
        return ""
    locs = ", ".join(html.escape(loc) for loc in game.location_history[-3:])
    return f'\n<prev_locations>{locs}</prev_locations>'


def build_new_game_prompt(game: GameState) -> str:
    crisis = "\n<crisis>Character at breaking point.</crisis>" if game.crisis_mode else ""
    story = _story_context_block(game)
    seed = _creativity_seed()
    log(f"[Narrator] Opening creativity_seed={seed!r}")
    return f"""<scene type="opening">
{_scene_header(game)}
<location>{html.escape(game.current_location)}</location>{_loc_hist(game)}{_time_ctx(game)}
<situation>{html.escape(game.current_scene_context)}</situation>{crisis}
{story}</scene>
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
    return f"""<target_npc name="{_xa(target['name'])}" disposition="{target['disposition']}" bond="{target['bond']}/{target.get('bond_max',4)}"{aliases_attr}>
agenda:{html.escape(target.get('agenda',''))} instinct:{html.escape(target.get('instinct',''))}
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

        parts.append(
            f'<activated_npc name="{_xa(npc["name"])}" disposition="{npc["disposition"]}" '
            f'bond="{npc["bond"]}"{mem_hint}{loc_hint}/>'
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


def build_dialog_prompt(game: GameState, brain: dict, player_words: str = "",
                        chaos_interrupt: Optional[str] = None,
                        activated_npcs: list = None, mentioned_npcs: list = None,
                        config: Optional[EngineConfig] = None) -> str:
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
    if dg and dg.get("narrator_guidance"):
        director_block = f'\n<director_guidance>{html.escape(dg["narrator_guidance"])}</director_guidance>'
        # NPC-specific guidance
        for npc_id, guidance in dg.get("npc_guidance", {}).items():
            director_block += f'\n<npc_note for="{npc_id}">{html.escape(guidance)}</npc_note>'

    return f"""<scene type="dialog" n="{game.scene_count}">
{_scene_header(game)}
<intent>{html.escape(brain.get('player_intent', ''))}</intent>{pw}
<location>{html.escape(game.current_location)}</location>{_loc_hist(game)}{_time_ctx(game)}
{npc}{npcs_section}{wl}{crisis}
{pacing}{director_block}
{_story_context_block(game)}{_recent_events_block(game)}</scene>
<task>2-3 paragraphs of immersive narration. Let the world breathe around the conversation — small details of place, light, sound, and texture that make this moment feel inhabited. Something between the characters should shift by the end. Let the current act's mood (from <story_arc>) shape the undertone of the exchange — even a quiet conversation carries the weight of the surrounding phase. If <director_guidance> is present, follow its direction while maintaining your creative voice.</task>"""


def build_action_prompt(game: GameState, brain: dict, roll: RollResult,
                        consequences: list, clock_events: list, npc_agency: list,
                        player_words: str = "",
                        chaos_interrupt: Optional[str] = None,
                        activated_npcs: list = None, mentioned_npcs: list = None,
                        config: Optional[EngineConfig] = None) -> str:
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
    pacing = _pacing_block(game, chaos_interrupt, brain.get("dramatic_question", ""))

    # Director guidance injection
    director_block = ""
    dg = game.director_guidance
    if dg and dg.get("narrator_guidance"):
        director_block = f'\n<director_guidance>{html.escape(dg["narrator_guidance"])}</director_guidance>'
        for npc_id, guidance in dg.get("npc_guidance", {}).items():
            director_block += f'\n<npc_note for="{npc_id}">{html.escape(guidance)}</npc_note>'

    return f"""<scene type="action" n="{game.scene_count}">
{_scene_header(game)}
<intent>{html.escape(brain.get('player_intent', ''))} ({html.escape(brain.get('approach', ''))})</intent>{pw}
{constraint}
{position_tag}
<status h="{game.health}" sp="{game.spirit}" su="{game.supply}" m="{game.momentum}"/>
<location>{html.escape(game.current_location)}</location>{_loc_hist(game)}{_time_ctx(game)}
{npc}{npcs_section}{wl}{flags}{agency}
{pacing}{director_block}
{_story_context_block(game)}{_recent_events_block(game)}</scene>
<task>2-4 paragraphs of immersive narration. Let the roll consequence open new story questions rather than just closing old ones — the scene should end in motion, with something shifted. Let the current act's mood (from <story_arc>) shape the texture of this moment — a STRONG_HIT in a desperate phase still tastes of the surrounding darkness. If <director_guidance> is present, follow its direction while maintaining your creative voice.</task>"""


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
            nd.setdefault("last_location", game.current_location or "")
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
        for c in data["clocks"]:
            if "type" in c and "clock_type" not in c:
                c["clock_type"] = c.pop("type")
            # Assign clock ID if missing
            if not c.get("id"):
                max_clock_num += 1
                c["id"] = f"clock_{max_clock_num}"
            # Normalize fired: extractor omits the field; None serializes to JSON null
            # which confuses the "fired" not in clock backfill check in load_game.
            if c.get("fired") is None:
                c["fired"] = False
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

            # Auto-create NPC stub if not found (safety net when <new_npcs> was omitted)
            if not npc and u["npc_id"] and u["npc_id"] not in ("world", "player", ""):
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
                        "last_location": game.current_location or "",
                    }
                    game.npcs.append(npc)
                    log(f"[NPC] Auto-created stub NPC from memory_update: {npc_name}")

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
            if (npc
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
    "time_of_day", "location_history",
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
]

def save_game(game: GameState, username: str, chat_messages: list = None,
              name: str = "autosave") -> Path:
    """Save game state and chat history. UI layer must provide username and chat_messages."""
    save_dir = _get_save_dir(username)
    save_dir.mkdir(parents=True, exist_ok=True)
    # --- Version history: read existing save to carry forward ---
    # New games (scene_count ≤ 1 AND chapter 1) always start a fresh version history —
    # they must not inherit the history of a previous game stored in the same slot.
    # Chapter transitions also reset scene_count to 1 but chapter_number > 1 — excluded.
    version_history = []
    path = save_dir / f"{name}.json"
    is_new_game = (getattr(game, "scene_count", 0) <= 1
                   and getattr(game, "chapter_number", 1) <= 1)
    if path.exists() and not is_new_game:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            version_history = existing.get("version_history", [])
            # Backfill: if old save had no version_history but had engine_version
            if not version_history and existing.get("engine_version"):
                version_history = [existing["engine_version"]]
        except Exception:
            pass
    # Append current version only if it differs from last entry
    if not version_history or version_history[-1] != VERSION:
        version_history.append(VERSION)
    data = {"saved_at": datetime.now().isoformat()}
    data["engine_version"] = VERSION
    data["version_history"] = version_history
    data.update({k: getattr(game, k) for k in SAVE_FIELDS})
    # last_turn_snapshot may contain a RollResult dataclass — serialize to plain dict
    if data.get("last_turn_snapshot") and data["last_turn_snapshot"].get("roll") is not None:
        import dataclasses
        data["last_turn_snapshot"] = dict(data["last_turn_snapshot"])
        data["last_turn_snapshot"]["roll"] = dataclasses.asdict(data["last_turn_snapshot"]["roll"])
    # Chat history for visual restoration (strip audio binary data and transient recaps)
    raw_messages = chat_messages or []
    data["chat_messages"] = [
        {k: v for k, v in msg.items() if k not in ("audio_bytes", "audio_format")}
        for msg in raw_messages
        if not msg.get("recap")
    ]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"[Save] Game saved: {username}/{name} (Scene {game.scene_count}, {len(data['chat_messages'])} chat msgs)")
    return path


def load_game(username: str, name: str = "autosave") -> tuple[Optional[GameState], list]:
    """Load game state and chat history. Returns (game, chat_messages)."""
    save_dir = _get_save_dir(username)
    path = save_dir / f"{name}.json"
    if not path.exists():
        log(f"[Load] Save not found: {username}/{name}", level="warning")
        return None, []
    data = json.loads(path.read_text(encoding="utf-8"))
    game = GameState()
    for k, v in data.items():
        if k not in ("saved_at", "chat_messages") and hasattr(game, k):
            setattr(game, k, v)
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
    # Backward compatibility: repair clock owners that still carry a stale NPC name.
    # _merge_npc_identity now updates owners live, but saves made before this fix
    # may have owner = old name (now an alias). Build normalized alias → canonical map.
    _norm_alias_to_canonical: dict[str, str] = {}
    for npc in game.npcs:
        for alias in npc.get("aliases", []):
            norm = _normalize_for_match(alias)
            if norm not in _norm_alias_to_canonical:
                _norm_alias_to_canonical[norm] = npc["name"]
    for clock in game.clocks:
        owner = clock.get("owner", "")
        if owner and owner not in ("", "world"):
            canonical = _norm_alias_to_canonical.get(_normalize_for_match(owner))
            if canonical and canonical != owner:
                log(f"[Load] Clock owner repaired: '{clock["name"]}' '{owner}' → '{canonical}'")
                clock["owner"] = canonical
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


def get_save_info(username: str, name: str) -> dict | None:
    """Read save metadata without loading full game state.
    Returns dict with player_name, scene_count, saved_at, chapter_number or None."""
    path = _get_save_dir(username) / f"{name}.json"
    if not path.exists():
        return None
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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
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
        backstory=creation_data.get("custom_desc", ""),
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

    # Opening-scene NPCs are extracted FROM the narration — they are introduced
    # by definition. _process_game_data defaults to introduced=False (legacy),
    # but parse_narrator_response step 10 can't check them because game.npcs
    # was empty when it ran. Mark them now so the sidebar shows them immediately.
    for npc in game.npcs:
        npc["introduced"] = True

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
    ) or "(keine)"

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
        data = json.loads(response.content[0].text)
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
{story}</scene>
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
    game.location_history = []  # Reset -- new chapter, fresh location tracking
    game.director_guidance = {}  # Reset -- old pacing/guidance shouldn't carry over

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
        # Skip if extractor already created an NPC with this name
        if _normalize_for_match(old_npc["name"]) in new_npc_names:
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
            # Transfer historical data from returning NPC into hollow extractor NPC.
            # Memories: returning NPC has the full history; extractor NPC has none.
            if old_npc.get("memory"):
                alias_hit["memory"] = old_npc["memory"]
            # Bond: take the higher value
            alias_hit["bond"] = max(alias_hit.get("bond", 0), old_npc.get("bond", 0))
            # Reflection state: preserve chapter-1 rhythm for Director
            alias_hit["importance_accumulator"] = (
                alias_hit.get("importance_accumulator", 0)
                + old_npc.get("importance_accumulator", 0)
            )
            alias_hit["last_reflection_scene"] = max(
                alias_hit.get("last_reflection_scene", 0),
                old_npc.get("last_reflection_scene", 0),
            )
            # Secrets: keep extractor's fresh chapter-2 secrets if present, else inherit
            if not alias_hit.get("secrets") and old_npc.get("secrets"):
                alias_hit["secrets"] = old_npc["secrets"]
            # Merge any remaining aliases from the returning NPC
            alias_hit.setdefault("aliases", [])
            existing_alias_norms = {_normalize_for_match(a) for a in alias_hit["aliases"]}
            canonical_norm = _normalize_for_match(alias_hit["name"])
            for alias in old_npc.get("aliases", []):
                a_norm = _normalize_for_match(alias)
                if a_norm not in existing_alias_norms and a_norm != canonical_norm:
                    alias_hit["aliases"].append(alias)
                    existing_alias_norms.add(a_norm)
            # Status stays active (NPC appeared in chapter opening)
            alias_hit["introduced"] = True
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
    log(f"[Turn] Scene {game.scene_count + 1} | Player: {player_message[:100]}")

    # Housekeeping: remove fired clocks that are old enough to no longer
    # provide useful narrator context (keeps prompt lean across long chapters)
    _purge_old_fired_clocks(game)

    # Snapshot BEFORE any mutation — used by ## correction flow and burn
    game.last_turn_snapshot = _build_turn_snapshot(game)
    game.last_turn_snapshot["player_input"] = player_message

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
        prompt = build_dialog_prompt(game, brain, player_words=player_message,
                                     chaos_interrupt=chaos_interrupt,
                                     activated_npcs=activated_npcs,
                                     mentioned_npcs=mentioned_npcs,
                                     config=config)
        raw = call_narrator(client, prompt, game, config)
        narration = parse_narrator_response(game, raw)
        if game.last_turn_snapshot is not None:
            game.last_turn_snapshot["narration"] = narration
        metadata = call_narrator_metadata(client, narration, game, config)
        _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids)
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
        # Autonomous clock ticks — world moves forward independent of player rolls
        auto_clock_events = _tick_autonomous_clocks(game)
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
        else:
            log(f"[Director] Skipped (no trigger at scene {game.scene_count})")

        # Note: UI layer handles save_game()
        return game, narration, None, None, director_ctx

    # Action
    game.scene_count += 1
    stat_name = brain.get("stat", "wits")
    roll = roll_action(stat_name, game.get_stat(stat_name), brain.get("move", "face_danger"))
    log(f"[Roll] {roll.move} ({roll.stat_name}={roll.stat_value}): "
        f"{roll.d1}+{roll.d2}+{roll.stat_value}={roll.action_score} "
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
    npc_agency = check_npc_agency(game)
    prompt = build_action_prompt(game, brain, roll, consequences, clock_events, npc_agency,
                                player_words=player_message, chaos_interrupt=chaos_interrupt,
                                activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                config=config)
    raw = call_narrator(client, prompt, game, config)
    narration = parse_narrator_response(game, raw)
    if game.last_turn_snapshot is not None:
        game.last_turn_snapshot["narration"] = narration
    metadata = call_narrator_metadata(client, narration, game, config)
    _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids)
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
                             "npc_activation": npc_activation_debug})
    if len(game.session_log) > MAX_SESSION_LOG:
        game.session_log = game.session_log[-MAX_SESSION_LOG:]
    # Autonomous clock ticks — world moves forward independent of player rolls
    auto_clock_events = _tick_autonomous_clocks(game)
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
    final_end = final_act.get("scene_range", [14, 20])[1]

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
            sr = act.get("scene_range", [1, 20])
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
        f"d1={roll.d1}+d2={roll.d2} vs c1={roll.c1}/c2={roll.c2})"
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
        result = json.loads(response.content[0].text)
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
    import uuid
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
                new_name = op_dict.get("split_name") or "Unknown"
                new_desc = op_dict.get("split_description") or ""
                new_id = f"npc_{uuid.uuid4().hex[:8]}"
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
                }
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
                target["memory"].extend(source.get("memory", []))
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
                game.npcs = [n for n in game.npcs if n["id"] != source["id"]]
                log(f"[Correction] npc_merge: '{source['name']}' absorbed into '{target['name']}'")

        elif op == "location_edit":
            if op_dict.get("value"):
                game.current_location = op_dict["value"]
                log(f"[Correction] location → {game.current_location}")

        elif op == "scene_context":
            if op_dict.get("value"):
                game.current_scene_context = op_dict["value"]
                log(f"[Correction] scene_context updated")

        elif op == "time_edit":
            if op_dict.get("value"):
                game.time_of_day = op_dict["value"]
                log(f"[Correction] time_of_day → {game.time_of_day}")

        elif op == "backstory_append":
            if op_dict.get("value"):
                sep = "\n" if game.backstory else ""
                game.backstory += sep + op_dict["value"]
                log(f"[Correction] backstory appended")


def _restore_from_snapshot(game: GameState, snap: dict) -> None:
    """Fully restore all turn-mutable GameState fields from a last_turn_snapshot.
    Used by the ## correction flow for input_misread corrections."""
    game.health = snap["health"]
    game.spirit = snap["spirit"]
    game.supply = snap["supply"]
    game.momentum = snap.get("momentum", game.momentum)
    game.max_momentum = snap.get("max_momentum", game.max_momentum)
    game.scene_count = snap.get("scene_count", game.scene_count)
    game.chaos_factor = snap.get("chaos_factor", game.chaos_factor)
    game.crisis_mode = snap.get("crisis_mode", game.crisis_mode)
    game.game_over = snap.get("game_over", game.game_over)
    game.epilogue_shown = snap.get("epilogue_shown", game.epilogue_shown)
    game.epilogue_dismissed = snap.get("epilogue_dismissed", game.epilogue_dismissed)
    game.current_location = snap.get("current_location", game.current_location)
    game.current_scene_context = snap.get("current_scene_context", game.current_scene_context)
    game.time_of_day = snap.get("time_of_day", game.time_of_day)
    game.location_history = list(snap.get("location_history", game.location_history))
    game.director_guidance = copy.deepcopy(snap.get("director_guidance", game.director_guidance))
    game.scene_intensity_history = list(snap.get("scene_intensity_history", game.scene_intensity_history))
    if "npcs" in snap:
        game.npcs = copy.deepcopy(snap["npcs"])
    if "clocks" in snap:
        game.clocks = copy.deepcopy(snap["clocks"])
    # Restore blueprint sub-fields that may have mutated during the turn:
    # revelation marks, act transitions, and story_complete flag.
    if game.story_blueprint is not None:
        if "bp_revealed" in snap:
            game.story_blueprint["revealed"] = list(snap["bp_revealed"])
        if "bp_triggered_transitions" in snap:
            game.story_blueprint["triggered_transitions"] = list(snap["bp_triggered_transitions"])
        if "bp_story_complete" in snap:
            if snap["bp_story_complete"]:
                game.story_blueprint["story_complete"] = True
            else:
                game.story_blueprint.pop("story_complete", None)
    # Trim session_log and narration_history back by one entry
    # (the turn being corrected will be re-appended by the re-run)
    if snap.get("session_log_tail") is not None and game.session_log:
        game.session_log.pop()
    if snap.get("narration_history_tail") is not None and game.narration_history:
        game.narration_history.pop()
    log("[Correction] State fully restored from snapshot")


def process_correction(client: anthropic.Anthropic, game: GameState,
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

    # Step 1: Analyse the correction
    analysis = call_correction_brain(client, game, correction_text, _cfg)
    source = analysis["correction_source"]

    # Step 2a: input_misread → full state restore, then re-run Brain + optional Roll
    if source == "input_misread":
        _restore_from_snapshot(game, snap)
        corrected_input = analysis.get("corrected_input") or snap.get("player_input", "")

        # Re-run Brain with the corrected input interpretation
        brain = call_brain(client, game, corrected_input, _cfg)
        _apply_brain_location_time(game, brain)

        if analysis.get("reroll_needed") and brain.get("stat", "none") != "none":
            # Full action path with new roll
            game.scene_count += 1
            stat_name = brain.get("stat", "wits")
            roll = roll_action(stat_name, game.get_stat(stat_name), brain.get("move", "face_danger"))
            log(f"[Roll] {roll.move} ({roll.stat_name}={roll.stat_value}): "
                f"{roll.d1}+{roll.d2}+{roll.stat_value}={roll.action_score} "
                f"vs [{roll.c1},{roll.c2}] \u2192 {roll.result} (correction re-roll)")
            consequences, clock_events = apply_consequences(game, roll, brain)
            npc_agency = check_npc_agency(game)
            activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(game, brain, corrected_input)
            prompt = build_action_prompt(game, brain, roll, consequences, clock_events, npc_agency,
                                         player_words=corrected_input, config=_cfg,
                                         activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs)
        else:
            # Dialog / intent-only path — no new roll
            roll = None
            game.scene_count += 1
            activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(game, brain, corrected_input)
            prompt = build_dialog_prompt(game, brain, player_words=corrected_input,
                                         activated_npcs=activated_npcs,
                                         mentioned_npcs=mentioned_npcs, config=_cfg)

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
            npc_agency = check_npc_agency(game)
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
    _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids)

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

    log(f"[Correction] Complete: source={source}, rewrite done")
    return game, narration, director_ctx


def process_momentum_burn(client: anthropic.Anthropic, game: GameState,
                          old_roll: RollResult, new_result: str,
                          brain_data: dict, player_words: str = "",
                          config: Optional[EngineConfig] = None,
                          pre_snapshot: Optional[dict] = None,
                          chaos_interrupt: Optional[str] = None) -> tuple[GameState, str]:
    """Re-narrate a scene after momentum burn upgrades the result.
    Fully restores game state from pre_snapshot before applying new consequences."""
    # Remove NPC memories from THIS scene (they came from the pre-burn narration
    # and will be replaced by the new narration's memory updates)
    current_scene = game.scene_count
    for npc in game.npcs:
        if npc.get("memory"):
            npc["memory"] = [
                m for m in npc["memory"]
                if not (isinstance(m, dict) and m.get("scene") == current_scene)
            ]

    # --- Restore state from pre-consequence snapshot ---
    # Full restoration using last_turn_snapshot (authoritative, taken before any mutations)
    game.health = pre_snapshot["health"]
    game.spirit = pre_snapshot["spirit"]
    game.supply = pre_snapshot["supply"]
    game.momentum = pre_snapshot["momentum"]
    game.max_momentum = pre_snapshot["max_momentum"]
    game.chaos_factor = pre_snapshot["chaos_factor"]
    game.crisis_mode = pre_snapshot["crisis_mode"]
    game.game_over = pre_snapshot["game_over"]
    game.epilogue_shown = pre_snapshot["epilogue_shown"]
    game.epilogue_dismissed = pre_snapshot["epilogue_dismissed"]
    game.current_location = pre_snapshot["current_location"]
    game.current_scene_context = pre_snapshot["current_scene_context"]
    game.time_of_day = pre_snapshot["time_of_day"]
    game.location_history = list(pre_snapshot["location_history"])
    game.director_guidance = copy.deepcopy(pre_snapshot["director_guidance"])
    # Restore full NPC state — removes any NPCs introduced in MISS narration
    game.npcs = copy.deepcopy(pre_snapshot["npcs"])
    game.clocks = copy.deepcopy(pre_snapshot["clocks"])
    game.scene_count = pre_snapshot["scene_count"]
    game.scene_intensity_history = list(pre_snapshot["scene_intensity_history"])
    # Restore blueprint sub-fields (revelation marks, act transitions, story_complete)
    if game.story_blueprint is not None:
        game.story_blueprint["revealed"] = list(pre_snapshot["bp_revealed"])
        game.story_blueprint["triggered_transitions"] = list(pre_snapshot["bp_triggered_transitions"])
        if pre_snapshot["bp_story_complete"]:
            game.story_blueprint["story_complete"] = True
        else:
            game.story_blueprint.pop("story_complete", None)
    log(f"[Burn] Fully restored state from snapshot: H{game.health} Sp{game.spirit} Su{game.supply} Chaos{game.chaos_factor}")

    # Create upgraded roll
    upgraded = RollResult(old_roll.d1, old_roll.d2, old_roll.c1, old_roll.c2,
                          old_roll.stat_name, old_roll.stat_value, old_roll.action_score,
                          new_result, old_roll.move, old_roll.match)

    # Apply new consequences
    consequences, clock_events = apply_consequences(game, upgraded, brain_data)
    # Re-run NPC activation for the re-narrated scene
    activated_npcs, mentioned_npcs, _ = activate_npcs_for_prompt(game, brain_data, player_words)
    prompt = build_action_prompt(game, brain_data, upgraded, consequences, clock_events, [],
                                player_words=player_words, chaos_interrupt=chaos_interrupt,
                                activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                config=config)
    prompt = prompt.replace('<task>', '<momentum_burn>Character digs deep, turns the tide.</momentum_burn>\n<task>')

    raw = call_narrator(client, prompt, game, config)
    narration = parse_narrator_response(game, raw)
    metadata = call_narrator_metadata(client, narration, game, config)
    _scene_present_ids = {n["id"] for n in activated_npcs} | {n["id"] for n in mentioned_npcs}
    _apply_narrator_metadata(game, metadata, scene_present_ids=_scene_present_ids)

    # Update chaos after burn (new result counts)
    update_chaos_factor(game, new_result)

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

    # Note: UI layer handles save_game()
    return game, narration

