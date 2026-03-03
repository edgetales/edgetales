# Changelog

All notable changes to EdgeTales are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [0.9.30]

### Added
- **Auto-Dependency Check & Install:** `_ensure_requirements()` runs at the very top of `app.py` before any package imports. Checks all 8 required packages via `importlib.import_module()` and auto-installs missing ones via pip. Retry with `--break-system-packages` for externally-managed Python environments (Raspberry Pi OS, Debian 12+). Exits with manual install instructions if both attempts fail
- **Verbose Startup Output:** Console shows `⚙️ Checking dependencies ...` immediately on launch with per-package status (name + version), optional package hints, and install progress. Eliminates the previous silent black screen during import phase
- **Deferred Dependency Logging:** Since the engine logger isn't available before imports, check results are stored in `builtins._EDGETALES_DEP_CHECK` and flushed to the log file as `[Deps]` entries immediately after engine import. Cleaned up after flush
- **Chatterbox Missing Hint Card:** Amber warning card in TTS settings when Chatterbox backend is selected but not installed. Shows install command (`pip install chatterbox-tts`) and requirements (Python 3.10–3.11 + PyTorch). Fully localized via three new i18n keys (`settings.cb_not_installed`, `settings.cb_install_cmd`, `settings.cb_requires`)

### Changed
- **`cryptography`, `faster-whisper`, `nameparser` are now required:** Previously optional with graceful fallbacks, these three packages are now auto-installed alongside the core dependencies. Only `chatterbox-tts` (+ PyTorch) remains truly optional
- **Dependency categories simplified:** 8 required packages (anthropic, nicegui, reportlab, edge-tts, stop-words, nameparser, cryptography, faster-whisper) + 1 optional (chatterbox-tts)

---

## [0.9.29]

### Added
- **NPC Duplicate Detection via Description:** New `_description_match_existing_npc()` catches duplicates when names have zero word overlap but descriptions match (e.g., "Sächsischer NVA-Kommandant" → "Hauptmann Rolf Ziegler"). Features: exact word overlap + substring matching for typos, hyphen-part decomposition for compound words ("NVA-Kommandant" → "NVA" + "Kommandant"), long compound bonus (≥10 char distinctive terms count 1.5×). Threshold: ≥25% overlap ratio OR any long match with effective score ≥1.5. Called in `_process_new_npcs` after fuzzy name match fails, before creating a new NPC
- **NPC Seed Memory on Discovery:** `_process_new_npcs()` now auto-creates a seed memory entry for every newly discovered NPC, using their description text and disposition-derived emotional weight. Prevents "hollow NPCs" with zero memories when the Narrator forgets `<memory_updates>` for characters it just introduced via `<new_npcs>`. Seed importance is scored normally (with `_score_debug: "auto-seed from new_npcs"`) and floored at 3
- **Narrator Location & Time Update Tags:** Two new optional metadata tags `<location_update>` and `<time_update>` in both dialog and action narrator prompts. Parser extracts them to update `game.current_location` and `game.time_of_day` — fixes frozen locations during narrative movement (e.g., takeoff/flight sequences) and stuck time progression despite explicit in-narration time jumps
- **NPC Description Updates via `<npc_details>`:** Narrator prompt schema expanded: `<npc_details>` now accepts optional `"description"` field alongside the existing `"full_name"`. Enables mid-game description corrections when a character's role changes (e.g., "Mech-Kampfpilotin" → "ehemalige Pilotin, jetzt Mechanikerin"). Parser applies updates to existing NPCs and logs changes

