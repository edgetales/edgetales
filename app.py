#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Tales - Narrative Solo RPG Engine 
========================================
NiceGUI UI and server logic
"""

# ---------------------------------------------------------------------------
# Auto-install required packages (runs once at startup before other imports)
# ---------------------------------------------------------------------------
def _ensure_requirements():
    """Check all required packages and install missing ones via pip."""
    import importlib
    import subprocess
    import sys

    # Map: import_name → pip package name
    _REQUIRED = {
        "anthropic":      "anthropic",
        "nicegui":        "nicegui",
        "reportlab":      "reportlab",
        "edge_tts":       "edge-tts",
        "stop_words":     "stop-words",
        "nameparser":     "nameparser",
        "cryptography":   "cryptography",
        "faster_whisper": "faster-whisper",
        "wonderwords":    "wonderwords",
    }

    # Optional packages (hint only, no auto-install)
    _OPTIONAL = {
        "chatterbox":     "chatterbox-tts",
    }

    print("\u2699\uFE0F  Checking dependencies ...")

    found = []
    missing = []
    for import_name, pip_name in _REQUIRED.items():
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", getattr(mod, "VERSION", ""))
            ver_str = f" ({ver})" if ver else ""
            found.append(f"{pip_name}{ver_str}")
        except ImportError:
            missing.append(pip_name)

    # Check optional packages
    optional_found = []
    optional_missing = []
    for import_name, pip_name in _OPTIONAL.items():
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", getattr(mod, "VERSION", ""))
            ver_str = f" ({ver})" if ver else ""
            optional_found.append(f"{pip_name}{ver_str}")
        except ImportError:
            optional_missing.append(pip_name)

    # Console output
    if found:
        print(f"   \u2705 Found: {', '.join(found)}")
    if optional_found:
        print(f"   \u2705 Optional: {', '.join(optional_found)}")
    if optional_missing:
        print(f"   \u2139\uFE0F  Optional (not installed): {', '.join(optional_missing)}")
    if missing:
        print(f"   \u274C Missing: {', '.join(missing)}")

    # Auto-install missing required packages
    if missing:
        print(f"\n   \u2B07\uFE0F  Installing: {', '.join(missing)} ...")
        pip_cmd = [sys.executable, "-m", "pip", "install", *missing]
        try:
            subprocess.check_call(pip_cmd)
        except subprocess.CalledProcessError:
            # Retry with --break-system-packages (needed on Debian/Ubuntu with
            # externally-managed Python environments, e.g. Raspberry Pi OS)
            try:
                subprocess.check_call(pip_cmd + ["--break-system-packages"])
            except subprocess.CalledProcessError as e:
                print(f"\n   \u274C Installation failed (exit code {e.returncode}).")
                print(f"      Please install manually: pip install {' '.join(missing)}")
                sys.exit(1)
        print(f"   \u2705 Successfully installed: {', '.join(missing)}")
    else:
        print("   \u2705 All dependencies satisfied.")

    # Store results for deferred logging (engine logger not yet initialized here)
    import builtins
    builtins._EDGETALES_DEP_CHECK = {
        "found": found,
        "missing_installed": missing,
        "optional_found": optional_found,
        "optional_missing": optional_missing,
    }


_ensure_requirements()


# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import asyncio
import html as html_mod
import os
import re
import tempfile
import uuid
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import anthropic
from nicegui import app, ui, Client

# ---------------------------------------------------------------------------
# Engine & Voice imports
# ---------------------------------------------------------------------------
from engine import (
    E, log, VERSION,
    GameState, RollResult, EngineConfig,
    LANGUAGES, CHATTERBOX_DEVICE_OPTIONS,
    VOICE_DIR,
    load_global_config, save_global_config,
    load_user_config, save_user_config,
    list_users, create_user, delete_user,
    save_game, load_game, list_saves, list_saves_with_info, delete_save, export_story_pdf,
    save_chapter_archive, load_chapter_archive, list_chapter_archives, delete_chapter_archives,
    copy_chapter_archives,
    get_current_act, setup_file_logging,
    call_setup_brain, start_new_game, start_new_chapter,
    process_turn, process_momentum_burn, process_correction, call_recap,
    run_deferred_director, generate_epilogue,
)
from i18n import (
    t, UI_LANGUAGES, DEFAULT_LANG,
    get_stat_labels, get_move_labels, get_result_labels,
    get_disposition_labels, get_position_labels, get_effect_labels,
    get_time_labels, get_dice_display_options, get_no_voice_sample_label,
    get_whisper_models, get_story_phase_labels,
    get_genres, get_tones, get_archetypes,
    get_genre_label, get_tone_label, get_archetype_label,
    translate_consequence,
    get_voice_options, get_tts_backends,
    resolve_voice_id, resolve_tts_backend,
    find_voice_label, find_tts_backend_label,
)
from voice import VoiceConfig, VoiceEngine

# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_voice_engine: Optional[VoiceEngine] = None


def get_voice_engine() -> VoiceEngine:
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine()
    return _voice_engine


# ---------------------------------------------------------------------------
# Server-side config: config.json → ENV override → defaults
# ---------------------------------------------------------------------------

def _load_server_config() -> dict:
    """Load server configuration with cascade: config.json → ENV override → defaults."""
    # 1. Defaults
    cfg = {
        "api_key": "",
        "invite_code": "",
        "enable_https": False,
        "ssl_certfile": "",
        "ssl_keyfile": "",
        "ssl_extra_sans": [],
        "storage_secret": "",
        "port": 8080,
        "default_ui_lang": "",
    }
    # 2. config.json overrides defaults
    from engine import load_global_config
    file_cfg = load_global_config()
    for key in cfg:
        if key in file_cfg:
            cfg[key] = file_cfg[key]
    # Normalize ssl_extra_sans: config.json may supply a plain string instead of a
    # list (e.g. "ssl_extra_sans": "77.21.237.27"). Convert to list so downstream
    # code can always iterate safely.
    if isinstance(cfg["ssl_extra_sans"], str):
        cfg["ssl_extra_sans"] = [s.strip() for s in cfg["ssl_extra_sans"].split(",") if s.strip()]
    # 3. ENV overrides config.json (for Docker, systemd, .bat, etc.)
    env_map = {
        "ANTHROPIC_API_KEY": "api_key",
        "INVITE_CODE": "invite_code",
        "ENABLE_HTTPS": "enable_https",
        "SSL_CERTFILE": "ssl_certfile",
        "SSL_KEYFILE": "ssl_keyfile",
        "SSL_EXTRA_SANS": "ssl_extra_sans",
        "STORAGE_SECRET": "storage_secret",
        "PORT": "port",
        "DEFAULT_UI_LANG": "default_ui_lang",
    }
    for env_key, cfg_key in env_map.items():
        env_val = os.environ.get(env_key, "").strip()
        if env_val:
            # Type coercion for non-string fields
            if cfg_key == "enable_https":
                cfg[cfg_key] = env_val.lower() in ("1", "true", "yes")
            elif cfg_key == "port":
                try:
                    cfg[cfg_key] = int(env_val)
                except ValueError:
                    pass
            elif cfg_key == "ssl_extra_sans":
                # ENV: comma-separated list, e.g. "77.21.237.27,myhost.example.com"
                cfg[cfg_key] = [s.strip() for s in env_val.split(",") if s.strip()]
            else:
                cfg[cfg_key] = env_val
    return cfg

_server_cfg = _load_server_config()
INVITE_CODE: str = _server_cfg["invite_code"]
SERVER_API_KEY: str = _server_cfg["api_key"]
ENABLE_HTTPS: bool = _server_cfg["enable_https"]
SSL_CERTFILE: str = _server_cfg["ssl_certfile"]
SSL_KEYFILE: str = _server_cfg["ssl_keyfile"]
SSL_EXTRA_SANS: list = _server_cfg["ssl_extra_sans"]  # Extra IPs/hostnames for SAN
SERVER_PORT: int = _server_cfg["port"]
# Validate default_ui_lang: must be a known code ('de', 'en', ...) or empty (→ DEFAULT_LANG)
_raw_ui_lang = _server_cfg.get("default_ui_lang", "").strip().lower()
DEFAULT_UI_LANG: str = _raw_ui_lang if _raw_ui_lang in UI_LANGUAGES.values() else ""

# Log config state (without secrets)
log(f"[Config] port={SERVER_PORT}, https={ENABLE_HTTPS}, "
    f"invite={'set' if INVITE_CODE else 'off'}, "
    f"default_ui_lang={DEFAULT_UI_LANG or DEFAULT_LANG}, "
    f"api_key={'ENV' if os.environ.get('ANTHROPIC_API_KEY') else ('config.json' if SERVER_API_KEY else 'not set')}"
    + (f", ssl_extra_sans={SSL_EXTRA_SANS}" if SSL_EXTRA_SANS else ""))

# Flush deferred dependency check results into log file
import builtins
_dep = getattr(builtins, "_EDGETALES_DEP_CHECK", None)
if _dep:
    log(f"[Deps] Found: {', '.join(_dep['found'])}")
    if _dep["optional_found"]:
        log(f"[Deps] Optional: {', '.join(_dep['optional_found'])}")
    if _dep["optional_missing"]:
        log(f"[Deps] Optional (not installed): {', '.join(_dep['optional_missing'])}")
    if _dep["missing_installed"]:
        log(f"[Deps] Auto-installed: {', '.join(_dep['missing_installed'])}")
    del builtins._EDGETALES_DEP_CHECK

# --- Tuning constants ---
SCROLL_DELAY_MS = 500                  # Delay before auto-scroll to new content
TEMP_CLEANUP_DELAY_SEC = 60.0          # Seconds before temp audio files are deleted
RECONNECT_TIMEOUT_SEC = 180            # WebSocket reconnect timeout (mobile-friendly)
INVITE_MAX_ATTEMPTS = 5                # Max failed invite code attempts before lockout
INVITE_LOCKOUT_SEC = 300               # Lockout duration in seconds (5 min)

# --- Invite code rate limiter ---
import time as _time
_invite_attempts: dict[str, list[float]] = {}  # IP → list of failed attempt timestamps
_invite_lock = __import__("threading").Lock()


def _check_invite_rate_limit(client_ip: str) -> bool:
    """Return True if the IP is allowed to attempt, False if locked out."""
    now = _time.time()
    with _invite_lock:
        attempts = _invite_attempts.get(client_ip, [])
        # Purge old attempts outside lockout window
        attempts = [ts for ts in attempts if now - ts < INVITE_LOCKOUT_SEC]
        _invite_attempts[client_ip] = attempts
        return len(attempts) < INVITE_MAX_ATTEMPTS


def _record_invite_failure(client_ip: str) -> None:
    """Record a failed invite code attempt."""
    with _invite_lock:
        _invite_attempts.setdefault(client_ip, []).append(_time.time())


# ---------------------------------------------------------------------------
# Session helpers (per-tab via app.storage.tab)
# ---------------------------------------------------------------------------

def S() -> dict:
    """Shortcut to per-tab storage."""
    return app.storage.tab


def L() -> str:
    """Get current UI language code from session (e.g. 'de' or 'en').
    Falls back to server-configured default_ui_lang (or DEFAULT_LANG)
    if called during a phase transition where the slot context has been destroyed."""
    _fallback = DEFAULT_UI_LANG or DEFAULT_LANG
    try:
        return S().get("ui_lang", _fallback)
    except RuntimeError:
        return _fallback


def _dice_string_to_index(val: str) -> int:
    """Migrate old localized dice_display strings to language-neutral index."""
    lower = val.lower()
    if "detail" in lower or "detailliert" in lower:
        return 2
    elif "einfach" in lower or "simple" in lower:
        return 1
    return 0


def _clean_narration(text: str) -> str:
    """Strip any leaked metadata from narration before display.
    Lightweight safety net — the engine's parse_narrator_response handles the
    primary cleanup. This catches only edge cases that slip through (unclosed
    tags, malformed code blocks, trailing metadata)."""
    import re
    # Unclosed tags at end of text (engine only strips properly closed tags)
    text = re.sub(r'<(?:game_data|new_npcs|memory_updates|scene_context|npc_rename)>[\s\S]*$', '', text)
    # Unclosed ```game_data, ```json, or any ```word code blocks
    text = re.sub(r'```\s*(?:\w+)\s*(?:\{[\s\S]*)?$', '', text)
    # Trailing bare ```word with no closing
    text = re.sub(r'```\w*\s*$', '', text)
    # Bold-bracket metadata blocks: **[char: state | location | threat | ...]**
    text = re.sub(r'\*{0,2}\[(?:[^\]]*\|){2,}[^\]]*\]\*{0,2}\s*$', '', text)
    # Bold-bracket game mechanic annotations: **[THREAT CLOCK CREATED: X - 0/4]**
    text = re.sub(r'\*{1,3}\[[^\]]+\]\*{1,3}', '', text)
    # Bare ALL-CAPS bracketed annotations that survived bold-stripping: [CLOCK ADVANCE: +1]
    text = re.sub(r'\[[A-Z][A-Z0-9 _\-]*:?[^\]]*\]', '', text)
    return text.strip()


# ---------------------------------------------------------------
# Dialog Highlighting (EdgeTales Design mode)
# Server-side Python marks quoted speech with ***bold-italic*** Markdown.
# Quote characters are placed OUTSIDE the *** delimiters because guillemets
# and curly quotes are Unicode punctuation (Ps/Pe) — placing *** inside them
# breaks CommonMark left-flanking detection and leaves *** as visible text.
# The opening quote is visually pulled into the highlight box via a negative
# margin-left on em strong; the closing quote is covered by the extended
# padding-right.  CSS selector: .chat-msg.assistant em strong.
# ---------------------------------------------------------------

def _highlight_dialog(text: str) -> str:
    """Wrap quoted speech in ***bold-italic*** Markdown for Dialog-Highlight mode.

    Quote characters are placed OUTSIDE the *** markers so the CommonMark
    left/right-flanking rules are satisfied for all Unicode quote styles.
    The CSS margin-left / padding-right on em strong visually encompasses
    both the opening and closing quote characters.

    CSS styles .chat-msg.assistant em strong (custom_head.html)."""
    import re

    def _wrap(open_q: str, content: str, close_q: str) -> str:
        inner = content.strip()
        if not inner:
            return open_q + content + close_q
        return f'{open_q}***{inner}***{close_q}'

    # DE standard: „..." — öffnet U+201E, schließt U+201D, U+201C oder gerades "
    text = re.sub(
        r'(\u201E)([^\u201E\u201C\u201D"\n]{1,600}?)([\u201C\u201D"])',
        lambda m: _wrap(m.group(1), m.group(2), m.group(3)), text)
    # EN curly: "..."
    text = re.sub(
        r'(\u201C)([^\u201C\u201D\n]{1,600}?)(\u201D)',
        lambda m: _wrap(m.group(1), m.group(2), m.group(3)), text)
    # Guillemets — both directions in a single pass to prevent cross-matching.
    text = re.sub(
        r'(\u00BB)([^\u00AB\u00BB\n]{1,600}?)(\u00AB)'   # »...«  reversed (DE/typographic)
        r'|(\u00AB)([^\u00AB\u00BB\n]{1,600}?)(\u00BB)',  # «...»  normal
        lambda m: (_wrap(m.group(1), m.group(2), m.group(3)) if m.group(1)
                   else _wrap(m.group(4), m.group(5), m.group(6))),
        text)
    # Straight ASCII double quotes: "..." — embedded/murmured dialog.
    # Negative lookbehind (?<!\*\*\*) prevents matching the trailing ASCII "
    # that the DE pass leaves after „***content***" — without it that " would
    # be treated as an opening quote and match all text up to the next ".
    text = re.sub(
        r'(?<!\*\*\*)"([^"\n]{1,600}?)"',
        lambda m: _wrap('"', m.group(1), '"'), text)
    # EN single curly: '...' — UK style primary quotes, nested inside double
    text = re.sub(
        r'(\u2018)([^\u2018\u2019\n]{1,600}?)(\u2019)',
        lambda m: _wrap(m.group(1), m.group(2), m.group(3)), text)
    # French single guillemets: ‹...› — nested quotes inside «»
    text = re.sub(
        r'(\u2039)([^\u2039\u203A\n]{1,600}?)(\u203A)',
        lambda m: _wrap(m.group(1), m.group(2), m.group(3)), text)
    return text

# ---------------------------------------------------------------
# Entity Highlighting (EdgeTales Design mode)
# Builds a data payload of known NPC names (colored by disposition)
# and the player name (accent color).
# The JS function _etHighlight() in custom_head.html walks the DOM
# after markdown rendering and wraps matched names in <span> elements.
# ---------------------------------------------------------------

_DISPOSITION_CSS = {
    "friendly": "et-npc-warm",  "loyal": "et-npc-warm",
    "hostile": "et-npc-hostile", "aggressive": "et-npc-hostile",
    "fearful": "et-npc-wary",   "wary": "et-npc-wary",
}

def _build_entity_data(game) -> dict:
    """Build entity highlight payload from game state for JS post-processing.
    Includes NPC names (colored by disposition) and player name (accent)."""
    entities = []
    seen = set()

    def _add(name: str, cls: str):
        if name and name not in seen and len(name) >= 3:
            entities.append({"name": name, "cls": cls})
            seen.add(name)

    # Player name — full name + parts ≥ 4 chars
    if game.player_name:
        _add(game.player_name, "et-player")
        for part in game.player_name.split():
            if len(part) >= 4:
                _add(part, "et-player")

    # NPC names — colored by disposition
    for npc in game.npcs:
        status = npc.get("status", "active")
        if status == "inactive":
            continue
        disp = npc.get("disposition", "neutral")
        css_cls = _DISPOSITION_CSS.get(disp, "")
        if not css_cls:
            continue  # neutral/curious: no coloring, blend with text
        name = npc.get("name", "")
        _add(name, css_cls)
        for part in name.split():
            if len(part) >= 4:
                _add(part, css_cls)
        for alias in npc.get("aliases", []):
            if len(alias) >= 4:
                _add(alias, css_cls)

    # Sort longest-first to avoid partial matches (e.g. "Anna" inside "Annabelle")
    entities.sort(key=lambda e: len(e["name"]), reverse=True)
    return {"entities": entities}


def _inject_entity_highlights(game, scope_new: bool = False) -> None:
    """Inject JS call to highlight entity names in narrator text (Design mode only).
    scope_new=True → only process elements with .et-new class (live turn optimization)."""
    import json as _json
    data = _build_entity_data(game)
    if data["entities"]:
        _scope = "true" if scope_new else "false"
        ui.run_javascript(f"setTimeout(function(){{ _etHighlight({_json.dumps(data, ensure_ascii=False)},{_scope}); }}, 80)")


def init_session() -> None:
    """Initialize session state for a new tab."""
    s = S()
    s.setdefault("authenticated", False)
    s.setdefault("current_user", "")
    s.setdefault("api_key", "")
    s.setdefault("messages", [])
    s.setdefault("game", None)
    s.setdefault("creation", None)
    s.setdefault("pending_burn", None)
    s.setdefault("pending_tts", None)
    s.setdefault("active_save", "autosave")
    s.setdefault("global_config_loaded", False)
    s.setdefault("processing", False)  # Double-send guard
    s.setdefault("_turn_gen", 0)       # Incremented on save load/new game — stale response guard
    # API key: prefer server-side env var, fall back to config file
    if not s["global_config_loaded"]:
        if SERVER_API_KEY:
            s["api_key"] = SERVER_API_KEY
        else:
            gcfg = load_global_config()
            s["api_key"] = gcfg.get("api_key", "")
        s["global_config_loaded"] = True


def get_engine_config() -> EngineConfig:
    s = S()
    # Pass display label directly — get_narration_lang() converts to English name
    return EngineConfig(narration_lang=s.get("narration_lang", "Deutsch"), kid_friendly=s.get("kid_friendly", False))


def get_voice_config() -> VoiceConfig:
    s = S()
    lang_label = s.get("narration_lang", "Deutsch")
    lang_english = LANGUAGES.get(lang_label, "German")
    backend_label = s.get("tts_backend", "")
    backend_code = resolve_tts_backend(backend_label) if backend_label else "edge_tts"
    return VoiceConfig(
        tts_enabled=s.get("tts_enabled", False),
        stt_enabled=s.get("stt_enabled", False),
        tts_backend=backend_code,
        voice_select=s.get("voice_select", ""),
        tts_rate=s.get("tts_rate", "+0%"),
        cb_device=s.get("cb_device", "Auto"),
        cb_exaggeration=s.get("cb_exaggeration", 0.5),
        cb_cfg_weight=s.get("cb_cfg_weight", 0.5),
        cb_voice_sample=s.get("cb_voice_sample", ""),
        whisper_size=s.get("whisper_size", "medium"),
        narration_lang=lang_english,
    )


def load_user_settings(username: str) -> None:
    s = S()
    cfg = load_user_config(username)
    _fallback = DEFAULT_UI_LANG or DEFAULT_LANG
    s["ui_lang"] = cfg.get("ui_lang", _fallback)
    lang = s["ui_lang"]
    s["narration_lang"] = cfg.get("narration_lang", "Deutsch")
    s["tts_enabled"] = cfg.get("tts_enabled", False)
    s["stt_enabled"] = cfg.get("stt_enabled", False)
    # Voice/backend: accept both codes (new) and localized labels (legacy)
    saved_voice = cfg.get("voice_select", "")
    voice_id = resolve_voice_id(saved_voice) if saved_voice else "de-DE-ConradNeural"
    s["voice_select"] = find_voice_label(voice_id, lang)
    s["tts_rate"] = cfg.get("tts_rate", "+0%")
    s["whisper_size"] = cfg.get("whisper_size", "medium")
    # dice_display: store as index (0=off, 1=simple, 2=detailed) for language independence
    raw_dice = cfg.get("dice_display", 0)
    if isinstance(raw_dice, str):
        # Migrate old string-based setting to index
        raw_dice = _dice_string_to_index(raw_dice)
    s["dice_display"] = raw_dice
    s["kid_friendly"] = cfg.get("kid_friendly", False)
    s["sr_chat"] = cfg.get("sr_chat", True)
    saved_backend = cfg.get("tts_backend", "")
    backend_code = resolve_tts_backend(saved_backend) if saved_backend else "edge_tts"
    s["tts_backend"] = find_tts_backend_label(backend_code, lang)
    s["cb_device"] = cfg.get("cb_device", "Auto")
    s["cb_exaggeration"] = cfg.get("cb_exaggeration", 0.5)
    s["cb_cfg_weight"] = cfg.get("cb_cfg_weight", 0.5)
    # Voice sample: "" or missing → no-sample label; filename → keep as-is
    saved_sample = cfg.get("cb_voice_sample", "")
    s["cb_voice_sample"] = get_no_voice_sample_label(lang) if not saved_sample else saved_sample
    s["narrator_font"] = cfg.get("narrator_font", "highlight")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_roll_data(roll: RollResult, consequences=None, clock_events=None, brain=None, chaos_interrupt=None) -> dict:
    lang = L()
    rl = get_result_labels(lang)
    result_label, _ = rl.get(roll.result, ("?", "info"))
    ml = get_move_labels(lang)
    sl = get_stat_labels(lang)
    return {
        "move": roll.move, "move_label": ml.get(roll.move, roll.move),
        "stat_name": roll.stat_name, "stat_label": sl.get(roll.stat_name, roll.stat_name),
        "stat_value": roll.stat_value,
        "d1": roll.d1, "d2": roll.d2, "c1": roll.c1, "c2": roll.c2,
        "action_score": roll.action_score,
        "score_display": (
            f"{roll.d1 + roll.d2 + roll.stat_value}\u219210"
            if roll.d1 + roll.d2 + roll.stat_value > 10
            else str(roll.action_score)
        ),
        "result": roll.result, "result_label": result_label,
        "match": getattr(roll, "match", roll.c1 == roll.c2),
        "consequences": consequences or [], "clock_events": clock_events or [],
        "position": brain.get("position", "risky") if brain else "risky",
        "effect": brain.get("effect", "standard") if brain else "standard",
        "chaos_interrupt": chaos_interrupt or "",
    }


# Scroll helpers — documentElement is the scroll container
async def _scroll_chat_bottom(delay_ms: int = 0) -> None:
    """Scroll to bottom of page (instant by default for DOM forcing)."""
    try:
        await ui.run_javascript(f'''
            setTimeout(() => {{
                document.documentElement.scrollTo({{top: document.documentElement.scrollHeight}});
            }}, {delay_ms or 10});
        ''', timeout=3.0)
    except TimeoutError:
        pass

async def _scroll_to_element(element_id: str) -> None:
    """Scroll smoothly so element is near top of viewport."""
    try:
        await ui.run_javascript(f'''
            setTimeout(() => {{
                const el = document.getElementById("{element_id}");
                if (el) el.scrollIntoView({{behavior: "smooth", block: "start"}});
            }}, {SCROLL_DELAY_MS});
        ''', timeout=3.0)
    except TimeoutError:
        pass


def render_audio_player(audio_bytes: bytes, fmt: str = "audio/mp3", autoplay: bool = False):
    """Render an HTML5 audio player by serving audio as a temp file.
    Schedules delayed deletion of the temp file after serving.
    Returns the NiceGUI audio element for lifecycle tracking."""
    _run_temp_cleanup()  # Clean up old temp files first
    ext = ".mp3" if "mp3" in fmt else ".wav" if "wav" in fmt else ".ogg"
    tmp = Path(tempfile.gettempdir()) / f"rpg_audio_{uuid.uuid4().hex[:8]}{ext}"
    tmp.write_bytes(audio_bytes)
    url = app.add_media_file(local_file=tmp)
    log(f"[Audio] Serving {len(audio_bytes)} bytes as {url}")
    a = ui.audio(url, autoplay=autoplay).classes("w-full").style("margin: 0.4em 0;")
    a.props(f'aria-label="{t("aria.narration_audio", L())}"')
    # Autoplay fallback: if browser blocks autoplay, retry on next user interaction
    if autoplay:
        ui.run_javascript(f'''
            (() => {{
                const audioEl = getElement({a.id}).$el;
                if (!audioEl) return;
                const tryPlay = audioEl.play();
                if (tryPlay) tryPlay.catch(() => {{
                    const handler = () => {{
                        audioEl.play().catch(() => {{}});
                        document.removeEventListener("click", handler);
                        document.removeEventListener("keydown", handler);
                    }};
                    document.addEventListener("click", handler, {{once: true}});
                    document.addEventListener("keydown", handler, {{once: true}});
                }});
            }})()
        ''')
    # Schedule temp file cleanup after browser had time to download (60s)
    _schedule_temp_cleanup(tmp)
    return a


# --- Temp file cleanup ---
_temp_cleanup_files: list[tuple[float, Path]] = []
_temp_cleanup_lock = __import__("threading").Lock()

def _schedule_temp_cleanup(path: Path, delay_sec: float = TEMP_CLEANUP_DELAY_SEC) -> None:
    """Track temp file for delayed cleanup."""
    import time
    with _temp_cleanup_lock:
        _temp_cleanup_files.append((time.time() + delay_sec, path))

def _run_temp_cleanup() -> None:
    """Delete temp files that have passed their cleanup time."""
    import time
    now = time.time()
    with _temp_cleanup_lock:
        remaining = []
        for deadline, path in _temp_cleanup_files:
            if now >= deadline:
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    pass
            else:
                remaining.append((deadline, path))
        _temp_cleanup_files.clear()
        _temp_cleanup_files.extend(remaining)


async def do_tts(narration: str, chat_container=None, autoplay: bool = True) -> None:
    """Run TTS in background thread if enabled. Renders audio player inline (ephemeral).
    Only the most recent audio player is kept — previous ones are removed from the DOM."""
    s = S()
    if not s.get("tts_enabled", False):
        return
    # Remove previous audio player (only keep the latest)
    prev_player = s.pop("_tts_player", None)
    if prev_player:
        try:
            prev_player.delete()
        except Exception:
            pass
    # Show loading indicator
    tts_indicator = None
    if chat_container:
        with chat_container:
            tts_indicator = ui.row().classes("w-full items-center gap-2")
            tts_indicator.props('role="status"')
            with tts_indicator:
                ui.spinner("audio", size="sm", color="primary")
                ui.label(t("tts.generating", L())).classes("text-xs").style("color: var(--text-secondary)")
    try:
        vcfg = get_voice_config()
        eng = get_voice_engine()
        log(f"[TTS] Starting TTS, backend={vcfg.tts_backend}, voice={vcfg.voice_select}, text_len={len(narration)}")
        audio, fmt = await asyncio.to_thread(eng.text_to_speech, narration, vcfg)
        # Remove loading indicator
        if tts_indicator:
            tts_indicator.delete()
        if audio:
            log(f"[TTS] Audio generated: {len(audio)} bytes, format={fmt}")
            if chat_container:
                with chat_container:
                    player = render_audio_player(audio, fmt, autoplay=autoplay)
                    s["_tts_player"] = player
        else:
            log("[TTS] Backend returned None — no audio generated.", level="warning")
            ui.notify(t("tts.no_audio", L()), type="warning")
    except Exception as e:
        if tts_indicator:
            tts_indicator.delete()
        log(f"[TTS] Error: {e}", level="warning")
        ui.notify(t("tts.error", L(), error=e), type="warning")


# ---------------------------------------------------------------------------
# STT Microphone recording
# ---------------------------------------------------------------------------

def _setup_stt_button(mic_btn, inp, chat_container, stt_status, stt_status_content, sidebar_container=None, sidebar_refresh=None):
    """Set up the microphone button for speech-to-text recording.
    Uses browser MediaRecorder → base64 → server-side Whisper transcription.
    Shows inline status with waveform animation below the input bar."""
    s = S()
    recording_state = {"active": False}

    _WAVEFORM_HTML = (
        '<span class="stt-waveform">'
        '<span class="wv-bar"></span><span class="wv-bar"></span><span class="wv-bar"></span>'
        '<span class="wv-bar"></span><span class="wv-bar"></span><span class="wv-bar"></span>'
        '<span class="wv-bar"></span></span>'
    )

    def _show_status(html_content: str):
        """Show inline status below input."""
        stt_status_content.content = html_content
        stt_status.classes(remove="hidden")

    def _hide_status():
        """Hide the inline status row."""
        stt_status.classes(add="hidden")
        stt_status_content.content = ""

    async def _hide_status_delayed(ms: int = 2000):
        """Hide status after a delay."""
        await asyncio.sleep(ms / 1000)
        _hide_status()

    async def toggle_recording():
        if not recording_state["active"]:
            # Start recording
            recording_state["active"] = True
            recording_state["_stt_chunks"] = {}
            mic_btn.props(f'color=red aria-label="{t("aria.stop_recording", L())}"')
            mic_btn._props["icon"] = "stop"
            mic_btn.update()
            _show_status(f'{_WAVEFORM_HTML} <span style="color: var(--error)">{t("stt.recording", L())} <span id="_sttTimer">0:00</span></span>')
            # Fire-and-forget: getUserMedia may show a permission dialog that blocks JS.
            # Wrapping in an async IIFE prevents Python from waiting on the dialog.
            ui.run_javascript(f'''
                (async () => {{
                if (window._rpgRecorder && window._rpgRecorder.state === "recording") return;
                try {{
                    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
                        throw new Error("Microphone requires HTTPS");
                    }}
                    const stream = await navigator.mediaDevices.getUserMedia({{audio: true}});
                    window._rpgRecorder = new MediaRecorder(stream, {{mimeType: "audio/webm;codecs=opus"}});
                    window._rpgChunks = [];
                    window._rpgRecorder.ondataavailable = e => {{ if (e.data.size > 0) window._rpgChunks.push(e.data); }};
                    // Recording timer
                    window._rpgRecStart = Date.now();
                    window._rpgTimerIv = setInterval(() => {{
                        const el = document.getElementById("_sttTimer");
                        if (!el) {{ clearInterval(window._rpgTimerIv); return; }}
                        const s = Math.floor((Date.now() - window._rpgRecStart) / 1000);
                        el.textContent = Math.floor(s/60) + ":" + String(s%60).padStart(2,"0");
                    }}, 500);
                    // Auto-stop after max duration (2 minutes)
                    window._rpgMaxTimer = setTimeout(() => {{
                        if (window._rpgRecorder && window._rpgRecorder.state === "recording") {{
                            window._rpgRecorder.stop();
                        }}
                    }}, 120000);
                    window._rpgRecorder.onstop = async () => {{
                        clearInterval(window._rpgTimerIv);
                        clearTimeout(window._rpgMaxTimer);
                        stream.getTracks().forEach(t => t.stop());
                        // Notify Python that recording stopped (handles auto-stop case)
                        getElement({mic_btn.id}).$emit("stt_stopped", {{}});
                        const blob = new Blob(window._rpgChunks, {{type: "audio/webm"}});
                        const reader = new FileReader();
                        reader.onloadend = () => {{
                            try {{
                                const b64 = reader.result.split(",")[1];
                                const CHUNK = 500000;
                                const total = Math.ceil(b64.length / CHUNK);
                                if (total <= 1) {{
                                    getElement({mic_btn.id}).$emit("stt_audio", {{audio: b64}});
                                }} else {{
                                    for (let i = 0; i < total; i++) {{
                                        getElement({mic_btn.id}).$emit("stt_chunk", {{
                                            data: b64.slice(i * CHUNK, (i+1) * CHUNK),
                                            index: i, total: total
                                        }});
                                    }}
                                }}
                            }} catch(err) {{
                                getElement({mic_btn.id}).$emit("stt_error", {{error: err.message || "Send failed"}});
                            }}
                        }};
                        reader.readAsDataURL(blob);
                    }};
                    window._rpgRecorder.start();
                }} catch(err) {{
                    getElement({mic_btn.id}).$emit("stt_error", {{error: err.message}});
                }}
                }})();
            ''')
        else:
            # Stop recording — reset UI immediately (don't wait for audio processing)
            recording_state["active"] = False
            mic_btn.props(remove="color")
            mic_btn.props(f'aria-label="{t("aria.start_recording", L())}"')
            mic_btn._props["icon"] = "mic"
            mic_btn.update()
            _show_status(f'<span class="stt-spinner-inline"></span> {t("stt.transcribing", L())}')
            await ui.run_javascript('''
                clearInterval(window._rpgTimerIv);
                clearTimeout(window._rpgMaxTimer);
                if (window._rpgRecorder && window._rpgRecorder.state === "recording") {
                    window._rpgRecorder.stop();
                }
            ''')

    async def _transcribe_and_send(b64: str):
        """Common handler: decode base64 audio, transcribe, and send as player input."""
        _lang = L()  # Capture now — L() loses NiceGUI request context after await
        _show_status(f'<span class="stt-spinner-inline"></span> {t("stt.transcribing", _lang)}')

        async def _keepalive():
            """Periodically update the spinner to prevent WebSocket timeout
            during long transcriptions on slow hardware (e.g. Raspberry Pi CPU)."""
            elapsed = 0
            while True:
                await asyncio.sleep(10)
                elapsed += 10
                _show_status(
                    f'<span class="stt-spinner-inline"></span>'
                    f' {t("stt.transcribing", _lang)} ({elapsed}s)'
                )

        _ka_task = asyncio.create_task(_keepalive())
        try:
            import base64 as b64mod
            audio_bytes = b64mod.b64decode(b64)
            log(f"[STT] Received audio: {len(audio_bytes)/1024:.0f} KB")
            vcfg = get_voice_config()
            eng = get_voice_engine()
            text = await asyncio.to_thread(eng.speech_to_text, audio_bytes, vcfg)
            if text and text.strip():
                _hide_status()
                inp.value = ""
                await process_player_input(text.strip(), chat_container, sidebar_container, sidebar_refresh=sidebar_refresh)
            else:
                _show_status(f'{E["warn"]} <span style="color: var(--accent-light)">{t("stt.no_speech", L())}</span>')
                asyncio.create_task(_hide_status_delayed(3000))
        except Exception as ex:
            log(f"[STT] Error: {ex}", level="warning")
            _show_status(f'{E["x_mark"]} <span style="color: var(--error)">{t("stt.error", L(), error=ex)}</span>')
            asyncio.create_task(_hide_status_delayed(4000))
        finally:
            _ka_task.cancel()

    async def handle_audio(e):
        """Receive complete base64 audio from browser (small recordings)."""
        # UI already reset in toggle_recording stop branch
        b64 = e.args.get("audio", "") if isinstance(e.args, dict) else ""
        if not b64:
            _hide_status()
            return
        await _transcribe_and_send(b64)

    async def handle_chunk(e):
        """Receive chunked base64 audio (for recordings that exceed WS message limit)."""
        args = e.args if isinstance(e.args, dict) else {}
        data = args.get("data", "")
        idx = args.get("index", 0)
        total = args.get("total", 1)
        if not data:
            return
        recording_state["_stt_chunks"][idx] = data
        log(f"[STT] Chunk {idx + 1}/{total} received ({len(data)/1024:.0f} KB)")
        if len(recording_state["_stt_chunks"]) >= total:
            # All chunks received — reassemble and transcribe
            full_b64 = "".join(recording_state["_stt_chunks"][i] for i in range(total))
            recording_state["_stt_chunks"] = {}
            await _transcribe_and_send(full_b64)

    async def handle_error(e):
        """Handle microphone access errors."""
        recording_state["active"] = False
        mic_btn.props(remove="color")
        mic_btn.props(f'aria-label="{t("aria.start_recording", L())}"')
        mic_btn._props["icon"] = "mic"
        mic_btn.update()
        err = e.args.get("error", t("stt.unknown", L())) if isinstance(e.args, dict) else t("stt.unknown", L())
        _show_status(f'{E["x_mark"]} <span style="color: var(--error)">{t("stt.mic_error", L(), error=err)}</span>')
        asyncio.create_task(_hide_status_delayed(4000))

    async def handle_stopped(_e):
        """Reset UI when recording stops (covers auto-stop from max duration)."""
        if recording_state["active"]:
            recording_state["active"] = False
            mic_btn.props(remove="color")
            mic_btn.props(f'aria-label="{t("aria.start_recording", L())}"')
            mic_btn._props["icon"] = "mic"
            mic_btn.update()
            _show_status(f'<span class="stt-spinner-inline"></span> {t("stt.transcribing", L())}')

    mic_btn.on("click", toggle_recording)
    mic_btn.on("stt_audio", handle_audio)
    mic_btn.on("stt_chunk", handle_chunk)
    mic_btn.on("stt_stopped", handle_stopped)
    mic_btn.on("stt_error", handle_error)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS_FILE = Path(__file__).resolve().parent / "custom_head.html"
CUSTOM_CSS = _CSS_FILE.read_text(encoding="utf-8") if _CSS_FILE.exists() else ""


# ===============================================================
# USER SELECTION — now built inline by main_page phases
# ===============================================================


# ===============================================================
# SIDEBAR
# ===============================================================

# Articles that mark a descriptor alias (not a real name or nickname).
# Used by _display_aliases() to suppress these from the UI.
_DESCRIPTOR_ARTICLES = {
    "der", "die", "das", "dem", "den", "des",  # German def. articles
    "ein", "eine", "einem", "einen", "eines",   # German indef. articles
    "the", "a", "an",                            # English articles
}


def _display_aliases(aliases: list) -> list:
    """Filter NPC aliases for sidebar display: suppress descriptor-style aliases
    that the dedup system accumulates as lookup keys but are ugly to show.

    Kept (display-worthy):  'Cremon', 'der Fass-Schläger', 'Vertreter', 'Black Hand'
    Suppressed (lookup-only): 'Ein zweiter Mann in braunem Wams',
                               'Der Mann im braunen Wams', 'kandidatin_blonde'
    Rules:
    - More than 4 words → verbose descriptor, suppress
    - Contains an underscore → snake_case stub, suppress
    - First word is a German/English article AND 3+ total words → descriptor, suppress
      (2-word combos like 'der Fass-Schläger' are legitimate epithets and kept)
    Empty alias list → empty list (no-op)."""
    result = []
    for alias in aliases:
        if not alias:
            continue
        if "_" in alias:
            continue
        words = alias.split()
        if len(words) > 4:
            continue
        if words[0].lower() in _DESCRIPTOR_ARTICLES and len(words) >= 3:
            continue
        result.append(alias)
    return result


def render_sidebar_status(game: GameState, session=None) -> None:
    s = session or S()
    lang = s.get("ui_lang", DEFAULT_UI_LANG or DEFAULT_LANG) if session else L()
    kid = s.get("kid_friendly", False)
    sl = get_stat_labels(lang)
    _name_aria = game.player_name.replace('"', '&quot;')
    ui.label(f"{E['mask']} {game.player_name}").classes("text-lg font-bold").props(f'aria-label="{_name_aria}"')
    ui.label(game.character_concept).classes("text-sm text-gray-400 italic")
    if kid: ui.label(f"{E['green_heart']} {t('sidebar.kid_mode', lang)}").classes("text-xs text-green-400")
    tl = get_time_labels(lang)
    t_label = tl.get(game.time_of_day, "") if game.time_of_day else ""
    t_disp = f" {E['dash']} {t_label}" if t_label else ""
    _loc_aria = f"{t('aria.location', lang)}: {game.current_location} {E['dash']} {t('sidebar.scene', lang)} {game.scene_count}{t_disp}".replace('"', '&quot;')
    ui.label(f"{E['pin']} {game.current_location} {E['dash']} {t('sidebar.scene', lang)} {game.scene_count}{t_disp}").classes("text-xs text-gray-400").props(f'aria-label="{_loc_aria}"')
    if game.crisis_mode and not game.game_over:
        ui.label(f"{E['warn']} {t('sidebar.crisis_kid', lang) if kid else t('sidebar.crisis', lang)}").classes("text-sm text-red-400 font-bold mt-2")
    if game.game_over:
        ui.label(f"{E['skull']} {t('sidebar.finale', lang)}").classes("text-sm text-red-400 font-bold mt-2")
    ui.separator()
    # Stats (5 core stats; momentum rendered separately below)
    # Use ui.element() nesting — NiceGUI applies classes via its own mechanism,
    # avoiding the desktop browser issue where innerHTML class attributes are stripped.
    _stat_specs = [
        (sl['edge'],   game.get_stat('edge'),   t('aria.stat_item', lang, label=sl['edge'],   value=int(game.get_stat('edge')))),
        (sl['shadow'], game.get_stat('shadow'), t('aria.stat_item', lang, label=sl['shadow'], value=int(game.get_stat('shadow')))),
        (sl['heart'],  game.get_stat('heart'),  t('aria.stat_item', lang, label=sl['heart'],  value=int(game.get_stat('heart')))),
        (sl['wits'],   game.get_stat('wits'),   t('aria.stat_item', lang, label=sl['wits'],   value=int(game.get_stat('wits')))),
        (sl['iron'],   game.get_stat('iron'),   t('aria.stat_item', lang, label=sl['iron'],   value=int(game.get_stat('iron')))),
        (t('sidebar.momentum', lang), f"{game.momentum}/{game.max_momentum}",
         t('aria.momentum_stat', lang, current=int(game.momentum), max=int(game.max_momentum))),
    ]
    with ui.element('div').classes('stat-grid w-full'):
        for _lbl, _val, _aria in _stat_specs:
            _aria_esc = _aria.replace('"', '&quot;')
            with ui.element('div').classes('stat-item').props(f'role="text" aria-label="{_aria_esc}"'):
                ui.html(str(_lbl)).classes('stat-label').props('aria-hidden="true"')
                ui.html(str(_val)).classes('stat-value').props('aria-hidden="true"')
    ui.separator()
    # Tracks — label already communicates value, progressbar is visual-only
    for track, label, cls in [("health",f"{E['heart_red']} {t('sidebar.health', lang)}","health"),("spirit",f"{E['heart_blue']} {t('sidebar.spirit', lang)}","spirit"),("supply",f"{E['yellow_dot']} {t('sidebar.supply', lang)}","supply")]:
        val = int(getattr(game, track))
        pct = max(0, val / 5 * 100)
        ui.label(f"{label}: {val}/5").classes("text-sm font-semibold")
        with ui.element('div').classes('track-bar w-full').props('aria-hidden="true"'):
            ui.element('div').classes(f'track-fill {cls}').style(f'width:{pct:.0f}%')
    # Chaos — label only; danger level in progressbar aria-label for screen readers
    ui.separator()
    chaos = int(game.chaos_factor)
    pct = max(0, chaos / 9 * 100)
    _chaos_level_key = "aria.chaos_low" if chaos <= 4 else ("aria.chaos_medium" if chaos <= 6 else ("aria.chaos_high" if chaos <= 8 else "aria.chaos_critical"))
    _chaos_level = t(_chaos_level_key, lang)
    _chaos_aria = t("aria.chaos_bar", lang, n=chaos, level=_chaos_level)
    ui.label(f'{E["tornado"]} {t("sidebar.chaos", lang)}: {chaos}/9').classes("text-sm font-semibold w-full")
    with ui.element('div').classes('track-bar w-full') \
            .props(f'role="progressbar" aria-valuenow="{int(pct)}" aria-valuemin="0" aria-valuemax="100" aria-label="{_chaos_aria}"'):
        ui.element('div').classes('track-fill chaos').style(f'width:{pct:.0f}%')
    # Chaos ambient glow + letter pulse (highlight mode)
    _chaos_js = "document.body.setAttribute('data-chaos-high','')" if chaos >= 7 else "document.body.removeAttribute('data-chaos-high')"
    _chaos_js += "; _etLetterPulse(" + ("true" if chaos >= 8 else "false") + ");"
    ui.run_javascript(_chaos_js)
    # Health vignette: opacity steigt wenn Gesundheit <= 3 sinkt (highlight mode)
    _health = int(game.health)
    _vignette_op = {5: 0.0, 4: 0.0, 3: 0.18, 2: 0.40, 1: 0.62, 0: 0.82}.get(_health, 0.0)
    ui.run_javascript(f"document.body.style.setProperty('--health-vignette', '{_vignette_op}')")
    # Clocks — label already communicates value, progressbar is visual-only
    active = [c for c in game.clocks if not c.get("fired")]
    if active:
        ui.separator()
        ui.label(f"{E['clock']} {t('sidebar.clocks', lang)}").classes("text-sm font-semibold")
        for c in active:
            em = E['red_circle'] if c["clock_type"]=="threat" else E['purple_circle']
            _c_filled = int(c["filled"])
            _c_segs = int(c["segments"])
            p = _c_filled / _c_segs * 100
            ui.label(f"{em} {c['name']}: {_c_filled}/{_c_segs}").classes("text-xs")
            with ui.element('div').classes('track-bar w-full').props('aria-hidden="true"'):
                ui.element('div').classes('track-fill progress').style(f'width:{p:.0f}%')
    # Story arc
    if game.story_blueprint and game.story_blueprint.get("acts"):
        bp = game.story_blueprint
        act = get_current_act(game)
        st_type = bp.get("structure_type","3act")
        ui.separator()
        si = E['cherry'] if st_type=="kishotenketsu" else E['book']
        sl_arc = "Kish\u014dtenketsu" if st_type=="kishotenketsu" else t("sidebar.3act", lang)
        ch_l = f" {E['dash']} {t('sidebar.chapter', lang)} {game.chapter_number}" if game.chapter_number > 1 else ""
        ui.label(f"{si} {sl_arc}{ch_l}").classes("text-sm font-semibold")
        act_l = t("sidebar.act", lang)
        pl = get_story_phase_labels(lang)
        for i,a in enumerate(bp["acts"]):
            an = i+1; sr = a.get("scene_range",[1,20]); phase = pl.get(a["phase"],a["phase"])
            if an < act["act_number"]: ui.label(f"{act_l} {an} {E['check']}").classes("text-xs text-gray-500")
            elif an == act["act_number"]:
                p = max(0,min(100,(game.scene_count-sr[0])/max(1,sr[1]-sr[0])*100))
                _act_aria = t("aria.story_progress", lang, n=an)
                ui.label(f"{E['play']} {act_l} {an} {E['dash']} {phase}").classes("text-xs font-bold")
                with ui.element('div').classes('track-bar w-full') \
                        .props(f'role="progressbar" aria-valuenow="{int(p)}" aria-valuemin="0" aria-valuemax="100" aria-label="{_act_aria}"'):
                    ui.element('div').classes('track-fill progress').style(f'width:{p:.0f}%')
            else: ui.label(f"{act_l} {an}").classes("text-xs text-gray-500")
        if bp.get("story_complete") and not getattr(game, "epilogue_dismissed", False):
            ui.label(f"{E['star']} {t('sidebar.story_complete', lang)}").classes("text-xs text-amber-400 font-bold mt-1")
    # NPCs
    active_npcs = [n for n in game.npcs if n.get("status")=="active" and n.get("introduced",True)]
    background_npcs = [n for n in game.npcs if n.get("status") in ("background", "lore") and n.get("introduced",True)]
    deceased_npcs = [n for n in game.npcs if n.get("status")=="deceased"]
    if active_npcs or background_npcs or deceased_npcs:
        # Sort by bond (desc), then by most recent memory scene (desc)
        def _npc_sort_key(n):
            last_scene = max((m.get("scene") or 0 for m in n.get("memory", []) if isinstance(m, dict)), default=0)
            return (-n.get("bond", 0), -(last_scene or 0))
        ui.separator()
        dl = get_disposition_labels(lang)
        bond_label = t("sidebar.bond", lang)
        aka_label = t("sidebar.npc_aka", lang)
        if active_npcs:
            active_npcs.sort(key=_npc_sort_key)
            ui.label(f"{E['people']} {t('sidebar.persons', lang)}").classes("text-sm font-semibold")
            for n in active_npcs:
                disp = dl.get(n["disposition"], f"{E['white_circle']} Neutral")
                bond_max = n.get("bond_max", 4)
                with ui.expansion(f"{disp} {E['dash']} {n['name']}").classes("w-full"):
                    _da = _display_aliases(n.get("aliases", []))
                    alias_str = f"{aka_label} {', '.join(_da)}" if _da else ""
                    with ui.element('div').classes('npc-card'):
                        ui.label(f'{bond_label}: {n["bond"]}/{bond_max}').classes('npc-meta')
                        if alias_str:
                            ui.label(alias_str).classes('npc-meta').style('font-style:italic')
                        if n.get("description"):
                            ui.label(n["description"]).classes('npc-desc')
        if background_npcs:
            background_npcs.sort(key=_npc_sort_key)
            with ui.expansion(f"{E['people']} {t('sidebar.known_persons', lang)} ({len(background_npcs)})").classes("w-full"):
                for n in background_npcs:
                    disp = dl.get(n["disposition"], f"{E['white_circle']} Neutral")
                    bond_max = n.get("bond_max", 4)
                    with ui.expansion(f"{disp} {E['dash']} {n['name']}").classes("w-full").style("opacity:0.75"):
                        _da = _display_aliases(n.get("aliases", []))
                        alias_str = f"{aka_label} {', '.join(_da)}" if _da else ""
                        with ui.element('div').classes('npc-card'):
                            ui.label(f'{bond_label}: {n["bond"]}/{bond_max}').classes('npc-meta')
                            if alias_str:
                                ui.label(alias_str).classes('npc-meta').style('font-style:italic')
                            if n.get("description"):
                                ui.label(n["description"]).classes('npc-desc')
        if deceased_npcs:
            with ui.expansion(f"\u2620\ufe0f {t('sidebar.deceased_persons', lang)} ({len(deceased_npcs)})").classes("w-full"):
                for n in deceased_npcs:
                    ui.label(f"\u2620\ufe0f {n['name']}").classes("text-xs").style("opacity: 0.4; text-decoration: line-through; padding: 0.15rem 0.5rem")


def render_sidebar_actions(on_switch_user=None, on_refresh=None, saves_open=False, on_chapter_view_change=None) -> None:
    s = S()
    lang = L()
    game = s.get("game")
    username = s["current_user"]
    ui.separator()
    # Recap
    recap_status = None
    async def do_recap():
        nonlocal recap_status
        if s.get("processing", False):
            return
        if s["api_key"] and game and len(game.session_log) >= 2:
            s["processing"] = True
            if recap_status:
                recap_status.text = f"{E['scroll']} {t('actions.recap_loading', lang)}"
                recap_status.set_visibility(True)
            try:
                client = anthropic.Anthropic(api_key=s["api_key"])
                config = get_engine_config()
                recap = await asyncio.to_thread(call_recap, client, game, config)
                # Replace any existing recap in messages
                msgs = [m for m in s["messages"] if not m.get("recap")]
                msgs.append({"role":"assistant","content":recap,"recap":True})
                s["messages"] = msgs
                save_game(game, username, s["messages"], s.get("active_save", "autosave"))
                # Remove old recap element from chat if present, render new one
                old_recap = s.get("_recap_element")
                if old_recap:
                    try: old_recap.delete()
                    except Exception: pass
                cc = s.get("_chat_container")
                if cc:
                    prefix = f"{E['scroll']} **{t('actions.recap_prefix', lang)}**\n\n"
                    with cc:
                        recap_el = ui.column().classes("chat-msg recap w-full")
                        if not s.get("sr_chat", True):
                            recap_el.props('aria-hidden="true"')
                        elif s.get("sr_chat", True):
                            recap_el.props(f'aria-label="{t("aria.recap_says", lang)}"')
                        with recap_el:
                            ui.markdown(f"{prefix}{_clean_narration(recap)}")
                    s["_recap_element"] = recap_el
                    await _scroll_chat_bottom()
                    await do_tts(recap, recap_el)
                else:
                    # Chat container not available (edge case) — recap is saved,
                    # will appear on next natural page render. No disruptive reload needed.
                    ui.notify(f"{E['scroll']} {t('actions.recap_prefix', lang)}", type="positive")
            except Exception as e: ui.notify(t("creation.error", lang, error=e), type="negative")
            finally:
                s["processing"] = False
                if recap_status:
                    recap_status.set_visibility(False)
    if game:
        # --- Wrap Up Story (re-offer epilogue after dismiss) ---
        _bp = game.story_blueprint or {}
        if _bp.get("story_complete") and game.epilogue_dismissed and not game.epilogue_shown:
            def wrap_story():
                game.epilogue_dismissed = False
                save_game(game, s["current_user"], s["messages"], s.get("active_save", "autosave"))
                ui.navigate.reload()
            ui.button(t('actions.wrap_story', lang), on_click=wrap_story, color="primary").props("flat dense").classes("w-full")
        ui.button(f"{E['scroll']} {t('actions.recap', lang)}", on_click=do_recap).props("flat dense").classes("w-full")
        recap_status = ui.label("").classes("text-xs text-center w-full").style("color: var(--text-secondary)")
        recap_status.set_visibility(False)
    # Save/Load
    with ui.expansion(f"{E['floppy']} {t('actions.saves', lang)}", value=saves_open).classes("w-full"):
        active = s.get("active_save", "autosave")
        active_display = t("actions.autosave", lang) if active == "autosave" else active

        # --- Active slot indicator ---
        if game:
            ui.label(f"{E['floppy']} {t('actions.active_save', lang, name=active_display)}").classes(
                "text-xs font-semibold w-full").style("color: var(--success)")

            # --- Quick save (into active slot) ---
            save_confirm = ui.label(f"{E['checkmark']} {t('actions.saved', lang)}").classes(
                "text-sm text-center w-full").style("color: var(--success)")
            save_confirm.set_visibility(False)
            async def do_quick_save():
                save_game(game, username, s["messages"], s.get("active_save", "autosave"))
                save_confirm.set_visibility(True)
                async def _hide():
                    await asyncio.sleep(2)
                    save_confirm.set_visibility(False)
                asyncio.create_task(_hide())
            ui.button(f"{E['floppy']} {t('actions.quick_save', lang)}", on_click=do_quick_save).classes("w-full")

            # --- Save As (new slot) ---
            save_as_container = ui.column().classes("w-full gap-1")
            save_as_visible = {"val": False}
            def toggle_save_as():
                save_as_visible["val"] = not save_as_visible["val"]
                save_as_container.set_visibility(save_as_visible["val"])
            ui.button(f"{E['plus']} {t('actions.save_as', lang)}", on_click=toggle_save_as).props("flat dense").classes("w-full")
            with save_as_container:
                save_as_inp = ui.input(t("actions.save_as_placeholder", lang)).classes("w-full").props("dense outlined dark")
                async def do_save_as():
                    new_name = save_as_inp.value.strip()
                    if not new_name:
                        return
                    # Sanitize: no path separators or dots
                    new_name = re.sub(r'[/\\.\s]+', '_', new_name).strip('_')
                    if not new_name:
                        return
                    old_name = s.get("active_save", "autosave")
                    save_game(game, username, s["messages"], new_name)
                    # Replace chapter archives in the destination slot wholesale so
                    # no stale chapters from a previously existing save survive.
                    delete_chapter_archives(username, new_name)
                    copy_chapter_archives(username, old_name, new_name)
                    s["active_save"] = new_name
                    if on_refresh:
                        on_refresh()
                    else:
                        ui.navigate.reload()
                ui.button(f"{E['floppy']} {t('actions.save_as_btn', lang)}", on_click=do_save_as).classes("w-full")
            save_as_container.set_visibility(False)

        ui.separator().classes("my-1")

        # --- Save list with metadata ---
        saves = list_saves_with_info(username)
        if saves:
            for info in saves:
                sname = info["name"]
                is_active = (sname == active and game is not None)
                pname = info.get("player_name", "?")
                scene = info.get("scene_count", 0)
                chapter = info.get("chapter_number", 1)
                saved_at = info.get("saved_at", "")
                # Format date
                date_str = ""
                if saved_at:
                    try:
                        dt = datetime.fromisoformat(saved_at)
                        date_str = dt.strftime("%d.%m. %H:%M")
                    except Exception:
                        date_str = saved_at[:16]

                display_name = t("actions.autosave", lang) if sname == "autosave" else sname
                # Card-style row
                border_color = "var(--success)" if is_active else "var(--accent)"
                bg_color = "var(--success-dim)" if is_active else "var(--accent-dim)"
                with ui.card().classes("w-full p-2 mb-1").style(
                    f"background: {bg_color}; border: 1px solid {border_color}; border-radius: 8px"):
                    with ui.column().classes("w-full gap-1"):
                        # Title + meta
                        _dn_safe = html_mod.escape(display_name)
                        title_html = f"<b>{_dn_safe}</b>"
                        if is_active:
                            title_html += f" {E['check']}"
                        ui.html(title_html).classes("text-sm")
                        meta = f"{pname} {E['dot']} {t('actions.save_scene', lang, n=scene)}"
                        if chapter > 1:
                            meta += f" {E['dot']} {t('actions.save_chapter', lang, n=chapter)}"
                        if date_str:
                            meta += f" {E['dot']} {date_str}"
                        ui.label(meta).classes("text-xs").style("color: var(--text-secondary)")
                        # Action buttons — 3-column grid, one slot per button (stable layout regardless of visibility)
                        with ui.element("div").style("display: grid; grid-template-columns: 1fr 1fr 1fr; width: 100%; align-items: center; margin-top: 4px; padding: 0 0.25rem"):
                            def make_load(n=sname, dn=display_name, _active=is_active):
                                async def do_load():
                                    async def _execute_load():
                                        loaded, hist = load_game(username, n)
                                        if loaded:
                                            s["game"]=loaded; s["creation"]=None; s["pending_burn"]=None; s["messages"]=hist
                                            s["active_save"] = n
                                            s["processing"] = False  # Cancel any in-flight turn
                                            s["_turn_gen"] = s.get("_turn_gen", 0) + 1
                                            s["viewing_chapter"] = None; s["chapter_view_messages"] = None; s["chapter_view_title"] = None
                                            s["messages"].append({"role":"assistant","content":f"*{E['checkmark']} {t('actions.game_loaded', lang, name=loaded.player_name, scene=loaded.scene_count)}*"})
                                            # Persist last used save so next login restores it
                                            _ucfg = load_user_config(username); _ucfg["last_save"] = n; save_user_config(username, _ucfg)
                                            ui.navigate.reload()
                                    if game and not _active:
                                        with ui.dialog() as dlg, ui.card():
                                            ui.label(t("actions.load_confirm", lang, name=dn))
                                            with ui.row().classes("gap-4 mt-2"):
                                                async def confirm_load():
                                                    dlg.close()
                                                    await _execute_load()
                                                ui.button(t("user.yes", lang), on_click=confirm_load, color="positive")
                                                ui.button(t("user.no", lang), on_click=dlg.close)
                                        dlg.open()
                                    else:
                                        await _execute_load()
                                return do_load
                            _load_aria = t("aria.load_save", lang, name=display_name)
                            ui.button(icon="play_arrow", on_click=make_load(sname, display_name, is_active)).props(f'flat round dense size=sm aria-label="{_load_aria}"').tooltip(t("actions.load", lang)).style("justify-self: start")

                            # --- Setup info tooltip (slot always rendered for stable layout) ---
                            _si_genre = info.get("setting_genre", "")
                            _si_tone = info.get("setting_tone", "")
                            _si_arch = info.get("setting_archetype", "")
                            _si_concept = info.get("character_concept", "")
                            _si_back = info.get("backstory", "")
                            _si_wishes = info.get("player_wishes", "")
                            _si_bounds = info.get("content_lines", "")
                            _has_info = any([_si_genre, _si_tone, _si_arch, _si_concept, _si_back, _si_wishes, _si_bounds])
                            _info_visibility = "" if _has_info else "visibility: hidden; pointer-events: none"
                            with ui.button(icon="info_outline").props(
                                f'flat round dense size=sm aria-label="{t("aria.save_info", lang)}"'
                            ).classes("text-gray-400").style(f"min-width: 36px; min-height: 36px; justify-self: center; {_info_visibility}"):
                                if _has_info:
                                    _lines = []
                                    if _si_genre:
                                        _gl = get_genre_label(_si_genre, lang) if " " not in _si_genre else _si_genre
                                        _lines.append(f'<b>{t("save_info.genre", lang)}:</b> {html_mod.escape(_gl)}')
                                    if _si_tone:
                                        _tl = get_tone_label(_si_tone, lang) if " " not in _si_tone else _si_tone
                                        _lines.append(f'<b>{t("save_info.tone", lang)}:</b> {html_mod.escape(_tl)}')
                                    if _si_arch:
                                        _al = get_archetype_label(_si_arch, lang) if " " not in _si_arch else _si_arch
                                        _lines.append(f'<b>{t("save_info.archetype", lang)}:</b> {html_mod.escape(_al)}')
                                    if _si_concept:
                                        _lines.append(f'<b>{t("save_info.concept", lang)}:</b> {html_mod.escape(_si_concept)}')
                                    if _si_back:
                                        _lines.append(f'<b>{t("save_info.backstory", lang)}:</b> {html_mod.escape(_si_back)}')
                                    if _si_wishes:
                                        _lines.append(f'<b>{t("save_info.wishes", lang)}:</b> {html_mod.escape(_si_wishes)}')
                                    if _si_bounds:
                                        _lines.append(f'<b>{t("save_info.boundaries", lang)}:</b> {html_mod.escape(_si_bounds)}')
                                    with ui.menu().props("anchor='top middle' self='bottom middle' :offset='[0,6]'"):
                                        ui.html('<br>'.join(_lines)).style(
                                            "max-width:280px;max-height:320px;overflow-y:auto;"
                                            "padding:8px 12px;font-size:0.82rem;line-height:1.45"
                                        )

                            # --- Delete slot (always rendered for stable layout) ---
                            if sname != "autosave":
                                def make_delete(n=sname):
                                    async def do_delete():
                                        display = t("actions.autosave", lang) if n == "autosave" else n
                                        with ui.dialog() as dlg, ui.card():
                                            ui.label(t("actions.delete_confirm", lang, name=display))
                                            with ui.row().classes("gap-4 mt-2"):
                                                async def confirm_del():
                                                    try:
                                                        delete_save(username, n)
                                                    except Exception as e:
                                                        log(f"[Save] Delete failed for {n}: {e}", level="warning")
                                                    if s.get("active_save") == n:
                                                        s["active_save"] = "autosave"
                                                    dlg.close()
                                                    if on_refresh:
                                                        on_refresh()
                                                    else:
                                                        ui.navigate.reload()
                                                ui.button(t("user.yes", lang), on_click=confirm_del, color="positive")
                                                ui.button(t("user.no", lang), on_click=dlg.close)
                                        dlg.open()
                                    return do_delete
                                _del_aria = t("aria.delete_save", lang, name=display_name)
                                ui.button(icon="delete_outline", on_click=make_delete(sname)).props(f'flat round dense size=sm aria-label="{_del_aria}"').tooltip(t("actions.delete", lang)).style("color: var(--error); justify-self: end")
                            else:
                                # Phantom button — invisible, keeps delete slot for stable centering
                                ui.button(icon="delete_outline").props('flat round dense size=sm aria-hidden="true"').style("min-width: 36px; min-height: 36px; visibility: hidden; pointer-events: none; justify-self: end")
                        # --- Chapter archives (inside active save card) ---
                        if is_active and chapter > 1:
                            archived = list_chapter_archives(username, sname)
                            if archived:
                                viewing = s.get("viewing_chapter")
                                ui.separator().classes("my-1")
                                for arch in archived:
                                    ch_n = arch["chapter"]
                                    ch_title = arch.get("title", "")
                                    is_viewing = (viewing == ch_n)
                                    lbl = f"{E['book']} {t('chapters.chapter_label', lang, n=ch_n)}"
                                    if ch_title:
                                        lbl += f" — {ch_title}"
                                    def make_view_ch(n=ch_n, sn=sname):
                                        async def do_view():
                                            msgs, ttl = load_chapter_archive(username, sn, n)
                                            if msgs:
                                                s["viewing_chapter"] = n
                                                s["chapter_view_messages"] = msgs
                                                s["chapter_view_title"] = ttl
                                                if on_chapter_view_change:
                                                    await on_chapter_view_change()
                                                else:
                                                    ui.navigate.reload()
                                            else:
                                                ui.notify(t("chapters.not_found", lang), type="warning")
                                        return do_view
                                    btn = ui.button(lbl, on_click=make_view_ch(ch_n)).props("flat dense size=sm no-caps").classes("w-full text-left text-xs")
                                    if is_viewing:
                                        btn.style("color: var(--accent-light); border: 1px solid var(--accent-light)")
                                    else:
                                        btn.style("color: var(--text-secondary)")
                                # Current chapter (not clickable when active)
                                cur_lbl = f"{E['book']} {t('chapters.chapter_label', lang, n=chapter)} {E['check']}"
                                if viewing:
                                    async def back_to_current():
                                        s["viewing_chapter"] = None; s["chapter_view_messages"] = None; s["chapter_view_title"] = None
                                        if on_chapter_view_change:
                                            await on_chapter_view_change()
                                        else:
                                            ui.navigate.reload()
                                    ui.button(cur_lbl, on_click=back_to_current).props("flat dense size=sm no-caps").classes("w-full text-left text-xs")
                                else:
                                    ui.label(cur_lbl).classes("text-xs w-full").style("color: var(--success); padding: 0.25rem 0.5rem")
        else:
            ui.label(t("actions.no_saves", lang)).classes("text-xs text-center w-full").style("color: var(--text-secondary)")

        # --- New game ---
        ui.separator().classes("my-1")
        async def new_game():
            if game:
                with ui.dialog() as dlg, ui.card():
                    ui.label(t("actions.new_game_confirm", lang))
                    with ui.row().classes("gap-4 mt-2"):
                        async def confirm_new():
                            dlg.close()
                            delete_chapter_archives(username, s.get("active_save", "autosave"))
                            s["game"]=None;s["creation"]=None;s["pending_burn"]=None;s["messages"]=[];s["active_save"]="autosave"
                            s["processing"]=False;s["_turn_gen"]=s.get("_turn_gen",0)+1
                            s["viewing_chapter"]=None;s["chapter_view_messages"]=None
                            ui.navigate.reload()
                        ui.button(t("user.yes", lang), on_click=confirm_new, color="positive")
                        ui.button(t("user.no", lang), on_click=dlg.close)
                dlg.open()
            else:
                s["game"]=None;s["creation"]=None;s["pending_burn"]=None;s["messages"]=[];s["active_save"]="autosave"
                s["processing"]=False;s["_turn_gen"]=s.get("_turn_gen",0)+1
                s["viewing_chapter"]=None;s["chapter_view_messages"]=None
                ui.navigate.reload()
        ui.button(f"{t('actions.new_game', lang)}", on_click=new_game, color="red").props("flat").classes("w-full")

        # --- Export ---
        if game and s["messages"]:
            def do_export():
                pdf_bytes = export_story_pdf(game, s["messages"], lang=lang)
                ui.download(pdf_bytes, f"{game.player_name}_Story.pdf")
            ui.button(t('actions.export', lang), on_click=do_export).props("flat dense").classes("w-full")
    # Settings
    render_settings()
    # Help
    render_help()
    # Switch user
    ui.separator()
    async def switch():
        s["current_user"]="";s["game"]=None;s["creation"]=None;s["messages"]=[];s["user_config_loaded"]=False;s["active_save"]="autosave"
        s["processing"]=False;s["_turn_gen"]=s.get("_turn_gen",0)+1
        s["viewing_chapter"]=None;s["chapter_view_messages"]=None;s["chapter_view_title"]=None
        if on_switch_user:
            await on_switch_user()
        else:
            ui.navigate.reload()
    ui.button(f"{E['refresh']} {t('actions.switch_user', lang)}", on_click=switch).props("flat dense").classes("w-full")


def _info_btn(tip_text: str) -> None:
    """Info icon that opens a click-to-dismiss popover (mobile-friendly alternative to hover tooltip)."""
    with ui.button(icon="info_outline").props(
        f'flat round dense size=sm aria-label="{tip_text}"'
    ).classes("text-gray-400").style("min-width: 36px; min-height: 36px"):
        with ui.menu().props("anchor='top middle' self='bottom middle' :offset='[0,6]'"):
            ui.label(tip_text).style(
                "max-width: 260px; white-space: normal; padding: 8px 12px;"
                " font-size: 0.85rem; line-height: 1.45"
            )


def render_settings() -> None:
    s = S()
    lang = L()
    username = s["current_user"]
    with ui.expansion(f"{E['gear']} {t('settings.title', lang)}").classes("w-full"):
        # Only show API key input if no server-side key is configured
        if not SERVER_API_KEY:
            api_inp = ui.input(t("settings.api_key", lang), value=s.get("api_key",""), password=True, password_toggle_button=True).classes("w-full")
            ui.separator()
        # --- UI Language ---
        ui_lang_labels = list(UI_LANGUAGES.keys())
        # Reverse-map current code to display label
        _code_to_label = {v: k for k, v in UI_LANGUAGES.items()}
        cur_ui_label = _code_to_label.get(s.get("ui_lang", DEFAULT_LANG), ui_lang_labels[0])
        ui_lang_sel = ui.select(ui_lang_labels, label=t("settings.ui_lang", lang), value=cur_ui_label).classes("w-full")
        # --- Narration Language ---
        lang_sel = ui.select(list(LANGUAGES.keys()), label=t("settings.narration_lang", lang), value=s.get("narration_lang","Deutsch")).classes("w-full")
        with ui.row().classes("w-full items-center justify-between"):
            kid_sw = ui.switch(t("settings.kid_mode", lang), value=s.get("kid_friendly",False))
            _tip = t("settings.kid_tooltip", lang)
            _info_btn(_tip)
        ui.separator()
        with ui.row().classes("w-full items-center justify-between"):
            tts_sw = ui.switch(t("settings.tts", lang), value=s.get("tts_enabled",False))
            _tip = t("settings.tts_tooltip", lang)
            _info_btn(_tip)
        tts_container = ui.column().classes("w-full gap-1")
        tts_container.bind_visibility_from(tts_sw, "value")
        with tts_container:
            be_labels = list(get_tts_backends(lang).keys())
            be_sel = ui.select(be_labels, label=t("settings.backend", lang), value=s.get("tts_backend", be_labels[0])).classes("w-full")
            # --- edge-tts settings ---
            edge_container = ui.column().classes("w-full gap-1")
            edge_container.bind_visibility_from(be_sel, "value", backward=lambda v: resolve_tts_backend(v) == "edge_tts")
            with edge_container:
                voice_opts = list(get_voice_options(lang).keys())
                v_sel = ui.select(voice_opts, label=t("settings.voice", lang), value=s.get("voice_select", voice_opts[0])).classes("w-full")
                rate_sel = ui.select(["-50%","-25%","+0%","+25%","+50%"], label=t("settings.speed", lang), value=s.get("tts_rate","+0%")).classes("w-full")
            # --- Chatterbox settings ---
            cb_container = ui.column().classes("w-full gap-1")
            cb_container.bind_visibility_from(be_sel, "value", backward=lambda v: resolve_tts_backend(v) == "chatterbox")
            with cb_container:
                # Hint if chatterbox is not installed
                _cb_installed = True
                try:
                    import importlib as _il
                    _il.import_module("chatterbox")
                except ImportError:
                    _cb_installed = False
                if not _cb_installed:
                    with ui.card().classes("w-full").style(
                        "background: var(--accent-dim); border: 1px solid var(--accent-border); padding: 8px 12px"
                    ):
                        ui.label(
                            f"{E['warn']} {t('settings.cb_not_installed', lang)}"
                        ).classes("text-sm font-bold").style("color: var(--accent-light)")
                        ui.label(
                            t("settings.cb_install_cmd", lang)
                        ).classes("text-xs").style("font-family: monospace; color: #ccc; margin-top: 2px")
                        ui.label(
                            t("settings.cb_requires", lang)
                        ).classes("text-xs").style("color: #999; margin-top: 2px")
                cb_device_sel = ui.select(list(CHATTERBOX_DEVICE_OPTIONS.keys()), label=t("settings.device", lang), value=s.get("cb_device","Auto")).classes("w-full")
                cb_exag_slider = ui.slider(min=0.0, max=1.0, step=0.05, value=s.get("cb_exaggeration",0.5)).props("label-always")
                ui.label(t("settings.emotion", lang)).classes("text-xs").style("color: var(--text-secondary)")
                cb_cfg_slider = ui.slider(min=0.0, max=1.0, step=0.05, value=s.get("cb_cfg_weight",0.5)).props("label-always")
                ui.label(t("settings.cfg_weight", lang)).classes("text-xs").style("color: var(--text-secondary)")
                # Voice sample selection
                no_sample = get_no_voice_sample_label(lang)
                voice_samples = [no_sample]
                if VOICE_DIR.exists():
                    for f in sorted(VOICE_DIR.iterdir()):
                        if f.suffix.lower() in (".wav", ".mp3", ".ogg", ".flac"):
                            voice_samples.append(f.name)
                # Migrate saved no-sample label from other language
                saved_sample = s.get("cb_voice_sample", no_sample)
                if saved_sample not in voice_samples:
                    saved_sample = no_sample
                cb_voice_sel = ui.select(voice_samples, label=t("settings.voice_sample", lang), value=saved_sample).classes("w-full")
                ui.label(t("settings.voice_hint", lang)).classes("text-xs").style("color: var(--text-secondary)")
            # --- Voice preview ---
            preview_container = ui.column().classes("w-full gap-1")
            async def preview_voice():
                preview_text = t("tts.preview_text", lang)
                with preview_container:
                    indicator = ui.row().classes("w-full items-center gap-2")
                    with indicator:
                        ui.spinner("audio", size="sm", color="primary")
                        ui.label(t("settings.preview_loading", lang)).classes("text-xs").style("color: var(--text-secondary)")
                try:
                    _preview_backend = resolve_tts_backend(be_sel.value)
                    vcfg = VoiceConfig(
                        tts_enabled=True,
                        tts_backend=_preview_backend,
                        voice_select=v_sel.value if _preview_backend == "edge_tts" else "",
                        tts_rate=rate_sel.value,
                        cb_device=cb_device_sel.value,
                        cb_exaggeration=cb_exag_slider.value,
                        cb_cfg_weight=cb_cfg_slider.value,
                        cb_voice_sample=cb_voice_sel.value if _preview_backend == "chatterbox" else "",
                        narration_lang=LANGUAGES.get(lang_sel.value, "German"),
                    )
                    eng = get_voice_engine()
                    audio, fmt = await asyncio.to_thread(eng.text_to_speech, preview_text, vcfg)
                    indicator.delete()
                    if audio:
                        with preview_container:
                            render_audio_player(audio, fmt, autoplay=True)
                    else:
                        ui.notify(t("settings.no_audio", lang), type="warning")
                except Exception as e:
                    indicator.delete()
                    ui.notify(t("settings.preview_fail", lang, error=e), type="warning")
            ui.button(f"{E['play']} {t('settings.preview', lang)}", on_click=preview_voice).props("flat dense").classes("w-full")
        ui.separator()
        # --- STT ---
        with ui.row().classes("w-full items-center justify-between"):
            stt_sw = ui.switch(t("settings.stt", lang), value=s.get("stt_enabled",False))
            _tip = t("settings.stt_tooltip", lang)
            _info_btn(_tip)
        wm = get_whisper_models(lang)
        whisper_display = [f"{k} {E['dash']} {v}" for k, v in wm.items()]
        whisper_map = {f"{k} {E['dash']} {v}": k for k, v in wm.items()}
        cur_whisper = s.get("whisper_size", "medium")
        cur_whisper_display = f"{cur_whisper} {E['dash']} {wm.get(cur_whisper, '?')}"
        whisper_sel = ui.select(whisper_display, label=t("settings.whisper_model", lang), value=cur_whisper_display).classes("w-full")
        whisper_sel.bind_visibility_from(stt_sw, "value")
        ui.separator()
        # --- Screen reader chat toggle ---
        with ui.row().classes("w-full items-center justify-between"):
            sr_chat_sw = ui.switch(t("settings.sr_chat", lang), value=s.get("sr_chat", True))
            _tip = t("settings.sr_chat_tooltip", lang)
            _info_btn(_tip)
        ui.separator()
        dice_opts = get_dice_display_options(lang)
        dice_options_map = {label: i for i, label in enumerate(dice_opts)}
        cur_dice_idx = s.get("dice_display", 0)
        if isinstance(cur_dice_idx, str):
            cur_dice_idx = _dice_string_to_index(cur_dice_idx)
        cur_dice_label = dice_opts[cur_dice_idx] if cur_dice_idx < len(dice_opts) else dice_opts[0]
        dice_sel = ui.select(dice_opts, label=t("settings.dice", lang), value=cur_dice_label).classes("w-full")
        ui.separator()
        # --- Narrator font ---
        _font_opts = {
            t("settings.narrator_font_sans",      lang): "sans",
            t("settings.narrator_font_serif",     lang): "serif",
            t("settings.narrator_font_highlight", lang): "highlight",
        }
        _cur_font = s.get("narrator_font", "sans")
        _cur_font_label = next((k for k, v in _font_opts.items() if v == _cur_font),
                               list(_font_opts.keys())[0])
        font_sel = ui.select(list(_font_opts.keys()), label=t("settings.narrator_font", lang),
                             value=_cur_font_label).classes("w-full")
        def _apply_font(val):
            code = _font_opts.get(val, "serif")
            ui.run_javascript(f"document.body.setAttribute('data-narrator-font', '{code}')")
        font_sel.on("update:model-value", lambda e: _apply_font(e.args))
        ui.separator()
        async def save_cfg():
            if not SERVER_API_KEY:
                s["api_key"]=api_inp.value
                save_global_config({"api_key":api_inp.value})
            new_ui_lang = UI_LANGUAGES.get(ui_lang_sel.value, DEFAULT_LANG)
            old_ui_lang = s.get("ui_lang", DEFAULT_LANG)
            s["ui_lang"]=new_ui_lang
            s["narration_lang"]=lang_sel.value;s["kid_friendly"]=kid_sw.value
            s["tts_enabled"]=tts_sw.value;s["tts_backend"]=be_sel.value;s["voice_select"]=v_sel.value
            s["tts_rate"]=rate_sel.value;s["stt_enabled"]=stt_sw.value
            s["dice_display"]=dice_options_map.get(dice_sel.value, 0)
            s["sr_chat"]=sr_chat_sw.value
            new_font = _font_opts.get(font_sel.value, "sans")
            old_font = s.get("narrator_font", "sans")   # lesen VOR dem Überschreiben
            s["narrator_font"]=new_font
            s["cb_device"]=cb_device_sel.value;s["cb_exaggeration"]=cb_exag_slider.value
            s["cb_cfg_weight"]=cb_cfg_slider.value;s["cb_voice_sample"]=cb_voice_sel.value
            s["whisper_size"]=whisper_map.get(whisper_sel.value, "medium")
            # Resolve to language-neutral codes for persistence (not localized labels)
            voice_id = resolve_voice_id(v_sel.value)
            backend_code = resolve_tts_backend(be_sel.value)
            no_sample = get_no_voice_sample_label(lang)
            sample_value = "" if cb_voice_sel.value == no_sample else cb_voice_sel.value
            ucfg = load_user_config(username)
            ucfg.update({"ui_lang":new_ui_lang,
                         "tts_enabled":tts_sw.value,"stt_enabled":stt_sw.value,"narration_lang":lang_sel.value,
                         "kid_friendly":kid_sw.value,"tts_backend":backend_code,"voice_select":voice_id,
                         "tts_rate":rate_sel.value,"dice_display":dice_options_map.get(dice_sel.value, 0),
                         "cb_device":cb_device_sel.value,"cb_exaggeration":cb_exag_slider.value,
                         "cb_cfg_weight":cb_cfg_slider.value,"cb_voice_sample":sample_value,
                         "whisper_size":whisper_map.get(whisper_sel.value, "medium"),
                         "sr_chat":sr_chat_sw.value,
                         "narrator_font":_font_opts.get(font_sel.value, "sans")})
            save_user_config(username, ucfg)
            # UI language change requires full reload to re-render all labels
            if new_ui_lang != old_ui_lang:
                s["user_config_loaded"] = False
                ui.navigate.reload()
                return
            # Highlight mode change requires reload to re-render quote spans server-side
            if (new_font == "highlight") != (old_font == "highlight"):
                ui.navigate.reload()
                return
            # Sofort am Body setzen, damit der Chat ohne Reload die neue Schrift zeigt
            ui.run_javascript(f"document.body.setAttribute('data-narrator-font', '{new_font}')")
            save_confirm.set_visibility(True)
            async def _hide():
                await asyncio.sleep(2)
                save_confirm.set_visibility(False)
            asyncio.create_task(_hide())
        ui.button(f"{E['floppy']} {t('settings.save_btn', lang)}", on_click=save_cfg, color="primary").classes("w-full")
        save_confirm = ui.label(f"{E['checkmark']} {t('settings.saved_confirm', lang)}").classes("text-sm text-center w-full").style("color: var(--success)")
        save_confirm.set_visibility(False)


def render_help() -> None:
    lang = L()
    with ui.expansion(f"{E['question']} {t('help.title', lang)}").classes("w-full"):
        ui.markdown(t("help.intro_title", lang))
        ui.label(t("help.intro_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(t("help.freedom_title", lang))
        ui.label(t("help.freedom_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(t("help.probe_title", lang))
        ui.label(t("help.probe_text", lang)).classes("text-xs text-gray-400")
        ui.html(t("help.probe_detail", lang)).style("font-size:0.85em; line-height:1.8; padding:0.3em 0")
        ui.separator()

        ui.markdown(t("help.results_title", lang))
        ui.label(t("help.results_text", lang)).classes("text-xs text-gray-400")
        with ui.element('div').style("font-size:0.85em; line-height:1.6; padding:0.2em 0"):
            for _ico, _lbl_key, _desc_key in [
                (E['check'],  "help.result_strong", "help.result_strong_desc"),
                (E['warn'],   "help.result_weak",   "help.result_weak_desc"),
                (E['x_mark'], "help.result_miss",   "help.result_miss_desc"),
            ]:
                ui.html(f"{_ico} {t(_lbl_key, lang)}")
                ui.label(t(_desc_key, lang)).classes("text-xs text-gray-400").style("margin-bottom:0.4em")
        ui.separator()

        ui.markdown(f"{t('help.match_title', lang)} {E['comet']}")
        ui.label(t("help.match_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(t("help.position_title", lang))
        ui.label(t("help.position_text", lang)).classes("text-xs text-gray-400")
        with ui.element('div').style("font-size:0.85em; line-height:1.6; padding:0.2em 0"):
            for _ico, _lbl_key, _desc_key in [
                (E['green_circle'],  "help.pos_controlled", "help.pos_controlled_desc"),
                (E['orange_circle'], "help.pos_risky",      "help.pos_risky_desc"),
                (E['red_circle'],    "help.pos_desperate",  "help.pos_desperate_desc"),
            ]:
                ui.html(f"{_ico} {t(_lbl_key, lang)}")
                ui.label(t(_desc_key, lang)).classes("text-xs text-gray-400").style("margin-bottom:0.4em")
        ui.separator()

        ui.markdown(t("help.stats_title", lang))
        ui.label(t("help.stats_text", lang)).classes("text-xs text-gray-400")
        ui.html(
            f"{E['lightning']} {t('help.stat_edge', lang)}<br>"
            f"{E['heart_red']} {t('help.stat_heart', lang)}<br>"
            f"{E['shield']} {t('help.stat_iron', lang)}<br>"
            f"{E['dark_moon']} {t('help.stat_shadow', lang)}<br>"
            f"{E['brain']} {t('help.stat_wits', lang)}"
        ).style("font-size:0.85em; line-height:2")
        ui.separator()

        ui.markdown(t("help.tracks_title", lang))
        ui.label(t("help.tracks_text", lang)).classes("text-xs text-gray-400")
        ui.html(
            f"{E['heart_red']} {t('help.track_health', lang)}<br>"
            f"{E['heart_blue']} {t('help.track_spirit', lang)}<br>"
            f"{E['yellow_dot']} {t('help.track_supply', lang)}"
        ).style("font-size:0.85em; line-height:2")
        ui.separator()

        ui.markdown(t("help.momentum_title", lang))
        ui.label(t("help.momentum_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(f"{t('help.chaos_title', lang)} {E['tornado']}")
        ui.label(t("help.chaos_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(f"{t('help.clocks_title', lang)} {E['clock']}")
        ui.label(t("help.clocks_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(f"{t('help.crisis_title', lang)} {E['skull']}")
        ui.label(t("help.crisis_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(f"{t('help.kid_title', lang)} {E['green_heart']}")
        ui.label(t("help.kid_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(f"{t('help.correction_title', lang)} {E['pen']}")
        ui.label(t("help.correction_text", lang)).classes("text-xs text-gray-400")
        ui.label(t("help.correction_example", lang)).classes("text-xs text-gray-400")


# ===============================================================
# CHAT RENDERING
# ===============================================================

def render_chat_messages(container) -> Optional[str]:
    """Render chat history. Returns the ID of the last scene marker (for scroll targeting)."""
    s = S()
    lang = L()
    _sr_chat = s.get("sr_chat", True)
    viewing = s.get("viewing_chapter")
    messages = s.get("chapter_view_messages", []) if viewing else s.get("messages", [])
    last_scene_marker_id = None
    for i, msg in enumerate(messages):
        if msg.get("scene_marker"):
            marker_id = f"msg-{i}"
            last_scene_marker_id = marker_id
            ui.html(msg["scene_marker"]).classes("scene-marker").props(f'id="{marker_id}"')
            continue
        role = msg.get("role","assistant")
        content = msg.get("content","")
        css = "recap" if msg.get("recap") else role
        if msg.get("correction_input"):
            css += " correction"
        prefix = f"{E['scroll']} **{t('actions.recap_prefix', lang)}**\n\n" if msg.get("recap") else ""
        _msg_col = ui.column().classes(f"chat-msg {css} w-full")
        if not _sr_chat:
            _msg_col.props('aria-hidden="true"')
        elif _sr_chat:
            # Screen-reader role attribution via aria-label on the container —
            # avoids injecting sr-only spans that leak visibly through DOMPurify / ui.html wrappers
            if msg.get("recap"):
                _msg_col.props(f'aria-label="{t("aria.recap_says", lang)}"')
            elif role == "user":
                _msg_col.props(f'aria-label="{t("aria.player_says", lang)}"')
            else:
                _msg_col.props(f'aria-label="{t("aria.narrator_says", lang)}"')
        with _msg_col:
            if msg.get("corrected"):
                with ui.element('div').classes('correction-badge').props(f'aria-label="{t("aria.correction_badge", lang)}"'):
                    ui.html(t("correction.badge", lang))
            _content = _clean_narration(content)
            if role == "assistant" and s.get("narrator_font") == "highlight":
                _content = _highlight_dialog(_content)
            ui.markdown(f"{prefix}{_content}")
            rd = msg.get("roll_data")
            if rd: render_dice_display(rd)
    # Entity highlights (Design mode): inject JS after all messages are rendered
    if s.get("narrator_font") == "highlight" and s.get("game"):
        _inject_entity_highlights(s["game"])
    return last_scene_marker_id


def render_dice_display(rd: dict) -> None:
    if not rd: return
    s = S()
    lang = L()
    setting = s.get("dice_display", 0)
    if isinstance(setting, str):
        setting = _dice_string_to_index(setting)
    if setting == 0: return  # Off
    # Always re-translate from codes — stored labels may be from a different language or old save
    rl = get_result_labels(lang)
    ml = get_move_labels(lang)
    sl = get_stat_labels(lang)
    result_label, severity = rl.get(rd.get("result", ""), (rd.get("result_label", "?"), "info"))
    stat_label = sl.get(rd.get("stat_name", ""), rd.get("stat_label", "?"))
    move_label = ml.get(rd.get("move", ""), rd.get("move_label", "?"))
    is_match = rd.get("match", rd.get("c1") == rd.get("c2"))
    if setting == 1:  # Simple
        pos = rd.get("position","")
        pl = get_position_labels(lang)
        ph = f" {E['dot']} {pl.get(pos,'')}" if pos and pos!="risky" else ""
        match_txt = f" {E['dot']} {t('dice.match_short', lang)}" if is_match else ""
        chaos_txt = f" {E['dot']} {t('dice.chaos_short', lang)}" if rd.get("chaos_interrupt") else ""
        ui.html(f'{result_label} {E["dot"]} {stat_label}{ph}{match_txt}{chaos_txt}').classes(f'dice-simple {severity} w-full')
    elif setting == 2:  # Detailed
        header = f"{E['dice']} {result_label} \u2014 {move_label} ({stat_label})"
        if is_match:
            header += f" {E['comet']}"
        if rd.get("chaos_interrupt"):
            header += f" {E['dot']} {t('dice.chaos_short', lang)}"
        with ui.expansion(header).classes("w-full"):
            ui.markdown(t("dice.action", lang, d1=rd['d1'], d2=rd['d2'], stat_value=rd['stat_value'], score_display=rd['score_display'], c1=rd['c1'], c2=rd['c2']))
            if is_match:
                ui.markdown(t("dice.match", lang, value=rd['c1']))
            pl = get_position_labels(lang)
            el = get_effect_labels(lang)
            ui.markdown(t("dice.position", lang, position=pl.get(rd.get('position','risky'),'?'), effect=el.get(rd.get('effect','standard'),'?')))
            if rd.get("consequences"):
                cons_text = ', '.join(translate_consequence(c, lang) for c in rd['consequences'])
                ui.markdown(t("dice.consequences", lang, text=cons_text))
            for ce in rd.get("clock_events",[]):
                if isinstance(ce,dict): ui.markdown(f"{E['clock']} **{ce['clock']}**: {ce['trigger']}")


# ===============================================================
# CHARACTER CREATION
# ===============================================================

def render_creation_flow(chat_container) -> bool:
    s = S()
    lang = L()
    creation = s.get("creation")
    game = s.get("game")
    if game is None and creation is None:
        ui.markdown(t("creation.welcome", lang))
        genres = get_genres(lang)
        with ui.element("div").classes("choice-grid w-full").props(f'role="group" aria-label="{t("aria.genre_selection", lang)}"'):
            for label,code in genres.items():
                ui.button(label, on_click=lambda l=label,c=code: _pick_genre(l,c)).props("flat unelevated").classes("w-full choice-btn")
            ui.button(f"{E['pen']} {t('creation.custom_idea', lang)}", on_click=_pick_genre_custom).props("flat unelevated").classes("w-full choice-btn")
        return True
    if creation is None: return False
    step = creation.get("step","")
    if step == "genre_custom":
        ui.markdown(t("creation.custom_genre_title", lang))
        inp = ui.input(placeholder=t("creation.genre_placeholder", lang), value=creation.get("genre_description", "")).classes("w-full").props(f'aria-label="{t("creation.genre_placeholder", lang)}"')
        async def go():
            if inp.value.strip(): _finish_genre_custom(inp.value.strip())
        inp.on("keydown.enter", go)
        with ui.row().classes("gap-2"):
            ui.button(t("creation.back", lang), on_click=_creation_back_to_genre).props("flat")
            ui.button(t("creation.next", lang), on_click=go, color="primary")
        return True
    if step == "tone":
        ui.markdown(t("creation.tone_question", lang, genre=creation['genre_label']))
        tones = get_tones(lang)
        with ui.element("div").classes("choice-grid w-full").props(f'role="group" aria-label="{t("aria.tone_selection", lang)}"'):
            for label,code in tones.items():
                ui.button(label, on_click=lambda l=label,c=code: _pick_tone(l,c)).props("flat unelevated").classes("w-full choice-btn")
            ui.button(f"{E['pen']} {t('creation.custom_tone_btn', lang)}", on_click=_pick_tone_custom).props("flat unelevated").classes("w-full choice-btn")
        ui.button(t("creation.back", lang), on_click=_creation_back_to_genre).props("flat")
        return True
    if step == "tone_custom":
        ui.markdown(t("creation.custom_tone_title", lang))
        inp = ui.textarea(placeholder=t("creation.tone_placeholder", lang), value=creation.get("tone_description", "")).classes("w-full").props(f'rows=3 aria-label="{t("creation.tone_placeholder", lang)}"')
        async def go():
            if inp.value.strip(): _finish_tone_custom(inp.value.strip())
        with ui.row().classes("gap-2"):
            ui.button(t("creation.back", lang), on_click=_creation_back_to_tone).props("flat")
            ui.button(t("creation.next", lang), on_click=go, color="primary")
        return True
    if step == "archetype":
        ui.markdown(t("creation.archetype_question", lang, tone=creation['tone_label']))
        archetypes = get_archetypes(lang)
        with ui.element("div").classes("choice-grid w-full").props(f'role="group" aria-label="{t("aria.archetype_selection", lang)}"'):
            for label,code in archetypes.items():
                ui.button(label, on_click=lambda l=label,c=code: _pick_archetype(l,c)).props("flat unelevated").classes("w-full choice-btn")
            ui.button(f"{E['pen']} {t('creation.custom_idea', lang)}", on_click=_pick_archetype_custom).props("flat unelevated").classes("w-full choice-btn")
        ui.button(t("creation.back", lang), on_click=_creation_back_to_tone).props("flat")
        return True
    if step == "personalize":
        ui.markdown(t("creation.name_question", lang))
        name_inp = ui.input(placeholder=t("creation.name_placeholder", lang), value=creation.get("player_name", "")).classes("w-full").props(f'aria-label="{t("creation.name_placeholder", lang)}"')
        ui.markdown(t("creation.desc_question", lang))
        desc_inp = ui.textarea(placeholder=t("creation.desc_placeholder", lang), value=creation.get("custom_desc", "")).props("rows=4 maxlength=800 counter").classes("w-full").props(f'aria-label="{t("creation.desc_placeholder", lang)}"')
        async def go():
            if name_inp.value.strip(): _finish_personalize(name_inp.value.strip(), desc_inp.value.strip() if desc_inp.value else "")
        name_inp.on("keydown.enter", go)
        with ui.row().classes("gap-2"):
            ui.button(t("creation.back", lang), on_click=_creation_back_to_archetype).props("flat")
            ui.button(t("creation.next", lang), on_click=go, color="primary")
        return True
    if step == "wishes_boundaries": return _render_wishes()
    if step == "confirm": return _render_confirm()
    return creation is not None


def _pick_genre(l,c):
    s=S();s["creation"]={"step":"tone","genre":c,"genre_label":l}
    ui.navigate.reload()

def _pick_genre_custom():
    s=S();s["creation"]={"step":"genre_custom"}
    ui.navigate.reload()

def _creation_back_to_genre():
    s=S();s["creation"]=None
    ui.navigate.reload()

def _creation_back_to_tone():
    s=S();cr=s["creation"];cr["step"]="tone"
    # Clear tone-related choices
    cr.pop("tone",None);cr.pop("tone_label",None);cr.pop("tone_description",None)
    ui.navigate.reload()

def _creation_back_to_archetype():
    s=S();cr=s["creation"];cr["step"]="archetype"
    cr.pop("archetype",None);cr.pop("archetype_label",None)
    ui.navigate.reload()

def _creation_back_to_personalize():
    s=S();cr=s["creation"];cr["step"]="personalize"
    ui.navigate.reload()

def _creation_back_to_wishes():
    s=S();cr=s["creation"];cr["step"]="wishes_boundaries"
    ui.navigate.reload()

def _finish_genre_custom(txt):
    s=S();c=s["creation"];c["genre"]="custom";c["genre_label"]=f"{E['pen']} {txt[:40]}";c["genre_description"]=txt;c["step"]="tone"
    ui.navigate.reload()

def _pick_tone(l,c):
    s=S();cr=s["creation"];cr["tone"]=c;cr["tone_label"]=l;cr["step"]="archetype"
    ui.navigate.reload()

def _pick_tone_custom():
    s=S();s["creation"]["step"]="tone_custom"
    ui.navigate.reload()

def _finish_tone_custom(txt):
    s=S();c=s["creation"];label=txt.replace("\n"," ").replace("\r","");c["tone"]="custom";c["tone_label"]=f"{E['pen']} {label[:40]}";c["tone_description"]=txt;c["step"]="archetype"
    ui.navigate.reload()

def _pick_archetype(l,c):
    s=S();cr=s["creation"];cr["archetype"]=c;cr["archetype_label"]=l;cr["step"]="personalize"
    ui.navigate.reload()

def _pick_archetype_custom():
    s=S();s["creation"]["archetype"]="custom";s["creation"]["archetype_label"]=f"{E['pen']} {t('creation.custom_idea', L())}";s["creation"]["step"]="personalize"
    ui.navigate.reload()

def _finish_personalize(name, desc=""):
    s=S();s["creation"]["player_name"]=name;s["creation"]["custom_desc"]=desc;s["creation"]["step"]="wishes_boundaries"
    ui.navigate.reload()

def _render_wishes():
    s=S();creation=s["creation"];username=s["current_user"];lang=L()
    if "content_lines" not in creation:
        cfg=load_user_config(username);creation["content_lines"]=cfg.get("content_lines","")
    if "wishes" not in creation: creation["wishes"]=""
    ui.markdown(t("creation.almost_done", lang))
    ui.markdown(f"{E['star']} {t('creation.wishes_label', lang)}")
    w_inp = ui.textarea(placeholder=t("creation.wishes_placeholder", lang), value=creation.get("wishes","")).classes("w-full").props(f'maxlength=400 counter aria-label="{t("creation.wishes_placeholder", lang)}"')
    ui.label(f"{E['star']} {t('creation.wishes_hint', lang)}").classes("text-xs text-gray-500")
    ui.markdown(f"{E['shield']} {t('creation.boundaries_label', lang)}")
    l_inp = ui.textarea(placeholder=t("creation.boundaries_placeholder", lang), value=creation.get("content_lines","")).classes("w-full").props(f'maxlength=400 counter aria-label="{t("creation.boundaries_placeholder", lang)}"')
    ui.label(f"{E['shield']} {t('creation.boundaries_hint', lang)}").classes("text-xs text-gray-500")
    btn_container = ui.column().classes("w-full mt-4 gap-2")
    async def proceed():
        creation["wishes"]=w_inp.value.strip() if w_inp.value else ""
        creation["content_lines"]=l_inp.value.strip() if l_inp.value else ""
        # Show spinner below button
        with btn_container:
            with ui.row().classes("w-full items-center gap-3").props('role="status"'):
                ui.spinner("dots", size="md", color="primary")
                ui.label(t("creation.generating", lang)).classes("text-sm").style("color: var(--text-secondary)")
        await _scroll_chat_bottom()
        try:
            client=anthropic.Anthropic(api_key=s["api_key"]);config=get_engine_config()
            setup=await asyncio.to_thread(call_setup_brain,client,creation,config)
            creation["setup"]=setup
            if "drafts" not in creation: creation["drafts"]=[]
            creation["drafts"].append(setup);creation["step"]="confirm"
            if creation["content_lines"]:
                ucfg=load_user_config(username);ucfg["content_lines"]=creation["content_lines"]
                save_user_config(username,ucfg)
            s["creation"]=creation
            ui.navigate.reload()
        except Exception as e: ui.notify(t("creation.error", lang, error=e), type="negative")
    with btn_container:
        with ui.row().classes("w-full gap-2"):
            ui.button(t("creation.back", lang), on_click=_creation_back_to_personalize).props("flat")
            ui.button(f"{t('creation.next', lang)} {E['arrow_r']}", on_click=proceed, color="primary").classes("flex-grow")
    return True

def _render_confirm():
    s=S();creation=s["creation"];setup=creation.get("setup");lang=L()
    if not setup: return _render_wishes()

    # --- Draft management ---
    drafts = creation.get("drafts", [setup])
    selected_idx = creation.get("selected_draft", len(drafts) - 1)
    setup = drafts[selected_idx]
    creation["setup"] = setup  # keep in sync

    name=setup.get("character_name","?");concept=setup.get("character_concept","?")
    stats=setup.get("stats",{})
    setting_desc=setup.get("setting_description","")
    location=setup.get("starting_location","")

    # --- Character summary ---
    _name_esc = name.replace('"', '&quot;')
    ui.markdown(f"### {E['mask']} {name}").props(f'aria-label="{_name_esc}"')
    ui.markdown(f"*{concept}*")
    if setting_desc:
        ui.markdown(f"{setting_desc}")
    if location:
        _loc_esc = f"{t('aria.location', lang)}: {location}".replace('"', '&quot;')
        ui.markdown(f"{E['pin']} {location}").props(f'aria-label="{_loc_esc}"')
    sl = get_stat_labels(lang)
    with ui.row().classes("gap-4 my-2"):
        for sk,slabel in sl.items():
            ui.label(f"{slabel}: {stats.get(sk,0)}").classes("px-3 py-1 rounded text-sm").style("background: var(--bg-surface)")
    if creation.get("custom_desc"):
        ui.markdown(f"{E['scroll']} **{t('creation.backstory_title', lang)}:** {creation['custom_desc']}")
    if creation.get("wishes"):
        ui.markdown(f"{E['star']} **{t('creation.wishes_title', lang)}:** {creation['wishes']}")
    if creation.get("content_lines"):
        ui.markdown(f"{E['shield']} **{t('creation.boundaries_title', lang)}:** {creation['content_lines']}")

    # --- "Adjust draft" expander ---
    genres = get_genres(lang)
    tones = get_tones(lang)
    archetypes = get_archetypes(lang)
    custom_genre_lbl = f"{E['pen']} {t('creation.custom_idea', lang)}"
    custom_tone_lbl = f"{E['pen']} {t('creation.custom_tone_btn', lang)}"
    custom_arch_lbl = f"{E['pen']} {t('creation.custom_idea', lang)}"

    with ui.expansion(f"{E['pen']} {t('creation.adjust', lang)}").classes("w-full"):
        edit_name = ui.input("Name", value=setup.get("character_name","")).classes("w-full")
        edit_desc = ui.textarea(t("creation.background", lang), value=creation.get("custom_desc","")).props("rows=3 maxlength=800 counter").classes("w-full")
        ui.separator()
        # Genre dropdown
        genre_labels = list(genres.keys()) + [custom_genre_lbl]
        cur_genre = creation.get("genre","dark_fantasy")
        genre_codes = list(genres.values())
        if cur_genre == "custom" or cur_genre not in genre_codes:
            genre_idx = len(genre_labels) - 1
        else:
            genre_idx = genre_codes.index(cur_genre)
        sel_genre = ui.select(genre_labels, label=t("creation.genre", lang), value=genre_labels[genre_idx]).classes("w-full")
        edit_genre_desc = ui.input(t("creation.genre_desc", lang), value=creation.get("genre_description","")).classes("w-full")
        edit_genre_desc.bind_visibility_from(sel_genre, "value", backward=lambda v: v == custom_genre_lbl)
        # Tone dropdown
        tone_labels = list(tones.keys()) + [custom_tone_lbl]
        cur_tone = creation.get("tone","dark_gritty")
        tone_codes = list(tones.values())
        if cur_tone == "custom" or cur_tone not in tone_codes:
            tone_idx = len(tone_labels) - 1
        else:
            tone_idx = tone_codes.index(cur_tone)
        sel_tone = ui.select(tone_labels, label=t("creation.tone", lang), value=tone_labels[tone_idx]).classes("w-full")
        edit_tone_desc = ui.input(t("creation.tone_desc", lang), value=creation.get("tone_description","")).classes("w-full")
        edit_tone_desc.bind_visibility_from(sel_tone, "value", backward=lambda v: v == custom_tone_lbl)
        # Archetype dropdown
        arch_labels = list(archetypes.keys()) + [custom_arch_lbl]
        cur_arch = creation.get("archetype","outsider_loner")
        arch_codes = list(archetypes.values())
        if cur_arch == "custom" or cur_arch not in arch_codes:
            arch_idx = len(arch_labels) - 1
        else:
            arch_idx = arch_codes.index(cur_arch)
        sel_archetype = ui.select(arch_labels, label=t("creation.archetype", lang), value=arch_labels[arch_idx]).classes("w-full")
        ui.separator()
        edit_wishes = ui.textarea(f"{E['star']} {t('creation.wishes_title', lang)}", value=creation.get("wishes",""), placeholder=t("creation.wishes_placeholder", lang)).props("rows=2 maxlength=400 counter").classes("w-full")
        edit_lines = ui.textarea(f"{E['shield']} {t('creation.boundaries_title', lang)}", value=creation.get("content_lines",""), placeholder=t("creation.boundaries_placeholder", lang)).props("rows=2 maxlength=400 counter").classes("w-full")
        ui.separator()
        adjust_container = ui.column().classes("w-full gap-2")
        async def regenerate_adjusted():
            if not s.get("api_key", "").strip():
                ui.notify(t("game.invalid_api_key", lang), type="negative")
                return
            updated = dict(creation)
            if sel_genre.value == custom_genre_lbl:
                updated["genre"] = "custom"
                updated["genre_description"] = edit_genre_desc.value
                updated["genre_label"] = f"{E['pen']} {(edit_genre_desc.value or '')[:40]}"
            else:
                updated["genre"] = genres.get(sel_genre.value, "dark_fantasy")
                updated["genre_label"] = sel_genre.value
                updated.pop("genre_description", None)
            if sel_tone.value == custom_tone_lbl:
                updated["tone"] = "custom"
                updated["tone_description"] = edit_tone_desc.value
                updated["tone_label"] = f"{E['pen']} {(edit_tone_desc.value or '')[:40]}"
            else:
                updated["tone"] = tones.get(sel_tone.value, "dark_gritty")
                updated["tone_label"] = sel_tone.value
                updated.pop("tone_description", None)
            if sel_archetype.value == custom_arch_lbl:
                updated["archetype"] = "custom"
                updated["archetype_label"] = custom_arch_lbl
            else:
                updated["archetype"] = archetypes.get(sel_archetype.value, "outsider_loner")
                updated["archetype_label"] = sel_archetype.value
            updated["custom_desc"] = edit_desc.value or ""
            updated["player_name"] = edit_name.value or ""
            updated["wishes"] = edit_wishes.value.strip() if edit_wishes.value else ""
            updated["content_lines"] = edit_lines.value.strip() if edit_lines.value else ""
            with adjust_container:
                with ui.row().classes("w-full items-center gap-3"):
                    ui.spinner("dots", size="md", color="primary")
                    ui.label(t("creation.regenerating", lang)).classes("text-sm").style("color: var(--text-secondary)")
            try:
                client = anthropic.Anthropic(api_key=s["api_key"]); config = get_engine_config()
                new_setup = await asyncio.to_thread(call_setup_brain, client, updated, config)
                if "drafts" not in updated: updated["drafts"] = []
                updated["drafts"].append(new_setup)
                updated["selected_draft"] = len(updated["drafts"]) - 1
                updated["setup"] = new_setup; updated["step"] = "confirm"
                if updated["content_lines"]:
                    ucfg = load_user_config(s["current_user"]); ucfg["content_lines"] = updated["content_lines"]
                    save_user_config(s["current_user"], ucfg)
                s["creation"] = updated
                ui.navigate.reload()
            except Exception as e: ui.notify(t("creation.error", lang, error=e), type="negative")
        with adjust_container:
            ui.button(f"{E['refresh']} {t('creation.regenerate', lang)}", on_click=regenerate_adjusted, color="primary").classes("w-full")

    # --- Draft selector (if multiple drafts) ---
    if len(drafts) > 1:
        ui.separator()
        ui.markdown(t("creation.drafts", lang, n=len(drafts)))
        visible_drafts = drafts[-4:] if len(drafts) > 4 else drafts
        offset = len(drafts) - len(visible_drafts)
        with ui.row().classes("gap-2 flex-wrap w-full"):
            for vi, draft in enumerate(visible_drafts):
                i = vi + offset
                is_selected = (i == selected_idx)
                d_name = draft.get("character_name","?")
                d_concept = draft.get("character_concept","?")
                if len(d_concept) > 60: d_concept = d_concept[:57] + "..."
                def pick_draft(idx=i):
                    creation["selected_draft"] = idx
                    creation["setup"] = drafts[idx]
                    s["creation"] = dict(creation)
                    ui.navigate.reload()
                with ui.column().classes("items-center gap-1"):
                    btn = ui.button(f"{E['mask']} {d_name}", on_click=pick_draft, color="primary" if is_selected else None)
                    btn.props("outline" if not is_selected else "")
                    ui.label(d_concept).classes("text-xs text-center").style("color: var(--text-secondary); max-width: 160px")

    # --- Action buttons ---
    ui.separator()
    confirm_container = ui.column().classes("w-full gap-2")
    with confirm_container:
        with ui.row().classes("gap-4"):
            async def start():
                if not s.get("api_key", "").strip():
                    ui.notify(t("game.invalid_api_key", lang), type="negative")
                    return
                start_btn.disable(); reroll_btn.disable()
                with confirm_container:
                    with ui.row().classes("w-full items-center gap-3").props('role="status"'):
                        ui.spinner("dots", size="md", color="primary")
                        loading_label = ui.label(t("creation.world_awakens", lang)) \
                            .classes("text-sm creation-loading-label") \
                            .style("color: var(--text-secondary)")
                    # Rotate loading text every 10 seconds to show progress
                    _msg1 = t("creation.world_awakens", lang)
                    _msg2 = t("creation.world_awakens_2", lang)
                    _msg3 = t("creation.world_awakens_3", lang)
                    await ui.run_javascript(f'''
                        window._loadingMsgs = ["{_msg1}", "{_msg2}", "{_msg3}"];
                        window._loadingIdx = 0;
                        window._loadingTimer = setInterval(() => {{
                            window._loadingIdx = (window._loadingIdx + 1) % window._loadingMsgs.length;
                            const el = document.querySelector('.creation-loading-label');
                            if (el) {{
                                el.style.transition = 'opacity 0.4s ease';
                                el.style.opacity = '0';
                                setTimeout(() => {{
                                    el.textContent = window._loadingMsgs[window._loadingIdx];
                                    el.style.opacity = '1';
                                }}, 400);
                            }}
                        }}, 10000);
                    ''', timeout=3.0)
                await _scroll_chat_bottom()
                try:
                    client=anthropic.Anthropic(api_key=s["api_key"]);config=get_engine_config();username=s["current_user"]
                    game,narration=await asyncio.to_thread(start_new_game,client,creation,config,username)
                    s["game"]=game;s["creation"]=None;s["active_save"]="autosave"
                    s["messages"]=[]
                    s["messages"].append({"scene_marker":t("game.scene_marker", lang, n=1, location=game.current_location)})
                    s["messages"].append({"role":"assistant","content":narration})
                    save_game(game,username,s["messages"],s["active_save"])
                    _ucfg=load_user_config(username);_ucfg["last_save"]="autosave";save_user_config(username,_ucfg)
                    if s.get("tts_enabled",False): s["pending_tts"]=narration
                    ui.navigate.reload()
                except Exception as e:
                    start_btn.enable(); reroll_btn.enable()
                    ui.notify(t("creation.error", lang, error=e), type="negative")
            start_btn = ui.button(f"{E['swords']} {t('creation.start', lang)}", on_click=start, color="primary").classes("text-lg px-8")
            async def reroll():
                if not s.get("api_key", "").strip():
                    ui.notify(t("game.invalid_api_key", lang), type="negative")
                    return
                start_btn.disable(); reroll_btn.disable()
                with confirm_container:
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.spinner("dots", size="md", color="primary")
                        ui.label(t("creation.regenerating", lang)).classes("text-sm").style("color: var(--text-secondary)")
                await _scroll_chat_bottom()
                try:
                    client=anthropic.Anthropic(api_key=s["api_key"]);config=get_engine_config()
                    new_setup=await asyncio.to_thread(call_setup_brain,client,creation,config)
                    updated=dict(creation)
                    updated["setup"]=new_setup;updated["step"]="confirm"
                    if "drafts" not in updated: updated["drafts"]=[]
                    updated["drafts"].append(new_setup)
                    updated["selected_draft"]=len(updated["drafts"])-1
                    s["creation"]=updated
                    ui.navigate.reload()
                except Exception as e:
                    start_btn.enable(); reroll_btn.enable()
                    ui.notify(t("creation.error", lang, error=e), type="negative")
            reroll_btn = ui.button(f"{E['refresh']} {t('creation.reroll', lang)}", on_click=reroll, color="primary").props("outline").classes("text-lg px-8")
            ui.button(t("creation.back", lang), on_click=_creation_back_to_wishes).props("flat")
    return True


# ===============================================================
# GAME LOOP
# ===============================================================

async def process_player_input(text: str, chat_container, sidebar_container=None,
                               sidebar_refresh=None, is_retry: bool = False) -> None:
    s=S();game=s.get("game")
    if not game or not text.strip(): return
    # Double-send guard: prevent concurrent processing
    if s.get("processing", False):
        ui.notify(t("game.still_processing", L()), type="warning", position="top")
        return
    s["processing"] = True
    turn_gen = s.get("_turn_gen", 0)  # Capture generation to detect save-switch during processing
    s["_director_gen"] = s.get("_director_gen", 0) + 1  # Invalidate any in-flight director
    director_gen = s["_director_gen"]
    config=get_engine_config();username=s["current_user"]
    # On retry, the message is already in s["messages"] and rendered — don't duplicate
    if not is_retry:
        _is_corr_input = text.startswith("##")
        display_text = text[2:].strip() if _is_corr_input else text
        msg_entry = {"role": "user", "content": display_text}
        if _is_corr_input:
            msg_entry["correction_input"] = True
        s["messages"].append(msg_entry)
        with chat_container:
            css_corr = " correction" if _is_corr_input else ""
            _user_col = ui.column().classes(f"chat-msg user{css_corr} w-full")
            if not s.get("sr_chat", True):
                _user_col.props('aria-hidden="true"')
            elif s.get("sr_chat", True):
                _user_col.props(f'aria-label="{t("aria.player_says", L())}"')
            with _user_col:
                ui.markdown(display_text)
    try:
        with chat_container:
            spinner=ui.spinner("dots", size="lg")
            spinner.props('role="status" aria-label="%s"' % t("aria.loading", L()))
        # Scroll down so player sees their message + spinner
        await _scroll_chat_bottom()
        # Stop any playing audio
        try:
            await ui.run_javascript('document.querySelectorAll("audio").forEach(a=>{a.pause();a.currentTime=0})', timeout=3.0)
        except TimeoutError:
            pass
        client=anthropic.Anthropic(api_key=s["api_key"])
        # ## prefix → correction flow; otherwise normal turn
        if text.startswith("##"):
            if not game.last_turn_snapshot:
                try: spinner.delete()
                except Exception: pass
                ui.notify(t("correction.no_snapshot", L()), type="warning", position="top")
                s["processing"] = False
                return
            correction_text = text[2:].strip()
            game,narration,director_ctx=await asyncio.to_thread(
                process_correction,client,game,correction_text,config)
            roll,burn_info=None,None
            _is_correction=True
        else:
            game,narration,roll,burn_info,director_ctx=await asyncio.to_thread(
                process_turn,client,game,text,config)
            _is_correction=False
        # Staleness check: if user loaded a different save during processing, discard result
        if s.get("_turn_gen", 0) != turn_gen:
            log(f"[Turn] Discarding stale response (gen {turn_gen} → {s.get('_turn_gen', 0)})")
            try: spinner.delete()
            except Exception: pass
            return
        s["game"]=game
        spinner.delete()
        # --- Refresh sidebar (NPCs, stats, clocks, actions) ---
        if sidebar_refresh is not None:
            try:
                sidebar_refresh(game)
            except Exception as e:
                log(f"[Sidebar] Full refresh failed: {e}", level="warning")
        elif sidebar_container is not None:
            try:
                sidebar_container.clear()
                with sidebar_container:
                    render_sidebar_status(game, session=s)
            except Exception as e:
                log(f"[Sidebar] Status refresh failed: {e}", level="warning")
        if not _is_correction and game.scene_count > 1:
            s["messages"].append({"scene_marker":t("game.scene_marker", L(), n=game.scene_count, location=game.current_location)})
        roll_data=None
        if roll:
            ll=game.session_log[-1] if game.session_log else {}
            roll_data=build_roll_data(roll, consequences=ll.get("consequences",[]),
                clock_events=ll.get("clock_events",[]),
                brain={"position":ll.get("position","risky"),"effect":ll.get("effect","standard")},
                chaos_interrupt=ll.get("chaos_interrupt",""))
        if _is_correction:
            # If the correction changed current_location, update the stored scene marker
            # string for the current scene so render_chat_messages() shows the new name.
            _new_marker = t("game.scene_marker", L(), n=game.scene_count, location=game.current_location)
            for i in range(len(s["messages"]) - 1, -1, -1):
                if s["messages"][i].get("scene_marker"):
                    s["messages"][i]["scene_marker"] = _new_marker
                    break
            # Replace last assistant message in history with the corrected narration
            for i in range(len(s["messages"])-1, -1, -1):
                if s["messages"][i].get("role") == "assistant":
                    s["messages"][i] = {"role":"assistant","content":narration,
                                        "roll_data":roll_data,"corrected":True}
                    break
            # Remove ephemeral correction input from message history (before save)
            for i in range(len(s["messages"]) - 1, -1, -1):
                if s["messages"][i].get("correction_input"):
                    s["messages"].pop(i)
                    break
        else:
            s["messages"].append({"role":"assistant","content":narration,"roll_data":roll_data})
        # Render AI response
        if _is_correction:
            # Fade out the green correction input message before re-rendering
            try:
                await ui.run_javascript('''
                    const msgs = document.querySelectorAll('.chat-msg.user.correction');
                    const last = msgs[msgs.length - 1];
                    if (last) {
                        last.style.transition = 'opacity 0.5s ease-out';
                        last.style.opacity = '0';
                    }
                ''', timeout=3.0)
            except TimeoutError:
                pass
            await asyncio.sleep(0.6)
            # Full re-render without the correction input
            chat_container.clear()
            with chat_container:
                scroll_target_id = render_chat_messages(chat_container)
        else:
            scroll_target_id = f"msg-{len(s['messages'])}"
            with chat_container:
                if game.scene_count > 1:
                    ui.html(t("game.scene_marker", L(), n=game.scene_count, location=game.current_location)).classes("scene-marker").props(f'id="{scroll_target_id}"')
                else:
                    ui.element('div').props(f'id="{scroll_target_id}"')
                _has_chaos_interrupt = bool(roll_data and roll_data.get("chaos_interrupt"))
                msg_col = ui.column().classes("chat-msg assistant w-full et-new" + (" et-chaos" if _has_chaos_interrupt else ""))
                if not s.get("sr_chat", True):
                    msg_col.props('aria-hidden="true"')
                elif s.get("sr_chat", True):
                    msg_col.props(f'aria-label="{t("aria.narrator_says", L())}"')
                with msg_col:
                    _narr = _clean_narration(narration)
                    if s.get("narrator_font") == "highlight":
                        _narr = _highlight_dialog(_narr)
                    ui.markdown(_narr)
                    if roll_data: render_dice_display(roll_data)
        # Entity highlights (Design mode) — process newly rendered message
        # For corrections: render_chat_messages() already called _inject_entity_highlights
        if s.get("narrator_font") == "highlight" and not _is_correction:
            _inject_entity_highlights(game, scope_new=True)
        # Two-step scroll: bottom first (forces DOM render), then up to scene marker
        await _scroll_chat_bottom()
        if scroll_target_id:
            await _scroll_to_element(scroll_target_id)
        # Save after rendering — player sees narration immediately, save doesn't block display
        save_game(game,username,s["messages"],s.get("active_save","autosave"))
        # Fire Director in background — doesn't block narration display
        if director_ctx:
            _dc=director_ctx; _g=game; _u=username; _s=s; _gen=turn_gen; _dgen=director_gen
            async def _bg_director():
                try:
                    # Don't even run if a newer turn has already started
                    # (the game object may be mutated by the new turn's thread)
                    if _s.get("_director_gen", 0) != _dgen:
                        log("[Director] Skipping — newer turn already started")
                        return
                    await asyncio.to_thread(run_deferred_director, client, _g, _dc)
                    # Don't save if user switched to a different game during Director processing
                    if _s.get("_turn_gen", 0) != _gen:
                        log("[Director] Discarding stale save (game context changed)")
                        return
                    # Don't save if another turn started while Director was running
                    if _s.get("_director_gen", 0) != _dgen:
                        log("[Director] Discarding stale save (newer turn started)")
                        return
                    save_game(_g, _u, _s["messages"], _s.get("active_save", "autosave"))
                    log("[Director] Background save complete")
                except Exception as e:
                    log(f"[Director] Background call failed: {e}", level="warning")
            asyncio.create_task(_bg_director())
        # TTS — skip if momentum burn pending (page will reload, cutting off audio)
        if burn_info:
            # Serialize RollResult to dict for JSON-safe session storage
            burn_info["roll"] = asdict(burn_info["roll"])
            s["pending_burn"]=burn_info; ui.navigate.reload()
        else:
            # For corrections msg_col is None (full re-render) — TTS still works, no container needed
            tts_container = msg_col if not _is_correction else None
            await do_tts(narration, tts_container)
            # Reload if game state now requires special UI (epilogue offer, game over)
            # These cards only render on page load, so a reload is needed to show them.
            bp = game.story_blueprint or {}
            if game.game_over or (bp.get("story_complete") and not game.epilogue_dismissed and not game.epilogue_shown):
                ui.navigate.reload()
    except anthropic.AuthenticationError:
        try: spinner.delete()
        except Exception: pass
        ui.notify(t("game.invalid_api_key", L()), type="negative")
    except Exception as e:
        try: spinner.delete()
        except Exception: pass
        # Show inline retry button in chat instead of just a toast notification
        _retry_text = text  # capture for closure
        _retry_cc = chat_container
        _retry_sr = sidebar_refresh
        with chat_container:
            retry_row = ui.row().classes("w-full items-center gap-2 py-1 px-3").style(
                "background: var(--error-dim); border: 1px solid var(--error-border); "
                "border-radius: 8px; margin: 0.25rem 0"
            )
            retry_row.props('role="alert"')
            with retry_row:
                err_short = str(e)[:120]
                ui.label(f"{E['warn']} {err_short}").classes("text-xs text-red-300 flex-grow").style("word-break: break-word")
                async def _do_retry(rr=retry_row, rt=_retry_text, rc=_retry_cc, rs=_retry_sr):
                    try: rr.delete()
                    except Exception: pass
                    await process_player_input(rt, rc, sidebar_refresh=rs, is_retry=True)
                ui.button(icon="refresh", on_click=_do_retry).props(f'flat dense round aria-label="{t("aria.retry", L())}"').classes(
                    "text-red-300 hover:text-white"
                ).style("min-width: 40px; min-height: 40px").tooltip(t("game.retry_tooltip", L()))
    finally:
        # Only reset processing if this is still the active generation
        # (prevents stale task's finally from clearing a newer task's flag)
        if s.get("_turn_gen", 0) == turn_gen:
            s["processing"] = False


def render_momentum_burn() -> bool:
    s=S();bd=s.get("pending_burn");lang=L()
    if not bd: return False
    # Reconstruct RollResult from dict (serialization-safe)
    rd_raw=bd["roll"]
    roll=RollResult(**rd_raw) if isinstance(rd_raw, dict) else rd_raw
    nr=bd["new_result"]
    # Show pre-consequence momentum (the actual value being burned, before MISS penalties reduced it)
    pre_momentum = bd.get("pre_snapshot", {}).get("momentum", bd["cost"])
    rl=t("momentum.weak_hit", lang) if nr=="WEAK_HIT" else t("momentum.strong_hit", lang)
    with ui.card().classes("w-full p-4 burn-card").style("background: var(--accent-dim); border: 1px solid var(--accent)") as burn_card:
        burn_card.props('role="alertdialog"')
        ui.label(f"{E['fire']} {t('sidebar.momentum', lang)}").classes("text-xs font-semibold").style("color: var(--accent-light); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 0.25rem")
        ui.markdown(t("momentum.question", lang, cost=pre_momentum, result=rl))
        with ui.row().classes("gap-4 mt-4") as btn_row:
            async def burn():
                try:
                    # Show spinner and disable buttons
                    btn_row.set_visibility(False)
                    with burn_card:
                        burn_spinner = ui.row().classes("w-full items-center gap-2")
                        burn_spinner.props('role="status"')
                        with burn_spinner:
                            ui.spinner("dots", size="lg")
                            ui.label(t("momentum.gathering", lang)).classes("text-sm").style("color: var(--text-secondary)")
                    await _scroll_chat_bottom()
                    config=get_engine_config();username=s["current_user"]
                    client=anthropic.Anthropic(api_key=s["api_key"])
                    game,narration=await asyncio.to_thread(process_momentum_burn,client,s["game"],roll,nr,bd["brain"],
                        player_words=bd.get("player_words",""),config=config,pre_snapshot=bd.get("pre_snapshot"),
                        chaos_interrupt=bd.get("chaos_interrupt"))
                    s["game"]=game;s["pending_burn"]=None
                    ur=RollResult(roll.d1,roll.d2,roll.c1,roll.c2,roll.stat_name,roll.stat_value,roll.action_score,nr,roll.move,getattr(roll,"match",roll.c1==roll.c2))
                    ll=game.session_log[-1] if game.session_log else {}
                    rd=build_roll_data(ur,consequences=ll.get("consequences",[]),clock_events=ll.get("clock_events",[]),brain=bd["brain"],chaos_interrupt=ll.get("chaos_interrupt",""))
                    msgs=s["messages"]
                    if msgs and msgs[-1].get("role")=="assistant":
                        msgs[-1]={"role":"assistant","content":f"*{E['fire']} {t('momentum.gathering', lang)}*\n\n{narration}",
                                  "roll_data":rd}
                    save_game(game,username,s["messages"],s.get("active_save","autosave"))
                    if s.get("tts_enabled",False): s["pending_tts"]=narration
                    # Rewind effect: VHS-Scan-Linien + Chrom-Schimmer vor dem Reload
                    try:
                        await ui.run_javascript('''
                            (function(){
                                var style = document.createElement('style');
                                style.textContent =
                                    '@keyframes _rw_lines{0%{background-position:0 0;opacity:0.85}40%{opacity:1}100%{background-position:0 -300px;opacity:0}}' +
                                    '@keyframes _rw_flash{0%,100%{opacity:0}8%{opacity:0.9}20%{opacity:0.3}50%{opacity:0.6}80%{opacity:0.15}}' +
                                    '@keyframes _rw_chrom{0%{opacity:0;transform:translateY(0)}15%{opacity:1}100%{opacity:0;transform:translateY(-8px)}}' +
                                    '._rw_wrap{position:fixed;inset:0;z-index:99999;pointer-events:none;overflow:hidden}' +
                                    '._rw_lines{position:absolute;inset:0;background:repeating-linear-gradient(to bottom,transparent 0px,transparent 3px,rgba(255,255,255,0.045) 3px,rgba(255,255,255,0.045) 4px);background-size:100% 4px;animation:_rw_lines 0.6s linear forwards}' +
                                    '._rw_flash{position:absolute;inset:0;background:linear-gradient(180deg,rgba(220,180,80,0) 0%,rgba(220,180,80,0.55) 40%,rgba(220,180,80,0) 100%);animation:_rw_flash 0.55s ease forwards}' +
                                    '._rw_chrom{position:absolute;inset:0;background:linear-gradient(180deg,transparent 30%,rgba(150,220,255,0.12) 50%,rgba(255,200,100,0.1) 52%,transparent 70%);animation:_rw_chrom 0.55s ease forwards}';
                                document.head.appendChild(style);
                                var wrap = document.createElement('div');
                                wrap.className = '_rw_wrap';
                                wrap.innerHTML = '<div class="_rw_lines"></div><div class="_rw_flash"></div><div class="_rw_chrom"></div>';
                                document.body.appendChild(wrap);
                                setTimeout(function(){ wrap.remove(); style.remove(); }, 750);
                            })();
                        ''', timeout=3.0)
                        await asyncio.sleep(0.55)
                    except Exception:
                        pass
                    ui.navigate.reload()
                except Exception as e:
                    btn_row.set_visibility(True)
                    try: burn_spinner.delete()
                    except Exception: pass
                    ui.notify(t("game.error", lang, error=e), type="negative")
            ui.button(f"{E['fire']} {t('momentum.yes', lang)}", on_click=burn, color="primary")
            def decline(): s["pending_burn"]=None; ui.navigate.reload()
            ui.button(t("momentum.no", lang), on_click=decline)
    return True


def _make_chapter_action(game, chapter_msg_key: str):
    """Create async new-chapter and sync full-restart callbacks.
    Shared by render_epilogue and render_game_over to avoid duplication."""
    s = S(); lang = L()

    async def new_ch():
        if not s.get("api_key", "").strip():
            ui.notify(t("game.invalid_api_key", lang), type="negative")
            return
        # Show persistent loading dialog (blocks further clicks, visible feedback)
        loading_dlg = ui.dialog().props("persistent")
        with loading_dlg, ui.card().classes("items-center p-6").style(
            "background: var(--bg-surface); min-width: 260px"):
            ui.spinner("dots", size="lg", color="primary")
            ui.label(t(chapter_msg_key, lang, n=game.chapter_number + 1)).classes(
                "text-sm mt-2").style("color: var(--text-secondary)")
        loading_dlg.open()
        try:
            config = get_engine_config(); username = s["current_user"]
            client = anthropic.Anthropic(api_key=s["api_key"])
            g, n = await asyncio.to_thread(start_new_chapter, client, game, config, username)
            loading_dlg.close()
            # Archive the just-completed chapter's messages before replacing them
            completed_ch = g.chapter_number - 1
            ch_title = ""
            if g.campaign_history:
                ch_title = g.campaign_history[-1].get("title", "")
            active_save = s.get("active_save", "autosave")
            try:
                save_chapter_archive(username, active_save, completed_ch, s["messages"], title=ch_title)
            except Exception as arch_e:
                log(f"[ChapterArchive] Failed to archive chapter {completed_ch}: {arch_e}", level="warning")
            # Clear chapter viewing state if active
            s["viewing_chapter"] = None; s["chapter_view_messages"] = None
            s["game"] = g; s["pending_burn"] = None; ch = g.chapter_number
            s["messages"] = [
                {"scene_marker": t("game.scene_marker", lang, n=1, location=g.current_location)},
                {"role": "assistant", "content": f"*{E['book']} {t(chapter_msg_key, lang, n=ch)}*\n\n{n}"},
            ]
            save_game(g, username, s["messages"], s.get("active_save", "autosave"))
            if s.get("tts_enabled", False): s["pending_tts"] = n
            ui.navigate.reload()
        except Exception as e:
            loading_dlg.close()
            log(f"[Chapter] Error starting new chapter: {e}", level="warning")
            ui.notify(t("game.error", lang, error=e), type="negative")

    def full_new():
        delete_chapter_archives(s["current_user"], s.get("active_save", "autosave"))
        s["game"] = None; s["creation"] = None; s["messages"] = []; s["active_save"] = "autosave"
        s["viewing_chapter"] = None; s["chapter_view_messages"] = None
        ui.navigate.reload()

    return new_ch, full_new


def render_epilogue() -> bool:
    """Render epilogue offer or post-epilogue options.

    Returns True if footer should be hidden (epilogue done, waiting for player choice).
    Returns False if just showing the offer card (input stays active) or nothing to show.
    """
    s=S();game=s.get("game");lang=L()
    if not game or game.game_over:
        return False
    bp = game.story_blueprint or {}

    # --- Post-epilogue: chapter complete, choose next step ---
    if game.epilogue_shown:
        with ui.card().classes("w-full p-4").style("background: var(--accent-dim); border: 1px solid var(--accent-border)"):
            ui.markdown(f"{E['star']} **{t('epilogue.done_title', lang)}**")
            ui.label(t("epilogue.done_text", lang)).classes("text-sm mt-1")
            with ui.row().classes("gap-4 mt-4"):
                new_ch, full_new = _make_chapter_action(game, "epilogue.chapter_msg")
                ui.button(f"{E['refresh']} {t('epilogue.new_chapter', lang)}", on_click=new_ch, color="primary")
                ui.button(f"{t('epilogue.restart', lang)}", on_click=full_new)
        return True  # Hide footer — story is done

    # --- Epilogue offer: story complete but epilogue not yet generated ---
    if bp.get("story_complete") and not game.epilogue_dismissed:
        with ui.card().classes("w-full p-4").style("background: var(--accent-dim); border: 1px solid var(--accent-border)"):
            ui.markdown(f"{E['star']} **{t('epilogue.offer_title', lang)}**")
            ui.label(t("epilogue.offer_text", lang)).classes("text-sm mt-1")
            btn_row = ui.row().classes("gap-4 mt-4")
            with btn_row:
                async def gen_epilogue():
                    btn_row.clear()
                    with btn_row:
                        ui.spinner(size="sm")
                        ui.label(t("epilogue.generating", lang)).classes("text-sm")
                    try:
                        config=get_engine_config();username=s["current_user"]
                        client=anthropic.Anthropic(api_key=s["api_key"])
                        g, epilogue_text = await asyncio.to_thread(generate_epilogue, client, game, config)
                        s["game"] = g
                        s["messages"].append({"scene_marker": f"{E['star']} {t('epilogue.marker', lang)}"})
                        s["messages"].append({"role":"assistant","content": epilogue_text})
                        save_game(g, username, s["messages"], s.get("active_save","autosave"))
                        if s.get("tts_enabled", False): s["pending_tts"] = epilogue_text
                        ui.navigate.reload()
                    except Exception as e:
                        btn_row.clear()
                        with btn_row:
                            ui.button(f"{E['star']} {t('epilogue.generate', lang)}", on_click=gen_epilogue, color="primary")
                            def dismiss(): game.epilogue_dismissed=True; save_game(game,s["current_user"],s["messages"],s.get("active_save","autosave")); ui.navigate.reload()
                            ui.button(t("epilogue.continue", lang), on_click=dismiss).props("flat")
                        ui.notify(t("game.error", lang, error=e), type="negative")
                ui.button(f"{E['star']} {t('epilogue.generate', lang)}", on_click=gen_epilogue, color="primary")
                def dismiss(): game.epilogue_dismissed=True; save_game(game,s["current_user"],s["messages"],s.get("active_save","autosave")); ui.navigate.reload()
                ui.button(t("epilogue.continue", lang), on_click=dismiss).props("flat")
            ui.label(t("epilogue.dismiss_hint", lang)).classes("text-xs mt-2").style("color: var(--text-secondary)")
    return False  # Keep footer active — player can still type


def render_game_over() -> bool:
    s=S();game=s.get("game");lang=L()
    if not game or not game.game_over: return False
    kid=s.get("kid_friendly",False)
    import json as _json

    # Inject full-screen "Schwarzer Vorhang" overlay via JS.
    # It fades out after the animation and hands off to the NiceGUI buttons below.
    _sub   = t("gameover.dark", lang) if not kid else t("gameover.kid", lang)
    _flavor = t("gameover.flavor_kid" if kid else "gameover.flavor", lang, name=game.player_name)
    _skull  = "⭐" if kid else "💀"
    _title  = "ABENTEUER ZU ENDE" if lang == "de" else "ADVENTURE OVER"
    ui.run_javascript(f'''
        (function(){{
            if (document.querySelector('._go_overlay')) return;
            var ov = document.createElement('div');
            ov.className = '_go_overlay';
            ov.innerHTML =
                '<span class="_go_skull">{_skull}</span>'
                + '<div class="_go_title">{_title}</div>'
                + '<div class="_go_sub">{html_mod.escape(_sub)}</div>'
                + '<div class="_go_line"></div>'
                + '<div class="_go_flavor">{html_mod.escape(_flavor)}</div>';
            document.body.appendChild(ov);
            // Remove from DOM after animation completes
            setTimeout(function(){{ ov.remove(); }}, 5500);
        }})();
    ''')

    # NiceGUI card — becomes visible once overlay fades (after ~5.2s)
    with ui.card().classes("w-full p-4").style(
        "background: var(--error-dim); border: 1px solid var(--error-border)"
    ):
        ui.markdown(f"{t('gameover.title', lang)} " + (_sub))
        with ui.row().classes("gap-4 mt-4"):
            new_ch, full_new = _make_chapter_action(game, "gameover.chapter_msg")
            ui.button(f"{E['refresh']} {t('gameover.new_chapter', lang)}", on_click=new_ch, color="primary")
            ui.button(f"{t('gameover.restart', lang)}", on_click=full_new)
    return True


# ===============================================================
# LOGIN PAGE
# ===============================================================

# show_login — now built inline by main_page phases


# ===============================================================
# MAIN PAGE
# ===============================================================

@ui.page("/", response_timeout=30)
async def main_page(client: Client):
    ui.colors(primary='#D97706', secondary='#92400E', accent='#F59E0B')
    ui.add_head_html(CUSTOM_CSS)

    # ── Always show a spinner immediately (SSR, no WebSocket needed) ──
    loading = ui.column().classes("w-full items-center mt-20 gap-4")
    with loading:
        ui.spinner("dots", size="lg", color="primary")
        ui.label(t("conn.loading", DEFAULT_UI_LANG or DEFAULT_LANG)).classes("text-gray-400")
    # JS fallback: auto-reload if WebSocket never connects, with mobile lifecycle recovery
    ui.add_head_html("""<script>
