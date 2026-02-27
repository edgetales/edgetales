# Changelog

All notable changes to EdgeTales are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [0.9.24] — 2025

### Added
- **Deferred Director:** Director AI runs non-blocking in the background via `asyncio.create_task()` — narration displays instantly, no more 2–4s wait per turn
- **Truncation Salvage:** `_close_truncated_json()` rescues cut-off Director responses (stack-based bracket tracking, dangling key removal). `_salvage_truncated_narration()` trims Narrator output to last complete sentence instead of showing broken text
- **NPC Description Updates:** Director dynamically updates NPC sidebar descriptions during reflections — characters evolve visually as the story progresses
- **STT Chunked Upload:** Audio recordings split into 500KB chunks for WebSocket transmission — removes the ~30s recording limit. Live recording timer with 2-minute auto-stop
- **Cross-Save Protection:** Turn-generation counter prevents stale AI responses from landing in the wrong save after mid-processing save switches

### Fixed
- Sidebar showed English labels despite German UI setting (wrong session key)
- `scene: None` in Director reflections crashed NPC sorting (`TypeError` on `max()`)
- Sidebar lost session context after long async operations
- Processing notification styling (cyan → amber for dark theme)

### Changed
- Director max_tokens 1000 → 1200, Narrator max_tokens 2000 → 2500
- All AI metadata fields (NPC descriptions, memory events, scene context) now enforce narration language
- Brain prompts explicitly require `location_change` and `player_intent` in narration language

---

## [0.9.23]

### Added
- **LLM JSON Repair:** `_repair_json()` fixes common Haiku JSON errors — unescaped control characters, missing commas, trailing commas. Applied to Director, Story Architect, and Chapter Summary calls with zero overhead on valid JSON

---

## [0.9.22]

### Fixed
- Mid-game `<game_data>` tags no longer overwrite the entire NPC list (scene-count guard)
- Opening-scene NPCs get consistent auto-assigned IDs (local counter prevents collisions)
- Freshly introduced NPCs are protected from immediate background demotion (+1000 relevance bonus)
- Chapter memory trim now keeps the 5 most *important* memories instead of the 5 most recent
- `_needs_reflection` flag cleanup for NPCs the Director doesn't address (prevents infinite trigger loops)
- NPC substring matching minimum raised from 3 to 4 characters
- API key validation in all Character Creation API calls (clear error instead of silent failure)
- Recap renders directly into chat without page reload

### Changed
- `_clean_narration()` reduced from 10 to 4 regex patterns (single responsibility — engine parser handles the rest)

---

## [0.9.21]

### Fixed
- **Critical:** Transient `_needs_reflection` flag removed from save files on load — prevents stale Director triggers
- `translate_consequence()` uses word-boundary regex to prevent substring collisions (e.g., NPC named "Bond")
- Momentum burn UI shows pre-consequence value from snapshot (not post-consequence)
- Chatterbox WAV fallback only triggers on OGG encoding failure (not on WAV failure)
- `burn_momentum()` renamed to `can_burn_momentum()` for clarity

---

## [0.9.20]

### Added
- **NPC Memory System:** Importance scoring (1–10) based on emotional weight + keyword boosts. Weighted retrieval (recency/importance/relevance) replaces simple last-5 slice. Intelligent consolidation with separate budgets for observations (15) and reflections (8)
- **Keyword-based NPC Activation:** Three-tier prompt context — full target NPC, activated NPCs (top 3 by score), known NPCs (name only). ~30–40% token savings in narrator prompts
- **Director Agent:** Third AI agent (Haiku) for strategic story guidance. Runs lazily on triggers (MISS rolls, chaos, new NPCs, every 3 scenes). Generates scene summaries, narrator guidance, NPC reflections. ~$0.003/session, 0ms player latency
- Importance accumulator per NPC triggers Director reflections at threshold (30)
- Auto-migration for existing saves to new memory fields

---

## [0.9.19]

### Fixed
- `call_narrator` consolidated to use shared retry wrapper (was duplicated)
- `_apply_memory_updates` fuzzy fallback prevents stub duplicates on NPC name variants
- `_clean_narration` catches bracket-format labels and leaked JSON blocks
- Missing i18n key `game.still_processing` added (DE + EN)