### Improved
- **Story Architect upgraded to Sonnet:** `call_story_architect()` now uses `NARRATOR_MODEL` (Sonnet) instead of `BRAIN_MODEL` (Haiku). Called once per game/chapter start (~$0.01 per call — negligible vs. ongoing narrator costs), but the quality of the blueprint shapes the entire story arc, pacing, and revelations. Haiku struggled with the complex nested JSON structure + foreign-language requirement, silently producing generic fallback blueprints
- **Story Architect diagnostic logging & retry:** All three previously silent failure paths now log detailed diagnostics: no JSON in response (logs first 300 chars), JSON parse + repair both failed (logs error + raw JSON head), JSON valid but missing `acts`/`central_conflict` (logs present keys). Two-attempt retry loop before falling through to context-aware fallback. `max_tokens` increased 1000 → 1200
- **Story Blueprint fallback localization:** Fallback blueprints now use language-aware text via `_fb_texts` dict — German act titles ("Erste Schatten", "Eskalation", "Die Entscheidung"), goals, and endings for German narration; English for all other languages. Location/genre strings shortened to first 40/30 chars to prevent ugly concatenation artifacts in fallback text
- **Keyword generation overhaul:** Removed agenda text from keyword sources entirely — generic goal verbs ("eindämmen", "überleben", "funktionsfähig") caused false-positive NPC activation. Keywords now derived exclusively from: name parts + aliases + capitalized proper nouns from description. Cap reduced 20 → 8 per NPC (fewer = less noise). ~165 RPG-specific German stopwords added (capitalized nouns that pass the library filter: "Wohngebiete", "Blockade", "Bedrohung", "Uniform", "Waffe" etc.). Name titles filtered via `_NAME_TITLES` set ("hauptmann", "major", "kommandant" etc.). Keywords always regenerated on load — they're derived data, so algorithm improvements apply retroactively to existing savegames
- **Emotion taxonomy:** Added `"urgent": 5` to `IMPORTANCE_MAP` (Tier 5, alongside `determined`). Fixed German emotion mappings: `"dringend"` and `"dringlich"` now correctly map to `"urgent"` via `_EMOTION_DE_EN` (were incorrectly mapped to `"desperate"`, causing Tier 9 over-scoring)

### Changed
- `call_story_architect()` uses `NARRATOR_MODEL` (Sonnet) instead of `BRAIN_MODEL` (Haiku)
- `_auto_generate_keywords()`: agenda text no longer used as keyword source; cap 20 → 8; ~165 RPG stopwords added
- Keywords regenerated on every save load (derived data, not persisted algorithm state)
- **New optional dependency:** `nameparser` (`pip install nameparser`) — provides 619 English name titles for NPC keyword filtering. Graceful fallback to ~60 manual titles if not installed

---

## [0.9.28]

### Added
- **Savegame Diagnostics:** Three new diagnostic fields in session_log for post-game analysis:
  - `director_trigger`: Why the Director ran (`"miss"`, `"chaos"`, `"new_npcs"`, `"reflection:Name"`, `"phase:climax"`, `"interval"`) — or absent if skipped
  - `npc_activation`: Per-NPC activation details (`{score, reasons[], status}`) showing exactly why each NPC was/wasn't included in the prompt
  - `_score_debug` on memory observations: How the importance score was derived (`"direct:terrified=7"`, `"de2en:verzweiflung→devastated=9"`, `"+event:death≥7"`)
- **Director fills empty NPC profiles:** Mid-game NPCs created via `<new_npcs>` (which lack agenda/instinct) now get `needs_profile="true"` flag in `<reflect>` tags. Director suggests agenda + instinct on first reflection. Applied only when fields are empty — never overwrites existing data
- **Director dual-tone system:** Reflections now carry two emotional fields: `tone` (1-3 word narrative compound like `"protective_guilt"`, `"reluctant_trust"`) for story arc nuance, and `tone_key` (single word from fixed enum) for machine-readable classification. Director prompt provides explicit guidance with examples for evolving emotional arcs across reflections
- **Reflect tag `last_tone` attribute:** Director receives the previous reflection's emotional tone in `<reflect>` tags, enabling deliberate emotional arc evolution (e.g. `protective_guilt` → `complicit_resignation` instead of repeating `guilty` → `guilty`)

### Improved
- **Importance scoring robustness:** `score_importance()` now handles compound phrases (`"Angst und Verzweiflung"`), snake_case (`"moral_reckoning"`), and German emotional words via `_EMOTION_DE_EN` mapping (~65 entries). Splits on `und`/`and`/`gemischt mit`/`_`/`,`, scores each token independently, takes highest. Savegame analysis showed 95% of observations stuck at default importance 3 — now 68% score correctly
- **Narrator emotional_weight format enforcement:** Both dialog and action prompts now instruct `"emotional_weight": "ONE English word: neutral|curious|wary|angry|..."` instead of free-form `"emotion"`. Prevents German compound phrases and mixed-language weights
- **Director anti-echo reflections:** `<reflect>` tags now include `last_reflection="..."` attribute (max 200 chars, escaped) and `last_tone="..."`. Task instruction: "Write a NEW insight that builds on, deepens, or contradicts it. Do NOT repeat the same theme." Savegame analysis showed 6-8 near-identical reflections per NPC
- **NPC keyword stopwords — library-based:** Replaced 72 hardcoded DE+EN stopwords with `stop-words` library (1,584 words DE+EN combined, 22× coverage). Language-aware: `_get_keyword_stopwords("French")` dynamically loads and caches French stopwords alongside DE+EN base. Supports all 18 EdgeTales narration languages except Thai. Graceful fallback to built-in set if library not installed
- **Reflection scene tracking:** Reflections now store `game.scene_count` instead of `None`, enabling proper recency scoring in `retrieve_memories()`
- **Brain null-safety:** `call_brain()` sanitizes all string fields after JSON parsing — `null` values become empty strings. Prevents `TypeError` in downstream joins and concatenations

