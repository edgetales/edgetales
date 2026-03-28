# EdgeTales — Project Briefing

> Changelog → `CHANGELOG.md` | User Docs → `README.md` | Source → GitHub: edgetales/edgetales

---

## Quick Reference

| | |
|---|---|
| **Version** | v0.9.68 |
| **Codebase** | ~13,600 lines across 5 source files + config |
| **Stack** | Python 3.11+, NiceGUI, Anthropic SDK (Structured Outputs), reportlab, edge-tts, faster-whisper, wonderwords, stop-words, nameparser, cryptography |
| **AI Models** | Narrator/Architect: `claude-sonnet-4-6` · Brain/Director/Extractors: `claude-haiku-4-5-20251001` |
| **Core Principle** | "AI narrates, dice decide." — All outcomes determined by dice rolls, never by AI judgment |
| **Start** | `python app.py` → `http://localhost:8080` (requires `config.json` with `api_key`) |
| **ENV Overrides** | `ANTHROPIC_API_KEY`, `INVITE_CODE`, `ENABLE_HTTPS`, `PORT`, `DEFAULT_UI_LANG` |

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

1. **`CHANGELOG.md`**: Add to the existing version entry if the change belongs to the current release. Use the "Keep a Changelog" format (Added / Changed / Fixed). English only. Entries should be self-contained — someone reading the changelog cold should understand the change.
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

**Revelation pipeline (v0.9.65)**:
- `get_pending_revelations()` returns revelations eligible at current `scene_count` (not yet in `revealed`).
- `_story_context_block()` surfaces the first pending revelation as `<revelation_ready weight="...">full content</revelation_ready>` — a dedicated XML element with the **full, untruncated** content. Previously was a 80-char-truncated XML attribute, which silently dropped most of the twist.
- After narration, `call_revelation_check()` (Haiku, `REVELATION_CHECK_SCHEMA`) verifies whether the narrator actually wove the revelation in. Returns `revelation_confirmed: bool + reasoning`. `mark_revelation_used()` is gated on `True`. On extractor failure, defaults `True` (anti-loop safety).
- `revelation_confirmed` is also forwarded to `_should_call_director()` — Director is only triggered with reason `"revelation"` when the revelation was genuinely confirmed, not merely pending.

**Transition Triggers**: Each act has a `transition_trigger` (narrative condition) alongside `scene_range` (fallback). Director evaluates via `act_transition: true/false`. `get_current_act()` uses dual logic: (1) check `triggered_transitions` from blueprint, (2) fallback to `scene_range`.

**Akt-Transitions Guard + Back-fill (v0.9.61)**:
- **Final-act guard**: If `act_idx >= len(acts)-1`, Director signal is ignored (final act has no outbound trigger by design).
- **Back-fill**: When recording `act_N`, all preceding `act_i` (i < N) with exceeded `scene_range` are also written to `triggered_transitions` if not yet present — prevents gaps like `['act_0', 'act_2']`.

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

**Director Race Condition Guard (v0.9.58)**: `_director_gen` session counter, incremented at each turn start in `process_player_input()`. Background Director task checks twice: (1) before API call — skips if new turn already running; (2) before `save_game()` — prevents overwriting a newer save.

**Director Alias-Awareness (v0.9.46)**: `build_director_prompt()` shows NPC aliases in NPC list (`aka ...`) and in `<reflect>` tags (`aliases="..."` attribute). `DIRECTOR_SYSTEM` instructs: aliases = same person, use primary name consistently.

**Lore NPC Status (v0.9.67)**: New `"lore"` status for narratively significant figures who are never physically present (dead mentors, missing persons, historical figures). Registered via `_process_lore_npcs()` from `lore_npcs` Metadata Extractor field. Lore NPCs: collect memories via `memory_updates`, appear in `<lore_figures>` narrator context block (name + 80-char description), excluded from `<known_npcs>` and NPC activation/agency, do not count against `MAX_ACTIVE_NPCS`. Sidebar renders them under "Known Persons" identically to `background`. Transition `lore → active` via `_reactivate_npc()` — happens automatically when the figure physically appears. All dedup paths recognise `lore` status. `valid_statuses` in correction-ops includes `"lore"`.

**Director Language Enforcement (v0.9.67)**: The `<task>` block opens with a hard `LANGUAGE RULE` that forbids any partial English, even mid-sentence, when the narration language is non-English. Per-field `in {lang}` instructions remain as secondary reinforcement.