### Changed
- `_make_chapter_action()` extracted as shared helper for epilogue/game-over
- Dead code removed: `scene_count == 0` guard, unused voice imports

---

## [0.9.18]

### Added
- **API Retry Wrapper:** `_api_create_with_retry()` with exponential backoff for all 6 AI call functions
- **Sidebar Refresh Callback:** Proper callback pattern replaces direct container reference
- **Double-Send Guard:** User notification when input is rejected during processing

### Fixed
- TTS skipped during momentum burn (was immediately cut off by reload, now deferred)
- Recap saved before reload (was lost on tab close)
- Voice preview respects active TTS backend
- `render_creation_flow` return type annotation corrected

---

## [0.9.17]

### Changed
- **PDF Export** replaces plain-text export: title page with character details, serif typography, scene dividers, page footer ("Story experienced with EdgeTales"). Powered by reportlab

---

## [0.9.16]

### Fixed
- **Critical:** Case-sensitive NPC lookup in `_apply_memory_updates` caused duplicates (now uses `_find_npc()`)
- **Critical:** `call_narrator` now has retry logic (was the only unprotected AI call)
- Chaos interrupt preserved through momentum burn pipeline
- Consistent session log schema for opening scenes

### Changed
- Removed unused `faction` field from all NPC creation paths
- Dead `creation_data` parameter removed from `get_narrator_system()`

---

## [0.9.15]

### Fixed
- **Critical:** Clock trigger events now visible in dice display (were stored as strings instead of dicts)
- NPC lookup works by both ID and name (Brain sometimes returns names instead of IDs)
- Momentum burn updates clock events in session log
- Double-send guard via `s["processing"]` flag with `try/finally` safety

---

## [0.9.14]

### Added
- **Three-tier NPC Status:** `active` (full prompt context + sidebar) → `background` (sidebar only, dimmed) → `inactive` (data only). Replaces binary active/inactive
- **Auto-Reactivation:** Background NPCs return to active when targeted by player, re-mentioned by narrator, or receiving memory updates
- **Brain Background Context:** Background NPCs sent as condensed list to Brain for target recognition without token budget inflation
- Background NPCs shown in collapsed sidebar section "Known (N)" at 60% opacity
- Chapter transitions preserve both active and background NPCs

---

## [0.9.13]

### Added
- Character creation split into separate name and description fields (names like "24" now work as intended)

### Fixed
- Player wishes no longer all appear in scene 1 (pacing rule: max one per scene)
- Post-reload scroll targets last scene marker (was only scrolling to bottom)
- AI-generated recap headings capped at 1.1rem in chat

### Changed
- Save card layout redesigned: buttons in separate row to prevent accidental deletion

---

## [0.9.12]

### Fixed
- `epilogue_dismissed` moved from transient session to GameState (persists across reloads)
- Save deletion now requires confirmation dialog

### Changed
- Dead voice option flat-dicts removed from engine.py
- All voice.py log messages translated to English

---

## [0.9.11]

### Added
- **Full Consequence Reversal on Momentum Burn:** Pre-consequence snapshot restores health, spirit, supply, momentum, chaos, NPC bonds, and clock fills — not just +1
- Retry logic for `call_recap()` and `call_chapter_summary()`
- Duplicate clock prevention in `_process_game_data()`

### Fixed
- **Critical:** Epilogue trailing-JSON regex no longer destroys prose containing brackets
- **Critical:** XML stripping in epilogue limited to known metadata tags (was removing stylistic prose like `<sigh>`)

---

## [0.9.10]

### Added
- **Epilogue System:** Two-phase flow — generate atmospheric 4–6 paragraph epilogue or continue playing. Post-epilogue offers new chapter or fresh start. Persisted via `epilogue_shown` flag
- Save deletion confirmation dialog

---

## [0.9.9]

### Added
- **Configurable UI Default:** `default_ui_lang` in config.json sets default UI language for new users
- **Language-neutral Persistence:** Voice, TTS backend, and sample settings stored as codes instead of localized labels. Dual-input resolvers accept both formats for backward compatibility

### Fixed
- **Critical:** UI language switch no longer causes black screen (settings reload on language change)

---

