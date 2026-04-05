# EdgeTales — Project Briefing

> Changelog → `CHANGELOG.md` | User Docs → `README.md` | Source → GitHub: edgetales/edgetales

---

## Quick Reference

| | |
|---|---|
| **Version** | v0.9.90 |
| **Codebase** | ~13,600 lines across 5 source files + config |
| **Stack** | Python 3.11+, NiceGUI, Anthropic SDK (Structured Outputs), reportlab, edge-tts, faster-whisper, wonderwords, stop-words, nameparser, cryptography |
| **AI Models** | Narrator/Architect: `claude-sonnet-4-6` · Brain/Director/Extractors: `claude-haiku-4-5-20251001` |
| **Core Principle** | "AI narrates, dice decide." — All outcomes determined by dice rolls, never by AI judgment |
| **Start** | `python app.py` → `http://localhost:8080` (requires `config.json` with `api_key`) |
| **ENV Overrides** | `ANTHROPIC_API_KEY`, `INVITE_CODE`, `ENABLE_HTTPS`, `SSL_EXTRA_SANS`, `PORT`, `DEFAULT_UI_LANG` |

Auto-install: `_ensure_requirements()` checks and installs 9 mandatory packages on startup. Chatterbox (TTS offline/voice cloning) remains optional — shown as info card in Settings if not installed.

---

## Working Contract

*Explicit instructions for Claude when working on this project. These rules apply every session.*

### Language Rules
- **Lars communicates in German** — respond in German
- **All code, comments, docstrings, CHANGELOG, README, and this file = English**
- German UI strings live in `i18n.py` — never hardcode German text in Python logic
- When discussing code in chat, use English identifiers/function names naturally (no translation needed)

### Session Workflow
1. **Analyze first** — read the relevant code/file section before proposing solutions. For bugs: ask for savegame or log upload if the root cause is unclear.
2. **Discuss if non-trivial** — if the approach has architectural implications, align before coding.
3. **Implement surgically** — use `str_replace` for targeted edits. Full file output only if Lars explicitly asks or if >30% of the file changes.
4. **Syntax-check** — verify Python syntax mentally after every code change.
5. **Session end (mandatory)** — update `CHANGELOG.md` + `PROJECT_BRIEFING.md` (see below).

### Editing Rules
- **`str_replace` is preferred**: Target the exact function or section. Never modify unrelated code.
- The `old_str` parameter must match the raw file content exactly (whitespace included) — always `view` the file immediately before editing.
- **Version strings** in `engine.py` and `README.md` are updated manually by Lars — do not touch them.
- After a successful `str_replace`, earlier `view` output of that file is stale — re-view before further edits.

### Mandatory Session-End Steps
Every session that changes code or architecture **must** end with both of these:

1. **`CHANGELOG.md`**: Add to the existing version entry if the change belongs to the current release. Use the "Keep a Changelog" format (Added / Changed / Fixed). English only. Entries should be self-contained — someone reading the changelog cold should understand the change. **`elvira/` changes are never logged here** — Elvira is an internal-only test tool, not part of the public GitHub repository, and must not appear in public-facing release notes.
2. **`PROJECT_BRIEFING.md`**: Reflect any architectural, behavioral, or API changes. Update the version number in Quick Reference.

### Multi-Language Requirement ⚠️
Every UI change must account for **both** languages — without exception:
- Add/update `i18n.py` keys for **both** `de` and `en`
- Add/update ARIA labels in both languages
- No UI string may be hardcoded — all strings go through `t(key, lang)`
- Lars enforces this strictly — a PR without both languages is incomplete.

### NiceGUI / DOM Rules (Hard-Won Lessons)
- **Vue DOM reconciliation**: `ui.markdown()` uses `v-html` — JavaScript DOM mutations (innerHTML patching, TreeWalker, MutationObserver) are **silently overwritten** on every re-render. Server-side Python post-processing is the only reliable approach for markup injection.
- **DOMPurify sanitization**: `sanitize=True` (default) strips injected `<span>` tags. DOMPurify runs inside Vue's `v-html` pipeline — it cannot be bypassed from Python, neither via a non-existent `sanitize=False` parameter on `ui.markdown()` nor via `ui.html()` (same pipeline). The only reliable way to inject spans post-render is JS DOM manipulation, as used by `_etHighlight()`. Dialog highlighting therefore uses server-side `***Markdown***` instead of span injection. **Never use `<span class="sr-only">` prepended to `ui.markdown()` strings** — spans are stripped, text stays visible. `ui.html()` wraps in a block `<div>` so `position: absolute` spans bleed visibly. **Correct pattern for screen-reader role attribution: `aria-label` on the container** (`.props('aria-label="..."')`).
- **Desktop Quasar drawer**: `ui.html()` innerHTML inside a persistent drawer strips `class=` and `style=` attributes on child elements. Use `ui.element()` with `.style()` chain instead.
- **Touch tooltips**: `ui.tooltip()` is unreliable on touch — use `_info_btn()` (click-to-dismiss `ui.menu()`) for settings UI.

### Architectural Caution
- Do not add architecturally invasive features without discussing trade-offs first (see Design Decisions section for precedent)
- The NPC system is multi-layered — changes to one layer often cascade to others
- Token budget constants are named module-level constants — never inline values; German uses ~15–20% more tokens than English

---

## Architecture

### 5-File Structure

```
engine.py        (~7,600 L) — GameState, mechanics, all AI calls, prompts, parser,
                              save/load, NPC/memory/director, chapter archives, correction system
app.py           (~3,540 L) — NiceGUI UI layer (sole NiceGUI dependency), auto-dependency
                              check, ARIA accessibility
i18n.py          (~1,400 L) — UI strings, emojis, label dicts, voice options, translation
                              functions, ARIA labels
voice.py           (~590 L) — EdgeTTS, Chatterbox, VoiceEngine, STT (faster-whisper)
custom_head.html   (~450 L) — CSS, meta tags, PWA, Google Fonts (Inter + Cinzel), CSS
                              variable system, EdgeTales Design Mode CSS, entity-highlight JS
```

**Key design principle**: `engine.py`, `voice.py`, and `i18n.py` have zero NiceGUI imports — framework-independent. Easy to test and swap frontend.

**Config/data layout**:
```
config.json                         — Server config (api_key, invite_code, etc.), chmod 600
config.example.json                 — Git-safe template
users/<n>/settings.json             — Per-user settings (language-neutral codes)
users/<n>/saves/<name>.json         — Save slots
users/<n>/saves/chapters/<name>/    — Chapter archives (chapter_1.json, chapter_2.json, ...)
```

### Framework Decoupling via Dataclasses

```python
@dataclass
class EngineConfig:
    narration_lang: str = "Deutsch"   # Display label → LANGUAGES dict → "German" for AI prompts
    kid_friendly: bool = False

@dataclass
class VoiceConfig:
    tts_enabled: bool = False
    stt_enabled: bool = False
    tts_backend: str = "edge_tts"
    voice_select: str = ""            # Voice ID; resolved via resolve_voice_id()
    tts_rate: str = "+0%"
    cb_device: str = "Auto"
    cb_exaggeration: float = 0.5
    cb_cfg_weight: float = 0.5
    cb_voice_sample: str = ""
    whisper_size: str = "medium"
    narration_lang: str = "German"
```

All AI calls receive `config: EngineConfig`. Voice functions receive `config: VoiceConfig`. The UI creates and manages config objects.

---

## Testing & Diagnostics — Elvira Bot

**Elvira** is a headless AI test player that drives `engine.py` directly, bypassing NiceGUI entirely. It lives in `elvira/elvira.py` and is configured via `elvira/elvira_config.json`. It uses Claude Haiku as the player brain and imports the engine like any other Python module.

**Purpose**: Generate realistic savegames and session logs for bug analysis without manual play. Run before/after engine changes to catch regressions.

> ⚠️ **Internal only.** The `elvira/` directory is excluded from the public GitHub repository and must never appear in `CHANGELOG.md`. Elvira changes are not release notes.

### File layout

```
elvira/
├── elvira.py               — Bot entry point and all session logic
├── elvira_config.json      — Configuration (style, genre, chapters, logging flags)
├── logs/
│   └── elvira_engine_YYYY-MM-DD.log  — Raw engine log (redirected from rpg_engine logger)
└── elvira_session.json     — Primary diagnostic output (see below)
```

The engine log is redirected to `elvira/logs/` by pre-registering a handler on the `rpg_engine` logger before `engine.py` is imported — this keeps Elvira's output out of the shared project `logs/` directory. Elvira reads the API key from `config.json` at the project root (same file as the main app) — not from an environment variable.

### Usage

```bash
python elvira/elvira.py                        # runs with elvira_config.json
python elvira/elvira.py --auto                 # Claude picks all game parameters freely
python elvira/elvira.py --turns 30             # override max turns per chapter
python elvira/elvira.py --config other.json    # custom config
```

### Session structure (`run_session()`)

Elvira's main function runs in three sequential phases:

**Phase 1 — Game Setup**: Resolves all config values. In `auto_mode`, calls Haiku once (`decide_auto_setup()`) to freely choose genre/tone/archetype/wishes via `AUTO_SETUP_PROMPT` (JSON-only response). In normal mode, reads parameters from `game` config section. Then calls `start_new_game()` or `load_game()` (when `game.load_existing = true`). When loading an existing save, the last assistant message in `chat_messages` is used as the seed narration for the first turn.

**Phase 2 — Chapter loop**: Outer `for chapter in range(max_chapters)` loop drives multi-chapter runs. Inner turn loop calls the 13-step turn sequence (see below). When a chapter ends with `bp_story_complete = True` and another chapter follows: `generate_epilogue()` → `save_chapter_archive()` → `save_game()` → `start_new_chapter()`. When a chapter ends for any other reason (`max_turns_reached`, `game_over`, error), the outer loop breaks immediately.

**Phase 3 — Wrap-up**: Prints session summary to stdout, writes final save, writes `elvira_session.json`.

### Turn loop (13 steps)

Each turn executes these steps in order:

1. **Bot action** — `ask_claude(persona, context, max_tokens=500)` with the style persona as system prompt and `build_turn_context()` output as user message. Uses `BRAIN_MODEL` (Haiku).
2. **Engine** — `process_turn(client, game, action, config)` → `(game, narration, roll, burn_info, director_ctx)`.
3. **Momentum burn** — if `burn_info` is not None and `burn_setting != "never"`: `aggressor` style always burns; all others call `decide_burn_momentum()` (Haiku, max_tokens=10, "yes"/"no"). On burn: `process_momentum_burn()`, replace last `chat_messages` entry, write `turn_record["roll"]["burn_result"]`.
4. **Director** — `run_deferred_director(client, game, director_ctx)` **called synchronously** — unlike the UI which runs this as an async background task, Elvira blocks until the Director completes. This ensures Director guidance and NPC reflections are always captured in the same save that triggered them.
5. **State snapshot** — `state_after`: health, spirit, supply, momentum, chaos, scene, location, time_of_day, scene_context, npc count (active+background only), active clock count.
6. **NPC snapshot** — full state for every active+background NPC: id, name, status, disposition, bond, agenda, instinct, arc, memory_count, last_memory text (100 chars), aliases.
7. **Clock snapshot** — all clocks including fired: name, clock_type, filled, segments, owner, fired.
8. **Director guidance** — captured from `game.director_guidance`: narrator_guidance, pacing, arc_notes.
9. **Engine log** — mirrors `game.session_log[-1]`: rich_summary, move, position, effect, dramatic_question, chaos_interrupt, director_trigger, consequences, clock_events, npc_target, npc_activation. Conditional keys (omitted when empty): `warnings` (engine-level warnings, e.g. unresolved social-move target), `revelation_check` (only when a revelation was pending that turn), `act_transitions` (only when an act transition was recorded that turn).
10. **Story arc** — current act phase/title/goal/mood + story_complete flag via `_get_current_act(game, bp)`.
11. **Invariant checks** — `assert_game_state()` verifies: `health` ∈ [0,5], `spirit` ∈ [0,5], `supply` ∈ [0,5], `chaos_factor` ∈ [1,9], `momentum ≤ max_momentum`, `scene_count ≥ 1`, `chapter_number ≥ 1`, `game.npcs` is list, `game.clocks` is list. Violations appended to `session_log["violations"]` and `turn_record["violations"]`.
12. **Periodic save** — `save_game()` every `save_every_n_turns` turns (default 5). Runs after Director so NPC reflections are included.
13. **Terminal conditions** — break inner loop on `game.game_over` or `bp_story_complete`.

### Bot styles

`explorer`, `aggressor`, `dialogist`, `chaosagent`, `balanced` — set via `bot_behavior.style` in config. Personas are in English with "write in narration language" so the bot respects `narration_lang`. `chaosagent` is best for stress-testing edge cases (one-word inputs, very long inputs, unexpected actions). The `aggressor` style skips the Haiku burn-decision call and always burns momentum.