**Clocks in Director (v0.9.59)**: Director receives `<clocks>` block with name, type, visual fill bar (`█░`), ratio, percent, trigger text. `DIRECTOR_SYSTEM` instructs Director to reference clocks in `arc_notes` / `narrator_guidance` when ≥50% filled or recently ticked.

**`_apply_director_guidance()` — Two Agenda/Instinct Paths**:
- `agenda`/`instinct`: fills **only empty fields** (`needs_profile="true"` NPCs)
- `updated_agenda`/`updated_instinct` (v0.9.61): **actively overwrites** when non-null — for NPCs whose goals fundamentally changed (defeat, betrayal, revelation). Director prompt explains when to use update vs. leave null.

**Reflection-Truncation Guard**: `_apply_director_guidance()` checks if reflection text ends with sentence-terminating character. Truncated reflections are discarded — `_needs_reflection` stays active, Director retries next cycle.

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

#### Three-Tier NPC Status (+deceased)

| Status | Sidebar | Brain/Narrator Context | Purpose |
|---|---|---|---|
| `active` | ✅ prominent | ✅ full (agenda, memories, secrets) | Currently relevant NPCs |
| `background` | ✅ dimmed, collapsed | Brain name list only (for target recognition) | Known NPCs, not currently present |
| `deceased` | ☠️ strikethrough, collapsed | ❌ (only `[DECEASED]` in metadata ref) | Killed NPCs — protected from all merges |
| `inactive` | ❌ | ❌ | Legacy compat / chapter transitions |

**Status transitions**:
- `active` → `background`: `_retire_distant_npcs()` at >MAX_ACTIVE_NPCS (12). Relevance score: `last_memory_scene + bond × 3 + current_scene_bonus (+1000)`. Current-scene bonus protects freshly introduced NPCs.
- `background` → `active`: Automatically when Brain identifies `target_npc`, Metadata Extractor recognizes new NPCs matching a known NPC, or memory updates arrive for background NPCs.
- `active`/`background` → `deceased`: `_process_deceased_npcs()` when Narrator **depicts** an on-screen death (not dialog claims). Extractor rule covers both physical deaths (collapse, killed) and supernatural/atmospheric finality (pulled under water, consumed, destroyed — described as irreversible). Two-stage guard: (1) Extractor prompt distinguishes narrator-depicted deaths from dialog claims; (2) code guard checks `scene_present_ids` (activated + mentioned NPC IDs, v0.9.47).
- `deceased` → `active`: Only on exact name match in `new_npcs` or `memory_updates` (resurrection). `_reactivate_npc(force=True)` required. Fuzzy matches are blocked.

#### Two NPC Creation Paths

1. **Opening scene** (`call_opening_metadata()`, v0.9.51): Haiku Structured Outputs with full schema: name, description, agenda, instinct, secrets, disposition + clocks, location, scene_context, time_of_day. Processing in `_process_game_data()`. Replaces old inline `<game_data>` JSON that the Narrator had to fill — eliminates that error class entirely.
2. **Mid-game discovery** (Metadata Extractor `new_npcs`): Minimal schema: `{"name": "...", "description": "1 sentence", "disposition": "neutral"}`. Code fills defaults. Auto-generates seed memory from description + disposition-based emotional weight.

Both paths set `last_location = game.current_location`. Updated on every memory in `_apply_memory_updates()`.

#### Six-Layer Anti-Duplicate Safety Net

