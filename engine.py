#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Tales - Narrative Solo RPG Engine 
========================================
Core Module (Framework-Independent)
"""

import json
import re
import random
import logging
import sys
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

# ===============================================================
# CONFIGURATION
# ===============================================================

BRAIN_MODEL = "claude-haiku-4-5-20251001"
NARRATOR_MODEL = "claude-sonnet-4-5-20250929"
_SCRIPT_DIR = Path(__file__).resolve().parent
USERS_DIR = _SCRIPT_DIR / "users"
USERS_DIR.mkdir(exist_ok=True)
GLOBAL_CONFIG_FILE = _SCRIPT_DIR / "config.json"
LOG_DIR = _SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# --- Tuning constants ---
STAT_TARGET_SUM = 7                # Character stats must total this
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
DIRECTOR_MODEL = BRAIN_MODEL       # Director uses same model as Brain (Haiku)

# --- Importance scoring: emotional_weight → importance (1-10) ---
IMPORTANCE_MAP = {
    # Low importance (routine interactions)
    "neutral": 2, "polite": 2, "casual": 2, "indifferent": 2,
    "formal": 2, "calm": 2, "bored": 2,
    # Medium importance (notable reactions)
    "amused": 3, "curious": 3, "interested": 3, "pleased": 3,
    "annoyed": 4, "wary": 4, "uneasy": 4, "concerned": 4,
    "frustrated": 4, "confused": 4, "nervous": 4,
    # High importance (significant emotional reactions)
    "grateful": 5, "impressed": 5, "suspicious": 5, "angry": 5,
    "disappointed": 5, "protective": 5, "trusting": 5,
    "hopeful": 5, "jealous": 5, "guilty": 5,
    # Very high importance (relationship-defining moments)
    "awed": 7, "devoted": 7, "terrified": 7, "furious": 7,
    "heartbroken": 7, "inspired": 7, "grief": 7,
    "defiant": 6, "loyal": 6, "conflicted": 6,
    # Critical importance (life-changing events)
    "betrayed": 9, "transformed": 10, "devastated": 9, "euphoric": 8,
    "sworn": 8, "sacrificial": 10, "reborn": 10,
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


def _find_npc(game, npc_ref: str) -> Optional[dict]:
    """Find an NPC by ID, name, alias, or substring match.
    Search order: exact ID → exact name → exact alias → substring name → substring alias.
    Brain sometimes returns a name string instead of an ID like 'npc_1'."""
    if not npc_ref:
        return None
    # 1. Try exact ID match
    for n in game.npcs:
        if n.get("id") == npc_ref:
            return n
    # 2. Try exact name match (case-insensitive)
    ref_lower = npc_ref.lower().strip()
    for n in game.npcs:
        if n.get("name", "").lower().strip() == ref_lower:
            return n
    # 3. Try exact alias match (case-insensitive)
    for n in game.npcs:
        for alias in n.get("aliases", []):
            if alias.lower().strip() == ref_lower:
                return n
    # 4. Substring fallback — ref is part of name or name is part of ref
    #    (handles "Krahe" matching "Hauptmann Krahe" and vice versa)
    if len(ref_lower) >= 4:  # Minimum length to avoid false positives (e.g. "Li" matching "Elisa")
        best_match = None
        best_score = 0
        for n in game.npcs:
            name_lower = n.get("name", "").lower().strip()
            if ref_lower in name_lower or name_lower in ref_lower:
                score = min(len(ref_lower), len(name_lower))  # Longer overlap = better
                if score > best_score:
                    best_score = score
                    best_match = n
                continue
            # Also check aliases for substring
            for alias in n.get("aliases", []):
                alias_lower = alias.lower().strip()
                if ref_lower in alias_lower or alias_lower in ref_lower:
                    score = min(len(ref_lower), len(alias_lower))
                    if score > best_score:
                        best_score = score
                        best_match = n
        if best_match:
            log(f"[NPC] Fuzzy matched '{npc_ref}' → '{best_match['name']}' (score={best_score})")
            return best_match
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


def _fuzzy_match_existing_npc(game, new_name: str) -> Optional[dict]:
    """Check if a 'new' NPC name fuzzy-matches an existing NPC.
    Handles identity reveals like 'Unbekannter Söldner' → 'Hauptmann Krahe'.
    Returns the matching NPC dict or None."""
    if not new_name or len(new_name.strip()) < 3:
        return None
    new_lower = new_name.lower().strip()
    # Extract individual words for word-overlap matching
    new_words = set(new_lower.split())

    best_match = None
    best_score = 0

    for n in game.npcs:
        name_lower = n.get("name", "").lower().strip()
        # Skip exact matches (handled elsewhere)
        if name_lower == new_lower:
            continue

        # 1. Substring check: "Krahe" ⊂ "Hauptmann Krahe" or vice versa
        if new_lower in name_lower or name_lower in new_lower:
            score = min(len(new_lower), len(name_lower))
            if score >= 3 and score > best_score:
                best_score = score
                best_match = n
            continue

        # 2. Check aliases for substring match
        for alias in n.get("aliases", []):
            alias_lower = alias.lower().strip()
            if alias_lower == new_lower:
                return n  # Exact alias match — definite
            if new_lower in alias_lower or alias_lower in new_lower:
                score = min(len(new_lower), len(alias_lower))
                if score >= 3 and score > best_score:
                    best_score = score
                    best_match = n

        # 3. Significant word overlap (e.g. "Krahe" appears in "Hauptmann Krahe")
        name_words = set(name_lower.split())
        alias_words = set()
        for alias in n.get("aliases", []):
            alias_words.update(alias.lower().strip().split())
        all_words = name_words | alias_words
        overlap = new_words & all_words
        # Require at least one significant word (3+ chars) to overlap
        significant_overlap = [w for w in overlap if len(w) >= 3]
        if significant_overlap:
            score = sum(len(w) for w in significant_overlap)
            if score > best_score:
                best_score = score
                best_match = n

    return best_match


def _merge_npc_identity(existing: dict, new_name: str, new_desc: str = ""):
    """Merge a new identity into an existing NPC (identity reveal).
    Old name becomes an alias, new name becomes primary."""
    old_name = existing["name"]
    existing.setdefault("aliases", [])
    if old_name and old_name not in existing["aliases"]:
        existing["aliases"].append(old_name)
    existing["name"] = new_name.strip()
    if new_desc and not existing.get("description"):
        existing["description"] = new_desc
    # Ensure active status
    if existing.get("status") == "background":
        _reactivate_npc(existing, reason=f"identity revealed as {new_name}")
    log(f"[NPC] Identity merged: '{old_name}' → '{new_name}' (aliases: {existing['aliases']})")


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
            new_name = r["new_name"].strip()
            # Don't rename to player character
            if new_name.lower() == game.player_name.lower().strip():
                continue
            _merge_npc_identity(npc, new_name, r.get("description", ""))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Failed to process NPC renames: {e}", level="warning")


def _process_new_npcs(game, json_text: str):
    """Add newly discovered NPCs from narrator <new_npcs> metadata."""
    try:
        new_npcs = json.loads(json_text.strip())
        if not isinstance(new_npcs, list):
            return

        player_lower = game.player_name.lower().strip()
        existing_names = {n["name"].lower().strip() for n in game.npcs}

        for nd in new_npcs:
            if not isinstance(nd, dict) or not nd.get("name"):
                continue
            name_lower = nd["name"].lower().strip()

            # Skip player character
            if name_lower == player_lower:
                continue

            # Check if this NPC already exists (exact name match, possibly background)
            if name_lower in existing_names:
                # Reactivate background NPCs that reappear in narration
                existing = next((n for n in game.npcs
                                 if n["name"].lower().strip() == name_lower), None)
                if existing and existing.get("status") == "background":
                    _reactivate_npc(existing, reason="reappeared in new_npcs")
                continue

            # Fuzzy match: check if this "new" NPC is actually a known NPC
            # under a different name (identity reveal, nickname, etc.)
            fuzzy_hit = _fuzzy_match_existing_npc(game, nd["name"])
            if fuzzy_hit:
                _merge_npc_identity(fuzzy_hit, nd["name"], nd.get("description", ""))
                existing_names.add(name_lower)
                continue

            # Assign ID
            npc_id, _ = _next_npc_id(game)

            # Build full NPC entry with defaults
            npc = {
                "id": npc_id,
                "name": nd["name"].strip(),
                "description": nd.get("description", ""),
                "agenda": "",
                "instinct": "",
                "secrets": [],
                "disposition": _normalize_disposition(nd.get("disposition", "neutral")),
                "bond": 0,
                "bond_max": 4,
                "status": "active",
                "memory": [],
                "introduced": True,  # They appeared in narration
                "aliases": [],
                "keywords": [],
                "importance_accumulator": 0,
                "last_reflection_scene": 0,
            }
            npc["keywords"] = _auto_generate_keywords(npc)

            game.npcs.append(npc)
            existing_names.add(name_lower)
            log(f"[NPC] New mid-game NPC: {npc['name']} ({npc_id}, {npc['disposition']})")

        # Check if active NPC count exceeds soft limit
        _retire_distant_npcs(game)

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Failed to process new NPCs: {e}", level="warning")


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


def _reactivate_npc(npc: dict, reason: str = ""):
    """Promote a background NPC back to active status."""
    if npc.get("status") == "background":
        npc["status"] = "active"
        log(f"[NPC] Reactivated: {npc['name']} (reason: {reason})")


# ===============================================================
# NPC MEMORY SYSTEM — Importance, Retrieval, Consolidation
# ===============================================================

def score_importance(emotional_weight: str, event_text: str = "") -> int:
    """Score the importance of a memory entry (1-10).
    Uses emotional_weight as primary signal, with keyword boosts from event text."""
    base = IMPORTANCE_MAP.get(emotional_weight.lower().strip(), 3)
    # Keyword boost from event text
    if event_text:
        event_lower = event_text.lower()
        for min_score, keywords in IMPORTANCE_BOOST_KEYWORDS.items():
            if any(kw in event_lower for kw in keywords):
                base = max(base, min_score)
                break
    return min(10, base)


def retrieve_memories(npc: dict, context_text: str = "", max_count: int = 5,
                      current_scene: int = 0) -> list[dict]:
    """Retrieve the most relevant memories for an NPC using weighted scoring.
    Score = 0.40 × recency + 0.35 × importance + 0.25 × relevance
    Always includes at least 1 reflection if available."""
    memories = npc.get("memory", [])
    if not memories:
        return []

    # Separate reflections and observations
    reflections = [m for m in memories if m.get("type") == "reflection"]
    observations = [m for m in memories if m.get("type") != "reflection"]

    # Context keywords for relevance scoring
    context_words = set()
    if context_text:
        context_words = {w.lower() for w in context_text.split() if len(w) >= 3}
    # Also use NPC keywords for relevance
    npc_keywords = {kw.lower() for kw in npc.get("keywords", [])}

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

        # Relevance: keyword overlap with context
        relevance = 0.0
        if context_words:
            event_words = {w.lower() for w in mem.get("event", "").split() if len(w) >= 3}
            overlap = context_words & (event_words | npc_keywords)
            if overlap:
                relevance = min(1.0, len(overlap) / max(3, len(context_words)) * 2)

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


def _auto_generate_keywords(npc: dict) -> list[str]:
    """Auto-generate activation keywords for an NPC from their data.
    Includes name parts, aliases, description keywords, and agenda keywords."""
    keywords = set()

    # Name parts (split compound names)
    name = npc.get("name", "")
    for part in name.split():
        if len(part) >= 3:
            keywords.add(part.lower())
    keywords.add(name.lower())

    # Aliases
    for alias in npc.get("aliases", []):
        keywords.add(alias.lower())
        for part in alias.split():
            if len(part) >= 3:
                keywords.add(part.lower())

    # Key nouns from description (simple extraction: capitalize words, role words)
    desc = npc.get("description", "")
    if desc:
        # Extract likely-important words (capitalized, role-like, location-like)
        for word in desc.split():
            clean = word.strip(".,;:!?\"'()-").lower()
            if len(clean) >= 4 and clean[0].isupper() if word[0:1].isupper() else False:
                keywords.add(clean)

    # Agenda keywords
    agenda = npc.get("agenda", "")
    if agenda:
        for word in agenda.split():
            clean = word.strip(".,;:!?\"'()-").lower()
            if len(clean) >= 5:
                keywords.add(clean)

    return list(keywords)[:20]  # Cap at 20 keywords


def _ensure_npc_memory_fields(npc: dict):
    """Ensure NPC has all memory system fields (migration + new NPC creation)."""
    npc.setdefault("memory", [])
    npc.setdefault("keywords", [])
    npc.setdefault("importance_accumulator", 0)
    npc.setdefault("last_reflection_scene", 0)
    # Auto-generate keywords if missing
    if not npc["keywords"]:
        npc["keywords"] = _auto_generate_keywords(npc)
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
# NPC KEYWORD-BASED CONTEXT ACTIVATION
# ===============================================================

def activate_npcs_for_prompt(game, brain: dict, player_input: str) -> tuple[list[dict], list[dict]]:
    """Decide which NPCs get full context vs name-only mention in narrator prompt.
    Returns (activated_npcs, mentioned_npcs).
    activated = full context (memories, secrets, agenda)
    mentioned = name + disposition only"""
    target_id = brain.get("target_npc")

    # Build scan text from all available context
    scan_parts = [
        player_input,
        brain.get("player_intent", ""),
        brain.get("approach", ""),
        game.current_scene_context,
        game.current_location,
    ]
    # Last 2 session log entries
    for s in game.session_log[-2:]:
        scan_parts.append(s.get("summary", ""))
    scan_text = " ".join(scan_parts).lower()
    scan_words = {w for w in scan_text.split() if len(w) >= 3}

    activated = []
    mentioned = []

    for npc in game.npcs:
        if npc.get("status") not in ("active", "background"):
            continue

        score = 0.0
        npc_name_lower = npc.get("name", "").lower()

        # 1. Direct target from Brain (highest priority)
        if target_id and (npc.get("id") == target_id or npc_name_lower == target_id.lower()):
            score += 1.0

        # 2. Name mentioned in scan text
        if npc_name_lower in scan_text:
            score += 0.8
        else:
            # Check name parts (e.g. "Borin" in "Ich frage Borin")
            for part in npc_name_lower.split():
                if len(part) >= 3 and part in scan_text:
                    score += 0.6
                    break

        # 3. Alias mentioned
        for alias in npc.get("aliases", []):
            if alias.lower() in scan_text:
                score += 0.7
                break

        # 4. Keyword overlap
        npc_kws = {kw.lower() for kw in npc.get("keywords", [])}
        kw_overlap = scan_words & npc_kws
        if kw_overlap:
            score += min(0.4, len(kw_overlap) * 0.15)

        # 5. Location match
        npc_desc = (npc.get("description", "") + " " + npc.get("agenda", "")).lower()
        if game.current_location and game.current_location.lower() in npc_desc:
            score += 0.3

        # 6. Recent interaction bonus
        recent_scenes = [m.get("scene") or 0 for m in npc.get("memory", [])[-3:] if isinstance(m, dict)]
        if recent_scenes and max(recent_scenes) >= game.scene_count - 2:
            score += 0.2

        # Classify
        if score >= NPC_ACTIVATION_THRESHOLD:
            activated.append(npc)
            # Auto-reactivate background NPCs that are contextually relevant
            if npc.get("status") == "background":
                _reactivate_npc(npc, reason=f"keyword activation (score={score:.2f})")
        elif score >= NPC_MENTION_THRESHOLD:
            mentioned.append(npc)

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

    return activated, mentioned


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
    # v5.10: Backstory (canon past, preserved raw player input)
    backstory: str = ""        # Raw player-authored backstory — canon facts, NOT plot seeds
    # v5.11: Director guidance (stored between turns)
    director_guidance: dict = field(default_factory=dict)  # Last DirectorGuidance output

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


def update_location(game: GameState, new_location: str):
    """Update current location and maintain location history."""
    if not new_location:
        return
    # AI sometimes returns underscores instead of spaces in location names
    new_location = new_location.replace("_", " ").strip()
    if not new_location or new_location == game.current_location:
        return
    if game.current_location:
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


def record_scene_intensity(game: GameState, scene_type: str):
    """Record a scene's intensity type for pacing analysis.
    scene_type: 'action', 'breather', or 'interrupt'
    """
    game.scene_intensity_history.append(scene_type)
    if len(game.scene_intensity_history) > 10:
        game.scene_intensity_history = game.scene_intensity_history[-10:]


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
                    consequences.append(f'{target["name"]} bond -1')
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
                    clock_events.append({"clock": clock["name"], "trigger": clock["trigger_description"]})
                break

    elif roll.result == "WEAK_HIT":
        game.momentum = min(game.max_momentum, game.momentum + 1)
        if roll.move in {"make_connection"} and target:
            target["bond"] = min(target.get("bond_max", 4), target["bond"] + 1)

    else:  # STRONG_HIT
        effect = brain.get("effect", "standard")
        mom_gain = 3 if effect == "great" else 2
        game.momentum = min(game.max_momentum, game.momentum + mom_gain)
        if roll.move in {"make_connection", "compel"} and target:
            target["bond"] = min(target.get("bond_max", 4), target["bond"] + 1)
            shifts = {"hostile": "distrustful", "distrustful": "neutral",
                      "neutral": "friendly", "friendly": "loyal"}
            target["disposition"] = shifts.get(target["disposition"], target["disposition"])

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


def can_burn_momentum(game: GameState, roll: RollResult) -> Optional[str]:
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
            for clock in game.clocks:
                if (clock["clock_type"] == "scheme" and clock.get("owner") == npc["id"]
                        and clock["filled"] < clock["segments"]):
                    clock["filled"] += 1
                    if clock["filled"] >= clock["segments"]:
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
    pending = get_pending_revelations(game)
    rev_hint = ""
    if pending:
        rev_hint = f' revelation_ready="{pending[0]["content"][:80]}"'

    ending_hint = ""
    if bp.get("story_complete"):
        endings = bp.get("possible_endings", [])
        ending_hint = f'\n<story_ending>Story has EXCEEDED its planned arc (scene {game.scene_count}). Guide toward a satisfying conclusion in the next 1-2 scenes. Possible endings: {", ".join(e["type"] for e in endings)}. Let player actions determine which ending, but actively weave toward closure.</story_ending>'
    elif act.get("approaching_end"):
        endings = bp.get("possible_endings", [])
        ending_hint = f'\n<story_ending>Story nearing conclusion. Possible endings: {", ".join(e["type"] for e in endings)}. Let player actions determine which.</story_ending>'

    structure = bp.get("structure_type", "3act")
    return f"""<story_arc structure="{structure}" act="{act['act_number']}/{act['total_acts']}" phase="{act['phase']}" progress="{act['progress']}" mood="{act.get('mood','')}"
 conflict="{bp.get('central_conflict','')}" act_goal="{act.get('goal','')}"{rev_hint}/>
{ending_hint}
"""



def _api_create_with_retry(client: anthropic.Anthropic, max_retries: int = 2, **kwargs):
    """Wrapper around client.messages.create with retry on transient API errors.
    Handles rate limits (429), server errors (500/502/503), and overloaded (529)
    with exponential backoff. JSON parsing retries remain in callers."""
    import time as _time
    for attempt in range(max_retries + 1):
        try:
            return client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            if attempt < max_retries and e.status_code in (429, 500, 502, 503, 529):
                wait = 2 ** attempt
                log(f"[API] Error {e.status_code}, retry {attempt + 1}/{max_retries} in {wait}s",
                    level="warning")
                _time.sleep(wait)
                continue
            raise
        except anthropic.APIConnectionError as e:
            if attempt < max_retries:
                wait = 2 ** attempt
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
    clock_summary = "\n".join(
        f'- {c["name"]} ({c["clock_type"]}): {c["filled"]}/{c["segments"]}'
        for c in game.clocks if c["filled"] < c["segments"]
    ) or "(keine)"
    last_scenes = "\n".join(
        f'Scene {s["scene"]}: {s.get("rich_summary") or s["summary"]}' for s in game.session_log[-3:]
    ) or "(Start)"

    _cfg = config or EngineConfig()
    _brain_lang = get_narration_lang(_cfg)

    lang_rules = (f"- If the player's action implies moving to a NEW location, "
                  f"set location_change to a short location name in {_brain_lang}. null if staying.\n"
                  f"- player_intent and location_change MUST be in {_brain_lang}")

    system = """<role>RPG engine parser. Convert player input to a game move as JSON.</role>
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
<stats>edge=speed/stealth heart=empathy/charm iron=force shadow=cunning wits=knowledge</stats>
<o>
Return ONLY valid JSON, no other text:
{"type":"action","move":"name","stat":"stat","approach":"how(5w)","target_npc":"id|null","dialog_only":false,"player_intent":"1 sentence","world_addition":"element|null","position":"controlled|risky|desperate","effect":"limited|standard|great","dramatic_question":"Can/Will...?","location_change":"new location|null","time_progression":"none|short|moderate|long"}
</o>"""

    campaign_ctx = ""
    if game.campaign_history:
        campaign_ctx = f"\n<campaign>Chapter {game.chapter_number}. Previous: " + "; ".join(
            f'Ch{ch.get("chapter","?")}:{ch.get("title","")}'
            for ch in game.campaign_history[-3:]
        ) + "</campaign>"

    backstory_ctx = ""
    if getattr(game, 'backstory', ''):
        backstory_ctx = f"\n<backstory>{game.backstory}</backstory>"

    user_msg = f"""<state>
