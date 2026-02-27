#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Tales - Narrative Solo RPG Engine — NiceGUI Frontend
"""

import asyncio
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
    E, log,
    GameState, RollResult, EngineConfig,
    LANGUAGES, CHATTERBOX_DEVICE_OPTIONS,
    VOICE_DIR,
    load_global_config, save_global_config,
    load_user_config, save_user_config,
    list_users, create_user, delete_user,
    save_game, load_game, list_saves, list_saves_with_info, delete_save, export_story_pdf,
    get_current_act, setup_file_logging,
    call_setup_brain, start_new_game, start_new_chapter,
    process_turn, process_momentum_burn, call_recap,
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
    # 3. ENV overrides config.json (for Docker, systemd, .bat, etc.)
    env_map = {
        "ANTHROPIC_API_KEY": "api_key",
        "INVITE_CODE": "invite_code",
        "ENABLE_HTTPS": "enable_https",
        "SSL_CERTFILE": "ssl_certfile",
        "SSL_KEYFILE": "ssl_keyfile",
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
            else:
                cfg[cfg_key] = env_val
    return cfg

_server_cfg = _load_server_config()
INVITE_CODE: str = _server_cfg["invite_code"]
SERVER_API_KEY: str = _server_cfg["api_key"]
ENABLE_HTTPS: bool = _server_cfg["enable_https"]
SSL_CERTFILE: str = _server_cfg["ssl_certfile"]
SSL_KEYFILE: str = _server_cfg["ssl_keyfile"]
SERVER_PORT: int = _server_cfg["port"]
# Validate default_ui_lang: must be a known code ('de', 'en', ...) or empty (→ DEFAULT_LANG)
_raw_ui_lang = _server_cfg.get("default_ui_lang", "").strip().lower()
DEFAULT_UI_LANG: str = _raw_ui_lang if _raw_ui_lang in UI_LANGUAGES.values() else ""

# Log config state (without secrets)
log(f"[Config] port={SERVER_PORT}, https={ENABLE_HTTPS}, "
    f"invite={'set' if INVITE_CODE else 'off'}, "
    f"default_ui_lang={DEFAULT_UI_LANG or DEFAULT_LANG}, "
    f"api_key={'ENV' if os.environ.get('ANTHROPIC_API_KEY') else ('config.json' if SERVER_API_KEY else 'not set')}")

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
    # Unclosed ```game_data or ```json code blocks
    text = re.sub(r'```\s*(?:game_data|json)\s*(?:\{[\s\S]*)?$', '', text)
    # Trailing bare ```word with no closing
    text = re.sub(r'```\w*\s*$', '', text)
    # Bold-bracket metadata blocks: **[char: state | location | threat | ...]**
    text = re.sub(r'\*{0,2}\[(?:[^\]]*\|){2,}[^\]]*\]\*{0,2}\s*$', '', text)
    return text.strip()


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
    saved_backend = cfg.get("tts_backend", "")
    backend_code = resolve_tts_backend(saved_backend) if saved_backend else "edge_tts"
    s["tts_backend"] = find_tts_backend_label(backend_code, lang)
    s["cb_device"] = cfg.get("cb_device", "Auto")
    s["cb_exaggeration"] = cfg.get("cb_exaggeration", 0.5)
    s["cb_cfg_weight"] = cfg.get("cb_cfg_weight", 0.5)
    # Voice sample: "" or missing → no-sample label; filename → keep as-is
    saved_sample = cfg.get("cb_voice_sample", "")
    s["cb_voice_sample"] = get_no_voice_sample_label(lang) if not saved_sample else saved_sample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_roll_data(roll: RollResult, consequences=None, clock_events=None, brain=None) -> dict:
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
        "result": roll.result, "result_label": result_label,
        "match": getattr(roll, "match", roll.c1 == roll.c2),
        "consequences": consequences or [], "clock_events": clock_events or [],
        "position": brain.get("position", "risky") if brain else "risky",
        "effect": brain.get("effect", "standard") if brain else "standard",
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


def render_audio_player(audio_bytes: bytes, fmt: str = "audio/mp3", autoplay: bool = False) -> None:
    """Render an HTML5 audio player by serving audio as a temp file.
    Schedules delayed deletion of the temp file after serving."""
    _run_temp_cleanup()  # Clean up old temp files first
    ext = ".mp3" if "mp3" in fmt else ".wav" if "wav" in fmt else ".ogg"
    tmp = Path(tempfile.gettempdir()) / f"rpg_audio_{uuid.uuid4().hex[:8]}{ext}"
    tmp.write_bytes(audio_bytes)
    url = app.add_media_file(local_file=tmp)
    log(f"[Audio] Serving {len(audio_bytes)} bytes as {url}")
    a = ui.audio(url, autoplay=autoplay).classes("w-full").style("margin: 0.4em 0;")
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
    """Run TTS in background thread if enabled. Renders audio player inline (ephemeral)."""
    s = S()
    if not s.get("tts_enabled", False):
        return
    # Show loading indicator
    tts_indicator = None
    if chat_container:
        with chat_container:
            tts_indicator = ui.row().classes("w-full items-center gap-2")
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
                    render_audio_player(audio, fmt, autoplay=autoplay)
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
            mic_btn.props("color=red")
            mic_btn._props["icon"] = "stop"
            mic_btn.update()
            _show_status(f'{_WAVEFORM_HTML} <span style="color: #ef4444">{t("stt.recording", L())} <span id="_sttTimer">0:00</span></span>')
            await ui.run_javascript(f'''
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
            ''')
        else:
            # Stop recording — reset UI immediately (don't wait for audio processing)
            recording_state["active"] = False
            mic_btn.props(remove="color")
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
        _show_status(f'<span class="stt-spinner-inline"></span> {t("stt.transcribing", L())}')
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
            _show_status(f'{E["x_mark"]} <span style="color: #f87171">{t("stt.error", L(), error=ex)}</span>')
            asyncio.create_task(_hide_status_delayed(4000))

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
        mic_btn._props["icon"] = "mic"
        mic_btn.update()
        err = e.args.get("error", t("stt.unknown", L())) if isinstance(e.args, dict) else t("stt.unknown", L())
        _show_status(f'{E["x_mark"]} <span style="color: #f87171">{t("stt.mic_error", L(), error=err)}</span>')
        asyncio.create_task(_hide_status_delayed(4000))

    async def handle_stopped(_e):
        """Reset UI when recording stops (covers auto-stop from max duration)."""
        if recording_state["active"]:
            recording_state["active"] = False
            mic_btn.props(remove="color")
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

def render_sidebar_status(game: GameState, session=None) -> None:
    s = session or S()
    lang = s.get("ui_lang", DEFAULT_UI_LANG or DEFAULT_LANG) if session else L()
    kid = s.get("kid_friendly", False)
    sl = get_stat_labels(lang)
    ui.label(f"{E['mask']} {game.player_name}").classes("text-lg font-bold")
    ui.label(game.character_concept).classes("text-sm text-gray-400 italic")
    if kid: ui.label(f"{E['green_heart']} {t('sidebar.kid_mode', lang)}").classes("text-xs text-green-400")
    tl = get_time_labels(lang)
    t_label = tl.get(game.time_of_day, "") if game.time_of_day else ""
    t_disp = f" {E['dash']} {t_label}" if t_label else ""
    ui.label(f"{E['pin']} {game.current_location} {E['dash']} {t('sidebar.scene', lang)} {game.scene_count}{t_disp}").classes("text-xs text-gray-400")
    if game.crisis_mode and not game.game_over:
        ui.label(f"{E['warn']} {t('sidebar.crisis_kid', lang) if kid else t('sidebar.crisis', lang)}").classes("text-sm text-red-400 font-bold mt-2")
    if game.game_over:
        ui.label(f"{E['skull']} {t('sidebar.finale', lang)}").classes("text-sm text-red-400 font-bold mt-2")
    ui.separator()
    # Stats
    ui.html(f'''<div class="stat-grid">
    <div class="stat-item"><div class="stat-label">{sl['edge']}</div><div class="stat-value">{game.get_stat('edge')}</div></div>
    <div class="stat-item"><div class="stat-label">{sl['shadow']}</div><div class="stat-value">{game.get_stat('shadow')}</div></div>
    <div class="stat-item"><div class="stat-label">{sl['heart']}</div><div class="stat-value">{game.get_stat('heart')}</div></div>
    <div class="stat-item"><div class="stat-label">{sl['wits']}</div><div class="stat-value">{game.get_stat('wits')}</div></div>
    <div class="stat-item"><div class="stat-label">{sl['iron']}</div><div class="stat-value">{game.get_stat('iron')}</div></div>
    <div class="stat-item"><div class="stat-label">{t('sidebar.momentum', lang)}</div><div class="stat-value">{game.momentum}/{game.max_momentum}</div></div>
    </div>''').classes("w-full")
    ui.separator()
    # Tracks
    for track, label, cls in [("health",f"{E['heart_red']} {t('sidebar.health', lang)}","health"),("spirit",f"{E['heart_blue']} {t('sidebar.spirit', lang)}","spirit"),("supply",f"{E['yellow_dot']} {t('sidebar.supply', lang)}","supply")]:
        val = getattr(game, track)
        pct = max(0, val / 5 * 100)
        ui.label(f"{label}: {val}/5").classes("text-sm font-semibold")
        ui.html(f'<div class="track-bar"><div class="track-fill {cls}" style="width:{pct}%"></div></div>').classes("w-full")
    # Chaos
    ui.separator()
    chaos = game.chaos_factor
    ci = {3:E['green_circle'],4:E['green_circle'],5:E['orange_circle'],6:E['orange_circle'],7:E['red_circle'],8:E['red_circle'],9:E['skull']}.get(chaos, E['white_circle'])
    pct = max(0, chaos / 9 * 100)
    ui.label(f"{E['tornado']} {t('sidebar.chaos', lang)}: {ci} {chaos}/9").classes("text-sm font-semibold")
    ui.html(f'<div class="track-bar"><div class="track-fill chaos" style="width:{pct}%"></div></div>').classes("w-full")
    # Clocks
    active = [c for c in game.clocks if c["filled"] < c["segments"]]
    if active:
        ui.separator()
        ui.label(f"{E['clock']} {t('sidebar.clocks', lang)}").classes("text-sm font-semibold")
        for c in active:
            em = E['red_circle'] if c["clock_type"]=="threat" else E['purple_circle']
            p = c["filled"]/c["segments"]*100
            ui.label(f"{em} {c['name']}: {c['filled']}/{c['segments']}").classes("text-xs")
            ui.html(f'<div class="track-bar"><div class="track-fill progress" style="width:{p}%"></div></div>').classes("w-full")
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
                ui.label(f"{E['play']} {act_l} {an} {E['dash']} {phase}").classes("text-xs font-bold")
                ui.html(f'<div class="track-bar"><div class="track-fill progress" style="width:{p}%"></div></div>').classes("w-full")
            else: ui.label(f"{act_l} {an}").classes("text-xs text-gray-500")
        if bp.get("story_complete"):
            ui.label(f"{E['star']} {t('sidebar.story_complete', lang)}").classes("text-xs text-amber-400 font-bold mt-1")
    # NPCs
    active_npcs = [n for n in game.npcs if n.get("status")=="active" and n.get("introduced",True)]
    background_npcs = [n for n in game.npcs if n.get("status")=="background" and n.get("introduced",True)]
    if active_npcs or background_npcs:
        # Sort by bond (desc), then by most recent memory scene (desc)
        def _npc_sort_key(n):
            last_scene = max((m.get("scene") or 0 for m in n.get("memory", []) if isinstance(m, dict)), default=0)
            return (-n.get("bond", 0), -(last_scene or 0))
        ui.separator()
        dl = get_disposition_labels(lang)
        if active_npcs:
            active_npcs.sort(key=_npc_sort_key)
            ui.label(f"{E['people']} {t('sidebar.persons', lang)}").classes("text-sm font-semibold")
            for n in active_npcs:
                disp = dl.get(n["disposition"],f"{E['white_circle']} Neutral")
                with ui.expansion(f"{disp} {n['name']} {E['dash']} {n['bond']}/{n.get('bond_max',4)}"):
                    if n.get("aliases"):
                        ui.label(f"{t('sidebar.npc_aka', lang)} {', '.join(n['aliases'])}").classes("text-xs text-gray-500 italic")
                    if n.get("description"): ui.label(n["description"]).classes("text-xs text-gray-400")
        if background_npcs:
            background_npcs.sort(key=_npc_sort_key)
            with ui.expansion(f"{E['people']} {t('sidebar.known_persons', lang)} ({len(background_npcs)})").classes("w-full"):
                for n in background_npcs:
                    disp = dl.get(n["disposition"],f"{E['white_circle']} Neutral")
                    ui.label(f"{disp} {n['name']} {E['dash']} {n['bond']}/{n.get('bond_max',4)}").classes("text-xs").style("opacity: 0.6")


def render_sidebar_actions(on_switch_user=None) -> None:
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
                        with recap_el:
                            ui.markdown(f"{prefix}{_clean_narration(recap)}")
                    s["_recap_element"] = recap_el
                    await _scroll_chat_bottom()
                    await do_tts(recap, recap_el)
                else:
                    # Fallback: no chat container available, reload
                    ui.navigate.reload()
            except Exception as e: ui.notify(t("creation.error", lang, error=e), type="negative")
            finally:
                s["processing"] = False
                if recap_status:
                    recap_status.set_visibility(False)
    if game:
        ui.button(f"{E['scroll']} {t('actions.recap', lang)}", on_click=do_recap).props("flat dense").classes("w-full")
        recap_status = ui.label("").classes("text-xs text-center w-full").style("color: var(--text-secondary)")
        recap_status.set_visibility(False)
    # Save/Load
    with ui.expansion(f"{E['floppy']} {t('actions.saves', lang)}").classes("w-full"):
        active = s.get("active_save", "autosave")
        active_display = t("actions.autosave", lang) if active == "autosave" else active

        # --- Active slot indicator ---
        if game:
            ui.label(f"{E['floppy']} {t('actions.active_save', lang, name=active_display)}").classes(
                "text-xs font-semibold w-full").style("color: #4ade80")

            # --- Quick save (into active slot) ---
            save_confirm = ui.label(f"{E['checkmark']} {t('actions.saved', lang)}").classes(
                "text-sm text-center w-full").style("color: #4ade80")
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
                    save_game(game, username, s["messages"], new_name)
                    s["active_save"] = new_name
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
                border_color = "#4ade80" if is_active else "var(--accent)"
                bg_color = "rgba(74,222,128,0.08)" if is_active else "var(--accent-dim)"
                with ui.card().classes("w-full p-2 mb-1").style(
                    f"background: {bg_color}; border: 1px solid {border_color}; border-radius: 8px"):
                    with ui.column().classes("w-full gap-1"):
                        # Title + meta
                        title_parts = [f"**{display_name}**"]
                        if is_active:
                            title_parts.append(f" {E['check']}")
                        ui.markdown("".join(title_parts)).classes("text-sm")
                        meta = f"{pname} {E['dot']} {t('actions.save_scene', lang, n=scene)}"
                        if chapter > 1:
                            meta += f" {E['dot']} {t('actions.save_chapter', lang, n=chapter)}"
                        if date_str:
                            meta += f" {E['dot']} {date_str}"
                        ui.label(meta).classes("text-xs").style("color: var(--text-secondary)")
                        # Action buttons — own row, load left, delete right
                        with ui.row().classes("w-full items-center justify-between mt-1").style("padding: 0 0.25rem"):
                            def make_load(n=sname):
                                async def do_load():
                                    loaded, hist = load_game(username, n)
                                    if loaded:
                                        s["game"]=loaded; s["creation"]=None; s["pending_burn"]=None; s["messages"]=hist
                                        s["active_save"] = n
                                        s["processing"] = False  # Cancel any in-flight turn
                                        s["_turn_gen"] = s.get("_turn_gen", 0) + 1
                                        s["messages"].append({"role":"assistant","content":f"*{E['checkmark']} {t('actions.game_loaded', lang, name=loaded.player_name, scene=loaded.scene_count)}*"})
                                        ui.navigate.reload()
                                return do_load
                            ui.button(icon="play_arrow", on_click=make_load(sname)).props("flat round dense size=sm").tooltip(t("actions.load", lang))

                            if sname != "autosave":
                                def make_delete(n=sname):
                                    async def do_delete():
                                        display = t("actions.autosave", lang) if n == "autosave" else n
                                        with ui.dialog() as dlg, ui.card():
                                            ui.label(t("actions.delete_confirm", lang, name=display))
                                            with ui.row().classes("gap-4 mt-2"):
                                                async def confirm_del():
                                                    delete_save(username, n)
                                                    if s.get("active_save") == n:
                                                        s["active_save"] = "autosave"
                                                    dlg.close()
                                                    ui.navigate.reload()
                                                ui.button(t("user.yes", lang), on_click=confirm_del, color="negative")
                                                ui.button(t("user.no", lang), on_click=dlg.close)
                                        dlg.open()
                                    return do_delete
                                ui.button(icon="delete_outline", on_click=make_delete(sname)).props("flat round dense size=sm").tooltip(t("actions.delete", lang)).style("color: #ef4444")
        else:
            ui.label(t("actions.no_saves", lang)).classes("text-xs text-center w-full").style("color: var(--text-secondary)")

        # --- New game ---
        ui.separator().classes("my-1")
        async def new_game():
            s["game"]=None;s["creation"]=None;s["pending_burn"]=None;s["messages"]=[];s["active_save"]="autosave"
            s["processing"]=False;s["_turn_gen"]=s.get("_turn_gen",0)+1
            ui.navigate.reload()
        ui.button(f"{E['trash']} {t('actions.new_game', lang)}", on_click=new_game, color="red").props("flat").classes("w-full")

        # --- Export ---
        if game and s["messages"]:
            def do_export():
                pdf_bytes = export_story_pdf(game, s["messages"], lang=lang)
                ui.download(pdf_bytes, f"{game.player_name}_Story.pdf")
            ui.button(f"{E['book']} {t('actions.export', lang)}", on_click=do_export).props("flat dense").classes("w-full")
    # Settings
    render_settings()
    # Help
    render_help()
    # Switch user
    ui.separator()
    async def switch():
        s["current_user"]="";s["game"]=None;s["creation"]=None;s["messages"]=[];s["user_config_loaded"]=False;s["active_save"]="autosave"
        s["processing"]=False;s["_turn_gen"]=s.get("_turn_gen",0)+1
        if on_switch_user:
            await on_switch_user()
        else:
            ui.navigate.reload()
    ui.button(f"{E['refresh']} {t('actions.switch_user', lang)}", on_click=switch).props("flat dense").classes("w-full")


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
            with ui.icon("info_outline").classes("text-gray-400 cursor-help"):
                ui.tooltip(_tip)
        ui.separator()
        with ui.row().classes("w-full items-center justify-between"):
            tts_sw = ui.switch(t("settings.tts", lang), value=s.get("tts_enabled",False))
            _tip = t("settings.tts_tooltip", lang)
            with ui.icon("info_outline").classes("text-gray-400 cursor-help"):
                ui.tooltip(_tip)
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
            with ui.icon("info_outline").classes("text-gray-400 cursor-help"):
                ui.tooltip(_tip)
        wm = get_whisper_models(lang)
        whisper_display = [f"{k} {E['dash']} {v}" for k, v in wm.items()]
        whisper_map = {f"{k} {E['dash']} {v}": k for k, v in wm.items()}
        cur_whisper = s.get("whisper_size", "medium")
        cur_whisper_display = f"{cur_whisper} {E['dash']} {wm.get(cur_whisper, '?')}"
        whisper_sel = ui.select(whisper_display, label=t("settings.whisper_model", lang), value=cur_whisper_display).classes("w-full")
        whisper_sel.bind_visibility_from(stt_sw, "value")
        ui.separator()
        dice_opts = get_dice_display_options(lang)
        dice_options_map = {label: i for i, label in enumerate(dice_opts)}
        cur_dice_idx = s.get("dice_display", 0)
        if isinstance(cur_dice_idx, str):
            cur_dice_idx = _dice_string_to_index(cur_dice_idx)
        cur_dice_label = dice_opts[cur_dice_idx] if cur_dice_idx < len(dice_opts) else dice_opts[0]
        dice_sel = ui.select(dice_opts, label=t("settings.dice", lang), value=cur_dice_label).classes("w-full")
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
                         "whisper_size":whisper_map.get(whisper_sel.value, "medium")})
            save_user_config(username, ucfg)
            # UI language change requires full reload to re-render all labels
            if new_ui_lang != old_ui_lang:
                s["user_config_loaded"] = False  # Force load_user_settings on reload to migrate labels to new language
                ui.navigate.reload()
                return
            save_confirm.set_visibility(True)
            async def _hide():
                await asyncio.sleep(2)
                save_confirm.set_visibility(False)
            asyncio.create_task(_hide())
        ui.button(f"{E['floppy']} {t('settings.save_btn', lang)}", on_click=save_cfg, color="primary").classes("w-full")
        save_confirm = ui.label(f"{E['checkmark']} {t('settings.saved_confirm', lang)}").classes("text-sm text-center w-full").style("color: #4ade80")
        save_confirm.set_visibility(False)


def render_help() -> None:
    lang = L()
    with ui.expansion(f"{E['question']} {t('help.title', lang)}").classes("w-full"):
        ui.markdown(t("help.dice_title", lang))
        ui.markdown(t("help.dice_text", lang))
        ui.separator()

        ui.markdown(t("help.probe_title", lang))
        ui.markdown(t("help.probe_text", lang))
        ui.html(f'''<div style="font-size:0.85em; line-height:1.8; padding:0.3em 0;">
            {t("help.probe_detail", lang)}
        </div>''')
        ui.separator()

        ui.markdown(t("help.results_title", lang))
        ui.html(f'''<div style="font-size:0.85em; line-height:2;">
            {E['check']} {t("help.result_strong", lang)}<br>
            <span style="color:#a3a3a3">{t("help.result_strong_desc", lang)}</span><br><br>
            {E['warn']} {t("help.result_weak", lang)}<br>
            <span style="color:#a3a3a3">{t("help.result_weak_desc", lang)}</span><br><br>
            {E['x_mark']} {t("help.result_miss", lang)}<br>
            <span style="color:#a3a3a3">{t("help.result_miss_desc", lang)}</span>
        </div>''')
        ui.separator()

        ui.markdown(f"{t('help.match_title', lang)} {E['comet']}")
        ui.label(t("help.match_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(t("help.position_title", lang))
        ui.html(f'''<div style="font-size:0.85em; line-height:2;">
            {E['green_circle']} {t("help.pos_controlled", lang)}<br>
            <span style="color:#a3a3a3">{t("help.pos_controlled_desc", lang)}</span><br><br>
            {E['orange_circle']} {t("help.pos_risky", lang)}<br>
            <span style="color:#a3a3a3">{t("help.pos_risky_desc", lang)}</span><br><br>
            {E['red_circle']} {t("help.pos_desperate", lang)}<br>
            <span style="color:#a3a3a3">{t("help.pos_desperate_desc", lang)}</span>
        </div>''')
        ui.separator()

        ui.markdown(t("help.stats_title", lang))
        ui.html(f'''<div style="font-size:0.85em; line-height:2;">
            {E['lightning']} {t("help.stat_edge", lang)}<br>
            {E['heart_red']} {t("help.stat_heart", lang)}<br>
            {E['shield']} {t("help.stat_iron", lang)}<br>
            {E['dark_moon']} {t("help.stat_shadow", lang)}<br>
            {E['brain']} {t("help.stat_wits", lang)}
        </div>''')
        ui.separator()

        ui.markdown(t("help.tracks_title", lang))
        ui.html(f'''<div style="font-size:0.85em; line-height:2;">
            {E['heart_red']} {t("help.track_health", lang)}<br>
            {E['heart_blue']} {t("help.track_spirit", lang)}<br>
            {E['yellow_dot']} {t("help.track_supply", lang)}
        </div>''')
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

        ui.markdown(t("help.freedom_title", lang))
        ui.label(t("help.freedom_text", lang)).classes("text-xs text-gray-400")
        ui.separator()

        ui.markdown(f"{t('help.kid_title', lang)} {E['green_heart']}")
        ui.label(t("help.kid_text", lang)).classes("text-xs text-gray-400")


# ===============================================================
# CHAT RENDERING
# ===============================================================

def render_chat_messages(container) -> Optional[str]:
    """Render chat history. Returns the ID of the last scene marker (for scroll targeting)."""
    s = S()
    last_scene_marker_id = None
    for i, msg in enumerate(s.get("messages", [])):
        if msg.get("scene_marker"):
            marker_id = f"msg-{i}"
            last_scene_marker_id = marker_id
            ui.html(f'<div id="{marker_id}" class="scene-marker">{E["dash"]} {msg["scene_marker"]} {E["dash"]}</div>').classes("w-full")
            continue
        role = msg.get("role","assistant")
        content = msg.get("content","")
        css = "recap" if msg.get("recap") else role
        prefix = f"{E['scroll']} **{t('actions.recap_prefix', L())}**\n\n" if msg.get("recap") else ""
        with ui.column().classes(f"chat-msg {css} w-full"):
            ui.markdown(f"{prefix}{_clean_narration(content)}")
            rd = msg.get("roll_data")
            if rd: render_dice_display(rd)
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
        ui.html(f'<div class="dice-simple {severity}">{result_label} {E["dot"]} {stat_label}{ph}{match_txt}</div>').classes("w-full")
    elif setting == 2:  # Detailed
        header = f"{E['dice']} {result_label} \u2014 {move_label} ({stat_label})"
        if is_match:
            header += f" {E['comet']}"
        with ui.expansion(header).classes("w-full"):
            ui.markdown(t("dice.action", lang, d1=rd['d1'], d2=rd['d2'], stat_value=rd['stat_value'], score=rd['action_score'], c1=rd['c1'], c2=rd['c2']))
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
        with ui.element("div").classes("choice-grid w-full"):
            for label,code in genres.items():
                ui.button(label, on_click=lambda l=label,c=code: _pick_genre(l,c)).props("flat unelevated").classes("w-full choice-btn")
            ui.button(f"{E['pen']} {t('creation.custom_idea', lang)}", on_click=_pick_genre_custom).props("flat unelevated").classes("w-full choice-btn")
        return True
    if creation is None: return False
    step = creation.get("step","")
    if step == "genre_custom":
        ui.markdown(t("creation.custom_genre_title", lang))
        inp = ui.input(placeholder=t("creation.genre_placeholder", lang)).classes("w-full")
        async def go():
            if inp.value.strip(): _finish_genre_custom(inp.value.strip())
        inp.on("keydown.enter", go); ui.button(t("creation.next", lang), on_click=go, color="primary")
        return True
    if step == "tone":
        ui.markdown(t("creation.tone_question", lang, genre=creation['genre_label']))
        tones = get_tones(lang)
        with ui.element("div").classes("choice-grid w-full"):
            for label,code in tones.items():
                ui.button(label, on_click=lambda l=label,c=code: _pick_tone(l,c)).props("flat unelevated").classes("w-full choice-btn")
            ui.button(f"{E['pen']} {t('creation.custom_tone_btn', lang)}", on_click=_pick_tone_custom).props("flat unelevated").classes("w-full choice-btn")
        return True
    if step == "tone_custom":
        ui.markdown(t("creation.custom_tone_title", lang))
        inp = ui.input(placeholder=t("creation.tone_placeholder", lang)).classes("w-full")
        async def go():
            if inp.value.strip(): _finish_tone_custom(inp.value.strip())
        inp.on("keydown.enter", go); ui.button(t("creation.next", lang), on_click=go, color="primary")
        return True
    if step == "archetype":
        ui.markdown(t("creation.archetype_question", lang, tone=creation['tone_label']))
        archetypes = get_archetypes(lang)
        with ui.element("div").classes("choice-grid w-full"):
            for label,code in archetypes.items():
                ui.button(label, on_click=lambda l=label,c=code: _pick_archetype(l,c)).props("flat unelevated").classes("w-full choice-btn")
            ui.button(f"{E['pen']} {t('creation.custom_idea', lang)}", on_click=_pick_archetype_custom).props("flat unelevated").classes("w-full choice-btn")
        return True
    if step == "personalize":
        ui.markdown(t("creation.name_question", lang))
        name_inp = ui.input(placeholder=t("creation.name_placeholder", lang)).classes("w-full")
        ui.markdown(t("creation.desc_question", lang))
        desc_inp = ui.textarea(placeholder=t("creation.desc_placeholder", lang)).props("rows=2").classes("w-full")
        async def go():
            if name_inp.value.strip(): _finish_personalize(name_inp.value.strip(), desc_inp.value.strip() if desc_inp.value else "")
        name_inp.on("keydown.enter", go); ui.button(t("creation.next", lang), on_click=go, color="primary")
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
    s=S();c=s["creation"];c["tone"]="custom";c["tone_label"]=f"{E['pen']} {txt[:40]}";c["tone_description"]=txt;c["step"]="archetype"
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
    w_inp = ui.textarea(placeholder=t("creation.wishes_placeholder", lang), value=creation.get("wishes","")).classes("w-full")
    ui.label(f"{E['star']} {t('creation.wishes_hint', lang)}").classes("text-xs text-gray-500")
    ui.markdown(f"{E['shield']} {t('creation.boundaries_label', lang)}")
    l_inp = ui.textarea(placeholder=t("creation.boundaries_placeholder", lang), value=creation.get("content_lines","")).classes("w-full")
    ui.label(f"{E['shield']} {t('creation.boundaries_hint', lang)}").classes("text-xs text-gray-500")
    btn_container = ui.column().classes("w-full mt-4 gap-2")
    async def proceed():
        creation["wishes"]=w_inp.value.strip() if w_inp.value else ""
        creation["content_lines"]=l_inp.value.strip() if l_inp.value else ""
        # Show spinner below button
        with btn_container:
            with ui.row().classes("w-full items-center gap-3"):
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
        ui.button(f"{t('creation.next', lang)} {E['arrow_r']}", on_click=proceed, color="primary").classes("w-full")
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
    ui.markdown(f"### {E['mask']} {name}")
    ui.markdown(f"*{concept}*")
    if setting_desc:
        ui.markdown(f"{setting_desc}")
    if location:
        ui.markdown(f"{E['pin']} {location}")
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
        edit_desc = ui.textarea(t("creation.background", lang), value=creation.get("custom_desc","")).props("rows=3").classes("w-full")
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
        edit_wishes = ui.textarea(f"{E['star']} {t('creation.wishes_title', lang)}", value=creation.get("wishes",""), placeholder=t("creation.wishes_placeholder", lang)).props("rows=2").classes("w-full")
        edit_lines = ui.textarea(f"{E['shield']} {t('creation.boundaries_title', lang)}", value=creation.get("content_lines",""), placeholder=t("creation.boundaries_placeholder", lang)).props("rows=2").classes("w-full")
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
                with confirm_container:
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.spinner("dots", size="md", color="primary")
                        ui.label(t("creation.world_awakens", lang)).classes("text-sm").style("color: var(--text-secondary)")
                await _scroll_chat_bottom()
                try:
                    client=anthropic.Anthropic(api_key=s["api_key"]);config=get_engine_config();username=s["current_user"]
                    game,narration=await asyncio.to_thread(start_new_game,client,creation,config,username)
                    s["game"]=game;s["creation"]=None;s["active_save"]="autosave"
                    s["messages"].append({"scene_marker":t("game.scene_marker", lang, n=1, location=game.current_location)})
                    s["messages"].append({"role":"assistant","content":narration})
                    save_game(game,username,s["messages"],s["active_save"])
                    if s.get("tts_enabled",False): s["pending_tts"]=narration
                    ui.navigate.reload()
                except Exception as e: ui.notify(t("creation.error", lang, error=e), type="negative")
            ui.button(f"{E['swords']} {t('creation.start', lang)}", on_click=start, color="primary").classes("text-lg px-8")
            async def reroll():
                if not s.get("api_key", "").strip():
                    ui.notify(t("game.invalid_api_key", lang), type="negative")
                    return
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
                except Exception as e: ui.notify(t("creation.error", lang, error=e), type="negative")
            ui.button(f"{E['refresh']} {t('creation.reroll', lang)}", on_click=reroll, color="primary").props("outline").classes("text-lg px-8")
    return True


# ===============================================================
# GAME LOOP
# ===============================================================

async def process_player_input(text: str, chat_container, sidebar_container=None,
                               sidebar_refresh=None) -> None:
    s=S();game=s.get("game")
    if not game or not text.strip(): return
    # Double-send guard: prevent concurrent processing
    if s.get("processing", False):
        ui.notify(t("game.still_processing", L()), type="warning", position="top")
        return
    s["processing"] = True
    turn_gen = s.get("_turn_gen", 0)  # Capture generation to detect save-switch during processing
    config=get_engine_config();username=s["current_user"]
    s["messages"].append({"role":"user","content":text})
    with chat_container:
        with ui.column().classes("chat-msg user w-full"): ui.markdown(text)
    try:
        with chat_container: spinner=ui.spinner("dots", size="lg")
        # Scroll down so player sees their message + spinner
        await _scroll_chat_bottom()
        # Stop any playing audio
        try:
            await ui.run_javascript('document.querySelectorAll("audio").forEach(a=>{a.pause();a.currentTime=0})', timeout=3.0)
        except TimeoutError:
            pass
        client=anthropic.Anthropic(api_key=s["api_key"])
        game,narration,roll,burn_info,director_ctx=await asyncio.to_thread(process_turn,client,game,text,config)
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
        if game.scene_count > 1:
            s["messages"].append({"scene_marker":t("game.scene_marker", L(), n=game.scene_count, location=game.current_location)})
        roll_data=None
        if roll:
            ll=game.session_log[-1] if game.session_log else {}
            roll_data=build_roll_data(roll, consequences=ll.get("consequences",[]),
                clock_events=ll.get("clock_events",[]),
                brain={"position":ll.get("position","risky"),"effect":ll.get("effect","standard")})
        s["messages"].append({"role":"assistant","content":narration,"roll_data":roll_data})
        save_game(game,username,s["messages"],s.get("active_save","autosave"))
        # Render AI response
        scroll_target_id = f"msg-{len(s['messages'])}"
        with chat_container:
            if game.scene_count > 1:
                ui.html(f'<div id="{scroll_target_id}" class="scene-marker">{E["dash"]} {t("game.scene_marker", L(), n=game.scene_count, location=game.current_location)} {E["dash"]}</div>')
            else:
                ui.html(f'<div id="{scroll_target_id}"></div>')
            msg_col = ui.column().classes("chat-msg assistant w-full")
            with msg_col:
                ui.markdown(_clean_narration(narration))
                if roll_data: render_dice_display(roll_data)
        # Two-step scroll: bottom first (forces DOM render), then up to scene marker
        await _scroll_chat_bottom()
        await _scroll_to_element(scroll_target_id)
        # Fire Director in background — doesn't block narration display
        if director_ctx:
            _dc=director_ctx; _g=game; _u=username; _s=s; _gen=turn_gen
            async def _bg_director():
                try:
                    await asyncio.to_thread(run_deferred_director, client, _g, _dc)
                    # Don't save if user switched to a different game during Director processing
                    if _s.get("_turn_gen", 0) != _gen:
                        log("[Director] Discarding stale save (game context changed)")
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
            await do_tts(narration, msg_col)
    except anthropic.AuthenticationError:
        try: spinner.delete()
        except Exception: pass
        ui.notify(t("game.invalid_api_key", L()), type="negative")
    except Exception as e:
        try: spinner.delete()
        except Exception: pass
        ui.notify(t("game.error", L(), error=e), type="negative")
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
    with ui.card().classes("w-full p-4").style("background: var(--accent-dim); border: 1px solid var(--accent)") as burn_card:
        ui.markdown(t("momentum.question", lang, cost=pre_momentum, result=rl))
        with ui.row().classes("gap-4 mt-4") as btn_row:
            async def burn():
                try:
                    # Show spinner and disable buttons
                    btn_row.set_visibility(False)
                    with burn_card:
                        burn_spinner = ui.row().classes("w-full items-center gap-2")
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
                    rd=build_roll_data(ur,consequences=ll.get("consequences",[]),clock_events=ll.get("clock_events",[]),brain=bd["brain"])
                    msgs=s["messages"]
                    if msgs and msgs[-1].get("role")=="assistant":
                        msgs[-1]={"role":"assistant","content":f"*{E['fire']} {t('momentum.gathering', lang)}*\n\n{narration}",
                                  "roll_data":rd}
                    save_game(game,username,s["messages"],s.get("active_save","autosave"))
                    if s.get("tts_enabled",False): s["pending_tts"]=narration
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
            s["game"] = g; s["pending_burn"] = None; ch = g.chapter_number
            s["messages"] = [{"role": "assistant", "content": f"*{E['book']} {t(chapter_msg_key, lang, n=ch)}*\n\n{n}"}]
            save_game(g, username, s["messages"], s.get("active_save", "autosave"))
            if s.get("tts_enabled", False): s["pending_tts"] = n
            ui.navigate.reload()
        except Exception as e:
            loading_dlg.close()
            log(f"[Chapter] Error starting new chapter: {e}", level="warning")
            ui.notify(t("game.error", lang, error=e), type="negative")

    def full_new():
        s["game"] = None; s["creation"] = None; s["messages"] = []; s["active_save"] = "autosave"
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
        with ui.card().classes("w-full p-4").style("background: rgba(217,119,6,0.1); border: 1px solid rgba(217,119,6,0.4)"):
            ui.markdown(f"{E['star']} **{t('epilogue.done_title', lang)}**")
            ui.label(t("epilogue.done_text", lang)).classes("text-sm mt-1")
            with ui.row().classes("gap-4 mt-4"):
                new_ch, full_new = _make_chapter_action(game, "epilogue.chapter_msg")
                ui.button(f"{E['refresh']} {t('epilogue.new_chapter', lang)}", on_click=new_ch, color="primary")
                ui.button(f"{E['trash']} {t('epilogue.restart', lang)}", on_click=full_new)
        return True  # Hide footer — story is done

    # --- Epilogue offer: story complete but epilogue not yet generated ---
    if bp.get("story_complete") and not game.epilogue_dismissed:
        with ui.card().classes("w-full p-4").style("background: rgba(217,119,6,0.08); border: 1px solid rgba(217,119,6,0.3)"):
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
                        s["messages"].append({"role":"assistant","content":f"*{E['star']} {t('epilogue.marker', lang)}*\n\n{epilogue_text}"})
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
    return False  # Keep footer active — player can still type


def render_game_over() -> bool:
    s=S();game=s.get("game");lang=L()
    if not game or not game.game_over: return False
    kid=s.get("kid_friendly",False)
    with ui.card().classes("w-full p-4").style("background: rgba(220,38,38,0.1); border: 1px solid rgba(220,38,38,0.4)"):
        ui.markdown(f"{t('gameover.title', lang)} " + (t("gameover.kid", lang) if kid else t("gameover.dark", lang)))
        with ui.row().classes("gap-4 mt-4"):
            new_ch, full_new = _make_chapter_action(game, "gameover.chapter_msg")
            ui.button(f"{E['refresh']} {t('gameover.new_chapter', lang)}", on_click=new_ch, color="primary")
            ui.button(f"{E['trash']} {t('gameover.restart', lang)}", on_click=full_new)
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
    # With HTTPS/self-signed certs, tab storage may need extra time to become available
    for _attempt in range(5):
        try:
            init_session()
            break
        except RuntimeError:
            await asyncio.sleep(0.5)
    else:
        log("[Session] app.storage.tab not available after retries", level="warning")
        return
    loading.delete()
    setup_file_logging()
    s = S()

    # ==================================================================
    # PAGE SKELETON — created once at page build, shown/hidden per phase
    # ==================================================================

    # Slim header with hamburger menu (hidden until main app phase)
    with ui.header(fixed=True).classes("rpg-slim-header items-center").style("padding: 0 0.5rem") as header:
        ui.button(icon="menu", on_click=lambda: drawer.toggle()) \
            .props("flat round dense").classes("text-gray-400 hover:text-white") \
            .style("min-width: 44px; min-height: 44px")
    header.set_value(False)

    # Left drawer (created at page level, hidden initially, populated in main phase)
    with ui.left_drawer(value=False).props("width=320 breakpoint=768") as drawer:
        drawer_content = ui.column().classes("w-full")

    # Footer (created at page level, hidden initially, populated in main phase)
    with ui.footer(fixed=True).classes("q-pa-none").style(
        "background: var(--bg-primary); border-top: 1px solid var(--border)"
    ) as footer:
        footer_content = ui.column().classes("w-full")
    footer.set_value(False)

    # Main content area
    content_area = ui.column().classes("w-full max-w-4xl mx-auto px-4 sm:px-0")

    # ==================================================================
    # PHASE FUNCTIONS — transition without ui.navigate.reload()
    # ==================================================================

    def _show_login_phase():
        """Phase 1: Invite code login (no reload on success)."""
        header.set_value(False)
        drawer.set_value(False)
        footer.set_value(False)
        content_area.clear()
        lang = L()
        with content_area:
            with ui.column().classes("w-full max-w-sm mx-auto mt-20 gap-4 items-center"):
                ui.label(f"{E['swords']} {t('login.title', lang)}").classes("text-2xl font-bold")
                ui.label(t("user.subtitle", lang)).classes("text-gray-400 italic")
                ui.label(t("login.subtitle", lang)).classes("text-gray-400 text-sm")
                code_inp = ui.input(t("login.code_label", lang), password=True, password_toggle_button=True).classes("w-full")
                error_label = ui.label("").classes("text-red-400 text-sm")
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

    async def _select_user(name: str):
        """Handle user selection → transition to main phase without reload."""
        s["current_user"] = name
        load_user_settings(name)
        s["user_config_loaded"] = True
        # Auto-load autosave if it exists
        if not s.get("game"):
            loaded, hist = load_game(name, "autosave")
            if loaded:
                s["game"] = loaded
                s["messages"] = hist
                s["active_save"] = "autosave"
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

        # --- Populate drawer ---
        drawer_content.clear()
        with drawer_content:
            with ui.row().classes("w-full items-center justify-between mb-2"):
                ui.label(s["current_user"]).classes("text-lg font-semibold")
                ui.button(icon="chevron_left", on_click=drawer.hide).props("flat round dense").classes("text-gray-500 hover:text-white").style("min-width: 44px; min-height: 44px")
            sidebar_status_container = ui.column().classes("w-full")
            game = s.get("game")
            if game:
                with sidebar_status_container:
                    render_sidebar_status(game)
            render_sidebar_actions(on_switch_user=_handle_switch_user)
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
            s["_chat_container"] = chat_container  # Store reference for sidebar actions (recap etc.)
            with chat_container:
                last_scene_id = render_chat_messages(chat_container)

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

        # --- Populate footer (input bar) ---
        game = s.get("game")
        if game and not game.game_over and chat_container:
            footer_content.clear()
            with footer_content:
                # STT status line (hidden by default, shown during recording/transcription)
                stt_status = ui.row().classes("stt-status-row rpg-input-bar hidden w-full items-center")
                with stt_status:
                    stt_status_content = ui.html("").style("display: inline")
                with ui.row().classes("w-full items-center gap-2 rpg-input-bar").style("padding: 0.5rem 1rem"):
                    inp = ui.input(placeholder=t("game.input_placeholder", L())).classes("flex-grow").props("outlined dense dark")
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
                        mic_btn = ui.button(icon="mic", on_click=lambda: None).props("flat dense") \
                            .classes("text-gray-400 hover:text-white stt-mic-btn") \
                            .style("border: 1px solid var(--border-light); border-radius: 8px; min-width: 44px; height: 44px")
                        _setup_stt_button(mic_btn, inp, _cc, stt_status, stt_status_content, sidebar_refresh=_sr)
                    ui.button(icon="send", on_click=send).props("flat dense").classes("text-gray-400 hover:text-white").style("border: 1px solid var(--border-light); border-radius: 8px; min-width: 44px; height: 44px")
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

def _generate_self_signed_cert():
    """Generate a self-signed SSL certificate for local HTTPS."""
    cert_dir = Path.home() / ".rpg_engine_ssl"
    cert_dir.mkdir(exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    # Reuse existing cert if less than 365 days old
    if cert_path.exists() and key_path.exists():
        import time
        age_days = (time.time() - cert_path.stat().st_mtime) / 86400
        if age_days < 365:
            log(f"[SSL] Reusing existing certificate from {cert_dir}")
            return str(cert_path), str(key_path)
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime, ipaddress, socket
        log("[SSL] Generating self-signed certificate...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        # Get local hostname and IPs for SAN
        hostname = socket.gethostname()
        san_entries = [
            x509.DNSName("localhost"),
            x509.DNSName(hostname),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        # Add all local network IPs
        try:
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip != "127.0.0.1":
                    san_entries.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "EdgeTales Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EdgeTales"),
        ])
        cert = (x509.CertificateBuilder()
                .subject_name(subject).issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
                .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
                .sign(key, hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        log(f"[SSL] Certificate generated: {cert_path}")
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
if SSL_CERTFILE and SSL_KEYFILE:
    _ssl_kwargs = {"ssl_certfile": SSL_CERTFILE, "ssl_keyfile": SSL_KEYFILE}
    log(f"[SSL] Using custom certificate: {SSL_CERTFILE}")
elif ENABLE_HTTPS:
    _cert, _key = _generate_self_signed_cert()
    if _cert and _key:
        _ssl_kwargs = {"ssl_certfile": _cert, "ssl_keyfile": _key}

if _ssl_kwargs:
    _proto = "https"
    log(f"[SSL] HTTPS enabled on port {SERVER_PORT}")
else:
    _proto = "http"

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
