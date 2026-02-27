#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Narrative RPG Engine — Voice Module (Framework-Independent)
===========================================================
Extracted from rpg_engine.py v5.11 for NiceGUI migration.
Contains: EdgeTTSBackend, ChatterboxBackend, VoiceEngine (TTS + STT).
No Streamlit dependency.
"""

import re
import io
import asyncio
import tempfile
import logging
import concurrent.futures
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Import engine constants (shared with engine.py)
# ---------------------------------------------------------------------------
from engine import (
    E, log, VOICE_DIR,
    CHATTERBOX_LANG_MAP, CHATTERBOX_DEVICE_OPTIONS,
    LANGUAGES,
)
from i18n import _NO_VOICE_SAMPLE_LABEL, resolve_voice_id


# ===============================================================
# TEXT CLEANUP
# ===============================================================

def _clean_text_for_tts(text: str) -> str:
    """Clean text for any TTS backend: strip markdown, emojis, normalize punctuation."""
    clean = re.sub(r'\*\*?(.*?)\*\*?', r'\1', text)
    clean = re.sub(r'#{1,6}\s*', '', clean)
    clean = re.sub(r'---+', '', clean)
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
    clean = re.sub(r'`[^`]+`', '', clean)
    # Strip ALL emoji (comprehensive range)
    clean = re.sub(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF'
        r'\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF'
        r'\u2600-\u26FF\u2700-\u27BF\u2300-\u23FF\uFE0F]+', '', clean)
    # Normalize dashes and special punctuation for TTS
    clean = clean.replace('\u2014', ' \u2013 ')  # em dash -> spaced en dash
    clean = clean.replace('\u2013', ', ')  # en dash -> comma pause
    clean = re.sub(r'\n{2,}', '. ', clean)  # paragraph breaks -> sentence pause
    clean = re.sub(r'\n', ' ', clean)
    clean = re.sub(r'\s{2,}', ' ', clean).strip()
    return clean


# ===============================================================
# VOICE CONFIGURATION (replaces st.session_state for voice settings)
# ===============================================================

@dataclass
class VoiceConfig:
    """All voice-related settings. The UI layer populates this."""
    tts_enabled: bool = False
    stt_enabled: bool = False
    # Backend selection
    tts_backend: str = "edge_tts"   # "edge_tts" or "chatterbox"
    # EdgeTTS settings
    voice_select: str = ""              # display label; resolved via resolve_voice_id()
    tts_rate: str = "+0%"
    # Chatterbox settings
    cb_device: str = "Auto"
    cb_exaggeration: float = 0.5
    cb_cfg_weight: float = 0.5
    cb_voice_sample: str = ""       # filename in VOICE_DIR, or "" for default
    # Whisper STT settings
    whisper_size: str = "medium"
    # Language (resolved English name, e.g. "German")
    narration_lang: str = "German"


# Optional callback type for progress reporting
# Signature: callback(progress: float, message: str)
ProgressCallback = Optional[Callable[[float, str], None]]

# --- Tuning constants ---
EDGE_TTS_MAX_TEXT_CHARS = 4000         # Truncate input text beyond this
EDGE_TTS_TIMEOUT_SEC = 30             # Timeout for edge-tts synthesis
CHATTERBOX_MAX_TEXT_CHARS = 6000      # Truncate input text beyond this
CHATTERBOX_MAX_CHUNK_CHARS = 350      # Split text into chunks of this size
# OGG vs WAV encoding threshold: ~15 seconds at 48kHz.
# Shorter audio → OGG (smaller). Longer audio → WAV (avoids OGG encoder memory issues).
CHATTERBOX_OGG_SAMPLE_THRESHOLD = 720_000


# ===============================================================
# EDGE TTS BACKEND
# ===============================================================

class EdgeTTSBackend:
    """TTS backend using Microsoft Edge TTS (online, free)."""

    audio_format = "audio/mp3"

    @staticmethod
    async def _tts_async(text: str, voice: str, rate: str) -> bytes:
        import edge_tts
        kwargs = {"voice": voice}
        if rate and rate != "+0%":
            kwargs["rate"] = rate
        comm = edge_tts.Communicate(text, **kwargs)
        buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    @staticmethod
    def _run_tts_in_thread(text: str, voice: str, rate: str) -> bytes:
        """Run async TTS in a fresh thread with its own event loop."""
        return asyncio.run(EdgeTTSBackend._tts_async(text, voice, rate))

    def synthesize(self, text: str, *, voice: str = "de-DE-ConradNeural",
                   rate: str = "+0%", **kwargs) -> Optional[bytes]:
        clean = _clean_text_for_tts(text)
        if not clean or len(clean) < 3:
            return None
        # Truncate very long texts (edge-tts can choke on >5000 chars)
        if len(clean) > EDGE_TTS_MAX_TEXT_CHARS:
            cut = clean[:EDGE_TTS_MAX_TEXT_CHARS].rfind('.')
            clean = clean[:cut + 1] if cut > 0 else clean[:EDGE_TTS_MAX_TEXT_CHARS]
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                audio = pool.submit(
                    self._run_tts_in_thread, clean, voice, rate
                ).result(timeout=EDGE_TTS_TIMEOUT_SEC)
            if audio and len(audio) > 100:
                return audio
            log("TTS: No audio data received.", level="warning")
            return None
        except concurrent.futures.TimeoutError:
            log(f"TTS error (edge-tts): Timeout ({EDGE_TTS_TIMEOUT_SEC}s). Check network.",
                level="warning")
            return None
        except Exception as e:
            log(f"TTS error (edge-tts): {e}", level="warning")
            return None


# ===============================================================
# CHATTERBOX BACKEND
# ===============================================================

class ChatterboxBackend:
    """TTS backend using Chatterbox by Resemble AI (offline, GPU recommended).

    Install: pip install chatterbox-tts
    Requires: Python 3.10-3.11, PyTorch
    """

    audio_format = "audio/ogg"  # OGG Vorbis: ~10-20x smaller than WAV

    def __init__(self):
        self._model = None
        self._device = None
        self._multilingual = False
        self._lang_warned = False

    @staticmethod
    def _fmt_size(b: int) -> str:
        """Format byte count as human-readable string."""
        if b >= 1024 ** 3:
            return f"{b / 1024 ** 3:.1f} GB"
        if b >= 1024 ** 2:
            return f"{b / 1024 ** 2:.0f} MB"
        return f"{b / 1024:.0f} KB"

    def _download_model_with_progress(self, repo_id: str,
                                       on_progress: ProgressCallback = None):
        """Pre-download model files with optional progress callback.
        If on_progress is None, just logs silently.
        """
        try:
            from huggingface_hub import HfApi, hf_hub_download, try_to_load_from_cache
        except ImportError:
            return

        try:
            api = HfApi()
            info = api.model_info(repo_id)
        except Exception:
            return

        model_exts = {'.safetensors', '.pt', '.pth', '.bin', '.json'}
        files = []
        for s in info.siblings:
            ext = Path(s.rfilename).suffix.lower()
            if ext in model_exts and '/' not in s.rfilename:
                files.append((s.rfilename, s.size or 0))

        if not files:
            return

        to_download = []
        for fname, size in files:
            try:
                cached = try_to_load_from_cache(repo_id, fname)
                if not isinstance(cached, str):
                    to_download.append((fname, size))
            except Exception:
                to_download.append((fname, size))

        if not to_download:
            return

        total_bytes = sum(s for _, s in to_download)
        downloaded_bytes = 0

        for i, (fname, size) in enumerate(to_download):
            msg = (f"\u2B07\uFE0F {fname} ({self._fmt_size(size)}) "
                   f"{E['dash']} Datei {i + 1}/{len(to_download)} "
                   f"{E['dot']} {self._fmt_size(downloaded_bytes)}/{self._fmt_size(total_bytes)}")
            log(f"[Chatterbox] Downloading: {msg}")
            if on_progress:
                progress = downloaded_bytes / total_bytes if total_bytes > 0 else 0
                on_progress(progress, msg)
            try:
                hf_hub_download(repo_id=repo_id, filename=fname)
            except Exception as e:
                log(f"[Chatterbox] Download error for {fname}: {e}", level="warning")
                return
            downloaded_bytes += size

        final_msg = f"{E['check']} Modell heruntergeladen ({self._fmt_size(total_bytes)})"
        log(f"[Chatterbox] {final_msg}")
        if on_progress:
            on_progress(1.0, final_msg)

    def _ensure_model(self, device: str = "auto",
                      on_progress: ProgressCallback = None):
        """Lazy-load the Chatterbox model on first use.
        Prefers ChatterboxMultilingualTTS (23+ languages).
        Falls back to ChatterboxTTS (English only) if multilingual unavailable.
        """
        if self._model is not None:
            return
        try:
            import torch
        except ImportError:
            raise RuntimeError(
                f"{E['warn']} PyTorch nicht installiert. Benötigt für Chatterbox."
            )

        model_label = ""
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            model_class = ChatterboxMultilingualTTS
            self._multilingual = True
            repo_id = "ResembleAI/chatterbox-multilingual"
            model_label = "Multilingual (23+ Sprachen)"
        except ImportError:
            try:
                from chatterbox.tts import ChatterboxTTS
                model_class = ChatterboxTTS
                self._multilingual = False
                repo_id = "ResembleAI/chatterbox"
                model_label = "English-only"
                log(f"{E['globe']} Chatterbox-Multilingual nicht verfügbar. Nur Englisch aktiv. "
                    "Für Mehrsprachigkeit: `pip install --upgrade chatterbox-tts`",
                    level="warning")
            except ImportError:
                raise RuntimeError(
                    f"{E['warn']} Chatterbox nicht installiert.\n"
                    "pip install chatterbox-tts\n"
                    "Benötigt Python 3.10–3.11 und PyTorch."
                )

        if hasattr(model_class, 'REPO_ID'):
            repo_id = model_class.REPO_ID

        # Auto-detect best device
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        # Phase 1: Download model files
        self._download_model_with_progress(repo_id, on_progress)

        # Phase 2: Load model into memory
        self._device = device
        log(f"[Chatterbox] Initializing {model_label} ({device})...")
        if on_progress:
            on_progress(0.99, f"{E['brain']} Initialisiere Chatterbox {model_label} ({device})...")

        _orig_torch_load = torch.load
        if device == "cpu":
            def _patched_load(*args, **kwargs):
                kwargs.setdefault("map_location", "cpu")
                return _orig_torch_load(*args, **kwargs)
            torch.load = _patched_load

        try:
            self._model = model_class.from_pretrained(device=device)
        except Exception as e:
            if device != "cpu":
                log(f"[Chatterbox] Device '{device}' failed: {e}\nFalling back to CPU...",
                    level="warning")
                self._device = "cpu"
                def _patched_load_fb(*args, **kwargs):
                    kwargs.setdefault("map_location", "cpu")
                    return _orig_torch_load(*args, **kwargs)
                torch.load = _patched_load_fb
                self._model = model_class.from_pretrained(device="cpu")
            else:
                raise
        finally:
            torch.load = _orig_torch_load

        log(f"[Chatterbox] {E['check']} {model_label} loaded ({self._device})")

    @staticmethod
    def _get_voice_sample(voice_sample: str) -> Optional[str]:
        """Return path to voice sample file, or None."""
        if not voice_sample or voice_sample in _NO_VOICE_SAMPLE_LABEL.values():
            return None
        path = VOICE_DIR / voice_sample
        if path.exists() and path.stat().st_size > 500:
            return str(path)
        return None

    @staticmethod
    def _split_into_chunks(text: str, max_chars: int = CHATTERBOX_MAX_CHUNK_CHARS) -> list[str]:
        """Split text into chunks at sentence boundaries for better TTS prosody."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current = ""
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if current and len(current) + len(sent) + 1 > max_chars:
                chunks.append(current.strip())
                current = sent
            else:
                current = f"{current} {sent}" if current else sent
        if current.strip():
            chunks.append(current.strip())
        # Safety: if a single sentence is very long, split at comma/semicolon
        result = []
        for chunk in chunks:
            if len(chunk) > max_chars * 1.5:
                parts = re.split(r'(?<=[,;:])\s+', chunk)
                sub = ""
                for part in parts:
                    if sub and len(sub) + len(part) + 1 > max_chars:
                        result.append(sub.strip())
                        sub = part
                    else:
                        sub = f"{sub} {part}" if sub else part
                if sub.strip():
                    result.append(sub.strip())
            else:
                result.append(chunk)
        return result if result else [text]

    def synthesize(self, text: str, *, lang: str = "de",
                   exaggeration: float = 0.5, cfg_weight: float = 0.5,
                   device: str = "auto", voice_sample: str = "",
                   on_progress: ProgressCallback = None,
                   **kwargs) -> Optional[tuple[bytes, str]]:
        """Synthesize text. Returns (audio_bytes, mime_type) or None."""
        clean = _clean_text_for_tts(text)
        if not clean or len(clean) < 3:
            return None
        if len(clean) > CHATTERBOX_MAX_TEXT_CHARS:
            cut = clean[:CHATTERBOX_MAX_TEXT_CHARS].rfind('.')
            clean = clean[:cut + 1] if cut > 0 else clean[:CHATTERBOX_MAX_TEXT_CHARS]
        try:
            self._ensure_model(device=device, on_progress=on_progress)
            result_format = "audio/ogg"  # Default; may switch to WAV below
            import torch
            import torchaudio
            import time as _time

            ref_path = self._get_voice_sample(voice_sample)
            if ref_path:
                log(f"[Chatterbox] Using voice sample: {ref_path}")
            else:
                log("[Chatterbox] No voice sample — using default voice")

            if self._multilingual:
                gen_kwargs = dict(
                    exaggeration=exaggeration,
                    cfg_weight=cfg_weight,
                    language_id=lang,
                )
            else:
                if lang != "en" and not self._lang_warned:
                    log(f"[Chatterbox] English-only Modell aktiv. Sprache '{lang}' wird ignoriert.",
                        level="warning")
                    self._lang_warned = True
                gen_kwargs = dict(
                    exaggeration=exaggeration,
                    cfg_weight=cfg_weight,
                )
            if ref_path:
                gen_kwargs["audio_prompt_path"] = ref_path

            chunks = self._split_into_chunks(clean)
            log(f"[Chatterbox] Input text ({len(clean)} chars) → {len(chunks)} chunk(s)")
            for i, ch in enumerate(chunks):
                log(f"[Chatterbox]   Chunk {i+1}: {len(ch)} chars → {repr(ch[:80])}{'...' if len(ch) > 80 else ''}")

            wav_parts = []
            _silence_samples = int(self._model.sr * 0.3)
            _silence = torch.zeros(1, _silence_samples)

            _t_total = _time.monotonic()
            for i, chunk in enumerate(chunks):
                _t0 = _time.monotonic()
                wav = self._model.generate(chunk, **gen_kwargs)
                _t1 = _time.monotonic()
                log(f"[Chatterbox]   Chunk {i+1}/{len(chunks)} done in {_t1-_t0:.1f}s, "
                      f"shape={wav.shape}")
                wav_parts.append(wav)
                if i < len(chunks) - 1:
                    wav_parts.append(_silence)

            if len(wav_parts) == 1:
                final_wav = wav_parts[0]
            else:
                final_wav = torch.cat(wav_parts, dim=1)

            del wav_parts

            _t_gen_done = _time.monotonic()
            log(f"[Chatterbox] All chunks generated in {_t_gen_done-_t_total:.1f}s total, "
                  f"final shape={final_wav.shape}")

            final_wav = final_wav.cpu().contiguous()

            _t_enc = _time.monotonic()
            buf = io.BytesIO()
            _use_ogg = final_wav.shape[1] < CHATTERBOX_OGG_SAMPLE_THRESHOLD
            log(f"[Chatterbox] Encoding {final_wav.shape[1]} samples as "
                f"{'OGG' if _use_ogg else 'WAV'} ...")
            try:
                if _use_ogg:
                    torchaudio.save(buf, final_wav, self._model.sr, format="ogg")
                else:
                    torchaudio.save(buf, final_wav, self._model.sr, format="wav")
                    result_format = "audio/wav"
            except Exception as enc_err:
                if not _use_ogg:
                    raise  # WAV encoding failed — no fallback, propagate to outer handler
                log(f"[Chatterbox] OGG encoding failed ({enc_err}), falling back to WAV",
                    level="warning")
                buf = io.BytesIO()
                torchaudio.save(buf, final_wav, self._model.sr, format="wav")
                result_format = "audio/wav"
            audio_bytes = buf.getvalue()
            _t_done = _time.monotonic()
            log(f"[Chatterbox] Audio encoded in {_t_done-_t_enc:.1f}s, "
                  f"size={len(audio_bytes)/1024:.0f} KB")
            if audio_bytes and len(audio_bytes) > 100:
                return audio_bytes, result_format
            log("Chatterbox: No audio data received.", level="warning")
            return None
        except ImportError:
            return None
        except Exception as e:
            log(f"TTS error (Chatterbox): {e}", level="warning")
            return None

    @staticmethod
    def convert_to_wav(src_path: Path) -> Path:
        """Convert any audio file to WAV using torchaudio. Returns path to WAV file.
        Removes the original non-WAV file after successful conversion.
        """
        dst_path = src_path.with_suffix(".wav")
        try:
            import torchaudio
            waveform, sr = torchaudio.load(str(src_path))
            torchaudio.save(str(dst_path), waveform, sr, format="wav")
            if src_path != dst_path and src_path.exists():
                src_path.unlink()
            log(f"[Chatterbox] Converted {src_path.name} -> {dst_path.name}")
            return dst_path
        except Exception as e:
            log(f"[Chatterbox] WAV conversion failed: {e}")
            if dst_path.exists() and dst_path != src_path:
                dst_path.unlink(missing_ok=True)
            return src_path