loc:{game.current_location} | ctx:{game.current_scene_context}
time:{game.time_of_day or 'unspecified'} | prev_locations:{', '.join(game.location_history[-3:]) or 'none'}
{game.player_name} H{game.health} Sp{game.spirit} Su{game.supply} M{game.momentum} chaos:{game.chaos_factor} | E{game.edge} H{game.heart} I{game.iron} Sh{game.shadow} W{game.wits}
</state>
<npcs>{npc_summary}</npcs>
<clocks>{clock_summary}</clocks>
<recent>{last_scenes}</recent>
{_story_context_block(game)}{campaign_ctx}{backstory_ctx}<input>{player_message}</input>"""

    MAX_RETRIES = 3

    for attempt in range(MAX_RETRIES):
        msgs = [{"role": "user", "content": user_msg}]
        if attempt > 0:
            # Prefill technique: start the assistant response with { to force JSON
            msgs.append({"role": "assistant", "content": "{"})
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=512, system=system,
            messages=msgs,
        )
        text = response.content[0].text
        if attempt > 0:
            text = "{" + text  # Prepend the prefill
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                result = json.loads(match.group())
                if result.get("move"):
                    # Ensure defaults for new v5.0 fields
                    result.setdefault("position", "risky")
                    result.setdefault("effect", "standard")
                    result.setdefault("dramatic_question", "")
                    result.setdefault("location_change", None)
                    result.setdefault("time_progression", "none")
                    log(f"[Brain] Result: move={result.get('move')}, pos={result.get('position')}, "
                        f"effect={result.get('effect')}, intent={result.get('player_intent','')[:60]}")
                    return result
            except json.JSONDecodeError:
                continue

    # All retries failed  --  fallback to dialog
    log("[Brain] All retries failed, falling back to dialog", level="warning")
    return {"type": "action", "move": "dialog", "dialog_only": True,
            "player_intent": player_message, "position": "risky",
            "effect": "standard", "dramatic_question": "",
            "location_change": None, "time_progression": "none"}


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
- Stats MUST total exactly 7, each 0-3, matched to archetype
- All text fields in {lang}
</rules>
<o>Return ONLY valid JSON:
{{"character_name":"str","character_concept":"1 sentence identity in {lang} (NO backstory)","setting_description":"2-3 sentences in {lang}","stats":{{"edge":int,"heart":int,"iron":int,"shadow":int,"wits":int}},"starting_location":"str","opening_situation":"1-2 sentences in {lang}"}}
</o>"""

    genre_info = creation_data.get('genre', 'dark_fantasy')
    if creation_data.get('genre_description'):
        genre_info = f"custom: {creation_data['genre_description']}"
    tone_info = creation_data.get('tone', 'dark_gritty')
    if creation_data.get('tone_description'):
        tone_info = f"custom: {creation_data['tone_description']}"
    name_override = creation_data.get('player_name', '')
    name_line = f"\ncharacter_name(USE EXACTLY): {name_override}" if name_override else ""
    user_msg = f"""genre:{genre_info} tone:{tone_info} archetype:{creation_data.get('archetype','outsider')}{name_line}
player_input: {creation_data.get('custom_desc','')}"""

    response = _api_create_with_retry(
        client, max_retries=2,
        model=BRAIN_MODEL, max_tokens=512, system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = response.content[0].text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            result = json.loads(match.group())
            # Validate stat sum
            stats = result.get("stats", {})
            stat_keys = ("edge", "heart", "iron", "shadow", "wits")
            total = sum(stats.get(k, 0) for k in stat_keys)
            if total != STAT_TARGET_SUM:
                log(f"[Setup] AI returned stats summing to {total}, normalizing to {STAT_TARGET_SUM}", level="warning")
                result["stats"] = {"edge":1,"heart":2,"iron":1,"shadow":1,"wits":2}
            else:
                # Clamp individual stats to 0-3
                for k in stat_keys:
                    stats[k] = max(0, min(3, stats.get(k, 1)))
                # Re-check sum after clamping (clamping can reduce total)
                clamped_total = sum(stats.get(k, 0) for k in stat_keys)
                if clamped_total != STAT_TARGET_SUM:
                    log(f"[Setup] Stats sum changed to {clamped_total} after clamping, using defaults", level="warning")
                    result["stats"] = {"edge":1,"heart":2,"iron":1,"shadow":1,"wits":2}
            return result
        except json.JSONDecodeError:
            pass
    return {"character_name": "Namenlos", "character_concept": "Ein Wanderer",
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
                model=BRAIN_MODEL, max_tokens=512,
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
            return response.content[0].text
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
- Include 2-3 key revelations that can be woven in at appropriate moments
- Define 2-3 possible endings (harmony, bittersweet, melancholy)
- The blueprint is a COMPASS, not rails {E['dash']} player choices override everything
- If this is a continuing campaign (campaign_chapter > 1): build on unresolved threads from previous chapters, evolve existing relationships, introduce new conflicts that connect to the established world
- All text fields in {lang}
</rules>
<o>Return ONLY valid JSON:
{{
  "central_conflict": "1 sentence core tension/theme in {lang}",
  "antagonist_force": "the opposing force or tension in {lang}",
  "acts": [
    {{"phase": "ki_introduction", "title": "act title in {lang}", "goal": "what should happen in {lang}", "scene_range": [1, 5], "mood": "atmosphere keyword"}},
    {{"phase": "sho_development", "title": "act title in {lang}", "goal": "what should happen in {lang}", "scene_range": [6, 10], "mood": "atmosphere keyword"}},
    {{"phase": "ten_twist", "title": "act title in {lang}", "goal": "what perspective shift occurs in {lang}", "scene_range": [11, 15], "mood": "atmosphere keyword"}},
    {{"phase": "ketsu_resolution", "title": "act title in {lang}", "goal": "what should happen in {lang}", "scene_range": [16, 20], "mood": "atmosphere keyword"}}
  ],
  "revelations": [
    {{"id": "rev_1", "content": "what is revealed in {lang}", "earliest_scene": 4, "dramatic_weight": "medium"}},
    {{"id": "rev_2", "content": "what is revealed in {lang}", "earliest_scene": 10, "dramatic_weight": "high"}},
    {{"id": "rev_3", "content": "perspective shift revelation in {lang}", "earliest_scene": 12, "dramatic_weight": "critical"}}
  ],
  "possible_endings": [
    {{"type": "harmony", "description": "in {lang}"}},
    {{"type": "bittersweet", "description": "in {lang}"}},
    {{"type": "melancholy", "description": "in {lang}"}}
  ]
}}</o>"""
    else:
        system = f"""<role>Story architect for an RPG campaign. Create a flexible story blueprint.</role>
{kf}{cb}<rules>
- Design a 3-act structure with ~15-20 total scenes
- Each act has a GOAL the player should work toward, not a script
- Include 2-3 key revelations that can be woven in at appropriate moments
- Define 2-3 possible endings (triumphant, bittersweet, tragic)
- The blueprint is a COMPASS, not rails {E['dash']} player choices override everything
- If this is a continuing campaign (campaign_chapter > 1): build on unresolved threads from previous chapters, evolve existing relationships, introduce new conflicts that connect to the established world
- All text fields in {lang}
</rules>
<o>Return ONLY valid JSON:
{{
  "central_conflict": "1 sentence core tension in {lang}",
  "antagonist_force": "the opposition in {lang}",
  "acts": [
    {{"phase": "setup", "title": "act title in {lang}", "goal": "what should happen in {lang}", "scene_range": [1, 6], "mood": "atmosphere keyword"}},
    {{"phase": "confrontation", "title": "act title in {lang}", "goal": "what should happen in {lang}", "scene_range": [7, 13], "mood": "atmosphere keyword"}},
    {{"phase": "climax", "title": "act title in {lang}", "goal": "what should happen in {lang}", "scene_range": [14, 20], "mood": "atmosphere keyword"}}
  ],
  "revelations": [
    {{"id": "rev_1", "content": "what is revealed in {lang}", "earliest_scene": 4, "dramatic_weight": "medium"}},
    {{"id": "rev_2", "content": "what is revealed in {lang}", "earliest_scene": 8, "dramatic_weight": "high"}},
    {{"id": "rev_3", "content": "what is revealed in {lang}", "earliest_scene": 13, "dramatic_weight": "critical"}}
  ],
  "possible_endings": [
    {{"type": "triumph", "description": "in {lang}"}},
    {{"type": "bittersweet", "description": "in {lang}"}},
    {{"type": "tragedy", "description": "in {lang}"}}
  ]
}}</o>"""

    npc_text = ", ".join(n["name"] for n in game.npcs) if game.npcs else "none yet"
    campaign_ctx = ""
    if game.campaign_history:
        campaign_ctx = f"\ncampaign_chapter:{game.chapter_number}"
        for ch in game.campaign_history[-3:]:
            campaign_ctx += f"\n  prev_chapter_{ch.get('chapter','?')}: {ch.get('summary','')}"
            threads = ch.get("unresolved_threads", [])
            if threads:
                campaign_ctx += f" [threads: {'; '.join(threads)}]"
    backstory_text = ""
    if getattr(game, 'backstory', ''):
        backstory_text = f"\nbackstory(canon past):{game.backstory}"
    user_msg = f"""genre:{game.setting_genre} tone:{game.setting_tone}
world:{game.setting_description}
character:{game.player_name} {E['dash']} {game.character_concept}
location:{game.current_location}
situation:{game.current_scene_context}
npcs:{npc_text}{campaign_ctx}{backstory_text}"""

    try:
        response = _api_create_with_retry(
            client, max_retries=2,
            model=BRAIN_MODEL, max_tokens=1000, system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            raw_json = match.group()
            try:
                blueprint = json.loads(raw_json)
            except json.JSONDecodeError:
                blueprint = json.loads(_repair_json(raw_json))
            # Validate minimal structure
            if blueprint.get("acts") and blueprint.get("central_conflict"):
                blueprint["revealed"] = []  # Track which revelations have fired
                blueprint["structure_type"] = structure_type
                return blueprint
    except (json.JSONDecodeError, Exception):
        pass

    # Fallback: minimal blueprint (English — language-neutral fallback)
    if structure_type == "kishotenketsu":
        return {
            "central_conflict": "A hidden secret waits to be discovered.",
            "antagonist_force": "The truth beneath the surface",
            "structure_type": "kishotenketsu",
            "acts": [
                {"phase": "ki_introduction", "title": "Daily Life", "goal": "Get to know the world and its people",
                 "scene_range": [1, 5], "mood": "contemplative"},
                {"phase": "sho_development", "title": "Deepening", "goal": "Deepen relationships and patterns",
                 "scene_range": [6, 10], "mood": "intimate"},
                {"phase": "ten_twist", "title": "The Twist", "goal": "An unexpected perspective changes everything",
                 "scene_range": [11, 15], "mood": "surprising"},
                {"phase": "ketsu_resolution", "title": "Reconciliation", "goal": "Unite the new with the old",
                 "scene_range": [16, 20], "mood": "reflective"},
            ],
            "revelations": [],
            "possible_endings": [
                {"type": "harmony", "description": "Peace and understanding."},
                {"type": "bittersweet", "description": "Insight at a cost."},
                {"type": "melancholy", "description": "Beautiful sadness."},
            ],
            "revealed": [],
        }
    else:
        return {
            "central_conflict": "An unknown threat grows in the shadows.",
            "antagonist_force": "Dark forces",
            "structure_type": "3act",
            "acts": [
                {"phase": "setup", "title": "First Shadows", "goal": "Find clues about the threat",
                 "scene_range": [1, 6], "mood": "mysterious"},
                {"phase": "confrontation", "title": "Into Darkness", "goal": "Confront the threat",
                 "scene_range": [7, 13], "mood": "tense"},
                {"phase": "climax", "title": "The Decision", "goal": "Decide the fate",
                 "scene_range": [14, 20], "mood": "desperate"},
            ],
            "revelations": [],
            "possible_endings": [
                {"type": "triumph", "description": "Victory over darkness."},
                {"type": "bittersweet", "description": "Victory at a high cost."},
                {"type": "tragedy", "description": "Downfall despite the struggle."},
            ],
            "revealed": [],
        }


def get_current_act(game: GameState) -> dict:
    """Determine which act the story is in based on scene count."""
    bp = game.story_blueprint
    if not bp or not bp.get("acts"):
        return {"phase": "setup", "title": "?", "goal": "?", "mood": "mysterious",
                "act_number": 1, "total_acts": 3, "progress": "early", "approaching_end": False}

    acts = bp["acts"]
    scene = game.scene_count
    current = acts[0]
    act_number = 1

    for i, act in enumerate(acts):
        sr = act.get("scene_range", [1, 20])
        if scene >= sr[0]:
            current = act
            act_number = i + 1

    # Estimate progress within act
    sr = current.get("scene_range", [1, 20])
    act_len = sr[1] - sr[0] + 1
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
    revealed = set(bp.get("revealed", []))
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
            f"{lines}\n"
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
            f"{wishes}\n"
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
        f"{backstory}\n"
        "</backstory>"
    )


def get_narrator_system(config: EngineConfig, game: Optional[GameState] = None) -> str:
    """Build narrator system prompt with configured language."""
    lang = get_narration_lang(config)
    kf = _kid_friendly_block(config)
    cb = _content_boundaries_block(game)
    bs = _backstory_block(game)
    return f"""<role>Narrator of an immersive RPG. All output in {lang}, second person singular.</role>
{kf}{cb}{bs}
<rules>
- NEVER mention dice, stats, numbers, or game mechanics
- ALL text content in metadata fields (description, event, scene_context, trigger_description) MUST be in {lang}, just like the narration itself
- MISS: concrete failure, situation worsens, NO silver linings
- WEAK_HIT: success at tangible cost
- STRONG_HIT: clean success
- NPCs act per their disposition and memories
- NEW NPCs: When a new NAMED character appears who is NOT in <npcs_present>, include them in <new_npcs> metadata. Only named, story-relevant characters {E['dash']} not unnamed crowd or background figures.
- NPC IDENTITY REVEAL: When a character already listed in <npcs_present> is revealed to have a DIFFERENT true name (unmasking, introduction by full name, alias reveal), use <npc_rename> metadata INSTEAD of <new_npcs>. This prevents duplicate NPCs. Example: a mysterious stranger reveals themselves as a known captain.
- BACKSTORY CANON: If <backstory> is present, treat it as ESTABLISHED HISTORY. People mentioned there (family, friends, rivals) are ALREADY KNOWN to the player character {E['dash']} if they appear, they recognize the player and vice versa. NEVER introduce a backstory character as a stranger or reinterpret established relationships. Backstory events ALREADY HAPPENED {E['dash']} reference them as shared memory, not new plot.
- Describe only sensory impressions, never player thoughts
- End scenes OPEN {E['dash']} no option lists, no suggested actions
- 2-4 paragraphs
- TEMPORAL CONSISTENCY: If <time> is provided, maintain that time period. Time only moves FORWARD (never backward). If you mention specific times, they must be later than any previously mentioned time. Do NOT invent specific clock times unless narratively important {E['dash']} prefer atmospheric time cues (moonlight, sunset glow, morning mist). CRITICAL: Each scene transition represents minutes to hours of in-world time, NOT days or years. Events from recent scenes just happened {E['dash']} signs don't weather, wounds are fresh, sent NPCs are still en route or just arrived. Never describe recent events or objects as aged, decayed, or long-past unless the player explicitly time-skips.
- SPATIAL CONSISTENCY: The <location> tag shows where the player currently IS. If <prev_locations> is provided, the player has LEFT those places. NEVER place the player back at a previous location unless they explicitly travel there. If the scene moves to a new location, you MUST update the location field in your metadata.
- If <story_arc> is present, steer scenes toward the act goal and mood
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
</rules>
<player_authorship>
- The PLAYER IS the character. If <player_words> is provided, these are CANONICAL.
- DIALOG: The narration MUST SHOW the player character speaking. Include their words as quoted dialog in the scene (with speech tags/body language). You may lightly polish grammar, but NEVER omit, skip, or replace what they said. The player's speech MUST appear in the text BEFORE NPCs react to it.
- ACTIONS: The narration MUST SHOW the player character performing the described action. You may add sensory detail and atmosphere, but the core action stays as stated and must be visible in the text.
- NEVER skip the player's contribution. NEVER jump straight to NPC reactions without first showing what the player character said or did.
- NEVER invent dialog the player character didn't say. NEVER replace player actions with different ones.
- NPCs REACT to what the player actually said/did, not to a reinterpretation.
</player_authorship>
<style>Terse, vivid, sensory. Show, don't tell. Player co-creates the world  --  integrate new elements seamlessly.</style>"""


def call_narrator(client: anthropic.Anthropic, prompt: str,
                  game: Optional[GameState] = None,
                  config: Optional[EngineConfig] = None) -> str:
    """Narrator call with conversation memory for style consistency."""
    log(f"[Narrator] Calling narrator (prompt: {len(prompt)} chars)")
    messages = []

    # Include last 3 narrations as conversation context
    if game and game.narration_history:
        for entry in game.narration_history[-3:]:
            messages.append({"role": "user", "content": entry.get("prompt_summary",
                             "Continue the story.")})
            messages.append({"role": "assistant", "content": entry["narration"]})

    # Current prompt
    messages.append({"role": "user", "content": prompt})

    response = _api_create_with_retry(
        client, max_retries=3,
        model=NARRATOR_MODEL, max_tokens=2500,
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

    log(f"[Narrator] Raw response ({len(raw)} chars): {raw[:500]}")
    # Log metadata tags found
    tags_found = []
    if '<game_data>' in raw: tags_found.append('game_data')
    if '<npc_rename>' in raw: tags_found.append('npc_rename')
    if '<new_npcs>' in raw: tags_found.append('new_npcs')
    if '<memory_updates>' in raw: tags_found.append('memory_updates')
    if '<scene_context>' in raw: tags_found.append('scene_context')
    if tags_found:
        log(f"[Narrator] Metadata tags found: {', '.join(tags_found)}")
    else:
        log(f"[Narrator] WARNING: No metadata tags found in response")
    return raw


def _salvage_truncated_narration(raw: str) -> str:
    """Clean up a truncated narrator response so it ends at a natural break.
    Preserves any complete metadata tags, trims prose to last full sentence."""
    # Split into prose and metadata parts
    # Find the last complete metadata tag boundary
    metadata_tags = ['<game_data>', '<npc_rename>', '<new_npcs>',
                     '<memory_updates>', '<scene_context>']
    # Check for incomplete metadata at the end (tag opened but not closed)
    for tag in metadata_tags:
        close_tag = tag.replace('<', '</')
        last_open = raw.rfind(tag)
        if last_open != -1 and raw.find(close_tag, last_open) == -1:
            # Incomplete metadata tag — remove it
            raw = raw[:last_open].rstrip()
            log(f"[Narrator] Removed incomplete {tag} from truncated response")

    # Now find the prose portion (before any metadata)
    prose_end = len(raw)
    for tag in metadata_tags:
        idx = raw.find(tag)
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

For NPC reflections: Synthesize their accumulated memories into a higher-level
insight about how they view the player character. Write in the story language.
Focus on relationship evolution, not event recaps.

Be SPECIFIC in narrator_guidance. Not "make things interesting" but
"Borin should test the player's loyalty with a dangerous request before
revealing the secret passage."

Always reply with valid JSON only. No markdown, no backticks."""


def _should_call_director(game: GameState, roll_result: str = "",
                          chaos_used: bool = False,
                          new_npcs_found: bool = False,
                          revelation_used: bool = False) -> bool:
    """Decide whether to call the Director after this scene.
    Director runs lazily — not every turn, only when valuable."""
    # 1. Significant game events → always
    if roll_result == "MISS":
        return True
    if chaos_used:
        return True
    if new_npcs_found:
        return True
    if revelation_used:
        return True

    # 2. Any NPC needs reflection
    for npc in game.npcs:
        if npc.get("_needs_reflection") and npc.get("status") in ("active", "background"):
            return True

    # 3. Act phase change
    if game.story_blueprint and game.story_blueprint.get("acts"):
        act = get_current_act(game)
        if act.get("phase") in ("climax", "resolution", "ten_twist"):
            return True

    # 4. Regular interval
    if game.scene_count > 0 and game.scene_count % DIRECTOR_INTERVAL == 0:
        return True

    return False


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
        npc_desc = n.get("description", "").replace('"', '&quot;')
        reflection_blocks.append(
            f'<reflect npc_id="{n.get("id","")}" name="{n.get("name","")}" '
            f'disposition="{n.get("disposition","")}" bond="{n.get("bond",0)}" '
            f'description="{npc_desc}">'
            f'{mem_text}</reflect>'
        )
    reflection_section = "\n".join(reflection_blocks)

    # Story arc info
    story_info = ""
    if game.story_blueprint and game.story_blueprint.get("acts"):
        act = get_current_act(game)
        bp = game.story_blueprint
        story_info = (
            f'\n<story_arc structure="{bp.get("structure_type", "3act")}" '
            f'act="{act["act_number"]}/{act["total_acts"]}" phase="{act["phase"]}" '
            f'progress="{act["progress"]}" conflict="{bp.get("central_conflict", "")}"/>'
        )

    # Active NPC overview
    npc_overview = "\n".join(
        f'- {n["name"]}({n.get("id","")}) {n["disposition"]} B{n.get("bond",0)} '
        f'status={n.get("status","active")}'
        for n in game.npcs
        if n.get("status") in ("active", "background")
    ) or "(none)"

    return f"""<scene_history>
{log_text}
</scene_history>

<latest_scene>
{latest_narration[:1000]}
</latest_scene>

<npcs>
{npc_overview}
</npcs>
{story_info}
{reflection_section}

<task>
Analyze the latest scene and provide strategic guidance in {lang}.
Reflections and narrator_guidance MUST be in {lang}.
Reply ONLY with this JSON:
{{
  "scene_summary": "2-3 sentence summary of what happened and WHY it matters (in {lang})",
  "narrator_guidance": "Specific direction for the next 1-2 scenes (in {lang})",
  "npc_guidance": {{"npc_id": "what this NPC should do/feel next (in {lang})"}},
  "pacing": "tension_rising|building|climax|breather|resolution",
  "npc_reflections": [{{"npc_id": "...", "reflection": "1-2 sentence higher-level insight (in {lang})", "tone": "emotional_weight", "updated_description": "SIDEBAR LABEL: 1 short sentence describing WHO this character IS — role, appearance, personality (in {lang}). Write like a cast list entry, NOT a scene description. NO actions, NO current posture, NO 'stands/sits/looks'. Example: 'Grumpy dwarf blacksmith with burn scars, secretly loyal'. Omit if character hasn't fundamentally changed."}}],
  "arc_notes": "Brief story arc progress observation"
}}
Only include npc_reflections for NPCs listed in <reflect> tags.
npc_guidance keys should be NPC IDs like "npc_1".
</task>"""


def _close_truncated_json(text: str) -> str:
    """Attempt to close truncated JSON by removing incomplete trailing content
    and closing all open brackets/braces in correct order.
    Best-effort for max_tokens cutoffs."""
    # Step 1: Remove trailing whitespace
    text = text.rstrip()
    # Step 2: If we're mid-string, close the string
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        text += '"'
    # Step 3: Strip back to the last structurally complete point
    for _ in range(5):
        stripped = text.rstrip()
        # Trailing colon (key with no value): remove "key":
        if stripped.endswith(':'):
            text = re.sub(r',?\s*"[^"]*"\s*:\s*$', '', stripped)
            continue
        # Trailing comma
        if stripped.endswith(','):
            text = stripped[:-1]
            continue
        # Trailing dangling key or incomplete array element after comma:
        # e.g. '..., "narrator_gui"' — truncated before ":"
        # Safe to remove: in objects it's a dangling key, in arrays it's
        # an incomplete last element; both produce valid JSON when removed.
        m = re.search(r',\s*"[^"]*"\s*$', stripped)
        if m:
            text = stripped[:m.start()]
            continue
        break
    # Step 4: Close all open brackets/braces IN CORRECT ORDER
    # Track the stack of open delimiters to close them properly
    stack = []
    in_str = False
    esc = False
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in ('}', ']') and stack:
            stack.pop()
    # Close in reverse order (innermost first)
    text += ''.join(reversed(stack))
    return text


def _repair_json(text: str) -> str:
    """Attempt to repair common LLM JSON errors before parsing.
    Only called after json.loads() already failed — no overhead for valid JSON.

    Fixes:
    1. Unescaped control characters inside strings (newlines, tabs)
    2. Missing commas between fields / after any value type
    3. Trailing commas before } or ]
    """
    # --- Pass 1: Fix unescaped control chars inside strings ---
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            result.append(ch)
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            if ch == '\n':
                result.append('\\n')
                continue
            if ch == '\r':
                result.append('\\r')
                continue
            if ch == '\t':
                result.append('\\t')
                continue
        result.append(ch)
    text = ''.join(result)

    # --- Pass 2: Fix missing commas ---
    # After string value: "value"\n"key"
    text = re.sub(r'("\s*)\n(\s*")', r'\1,\n\2', text)
    # After closing brace/bracket: }\n" or ]\n" or }\n{ or ]\n[
    text = re.sub(r'([\}\]]\s*)\n(\s*["\{\[])', r'\1,\n\2', text)
    # After number: 123\n"key" (digits, possibly with decimal/negative/exponent)
    text = re.sub(r'(\d\s*)\n(\s*")', r'\1,\n\2', text)
    # After boolean/null: true\n"key" or false\n"key" or null\n"key"
    text = re.sub(r'((?:true|false|null)\s*)\n(\s*")', r'\1,\n\2', text)

    # --- Pass 3: Fix trailing commas ---
    text = re.sub(r',(\s*[\}\]])', r'\1', text)

    return text


def call_director(client: anthropic.Anthropic, game: GameState,
                  latest_narration: str,
                  config: Optional[EngineConfig] = None) -> dict:
    """Call the Director agent for scene analysis and story guidance.
    Returns a dict with guidance fields, or empty dict on failure."""
    log(f"[Director] Analyzing scene {game.scene_count}")

    prompt = build_director_prompt(game, latest_narration, config)

    for attempt in range(2):
        try:
            msgs = [{"role": "user", "content": prompt}]
            if attempt > 0:
                msgs.append({"role": "assistant", "content": "{"})

            response = _api_create_with_retry(
                client, max_retries=1,
                model=DIRECTOR_MODEL, max_tokens=1200,
                system=DIRECTOR_SYSTEM,
                messages=msgs,
            )
            text = response.content[0].text
            if attempt > 0:
                text = "{" + text

            # Check if response was truncated
            stop = getattr(response, 'stop_reason', None)
            if stop == 'max_tokens':
                log(f"[Director] Attempt {attempt + 1}/2: response truncated (max_tokens)", level="warning")
                # Try to salvage truncated JSON by closing open brackets
                text = _close_truncated_json(text)

            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                raw_json = match.group()
                try:
                    guidance = json.loads(raw_json)
                except json.JSONDecodeError as je:
                    log(f"[Director] Raw JSON parse failed ({je}), attempting repair...", level="warning")
                    repaired = _repair_json(raw_json)
                    try:
                        guidance = json.loads(repaired)
                        log("[Director] JSON repair successful")
                    except json.JSONDecodeError as je2:
                        # Log failing JSON for diagnosis
                        log(f"[Director] Repair also failed ({je2}). Raw JSON tail: ...{raw_json[-300:]}", level="warning")
                        raise
                log(f"[Director] Guidance: pacing={guidance.get('pacing','?')}, "
                    f"reflections={len(guidance.get('npc_reflections', []))}, "
                    f"summary={guidance.get('scene_summary', '')[:80]}")
                return guidance
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log(f"[Director] Attempt {attempt + 1}/2 failed: {e}", level="warning")
        except Exception as e:
            log(f"[Director] API error: {e}", level="warning")
            break

    log("[Director] All attempts failed, continuing without guidance", level="warning")
    return {}


def _apply_director_guidance(game: GameState, guidance: dict):
    """Apply Director guidance to game state: store guidance, apply reflections,
    update session log with rich summary."""
    if not guidance:
        return

    # Store guidance for next narrator call
    game.director_guidance = {
        "narrator_guidance": guidance.get("narrator_guidance", ""),
        "npc_guidance": guidance.get("npc_guidance", {}),
        "pacing": guidance.get("pacing", ""),
        "arc_notes": guidance.get("arc_notes", ""),
    }

    # Enrich the latest session log entry with Director's summary
    if guidance.get("scene_summary") and game.session_log:
        game.session_log[-1]["rich_summary"] = guidance["scene_summary"]

    # Apply NPC reflections
    for ref in guidance.get("npc_reflections", []):
        npc_id = ref.get("npc_id", "")
        npc = _find_npc(game, npc_id)
        if not npc:
            continue
        _ensure_npc_memory_fields(npc)

        reflection_text = ref.get("reflection", "")
        if not reflection_text:
            continue

        npc["memory"].append({
            "scene": None,  # Reflections are timeless
            "event": reflection_text,
            "emotional_weight": ref.get("tone", "reflective"),
            "importance": 8,  # Reflections are always important
            "type": "reflection",
        })
        npc["_needs_reflection"] = False
        npc["importance_accumulator"] = 0
        npc["last_reflection_scene"] = game.scene_count

        # Update description if Director provided a meaningful character description
        new_desc = ref.get("updated_description", "").strip()
        if new_desc and len(new_desc) > 10:
            # Reject scene snapshots: too long or starts with action verbs
            if len(new_desc) > 200:
                log(f"[Director] Rejected description for {npc['name']}: "
                    f"too long ({len(new_desc)} chars), likely scene snapshot")
            else:
                old_desc = npc.get("description", "")
                npc["description"] = new_desc
                log(f"[Director] Description updated for {npc['name']}: "
                    f"'{old_desc[:60]}' → '{new_desc[:60]}'")

        # Consolidate after adding reflection
        _consolidate_memory(npc)

        log(f"[Director] Reflection for {npc['name']}: {reflection_text[:80]}")

    # Fallback: reset _needs_reflection for any NPCs the Director didn't address.
    # Without this, the flag stays True forever, triggering Director every turn.
    reflected_ids = {ref.get("npc_id", "") for ref in guidance.get("npc_reflections", [])}
    for npc in game.npcs:
        if npc.get("_needs_reflection") and npc.get("id", "") not in reflected_ids:
            npc["_needs_reflection"] = False
            # Don't reset accumulator — it will re-trigger next threshold crossing
            log(f"[Director] Reset stale _needs_reflection for {npc.get('name','?')} "
                f"(Director didn't address)")

    log(f"[Director] Guidance applied: pacing={guidance.get('pacing', '?')}")


# ===============================================================
# PROMPT BUILDERS
# ===============================================================

def build_new_game_prompt(game: GameState) -> str:
    crisis = "\n<crisis>Character at breaking point.</crisis>" if game.crisis_mode else ""
    story = _story_context_block(game)
    time_ctx = f'\n<time>{game.time_of_day}</time>' if game.time_of_day else ""
    loc_hist = f'\n<prev_locations>{", ".join(game.location_history[-3:])}</prev_locations>' if game.location_history else ""
    return f"""<scene type="opening">
<world genre="{game.setting_genre}" tone="{game.setting_tone}">{game.setting_description}</world>
<character name="{game.player_name}">{game.character_concept}</character>
<location>{game.current_location}</location>{loc_hist}{time_ctx}
<situation>{game.current_scene_context}</situation>{crisis}
{story}</scene>
<task>
Opening scene: 3-4 paragraphs. Introduce 2 NPCs through action/dialog. Immediate tension. Create one threat clock.
IMPORTANT: The <character> above is the PLAYER CHARACTER (the "you" in narration). Do NOT include them as an NPC. NPCs are OTHER people the player meets.
If <backstory> exists in system context, treat those facts as established canon — reference naturally but don't retell.
If player_wishes exist, do NOT address them in the opening — save them for later scenes. Focus on world and conflict first.
After narration, append invisible structured data:
</task>
<game_data>
{{"npcs":[{{"id":"npc_1","name":"","description":"","agenda":"","instinct":"","secrets":[""],"disposition":"neutral","bond":0,"bond_max":4,"status":"active","memory":[]}}],"clocks":[{{"id":"clock_1","name":"","clock_type":"threat","segments":6,"filled":1,"trigger_description":"","owner":"world"}}],"location":"","scene_context":"","time_of_day":"early_morning|morning|midday|afternoon|evening|late_evening|night|deep_night"}}
</game_data>"""


def _npc_block(game: GameState, target_id: Optional[str],
               context_text: str = "") -> str:
    """Build full context block for the target NPC using weighted memory retrieval."""
    target = _find_npc(game, target_id) if target_id else None
    if not target:
        return ""
    _ensure_npc_memory_fields(target)
    # Retrieve best memories using weighted scoring
    memories = retrieve_memories(target, context_text=context_text,
                                max_count=5, current_scene=game.scene_count)
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
    mem_str = "\n".join(mem_parts) if mem_parts else "(no memories)"

    secs = json.dumps(target.get("secrets", []), ensure_ascii=False)
    aliases_attr = f' aliases="{",".join(target["aliases"])}"' if target.get("aliases") else ""
    return f"""<target_npc name="{target['name']}" disposition="{target['disposition']}" bond="{target['bond']}/{target.get('bond_max',4)}"{aliases_attr}>
agenda:{target.get('agenda','')} instinct:{target.get('instinct','')}
{mem_str}
secrets(weave subtly,never reveal):{secs}
</target_npc>"""


def _activated_npcs_block(activated: list[dict], target_id: Optional[str],
                          game: GameState, context_text: str = "") -> str:
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
                                     max_count=2, current_scene=game.scene_count)
        mem_hint = ""
        if memories:
            reflections = [m for m in memories if m.get("type") == "reflection"]
            if reflections:
                mem_hint = f' insight="{reflections[0].get("event","")[:80]}"'
            else:
                mem_hint = f' recent="{memories[0].get("event","")[:60]}({memories[0].get("emotional_weight","")})"'

        parts.append(
            f'<activated_npc name="{npc["name"]}" disposition="{npc["disposition"]}" '
            f'bond="{npc["bond"]}"{mem_hint}/>'
        )
    return "\n".join(parts)


def _known_npcs_string(mentioned: list[dict], game: GameState,
                       exclude_ids: set = None) -> str:
    """Build compact known-NPCs line for name-only mentions.
    Also includes remaining active/background NPCs not in activated or mentioned."""
    exclude_ids = exclude_ids or set()
    parts = []

    # Mentioned NPCs (scored but below activation threshold)
    for n in mentioned:
        if n.get("id") in exclude_ids:
            continue
        entry = f'{n["name"]}({n["disposition"]})'
        if n.get("status") == "background":
            entry += "[bg]"
        parts.append(entry)
        exclude_ids.add(n.get("id"))

    # Remaining active NPCs not yet included
    for n in game.npcs:
        if n.get("id") in exclude_ids:
            continue
        if n.get("status") not in ("active", "background"):
            continue
        entry = f'{n["name"]}({n["disposition"]})'
        if n.get("status") == "background":
            entry += "[bg]"
        parts.append(entry)

    return ", ".join(parts) or "none"


def _pacing_block(game: GameState, chaos_interrupt: Optional[str] = None,
                  dramatic_question: str = "") -> str:
    """Build pacing/chaos/dramatic_question block for prompts."""
    parts = []
    pacing = get_pacing_hint(game)
    if pacing != "neutral":
        parts.append(f'<pacing type="{pacing}"/>')
    if dramatic_question:
        parts.append(f'<dramatic_question>{dramatic_question}</dramatic_question>')
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
    parts = []
    for n in game.npcs:
        if n.get("status") != "active":
            continue
        entry = f'{n["name"]}:{n["disposition"]}'
        if n.get("aliases"):
            entry += f'(aka {",".join(n["aliases"])})'
        parts.append(entry)
    return ", ".join(parts) or "none"


def build_dialog_prompt(game: GameState, brain: dict, player_words: str = "",
                        chaos_interrupt: Optional[str] = None,
                        activated_npcs: list = None, mentioned_npcs: list = None,
                        config: Optional[EngineConfig] = None) -> str:
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    context_text = f"{player_words} {brain.get('player_intent', '')} {game.current_scene_context}"
    npc = _npc_block(game, brain.get("target_npc"), context_text=context_text)

    # Three-tier NPC display
    target_id = brain.get("target_npc")
    if activated_npcs is not None:
        # New system: activated NPCs get context, rest are just names
        activated_block = _activated_npcs_block(activated_npcs, target_id, game, context_text)
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
    else:
        # Fallback: old behavior
        all_npcs = _npcs_present_string(game)
        npcs_section = f"\n<npcs_present>{all_npcs}</npcs_present>"

    wa = brain.get("world_addition", "")
    wl = f'\n<world_add>{wa}</world_add>' if wa else ""
    crisis = '\n<crisis/>' if game.crisis_mode else ""
    pw = f'\n<player_words>{player_words}</player_words>' if player_words else ""
    pacing = _pacing_block(game, chaos_interrupt, brain.get("dramatic_question", ""))
    time_ctx = f'\n<time>{game.time_of_day}</time>' if game.time_of_day else ""
    loc_hist = f'\n<prev_locations>{", ".join(game.location_history[-3:])}</prev_locations>' if game.location_history else ""

    # Director guidance injection
    director_block = ""
    dg = game.director_guidance
    if dg and dg.get("narrator_guidance"):
        director_block = f'\n<director_guidance>{dg["narrator_guidance"]}</director_guidance>'
        # NPC-specific guidance
        for npc_id, guidance in dg.get("npc_guidance", {}).items():
            director_block += f'\n<npc_note for="{npc_id}">{guidance}</npc_note>'

    return f"""<scene type="dialog" n="{game.scene_count}">
<world genre="{game.setting_genre}" tone="{game.setting_tone}">{game.setting_description}</world>
<character name="{game.player_name}">{game.character_concept}</character>
<intent>{brain.get('player_intent', '')}</intent>{pw}
<location>{game.current_location}</location>{loc_hist}{time_ctx}
{npc}{npcs_section}{wl}{crisis}
{pacing}{director_block}
{_story_context_block(game)}</scene>
<task>2-3 paragraphs. After narration append invisible metadata:
- If ANY named character appears who is NOT listed in <known_npcs>, add a <new_npcs> block
- If a known NPC is revealed to have a DIFFERENT true name (unmasking, alias reveal), add a <npc_rename> block INSTEAD of <new_npcs>
- Always add <memory_updates> for NPCs involved in this scene
- Always add <scene_context>
- If <director_guidance> is present, follow its narrative direction while maintaining your creative voice
</task>
<npc_rename>[{{"npc_id":"id_or_name","new_name":"revealed true name"}}]</npc_rename>
<new_npcs>[{{"name":"","description":"1 sentence in {lang}","disposition":"neutral|friendly|distrustful|hostile|loyal"}}]</new_npcs>
<memory_updates>[{{"npc_id":"id_or_name","event":"what happened (in {lang})","emotional_weight":"emotion"}}]</memory_updates>
<scene_context>updated context</scene_context>"""


def build_action_prompt(game: GameState, brain: dict, roll: RollResult,
                        consequences: list, clock_events: list, npc_agency: list,
                        player_words: str = "",
                        chaos_interrupt: Optional[str] = None,
                        activated_npcs: list = None, mentioned_npcs: list = None,
                        config: Optional[EngineConfig] = None) -> str:
    _cfg = config or EngineConfig()
    lang = get_narration_lang(_cfg)
    context_text = f"{player_words} {brain.get('player_intent', '')} {game.current_scene_context}"
    npc = _npc_block(game, brain.get("target_npc"), context_text=context_text)

    # Three-tier NPC display
    target_id = brain.get("target_npc")
    if activated_npcs is not None:
        activated_block = _activated_npcs_block(activated_npcs, target_id, game, context_text)
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
    else:
        all_npcs = _npcs_present_string(game)
        npcs_section = f"\n<npcs_present>{all_npcs}</npcs_present>"

    wa = brain.get("world_addition", "")
    wl = f'\n<world_add>{wa}</world_add>' if wa else ""
    pw = f'\n<player_words>{player_words}</player_words>' if player_words else ""

    position = brain.get("position", "risky")
    effect = brain.get("effect", "standard")

    match_tag = ' match="true"' if roll.match else ''
    if roll.result == "MISS":
        clk = "".join(f' clock_triggered="{e["clock"]}:{e["trigger"]}"' for e in clock_events)
        match_hint = ' A MATCH \u2014 the situation escalates dramatically, a fateful twist makes everything worse.' if roll.match else ''
        constraint = f'<result type="MISS"{match_tag} consequences="{",".join(consequences)}"{clk}>Concrete failure. No silver linings. Make it hurt.{match_hint}</r>'
    elif roll.result == "WEAK_HIT":
        match_hint = ' A MATCH \u2014 despite the cost, something unexpected and significant happens, a twist of fate.' if roll.match else ''
        constraint = f'<result type="WEAK_HIT"{match_tag}>Success with tangible cost or complication.{match_hint}</r>'
    else:
        match_hint = ' A MATCH \u2014 an unexpected boon, a fateful revelation, or a dramatic advantage beyond the clean success.' if roll.match else ''
        constraint = f'<result type="STRONG_HIT"{match_tag}>Clean success.{match_hint}</r>'

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
    agency = f'\n<npc_agency>{"| ".join(npc_agency)}</npc_agency>' if npc_agency else ""
    pacing = _pacing_block(game, chaos_interrupt, brain.get("dramatic_question", ""))
    time_ctx = f'\n<time>{game.time_of_day}</time>' if game.time_of_day else ""
    loc_hist = f'\n<prev_locations>{", ".join(game.location_history[-3:])}</prev_locations>' if game.location_history else ""

    # Director guidance injection
    director_block = ""
    dg = game.director_guidance
    if dg and dg.get("narrator_guidance"):
        director_block = f'\n<director_guidance>{dg["narrator_guidance"]}</director_guidance>'
        for npc_id, guidance in dg.get("npc_guidance", {}).items():
            director_block += f'\n<npc_note for="{npc_id}">{guidance}</npc_note>'

    return f"""<scene type="action" n="{game.scene_count}">
<world genre="{game.setting_genre}" tone="{game.setting_tone}">{game.setting_description}</world>
<character name="{game.player_name}">{game.character_concept}</character>
<intent>{brain.get('player_intent', '')} ({brain.get('approach', '')})</intent>{pw}
{constraint}
{position_tag}
<status h="{game.health}" sp="{game.spirit}" su="{game.supply}" m="{game.momentum}"/>
<location>{game.current_location}</location>{loc_hist}{time_ctx}
{npc}{npcs_section}{wl}{flags}{agency}
{pacing}{director_block}
{_story_context_block(game)}</scene>
<task>2-4 paragraphs. After narration append invisible metadata:
- If ANY named character appears who is NOT listed in <known_npcs>, add a <new_npcs> block
- If a known NPC is revealed to have a DIFFERENT true name (unmasking, alias reveal), add a <npc_rename> block INSTEAD of <new_npcs>
- Always add <memory_updates> for NPCs involved in this scene
- Always add <scene_context>
- If <director_guidance> is present, follow its narrative direction while maintaining your creative voice
</task>
<npc_rename>[{{"npc_id":"id_or_name","new_name":"revealed true name"}}]</npc_rename>
<new_npcs>[{{"name":"","description":"1 sentence in {lang}","disposition":"neutral|friendly|distrustful|hostile|loyal"}}]</new_npcs>
<memory_updates>[{{"npc_id":"id_or_name","event":"what happened (in {lang})","emotional_weight":"emotion"}}]</memory_updates>
<scene_context>updated context</scene_context>"""


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
            nd.setdefault("memory", [])
            nd.setdefault("introduced", False)
            nd.setdefault("aliases", [])
            nd.setdefault("keywords", [])
            nd.setdefault("importance_accumulator", 0)
            nd.setdefault("last_reflection_scene", 0)
            nd["memory"] = [
                m if isinstance(m, dict) else {"scene": 0, "event": str(m), "emotional_weight": "neutral"}
                for m in nd["memory"]
            ]
            # Auto-generate keywords if missing
            if not nd["keywords"]:
                nd["keywords"] = _auto_generate_keywords(nd)
        # Filter out NPCs that match the player character name
        player_lower = game.player_name.lower().strip()
        data["npcs"] = [
            n for n in data["npcs"]
            if n.get("name", "").lower().strip() != player_lower
        ]
        if force_npcs or not game.npcs:
            game.npcs = data["npcs"]
            log(f"[NPC] Opening game_data: set {len(game.npcs)} NPCs: {[n.get('name','?') for n in game.npcs]}")
    if data.get("clocks"):
        existing_ids = {c.get("id") for c in game.clocks if c.get("id")}
        for c in data["clocks"]:
            if "type" in c and "clock_type" not in c:
                c["clock_type"] = c.pop("type")
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
    narration = raw

    # --- 1) Tagged game_data (opening scene) ---
    gd = re.search(r'<game_data>([\s\S]*?)</game_data>', narration)
    if gd:
        log(f"[Parser] Step 1: Found <game_data> tag ({len(gd.group(1))} chars)")
        try:
            data = json.loads(gd.group(1))
            # Only allow force_npcs=True (full NPC replacement) in opening scene.
            # Mid-game game_data tags are AI hallucinations — merge only, never replace.
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
        # Look for a JSON object containing "npcs" key (opening scene data without tags)
        npcs_obj_match = re.search(r'\{[\s\S]*?"npcs"\s*:\s*\[', narration)
        if npcs_obj_match:
            log(f"[Parser] Step 1.5: Found untagged game_data JSON at pos {npcs_obj_match.start()}")
            start = npcs_obj_match.start()
            try:
                decoder = json.JSONDecoder()
                data, end_idx = decoder.raw_decode(narration, start)
                if isinstance(data, dict) and (data.get("npcs") or data.get("clocks")):
                    _process_game_data(game, data)
                    # Remove the JSON block from narration
                    narration = (narration[:start].rstrip() + "\n" + narration[start + end_idx:].lstrip()).strip()
            except (json.JSONDecodeError, ValueError) as e:
                log(f"[Parser] Step 1.5: Failed to parse untagged game_data: {e}", level="warning")

    # --- 1.6) Tagged npc_rename (identity reveals / NPC merging) ---
    rename_match = re.search(r'<npc_rename>([\s\S]*?)</npc_rename>', narration)
    if rename_match:
        log(f"[Parser] Step 1.6: Found <npc_rename> tag: {rename_match.group(1)[:200]}")
        _process_npc_renames(game, rename_match.group(1))
        narration = re.sub(r'<npc_rename>[\s\S]*?</npc_rename>', '', narration).strip()

    # --- 1.7) Tagged new_npcs (mid-game NPC discovery) ---
    new_npc_match = re.search(r'<new_npcs>([\s\S]*?)</new_npcs>', narration)
    if new_npc_match:
        log(f"[Parser] Step 1.7: Found <new_npcs> tag: {new_npc_match.group(1)[:200]}")
        _process_new_npcs(game, new_npc_match.group(1))
        narration = re.sub(r'<new_npcs>[\s\S]*?</new_npcs>', '', narration).strip()

    # --- 2) Tagged memory_updates ---
    mem = re.search(r'<memory_updates>([\s\S]*?)</memory_updates>', narration)
    if mem:
        log(f"[Parser] Step 2: Found <memory_updates> tag: {mem.group(1)[:200]}")
        _apply_memory_updates(game, mem.group(1))
        narration = re.sub(r'<memory_updates>[\s\S]*?</memory_updates>', '', narration).strip()

    # --- 3) Tagged scene_context ---
    ctx = re.search(r'<scene_context>([\s\S]*?)</scene_context>', narration)
    if ctx:
        game.current_scene_context = ctx.group(1).strip()
        narration = re.sub(r'<scene_context>[\s\S]*?</scene_context>', '', narration).strip()

    # --- 4) Strip ALL remaining XML tags with content ---
    narration = re.sub(r'<[^>]+>[\s\S]*?</[^>]+>', '', narration).strip()
    narration = re.sub(r'<[^>]+/>', '', narration).strip()

    # --- 4.5) Bracket-format metadata (Narrator sometimes uses [tag] instead of <tag>) ---
    # Patterns: "[memory_updates]", "[scene_context] ...", "[memory_updates]\n[{json}]"
    # Also handles multi-line scene_context that continues after the tag line.

    # Catch "[scene_context] rest of text" → everything from this tag to end is metadata
    # (scene_context often spans multiple lines when it's the last block)
    bracket_ctx = re.search(
        r'^\[scene[_\s-]*context\]\s*(.+)', narration, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if bracket_ctx:
        # Grab everything after the tag →
        remaining = bracket_ctx.group(1).strip()
        # If there's a next bracket tag, only take up to that point
        next_bracket = re.search(r'^\[(?:memory|scene|location)', remaining, re.IGNORECASE | re.MULTILINE)
        if next_bracket:
            val = remaining[:next_bracket.start()].strip()
            rest_after = remaining[next_bracket.start():]
        else:
            val = remaining
            rest_after = ""
        if val:
            game.current_scene_context = val
        narration = narration[:bracket_ctx.start()].rstrip()
        if rest_after:
            narration = narration + "\n" + rest_after
        narration = narration.strip()

    # Catch "[npc_rename]" standalone or with inline content, possibly followed by JSON
    bracket_rename = re.search(
        r'^\[npc[_\s-]*renames?\][ \t]*(.*)$', narration, re.IGNORECASE | re.MULTILINE)
    if bracket_rename:
        inline = bracket_rename.group(1).strip()
        before = narration[:bracket_rename.start()].rstrip()
        after = narration[bracket_rename.end():].lstrip()
        if inline and inline.startswith('['):
            _process_npc_renames(game, inline)
        else:
            json_after = re.match(r'(\[[\s\S]*?\])', after)
            if json_after:
                _process_npc_renames(game, json_after.group(1))
                after = after[json_after.end():].lstrip()
        narration = (before + "\n" + after).strip()

    # Catch "[new_npcs]" standalone or with inline content, possibly followed by JSON
    bracket_new_npcs = re.search(
        r'^\[new[_\s-]*npcs?\][ \t]*(.*)$', narration, re.IGNORECASE | re.MULTILINE)
    if bracket_new_npcs:
        inline = bracket_new_npcs.group(1).strip()
        before = narration[:bracket_new_npcs.start()].rstrip()
        after = narration[bracket_new_npcs.end():].lstrip()
        if inline and inline.startswith('['):
            _process_new_npcs(game, inline)
        else:
            json_after = re.match(r'(\[[\s\S]*?\])', after)
            if json_after:
                _process_new_npcs(game, json_after.group(1))
                after = after[json_after.end():].lstrip()
        narration = (before + "\n" + after).strip()

    # Catch "[memory_updates]" standalone or with inline content, possibly followed by JSON
    bracket_mem = re.search(
        r'^\[memory[_\s-]*updates?\][ \t]*(.*)$', narration, re.IGNORECASE | re.MULTILINE)
    if bracket_mem:
        inline = bracket_mem.group(1).strip()
        before = narration[:bracket_mem.start()].rstrip()
        after = narration[bracket_mem.end():].lstrip()
        # Inline JSON or JSON on next line
        if inline and inline.startswith('['):
            _apply_memory_updates(game, inline)
        else:
            json_after = re.match(r'(\[[\s\S]*?\])', after)
            if json_after:
                _apply_memory_updates(game, json_after.group(1))
                after = after[json_after.end():].lstrip()
        narration = (before + "\n" + after).strip()

    # Catch any remaining standalone bracket labels (including [scene_context] without content)
    narration = re.sub(
        r'^\[(?:memory[_\s-]*updates?|scene[_\s-]*context|new[_\s-]*npcs?|npc[_\s-]*renames?|location)\][ \t]*.*$',
        '', narration, flags=re.IGNORECASE | re.MULTILINE).strip()

    # --- 5) Strip markdown code fences (``` blocks) ---
    # Extract and process JSON content inside code blocks before removing
    for code_match in re.finditer(r'```(?:json)?\s*([\s\S]*?)```', narration):
        code_content = code_match.group(1).strip()
        # Try to extract game_data, memory_updates or scene_context from code blocks
        if '"npcs"' in code_content or '"clocks"' in code_content:
            # game_data block in code fence
            try:
                data = json.loads(code_content)
                if isinstance(data, dict) and (data.get("npcs") or data.get("clocks")):
                    _process_game_data(game, data, force_npcs=False)
            except json.JSONDecodeError:
                pass
        elif '"npc_id"' in code_content and '"new_name"' in code_content:
            # npc_rename data in code fence
            _process_npc_renames(game, code_content)
        elif '"npc_id"' in code_content:
            _apply_memory_updates(game, code_content)
        elif '"disposition"' in code_content and '"name"' in code_content and '"npc_id"' not in code_content:
            # Likely new_npcs data in code fence (has name+disposition but no npc_id)
            _process_new_npcs(game, code_content)
        elif not code_content.startswith('{'):
            # Plain text in code block might be scene_context
            game.current_scene_context = code_content
        else:
            try:
                obj = json.loads(code_content)
                if isinstance(obj, dict):
                    if obj.get("scene_context"):
                        game.current_scene_context = obj["scene_context"]
                        if obj.get("time_of_day") and obj["time_of_day"] in TIME_PHASES:
                            game.time_of_day = obj["time_of_day"]
                    if obj.get("location"):
                        update_location(game, obj["location"])
            except json.JSONDecodeError:
                pass
    narration = re.sub(r'```(?:json)?\s*[\s\S]*?```', '', narration).strip()

    # --- 6) Untagged JSON arrays anywhere (memory updates without wrapper) ---
    # Find the FIRST JSON array with npc_id  --  everything from there onward is metadata
    json_arr_match = re.search(r'\[[\s]*\{[^[\]]*"(?:npc_id|event|emotional_weight)"', narration)
    if json_arr_match:
        before = narration[:json_arr_match.start()].rstrip()
        after_section = narration[json_arr_match.start():]
        # Extract all JSON arrays from the after section
        for jm in re.finditer(r'\[[\s\S]*?\]', after_section):
            _apply_memory_updates(game, jm.group())
        # Any remaining non-JSON text after the array = scene_context
        remaining = re.sub(r'\[[\s\S]*?\]', '', after_section).strip()
        remaining = re.sub(r'```(?:json)?|```', '', remaining).strip()
        if remaining and not remaining.startswith('{'):
            game.current_scene_context = remaining
        narration = before

    # --- 7) Untagged single JSON objects (scene_context, location etc.) ---
    for obj_match in re.finditer(r'\{[^{}]*"(?:scene_context|location|npc_id)"[^{}]*\}', narration):
        try:
            obj = json.loads(obj_match.group())
            if obj.get("scene_context"):
                game.current_scene_context = obj["scene_context"]
                if obj.get("time_of_day") and obj["time_of_day"] in TIME_PHASES:
                    game.time_of_day = obj["time_of_day"]
            if obj.get("location"):
                update_location(game, obj["location"])
        except json.JSONDecodeError:
            pass
    narration = re.sub(r'\{[^{}]*"(?:scene_context|location|npc_id)"[^{}]*\}', '', narration).strip()

    # --- 7.5) Markdown-formatted metadata paragraphs (e.g. **Scene Context:** ...) ---
    _META_LABEL_RE = re.compile(
        r'^[*_#\s]*(scene[\s_-]*context|memory[\s_-]*updates?|szenenkontext|location)\s*[*_#]*\s*[:=]\s*',
        re.IGNORECASE | re.MULTILINE,
    )
    meta_match = _META_LABEL_RE.search(narration)
    if meta_match:
        # Everything from the label onward is metadata
        before = narration[:meta_match.start()].rstrip()
        after = narration[meta_match.end():].strip()
        # Strip leading and trailing markdown formatting from value
        val = re.sub(r'^[*_#\s]+', '', after).strip()
        val = re.sub(r'[*_#]+$', '', val).strip()
        label = meta_match.group(1).lower()
        if val and ('scene' in label or 'szenen' in label):
            game.current_scene_context = val
        elif val and 'location' in label:
            update_location(game, val)
        narration = before

    # --- 8) Trailing metadata lines ---
    lines = narration.rstrip().split('\n')
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        # JSON objects/arrays
        if (last.startswith('{') or last.startswith('[')):
            try:
                parsed = json.loads(last)
                if isinstance(parsed, dict):
                    if parsed.get("scene_context"):
                        game.current_scene_context = parsed["scene_context"]
                        if parsed.get("time_of_day") and parsed["time_of_day"] in TIME_PHASES:
                            game.time_of_day = parsed["time_of_day"]
                    elif parsed.get("location"):
                        update_location(game, parsed["location"])
                elif isinstance(parsed, list):
                    _apply_memory_updates(game, last)
            except json.JSONDecodeError:
                pass
            lines.pop()
            continue
        # Metadata prefix lines (scene_context:, memory_updates:, etc.)
        # Strip leading markdown formatting before matching
        clean_last = re.sub(r'^[\s*_#]+', '', last)
        if re.match(r'^(scene[\s_-]*context|memory[\s_-]*updates?|location|szenenkontext)\s*[:=]', clean_last, re.IGNORECASE):
            val = re.sub(r'^[^:=]+[:=]\s*', '', clean_last).strip()
            val = re.sub(r'[*_#]+$', '', val).strip()  # Strip trailing markdown
            if val:
                game.current_scene_context = val
            lines.pop()
            continue
        # Lines that are clearly technical (contain JSON-like patterns mid-text)
        if re.match(r'^[\[{"\s].*"(?:npc_id|npcs|clocks)"', last):
            lines.pop()
            continue
        break

    narration = '\n'.join(lines).rstrip()

    # --- 8.5) Bold-bracket metadata blocks: **[char: state | location | threat | ...]** ---
    # Narrator sometimes outputs scene_context as pipe-separated items in bold brackets
    bracket_meta = re.search(r'\*{0,2}\[(?:[^\]]*\|){2,}[^\]]*\]\*{0,2}\s*$', narration)
    if bracket_meta:
        # Extract content between brackets as scene_context
        inner = re.sub(r'^[\s*\[]+|[\]\s*]+$', '', bracket_meta.group()).strip()
        if inner:
            game.current_scene_context = inner
        narration = narration[:bracket_meta.start()].rstrip()

    # --- 9) NUCLEAR FALLBACK: find narrative boundary ---
    # If any JSON/technical content still remains, find the last paragraph
    # that ends with prose punctuation and cut everything after it
    if re.search(r'"npc_id"|"npcs"|"clocks"|"scene_context"|"emotional_weight"|"event":', narration):
        # Find the last line that ends with narrative punctuation
        result_lines = []
        found_end = False
        for line in narration.split('\n'):
            stripped = line.strip()
            # Skip empty lines between paragraphs (keep them)
            if not stripped:
                if not found_end:
                    result_lines.append(line)
                continue
            # If we haven't found the end yet, check if this line is narrative
            if not found_end:
                # Technical line detection
                is_technical = bool(
                    re.search(r'"npc_id"|"npcs"|"clocks"|"scene_context"|"emotional_weight"|"event"\s*:', stripped)
                    or (stripped.startswith(('[', '{')) and '"' in stripped)
                )
                if is_technical:
                    found_end = True
                    # Try to extract data from this line
                    if '"npc_id"' in stripped:
                        # Try wrapping in array if needed
                        try_json = stripped if stripped.startswith('[') else f'[{stripped}]'
                        _apply_memory_updates(game, try_json)
                    continue
                result_lines.append(line)
            # After finding end, try to extract useful data but don't add to narration
            else:
                if '"npc_id"' in stripped:
                    try_json = stripped if stripped.startswith('[') else f'[{stripped}]'
                    _apply_memory_updates(game, try_json)

        narration = '\n'.join(result_lines).rstrip()

    # --- 10) Final cleanup: strip trailing JSON blocks at the end ---
    # Only strip if the narration ends with ] or } AND the bracket block
    # starts on its own line (not embedded in prose)
    if narration.rstrip().endswith((']', '}')):
        # Find the last line that starts with [ or { and remove from there
        lines_10 = narration.split('\n')
        cut_idx = len(lines_10)
        for i in range(len(lines_10) - 1, -1, -1):
            stripped = lines_10[i].strip()
            if stripped and (stripped[0] in '[{'):
                cut_idx = i
            elif stripped:
                break  # Hit a non-bracket, non-empty line → stop
        if cut_idx < len(lines_10):
            narration = '\n'.join(lines_10[:cut_idx]).rstrip()

    # --- 11) Strip markdown horizontal rules (---, ***, ___) ---
    narration = re.sub(r'^\s*[-*_]{3,}\s*$', '', narration, flags=re.MULTILINE).strip()

    # --- 12) FINAL SAFETY NET: catch any remaining bracket metadata that slipped through ---
    # This catches patterns like "[memory_updates]", "[scene_context] ...", etc.
    # that earlier steps might have missed due to formatting variations
    narration = re.sub(
        r'^\[(?:memory[_\s-]*updates?|scene[_\s-]*context|new[_\s-]*npcs?|npc[_\s-]*renames?|location|game[_\s-]*data)\].*$',
        '', narration, flags=re.IGNORECASE | re.MULTILINE).strip()

    # --- 13) Strip stray markdown artifacts (orphan bold/italic markers) ---
    narration = re.sub(r'\s*\*{1,3}\s*$', '', narration, flags=re.MULTILINE).rstrip()

    # --- 13.5) Strip stray code fence markers (empty ```json``` blocks or unclosed fences) ---
    narration = re.sub(r'```(?:json|xml)?\s*```', '', narration).strip()
    narration = re.sub(r'^\s*```(?:json|xml)?\s*$', '', narration, flags=re.MULTILINE).strip()

    # --- 14) Normalize NPC dispositions to canonical values ---
    _normalize_npc_dispositions(game.npcs)

    # --- 15) Mark NPCs as introduced if their name appears in visible text ---
    narration_lower = narration.lower()
    for npc in game.npcs:
        if not npc.get("introduced", False) and npc.get("name"):
            # Check if NPC name (or significant part) appears in visible narration
            name = npc["name"].strip()
            if name and name.lower() in narration_lower:
                npc["introduced"] = True

    # Summary log for debugging
    active = [n for n in game.npcs if n.get("status") == "active"]
    background = [n for n in game.npcs if n.get("status") == "background"]
    introduced = [n for n in active if n.get("introduced", False)]
    log(f"[Parser] Done. NPCs total={len(game.npcs)} active={len(active)} background={len(background)} "
        f"introduced={len(introduced)}: {[n['name'] for n in introduced]}")

    # Safety: if parser stripped everything, return a minimal fallback
    if not narration.strip():
        log("[Parser] WARNING: Narration empty after parsing — returning raw text excerpt", level="warning")
        # Extract first substantial paragraph from raw response (before any metadata)
        for para in raw.split('\n\n'):
            clean_para = para.strip()
            if clean_para and not clean_para.startswith(('<', '{', '[', '```')):
                narration = clean_para
                break
        if not narration.strip():
            narration = "(The narrator pauses, gathering thoughts...)"

    return narration


def _apply_memory_updates(game: GameState, json_text: str):
    """Apply NPC memory updates from JSON text with importance scoring and consolidation."""
    try:
        updates = json.loads(json_text.strip())
        if not isinstance(updates, list):
            return
        for u in updates:
            if not isinstance(u, dict) or "npc_id" not in u:
                continue
            npc = _find_npc(game, u["npc_id"])

            # Fuzzy fallback: try word-overlap matching before creating a stub
            if not npc and u["npc_id"] and u["npc_id"] not in ("world", "player", ""):
                npc = _fuzzy_match_existing_npc(game, u["npc_id"])
                if npc:
                    log(f"[NPC] memory_update fuzzy-matched '{u['npc_id']}' → '{npc['name']}'")

            # Auto-create NPC stub if not found (safety net when <new_npcs> was omitted)
            if not npc and u["npc_id"] and u["npc_id"] not in ("world", "player", ""):
                npc_name = u["npc_id"]
                if npc_name.lower().strip() != game.player_name.lower().strip():
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
                        "keywords": [],
                        "importance_accumulator": 0,
                        "last_reflection_scene": 0,
                    }
                    npc["keywords"] = _auto_generate_keywords(npc)
                    game.npcs.append(npc)
                    log(f"[NPC] Auto-created stub NPC from memory_update: {npc_name}")

            if npc:
                # Reactivate background NPCs that appear in current scene
                if npc.get("status") == "background":
                    _reactivate_npc(npc, reason="memory_update in current scene")
                # Ensure memory system fields exist
                _ensure_npc_memory_fields(npc)

                event_text = u.get("event", "")
                emotional = u.get("emotional_weight", "neutral")
                importance = score_importance(emotional, event_text)

                npc["memory"].append({
                    "scene": game.scene_count,
                    "event": event_text,
                    "emotional_weight": emotional,
                    "importance": importance,
                    "type": "observation",
                })

                # Update importance accumulator for reflection triggering
                npc["importance_accumulator"] = npc.get("importance_accumulator", 0) + importance
                if npc["importance_accumulator"] >= REFLECTION_THRESHOLD:
                    npc["_needs_reflection"] = True
                    log(f"[NPC] {npc['name']} needs reflection "
                        f"(accumulator={npc['importance_accumulator']})")

                # Consolidate memory (replaces simple FIFO)
                _consolidate_memory(npc)

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log(f"[NPC] Memory update failed: {e}", level="warning")



# ===============================================================
# SAVE / LOAD
# ===============================================================

SAVE_FIELDS = [
    "player_name", "character_concept", "setting_genre", "setting_tone",
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
    # v5.10: Backstory
    "backstory",
    # v5.11: Director guidance
    "director_guidance",
]

def save_game(game: GameState, username: str, chat_messages: list = None,
              name: str = "autosave") -> Path:
    """Save game state and chat history. UI layer must provide username and chat_messages."""
    save_dir = _get_save_dir(username)
    save_dir.mkdir(parents=True, exist_ok=True)
    data = {"saved_at": datetime.now().isoformat()}
    data.update({k: getattr(game, k) for k in SAVE_FIELDS})
    # Chat history for visual restoration (strip audio binary data and transient recaps)
    raw_messages = chat_messages or []
    data["chat_messages"] = [
        {k: v for k, v in msg.items() if k not in ("audio_bytes", "audio_format")}
        for msg in raw_messages
        if not msg.get("recap")
    ]
    path = save_dir / f"{name}.json"
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
    # Normalize dispositions from older saves that may have non-canonical values
    _normalize_npc_dispositions(game.npcs)
    # Backward compatibility: older saves don't have 'introduced' flag -- assume all existing NPCs were introduced
    for npc in game.npcs:
        npc.setdefault("introduced", True)
    # Backward compatibility: older saves don't have 'aliases' field
    for npc in game.npcs:
        npc.setdefault("aliases", [])
    # Backward compatibility: migrate old "inactive" status to "background" (three-tier NPC system v0.9.14)
    for npc in game.npcs:
        if npc.get("status") == "inactive":
            npc["status"] = "background"
    # Backward compatibility: migrate NPC memory system fields (v5.11)
    for npc in game.npcs:
        _ensure_npc_memory_fields(npc)
    # Clean up transient flags that should not persist across save/load
    for npc in game.npcs:
        npc.pop("_needs_reflection", None)
    # Backward compatibility: older saves don't have location_history/time_of_day
    if game.location_history is None:
        game.location_history = []
    if game.time_of_day is None:
        game.time_of_day = ""
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
        }
    except Exception:
        return {"name": name, "player_name": "?", "scene_count": 0,
                "chapter_number": 1, "saved_at": "", "setting_genre": ""}


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

    game = GameState(
        player_name=setup.get("character_name", "Namenlos"),
        character_concept=setup.get("character_concept", ""),
        setting_genre=genre,
        setting_tone=tone,
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

    # Generate the opening scene
    raw = call_narrator(client, build_new_game_prompt(game), game, config)
    narration = parse_narrator_response(game, raw)

    # Choose story structure based on tone probability
    structure = choose_story_structure(tone)

    # Generate story blueprint AFTER opening (uses NPCs/setting from parsed response)
    game.story_blueprint = call_story_architect(client, game, structure_type=structure, config=config)

    # Record opening as neutral intensity
    record_scene_intensity(game, "action")

    # Store in narration history for context continuity
    game.narration_history.append({
        "prompt_summary": f"Opening scene: {game.player_name} in {game.current_location}",
        "narration": narration[:MAX_NARRATION_CHARS],
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
        parts.append(f'  <chapter n="{ch.get("chapter", "?")}" title="{ch.get("title", "")}">'
                     f'{ch.get("summary", "")}</chapter>')
    parts.append('</campaign_history>')
    return "\n".join(parts)


def call_chapter_summary(client: anthropic.Anthropic, game: GameState,
                          config: Optional[EngineConfig] = None) -> dict:
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

    for attempt in range(3):
        try:
            response = _api_create_with_retry(
                client, max_retries=1,
                model=BRAIN_MODEL, max_tokens=400,
                system=f"""Summarize an RPG chapter for campaign continuity. Return ONLY valid JSON.
- Write in {lang}
- "title": A short evocative title for this chapter (3-6 words)
- "summary": 3-4 sentences capturing key events, character growth, and how the chapter ended
- "unresolved_threads": List of 1-3 open plot threads or tensions that could carry into the next chapter
- "character_growth": 1 sentence on how the protagonist changed
""" + _kid_friendly_block(_cfg) + _content_boundaries_block(game),
                messages=[{"role": "user", "content":
                           f"character:{game.player_name} {E['dash']} {game.character_concept}\n"
                           f"genre:{game.setting_genre} tone:{game.setting_tone}\n"
                           f"world:{game.setting_description}\n"
                           f"conflict:{conflict}\n"
                           f"log:{log_text}\nnpcs:{npc_text}\n"
                           f"location:{game.current_location}\n"
                           f"situation:{game.current_scene_context}"}],
            )
            text = response.content[0].text
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                raw_json = match.group()
                try:
                    data = json.loads(raw_json)
                except json.JSONDecodeError:
                    data = json.loads(_repair_json(raw_json))
                data["chapter"] = game.chapter_number
                data["scenes"] = game.scene_count
                return data
            # No JSON found — retry
            log(f"[ChapterSummary] Attempt {attempt + 1}/3: no JSON in response", level="warning")
        except json.JSONDecodeError:
            log(f"[ChapterSummary] Attempt {attempt + 1}/3: invalid JSON", level="warning")
        except Exception as e:
            log(f"[ChapterSummary] Attempt {attempt + 1}/3 failed: {e}", level="warning")
            if attempt < 2:
                import time as _time
                _time.sleep(2 ** attempt)
    # Fallback (English — language-neutral)
    return {
        "chapter": game.chapter_number,
        "title": f"Chapter {game.chapter_number}",
        "summary": f"{game.player_name} had an adventure in {game.current_location}.",
        "unresolved_threads": [],
        "character_growth": "",
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
        f'<npc name="{n["name"]}" disposition="{n["disposition"]}" bond="{n["bond"]}/{n.get("bond_max",4)}">'
        f'{n.get("description","")}</npc>'
        for n in game.npcs if n.get("status") == "active"
    )

    log_text = "; ".join(
        f'S{s["scene"]}:{s.get("rich_summary") or s["summary"]}({s["result"]})'
        for s in game.session_log[-15:]
    )

    return f"""<scene type="epilogue">
<world genre="{game.setting_genre}" tone="{game.setting_tone}">{game.setting_description}</world>
<character name="{game.player_name}">{game.character_concept}</character>
<location>{game.current_location}</location>
<situation>{game.current_scene_context}</situation>
<conflict>{conflict}</conflict>
<possible_endings>{endings_text}</possible_endings>
{npc_block}
{campaign}
<session_log>{log_text}</session_log>
</scene>
<task>
Write a beautiful EPILOGUE for this story (4-6 paragraphs). This is NOT a new scene — no dice, no mechanics.
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
    narration = narration.strip()

    if not narration:
        narration = "(The narrator pauses, then offers a quiet reflection on the journey...)"

    game.epilogue_shown = True
    log(f"[Epilogue] Generated ({len(narration)} chars)")
    return game, narration


def build_new_chapter_prompt(game: GameState) -> str:
    """Build opening prompt for a new chapter in an ongoing campaign."""
    campaign = _campaign_history_block(game)
    npc_block = "\n".join(
        f'<returning_npc id="{n["id"]}" name="{n["name"]}" disposition="{n["disposition"]}" '
        f'bond="{n["bond"]}/{n.get("bond_max",4)}"'
        + (f' aliases="{",".join(n["aliases"])}"' if n.get("aliases") else '')
        + f'>{n.get("description","")}</returning_npc>'
        for n in game.npcs if n.get("status") == "active"
    )
    bg_npcs = [n for n in game.npcs if n.get("status") == "background"]
    if bg_npcs:
        bg_parts = []
        for n in bg_npcs:
            entry = f'{n["name"]}({n["disposition"]})'
            if n.get("aliases"):
                entry += f'[aka {",".join(n["aliases"])}]'
            bg_parts.append(entry)
        bg_names = ", ".join(bg_parts)
        npc_block += f'\n<background_npcs>Known but not recently active: {bg_names}</background_npcs>'
    story = _story_context_block(game)
    time_ctx = f'\n<time>{game.time_of_day}</time>' if game.time_of_day else ""

    return f"""<scene type="chapter_opening" chapter="{game.chapter_number}">
<world genre="{game.setting_genre}" tone="{game.setting_tone}">{game.setting_description}</world>
<character name="{game.player_name}">{game.character_concept}</character>
<location>{game.current_location}</location>{time_ctx}
<situation>{game.current_scene_context}</situation>
{campaign}
{npc_block}
{story}</scene>
<task>
Chapter {game.chapter_number} opening: 3-4 paragraphs. This is a NEW chapter in an ongoing campaign.
- Reference the character's history and relationships naturally (don't recap everything, just hint)
- Some time has passed since last chapter. Show how the world/relationships evolved
- Introduce a NEW tension or situation that builds on unresolved threads
- Returning NPCs should feel familiar but may have changed
- Introduce 1-2 NEW NPCs alongside returning characters
- Create one new threat clock for this chapter
IMPORTANT: The <character> above is the PLAYER CHARACTER. Do NOT include them as an NPC.
After narration, append invisible structured data:
</task>
<game_data>
{{"npcs":[{{"id":"npc_new_1","name":"","description":"","agenda":"","instinct":"","secrets":[""],"disposition":"neutral","bond":0,"bond_max":4,"status":"active","memory":[]}}],"clocks":[{{"id":"clock_1","name":"","clock_type":"threat","segments":6,"filled":1,"trigger_description":"","owner":"world"}}],"location":"","scene_context":"","time_of_day":"early_morning|morning|midday|afternoon|evening|late_evening|night|deep_night"}}
</game_data>"""


def start_new_chapter(client: anthropic.Anthropic, game: GameState,
                      config: Optional[EngineConfig] = None,
                      username: str = "") -> tuple[GameState, str]:
    """Start a new chapter: keep character/world/NPCs, reset mechanics, new story arc."""
    log(f"[Campaign] Starting chapter {game.chapter_number + 1} for {game.player_name}")

    # Generate chapter summary before resetting
    chapter_summary = call_chapter_summary(client, game, config)
    game.campaign_history.append(chapter_summary)

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

    # Save returning NPCs before parse replaces them (active + background)
    returning_npcs = [dict(n) for n in game.npcs if n.get("status") in ("active", "background")]

    # Generate opening scene with campaign context
    raw = call_narrator(client, build_new_chapter_prompt(game), game, config)
    narration = parse_narrator_response(game, raw)

    # Merge: parse_narrator_response replaces game.npcs with new NPCs from game_data.
    # Re-add returning NPCs that weren't mentioned in the new chapter's game_data.
    new_npc_ids = {n["id"] for n in game.npcs}
    new_npc_names = {n["name"].lower().strip() for n in game.npcs}
    for old_npc in returning_npcs:
        # Skip if narrator already re-introduced this NPC (by id or name)
        if old_npc["id"] in new_npc_ids:
            continue
        if old_npc["name"].lower().strip() in new_npc_names:
            continue
        old_npc["introduced"] = True  # Player knows them from previous chapter
        game.npcs.append(old_npc)

    # Choose story structure for new chapter
    structure = choose_story_structure(game.setting_tone)
    game.story_blueprint = call_story_architect(client, game, structure_type=structure, config=config)

    # Record opening
    record_scene_intensity(game, "action")
    game.narration_history.append({
        "prompt_summary": f"Chapter {game.chapter_number} opening: {game.player_name} in {game.current_location}",
        "narration": narration[:MAX_NARRATION_CHARS],
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
    brain = call_brain(client, game, player_message, config)

    # Reactivate background NPC if Brain targets one
    tid = brain.get("target_npc")
    if tid:
        target = _find_npc(game, tid)
        if target and target.get("status") == "background":
            _reactivate_npc(target, reason=f"targeted by player in scene {game.scene_count + 1}")

    # Apply location change and time progression from Brain
    _apply_brain_location_time(game, brain)

    # NPC Activation — determine who gets full context in prompt
    activated_npcs, mentioned_npcs = activate_npcs_for_prompt(game, brain, player_message)

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
        # Mark first pending revelation as used (narrator was instructed to weave it in)
        if pending_revs:
            mark_revelation_used(game, pending_revs[0]["id"])
        # Record pacing
        scene_type = "interrupt" if chaos_interrupt else "breather"
        record_scene_intensity(game, scene_type)
        game.narration_history.append({
            "prompt_summary": f"Dialog: {brain.get('player_intent', player_message)[:80]}",
            "narration": narration[:MAX_NARRATION_CHARS],
        })
        if len(game.narration_history) > MAX_NARRATION_HISTORY:
            game.narration_history = game.narration_history[-MAX_NARRATION_HISTORY:]
        game.session_log.append({"scene": game.scene_count,
                                 "summary": brain.get("player_intent", player_message),
                                 "result": "dialog", "consequences": [], "clock_events": [],
                                 "dramatic_question": brain.get("dramatic_question", ""),
                                 "chaos_interrupt": chaos_interrupt})
        if len(game.session_log) > MAX_SESSION_LOG:
            game.session_log = game.session_log[-MAX_SESSION_LOG:]
        # Check story completion
        _check_story_completion(game)

        # Director — deferred to UI layer for non-blocking display
        director_ctx = None
        if _should_call_director(game, roll_result="dialog",
                                  chaos_used=bool(chaos_interrupt),
                                  new_npcs_found='<new_npcs>' in raw,
                                  revelation_used=bool(pending_revs)):
            director_ctx = {"narration": narration, "config": config}
        else:
            log(f"[Director] Skipped (no trigger at scene {game.scene_count})")

        # Note: UI layer handles save_game()
        return game, narration, None, None, director_ctx

    # Action
    game.scene_count += 1
    stat_name = brain.get("stat", "wits")
    roll = roll_action(stat_name, game.get_stat(stat_name), brain.get("move", "face_danger"))
    if roll.match:
        log(f"[Turn] MATCH! Both challenge dice show {roll.c1} \u2014 {roll.result}")

    # Check burn possibility BEFORE consequences reduce momentum
    burn_info = None
    if roll.result in ("MISS", "WEAK_HIT") and game.momentum > 0:
        potential_burn = can_burn_momentum(game, roll)
        if potential_burn:
            # Snapshot state BEFORE consequences so burn can fully reverse them
            burn_info = {
                "roll": roll,
                "new_result": potential_burn,
                "cost": game.momentum,
                "brain": dict(brain),
                "player_words": player_message,
                "chaos_interrupt": chaos_interrupt,
                "pre_snapshot": {
                    "health": game.health,
                    "spirit": game.spirit,
                    "supply": game.supply,
                    "momentum": game.momentum,
                    "chaos_factor": game.chaos_factor,
                    "crisis_mode": game.crisis_mode,
                    "game_over": game.game_over,
                    "npc_bonds": {n["id"]: n.get("bond", 0) for n in game.npcs},
                    "clock_fills": {c["id"]: c["filled"] for c in game.clocks},
                },
            }

    consequences, clock_events = apply_consequences(game, roll, brain)
    npc_agency = check_npc_agency(game)
    prompt = build_action_prompt(game, brain, roll, consequences, clock_events, npc_agency,
                                player_words=player_message, chaos_interrupt=chaos_interrupt,
                                activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                config=config)
    raw = call_narrator(client, prompt, game, config)
    narration = parse_narrator_response(game, raw)
    # Update chaos factor based on result
    update_chaos_factor(game, roll.result)
    # Record pacing
    scene_type = "interrupt" if chaos_interrupt else "action"
    record_scene_intensity(game, scene_type)
    # Mark first pending revelation as used
    if pending_revs:
        mark_revelation_used(game, pending_revs[0]["id"])
    game.narration_history.append({
        "prompt_summary": f"Action ({roll.result}): {brain.get('player_intent', player_message)[:80]}",
        "narration": narration[:MAX_NARRATION_CHARS],
    })
    if len(game.narration_history) > MAX_NARRATION_HISTORY:
        game.narration_history = game.narration_history[-MAX_NARRATION_HISTORY:]
    game.session_log.append({"scene": game.scene_count,
                             "summary": brain.get("player_intent", player_message),
                             "result": roll.result, "consequences": consequences,
                             "clock_events": clock_events,
                             "position": brain.get("position", "risky"),
                             "effect": brain.get("effect", "standard"),
                             "dramatic_question": brain.get("dramatic_question", ""),
                             "chaos_interrupt": chaos_interrupt})
    if len(game.session_log) > MAX_SESSION_LOG:
        game.session_log = game.session_log[-MAX_SESSION_LOG:]
    # Check story completion
    _check_story_completion(game)

    # Director — deferred to UI layer for non-blocking display
    director_ctx = None
    if _should_call_director(game, roll_result=roll.result,
                              chaos_used=bool(chaos_interrupt),
                              new_npcs_found='<new_npcs>' in raw,
                              revelation_used=bool(pending_revs)):
        director_ctx = {"narration": narration, "config": config}
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


def _try_call_director(client: anthropic.Anthropic, game: GameState,
                       narration: str, config: Optional[EngineConfig],
                       roll_result: str = "", chaos_used: bool = False,
                       new_npcs_found: bool = False,
                       revelation_used: bool = False):
    """Attempt to call Director agent if conditions are met.
    Runs synchronously for now, but designed for future async execution.
    Fails gracefully — game works fine without Director."""
    try:
        if _should_call_director(game, roll_result=roll_result,
                                 chaos_used=chaos_used,
                                 new_npcs_found=new_npcs_found,
                                 revelation_used=revelation_used):
            guidance = call_director(client, game, narration, config)
            _apply_director_guidance(game, guidance)
        else:
            log(f"[Director] Skipped (no trigger at scene {game.scene_count})")
    except Exception as e:
        log(f"[Director] Failed gracefully: {e}", level="warning")


def _check_story_completion(game: GameState):
    """Check if the story has reached its natural end point."""
    if not game.story_blueprint or not game.story_blueprint.get("acts"):
        return
    acts = game.story_blueprint["acts"]
    final_act = acts[-1]
    final_end = final_act.get("scene_range", [14, 20])[1]
    # If past the final scene range, signal story complete
    if game.scene_count >= final_end:
        game.story_blueprint["story_complete"] = True


def process_momentum_burn(client: anthropic.Anthropic, game: GameState,
                          old_roll: RollResult, new_result: str,
                          brain_data: dict, player_words: str = "",
                          config: Optional[EngineConfig] = None,
                          pre_snapshot: Optional[dict] = None,
                          chaos_interrupt: Optional[str] = None) -> tuple[GameState, str]:
    """Re-narrate a scene after momentum burn upgrades the result.
    If pre_snapshot is provided (v0.9.11+), fully restores game state before
    applying new consequences. Otherwise falls back to partial restoration."""
    # Reset momentum (burn always costs all momentum)
    game.momentum = 0

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
    if pre_snapshot:
        # Full restoration: health, spirit, supply to pre-consequence values
        game.health = pre_snapshot["health"]
        game.spirit = pre_snapshot["spirit"]
        game.supply = pre_snapshot["supply"]
        game.chaos_factor = pre_snapshot.get("chaos_factor", game.chaos_factor)
        game.crisis_mode = pre_snapshot.get("crisis_mode", False)
        game.game_over = pre_snapshot.get("game_over", False)
        # Restore NPC bonds
        npc_bonds = pre_snapshot.get("npc_bonds", {})
        for npc in game.npcs:
            if npc["id"] in npc_bonds:
                npc["bond"] = npc_bonds[npc["id"]]
        # Restore clock fills (reverse any ticks from the old MISS)
        clock_fills = pre_snapshot.get("clock_fills", {})
        for clock in game.clocks:
            if clock["id"] in clock_fills:
                clock["filled"] = clock_fills[clock["id"]]
        log(f"[Burn] Fully restored state from snapshot: H{game.health} Sp{game.spirit} Su{game.supply} Chaos{game.chaos_factor}")
    else:
        # Legacy fallback (old burn_info without snapshot — backward compat)
        old_result = old_roll.result
        if old_result == "MISS":
            move = old_roll.move
            position = brain_data.get("position", "risky")
            if move == "endure_harm" or move in COMBAT_MOVES:
                game.health = min(5, game.health + 1)
            elif move == "endure_stress" or move in SOCIAL_MOVES:
                game.spirit = min(5, game.spirit + 1)
            else:
                game.supply = min(5, game.supply + 1)
                if position != "controlled":
                    game.health = min(5, game.health + 1)
        # Reverse old chaos update before new one gets applied
        if old_result == "MISS":
            game.chaos_factor = max(3, game.chaos_factor - 1)
        elif old_result == "STRONG_HIT":
            game.chaos_factor = min(9, game.chaos_factor + 1)
        # Re-check crisis flags after partial restoration
        if game.health > 0 and game.spirit > 0:
            game.crisis_mode = False
            game.game_over = False
        elif game.health > 0 or game.spirit > 0:
            game.game_over = False

    # Create upgraded roll
    upgraded = RollResult(old_roll.d1, old_roll.d2, old_roll.c1, old_roll.c2,
                          old_roll.stat_name, old_roll.stat_value, old_roll.action_score,
                          new_result, old_roll.move, old_roll.match)

    # Apply new consequences
    consequences, clock_events = apply_consequences(game, upgraded, brain_data)
    # Re-run NPC activation for the re-narrated scene
    activated_npcs, mentioned_npcs = activate_npcs_for_prompt(game, brain_data, player_words)
    prompt = build_action_prompt(game, brain_data, upgraded, consequences, clock_events, [],
                                player_words=player_words, chaos_interrupt=chaos_interrupt,
                                activated_npcs=activated_npcs, mentioned_npcs=mentioned_npcs,
                                config=config)
    prompt = prompt.replace('<task>', '<momentum_burn>Character digs deep, turns the tide.</momentum_burn>\n<task>')

    raw = call_narrator(client, prompt, game, config)
    narration = parse_narrator_response(game, raw)

    # Update chaos after burn (new result counts)
    update_chaos_factor(game, new_result)

    # Replace last narration history entry with burned version
    if game.narration_history:
        game.narration_history[-1] = {
            "prompt_summary": f"Momentum burn ({new_result}): {brain_data.get('player_intent', '')[:80]}",
            "narration": narration[:MAX_NARRATION_CHARS],
        }

    # Update last log entry
    if game.session_log:
        game.session_log[-1]["result"] = new_result
        game.session_log[-1]["consequences"] = consequences
        game.session_log[-1]["clock_events"] = clock_events
        game.session_log[-1]["chaos_interrupt"] = chaos_interrupt

    # Note: UI layer handles save_game()
    return game, narration