### Changed
- `_should_call_director()` returns reason string (`Optional[str]`) instead of `bool` — enables `director_trigger` logging without additional logic
- `activate_npcs_for_prompt()` returns 3-tuple `(activated, mentioned, activation_debug)` instead of 2-tuple
- `score_importance()` accepts optional `debug=True` parameter → returns `(score, explanation)` tuple
- `_auto_generate_keywords(npc, narration_lang="")` accepts optional narration language for language-aware stopword filtering
- **New dependency:** `stop-words` (`pip install stop-words`) — zero-dependency, 156KB, lazy-loaded per language

---

## [0.9.27]

### Added
- **Chapter Archives:** Separate JSON files per chapter (`chapters/<save>/<chapter_N>.json`) preserve full chat history when starting a new chapter. Read-only replay via sidebar inside the active save card — vertical list with "Chapter N — Title". Viewing mode renders archived messages with a banner + "Back to game" button, disabled input, and per-chapter PDF export. Cleanup on save deletion, new game, and full restart
- **Chaos Interrupt UI Indicator:** `⚡ Chaos!` shown in dice display line (simple + detailed mode) alongside existing match/position indicators. CSS `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` on `.dice-simple` prevents line wrapping on narrow screens
- **Epilogue Scene Marker:** Epilogue now gets a proper `scene_marker` entry before the narration message, enabling two-step scroll targeting and visual separation in chat
- **Chat Bottom Padding:** `padding-bottom: 5rem` on `.chat-scroll` across all three breakpoints (desktop, tablet, small mobile) prevents last chat content from hiding behind the fixed footer

### Fixed
- **Critical: Epilogue/Game-Over card never appeared during gameplay.** `render_epilogue()` and `render_game_over()` only ran on page load, but `process_player_input()` never triggered a reload after `story_complete` or `game_over` was set. Fix: auto-reload after TTS completes when these flags are newly active
- **Closure bug in chapter archive buttons:** `sname` from outer save-list loop was captured by reference, causing chapter loads to search in the wrong save directory. Fix: capture via default argument `sn=sname`

---

## [0.9.26]

### Improved
- **NPC name wrapping in sidebar:** Long NPC names now wrap with a hanging indent — second line aligns under the name text, not under the disposition bubble (CSS `text-indent` + `padding-left` on `.q-item__label`)
- **Sidebar swipe-to-close:** Added Quasar `swipeable` prop to left drawer — sidebar can be dismissed with a left swipe gesture on mobile (opening via edge-swipe not feasible due to iOS system gesture conflict)

---

## [0.9.25]

### Added
- **Expanded Chaos Interrupts (10 types):** Researched Mythic GME Event Focus Table, Ironsworn/Starforged oracles, and screenwriting theory (McKee's "Crisis", Aristotle's Peripeteia, Snyder's beat sheet). 6 new interrupt types: `environment_shift` (dramatic environmental change), `remote_event` (off-screen news), `positive_windfall` (lucky break — prevents "chaos = only bad"), `callback` (past decisions echo forward), `dilemma` (forced choice between competing values, no clean option), `ticking_clock` (sudden time pressure). Type-specific narrator instructions for dilemma, ticking_clock, and positive_windfall

### Fixed
- **Chapter-start scroll bug:** New chapter scrolled to bottom instead of scene start, with bounce effect on manual scroll. Cause: missing scene marker in `_make_chapter_action()` — `render_chat_messages()` returned no `last_scene_id`, so two-step scroll only executed the "scroll to bottom" half. Fix: scene marker inserted as first message element, matching the game-start flow

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