1. **`npc_renames`** (Metadata Extractor) → `_merge_npc_identity()`: old name → aliases, new name → primary. Guards: same-name check (identical names → skip), self-alias cleanup (new name removed from aliases), `load_game()` cleans self-aliases in existing saves. `_absorb_duplicate_npc()` called after every rename to absorb any NPC whose primary name **or alias** matches the renamed-to name.
2. **Fuzzy name match** in `_process_new_npcs()` — substring overlap, word overlap, STT-variant matching (Levenshtein ≤ 1). Returns `(npc, match_type)`: `"identity"` for rename, `"stt_variant"` for alias-only.
3. **Description match** `_description_match_existing_npc()` — catches duplicates when names have zero word overlap but descriptions match. Word overlap + substring matching + compound decomposition (Bindestrich split) + Long-Compound-Bonus (≥12 chars count 1.5×). Threshold: ≥25% ratio OR one long match with effective ≥2.0. **Spatial Guard**: skips candidates whose `last_location` differs from `game.current_location`. **Name-Reference Guard (v0.9.48)**: words from candidate's name/aliases (≥4 chars) are filtered from the new description word set before overlap check.
4. **`_apply_memory_updates()`** — finds NPC even with unknown reference, creates stub only as last resort. Guards: `npc_\d+` pattern and player character name (part-intersection) are rejected. **Auto-stub humanization (v0.9.45)**: snake_case stub names → Title Case with spaces. **Name/alias guard (v0.9.66)**: after humanization, `_find_npc()` is called before any stub creation — if a match is found by name or alias, memory is routed to the existing NPC and no stub is created; background NPCs are reactivated as needed.
5. **`_process_npc_details()` identity-reveal fallback**: if `full_name` completely differs from current NPC name, calls `_merge_npc_identity()` instead of rejecting. Then `_absorb_duplicate_npc()` checks if `_process_new_npcs()` already created a duplicate with the new name in the same metadata cycle, and absorbs its memories/data.
6. **Slug resolution** `_resolve_slug_refs()` (v0.9.45) — runs in `_apply_narrator_metadata()` between `_process_new_npcs()` and `_apply_memory_updates()`. Converts snake_case slugs (e.g., `moderator_headset`) to real `npc_id`s for same-cycle cross-references.

**`_absorb_duplicate_npc()` match logic (v0.9.66):** matches candidate duplicates by primary name **or any alias** of the duplicate NPC — so a NPC whose primary name differs but carries the merged name as an alias is also absorbed.

#### NPC Spatial Tracking (`last_location`)

Every NPC has `last_location` (string, default `""`). Set on creation, updated on every memory. Prompt builders inject spatial hints when NPC location differs from player location: `last_seen="..."` (activated NPCs) and `[at:Location]` (known NPCs). **SPATIAL CONSISTENCY** rule in Narrator prompt: NPCs at other locations cannot physically interact — they must first plausibly travel to the player.

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

**NPC-to-NPC relationships (`about_npc`)**: Optional field on any memory. When a memory primarily concerns another NPC (player tells Sophie about Bruce, Sophie observes Bruce acting), `about_npc` is set to the referenced NPC's ID. No separate relationship system — relationships emerge organically from tagged memories within the existing memory infrastructure. Extractor prompt instructs: player-initiated NPC-to-NPC communication (gossip, warnings, lies, compliments) MUST be captured as a memory with `about_npc`.

**Weighted retrieval** `retrieve_memories()`:
```
Score = 0.40 × Recency + 0.35 × Importance + 0.25 × Relevance
```
Exponential recency decay (`0.92^scene_gap`). Reflections have floor 0.6 and store `scene_count`. Guarantees ≥1 reflection always present. Optional `present_npc_ids`: memories with `about_npc` pointing to a present NPC get +0.6 relevance boost (max 1.0).

**Consolidation** `_consolidate_memory()`: Reflections always kept (max 8), observations by budget split (60% recency + 40% importance). Total max 25 entries.

**Reflection trigger**: `importance_accumulator` incremented per memory update. At `REFLECTION_THRESHOLD` (30) → `_needs_reflection = True` → Director generates reflection (importance 8, decays slower). Director receives last reflection in `<reflect>` tag (`last_reflection="..."`, `last_tone="..."`) with instruction not to repeat themes or emotional tone.

Mid-game NPCs without agenda/instinct get `needs_profile="true"` — Director proposes both.

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

**Rolling** `roll_action()`: 2d10 (challenge dice c1, c2) + 1d6+stat (action score)
- Action > both challenge → **STRONG_HIT** (+2 momentum, positive outcome)
- Action > one challenge → **WEAK_HIT** (+1 momentum, compromise)
- Action ≤ both challenge → **MISS** (-1 momentum, complication)
- `c1 == c2` → **Match/Fate Roll** (~10% chance, narrative only, no mechanical bonus)

**Tracks**: Health, Spirit, Supply (0–5), Momentum (-6 to +10)

**Momentum Burn**: Player converts MISS → STRONG_HIT or WEAK_HIT → STRONG_HIT. `process_momentum_burn()` fully restores state from `pre_snapshot` (all turn-mutable fields including NPCs, clocks, chaos, resources) before applying new consequences. `pre_snapshot` is always the `last_turn_snapshot` captured at the start of `process_turn()`.