### What the bot sees each turn (`build_turn_context()`)

```
TURN N - Scene N

--- LATEST NARRATION ---
[full previous narrator response]
--- END NARRATION ---

CHARACTER : [name]
Location  : [current_location]
Time      : [time_of_day]

STATS     : Edge N | Heart N | Iron N | Shadow N | Wits N
RESOURCES : Health N/5 | Spirit N/5 | Supply N/5 | Momentum N/N
CHAOS     : N  |  Chapter N
STORY PHASE : Act N/N - [title] (Scene N-N)   ← only when blueprint exists
CENTRAL CONFLICT: [first 120 chars]           ← only when blueprint exists

ACTIVE NPCs:
  - [name] [disposition]
BACKGROUND NPCs:
  - [name]
ACTIVE CLOCKS:
  - [name]: N/N ticks
```

### Complete config reference (`elvira_config.json`)

```jsonc
{
  "username": "elvira",          // save slot owner — creates users/elvira/ on first run

  "auto_mode": false,            // true → Haiku picks all game parameters freely

  "game": {
    "load_existing": false,      // true → load save_name instead of creating new game
    "save_name": "autosave",     // save slot to load (only used when load_existing=true)

    // New-game parameters (ignored when load_existing=true or auto_mode=true):
    "genre":         "...",      // genre code or free-form string
    "tone":          "...",      // tone code
    "archetype":     "...",      // archetype code or "custom"
    "wishes":        "...",      // 1-2 sentences: desired story moments
    "content_lines": "",         // content restrictions (passed to engine)
    "custom_desc":   "..."       // character concept (used when archetype="custom")
  },

  "session": {
    "max_chapters":        1,         // chapters to play; each triggers epilogue+transition
    "max_turns":           15,        // max turns per chapter (overridable via --turns)
    "narration_lang":      "Deutsch", // narration language passed to EngineConfig
    "save_every_n_turns":  5,         // periodic save frequency
    "save_name_output":    "autosave",// save slot for output (can differ from load slot)
    "clean_before_run":    false      // delete old save + archives before starting
  },

  "bot_behavior": {
    "style":          "balanced",     // explorer|aggressor|dialogist|chaosagent|balanced
    "burn_momentum":  "auto"          // always|never|auto (auto = Haiku decides)
  },

  "logging": {
    "log_file":               "elvira_session.json", // output path relative to elvira/
    "print_full_narration":   false,  // true → full narrator text to stdout
    "print_roll_details":     true,   // false → suppress [ROLL] lines
    "assert_state_invariants": true   // false → skip invariant checks (faster runs)
  }
}
```

### `elvira_session.json` — primary diagnostic file

This is the authoritative analysis artifact — a complete turn-by-turn audit trail. Use this for diagnosis; the savegame is only needed to reload and continue play.

**Top-level fields:**
- `engine_version` — exact version string when the session ran
- `config` — full elvira_config.json snapshot (reproducibility)
- `style`, `auto_mode`, `max_chapters`
- `started_at`, `ended_at`, `total_turns`
- `character`, `location_start`, `opening_narration`
- `game_context` — genre, tone, archetype, wishes, all five stats (correctly populated even in auto_mode)
- `story_blueprint` — the Architect's full narrative plan: structure_type, central_conflict, antagonist_force, thematic_thread, acts[] (phase/title/goal/mood/scene_range/transition_trigger), possible_endings
- `chapters[]` — per-chapter summary: chapter, started_at_turn, turns_played, ended_reason
- `violations[]` — all invariant violations across the session (format: `[TURN N] INVARIANT VIOLATION: ...`)
- `ended_reason` — one of: `story_complete`, `game_over`, `max_turns_reached`, `max_chapters_reached`, `epilogue_error`, `chapter_transition_error`, `engine_error`, `bot_error`, `complete`
- `final_state` — character, chapter, location, scene, health, spirit, supply, momentum, chaos, npcs, active_clocks

**Per-turn fields** (`turns[]`):
- `turn`, `chapter`, `scene`, `location`
- `action` — what the bot-player typed
- `narration` — full narrator response (not truncated)
- `narration_excerpt` — first 300 chars (newlines collapsed) for quick scanning
- `roll` — stat, **d1** (first action d6), **d2** (second action d6), total (`action_score` = min(d1+d2+stat, 10)), c1, c2, result, match (bool). `burn_result` added when burn was taken (the upgraded result, e.g. `STRONG_HIT`) — `result` keeps the original dice outcome for mechanical accuracy.
- `burn_offered` — the upgrade result that was available (e.g. `"STRONG_HIT"`), or absent if no burn was possible
- `burn_taken` — bool; absent if no burn was offered
- `burn_error` — error string if `process_momentum_burn()` raised
- `director_ran` — bool; `director_error` present on failure
- `state_after` — health, spirit, supply, momentum, chaos, scene, location, time_of_day, scene_context, npcs (count of active+background), clocks (count of unfired)
- `npcs[]` — snapshot of every active+background NPC: id, name, status, disposition, bond, agenda, instinct, arc, memory_count, last_memory (100 chars), aliases
- `clocks[]` — all clocks including fired: name, clock_type, filled, segments, owner, fired
- `director_guidance` — narrator_guidance, pacing, arc_notes; absent when Director did not run
- `engine_log` — mirrors `game.session_log[-1]`: summary (rich_summary or summary), move, position, effect, dramatic_question, chaos_interrupt, director_trigger, consequences[], clock_events[], npc_target, npc_activation. Conditional keys omitted when empty: `warnings` (e.g. unresolved social-move target), `revelation_check` (when a revelation was pending), `act_transitions` (when an act transition fired this turn)
- `story_arc` — phase, title, goal, mood, story_complete. Phase via `_get_current_act(game, bp)`: reads `bp.triggered_transitions` — `len(triggered)` = current act index; falls back to `scene_range` before any transition fires. `story_complete` from `game.bp_story_complete` directly (not from bp dict, which may lack the key after save/load).
- `violations[]` — invariant violations for this specific turn
- `error` — error string if bot or engine raised an unhandled exception this turn

### When to use which file

| File | Use for |
|---|---|
| `elvira_session.json` | Primary analysis — everything in one place |
| `users/elvira/saves/<n>.json` | Reload in the UI to continue play, or as input for further Elvira runs (`load_existing: true`) |
| `users/elvira/saves/chapters/<n>/` | Full chat history per completed chapter (multi-chapter runs only) |
| `elvira/logs/elvira_engine_*.log` | Deep engine internals when session.json shows an error and root cause is unclear |

### Social Moves & Bond Mechanics (v0.9.86)

`SOCIAL_MOVES = {"compel", "make_connection", "test_bond"}` — all three share the MISS consequence (bond -1, spirit -1 or -2), but differ on success:

| Move | WEAK_HIT | STRONG_HIT |
|---|---|---|
| `compel` | — | bond +1 |
| `make_connection` | bond +1 | bond +1, disposition shift ↑ one step |
| `test_bond` | — | bond +1, disposition shift ↑ one step |

Disposition shift ladder (one step per trigger): `hostile → distrustful → neutral → friendly → loyal`.

**Design rationale**: `compel` is transactional — repeated successful coercion builds familiarity (bond) but not fundamental attitude (disposition). `make_connection` is relational — explicitly investing in the relationship shifts both. `test_bond` on STRONG_HIT deepens a relationship organically: surviving a crisis together is equivalent to a deliberate connection moment. `test_bond` was previously a dead move on success (no unique outcome beyond momentum) — fixed in v0.9.86. Reaching `loyal` disposition requires `make_connection` or `test_bond` — it cannot be compelled.

 The roll mechanic is:

```
action_score = min(d1 + d2 + stat, 10)   (two d6s, capped at 10)
vs. two challenge dice (each d10)
```

When the raw sum exceeds 10, the cap applies silently. Log output (since v0.9.84) shows this explicitly as e.g. `4+6+1=11→10(cap)` to prevent the result from looking like an arithmetic error. The UI dice display (`dice.action` i18n key) uses `score_display` which formats the same way.

---

## Core Systems

### Three-AI Pipeline (Deferred Director Pattern)

```
Player Input
    ↓
[Brain] (Haiku, Structured Outputs)  ─── ~300ms, ~$0.0002
    Parses input → JSON: move, stat, player_intent, target_npc,
    world_addition, position, effect, dramatic_question
    ↓
[NPC Activation]  ─── activate_npcs_for_prompt() → 3-tier context (TF-IDF)
    ↓
[Narrator] (Sonnet)  ─── ~2s, ~$0.003
    PURE PROSE ONLY — no JSON, no metadata
    Follows <director_guidance> when present
    ↓
[Metadata Extractor] (Haiku, Structured Outputs)  ─── ~300ms, ~$0.0002
    Analyzes narrator prose → guaranteed valid JSON:
    scene_context, location_update, time_update, memory_updates,
    new_npcs, npc_renames, npc_details, deceased_npcs
    ↓
[Player receives narration + TTS]  ←── IMMEDIATELY (no waiting for Director or Save)
    ↓  (after rendering + scroll, via asyncio.create_task)
[Save]  ─── save_game() — runs after display, does not block player
    ↓  (parallel, non-blocking)
[Director] (Haiku, Structured Outputs)  ─── ~$0.0003, 0ms latency for player
    Triggered ONLY on: MISS, Chaos, new NPCs, every 3 scenes
    → narrator_guidance (concrete, for next round)
    → npc_reflections (stored in NPC memory, dual tone/tone_key)
    → scene_summary (enriches session_log)
```

**Total per turn: ~$0.003–0.004, ~2.5s**

### Story Architect (Sonnet, one-time call)

`call_story_architect()` runs once at game start and once per chapter start. Uses Sonnet with Structured Outputs. Runs **in parallel** with the opening Narrator via `concurrent.futures.ThreadPoolExecutor(max_workers=2)` — halves startup wait (~15s vs ~30s). Thread-safe: Architect only needs genre/tone/setting/character (populated by Setup Brain before threads launch). In `start_new_chapter()`, the Architect thread receives a `copy.copy(game)` snapshot to prevent race conditions from `parse_narrator_response()` mutations.

**Output**: Story blueprint with `central_conflict`, `antagonist_force`, `thematic_thread`, Acts (3-act or Kishōtenketsu) with `transition_trigger` per act, revelations, and possible endings.

**3-act prompt (v0.9.78)**: Five additions bring the 3-act prompt to qualitative parity with Kishōtenketsu: (1) Explicit act definitions — Setup establishes working assumptions, Confrontation plants the reframing seed, Climax forces a perspective shift on what the conflict means. (2) Anti-escalation rule — the confrontation→climax `transition_trigger` must be a REFRAMING EVENT, not mere escalation. (3) Dual-layer `central_conflict` — SURFACE LAYER (apparent start) + HIDDEN LAYER (true meaning, emerging through Act 2). (4) `thematic_thread` structurally anchored — defined as a genuine open philosophical question with explicit act-by-act surfacing instructions. (5) Perception-shift revelation — at least one revelation must recontextualize something already seen; endings must address both external outcome and thematic question.

**Revelation pipeline (v0.9.65)**:
- `get_pending_revelations()` returns revelations eligible at current `scene_count` (not yet in `revealed`).
- `_story_context_block()` surfaces the first pending revelation as `<revelation_ready weight="...">full content</revelation_ready>` — a dedicated XML element with the **full, untruncated** content. Previously was a 80-char-truncated XML attribute, which silently dropped most of the twist.
- After narration, `call_revelation_check()` (Haiku, `REVELATION_CHECK_SCHEMA`) verifies whether the narrator actually wove the revelation in. Returns `revelation_confirmed: bool + reasoning`. `mark_revelation_used()` is gated on `True`. On extractor failure, defaults `True` (anti-loop safety).
- `revelation_confirmed` is also forwarded to `_should_call_director()` — Director is only triggered with reason `"revelation"` when the revelation was genuinely confirmed, not merely pending.
- **`revelation_check` logged in session_log (v0.9.88)**: Both dialog and action paths now write `session_log[-1]["revelation_check"] = {"id": ..., "confirmed": bool}` immediately after the check. Key is omitted entirely on turns where no revelation was pending. After a momentum burn, `process_momentum_burn()` removes this key from `session_log[-1]` — the pre-burn check result is stale (new narration not checked, revelation un-marked by snapshot restore). The revelation remains pending and will be re-checked on the next turn.

**Transition Triggers**: Each act has a `transition_trigger` (narrative condition) alongside `scene_range` (fallback). Director evaluates via `act_transition: true/false`. `get_current_act()` uses dual logic: (1) check `triggered_transitions` from blueprint, (2) fallback to `scene_range`.