(function(){
    // --- Initial load: auto-reload if WebSocket never connects ---
    var _r = parseInt(sessionStorage.getItem('_wsRetry')||'0');
    // Time-based reset: if last retry was >60s ago, start fresh (prevents permanent lockout)
    var _ts = parseInt(sessionStorage.getItem('_wsRetryTs')||'0');
    if(_ts && Date.now()-_ts > 60000) _r = 0;
    if(_r < 5){
        window.__wsTimeout = setTimeout(function(){
            if(!window.__wsConnected){
                sessionStorage.setItem('_wsRetry', String(_r+1));
                sessionStorage.setItem('_wsRetryTs', String(Date.now()));
                location.reload();
            }
        }, 20000);
    } else {
        // Even after 5 fast retries, try once more after a longer delay (never give up)
        window.__wsTimeout = setTimeout(function(){
            if(!window.__wsConnected){
                sessionStorage.removeItem('_wsRetry');
                sessionStorage.removeItem('_wsRetryTs');
                location.reload();
            }
        }, 45000);
    }
    // --- Safari back-forward cache: force reload on bfcache restore ---
    // iOS Safari aggressively caches pages; restored pages have dead WebSockets
    window.addEventListener('pageshow', function(e){
        if(e.persisted) location.reload();
    });
    // --- Phone lock/unlock recovery ---
    // iOS Safari can kill WebSockets after just a few seconds of sleep.
    // Strategy: when page becomes visible after being hidden, check page health.
    var _healthCheckId = 0;
    function _pageHasContent(){
        // Check if main content area has any children (skeleton should always have content after init)
        var ca = document.querySelector('.max-w-4xl');
        return ca && ca.children.length > 0;
    }
    document.addEventListener('visibilitychange', function(){
        if(document.visibilityState==='hidden'){
            window.__hiddenAt = Date.now();
            clearInterval(_healthCheckId);
        } else {
            var elapsed = window.__hiddenAt ? Date.now()-window.__hiddenAt : 0;
            window.__hiddenAt = 0;
            // After >5s hidden: page is likely dead or degraded on mobile
            if(elapsed > 5000){
                // Give NiceGUI's reconnect a brief chance (3s), then check health
                window.__recoveryTimeout = setTimeout(function(){
                    if(!_pageHasContent()){
                        // Page is empty after reconnect — force clean reload
                        sessionStorage.removeItem('_wsRetry');
                        sessionStorage.removeItem('_wsRetryTs');
                        location.reload();
                    }
                }, 3000);
                // Also set a longer fallback: if page is still broken after 12s, force reload
                // (covers the case where NiceGUI reconnect "succeeds" but page is empty)
                setTimeout(function(){
                    if(!_pageHasContent()){
                        sessionStorage.removeItem('_wsRetry');
                        sessionStorage.removeItem('_wsRetryTs');
                        location.reload();
                    }
                }, 12000);
            }
            // Regardless of elapsed time: schedule periodic health check for 30s
            // Catches delayed WebSocket death that visibilitychange alone misses
            var _checks = 0;
            _healthCheckId = setInterval(function(){
                _checks++;
                if(_checks > 6){clearInterval(_healthCheckId); return;} // stop after 30s
                if(window.__wsConnected && !_pageHasContent()){
                    clearInterval(_healthCheckId);
                    sessionStorage.removeItem('_wsRetry');
                    sessionStorage.removeItem('_wsRetryTs');
                    location.reload();
                }
            }, 5000);
        }
    });
})();
    </script>""")

    # ── Wait for WebSocket connection ──
    try:
        await client.connected(timeout=20)
    except TimeoutError:
        return  # Spinner stays visible; JS auto-reload will retry
    # WebSocket connected → cancel auto-reload, cancel recovery timeout, reset retry counter
    try:
        await ui.run_javascript(
            "window.__wsConnected=true;"
            "clearTimeout(window.__wsTimeout);"
            "clearTimeout(window.__recoveryTimeout);"
            "sessionStorage.removeItem('_wsRetry');"
            "sessionStorage.removeItem('_wsRetryTs');",
            timeout=5.0)
    except TimeoutError:
        pass  # Non-critical, page still works without it

    # ── WebSocket connected → init session ──
    # app.storage.tab requires a sessionStorage→WebSocket roundtrip to establish the
    # tab ID. On desktop browsers this completes in <100ms. iOS Safari is significantly
    # slower after a manually-trusted self-signed certificate is installed — the tab ID
    # roundtrip can take 10–20s. We retry generously (30 × 1.0s = 30s max) to cover
    # this case without affecting desktop performance (which succeeds on attempt 1).
    for _attempt in range(30):
        try:
            init_session()
            break
        except RuntimeError:
            if _attempt == 5:
                log("[Session] app.storage.tab slow to initialize — still waiting (iOS Safari?)")
            await asyncio.sleep(1.0)
    else:
        log("[Session] app.storage.tab not available after 30s — giving up", level="warning")
        return
    loading.delete()
    setup_file_logging()
    s = S()

    # Accessibility: set HTML lang attribute for screen reader language/accent detection
    _init_lang = L()  # Default or previously stored UI language
    try:
        await ui.run_javascript(f'document.documentElement.lang="{_init_lang}"', timeout=3.0)
    except TimeoutError:
        pass

    # ==================================================================
    # PAGE SKELETON — created once at page build, shown/hidden per phase
    # ==================================================================

    # Slim header with hamburger menu (hidden until main app phase)
    with ui.header(fixed=True).classes("rpg-slim-header items-center").style("padding: 0 0.5rem") as header:
        _hamburger_btn = ui.button(icon="menu", on_click=lambda: drawer.toggle()) \
            .props(f'flat round dense aria-label="{t("aria.menu_open", L())}"') \
            .classes("text-gray-400 hover:text-white") \
            .style("min-width: 44px; min-height: 44px")
    header.set_value(False)

    # Left drawer (created at page level, hidden initially, populated in main phase)
    with ui.left_drawer(value=False).props(f'width=320 breakpoint=768 aria-label="{t("aria.sidebar", L())}"') as drawer:
        drawer_content = ui.column().classes("w-full")

    # Accessibility: hide main content from screen readers when drawer overlays (mobile < 768px)
    drawer.on('show', lambda: ui.run_javascript('''
        if (window.innerWidth < 768) {
            document.querySelector('.q-page')?.setAttribute('aria-hidden','true');
            document.querySelector('.q-footer')?.setAttribute('aria-hidden','true');
        }
    '''))
    drawer.on('hide', lambda: ui.run_javascript('''
        document.querySelector('.q-page')?.removeAttribute('aria-hidden');
        document.querySelector('.q-footer')?.removeAttribute('aria-hidden');
    '''))

    # Footer (created at page level, hidden initially, populated in main phase)
    with ui.footer(fixed=True).classes("q-pa-none").style(
        "background: var(--bg-primary); border-top: 1px solid var(--border)"
    ) as footer:
        footer.props(f'aria-label="{t("aria.input_area", L())}"')
        footer_content = ui.column().classes("w-full")
    footer.set_value(False)

    # Main content area
    content_area = ui.column().classes("w-full max-w-4xl mx-auto px-4 sm:px-0")
    content_area.props(f'role="main" aria-label="{t("aria.main_content", L())}"')

    # ==================================================================
    # PHASE FUNCTIONS — transition without ui.navigate.reload()
    # ==================================================================

    def _focus_element(css_selector: str, delay_ms: int = 400):
        """Move keyboard/screen-reader focus to the first matching element after a short delay."""
        ui.run_javascript(f'''
            setTimeout(() => {{
                const el = document.querySelector('{css_selector}');
                if (el) {{ el.focus(); }}
            }}, {delay_ms});
        ''')

    def _show_login_phase():
        """Phase 1: Invite code login (no reload on success)."""
        header.set_value(False)
        drawer.set_value(False)
        footer.set_value(False)
        content_area.clear()
        lang = L()
        with content_area:
            with ui.column().classes("w-full max-w-sm mx-auto mt-20 gap-4 items-center"):
                ui.label(f"{E['swords']} {t('login.title', lang)}").classes("text-2xl font-bold").props(f'aria-label="{t("login.title", lang)}"')
                ui.label(t("user.subtitle", lang)).classes("text-gray-400 italic")
                ui.label(t("login.subtitle", lang)).classes("text-gray-400 text-sm")
                code_inp = ui.input(t("login.code_label", lang), password=True, password_toggle_button=True).classes("w-full")
                error_label = ui.label("").classes("text-red-400 text-sm")
                error_label.props('role="alert"')
                error_label.set_visibility(False)
                async def check_code():
                    client_ip = client.ip or "unknown"
                    if not _check_invite_rate_limit(client_ip):
                        error_label.text = t("login.rate_limited", lang)
                        error_label.set_visibility(True)
                        return
                    if code_inp.value and code_inp.value.strip() == INVITE_CODE:
                        s["authenticated"] = True
                        if s.get("current_user"):
                            await _show_main_phase()
                        else:
                            _show_user_selection_phase()
                    else:
                        _record_invite_failure(client_ip)
                        error_label.text = t("login.error", lang)
                        error_label.set_visibility(True)
                code_inp.on("keydown.enter", check_code)
                ui.button(t("login.submit", lang), on_click=check_code, color="primary").classes("w-full")
        _focus_element('.q-page input', delay_ms=500)

    def _show_user_selection_phase():
        """Phase 2: User selection (no reload on select)."""
        header.set_value(False)
        drawer.set_value(False)
        footer.set_value(False)
        content_area.clear()
        lang = L()
        with content_area:
            with ui.column().classes("w-full items-center mt-12"):
                ui.label(t("user.title", lang)).classes("text-3xl font-bold")
                ui.label(t("user.subtitle", lang)).classes("text-gray-400 italic mb-2")
                ui.label(t("user.who_plays", lang)).classes("text-lg mb-8").style("color: var(--text-secondary)")
                users = list_users()
                if users:
                    with ui.row().classes("gap-4 flex-wrap justify-center"):
                        for user in users:
                            name = user["name"]
                            ui.button(name, on_click=lambda n=name: _select_user(n),
                                      color="primary").classes("px-8 py-4 text-lg")
                    ui.separator().classes("my-4 w-96")
                with ui.expansion(f"{E['plus']} {t('user.new_player', lang)}", value=len(users) == 0).classes("w-96"):
                    inp = ui.input(t("user.name", lang), placeholder=t("user.name_placeholder", lang)).props("maxlength=30").classes("w-full")
                    async def create():
                        n = inp.value.strip()
                        if n:
                            if create_user(n):
                                await _select_user(n)
                            else:
                                ui.notify(t("user.exists", lang, name=n), type="negative")
                    ui.button(f"{E['checkmark']} {t('user.create', lang)}", on_click=create, color="primary").classes("w-full mt-2")
                if users:
                    with ui.expansion(f"{E['gear']} {t('user.manage', lang)}").classes("w-96"):
                        names = [u["name"] for u in users]
                        sel = ui.select(names, label=t("user.remove_label", lang), value=names[0]).classes("w-full")
                        async def del_user():
                            with ui.dialog() as dlg, ui.card():
                                ui.label(t("user.confirm_delete", lang, name=sel.value))
                                with ui.row():
                                    ui.button(t("user.yes", lang), on_click=lambda: (delete_user(sel.value), dlg.close(), _show_user_selection_phase()), color="negative")
                                    ui.button(t("user.no", lang), on_click=dlg.close)
                            dlg.open()
                        ui.button(f"{E['trash']} {t('user.remove_label', lang)}", on_click=del_user, color="red").classes("w-full mt-2")
                if not s.get("api_key"):
                    ui.separator().classes("my-4 w-96")
                    ui.label(f"{E['gear']} {t('user.api_hint', lang)}").classes("text-sm text-gray-400 w-96 text-center")
        _focus_element('.q-page .q-btn', delay_ms=500)

    async def _show_language_onboarding(username: str):
        """Show language selection overlay for first-time users."""
        lang = L()
        done = asyncio.Event()
        with ui.dialog() as dlg, ui.card().classes("w-full max-w-sm p-6"):
            dlg.props(f'persistent aria-label="{t("onboarding.title", lang)}"')
            _title = t("onboarding.title", lang)
            ui.label(f"{E['globe']} {_title}").classes("text-xl font-bold").props(f'aria-label="{_title}"')
            ui.label(t("onboarding.subtitle", lang)).classes("text-sm").style("color: var(--text-secondary)")
            ui.separator().classes("my-2")
            ui_lang_labels = list(UI_LANGUAGES.keys())
            _code_to_label = {v: k for k, v in UI_LANGUAGES.items()}
            cur_ui = _code_to_label.get(s.get("ui_lang", DEFAULT_UI_LANG or DEFAULT_LANG), ui_lang_labels[0])
            ui_sel = ui.select(ui_lang_labels, label=t("settings.ui_lang", lang), value=cur_ui).classes("w-full")
            narr_sel = ui.select(list(LANGUAGES.keys()), label=t("settings.narration_lang", lang), value=s.get("narration_lang", "Deutsch")).classes("w-full")
            async def confirm():
                chosen_ui = UI_LANGUAGES.get(ui_sel.value, DEFAULT_LANG)
                s["ui_lang"] = chosen_ui
                s["narration_lang"] = narr_sel.value
                ucfg = load_user_config(username)
                ucfg["ui_lang"] = chosen_ui
                ucfg["narration_lang"] = narr_sel.value
                # Sensible defaults for new users
                ucfg.setdefault("dice_display", 1)        # Simple
                ucfg.setdefault("stt_enabled", True)       # STT on
                ucfg.setdefault("whisper_size", "medium")  # Medium model
                ucfg.setdefault("sr_chat", True)           # Screen reader in chat
                save_user_config(username, ucfg)
                load_user_settings(username)
                s["user_config_loaded"] = True
                dlg.close()
                done.set()
            ui.button(f"{t('onboarding.confirm', lang)} {E['arrow_r']}", on_click=confirm, color="primary").classes("w-full mt-4")
        dlg.open()
        await done.wait()

    async def _select_user(name: str):
        """Handle user selection → transition to main phase without reload."""
        s["current_user"] = name
        load_user_settings(name)
        s["user_config_loaded"] = True
        # First-time user: show language onboarding before entering the app
        if not load_user_config(name):
            await _show_language_onboarding(name)
        # Auto-load last used save (or autosave as fallback)
        if not s.get("game"):
            _login_cfg = load_user_config(name)
            _last_save = _login_cfg.get("last_save", "autosave")
            loaded, hist = load_game(name, _last_save)
            if not loaded and _last_save != "autosave":
                loaded, hist = load_game(name, "autosave")
                _last_save = "autosave"
            if loaded:
                s["game"] = loaded
                s["messages"] = hist
                s["active_save"] = _last_save
        await _show_main_phase()

    async def _handle_switch_user():
        """Callback for 'Spieler wechseln' in sidebar → back to user selection without reload."""
        drawer.set_value(False)
        footer.set_value(False)
        header.set_value(False)
        if INVITE_CODE and not s.get("authenticated"):
            _show_login_phase()
        else:
            _show_user_selection_phase()

    async def _show_main_phase():
        """Phase 3: Main app with drawer, footer, chat."""
        if not s.get("user_config_loaded"):
            load_user_settings(s["current_user"])
            s["user_config_loaded"] = True

        # Accessibility: update HTML lang + skeleton ARIA labels to match user's UI language
        _user_lang = L()
        try:
            await ui.run_javascript(f'document.documentElement.lang="{_user_lang}"', timeout=3.0)
        except TimeoutError:
            pass
        # Apply saved narrator font preference
        _narrator_font = s.get("narrator_font", "sans")
        ui.run_javascript(f"document.body.setAttribute('data-narrator-font', '{_narrator_font}')")
        # Re-set skeleton ARIA labels (were set at build time with default language)
        _hamburger_btn.props(f'aria-label="{t("aria.menu_open", _user_lang)}"')
        drawer.props(f'aria-label="{t("aria.sidebar", _user_lang)}"')
        footer.props(f'aria-label="{t("aria.input_area", _user_lang)}"')
        content_area.props(f'role="main" aria-label="{t("aria.main_content", _user_lang)}"')

        # --- Populate drawer ---
        drawer_content.clear()
        with drawer_content:
            with ui.row().classes("w-full items-center justify-between mb-2"):
                ui.label(s["current_user"]).classes("text-lg font-semibold")
                ui.button(icon="chevron_left", on_click=drawer.hide).props(f'flat round dense aria-label="{t("aria.menu_close", L())}"').classes("text-gray-500 hover:text-white").style("min-width: 44px; min-height: 44px")
            sidebar_status_container = ui.column().classes("w-full")
            game = s.get("game")
            if game:
                with sidebar_status_container:
                    render_sidebar_status(game)
            sidebar_actions_container = ui.column().classes("w-full")
            def _refresh_sidebar_actions():
                sidebar_actions_container.clear()
                with sidebar_actions_container:
                    render_sidebar_actions(on_switch_user=_handle_switch_user,
                                           on_refresh=_refresh_sidebar_actions,
                                           saves_open=True,
                                           on_chapter_view_change=_show_main_phase)
            with sidebar_actions_container:
                render_sidebar_actions(on_switch_user=_handle_switch_user,
                                       on_refresh=_refresh_sidebar_actions,
                                       on_chapter_view_change=_show_main_phase)
            # Version display at bottom of sidebar
            ui.label(f"v{VERSION}").classes("w-full text-center text-xs mt-4").style("color: var(--text-secondary); opacity: 0.5")
        drawer.set_value(False)
        header.set_value(True)

        # Sidebar refresh callback — rebuilds status + actions with fresh data
        # Capture session ref here; inside callback S() may lose client context
        # after long asyncio.to_thread calls.
        _sidebar_session = s
        def _refresh_sidebar(game_obj):
            """Rebuild sidebar status section after a turn."""
            try:
                sidebar_status_container.clear()
                with sidebar_status_container:
                    render_sidebar_status(game_obj, session=_sidebar_session)
            except Exception as e:
                log(f"[Sidebar] Refresh failed: {e}", level="warning")

        # --- Build main content ---
        content_area.clear()
        chat_container = None
        with content_area:
            if not s.get("api_key"):
                ui.label(t("user.api_missing", L())).classes("text-gray-400 text-center mt-8")
                footer.set_value(False)
                return

            chat_container = ui.column().classes("chat-scroll w-full")
            _sr_chat = s.get("sr_chat", True)
            _chat_aria_props = f'id="chat-log" aria-label="{t("aria.chat_log", L())}"'
            if _sr_chat:
                _chat_aria_props += ' role="log" aria-live="polite"'
            chat_container.props(_chat_aria_props)
            s["_chat_container"] = chat_container  # Store reference for sidebar actions (recap etc.)
            with chat_container:
                # Chapter viewing banner
                viewing_chapter = s.get("viewing_chapter")
                if viewing_chapter:
                    ch_title = s.get("chapter_view_title", "")
                    if ch_title:
                        banner_text = t("chapters.viewing_title", L(), n=viewing_chapter, title=ch_title)
                    else:
                        banner_text = t("chapters.viewing", L(), n=viewing_chapter)
                    with ui.card().classes("w-full mb-2").style(
                        "background: var(--accent-dim); border: 1px solid var(--accent-border); border-radius: 8px"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label(banner_text).classes("text-sm font-semibold")
                            async def _exit_view():
                                s["viewing_chapter"] = None; s["chapter_view_messages"] = None; s["chapter_view_title"] = None
                                await _show_main_phase()
                            ui.button(t("chapters.back", L()), icon="arrow_back", on_click=_exit_view).props("flat dense size=sm no-caps").classes("text-xs")

                last_scene_id = render_chat_messages(chat_container)

                # Skip game flow when viewing archived chapter
                if not viewing_chapter:
                    # Detect orphaned user input (page reload/disconnect before AI response)
                    if not s.get("processing"):
                        _msgs = s.get("messages", [])
                        _last_msg = None
                        for _m in reversed(_msgs):
                            if not _m.get("scene_marker"):
                                _last_msg = _m
                                break
                        if _last_msg and _last_msg.get("role") == "user":
                            _orphan_text = _last_msg.get("content", "")
                            if _last_msg.get("correction_input"):
                                _orphan_text = "## " + _orphan_text
                            _retry_cc = chat_container
                            _retry_sr = _refresh_sidebar
                            with chat_container:
                                retry_row = ui.row().classes("w-full items-center gap-2 py-1 px-3").style(
                                    "background: var(--accent-dim); border: 1px solid var(--accent-border); "
                                    "border-radius: 8px; margin: 0.25rem 0"
                                )
                                retry_row.props('role="alert"')
                                with retry_row:
                                    _orphan_msg = t('game.retry_orphan', L())
                                    ui.html(
                                        f'<span aria-hidden="true">{E["warn"]} </span>{_orphan_msg}'
                                    ).classes("text-xs flex-grow").style("color: var(--accent-light)")
                                    async def _do_orphan_retry(rr=retry_row, rt=_orphan_text,
                                                               rc=_retry_cc, rs=_retry_sr):
                                        try: rr.delete()
                                        except Exception: pass
                                        await process_player_input(rt, rc, sidebar_refresh=rs, is_retry=True)
                                    ui.button(icon="refresh", on_click=_do_orphan_retry).props(
                                        f'flat dense round aria-label="{t("aria.retry", L())}"'
                                    ).classes("hover:text-white").style(
                                        "min-width: 40px; min-height: 40px; color: var(--accent-light)"
                                    ).tooltip(t("game.retry_tooltip", L()))
                    if render_momentum_burn():
                        footer.set_value(False)
                        await _scroll_chat_bottom(delay_ms=300)
                        return
                    if render_game_over():
                        footer.set_value(False)
                        await _scroll_chat_bottom(delay_ms=300)
                        return
                    if render_epilogue():
                        footer.set_value(False)
                        await _scroll_chat_bottom(delay_ms=300)
                        return

                    game = s.get("game"); creation = s.get("creation")
                    if game is None or creation is not None:
                        if render_creation_flow(chat_container):
                            footer.set_value(False)
                            return

        # --- Populate footer (input bar or chapter view bar) ---
        viewing_chapter = s.get("viewing_chapter")
        game = s.get("game")
        if viewing_chapter and chat_container:
            # Chapter view footer: export + back to game
            footer_content.clear()
            with footer_content:
                with ui.row().classes("w-full items-center justify-center gap-3 rpg-input-bar").style("padding: 0.5rem 1rem"):
                    ch_title = s.get("chapter_view_title", "")
                    if ch_title:
                        ui.label(ch_title).classes("text-sm").style("color: var(--text-secondary); opacity: 0.7")
                    def _do_chapter_export():
                        ch_msgs = s.get("chapter_view_messages", [])
                        g = s.get("game")
                        if g and ch_msgs:
                            pdf_bytes = export_story_pdf(g, ch_msgs, lang=L())
                            ch_n = s.get("viewing_chapter", 0)
                            ui.download(pdf_bytes, f"{g.player_name}_Chapter_{ch_n}.pdf")
                    ui.button(t('chapters.export', L()), on_click=_do_chapter_export).props("flat dense no-caps").classes("text-sm")
                    async def _exit_view_footer():
                        s["viewing_chapter"] = None; s["chapter_view_messages"] = None; s["chapter_view_title"] = None
                        await _show_main_phase()
                    ui.button(f"{t('chapters.back', L())}", icon="arrow_back", on_click=_exit_view_footer).props("flat dense no-caps").classes("text-sm")
            footer.set_value(True)
            # Trigger footer alignment (same as normal footer)
            ui.run_javascript('setTimeout(() => { window._rpgAlignFooter && window._rpgAlignFooter(); }, 200)')
        elif game and not game.game_over and chat_container:
            footer_content.clear()
            with footer_content:
                # STT status line (hidden by default, shown during recording/transcription)
                stt_status = ui.row().classes("stt-status-row rpg-input-bar hidden w-full items-center")
                stt_status.props('role="status" aria-live="polite"')
                with stt_status:
                    stt_status_content = ui.html("").style("display: inline")
                with ui.row().classes("w-full items-center gap-2 rpg-input-bar").style("padding: 0.5rem 1rem"):
                    inp = ui.input(placeholder=t("game.input_placeholder", L())).classes("flex-grow").props(f'outlined dense dark aria-label="{t("game.input_placeholder", L())}"')
                    _cc = chat_container  # capture reference for closure
                    _sr = _refresh_sidebar  # capture sidebar refresh callback
                    async def send():
                        txt=inp.value
                        if txt and txt.strip():
                            inp.value=""
                            await process_player_input(txt.strip(), _cc, sidebar_refresh=_sr)
                    inp.on("keydown.enter", send)
                    # --- STT Microphone button ---
                    if s.get("stt_enabled", False):
                        mic_btn = ui.button(icon="mic", on_click=lambda: None).props(f'flat dense aria-label="{t("aria.start_recording", L())}"') \
                            .classes("text-gray-400 hover:text-white stt-mic-btn") \
                            .style("border: 1px solid var(--border-light); border-radius: 8px; min-width: 44px; height: 44px")
                        _setup_stt_button(mic_btn, inp, _cc, stt_status, stt_status_content, sidebar_refresh=_sr)
                    ui.button(icon="send", on_click=send).props(f'flat dense aria-label="{t("aria.send_message", L())}"').classes("text-gray-400 hover:text-white").style("border: 1px solid var(--border-light); border-radius: 8px; min-width: 44px; height: 44px")
            footer.set_value(True)
            # Dynamically align footer input bar with page content
            ui.run_javascript('''
                window._rpgAlignFooter = function() {
                    const pageCol = document.querySelector('.q-page .max-w-4xl');
                    const inputBars = document.querySelectorAll('.rpg-input-bar');
                    if (pageCol && inputBars.length) {
                        const rect = pageCol.getBoundingClientRect();
                        inputBars.forEach(bar => {
                            const parentRect = bar.parentElement.getBoundingClientRect();
                            bar.style.maxWidth = rect.width + 'px';
                            bar.style.marginLeft = (rect.left - parentRect.left) + 'px';
                        });
                    }
                };
                setTimeout(window._rpgAlignFooter, 200);
                if (!window._rpgFooterListeners) {
                    window._rpgFooterListeners = true;
                    window.addEventListener('resize', () => window._rpgAlignFooter && window._rpgAlignFooter());
                    /* Visual viewport resize: handles iOS virtual keyboard */
                    if (window.visualViewport) {
                        window.visualViewport.addEventListener('resize', () => {
                            window._rpgAlignFooter && window._rpgAlignFooter();
                        });
                        window.visualViewport.addEventListener('scroll', () => {
                            window._rpgAlignFooter && window._rpgAlignFooter();
                        });
                    }
                    new MutationObserver(() => setTimeout(() => window._rpgAlignFooter && window._rpgAlignFooter(), 350))
                        .observe(document.querySelector('.q-layout') || document.body,
                                 {attributes: true, attributeFilter: ['style']});
                }
            ''')
        else:
            footer.set_value(False)

        # Two-step scroll: bottom first (forces DOM render), then up to last scene marker
        await _scroll_chat_bottom(delay_ms=300)
        if last_scene_id:
            await _scroll_to_element(last_scene_id)

        # Process pending TTS (from game start / new chapter / momentum burn that triggered reload)
        pending = s.pop("pending_tts", None)
        if pending and chat_container:
            await do_tts(pending, chat_container)

        # Accessibility: move focus to the most relevant interactive element
        # Priority: footer input (game active) → creation buttons → creation input → card buttons
        ui.run_javascript('''
            setTimeout(() => {
                const targets = [
                    '.q-footer input',
                    '.q-page .choice-btn',
                    '.q-page .q-card .q-btn',
                    '.q-page input',
                    '.q-page textarea'
                ];
                for (const sel of targets) {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent !== null) { el.focus(); return; }
                }
            }, 600);
        ''')

    # ==================================================================
    # DETERMINE INITIAL PHASE
    # ==================================================================
    if INVITE_CODE and not s.get("authenticated"):
        _show_login_phase()
    elif not s.get("current_user"):
        _show_user_selection_phase()
    else:
        await _show_main_phase()


# ===============================================================
# STARTUP
# ===============================================================

# Clean up leftover temp audio files from previous sessions
def _startup_temp_cleanup():
    import glob
    tmp_dir = tempfile.gettempdir()
    for f in glob.glob(os.path.join(tmp_dir, "rpg_audio_*")):
        try:
            os.unlink(f)
        except OSError:
            pass

_startup_temp_cleanup()

# Generate apple-touch-icon (suppresses iOS Safari 404s, enables "Add to Home Screen")
def _generate_touch_icon():
    """Create a minimal 180x180 PNG apple-touch-icon with the accent color."""
    import struct, zlib
    size = 180
    r, g, b = 0xD9, 0x77, 0x06  # Orange accent (#D97706)
    raw = b''
    for _ in range(size):
        raw += b'\x00' + bytes([r, g, b]) * size
    def _chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    png = (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr)
           + _chunk(b'IDAT', zlib.compress(raw)) + _chunk(b'IEND', b''))
    icon_path = Path(tempfile.gettempdir()) / "rpg_touch_icon.png"
    icon_path.write_bytes(png)
    return icon_path

_touch_icon = _generate_touch_icon()
for _icon_url in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
                   "/apple-touch-icon-120x120.png", "/apple-touch-icon-120x120-precomposed.png"):
    app.add_static_file(url_path=_icon_url, local_file=str(_touch_icon))


# ---------------------------------------------------------------------------
# HTTPS / SSL setup
# ---------------------------------------------------------------------------

def _fetch_public_ip() -> str | None:
    """Fetch the current public IP via ipify.org. Returns None on any failure.

    Used to include the public IP in the certificate SAN so that external
    users accessing EdgeTales via its public IP get a valid TLS connection.
    Timeout is short (5s) to avoid delaying startup on offline systems.
    """
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as resp:
            ip = resp.read().decode().strip()
            # Basic sanity check — must look like an IPv4 address
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return ip
    except Exception:
        pass
    return None


def _cert_is_ios_compatible(cert_path: Path, key_path: Path,
                             required_san_ips: list | None = None) -> bool:
    """Return True if cert and key are a valid, iOS 13+-compatible pair.

    Checks performed:
    1. BasicConstraints(ca=True)      — required for iOS Certificate Trust Settings toggle.
    2. ExtendedKeyUsage(serverAuth)   — required for TLS server certs since iOS 13.
    3. Public key match               — cert and key file must share the same public key.
                                        Mismatch occurs if the process crashes between
                                        writing key.pem and cert.pem.
    4. Required SANs present          — if required_san_ips is provided, every IP in that
                                        list must appear in the cert's SAN extension.
                                        Triggers regeneration when the public IP changes.

    Any failure returns False, triggering a full regeneration.
    """
    try:
        from cryptography import x509
        from cryptography.x509.extensions import BasicConstraints, ExtendedKeyUsage
        from cryptography.x509.oid import ExtendedKeyUsageOID
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        import ipaddress

        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())

        # Check 1: CA BasicConstraints
        bc = cert.extensions.get_extension_for_class(BasicConstraints)
        if not bc.value.ca:
            return False

        # Check 2: ExtendedKeyUsage with serverAuth
        eku = cert.extensions.get_extension_for_class(ExtendedKeyUsage)
        if ExtendedKeyUsageOID.SERVER_AUTH not in eku.value:
            return False

        # Check 3: Public key fingerprint match
        _enc = serialization.Encoding.PEM
        _fmt = serialization.PublicFormat.SubjectPublicKeyInfo
        private_key = load_pem_private_key(key_path.read_bytes(), password=None)
        if cert.public_key().public_bytes(_enc, _fmt) != private_key.public_key().public_bytes(_enc, _fmt):
            return False

        # Check 4: Required SAN IPs present (e.g. public IP, ssl_extra_sans)
        if required_san_ips:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            cert_ips = {str(e.value) for e in san_ext.value
                        if isinstance(e, x509.IPAddress)}
            for ip in required_san_ips:
                try:
                    if str(ipaddress.ip_address(ip)) not in cert_ips:
                        return False
                except ValueError:
                    # Not an IP — check as DNS name
                    cert_dns = {e.value for e in san_ext.value
                                if isinstance(e, x509.DNSName)}
                    if ip not in cert_dns:
                        return False

        return True
    except Exception:
        return False


def _generate_self_signed_cert(extra_sans: list | None = None):
    """Generate a self-signed CA certificate for local HTTPS.

    The certificate satisfies all iOS 13+ requirements for both CA trust
    installation and TLS server use simultaneously:
    - BasicConstraints(ca=True)           — for Certificate Trust Settings toggle
    - ExtendedKeyUsage(serverAuth)        — required for all TLS server certs (iOS 13+)
    - KeyUsage(key_cert_sign, crl_sign)   — standard CA key usage
    - SubjectKeyIdentifier                — recommended for CA certs
    - SubjectAlternativeName              — required; CommonName alone not trusted (iOS 13+)

    extra_sans: list of additional IP strings or hostnames to include in SAN.
    Public IP is auto-detected via ipify.org and always included when reachable.
    """
    cert_dir = Path.home() / ".rpg_engine_ssl"
    cert_dir.mkdir(mode=0o700, exist_ok=True)
    # Ensure directory permissions are restricted even if it already existed
    try:
        cert_dir.chmod(0o700)
    except OSError:
        pass
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    # Determine which IPs/hostnames must be in the cert
    _extra = list(extra_sans) if extra_sans else []

    # Auto-detect public IP and add if not already in extra_sans
    _public_ip = _fetch_public_ip()
    if _public_ip and _public_ip not in _extra:
        _extra.append(_public_ip)
        log(f"[SSL] Public IP detected: {_public_ip}")
    elif not _public_ip:
        log("[SSL] Public IP detection failed — skipping (offline or timeout)")

    # Reuse existing cert only if < 365 days old AND it passes all iOS checks
    # including all required SAN entries.
    if cert_path.exists() and key_path.exists():
        import time
        age_days = (time.time() - cert_path.stat().st_mtime) / 86400
        if age_days >= 365:
            log("[SSL] Existing certificate has expired — regenerating")
        elif _cert_is_ios_compatible(cert_path, key_path, required_san_ips=_extra):
            log(f"[SSL] Reusing existing CA certificate from {cert_dir}")
            return str(cert_path), str(key_path)
        else:
            log("[SSL] Existing certificate is not reusable "
                "(missing extensions, key mismatch, or missing SANs) — regenerating")

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime, ipaddress, socket, stat
        log("[SSL] Generating self-signed CA certificate...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Build SAN list — deduplicate DNS names and IPs separately
        hostname = socket.gethostname()
        _san_seen_dns = {"localhost"}
        _san_seen_ips = {"127.0.0.1"}
        san_entries = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        # Pi hostname
        if hostname not in _san_seen_dns:
            _san_seen_dns.add(hostname)
            san_entries.insert(1, x509.DNSName(hostname))
        # Local network IPs from getaddrinfo
        try:
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip not in _san_seen_ips:
                    _san_seen_ips.add(ip)
                    san_entries.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass
        # Extra SANs (public IP + ssl_extra_sans from config)
        for entry in _extra:
            try:
                parsed_ip = ipaddress.ip_address(entry)
                ip_str = str(parsed_ip)
                if ip_str not in _san_seen_ips:
                    _san_seen_ips.add(ip_str)
                    san_entries.append(x509.IPAddress(parsed_ip))
            except ValueError:
                # Not an IP — treat as DNS name
                if entry not in _san_seen_dns:
                    _san_seen_dns.add(entry)
                    san_entries.append(x509.DNSName(entry))

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "EdgeTales Local CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EdgeTales"),
        ])
        pub_key = key.public_key()
        cert = (x509.CertificateBuilder()
                .subject_name(subject).issuer_name(issuer)
                .public_key(pub_key)
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
                .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
                # Required by iOS to show Certificate Trust Settings toggle
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                # Required by iOS 13+ for all TLS server certs (id-kp-serverAuth OID).
                # Non-standard to combine with ca=True, but necessary for self-signed
                # certs that serve as both CA root and TLS server certificate.
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                # Standard CA key usage
                .add_extension(x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ), critical=True)
                # Subject Key Identifier — recommended for CA certs
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub_key), critical=False)
                # Required by iOS 13+; CommonName alone is not trusted
                .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
                .sign(key, hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        # Restrict private key permissions (Unix only)
        try:
            key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        log(f"[SSL] CA certificate generated: {cert_path}")
        log(f"[SSL] SAN entries: {[str(s) for s in san_entries]}")
        return str(cert_path), str(key_path)
    except ImportError:
        log("[SSL] 'cryptography' package not installed. Run: pip install cryptography", level="warning")
        return None, None
    except Exception as e:
        log(f"[SSL] Certificate generation failed: {e}", level="warning")
        return None, None


def _get_storage_secret() -> str:
    """Get storage secret: from ENV / config.json, or generate and persist one."""
    # 1. Already resolved via config cascade (ENV or config.json)
    if _server_cfg.get("storage_secret"):
        return _server_cfg["storage_secret"]
    # 2. Persistent file (auto-generated once)
    secret_file = Path(__file__).resolve().parent / ".storage_secret"
    if secret_file.exists():
        try:
            return secret_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    # 3. Generate new secret
    import secrets
    new_secret = secrets.token_urlsafe(32)
    try:
        secret_file.write_text(new_secret, encoding="utf-8")
        # Restrict permissions (Unix only)
        try:
            import stat
            secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        log(f"[Security] Generated new storage secret → {secret_file}")
    except OSError:
        log("[Security] Could not persist storage secret — using ephemeral", level="warning")
    return new_secret


_ssl_kwargs = {}
_AUTO_CERT_PATH: str | None = None  # Set when auto-generated cert is used; drives /download-cert

if SSL_CERTFILE and SSL_KEYFILE:
    _ssl_kwargs = {"ssl_certfile": SSL_CERTFILE, "ssl_keyfile": SSL_KEYFILE}
    log(f"[SSL] Using custom certificate: {SSL_CERTFILE}")
elif ENABLE_HTTPS:
    _cert, _key = _generate_self_signed_cert(extra_sans=SSL_EXTRA_SANS)
    if _cert and _key:
        _ssl_kwargs = {"ssl_certfile": _cert, "ssl_keyfile": _key}
        _AUTO_CERT_PATH = _cert

if _ssl_kwargs:
    _proto = "https"
    log(f"[SSL] HTTPS enabled on port {SERVER_PORT}")
else:
    _proto = "http"

# ---------------------------------------------------------------------------
# /download-cert  — serves the auto-generated CA certificate for iOS trust
#
# Usage: open https://<pi-ip>:<port>/download-cert in Safari on iOS.
# Safari downloads the cert, iOS prompts to install it as a Profile.
# After installation: Settings → General → About → Certificate Trust Settings
# → enable the toggle for "EdgeTales Local CA".
# Only active when EdgeTales generated its own certificate (enable_https: true
# without ssl_certfile/ssl_keyfile overrides). Custom certs are not served.
# ---------------------------------------------------------------------------
if _AUTO_CERT_PATH:
    from fastapi.responses import Response as _FastAPIResponse

    @app.get("/download-cert")
    async def _download_cert():
        try:
            cert_bytes = Path(_AUTO_CERT_PATH).read_bytes()
            # No Content-Disposition header: iOS Safari must handle this purely
            # via the MIME type to trigger the profile installation flow.
            # Using 'attachment' would cause Safari to treat it as a generic
            # download instead of opening the certificate installer.
            return _FastAPIResponse(
                content=cert_bytes,
                media_type="application/x-x509-ca-cert",
            )
        except OSError:
            return _FastAPIResponse(content=b"Certificate not found", status_code=404)

    log("[SSL] Certificate download available at /download-cert")

ui.run(
    title="EdgeTales",
    port=SERVER_PORT,
    dark=True,
    storage_secret=_get_storage_secret(),
    favicon="⚔️",
    reload=False,
    show=False,
    reconnect_timeout=RECONNECT_TIMEOUT_SEC,
    **_ssl_kwargs,
)