**Chaos System**: Scene dice with chaos threshold (3–9). Match on Miss → Chaos Interrupt (10 types). UI indicator `⚡ Chaos!` in dice row.

**Clocks**: Progress clocks (1–12 segments). When `filled >= segments`, `"fired": true` and `"fired_at_scene": scene_count` are set at all three fill points (`apply_consequences`, `_tick_autonomous_clocks`, NPC-scheme path). `_purge_old_fired_clocks(game, keep_scenes=3)` runs at the start of every `process_turn()` — clocks that fired more than 3 scenes ago are removed entirely (short-term narrator context is preserved; long-term noise is eliminated). Sidebar filter: `not fired`. Director `<clocks>` block shows unfired clocks with fill bar, fired clocks as compact "already triggered" list. `load_game()` backfills `fired=True` for fully filled clocks in older saves, and `fired_at_scene=0` for already-fired clocks without the field — they are purged on the next turn.

**Autonomous clock ticking (v0.9.59)**: Each scene, every unfilled threat clock (not owner-controlled) rolls 18% chance (`AUTONOMOUS_CLOCK_TICK_CHANCE`) to tick forward 1 segment. Logged and appended to `clock_events`.

**Recovery moves (v0.9.61)**: `endure_harm`, `endure_stress`, `resupply` now have positive resource consequences: STRONG_HIT +1 (or +2 with `effect="great"`), WEAK_HIT +1. Crisis-exit check runs correctly after recovery from 0.

**`SAVE_FIELDS`**: Authoritative list of persisted fields — all other GameState fields are transient. `last_turn_snapshot` is now persisted (v0.9.62) — enables `##` correction after reload.

---

### `##` Correction System

Players prefix any input with `##` to correct the previous turn. The correction flow analyzes the error type automatically and selects the appropriate repair strategy.

**Turn Snapshot** (`_build_turn_snapshot()`): Created at every `process_turn()` start. Captures all turn-mutable fields: resources, counters, flags, spatial/temporal state, NPCs (deepcopy), clocks (deepcopy), director guidance, scene intensity, and `story_blueprint` sub-fields (`bp_revealed`, `bp_triggered_transitions`, `bp_story_complete`). Both restore paths (`_restore_from_snapshot()` for `##` corrections and `process_momentum_burn()`) use direct key access — snapshot is always authoritative and complete.

Since v0.9.62: `last_turn_snapshot` persisted in `SAVE_FIELDS`. `save_game()` converts `snapshot["roll"]` (a `RollResult` dataclass) via `dataclasses.asdict()` before serialization. `load_game()` reconstructs it via `RollResult(**r)`.

**Scene marker sync on location correction (v0.9.64)**: Scene markers are stored as pre-formatted strings in `s["messages"]` at render time. A `state_error` correction that changes `current_location` via `location_edit` must also update the most recent scene marker string in `s["messages"]` — otherwise the re-render shows the old location name. The `_is_correction` branch in `process_player_input()` handles this before calling `render_chat_messages()`.

**NPC death via correction (v0.9.65)**: `CORRECTION_OUTPUT_SCHEMA` `npc_edit.fields` now includes `"status"` (validated against `{"active","background","inactive","deceased"}`). `_apply_correction_ops()` `allowed` set updated accordingly. Correction brain system prompt instructs the model to use `status="deceased"` for death corrections — never write `"VERSTORBEN"` or similar into `description`. When `status="deceased"` is applied, any existing death annotation is automatically scrubbed from `description` via regex.

---

### Narrator Systems

#### Two-Call Pattern

**Step 1: Narrator (Sonnet) → Pure Prose**

`PURE PROSE ONLY` instruction in system prompt — no metadata templates, no JSON examples in any prompt. Narrator focuses entirely on atmospheric narration.

`call_narrator()` applies `_fix_cyrillic_homoglyphs()` before return — Sonnet occasionally mixes in Cyrillic lookalike characters (е/с/т/о/...) that break search, copy-paste, and TTS.

**Truncation salvage**: `_salvage_truncated_narration()` trims broken responses to the last complete sentence. Fires on `stop_reason="max_tokens"` AND on `end_turn` with incomplete prose end (last character not in `.!?"»«…)–—*`) — catches a rare Sonnet bug where `end_turn` returns mid-word.