# ===============================================================
# VOICE ENGINE FACADE
# ===============================================================

class VoiceEngine:
    """Facade for TTS backends + STT (Whisper).
    All settings passed explicitly via VoiceConfig — no session_state.
    """

    def __init__(self):
        self._whisper_model = None
        self._whisper_size = None
        self._edge_tts = EdgeTTSBackend()
        self._chatterbox = None  # Lazy: only created when first needed

    def _get_backend(self, backend_code: str = "edge_tts"):
        """Return the requested TTS backend instance."""
        if backend_code == "chatterbox":
            if self._chatterbox is None:
                self._chatterbox = ChatterboxBackend()
            return self._chatterbox
        return self._edge_tts

    def text_to_speech(self, text: str, config: VoiceConfig,
                       on_progress: ProgressCallback = None) -> tuple[Optional[bytes], str]:
        """Synthesize text using the configured backend. Returns (audio_bytes, mime_type)."""
        if not config.tts_enabled:
            return None, "audio/mp3"
        backend = self._get_backend(config.tts_backend)

        if isinstance(backend, ChatterboxBackend):
            lang_code = CHATTERBOX_LANG_MAP.get(config.narration_lang)
            if lang_code is None:
                log(f"[Voice] Chatterbox unterstützt '{config.narration_lang}' nicht. Verwende Englisch.",
                    level="warning")
                lang_code = "en"
            device_code = CHATTERBOX_DEVICE_OPTIONS.get(config.cb_device, "auto")
            result = backend.synthesize(
                text,
                lang=lang_code,
                exaggeration=config.cb_exaggeration,
                cfg_weight=config.cb_cfg_weight,
                device=device_code,
                voice_sample=config.cb_voice_sample,
                on_progress=on_progress,
            )
            # synthesize returns (audio_bytes, mime_type) or None
            if result is None:
                return None, "audio/ogg"
            return result
        else:
            voice_id = resolve_voice_id(config.voice_select)
            result = backend.synthesize(text, voice=voice_id, rate=config.tts_rate)
            return result, backend.audio_format

    def get_audio_format(self, config: VoiceConfig) -> str:
        """Return the MIME type of the active backend's output."""
        return self._get_backend(config.tts_backend).audio_format

    def speech_to_text(self, audio_bytes: bytes, config: VoiceConfig) -> str:
        """Transcribe audio to text using Whisper."""
        model_size = config.whisper_size
        if self._whisper_model is None or self._whisper_size != model_size:
            try:
                from faster_whisper import WhisperModel
                self._whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                self._whisper_size = model_size
            except Exception as e:
                log(f"Whisper error: {e}", level="error")
                return ""
        import tempfile as _tf
        with _tf.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        try:
            _whisper_lang_map = {
                "German": "de", "English": "en", "Spanish": "es", "French": "fr",
                "Portuguese": "pt", "Italian": "it", "Dutch": "nl", "Russian": "ru",
                "Chinese (Mandarin)": "zh", "Japanese": "ja", "Korean": "ko",
                "Arabic": "ar", "Hindi": "hi", "Indonesian": "id", "Turkish": "tr",
                "Polish": "pl", "Vietnamese": "vi", "Thai": "th", "Swedish": "sv",
                "Danish": "da",
            }
            whisper_lang = _whisper_lang_map.get(config.narration_lang, "de")
            segs, _ = self._whisper_model.transcribe(tmp, language=whisper_lang,
                                                      beam_size=5, vad_filter=True)
            return " ".join(s.text.strip() for s in segs)
        except Exception as e:
            log(f"STT error: {e}", level="warning")
            return ""
        finally:
            Path(tmp).unlink(missing_ok=True)