**Akt-Transitions Guard + Back-fill (v0.9.61)**:
- **Final-act guard**: If `act_idx >= len(acts)-1`, Director signal is ignored (final act has no outbound trigger by design).
- **Back-fill in `_apply_director_guidance`**: When recording `act_N`, all preceding `act_i` (i < N) with exceeded `scene_range` are also written to `triggered_transitions` if not yet present — prevents gaps like `['act_0', 'act_2']`.

**`_check_story_completion` — Three-Stage Trigger (v0.9.81)**:
1. **Primary**: `penultimate_id` in `triggered_transitions` AND `scene_count >= final_end` → `story_complete = True`. Requires Director to have confirmed the transition via `act_transition: true`.
2. **Scene-range back-fill**: If primary fails AND `scene_count >= final_end`, all preceding acts whose `scene_range` is past are added to `triggered_transitions` (same logic as Director back-fill). Primary check is then re-evaluated. This handles campaigns where all Director runs were superseded by fast play and `triggered_transitions` stayed empty — which previously caused the epilogue to be permanently suppressed.
3. **Fallback**: `scene_count >= final_end + 5` → `story_complete = True` (safety net, unchanged).

### Narrative Continuity Pipeline (Chapter Transitions)

Three extensions inspired by TV series dramaturgy:
1. **Extended chapter summary**: `npc_evolutions` (projected NPC changes in time skip) + `thematic_question` (vertical emotional question carrying across chapters) + `post_story_location` (where the protagonist physically ends up at story's end — extracted from epilogue or inferred)
2. **Emotional continuity in Story Architect**: `character_growth` and `thematic_question` from previous chapters feed into blueprint input. Generates `thematic_thread` as a continuous emotional layer. Narrator receives `thematic_thread` in every `<story_arc>` tag.
3. **Chapter opening uses NPC evolutions**: `build_new_chapter_prompt()` injects `<npc_evolutions>` block from last chapter summary. Marked as projections (hints, not facts).

**Epilogue → Chapter Continuity (v0.9.67)**: When a player generates an epilogue and then starts a new chapter, the chapter summary and opening now reflect the story's actual conclusion rather than the mid-action state:
- `GameState.epilogue_text: str = ""` — **persisted in `SAVE_FIELDS`**. Stores the generated epilogue prose so it survives `ui.navigate.reload()` (which clears `app.storage.tab`) between epilogue generation and the "New Chapter" button click. `generate_epilogue()` writes to it; `start_new_chapter()` consumes and clears it (`game.epilogue_text = ""`) after `call_chapter_summary()` so it cannot bleed into chapter-3 summaries.
- `generate_epilogue()` writes to `game.epilogue_text` after generating.
- `call_chapter_summary(epilogue_text="")` — optional parameter. When non-empty, injects the epilogue as an authoritative `<epilogue>` block in the Haiku prompt. Summary, `unresolved_threads`, and `character_growth` are derived from the post-epilogue state. `CHAPTER_SUMMARY_OUTPUT_SCHEMA` includes `post_story_location` (string).
- `start_new_chapter()` reads `game.epilogue_text`, passes it to `call_chapter_summary()`, then sets `game.current_location = chapter_summary["post_story_location"]` before building the chapter-2 opening prompt. Fallback: if `post_story_location` is empty, location is unchanged.

### Director Trigger System (`_should_call_director()`)

Returns reason string (`Optional[str]`) or `None`. Reasons: `"miss"`, `"chaos"`, `"new_npcs"`, `"revelation"`, `"reflection:<NPC-Name>"`, `"phase:<phase>"`, `"interval"`. Stored in `session_log[-1]["director_trigger"]` for diagnostics. Typical: 5–7 Director calls per session.

Phase trigger list: `"climax"`, `"resolution"` (3-act finale), `"ten_twist"` (Kishōtenketsu twist), `"ketsu_resolution"` (Kishōtenketsu finale v0.9.61).

**Phase-trigger deduplication (v0.9.89)**: `phase:` triggers fire at most once per phase per chapter. When `_should_call_director()` would return `phase:X`, it first checks `story_blueprint["triggered_director_phases"]`. If `X` is already listed, the trigger is suppressed and evaluation falls through to the `interval` check. When a `phase:` trigger fires, all three callsites (action path, dialog path, `process_correction()`) immediately append the phase key to `triggered_director_phases`. `_build_turn_snapshot()` captures this list as `bp_triggered_director_phases`; `_restore_from_snapshot()` restores it — so a `##` correction on the trigger turn un-marks the phase, allowing it to re-fire on the corrected turn. Old saves without the key behave correctly: the field defaults to `[]`, and the phase fires once on the next qualifying turn.

**Director Race Condition Guard (v0.9.58)**: `_director_gen` session counter, incremented at each turn start in `process_player_input()`. Background Director task checks twice: (1) before API call — skips if new turn already running; (2) before `save_game()` — prevents overwriting a newer save.

**Director Alias-Awareness (v0.9.46)**: `build_director_prompt()` shows NPC aliases in NPC list (`aka ...`) and in `<reflect>` tags (`aliases="..."` attribute). `DIRECTOR_SYSTEM` instructs: aliases = same person, use primary name consistently.

**Lore NPC Status (v0.9.67)**: New `"lore"` status for narratively significant figures who are never physically present (dead mentors, missing persons, historical figures). Registered via `_process_lore_npcs()` from `lore_npcs` Metadata Extractor field. Lore NPCs: collect memories via `memory_updates`, appear in `<lore_figures>` narrator context block (name + 80-char description), excluded from `<known_npcs>` and NPC activation/agency, do not count against `MAX_ACTIVE_NPCS`. Sidebar renders them under "Known Persons" identically to `background`. Transition `lore → active` via `_reactivate_npc()` — happens automatically when the figure physically appears. All dedup paths recognise `lore` status. `valid_statuses` in correction-ops includes `"lore"`.

**Director Language Enforcement (v0.9.67)**: The `<task>` block opens with a hard `LANGUAGE RULE` that forbids any partial English, even mid-sentence, when the narration language is non-English. Per-field `in {lang}` instructions remain as secondary reinforcement.

**Clocks in Director (v0.9.59)**: Director receives `<clocks>` block with name, type, visual fill bar (`█░`), ratio, percent, trigger text. `DIRECTOR_SYSTEM` instructs Director to reference clocks in `arc_notes` / `narrator_guidance` when ≥50% filled or recently ticked.

**`_apply_director_guidance()` — Two Agenda/Instinct Paths**:
- `agenda`/`instinct`: fills **only empty fields** (`needs_profile="true"` NPCs)
- `updated_agenda` (v0.9.61, updated v0.9.90): **actively overwrites** when non-null — for NPCs whose goals fundamentally changed (defeat, betrayal, revelation). Director prompt explains when to use update vs. leave null.
- `updated_instinct` **removed (v0.9.90)**: was overwritten on nearly every Director call, destroying instinct stability (session analysis: 13 versions in 15 turns for one NPC). Replaced by `updated_arc`. `instinct` field in `npc_reflections` remains for **initial fill only** (`needs_profile="true"` NPCs with empty instinct). After first fill, instinct is never updated — it is the NPC's wiring, not their mood.
- `updated_arc` **(new v0.9.90)**: narrative trajectory field, expected to evolve each reflection. 1-2 sentences from the NPC's inside perspective — what the story has made of them so far, not what they will do next. Distinct from `instinct` (stable wiring) and `npc_guidance` (ephemeral scene instruction). Exposed in `<reflect>` tag as `arc="..."` attribute. Written to `npc["arc"]` in `_apply_director_guidance()` with 300-char length guard. Shown to Narrator in `<target_npc>` and as attribute on `<activated_npc>` tags.

**Director `instinct` diversity for mid-game NPCs (v0.9.88)**: Mid-game NPCs created via `new_npcs` start with `instinct: ""` and receive their instinct from the Director on the same turn (triggered by `_should_call_director()` reason `"new_npcs"`). The Director task prompt instruction for `instinct` carries the full-spectrum diversity mandate — "calm and calculating" named as model default to avoid, concrete profiles enumerated. Note: `updated_instinct` was removed in v0.9.90; instinct is now set once and locked. The diversity mandate applies at initial-fill time via the `instinct` field (only when `needs_profile="true"`).

**act_transitions now logged in session_log (v0.9.88)**: When `_apply_director_guidance()` records a new `act_id` into `story_blueprint["triggered_transitions"]`, it now also appends that act ID to `session_log[-1]["act_transitions"]` (list, via `setdefault`). Back-filled acts (from the back-fill loop) are also logged. Key is omitted entirely on turns without a transition event. Note: `_apply_director_guidance()` runs deferred (called by `run_deferred_director()` from the UI layer after narration rendering) — `session_log[-1]` at that point refers to the turn that triggered the Director, which is correct in normal flow but subject to the same race condition as `rich_summary` if a new turn starts before the Director completes.

**Reflection-Truncation Guard & Fallback**: `_apply_director_guidance()` tracks successfully stored reflections in `successfully_reflected_ids` — populated only when a reflection passes all checks (non-empty, ends with sentence-terminating punctuation) and is written to memory. The fallback loop uses this set (not the raw `npc_reflections` list) to identify NPCs whose reflection was rejected or not produced; it resets both `_needs_reflection = False` and `importance_accumulator = 0`. Resetting the accumulator is essential: an accumulator already ≥ `REFLECTION_THRESHOLD` (30) would cause `_apply_memory_updates()` to immediately re-set the flag on the next memory addition, nullifying the fallback. Note: a truncated or empty reflection from the Director counts as "not addressed" — the NPC will re-accumulate and trigger again naturally from new scene observations.

### Post-Completion Aftermath Phase (v0.9.61)

**`_check_story_completion()` — Two-Stage Trigger (v0.9.68)**: Called at the end of every `process_turn()`. Sets `story_blueprint["story_complete"] = True` when:
1. **Primary**: The penultimate act ID (e.g. `"act_2"` in a 4-act structure) is in `triggered_transitions` (Director confirmed the final act was narratively entered) AND `scene_count >= final_act.scene_range[1]`. Final acts have no `transition_trigger` by design — the penultimate act's transition is the only reliable signal the resolution phase is underway.
2. **Fallback**: `scene_count >= final_end + 5` — safety net for games that run long without a Director-confirmed transition. The +5 buffer is intentionally generous for Kishōtenketsu structures. Once set, `story_complete` is not unset by this function (snapshot restore via `##` or momentum burn can still clear it).

`load_game()` normalizes `triggered_transitions=null`, `story_complete=null`, and `revealed=null` → key removed, so the `or []` / `.get()` defaults work correctly on older saves where the Architect returned explicit nulls.

Prior to v0.9.68, `_check_story_completion()` used a pure scene counter (`scene_count >= final_end`), which caused premature epilogue offers mid-mission before the central conflict was resolved.

When `story_complete=True` + `epilogue_dismissed=True` (player keeps playing after dismissing epilogue offer), `get_current_act()` returns a synthetic `aftermath` act. Effects:
- `_should_call_director()`: `"aftermath"` not in phase-trigger list → falls back to normal `interval` rhythm (every 3 scenes)
- `_story_context_block()`: dedicated branch → Narrator gets "follow organically, no forced conclusion"
- `DIRECTOR_SYSTEM`: explains `aftermath` as "Season 2 setup" mode (consequences, relationships, new organic tension — no forced finale)

**"Wrap Up Story" button (v0.9.61)**: Appears in menu when `story_complete && epilogue_dismissed && !epilogue_shown`. Sets `epilogue_dismissed = False`, saves, reloads → epilogue offer reappears normally.

---

### NPC System

#### NPC Status System

| Status | Sidebar | Brain/Narrator Context | Purpose |
|---|---|---|---|
| `active` | ✅ prominent | ✅ full (agenda, memories, secrets) | Currently relevant NPCs |
| `background` | ✅ dimmed, collapsed | Brain name list only (for target recognition) | Known NPCs, not currently present |
| `lore` | ✅ dimmed, collapsed (same as background) | `<lore_figures>` slim block (name + 80-char description) | Narratively significant figures never physically present (dead mentors, historical figures, off-screen handlers). Collect memories. Do not count against `MAX_ACTIVE_NPCS`. |
| `deceased` | ☠️ strikethrough, collapsed | ❌ (only `[DECEASED]` in metadata ref) | Killed NPCs — protected from all merges |
| `inactive` | ❌ | ❌ | Legacy only — migrated to `background` on `load_game()` since v0.9.14. Never set by current code. |

**Status transitions**:
- `active` → `background`: `_retire_distant_npcs()` at >MAX_ACTIVE_NPCS (12). Relevance score: `last_memory_scene + bond × 3 + current_scene_bonus (+1000)`. Current-scene bonus protects freshly introduced NPCs.
- `background` → `active`: Automatically when Brain identifies `target_npc`, Metadata Extractor recognizes new NPCs matching a known NPC, or memory updates arrive for background NPCs.
- `lore` → `active`: Via `_reactivate_npc()` when the figure physically appears in a scene (e.g. time-travel, resurrection). Registered from `lore_npcs` Metadata Extractor field by `_process_lore_npcs()`. Lore NPCs are always exempt from the scene-presence guard in `_apply_memory_updates()` — they accumulate memories regardless of whether they were activated for the current scene.
- `active`/`background` → `deceased`: `_process_deceased_npcs()` when Narrator **depicts** an on-screen death (not dialog claims). Extractor rule covers explicit deaths (collapse, killed, stop breathing), literary/physical cessation (legs stop moving, resistance ceases, body goes still — explicit death words not required), and supernatural/atmospheric finality (pulled under water, consumed, destroyed — described as irreversible). German-language examples included in prompt. Two-stage guard: (1) Extractor prompt distinguishes narrator-depicted deaths from dialog claims; (2) code guard checks `scene_present_ids` (activated + mentioned NPC IDs, v0.9.47). **Fallback: off-screen death detection (v0.9.84)**: `_check_death_corroboration()` runs at the end of `_apply_narrator_metadata()` after all memories are stored. Catches deaths the extractor's physically-witnessed rule misses (e.g. heard but not seen). Signals: (1) cross-NPC vote — another NPC's observation with `about_npc=X`, `importance >= 9`, `emotional_weight` in `{betrayed, devastated}`; (2) self-vote — NPC X's own observation with `importance >= 9`, `emotional_weight == devastated`. Threshold: ≥1 cross-NPC vote AND total ≥2. Reflections excluded (Director-generated). Known edge case: catastrophic betrayal where both sides score imp=9 can false-trigger; `##` correction resolves it. **Opening-scene death detection (v0.9.84)**: `OPENING_METADATA_SCHEMA` includes `deceased_npcs` array. Extractor uses NPC full name (not ID — IDs not yet assigned at extraction time). `_process_deceased_npcs()` called after `_process_game_data()` in `start_new_game()` and after the full merge loop in `start_new_chapter()` (so returning NPCs are reachable by name). No `scene_present_ids` guard — everything in an opening is witnessed. Known limitation: returning NPCs that die in a chapter opening cannot be listed in `deceased_npcs` (they are excluded from `npcs` by the known-NPC instruction); their death falls back to `_check_death_corroboration` in subsequent scenes.
- `deceased` → `active`: Only on exact name match in `new_npcs` or `memory_updates` (resurrection). `_reactivate_npc(force=True)` required. Fuzzy matches are blocked.

#### Two NPC Creation Paths

1. **Opening scene** (`call_opening_metadata()`, v0.9.51): Haiku Structured Outputs with full schema: name, description, agenda, instinct, secrets, disposition + clocks, location, scene_context, time_of_day. Processing in `_process_game_data()`. Replaces old inline `<game_data>` JSON that the Narrator had to fill — eliminates that error class entirely.
2. **Mid-game discovery** (Metadata Extractor `new_npcs`): Minimal schema: `{"name": "...", "description": "1 sentence", "disposition": "neutral"}`. Code fills defaults. Auto-generates seed memory from description + disposition-based emotional weight.

Both paths set `last_location = game.current_location`. Updated in `_apply_memory_updates()` — **only for NPCs in `scene_present_ids`** (physically activated) or `pre_turn_lore_ids` (lore→active transitions, not yet in `scene_present_ids` at activation time). NPCs that receive a memory update without physical presence (mentioned in dialog, remaining in a different time period) keep their existing `last_location`.

#### Six-Layer Anti-Duplicate Safety Net

1. **`npc_renames`** (Metadata Extractor) → `_merge_npc_identity()`: old name → aliases, new name → primary. Covers: spy unmasked, alias discovered, AND descriptor-named NPCs receiving a personal name (e.g. "Die Frau im Wollhut" → "Hanna"). Guards: same-name check (identical names → skip), self-alias cleanup (new name removed from aliases), `load_game()` cleans self-aliases in existing saves. **Clock-owner sync (v0.9.83)**: accepts optional `game` parameter; when provided, iterates `game.clocks` and updates any owner whose normalized form matches the old name — using `_normalize_for_match` to catch whitespace/hyphen/case drift. All 5 call sites pass `game=game`. `_absorb_duplicate_npc()` called after every rename to absorb any NPC whose primary name **or alias** matches the renamed-to name. **Richness-aware merge direction**: `original` keeps its ID, but if `dup` scores higher on richness (memory count × 2 + bond × 2 + agenda × 3 + instinct × 3 + description × 1), `dup`'s substantive fields (description, agenda, instinct, disposition, secrets, last_location) overwrite `original`'s in-place. Prevents thin descriptor-NPCs from clobbering established characters' data when renamed to a name already in use.
2. **Fuzzy name match** in `_process_new_npcs()` — substring overlap, word overlap, STT-variant matching (Levenshtein ≤ 1). Returns `(npc, match_type)`: `"identity"` for rename, `"stt_variant"` for alias-only.
3. **Description match** `_description_match_existing_npc()` — catches duplicates when names have zero word overlap but descriptions match. Word overlap + substring matching + compound decomposition (Bindestrich split) + Long-Compound-Bonus (≥12 chars count 1.5×). Threshold: ≥25% ratio OR one long match with effective ≥2.0. **Spatial Guard**: skips candidates whose `last_location` differs from `game.current_location`. **Name-Reference Guard (v0.9.48)**: words from candidate's name/aliases (≥4 chars) are filtered from the new description word set before overlap check.
4. **`_apply_memory_updates(game, json_text, scene_present_ids=None, pre_turn_npc_ids=None, pre_turn_lore_ids=None)`** — finds NPC even with unknown reference, creates stub only as last resort. Guards: `npc_\d+` pattern and player character name (part-intersection) are rejected. **Auto-stub humanization (v0.9.45)**: snake_case stub names → Title Case with spaces. **Name/alias guard (v0.9.66)**: after humanization, `_find_npc()` is called before any stub creation — if a match is found by name or alias, memory is routed to the existing NPC and no stub is created. **Presence guard (v0.9.69)**: when `scene_present_ids` + `pre_turn_npc_ids` are provided, memory updates for known NPCs absent from `scene_present_ids` are rejected. Four exemptions: (1) freshly-created NPCs (not in `pre_turn_npc_ids`); (2) auto-stubs (`pre_turn_npc_ids=None`); (3) `status="lore"` or `status="deceased"` — lore always accumulates memories, deceased are structurally excluded from `activate_npcs_for_prompt` so blocking them would prevent resurrection; (4) formerly-lore NPCs in `pre_turn_lore_ids` — lore→active transitions lose lore status before guard runs. `pre_turn_lore_ids` is captured *before* `_process_npc_renames` in `_apply_narrator_metadata` (since `_process_npc_renames → _merge_npc_identity` can promote lore→active). `_reactivate_npc` is NOT called in the `existing_by_name` stub path — it happens inside `if npc:` after the guard passes, preventing premature promotion of absent background NPCs. **Known edge case**: a background NPC promoted via `_process_npc_details → _merge_npc_identity` (identity reveal) in the same metadata cycle, but absent from `scene_present_ids`, will have its memory blocked. This is an unusual scenario (narrator spontaneously names an unmentioned background NPC) and degrades gracefully — one missed memory, no wrong memory added.
5. **`_process_npc_details()` identity-reveal fallback**: if `full_name` completely differs from current NPC name, calls `_merge_npc_identity()` instead of rejecting. Then `_absorb_duplicate_npc()` checks if `_process_new_npcs()` already created a duplicate with the new name in the same metadata cycle, and absorbs its memories/data.
6. **Slug resolution** `_resolve_slug_refs()` (v0.9.45) — runs in `_apply_narrator_metadata()` between `_process_new_npcs()` and `_apply_memory_updates()`. Converts snake_case slugs (e.g., `moderator_headset`) to real `npc_id`s for same-cycle cross-references.

**`_absorb_duplicate_npc()` match logic (v0.9.66):** matches candidate duplicates by primary name **or any alias** of the duplicate NPC — so a NPC whose primary name differs but carries the merged name as an alias is also absorbed.

#### NPC Spatial Tracking (`last_location`)

Every NPC has `last_location` (string, default `""`). Set on creation, updated in `_apply_memory_updates()` — **only for NPCs in `scene_present_ids`** (physically activated) or `pre_turn_lore_ids` (lore→active transitions). NPCs receiving memory updates without physical presence keep their existing `last_location`. Prompt builders inject spatial hints when NPC location differs from player location: `last_seen="..."` (activated NPCs) and `[at:Location]` (known NPCs). **SPATIAL CONSISTENCY** rule in Narrator prompt: NPCs at other locations cannot physically interact — they must first plausibly travel to the player.

**Fuzzy location match** (`_locations_match()`, v0.9.61): multi-word uses word-set-subset after stopword filtering; single-word uses prefix check. Applied in `_description_match_existing_npc()`, `_activated_npcs_string()`, `_known_npcs_string()`, `update_location()`.

#### NPC Name Sanitization

`_sanitize_npc_name(name)` strips bracket annotations and extracts them as aliases. Recognizes explicit alias hints (`also known as`, `aka`, `genannt`, `called`) and generic epithets. Example: `"Cremin (also known as Cremon)"` → `name="Cremin"`, `alias=["Cremon"]`. Applied at 4 NPC entry points: `_merge_npc_identity()`, `_process_npc_details()`, `_process_new_npcs()`, `_process_game_data()`. Existing saves sanitized on `load_game()`.

#### `_normalize_for_match()` — Comparison-Only Normalization (v0.9.67)

`_normalize_for_match(s)` collapses hyphens, underscores, and whitespace runs to a single space, then lowercases and strips. **Stored names are never modified** — this is purely for matching. Applied consistently across all dedup layers so `"Wacholder-im-Schnee"`, `"Wacholder im Schnee"`, and `"wacholder_im_schnee"` all compare equal.

Applied in: `_find_npc()`, `_fuzzy_match_existing_npc()` (exact-skip, substring, alias, word-overlap, STT tokenization), `_absorb_duplicate_npc()` (matching + alias merge), `_merge_npc_identity()` (same-name guard + self-alias cleanup), `_process_new_npcs()` (`existing_names` set + player-name guard), `_process_npc_details()` (extension check + alias dedup), `_process_npc_renames()` (player-name guard), `_apply_memory_updates()` (player-name guard for auto-stub creation), `_process_game_data()` (player-name NPC filter), `start_new_chapter()` (chapter-transition NPC merge loop).

#### `_find_npc()` — Alias-Aware Search

Search chain: exact ID → **normalized name** → **normalized alias** → substring name (min. 5 chars) → substring alias. Normalization via `_normalize_for_match()` — replaces the earlier bespoke underscore-normalization block.

#### Three-Tier NPC Context in Prompts

- **Target NPC** (`<target_npc>`): Fullest context via `_npc_block()` — agenda, instinct, weighted memories (separated into `insight:` reflections + `recent:` observations + `npc_views:` opinions about present NPCs), secrets, aliases.
- **Activated NPCs** (`<activated_npc />`): Medium context — name, disposition, bond, 1–2 best memories. Via `activate_npcs_for_prompt()` with TF-IDF scoring (≥0.7 score → full activation, max 3).
- **Known NPCs** (`<known_npcs>`): Compact name+disposition list. All remaining active/background NPCs.

#### NPC Description Validation

`_is_complete_description(desc)` checks if description ends with sentence-terminating character (`. ! ? " » … ) – —`). Truncation guard: `_process_npc_details()` and `_apply_director_guidance()` only overwrite existing descriptions with complete new ones. New NPCs without existing description accept any description.

---

### NPC Memory System

Each memory: `importance` (1–10), `type` (`"observation"` | `"reflection"`), `emotional_weight`, `scene`, optional `about_npc` (NPC ID or null).

**NPC-to-NPC relationships (`about_npc`)**: Optional field on any memory. When a memory primarily concerns another NPC (player tells Sophie about Bruce, Sophie observes Bruce acting), `about_npc` is set to the referenced NPC's ID. No separate relationship system — relationships emerge organically from tagged memories within the existing memory infrastructure. Extractor prompt instructs: player-initiated NPC-to-NPC communication (gossip, warnings, lies, compliments) MUST be captured as a memory with `about_npc`. **Self-reference guard (v0.9.81)**: `_resolve_about_npc()` now accepts an `owner_id` parameter — if the resolved NPC ID matches the memory's owning NPC, `None` is returned and a rejection is logged. Both call sites (`_apply_memory_updates`, `_apply_director_guidance`) pass `owner_id=npc.get("id")`.

**Weighted retrieval** `retrieve_memories()`:
```
Score = 0.40 × Recency + 0.35 × Importance + 0.25 × Relevance
```
Exponential recency decay (`0.92^scene_gap`). Reflections have floor 0.6 and store `scene_count`. Guarantees ≥1 reflection always present. Optional `present_npc_ids`: memories with `about_npc` pointing to a present NPC get +0.6 relevance boost (max 1.0).

**Consolidation** `_consolidate_memory()`: Reflections always kept (max 8), observations by budget split (60% recency + 40% importance). Total max 25 entries.

**Reflection trigger**: `importance_accumulator` incremented per memory update. At `REFLECTION_THRESHOLD` (30) → `_needs_reflection = True` → Director generates reflection (importance 8, decays slower). `_should_call_director()` picks the NPC with the **highest accumulator** as the trigger label (v0.9.81 — previously always named the first NPC in the list regardless of accumulator value). `build_director_prompt()` includes NPCs in `<reflect>` blocks under two independent conditions: (1) `_needs_reflection = True` (accumulator threshold reached), or (2) `agenda` or `instinct` is empty (`needs_profile_flag`, v0.9.87). Condition 2 operates independently of the accumulator — a peripheral NPC mentioned once in dialogue with only 1 seed memory is included as long as its profile is incomplete, without needing to reach the threshold. Once both fields are filled the NPC drops out automatically. Director receives last reflection in `<reflect>` tag (`last_reflection="..."`, `last_tone="..."`) with instruction not to repeat themes or emotional tone.

**Stale reflection reset (v0.9.81)**: When the `_bg_director` background task is superseded by a newer turn (`_director_gen` mismatch), `reset_stale_reflection_flags(game)` is called before the early return. This clears `_needs_reflection` and resets `importance_accumulator` to 0 for all pending NPCs — preventing the zombie-reflection loop where `_needs_reflection` stays `True` permanently across every subsequent scene without ever producing output.

Mid-game NPCs without agenda/instinct get `needs_profile="true"` in their `<reflect>` tag — Director proposes both fields. The inclusion gate (condition 2 above) guarantees the NPC reaches the Director prompt even if its accumulator is far below threshold.

**Director Dual-Tone**: Two fields: `tone` (1–3 words, narrative compound like `"protective_guilt"`) for story-arc nuance, and `tone_key` (single word enum) for machine classification. `emotional_weight` gets a copy of `tone` for consistent importance scoring.

**TF-IDF NPC Activation** (`_compute_npc_tfidf_scores()`): Zero-dependency TF-IDF cosine similarity. Builds NPC profiles from name, aliases, description, agenda, last 5 observation memories. IDF weights rare words (proper names, RPG terms) automatically higher. Max contribution to activation score: 0.5.

**Importance score** `score_importance()`: Multi-stage matching:
1. Direct match against `IMPORTANCE_MAP` (50+ English emotional weights)
2. Compound split: `"Angst und Verzweiflung"` → `["angst", "verzweiflung"]`
3. DE→EN mapping via `_EMOTION_DE_EN` (~65 entries)
4. `IMPORTANCE_BOOST_KEYWORDS` (saved, death, secret, etc.) as minimum elevation from event text

---

### Game Mechanics

**Stats**: edge, iron, wits, shadow, heart (sum = 7, range 0–3)

**Rolling** `roll_action()`: 2d10 (challenge dice c1, c2) vs min(2d6+stat, 10) (action score, capped at 10)
- Action > both challenge → **STRONG_HIT** (+2 momentum, positive outcome)
- Action > one challenge → **WEAK_HIT** (+1 momentum, compromise)
- Action ≤ both challenge → **MISS** (-1 momentum, complication)
- `c1 == c2` → **Match/Fate Roll** (~10% chance, narrative only, no mechanical bonus)

**Tracks**: Health, Spirit, Supply (0–5), Momentum (-6 to +10)

**Momentum Burn**: Player converts MISS → STRONG_HIT or WEAK_HIT → STRONG_HIT. `process_momentum_burn()` fully restores state from `pre_snapshot` (all turn-mutable fields including NPCs, clocks, chaos, resources) before applying new consequences. `pre_snapshot` is always the `last_turn_snapshot` captured at the start of `process_turn()`.

**Chaos System**: Scene dice with chaos threshold (3–9). Match on Miss → Chaos Interrupt (10 types). UI indicator `⚡ Chaos!` in dice row.

**Clocks**: Progress clocks (1–12 segments). When `filled >= segments`, `"fired": true` and `"fired_at_scene": scene_count` are set at all fill points. `_purge_old_fired_clocks(game, keep_scenes=3)` runs at the start of every `process_turn()` — clocks that fired more than 3 scenes ago are removed entirely (short-term narrator context is preserved; long-term noise is eliminated). Sidebar filter: `not fired`. Director `<clocks>` block shows unfired clocks with fill bar, fired clocks as compact "already triggered" list. `load_game()` backfills `fired=True` for fully filled clocks in older saves, and `fired_at_scene=0` for already-fired clocks without the field — they are purged on the next turn.

**Clock advancement — four distinct mechanisms (owner-aware):**
- **`apply_consequences()` (on MISS)**: Ticks the first available unfilled threat clock by 1 (or 2 on desperate). No owner filter — applies to world and NPC-owned threat clocks alike. Always appends to `clock_events`: `{"clock", "trigger", "source": "miss", "ticks": int, "fired": bool}` — even for partial ticks that don't fire the clock.
- **`apply_consequences()` (on WEAK_HIT, v0.9.87)**: Position-scaled probabilistic tick. `controlled` → no tick. `risky` → 50% chance of 1 tick (`WEAK_HIT_CLOCK_TICK_CHANCE = 0.50`). `desperate` → guaranteed 1 tick. Same first-clock-only behaviour as the MISS path. Burn-restore correctly rolls back any tick (snapshot taken before `apply_consequences()`). Always appends to `clock_events` when a tick occurs: `{"clock", "trigger", "source": "weak_hit", "fired": bool}`. (Prior to v0.9.87 fix: `clock_events` only received an entry when the clock fired — partial ticks were invisible in session_log and Elvira JSON.)
- **`_tick_autonomous_clocks()` (every scene, 20% chance)**: Ticks world-owned threat clocks only (`owner in ("", "world")`). NPC-owned clocks of any type are excluded — `check_npc_agency()` is their sole advancement path. Excluding NPC-owned clocks from autonomous ticking prevents double-ticking on agency scenes (scene % 5 == 0) where both mechanisms would otherwise fire in the same turn.
- **`check_npc_agency()` (every 5 scenes, deterministic)**: Advances NPC-owned clocks of both `"scheme"` and `"threat"` type by 1 for each active NPC who owns such a clock. Owner matched by normalized NPC name + aliases (v0.9.83). (v0.9.86: extended from scheme-only to scheme+threat — NPC-owned threat clocks were permanently stuck before this fix.)

**Load-time owner repair (v0.9.83)**: `load_game()` builds a normalized `alias → canonical name` map and updates any clock owner that resolves to a different canonical name, healing stale owners from saves made before v0.9.83.

**Recovery moves (v0.9.61)**: `endure_harm`, `endure_stress`, `resupply` now have positive resource consequences: STRONG_HIT +1 (or +2 with `effect="great"`), WEAK_HIT +1. Crisis-exit check runs correctly after recovery from 0.

**`SAVE_FIELDS`**: Authoritative list of persisted fields — all other GameState fields are transient. `last_turn_snapshot` is now persisted (v0.9.62) — enables `##` correction after reload.

---

### `##` Correction System

Players prefix any input with `##` to correct the previous turn. The correction flow analyzes the error type automatically and selects the appropriate repair strategy.

**Turn Snapshot** (`_build_turn_snapshot()`): Created at every `process_turn()` start. Captures all turn-mutable fields: resources, counters, flags, spatial/temporal state, NPCs (deepcopy), clocks (deepcopy), director guidance, scene intensity, and `story_blueprint` sub-fields (`bp_revealed`, `bp_triggered_transitions`, `bp_story_complete`, `bp_triggered_director_phases`). Both restore paths (`_restore_from_snapshot()` for `##` corrections and `process_momentum_burn()`) use direct key access — snapshot is always authoritative and complete.

Since v0.9.62: `last_turn_snapshot` persisted in `SAVE_FIELDS`. `save_game()` converts `snapshot["roll"]` (a `RollResult` dataclass) via `dataclasses.asdict()` before serialization. `load_game()` reconstructs it via `RollResult(**r)`.

**Scene marker sync on location correction (v0.9.64)**: Scene markers are stored as pre-formatted strings in `s["messages"]` at render time. A `state_error` correction that changes `current_location` via `location_edit` must also update the most recent scene marker string in `s["messages"]` — otherwise the re-render shows the old location name. The `_is_correction` branch in `process_player_input()` handles this before calling `render_chat_messages()`.

**NPC death via correction (v0.9.65)**: `CORRECTION_OUTPUT_SCHEMA` `npc_edit.fields` now includes `"status"` (validated against `{"active","background","inactive","deceased"}`). `_apply_correction_ops()` `allowed` set updated accordingly. Correction brain system prompt instructs the model to use `status="deceased"` for death corrections — never write `"VERSTORBEN"` or similar into `description`. When `status="deceased"` is applied, any existing death annotation is automatically scrubbed from `description` via regex.

**NPC rename via correction (v0.9.76)**: Player writes `## Benenne X in Y um` (or equivalent). Correction brain receives aliases in NPC summary and has a dedicated NPC RENAME rule: use `fields.name="Y"`, leave `fields.aliases=null`. Engine-side: `_apply_correction_ops()` captures `old_name` before applying edits; if renaming is detected, `edits.pop("aliases")` discards any Haiku-supplied alias list (engine owns alias bookkeeping for renames); old name is moved into aliases; new name is stripped from aliases. Combined: robust against Haiku ignoring the prompt rule.

---

### Narrator Systems

#### Two-Call Pattern

**Step 1: Narrator (Sonnet) → Pure Prose**

`PURE PROSE ONLY` instruction in system prompt — no metadata templates, no JSON examples in any prompt. Narrator focuses entirely on atmospheric narration.

`call_narrator()` applies `_fix_cyrillic_homoglyphs()` before return — Sonnet occasionally mixes in Cyrillic lookalike characters (е/с/т/о/...) that break search, copy-paste, and TTS.

**Truncation salvage**: `_salvage_truncated_narration()` trims broken responses to the last complete sentence. Fires on `stop_reason="max_tokens"` AND on `end_turn` with incomplete prose end (last character not in `.!?"»«…)–—*`) — catches a rare Sonnet bug where `end_turn` returns mid-word.

**Step 1b — Opening/Chapter only: Opening Metadata Extractor (Haiku, Structured Outputs)**

`call_opening_metadata(narration, game, config, known_npcs)` runs in `start_new_game()` and `start_new_chapter()` **instead of** the mid-game extractor. Full schema: agenda, instinct, secrets + clocks, location, scene_context, time_of_day + **deceased_npcs (v0.9.84)**. Own schema `OPENING_METADATA_SCHEMA`. For chapter openings: `known_npcs` parameter ensures only genuinely new NPCs are extracted. Mid-game guard: from scene 2+, `force_npcs=False` — existing NPC list is never overwritten. **`introduced` flag (v0.9.67)**: `_process_game_data()` defaults `introduced=False` (legacy), but `parse_narrator_response()` step 10 — which sets the flag via name-matching — runs *before* `_process_game_data()` when `game.npcs` is still empty. Both `start_new_game()` and `start_new_chapter()` now explicitly set `introduced=True` on all NPCs immediately after `_process_game_data()`, since they were extracted from the narration by definition.

**NPC instinct diversity (v0.9.88)**: The `instinct` instruction in `call_opening_metadata()` now carries an explicit diversity mandate — "calm and calculating" is named as a known model default to avoid. The full spectrum is enumerated with concrete profiles: explosive/confrontational, panicked/losing control, coldly controlled (use sparingly), resigned/fatalistic, bitterly vengeful, recklessly courageous, paranoid, irrationally loyal, stubbornly refuses to adapt, dark humor under pressure, breaks down then recovers. A no-repeat rule prevents two NPCs in the same scene from sharing the same instinct profile. Root cause: savegame analysis of a 28-scene session showed all NPCs exhibiting identical low-arousal/high-dominance emotional profiles (PAD model terminology) — Haiku's unconstrained default.

**Chapter transition NPC merge (v0.9.65, extended v0.9.74)**: `start_new_chapter()` clears `game.npcs = []` then calls `_process_game_data()`, which re-assigns IDs from `npc_1`. The merge loop that re-inserts returning NPCs must **not** use ID-based deduplication — IDs were just recycled and will collide. Two-stage dedup: (1) name-based check — if extractor already created an NPC with the same name, skip; (2) **alias-based check** — if an extractor NPC's name matches any alias of the returning NPC (or vice versa), the returning NPC's history (memories, bond, importance_accumulator, last_reflection_scene, secrets, aliases) is merged into the hollow extractor NPC via `_merge_npc_identity()` rather than creating a duplicate. Alias minimum length 4 chars to exclude spatial/temporal words (e.g. `"westlich"`, `"nächtlich"`) that Brain occasionally appends as parenthetical context. Each truly new returning NPC gets a fresh ID via `_next_npc_id()`. An `id_remap` dict (old→new) is built for both paths (normal insertion and alias-merge) and used in a follow-up pass to rewrite all stale `about_npc` references across every NPC's memories.

**Step 2: Metadata Extractor (Haiku, Structured Outputs) → Game State**

`call_narrator_metadata()` extracts:

| Field | Type | Purpose |
|---|---|---|
| `scene_context` | string | Updated scene context |
| `location_update` | string\|null | New location if character moved |
| `time_update` | string\|null | Time-of-day phase (8 phases) |
| `memory_updates` | array | NPC memories (npc_id, event, emotional_weight, about_npc) |
| `new_npcs` | array | New named characters (name, description, disposition) |
| `npc_renames` | array | Identity reveals (npc_id, new_name) |
| `npc_details` | array | New facts about known NPCs (npc_id, full_name, description) |
| `deceased_npcs` | array | NPCs who died on-screen in THIS scene (npc_id) |

**Player-character exclusion**: `<player_character>` tag in prompt + name-part-intersection check in code — catches partial names like "Hermann" vs "Hermann Speedlaser".

**Physically-present rule**: `new_npcs` only for characters physically in the scene and interacting (speaking, acting, reacting). Explicit exclusion list in prompt: only-mentioned persons, deceased in flashbacks, historical figures, unnamed roles.

**NPC disambiguation (v0.9.46)**: `<known_npcs>` reference list includes `[at:Location]` and truncated description (`— desc[:60]`) per NPC. New `NPC DISAMBIGUATION` instruction in system prompt: on name ambiguity, prefer NPC whose location matches `<current_location>`.

#### Prose Cleanup (`parse_narrator_response()`)

10-step pipeline strips leaked metadata from prose:

| Step | What |
|---|---|
| 0 | Strip leading `Narrator:` role-label prefix (English narration anti-pattern) |
| 1–1.5 | `<game_data>` extraction — safety net (legacy since v0.9.51, not primary path) |
| 2 | Strip all XML metadata tags |
| 3 | Strip code fences |
| 4 | Strip leaked JSON arrays/objects |
| 5 | Strip bracket-format labels |
| 6 | Strip markdown metadata labels |
| 7 | Trailing JSON/metadata lines |
| 8 | Markdown horizontal rules + artifacts |
| 8.5 | Em-dash + en-dash → spaced regular hyphen (` - `) |
| 9 | NPC disposition normalization |
| 10 | NPC introduction marking + empty narration fallback |

`_clean_narration()` in app.py is a lightweight safety net for edge cases the parser doesn't catch — not a duplicate of the pipeline.

#### Narrator Consistency (v0.9.47)

Four information layers:

1. **Conversation history**: Last 3 narrations as user/assistant pairs. **Last narration untruncated** (v0.9.47), older ones at `MAX_NARRATION_CHARS` (1500). Provides style consistency and direct scene continuation.
2. **Factual timeline** (`_recent_events_block()`): Last 7 `session_log` entries as `<recent_events>` block. Uses Director `rich_summary` (when present), else Brain `player_intent`. These are ESTABLISHED FACTS — Narrator must not contradict them.
3. **Scene context** (`current_scene_context`): Single sentence from Metadata Extractor, overwritten each scene. As of v0.9.76: explicitly defined as situation + dominant mood/tension (not just factual state) — improves Brain position/effect calibration and TF-IDF NPC activation.
4. **Narrative state context** (`_status_context_block()`): Injects `<character_state>` block mapping Health/Spirit/Supply to 6 atmospheric stages each (e.g., health=3 → "injured — clearly hurting, moving with effort"). Narrator reflects state through body language/sensory detail, never mentions numbers. Only active when `game` is passed — opening calls without GameState are unaffected.

#### Narrator System Prompt Rules (v0.9.86)

- **`<tone_authority>` block**: Player's chosen tone injected as a first-class element before `<rules>`. Governs sentence rhythm, scene energy, highlighted details, NPC behavior, and scene mood. Explicitly instructs the narrator that `<director_guidance>` must never override or dilute the tone. Empty when `game` is `None` (opening calls unaffected).
- **`<style>` reduced to universal craft rules**: "Terse and precise" and "Render emotion through behavior and sensation" removed — these were dark/gritty-specific and actively suppressed comedy and high-energy tones. Remaining: "The player is inside the world, not watching it. Integrate what the player brings seamlessly." Tone-specific style guidance is now the sole responsibility of `<tone_authority>`.
- **SCENE CONTINUITY (v0.9.86)**: Begin in motion, not in setup. No fresh establishing paragraph. **Same location**: open with at most one bridging sentence holding the atmospheric or emotional residue of the previous scene's end (a sensation still in the air, a weight not yet lifted) — before moving into the player's action. This applies even when the player's input is very brief or sparse. **New location** (compare `<location>` with `<prev_locations>`): open with one sensory impression of the new space (sound, smell, texture, light quality) that grounds the reader without summarizing what came before — the new place exists indifferent to what preceded it; the character carries the previous moment in their body.
- **EMOTIONAL CARRY-THROUGH**: Significant emotional beats (betrayal, loss, triumph, relief, intimacy, shock) carry into the next scene through body language, perception, and attention — not narration. Emotional states do not reset between scenes.
- **SCENE ENDING (v0.9.86)**: Replaces the old "End scenes OPEN" rule. Each narration must close with a sentence naming the character's immediate unresolved inner state, unanswered perception, or the dominant open condition of the moment — not a plot cliffhanger, not a resolved beat, but an emotional/sensory suspension that gives the next scene's opening something to anchor to. The character is mid-breath, not concluded. Paired with SCENE CONTINUITY: the ending of each scene produces what the opening of the next scene picks up.
- **Thematic thread**: When `<story_arc>` contains a `thematic_thread`, it surfaces periodically through NPC dialog, reactions, or incidental observations — as a recurring undercurrent, never as lecture.
- **Act-mood texture** (action + dialog prompts): The current act's mood (from `<story_arc>`) shapes the texture of every outcome — a STRONG_HIT in a desperate phase still carries the surrounding darkness.
- **PHRASE VARIETY (v0.9.88/v0.9.89)**: The pattern `[noun] of a [person], who [relative clause]` — German: `mit dem [abstract noun] eines/einer [noun], die/der [relative clause]` — is a known Sonnet stylistic crutch, appearing almost exclusively in NPC dialog attribution. Rule (v0.9.89 tightening): AVOID as default (last resort, not template); AT MOST ONCE per response; CROSS-RESPONSE: if the pattern appeared in any preceding narration visible in the conversation history (last 3 narrations included), skip it entirely in the current response. "Tonfall" (tone of voice) called out by name as a specific overuse noun with its own per-session limit. Dialog attribution alternatives enumerated: physical action before/after speech, simple adverb, unattributed speech fragment, body-registered reaction.
- **NPC EMOTIONAL RANGE (v0.9.88)**: Emotional control is one option, not the default. An NPC's `instinct` field may produce volatile, disproportionate, or irrational responses — sudden rage, visible panic, bitter sarcasm, stubborn silence, reckless bravado, tearful collapse, uncontrollable dark humor. The rule explicitly forbids smoothing all NPCs toward composure: "A scene with three NPCs should not have three composed people — let the instinct field determine the emotional register, not a generic assumption of adult self-control."

#### Director Prompt Rules (v0.9.77)

- **`<setting>` context block**: `build_director_prompt()` now opens with `<setting genre="..." tone="..."/>`, giving the Director awareness of genre and tone for the first time.
- **TONE RULE**: `narrator_guidance` and `npc_guidance` must honor the story's tone. Comedy tones require comedy-compatible beats; dark tones require weight. Prevents Director guidance from pulling the narrator into a tonally mismatched register.
- **`player_name` intentionally absent from `<setting>`**: The Director does not need the player character's name for strategic guidance. Omitting it prevents Haiku from using it in `narrator_guidance` — which was the root cause of third-person drift. The fix is structural (don't give the information) rather than instructional (don't use the information).


#### Player Authorship Rules (Narrator System Prompt)

- **PRESERVE EXACTLY**: Player words reproduced exactly — typos, wrong names, slang, numbers unchanged. Only allowed changes: punctuation and capitalization at sentence start. (e.g., `thornwall` stays `thornwall`, not "corrected" to `Thornhill`)
- **DESCRIBED SPEECH**: If player describes a speech act without literal dialogue ("I ask him about Thornhill"), Narrator uses indirect speech or summary — never invents quoted dialog for player character. Only if `<player_words>` contains explicit direct speech does it appear as quoted dialog.

---

### Setup Brain Stat Validation (Two Layers)

`call_setup_brain()` validates after the API call with three sequential steps:
- **Layer 0**: Clamp each stat 0–3
- **Layer 1**: If sum ≠ 7 → reset to archetype-specific defaults (`_ARCHETYPE_STAT_DEFAULTS`), not blind `heart:2/wits:2` fallback
- **Layer 2**: Primary stat ≥ 2 enforced. Mapping in `_ARCHETYPE_PRIMARY_STAT`. Custom archetype skips Layer 2.

`_ARCHETYPE_PRIMARY_STAT` mapping: `outsider_loner/trickster` → shadow; `investigator/scholar/inventor` → wits; `protector/hardboiled` → iron; `healer/artist` → heart.

---

### Creativity Seeds

`_creativity_seed(n=3)` generates random English words (nouns/adjectives, 4–10 chars) via `wonderwords` and injects them as `creativity_seed:` line in three prompts:
- `call_setup_brain()` (character/world creation)
- `build_new_game_prompt()` (opening scene)
- `build_new_chapter_prompt()` (chapter opening)

Explicit instruction: "Use as loose inspiration for NPC names, locations, and scene details." Without this instruction, random words only shift setting/atmosphere — Sonnet still converges on default NPC names. The instruction anchors seeds in the name-token space.

Fallback: `_SEED_FALLBACK` 30-word inline list when `wonderwords` unavailable. All injection points log the seed value for diagnostics. Based on Agrawal et al. (2026) "Addressing LLM Diversity by Infusing Random Concepts."

Not active in normal turns, momentum burn, correction, or Director — varying game context provides sufficient natural entropy there.

---

### EdgeTales Design Mode (Visual System)

Implemented via `custom_head.html` + server-side Python in `app.py`:

- **Entity highlighting**: NPC names colored by disposition CSS class, player name in accent gold. `_highlight_dialog()` post-processes narration server-side, injecting `<span class="dh-quote">` tags. `_build_entity_data(game)` builds the highlight payload (longest-first sorted). `_inject_entity_highlights(game, scope_new)` injects `_etHighlight()` JS call with 80ms delay for DOM readiness. `scope_new=True` → only `.et-new` elements (live turns).
- **Health vignette**: Red/amber CSS corner vignette tied to Health value.
- **Chaos ambient glow**: `.et-chaos` class triggers `chaos-interrupt-pulse` keyframe (one-shot red box-shadow flash, 3.5s, v0.9.62) on `msg_col` for any chaos interrupt. Separate `data-chaos-high` attribute for ambient glow at `chaos >= 7`.
- **Dialog highlight**: Quoted speech wrapped in `***bold-italic***` Markdown by `_highlight_dialog()` — 7 quote-style variants (DE standard `„"`, EN curly `""`, guillemets `«»`/`»«`, straight ASCII `"`, EN single curly `''`, French single `‹›`). Quote characters placed **outside** `***` delimiters (`»***content***«`) — guillemets and curly quotes are Unicode punctuation (Ps/Pe), placing them inside breaks CommonMark left-flanking detection. Both guillemet directions in a single combined regex pass. CSS on `em strong`: `margin-left: -0.5em` covers the opening quote; `padding-right: 0.75em` covers the closing quote — both visually inside the marker box without any HTML injection.
- **Narrator quote style**: `get_narrator_system()` injects a language-specific `DIALOG QUOTES` rule. German: `„Text."` (U+201E/U+201C, lower-9 open, upper-6 close). English: `"Text."` (U+201C/U+201D). Guillemets and straight ASCII `"` explicitly forbidden. Prevents model drift to ASCII fallback quotes which fail `_highlight_dialog` matching.

---

### Save/Load & Persistence

`save_game()`: Writes `engine_version` + `version_history` (append-only on version change). `last_turn_snapshot` now serialized via `dataclasses.asdict()` for `RollResult` field (v0.9.62).

`load_game()`: Backward compat: self-alias cleanup, NPC name sanitization, seed memory repair for memoryless NPCs, retroactive `fired=True` for fully-filled clocks in older saves, `fired_at_scene=0` backfill for already-fired clocks without the field. `load_game()` is the backward-compatibility boundary — new fields should have sane defaults.

`list_saves_with_info()`: Returns saves with full creation metadata: `setting_genre`, `setting_tone`, `setting_archetype`, `character_concept`, `backstory`, `player_wishes`, `content_lines`.

`export_story_pdf()`: PDF export via reportlab Platypus. Uses `scene_marker` messages as the gate to begin writing narration content. Tracks `content_written` — if no narration is found after processing all messages (e.g. save created by bot without `chat_messages`), inserts an explanatory note (`export.no_content` i18n key) instead of a silently empty story section.

Chapter archives: `save_chapter_archive()` / `load_chapter_archive()` / `list_chapter_archives()` / `delete_chapter_archives()` (via `shutil.rmtree`).

#### Save File Field Reference

**Canonical field names** — use these when analysing save files. Many have non-obvious names that differ from natural-language equivalents.

**Top-level game state** (flat on the save dict, sourced from `GameState` attributes via `SAVE_FIELDS`):

| Field | Type | Notes |
|---|---|---|
| `player_name` | str | Character name |
| `character_concept` | str | One-line character concept |
| `setting_genre` / `setting_tone` / `setting_archetype` | str | Setup choices |
| `edge` / `heart` / `iron` / `shadow` / `wits` | int | Stats (NOT nested under "character") |
| `health` / `spirit` / `supply` / `momentum` / `max_momentum` | int | Vitals (also flat) |
| `scene_count` | int | Current scene number (NOT "scene") |
| `chapter_number` | int | Current chapter (NOT "chapter") |
| `chaos_factor` | int | 0–9 chaos (NOT "chaos") |
| `current_location` | str | Full location description string |
| `time_of_day` | str | e.g. `"deep_night"` |
| `npcs` | list | List of NPC dicts (NOT a dict keyed by name) |
| `clocks` | list | List of clock dicts |
| `session_log` | list | Per-scene log entries |

**`session_log` entry fields** (relevant diagnostic keys beyond the basics):

| Key | Present when | Content |
|---|---|---|
| `scene` | always | Scene number at time of entry |
| `move` | always | Brain-determined move name |
| `result` | always | `"STRONG_HIT"` / `"WEAK_HIT"` / `"MISS"` / `"dialog"` / `"opening"` |
| `director_trigger` | Director ran | Reason string: `"miss"`, `"new_npcs"`, `"revelation"`, `"reflection:<name>"`, `"interval"`, etc. |
| `rich_summary` | Director ran | Director's 2–3 sentence scene summary (replaces `summary` in `_recent_events_block`) |
| `revelation_check` | pending revelation existed | `{"id": "rev_01", "confirmed": bool}` — result of `call_revelation_check()`. Removed by `process_momentum_burn()` if a burn occurs (pre-burn check is stale; new narration not re-checked). |
| `act_transitions` | act transition recorded | List of `act_id` strings (e.g. `["act_1"]`) — set by `_apply_director_guidance()` when `act_transition=true`. Back-filled acts also included. Key absent on turns without a transition. |
| `warnings` | error conditions | List of warning strings, e.g. `"social_target_unresolved:'npc_3,npc_4'"` |
| `clock_events` | always | List of clock tick/fire events (autonomous + roll-triggered) |
| `npc_activation` | always | Dict of NPC name → activation debug info (score, reasons, status) |
| `narration_history` | list | Rolling window of recent narrations |
| `story_blueprint` | dict | Story Architect output |
| `director_guidance` | dict | Latest Director output |
| `last_turn_snapshot` | dict | Pre-turn state for `##` correction |
| `chat_messages` | list | UI chat history (NOT in `SAVE_FIELDS` — written separately) |

**NPC dict fields** (each entry in `game.npcs`):

| Field | Type | Notes |
|---|---|---|
| `id` | str | e.g. `"npc_1"` |
| `name` | str | Canonical display name |
| `description` | str | Physical/behavioral description |
| `agenda` / `instinct` | str | AI-authored personality fields |
| `secrets` | list[str] | |
| `disposition` | str | `hostile` / `distrustful` / `neutral` / `friendly` / `loyal` |
| `bond` / `bond_max` | int | Bond level (0–4) |
| `status` | str | `active` / `background` / `deceased` / `lore` |
| `memory` | list | Memory entries (NOT "memories") |
| `introduced` | bool | True once NPC appeared in narration |
| `aliases` | list[str] | Alternative names / revealed identities |
| `importance_accumulator` | int | Triggers reflection when ≥ threshold |
| `last_reflection_scene` | int | Scene number of last reflection |
| `last_location` | str | Location string where NPC was last seen (NOT "last_seen_scene") |
| `arc` | str | Narrative trajectory — what the story has made of this NPC so far (v0.9.90). Set by Director via `updated_arc` on each reflection. Distinct from `instinct` (stable wiring) and `npc_guidance` (ephemeral scene hint). Exposed to Narrator in `<target_npc>` and `<activated_npc>` blocks. Default `""`. |

**Memory entry fields** (each entry in `npc["memory"]`):

| Field | Type | Notes |
|---|---|---|
| `scene` | int | Scene number |
| `event` | str | What happened |
| `emotional_weight` | str | e.g. `"conflicted"`, `"loyal"` |
| `importance` | int | Scored 1–10 |
| `type` | str | `"observation"` or `"reflection"` |
| `about_npc` | str\|null | `npc_id` if memory is primarily about another NPC |
| `_score_debug` | str | Debug string, intentionally kept during testing |
| `tone` / `tone_key` | str | Reflection-only fields |

**Clock dict fields**:

| Field | Type | Notes |
|---|---|---|
| `id` | str | e.g. `"clock_1"` |
| `name` | str | Display name |
| `clock_type` | str | `"threat"` / `"scheme"` (NOT "type") |
| `segments` | int | Total segments |
| `filled` | int | Currently filled segments |
| `fired` | bool | Whether clock has triggered |
| `fired_at_scene` | int | Scene when it triggered |
| `trigger_description` | str | What happens when filled |
| `owner` | str | `"world"` or NPC name |

**Scene marker entries in `chat_messages`** use a special format — they are NOT `role`/`content` dicts:
```json
{ "scene_marker": "Szene 3 — <location>" }
```
Regular messages have `role` (`"user"` / `"assistant"`) and `content` fields. `type` is not a standard field on chat messages.

---

### Structured Outputs

All JSON-delivering AI calls (Brain, Setup Brain, Director, Story Architect, Chapter Summary, Metadata Extractor, Opening Metadata) use Anthropic's Structured Outputs (`output_config` with `json_schema`). Schemas defined as module-level constants. Guarantees valid JSON — no post-hoc repair needed. `call_brain()` sanitizes null string fields after parsing (null → `""` for downstream joins).

---

## API Reference

### engine.py — Key Functions

| Function | Purpose |
|---|---|
| `call_brain(client, player_input, game, config)` | Brain (Haiku, SO) → parses input to JSON |
| `call_setup_brain(client, game, config)` | Setup Brain (Haiku, SO) → character/world creation |
| `call_narrator(client, prompt, system, game, config)` | Narrator (Sonnet) → pure atmospheric prose |
| `call_narrator_metadata(client, narration, game, config)` | Metadata Extractor (Haiku, SO) → scene/NPC data |
| `call_opening_metadata(client, narration, game, config, known_npcs)` | Opening/Chapter Metadata Extractor (full NPC schema) |
| `call_director(client, game, latest_narration, config)` | Director (Haiku, SO) → guidance dict |
| `call_story_architect(client, game, config)` | Story Architect (Sonnet, SO) → story blueprint |
| `call_chapter_summary(client, game, config, epilogue_text="")` | Chapter summary with NPC evolutions + thematic question + post_story_location. Pass epilogue_text for accurate post-resolution summary. |
| `call_recap(client, game, config)` | Recap (Haiku) → narrative summary |
| `generate_epilogue(client, game, config)` | Epilogue (Sonnet) → story conclusion prose |
| `process_turn(client, player_input, game, chat_messages, config, voice_config)` | Full turn pipeline |
| `process_momentum_burn(client, game, chat_messages, config, voice_config)` | Momentum burn pipeline |
| `roll_action(stat_value, momentum)` | Dice rolls → `RollResult` |
| `apply_consequences(game, roll, move, position, effect)` | Applies roll results to GameState |
| `get_current_act(game)` | Current act dict (dual logic: triggered_transitions + scene_range) |
| `build_action_prompt(game, brain, roll, config)` | Action Narrator prompt |
| `build_dialog_prompt(game, brain, config)` | Dialog Narrator prompt |
| `build_director_prompt(game, latest_narration, config)` | Director prompt |
| `build_new_game_prompt(game, config)` | Opening game prompt |
| `build_new_chapter_prompt(game, config)` | Chapter opening prompt |
| `_status_context_block(game)` | Maps Health/Spirit/Supply → 6-stage narrative descriptions |
| `_story_context_block(game)` | Story arc XML block for Narrator prompt |
| `_recent_events_block(game)` | Last 7 session_log entries as `<recent_events>` block |
| `_apply_narrator_metadata(game, metadata, scene_present_ids)` | Delegates metadata dict to `_process_*` functions |
| `_resolve_slug_refs(game, mem_updates, fresh_npcs)` | Rewrites snake_case slugs to real npc_ids |
| `_process_deceased_npcs(game, deceased_list, scene_present_ids)` | Sets `status="deceased"` with presence guard. Called from `_apply_narrator_metadata()` (mid-game, with guard) and from opening paths in `start_new_game()`/`start_new_chapter()` (no guard — all opening deaths are witnessed) |
| `_check_death_corroboration(game)` | Fallback off-screen death detection. Scans observation memories from current scene for cross-NPC + self-vote signals (both imp≥9, betrayed/devastated). Threshold: ≥1 cross-NPC vote AND total≥2. Called at end of `_apply_narrator_metadata()` after all memories are stored. |
| `_process_game_data(game, data, force_npcs)` | Opening NPCs/clocks from `call_opening_metadata()` result |
| `_process_new_npcs(game, json_text)` | Mid-game NPC creation (fuzzy match, description match, seed memory, reactivation) |
| `_description_match_existing_npc(game, new_desc)` | Description-based duplicate detection |
| `_absorb_duplicate_npc(game, original, merged_name)` | After identity reveal: absorbs duplicate NPC (calls `_apply_name_sanitization` + `_consolidate_memory`) |
| `_is_complete_description(desc)` | Checks if NPC description ends with sentence-terminating char |
| `_apply_memory_updates(game, json_text, scene_present_ids, pre_turn_npc_ids)` | NPC memories (importance, accumulator, consolidation, auto-stub, presence guard) |
| `_retire_distant_npcs(game, max_active)` | active → background by relevance score |
| `_reactivate_npc(npc, reason, force)` | background → active; deceased → active only with `force=True` |
| `score_importance(emotional_weight, event_text)` | Importance score 1–10 |
| `retrieve_memories(npc, context_text, max_count, current_scene, present_npc_ids)` | Weighted memory retrieval with NPC-relationship boost |
| `_consolidate_memory(npc)` | Intelligent memory consolidation |
| `activate_npcs_for_prompt(game, brain, player_input)` | TF-IDF NPC activation |
| `_compute_npc_tfidf_scores(npcs, query_text)` | TF-IDF cosine similarity for NPC profiles |
| `_find_npc(game, npc_ref)` | Alias-aware NPC search (ID → name → underscore-norm → alias → substring) |
| `_sanitize_npc_name(name)` | Strips bracket annotations → `(clean_name, extracted_aliases)` |
| `_apply_name_sanitization(npc)` | In-place sanitization with alias preservation and self-alias cleanup |
| `_locations_match(loc_a, loc_b)` | Fuzzy location comparison (word-set-subset + prefix check) |
| `_should_call_director(...)` | Director trigger decision — returns reason string naming NPC with highest accumulator |
| `_apply_director_guidance(game, guidance)` | Apply Director guidance dict to GameState |
| `reset_stale_reflection_flags(game)` | Reset `_needs_reflection` + `importance_accumulator` for all pending NPCs when Director is skipped (race condition) |
| `save_game(game, username, chat_messages, name)` | Save game as JSON |
| `load_game(username, name)` | Load game → (GameState, chat_history) |
| `list_saves_with_info(username)` | Saves with metadata (newest first) |
| `save_chapter_archive / load_chapter_archive / list_chapter_archives / delete_chapter_archives` | Chapter archive management |
| `export_story_pdf(game, messages, username)` | PDF export via reportlab Platypus |

### app.py — Key Functions

| Function | Purpose |
|---|---|
| `main_page()` | Entry point: build skeleton, initiate phase |
| `_show_login_phase()` | Phase 1: invite code form |
| `_show_user_selection_phase()` | Phase 2: player selection/creation |
| `_show_language_onboarding(username)` | First-user language onboarding dialog |
| `_show_main_phase()` | Phase 3: main app + `_refresh_sidebar` callback + orphaned-input retry detection |
| `render_sidebar_status(game)` | Character, stats (6 attrs incl. momentum in stat grid), tracks, chaos, clocks, arc, NPCs |
| `render_sidebar_actions(on_switch_user, on_refresh, saves_open, on_chapter_view_change)` | Recap, save/load (active-slot UI, save-info tooltip), export, new game. `on_refresh` for in-place sidebar rebuild without page reload |
| `render_settings()` | Settings: UI language + narration language (two separate dropdowns) |
| `render_help()` | Help — game system: instructions, mechanics reference, correction mode. All texts via `t()` |
| `_info_btn(tip_text)` | Flat icon button with `ui.menu()` — touch-friendly tooltip replacement |
| `_build_entity_data(game)` | Builds entity highlight payload (NPC names + disposition CSS classes, player name in accent) |
| `_inject_entity_highlights(game, scope_new)` | Injects `_etHighlight()` JS call with 80ms delay. `scope_new=True` → only `.et-new` |
| `render_chat_messages(container)` | Chat history + scene markers. Returns ID of last scene marker for post-reload scroll |
| `render_creation_flow(container)` | 6-step character creation with back navigation. Textarea limits (backstory 800, wishes/boundaries 400 chars) with Quasar `counter`. Prevents double-submit via mutual button disable. |
| `process_player_input(text, container, sidebar_container, sidebar_refresh)` | Brain → Narrator → sidebar refresh → display → scroll → TTS → auto-save. Bumps `_director_gen` at turn start |
| `render_momentum_burn()` | Momentum spend dialog with pulsing amber glow (`.burn-card`) → auto-save |
| `render_game_over()` | Finale/new-chapter dialog → auto-save |
| `render_epilogue()` | Epilogue offer or post-epilogue options. Returns True → footer locked |
| `do_tts(narration, container, autoplay)` | TTS pipeline with spinner + error handling. Removes previous audio player from DOM (`s["_tts_player"]` tracking) |
| `_setup_stt_button(...)` | STT: MediaRecorder → faster-whisper → auto-send |
| `save_cfg()` | Labels → codes for file, labels in session, config reset on language change |
| `_fetch_public_ip()` | Queries `https://api.ipify.org` (5s timeout) to detect current public IP. Returns `None` on failure. Called during cert generation to auto-include the public IP in SAN. |
| `_cert_is_ios_compatible(cert_path, key_path, required_san_ips)` | Validates a cert+key pair for reuse. Four checks: `BasicConstraints(ca=True)`, `ExtendedKeyUsage(serverAuth)`, public-key fingerprint match (crash-mid-write guard), all `required_san_ips` present in SAN (triggers regen if public IP changed). Returns `False` on any failure. |
| `_generate_self_signed_cert(extra_sans)` | Generates iOS 13+-compatible CA cert. Auto-detects public IP via `_fetch_public_ip()`, merges with `ssl_extra_sans` config. SAN: `localhost`, Pi hostname, `127.0.0.1`, local LAN IPs, public IP, extra SANs — all deduplicated. Extensions: `BasicConstraints(ca=True)`, `ExtendedKeyUsage(serverAuth)`, `KeyUsage`, `SubjectKeyIdentifier`, `SubjectAlternativeName`. `key.pem` chmod 600, `cert_dir` chmod 700 on every startup. |
| `GET /download-cert` | Serves auto-generated CA cert as `application/x-x509-ca-cert` (no `Content-Disposition`). Active only when `enable_https: true` without custom cert paths. iOS Safari triggers profile installation flow. |

### i18n.py — Key Functions/Constants

| Function/Constant | Purpose |
|---|---|
| `E` (dict) | Emoji constants (Unicode escapes, ASCII-safe) |
| `LANGUAGES` | Narration languages: `{"Deutsch": "German", ...}` |
| `UI_LANGUAGES` | UI languages: `{"Deutsch": "de", ...}` |
| `t(key, lang, **kwargs)` | UI string lookup with format strings and fallback |
| `get_stat_labels(lang)` / `get_move_labels(lang)` / `get_result_labels(lang)` | Stat/move/result labels |
| `get_disposition_labels(lang)` / `get_position_labels(lang)` / `get_effect_labels(lang)` | NPC/position/effect labels |
| `get_dice_display_options(lang)` | List: hidden, simple, detailed |
| `get_voice_options(lang)` | Edge-TTS voice labels → voice IDs |
| `get_tts_backends(lang)` | TTS backend labels → codes |
| `resolve_voice_id(label_or_id)` | Label OR voice ID → voice ID (dual input, backward compat) |
| `resolve_tts_backend(label_or_code)` | Label OR code → backend code |
| `find_voice_label(voice_id, lang)` | Voice ID → display label |
| `find_tts_backend_label(code, lang)` | Backend code → display label |
| `get_genres(lang)` / `get_tones(lang)` / `get_archetypes(lang)` | Genre/tone/archetype dicts |
| `get_genre_label(code, lang)` / `get_tone_label(code, lang)` / `get_archetype_label(code, lang)` | Code → localized label |
| `get_story_phase_labels(lang)` | Story arc phases: `{"setup": "Exposition", ...}` |
| `translate_consequence(text, lang)` | Consequence keys → target language (word-boundary regex, backward compat) |

---

## Known Pitfalls & Anti-Patterns

Hard-won lessons from real development — read before making changes.

### NiceGUI / DOM
- **Vue reconciliation**: `ui.markdown()` uses `v-html` — all JavaScript DOM mutations (innerHTML patching, TreeWalker, MutationObserver) are silently overwritten on next render. Server-side Python markup is the only reliable approach.
- **DOMPurify**: `sanitize=True` (default) strips injected `<span>` tags. HTML must go through markdown or be rendered via `ui.html()`. **Never prepend `<span class="sr-only">` to a `ui.markdown()` string** — the span is stripped, leaving text visible. And `ui.html()` wraps content in a block `<div>`, so `position: absolute` spans bleed out visibly. **Correct pattern for screen-reader role attribution: use `aria-label` on the container element** (`.props('aria-label="..."')`). This is semantically correct and has zero visual side-effects.
- **Quasar desktop drawer**: `ui.html()` innerHTML strips `class=` and `style=` on child elements inside a persistent drawer. Use `ui.element()` + `.style()` chain.
- **Touch tooltips**: `ui.tooltip()` unreliable on touch — use `_info_btn()` for settings UI.
- **`<h2>` font-size**: Browser default sets `<h2>` to ~1.5rem; `em`-based CSS on `<h2>` compounds. Use `<div>` with direct `rem` sizing for custom elements.

### AI / Tokens
- `max_tokens` is an upper bound, not a cost factor — always set generous headroom.
- **German ≈ 15–20% more tokens than English** — Director and Narrator budgets must account for this.
- Token budget constants are named module-level constants — never hardcode inline values.
- **Structured Outputs replaced JSON repair** — do not reintroduce `json.loads(repair(text))` patterns.
- Narrator `PURE PROSE ONLY` instruction exists for a reason — never add metadata templates or JSON examples to Narrator prompts. The rule also explicitly forbids role-label prefixes (`"Narrator:"`) — Sonnet uses them in English if not told otherwise.
- **Director `_bg_director` race condition**: `_director_gen` is incremented at turn start — any turn played in < ~1–2s will supersede the previous Director task before it runs. When the early-return fires, `reset_stale_reflection_flags()` MUST be called before returning, or `_needs_reflection` flags accumulate indefinitely (zombie-reflection loop). Savegame diagnostic: if `importance_accumulator` equals the exact sum of all NPC memory importances and `last_reflection_scene = 0`, the Director has never completed for that NPC.

### NPC System
- The six-layer anti-duplicate system is delicate — test changes against all six layers.
- **Always use `_find_npc()`** as the search entry point — never iterate `game.npcs` directly by name.
- Deceased NPCs are protected from fuzzy and description matches — only exact matches can trigger resurrection.
- `_apply_name_sanitization()` must be called at all four NPC entry points — missing one causes descriptor strings to persist as aliases.
- `scene_present_ids` must be passed to `_process_deceased_npcs()` — it's the safety gate against false death reports.
- `_apply_director_guidance()` calls `_apply_name_sanitization(target)` after absorb step in both the organic and correction-flow merge paths — both paths need this.
- **`_find_npc()` comma-split (v0.9.88)**: Brain occasionally returns `target_npc` as a comma-separated string (e.g. `"npc_3,npc_4"`) when a scene involves multiple NPCs simultaneously. `_find_npc()` now splits on commas and resolves only the first token. An empty-string guard (`if not npc_ref: return None`) follows the split in case of degenerate input like `","`. All ~12 call sites are covered by this single entry-point fix.

### Persistence
- **`SAVE_FIELDS`** is the authoritative list — transient fields not in it are silently dropped on save.
- `RollResult` dataclass in snapshots requires `dataclasses.asdict()` for JSON serialization — `json.dumps` will raise `TypeError`.
- `load_game()` is the backward-compatibility boundary — new fields must have sane defaults that work with old saves.
- **`revelation_check` after momentum burn (v0.9.88)**: `process_momentum_burn()` restores blueprint state from the pre-turn snapshot, which un-marks any revelation confirmed during the pre-burn narration. The corresponding `session_log[-1]["revelation_check"]` entry must also be cleared — otherwise the log reports `confirmed: true` while the blueprint treats the revelation as still pending. Fix: `pop("revelation_check", None)` in the `session_log` update block of `process_momentum_burn()`.

### i18n
- Every user-visible string through `t(key, lang)` — no hardcoded German or English UI strings in app.py.
- ARIA labels need **both** `de` and `en` entries — screen readers use them.
- Voice/TTS backend labels resolved via `resolve_voice_id()` / `resolve_tts_backend()` — never assume label == ID.

### Deployment (Pi + Windows Dev)
- **PowerShell sequential commands after SSH password prompts**: use `;` not `&&` — `&&` silently fails on the second command when the first prompts for a password.
- SFTP auto-sync (`uploadOnSave: true`) pushes on save — restart the service after pushing `engine.py` changes.
- `edgetales_monitor.py` (watchdog + IONOS SMTP) is a separate service — don't confuse its log output with app errors.

---

## Design Decisions

Key architectural choices and the reasoning behind them.

| Decision | Rejected Alternative | Reason |
|---|---|---|
| Server-side Python markup for entity highlighting | JavaScript DOM mutation after render | NiceGUI Vue reconciliation silently overwrites all JS DOM changes |
| Structured Outputs for all AI JSON calls | JSON repair (`json.loads(repair(text))`) | Eliminates entire error class; guarantees valid schema |
| Deferred Director (non-blocking, post-save) | Blocking Director before player sees narration | Reduces player-facing latency from ~4s to ~2.5s |
| Haiku for Brain/Director/Metadata, Sonnet for Narrator/Architect | Sonnet everywhere | Haiku ~10× cheaper and fast enough for structured-output tasks |
| Parallel Narrator + Story Architect at game start | Sequential calls | Halves startup wait time (~15s vs ~30s) |
| `about_npc` field on memories (emergent relationships) | Dedicated NPC relationship data structure | No added complexity; relationships emerge organically from the existing memory infrastructure |
| Fuzzy location matching (`_locations_match()`) | Strict string equality | "Main Hall" vs "the main hall" must not create spatial inconsistencies |
| Creativity seeds via `wonderwords` with explicit use-instruction | No seeds / random seeds without instruction | Without explicit instruction, seeds only shift atmosphere — not NPC names (convergence problem). Inline-list fallback for minimal installs. |
| Shelved: NPC secret alias system | Implement it | Architecturally invasive; would destabilize core NPC/alias/merge systems |
| Opening Metadata Extractor (Haiku, separate call) | Narrator fills `<game_data>` JSON inline | Inline JSON in prose = entire error class (code fences, malformed JSON, mixed prose/data). Separate call with Structured Outputs is clean. |
| `copy.copy(game)` snapshot for Architect thread | Shared reference | `parse_narrator_response()` mutations on the main thread would race-condition the Architect's input |
| `_xa(s)` helper for XML attribute escaping | Manual `.replace('"', '&quot;')` | Manual replace only covers `"` — misses `<` and `&`. `html.escape(str(s), quote=True)` covers all three in one call. Applied to all AI-prose fields in XML attribute position. |
| `html.escape()` for XML element content | No escaping | AI-generated text in element positions (mem_text, revelation content, director guidance, NPC descriptions) can contain `<` or `&` — silently corrupts prompt structure without escaping. |
| Engine owns alias bookkeeping on NPC rename | Let Haiku manage aliases in `npc_edit` | If Haiku supplies `fields.aliases` alongside `fields.name`, it overwrites the existing list before engine can preserve the old name. `edits.pop("aliases")` on rename detection makes the engine the sole authority. |

---

*Changelog and detailed change history: `CHANGELOG.md`*  
*User documentation: `README.md`*