**Step 1b — Opening/Chapter only: Opening Metadata Extractor (Haiku, Structured Outputs)**

`call_opening_metadata(narration, game, config, known_npcs)` runs in `start_new_game()` and `start_new_chapter()` **instead of** the mid-game extractor. Full schema: agenda, instinct, secrets + clocks, location, scene_context, time_of_day. Own schema `OPENING_METADATA_SCHEMA`. For chapter openings: `known_npcs` parameter ensures only genuinely new NPCs are extracted. Mid-game guard: from scene 2+, `force_npcs=False` — existing NPC list is never overwritten. **`introduced` flag (v0.9.67)**: `_process_game_data()` defaults `introduced=False` (legacy), but `parse_narrator_response()` step 10 — which sets the flag via name-matching — runs *before* `_process_game_data()` when `game.npcs` is still empty. Both `start_new_game()` and `start_new_chapter()` now explicitly set `introduced=True` on all NPCs immediately after `_process_game_data()`, since they were extracted from the narration by definition.

**Chapter transition NPC merge (v0.9.65)**: `start_new_chapter()` clears `game.npcs = []` then calls `_process_game_data()`, which re-assigns IDs from `npc_1`. The merge loop that re-inserts returning NPCs must **not** use ID-based deduplication — IDs were just recycled and will collide. Name-based check only. Each returning NPC gets a fresh ID via `_next_npc_id()`. An `id_remap` dict (old→new) is built during insertion and used in a follow-up pass to rewrite all stale `about_npc` references across every NPC's memories.

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
3. **Scene context** (`current_scene_context`): Single sentence from Metadata Extractor, overwritten each scene. Compact state indicator.
4. **Narrative state context** (`_status_context_block()`): Injects `<character_state>` block mapping Health/Spirit/Supply to 6 atmospheric stages each (e.g., health=3 → "injured — clearly hurting, moving with effort"). Narrator reflects state through body language/sensory detail, never mentions numbers. Only active when `game` is passed — opening calls without GameState are unaffected.

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

`export_story_pdf()`: PDF export via reportlab Platypus.

Chapter archives: `save_chapter_archive()` / `load_chapter_archive()` / `list_chapter_archives()` / `delete_chapter_archives()` (via `shutil.rmtree`).

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
| `_process_deceased_npcs(game, deceased_list, scene_present_ids)` | Sets `status="deceased"` with presence guard |
| `_process_game_data(game, data, force_npcs)` | Opening NPCs/clocks from `call_opening_metadata()` result |
| `_process_new_npcs(game, json_text)` | Mid-game NPC creation (fuzzy match, description match, seed memory, reactivation) |
| `_description_match_existing_npc(game, new_desc)` | Description-based duplicate detection |
| `_absorb_duplicate_npc(game, original, merged_name)` | After identity reveal: absorbs duplicate NPC (calls `_apply_name_sanitization` + `_consolidate_memory`) |
| `_is_complete_description(desc)` | Checks if NPC description ends with sentence-terminating char |
| `_apply_memory_updates(game, json_text)` | NPC memories (importance, accumulator, consolidation, auto-stub) |
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
| `_should_call_director(...)` | Director trigger decision |
| `_apply_director_guidance(game, guidance)` | Apply Director guidance dict to GameState |
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

### NPC System
- The six-layer anti-duplicate system is delicate — test changes against all six layers.
- **Always use `_find_npc()`** as the search entry point — never iterate `game.npcs` directly by name.
- Deceased NPCs are protected from fuzzy and description matches — only exact matches can trigger resurrection.
- `_apply_name_sanitization()` must be called at all four NPC entry points — missing one causes descriptor strings to persist as aliases.
- `scene_present_ids` must be passed to `_process_deceased_npcs()` — it's the safety gate against false death reports.
- `_apply_director_guidance()` calls `_apply_name_sanitization(target)` after absorb step in both the organic and correction-flow merge paths — both paths need this.

### Persistence
- **`SAVE_FIELDS`** is the authoritative list — transient fields not in it are silently dropped on save.
- `RollResult` dataclass in snapshots requires `dataclasses.asdict()` for JSON serialization — `json.dumps` will raise `TypeError`.
- `load_game()` is the backward-compatibility boundary — new fields must have sane defaults that work with old saves.

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

---

*Changelog and detailed change history: `CHANGELOG.md`*  
*User documentation: `README.md`*