## [0.9.8]

### Added
- **Central config.json:** All server settings (API key, invite code, HTTPS, port, etc.) in one file with 3-tier cascade: defaults → config.json → ENV overrides
- `config.example.json` template for repositories
- Configurable server port (default: 8080)
- User settings renamed from `config.json` to `settings.json` (auto-migration)

---

## [0.9.7]

### Fixed
- Stat clamping preserves sum constraint (fallback to defaults if clamping changes total)
- Parser no longer destroys prose containing brackets (line-wise trailing JSON detection)
- Momentum burn shows correct post-consequence cost

### Changed
- All fallback texts/blueprints switched from German to English (language-neutral)
- Tuning constants extracted from magic numbers across all files
- CSS scoped: audio filter, card margins
- `viewport-fit=cover` added for proper safe-area-inset support on notch devices
- Empty narration fallback extracts first paragraph from raw response

---

## [0.9.6]

### Added
- **PDF Export:** `export_story_pdf()` with title page, serif typography, scene dividers
- Tuning constants for all magic numbers (15 in engine.py, 5 in voice.py, 5 in app.py)
- Storage secret via config.json/ENV (replaces hardcoded value)
- Invite code rate limiting (5 attempts per IP, 5-minute lockout)

### Fixed
- Consequences show actual delta (not requested change when already at 0)
- `story_complete` flag as stronger ending hint in narrator prompt + sidebar badge
- Temp file cleanup race condition (thread-safe lock)
- VoiceEngine returns tuple instead of mutating shared state

### Changed
- CSS extracted to `custom_head.html` (~155 lines out of app.py)
- 17 functions in app.py received return type annotations
- Reconnect timeout 60s → 180s

---

## [0.9.5]

### Fixed
- Location underscores replaced with spaces in scene markers
- Chaos progress bar formula corrected (`chaos/9` instead of `(chaos-3)/6`)
- Momentum burn and game-over scroll to bottom after reload
- Act labels localized in sidebar

---

## [0.9.4]

### Added
- **Mid-Game NPC Discovery:** Narrator reports new named characters via `<new_npcs>` metadata. Minimal schema (name + description + disposition), code fills defaults
- **NPC Retirement:** `_retire_distant_npcs()` demotes low-relevance NPCs when exceeding soft limit (12)
- **Sidebar Live Refresh:** NPCs appear immediately after creation without page reload
- NPC sidebar sorted by relevance (bond desc, last scene desc)
- Diagnostic logging for raw narrator response, parser steps, NPC state

---

## [0.9.3]

### Added
- **Active-Slot Save System:** `active_save` determines auto-save target. Switches on "Save As" or "Load", resets on new game
- **Auto-Load on Login:** Autosave loads automatically when selecting a player
- Card-based save list with metadata (character, scene, chapter, date)

### Changed
- Rebranded to "EdgeTales — A Narrative Solo-RPG Engine"

---

## [0.9.2]

### Added
- **Match System:** Doubles on challenge dice (~10% chance) trigger fate twists. Visual indicator ☄️ in dice display, communicated to narrator via `match="true"` attribute
- Pipe-bracket metadata filter in parser (catches `**[... | ... | ...]**` leaks)

---

## [0.9.1]

### Added
- **Internationalization (i18n):** New `i18n.py` with complete translation system (German + English). ~200 UI strings, emoji constants, language dicts centralized
- Separate dropdowns for UI language and narration language
- Language-neutral persistence for settings
- `translate_consequence()` for backward compatibility with German save files

---

## [0.9.0] — Initial Public Beta

### Added
- Complete solo RPG engine with AI narrator
- Two-AI architecture: Haiku (Brain parser) + Sonnet (Narrator)
- Ironsworn/Starforged-inspired game mechanics
- Skeleton + Phase system for reload-free auth flow
- TTS (EdgeTTS online / Chatterbox offline with voice cloning) and STT (Whisper)
- Multi-user support with invite code system
- HTTPS/SSL support (auto-generated certificates)
- PWA support (iOS homescreen)
- Mobile optimization (safe areas, touch targets, iOS Safari workarounds)
- Kid-friendly mode (ages 8–12)
- 20+ narration languages
- Character creation with draft system
