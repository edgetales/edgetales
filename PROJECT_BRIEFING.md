# EdgeTales — Project Briefing

> **Quick navigation**: [Working Contract](#working-contract) · [Architecture](#architecture) · [Core Systems](#core-systems) · [NPC System](#npc-system) · [Known Pitfalls](#known-pitfalls--anti-patterns) · [Design Decisions](#design-decisions) · [i18n Reference](#i18n-reference) · [Elvira](#elvira-test-bot)  
> Changelog → `CHANGELOG.md` | User Docs → `README.md` | Source → GitHub: edgetales/edgetales

---

## Quick Reference

| | |
|---|---|
| **Version** | v0.9.96 |
| **Codebase** | ~13,600 lines across 5 source files + config |
| **Stack** | Python 3.11+, NiceGUI, Anthropic SDK (Structured Outputs), reportlab, edge-tts, faster-whisper, wonderwords, stop-words, nameparser, cryptography |
| **AI Models** | Narrator/Architect: `claude-sonnet-4-6` · Brain/Director/Extractors: `claude-haiku-4-5-20251001` |
| **Core Principle** | "AI narrates, dice decide." — All outcomes determined by dice rolls, never by AI judgment |
| **Start** | `python app.py` → `http://localhost:8080` (requires `config.json` with `api_key`) |
| **ENV Overrides** | `ANTHROPIC_API_KEY`, `INVITE_CODE`, `ENABLE_HTTPS`, `SSL_EXTRA_SANS`, `PORT`, `DEFAULT_UI_LANG` |

Auto-install: `_ensure_requirements()` checks and installs 9 mandatory packages on startup. Chatterbox (TTS offline/voice cloning) remains optional — shown as info card in Settings if not installed.

---

## Working Contract

*These rules apply every session without exception.*

### Language Rules
- **Lars communicates in German** — respond in German
- **All code, comments, docstrings, CHANGELOG, README, and this file = English**
- German UI strings live in `i18n.py` — never hardcode German text in Python logic
- When discussing code in chat, use English identifiers/function names naturally

### Session Workflow
1. **Analyze first** — read the relevant code/file section before proposing solutions. For bugs: ask for savegame or log upload if the root cause is unclear.
2. **Discuss if non-trivial** — architectural implications → align before coding.
3. **Implement surgically** — `str_replace` for targeted edits. Full file output only if Lars explicitly asks or >30% of file changes.
4. **Syntax-check** — verify Python syntax after every code change.
5. **Session end** — update `CHANGELOG.md` + `PROJECT_BRIEFING.md` (mandatory).

### Editing Rules
- `str_replace` preferred: target the exact function or section; never modify unrelated code.
- `old_str` must match the raw file content exactly (whitespace included) — always `view` immediately before editing.
- **Version strings** in `engine.py` and `README.md` are updated manually by Lars — never touch them.
- After a successful `str_replace`, re-view the file before further edits to the same file.

### Mandatory Session-End Steps
Every session that changes code or architecture must end with both:

1. **`CHANGELOG.md`**: Add to the current version entry. Keep a Changelog format (Added / Changed / Fixed). English only. Entries self-contained. **`elvira/` changes are never logged here.**
2. **`PROJECT_BRIEFING.md`**: Reflect any architectural, behavioral, or API changes. Update version in Quick Reference.

### Multi-Language Requirement ⚠️
Every UI change must:
- Add/update `i18n.py` keys for **both** `de` and `en`
- Add/update ARIA labels in both languages
- Use `t(key, lang)` — zero hardcoded strings in `app.py`

### NiceGUI / DOM Rules
→ See full details in [Known Pitfalls: NiceGUI / DOM](#nicegui--dom). Key rule: server-side Python markup is the only reliable approach for any post-render content injection.

### Architectural Caution
- No architecturally invasive features without discussing trade-offs first
- The NPC system is multi-layered — changes to one layer cascade to others
- Token budget constants are named module-level constants — never inline values
- German uses ~15–20% more tokens than English — Director and Narrator budgets must account for this

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
users/<n>/saves/<n>.json            — Save slots
users/<n>/saves/chapters/<n>/       — Chapter archives
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

**Prompt caching**: `call_narrator()` sends the system prompt with `cache_control: {"type": "ephemeral"}` (5-min server-side cache, 10× cheaper reads). `_status_context_block()` lives in the four user-prompt builders (not the system prompt) so H/Sp/Su changes never invalidate the cache. ~20% Narrator input token savings at typical 2–3 min/turn pace.

### Story Architect (Sonnet, one-time call)

`call_story_architect()` runs at game start and chapter start. Runs **in parallel** with the opening Narrator via `concurrent.futures.ThreadPoolExecutor(max_workers=2)` — halves startup wait (~15s vs ~30s). Thread receives a `copy.copy(game)` snapshot to prevent race conditions from `parse_narrator_response()` mutations.

**Output**: Story blueprint with `central_conflict`, `antagonist_force`, `thematic_thread`, Acts (3-act or Kishōtenketsu) with `transition_trigger` per act, revelations, and possible endings.

**3-act prompt key rules**: (1) anti-escalation — confrontation→climax trigger must be a REFRAMING EVENT; (2) dual-layer `central_conflict` (SURFACE + HIDDEN); (3) `thematic_thread` as a genuine open philosophical question; (4) at least one revelation must recontextualize something already seen.

**Revelation pipeline**:
- `get_pending_revelations()` returns revelations eligible at current `scene_count`.
- `_story_context_block()` surfaces the first pending revelation as `<revelation_ready>` — **full, untruncated** content.
- `call_revelation_check()` (Haiku) verifies whether Narrator wove it in. Gates `mark_revelation_used()` on `True`. On extractor failure, defaults `True` (anti-loop).
- Director triggered with reason `"revelation"` only when genuinely confirmed.

**Transition triggers**: Each act has a `transition_trigger` (narrative condition) + `scene_range` (fallback). Director evaluates via `act_transition: true/false`. Back-fill in `_apply_director_guidance()`: when recording `act_N`, all preceding `act_i` with exceeded `scene_range` are also written to `triggered_transitions` — prevents gaps like `['act_0', 'act_2']`.

### Director Trigger System

`_should_call_director()` returns reason string or `None`. Reasons: `"miss"`, `"chaos"`, `"new_npcs"`, `"revelation"`, `"reflection:<NPC-Name>"`, `"phase:<phase>"`, `"interval"`. Stored in `session_log[-1]["director_trigger"]`. Phase triggers: `"climax"`, `"resolution"`, `"ten_twist"`, `"ketsu_resolution"`. Typical: 5–7 Director calls per session.

**Phase-trigger deduplication**: `phase:` triggers fire at most once per phase per chapter, tracked in `story_blueprint["triggered_director_phases"]`. `_build_turn_snapshot()` captures and `_restore_from_snapshot()` restores this list — a `##` correction on the trigger turn un-marks the phase, allowing re-fire.

**Director Race Condition Guard**: `_director_gen` session counter incremented at each turn start. Background Director task checks (1) before API call and (2) before `save_game()`. When early-return fires, `reset_stale_reflection_flags()` MUST be called — or `_needs_reflection` flags accumulate indefinitely (zombie-reflection loop).

**`_apply_director_guidance()` — agenda/instinct/arc paths**:
- `agenda`/`instinct`: fills **only empty fields** (`needs_profile="true"` NPCs)
- `updated_agenda`: **actively overwrites** when non-null — for NPCs whose goals fundamentally changed
- `instinct`: locked after first fill — it is the NPC's psychological wiring, not their mood. Never updated after initial fill.
- `updated_arc`: narrative trajectory, expected to evolve each reflection. 1–2 sentences from the NPC's inside perspective. Written to `npc["arc"]` with 300-char guard. Shown to Narrator in `<target_npc>` and `<activated_npc>` tags.

**Reflection-Truncation Guard**: `_apply_director_guidance()` tracks `successfully_reflected_ids`. Fallback loop resets `_needs_reflection=False` and `importance_accumulator=0` for rejected/missing reflections — prevents zombie-reflection loop.

**Lore/deceased NPC reflection guard**: `<reflect>` tags only emitted for `active` and `background` NPCs. If Director produces a reflection for a lore/deceased NPC, `_apply_director_guidance()` rejects it with WARNING.

### Post-Completion Aftermath Phase

`_check_story_completion()` — Three-Stage Trigger:
1. **Primary**: penultimate act ID in `triggered_transitions` AND `scene_count >= final_act.scene_range[1]`
2. **Scene-range back-fill**: if primary fails AND `scene_count >= final_end` → back-fill preceding acts with exceeded `scene_range` into `triggered_transitions`, re-evaluate primary. Handles fast-play campaigns where all Director runs were superseded.
3. **Fallback**: `scene_count >= final_end + 5` (safety net)

When `story_complete=True` + `epilogue_dismissed=True`: `get_current_act()` returns synthetic `aftermath` act. Director falls back to interval rhythm (every 2 scenes). Narrator gets "follow organically, no forced conclusion." "Wrap Up Story" button (appears in menu) re-offers epilogue.

### Narrator Systems

**Two-Call Pattern**: Narrator (Sonnet, pure prose) → Metadata Extractor (Haiku, Structured Outputs).

#### Seven Narrator Information Layers

1. **Conversation history**: Last 3 narrations as user/assistant pairs. Last narration untruncated; older at `MAX_NARRATION_CHARS` (1500).
2. **Factual timeline** (`_recent_events_block()`): Last 7 `session_log` entries as `<recent_events>` — ESTABLISHED FACTS Narrator must not contradict.
3. **Scene context** (`current_scene_context`): Single sentence from Extractor — situation + dominant mood/tension.
4. **Narrative state context** (`_status_context_block()`): Maps H/Sp/Su to 6 atmospheric stages each. Narrator reflects state through body language/sensation, never mentions numbers. Lives in user-prompt builders (not system prompt) to preserve caching.
5. **Active threat clocks** (`_narrator_clocks_block()`): All unfired clocks with fill + urgency descriptor (low/moderate/high/critical at 40%/65%/85%). Instruction: translate urgency to sensation and atmosphere, no game terms.
6. **Director arc context** (`arc_notes`): All three Director fields (`narrator_guidance`, `npc_guidance`, `arc_notes`) are independent — none silently suppresses another. `arc_notes` = background awareness only, not direct reference.
7. **NPC cross-relationship hints** (`_npc_relations_block()`): Mines `about_npc` memories across present NPCs → `<npc_dynamics>` block. Capped at 6 entries, deduplicated by NPC pair. Surface through subtext, never narrate directly.

#### Narrator Prompt Rules *(read before modifying `get_narrator_system()` or any prompt builder)*

- `PURE PROSE ONLY` — no JSON, no metadata templates, no JSON examples in any Narrator prompt. Never add role-label prefix (`"Narrator:"`).
- `<tone_authority>` block: player's chosen tone governs sentence rhythm, scene energy, NPC behavior. Director guidance must **never** override or dilute the tone.
- **SCENE CONTINUITY**: Begin in motion, not in setup. Same location: at most one bridging sentence. New location: one sensory impression of the new space.
- **EMOTIONAL CARRY-THROUGH**: Significant beats carry via body language, perception, attention — not narration. Emotional states do not reset between scenes.
- **SCENE ENDING**: Close with the character's immediate unresolved inner state, unanswered perception, or dominant open condition — not a plot cliffhanger. Mid-breath, not concluded.
- **PHRASE VARIETY**: `[noun] of a [person], who [relative clause]` pattern — AT MOST ONCE per response; ZERO if it appeared in any of the 3 preceding narrations. Same CROSS-RESPONSE rule for recurring atmospheric motifs (e.g. "Stille", "Kälte", "Dunkelheit") — if same motif anchored the last two narrations, switch sensory dimension.
- **NPC EMOTIONAL RANGE**: `instinct` field determines emotional register. Three NPCs in a scene ≠ three composed people. Volatile, irrational, disproportionate responses are correct when the instinct warrants them.
- **PRECISION**: Every sentence carries new information, advances tension, reveals character, or deepens atmosphere. No generic atmospheric filler.
- **TEMPORAL TEXTURE**: Even in static locations, every 2–3 scenes anchor one atmospheric time detail (light quality, temperature, ambient sound). Feeds Extractor's `time_update` detection. **Stale-time self-correction** (`TIME_STALE_THRESHOLD = 5`): `GameState.time_unchanged_scenes` counts consecutive scenes without a `time_of_day` change. At threshold, `_time_ctx()` injects an inline directive into the `<time>` tag in the Narrator prompt; `build_director_prompt()` emits `<current_time stale_scenes="N">` and adds a TIME RULE to the `narrator_guidance` instruction. Counter resets to 0 on any Extractor `time_update`, at chapter start, and when the Opening Extractor sets `time_of_day`.

#### Prose Cleanup (`parse_narrator_response()`)

10-step pipeline strips leaked metadata, code fences, JSON arrays/objects, bracket labels, markdown labels, trailing JSON, horizontal rules, em/en-dash normalization, role-label prefix, NPC disposition normalization, and sets `introduced=True` on NPC introduction. `_clean_narration()` in `app.py` is a lightweight safety net for edge cases.

#### Opening Metadata Extractor

`call_opening_metadata()` runs in `start_new_game()` and `start_new_chapter()` **instead of** the mid-game extractor. Full schema (agenda, instinct, secrets, clocks, location, scene_context, time_of_day, deceased_npcs) via `OPENING_METADATA_SCHEMA`. `known_npcs` parameter for chapter openings prevents re-extracting returning NPCs. Both start functions explicitly set `introduced=True` on all NPCs after `_process_game_data()`.

**NPC instinct definition** (applies to both opening extractor and Director `needs_profile`): *psychological signature under real pressure* — what the NPC specifically does when their strategy fails; what is slightly irrational but inevitable. BAD/GOOD concrete examples in prompt. SELF-CHECK: "could this apply to any competent professional in this genre?" = bad instinct. Genre-prior warning: situational composure in narration ≠ personality wiring.

**Extractor self-consistency rule**: If the Extractor's own `scene_context` describes an NPC as dying/dead, that NPC must appear in `deceased_npcs`. Catches slow/literary deaths spanning multiple turns.

### `##` Correction System

Players prefix `##` to correct the previous turn. Error type auto-detected; repair strategy selected accordingly.

**Turn Snapshot** (`_build_turn_snapshot()`): Created at every `process_turn()` start. Captures all turn-mutable fields: resources, counters, flags, spatial/temporal state, NPCs (deepcopy), clocks (deepcopy), director guidance, `story_blueprint` sub-fields (`bp_revealed`, `bp_triggered_transitions`, `bp_story_complete`, `bp_triggered_director_phases`). Both restore paths (`_restore_from_snapshot()` and `process_momentum_burn()`) use this snapshot.

`last_turn_snapshot` persisted in `SAVE_FIELDS`. `save_game()` converts `snapshot["roll"]` via `dataclasses.asdict()`; `load_game()` reconstructs via `RollResult(**r)`.

**Scene marker sync on location correction**: `_is_correction` branch updates the most recent scene marker string in `s["messages"]` before `render_chat_messages()`.

**NPC rename via correction**: `_apply_correction_ops()` captures `old_name` before edits; if renaming detected, `edits.pop("aliases")` discards Haiku's alias list (engine owns alias bookkeeping for renames); old name moved into aliases; new name stripped from aliases.

### Game Mechanics

**Stats**: edge, iron, wits, shadow, heart (sum = 7, range 0–3)

**Rolling** `roll_action()`: 2d10 (challenge dice c1, c2) vs min(2d6+stat, 10) (action score, capped at 10)
- Action > both challenge → **STRONG_HIT** (+2 momentum)
- Action > one challenge → **WEAK_HIT** (+1 momentum; `clash`/`strike` also cost health at risky/desperate)
- Action ≤ both challenge → **MISS** (-1 momentum)
- `c1 == c2` → **Match/Fate Roll** (~10% chance, narrative only)

**Tracks**: Health, Spirit, Supply (0–5), Momentum (-6 to +10)

**Momentum Burn**: `process_momentum_burn()` fully restores state from `last_turn_snapshot` (all turn-mutable fields including NPCs, clocks, chaos, resources) before applying new consequences.

**Chaos System**: Scene dice vs chaos threshold (3–9). Match on Miss → Chaos Interrupt (10 types).

**Clocks**: Progress clocks (1–12 segments). `_purge_old_fired_clocks(game, keep_scenes=3)` runs at `process_turn()` start — removes clocks fired >3 scenes ago.

**Clock advancement — four mechanisms (owner-aware)**:
- `apply_consequences()` on MISS: ticks first unfilled threat clock by 1 (or 2 on desperate)
- `apply_consequences()` on WEAK_HIT: position-scaled probabilistic tick (controlled=0%, risky=50%, desperate=100%)
- `_tick_autonomous_clocks()` (every scene, 20%): world-owned threat clocks only — NPC-owned excluded to prevent double-ticking
- `check_npc_agency()` (every 5 scenes): NPC-owned scheme+threat clocks +1; owner matched by normalized name + aliases

**`SAVE_FIELDS`**: Authoritative list of persisted fields — all other GameState fields are transient.

### Narrative Continuity (Chapter Transitions)

Extended chapter summary: `npc_evolutions` (projected NPC changes in time skip) + `thematic_question` + `post_story_location` (where protagonist ends up after epilogue). Architect receives `character_growth` and `thematic_question` from previous chapters. Chapter opening injects `<npc_evolutions>` as projections (hints, not facts).

`GameState.epilogue_text` persisted in `SAVE_FIELDS`. `generate_epilogue()` writes it; `start_new_chapter()` passes it to `call_chapter_summary()` then clears it — prevents bleed into chapter-3 summaries.

---

## NPC System

### NPC Status System

| Status | Sidebar | AI Context | Purpose |
|---|---|---|---|
| `active` | ✅ prominent | Full (agenda, memories, secrets) | Currently relevant NPCs |
| `background` | ✅ dimmed, collapsed | Brain name list only (target recognition) | Known NPCs, not currently present |
| `lore` | ✅ dimmed, collapsed | `<lore_figures>` slim block (name + 80-char desc) | Narratively significant, never physically present. Collect memories. Exempt from `MAX_ACTIVE_NPCS`. |
| `deceased` | ☠️ strikethrough, collapsed | `[DECEASED]` only | Protected from all merges |
| `inactive` | ❌ | ❌ | Legacy only — migrated to `background` on `load_game()` |

**Status transitions**:
- `active` → `background`: **Count path** (active > `MAX_ACTIVE_NPCS=12`, by relevance score: `last_memory_scene + bond×3 + current_scene_bonus+1000`) OR **Staleness path** (`bond=0` + `last_memory_scene` ≥ `NPC_STALE_SCENES=8` scenes past, only after scene 8, `last_memory_scene=0` treated as non-stale).
- `background` → `active`: When Brain identifies `target_npc`, Extractor matches known NPC, or memory update arrives.
- `lore` → `active`: Via `_reactivate_npc()` when figure physically appears. Lore NPCs always accumulate memories regardless of `scene_present_ids`.
- `active/background` → `deceased`: `_process_deceased_npcs()` on narrator-confirmed death. **"Narrator-confirmed" rule**: player need not witness directly — narrator depicting or unambiguously confirming the outcome suffices. Two-stage guard: (1) Extractor prompt distinguishes narrator-confirmed from dialog claims; (2) `scene_present_ids` code guard. Fallback: `_check_death_corroboration()` (cross-NPC vote mechanism). **Same-scene intro+death**: `new_npcs` carry optional `deceased: bool` flag; ID resolved after `_process_new_npcs()`; `_process_deceased_npcs()` called AFTER `_apply_memory_updates()` — scene memories stored first.
- `deceased` → `active`: Only on exact name match (`_reactivate_npc(force=True)`). Fuzzy matches blocked.

### Two NPC Creation Paths

1. **Opening scene** (`call_opening_metadata()`): Full schema — agenda, instinct, secrets, disposition, clocks, location, scene_context, time_of_day. Via `_process_game_data()`. **Auto-generates seed memory** for any NPC whose `memory` list is empty after the extractor's data is applied (mirrors mid-game path). Seed uses description or fallback appearance notice, disposition → emotional_weight mapping, `importance ≥ 3`, sets `last_memory_scene = scene_count`.
2. **Mid-game** (Extractor `new_npcs`): Minimal schema — name, description, disposition. Code fills defaults. Auto-generates seed memory.

**`_process_npc_details` extension check**: `old_norm in new_norm` only (one direction). The reverse `new_norm in old_norm` was intentionally removed — it allowed title-stripping by treating a shorter name as an "extension". Title differences are handled by `_is_title_only_difference()` instead.

**`_is_title_only_difference(old_norm, new_norm)`**: strips `_NAME_TITLES` words from both sides; returns True if the remaining cores are identical (non-empty). Used in three pipelines: `_process_npc_renames` (before `_merge_npc_identity`), `_process_npc_details` (before identity-reveal path), and `_process_new_npcs` (as `elif` branch alongside `stt_variant`). When True: keep the more complete name (more total words) as primary, register the shorter form as alias — no full identity merge. Handles title-add, title-remove, and title-swap across all creation and rename paths.

### Six-Layer Anti-Duplicate Safety Net

1. **`npc_renames`** → `_merge_npc_identity()`: old name → aliases, new name → primary. Richness-aware merge direction: if `dup` scores higher (memory count×2 + bond×2 + agenda×3 + instinct×3 + desc×1), dup's substantive fields overwrite original's. Clock-owner sync on rename via normalized matching. **Established-character guard**: if targeted NPC has memories OR agenda set, AND its current name is a proper name (not a descriptor placeholder — see `_is_descriptor_name()`), AND new name shares zero words with name+aliases → rename rejected; new NPC stub created instead. Descriptor-named NPCs (leading article/unknown-marker) always pass through to allow legitimate identity reveals.
2. **Fuzzy name match** (`_process_new_npcs()`): substring overlap, word overlap, STT-variant (Levenshtein ≤ 1), title-variant (`_is_title_only_difference` — adds alias, no rename).
3. **Description match** (`_description_match_existing_npc()`): word overlap + compound decomposition + Long-Compound-Bonus (≥12 chars = 1.5×). Threshold ≥25% OR one long match ≥2.0. Spatial guard: skips candidates at different location.
4. **`_apply_memory_updates()`**: Presence guard — memory updates for absent known NPCs rejected. Exemptions: fresh NPCs, auto-stubs, lore/deceased, formerly-lore NPCs (`pre_turn_lore_ids`).
5. **`_process_npc_details()` identity-reveal fallback**: Established Guard — if existing NPC has memories OR agenda set AND new name shares zero normalized words with name+aliases → reject rename, create fresh stub. Descriptor-named NPCs exempt. Guard extended from `memory`-only to `memory OR agenda` to protect Opening Extractor NPCs (agenda set on creation, no memories yet in first scene).
6. **Slug resolution** `_resolve_slug_refs()`: snake_case slugs → real `npc_id`s for same-cycle cross-references. Runs between `_process_new_npcs()` and `_apply_memory_updates()`.

**Always use `_find_npc()`** as search entry point — never iterate `game.npcs` by name directly.  
Search chain: exact ID → normalized name → normalized alias → **title-aware core match (3b)** → substring name (min 5 chars) → substring alias. Step 3b strips `_NAME_TITLES` from both ref and stored names and returns the NPC only when there is exactly ONE unambiguous core match (ambiguity guard prevents false positives when two NPCs share the same untitled core).

**`_normalize_for_match(s)`**: collapses hyphens/underscores/whitespace → single space, lowercase, strip. Stored names **never** modified — comparison-only.

### NPC Memory System

Each memory: `importance` (1–10), `type` (`observation` | `reflection`), `emotional_weight`, `scene`, optional `about_npc`.

**Weighted retrieval** `retrieve_memories()`:
```
Score = 0.40 × Recency + 0.35 × Importance + 0.25 × Relevance
```
Exponential recency decay (`0.92^scene_gap`). Reflections: floor 0.6, always ≥1 guaranteed. `about_npc` boost: +0.6 when referenced NPC is present in scene.

**Consolidation**: Reflections always kept (max 8), observations by budget split (60% recency + 40% importance). Total max 25 entries.

**Reflection trigger**: `importance_accumulator` incremented per memory. At `REFLECTION_THRESHOLD` (30): `_needs_reflection=True`. NPCs with empty `agenda`/`instinct` also included via `needs_profile="true"` (independent of accumulator — peripheral NPCs get profiled without needing 30 importance). Director Dual-Tone: `tone` (1–3 words, narrative compound) + `tone_key` (single word enum).

**NPC-to-NPC relationships (`about_npc`)**: No separate relationship system — relationships emerge organically from tagged memories. Extractor must capture player-initiated NPC-to-NPC communication (gossip, warnings, lies) with `about_npc`. Self-reference guard: `_resolve_about_npc()` returns `None` if resolved NPC ID == owning NPC.

**TF-IDF NPC Activation** (`_compute_npc_tfidf_scores()`): Zero-dependency TF-IDF cosine similarity. Builds profiles from name, aliases, description, agenda, last 5 observations. ≥0.7 score → full activation (max 3).

**Three-Tier Prompt Context**:
- **Target NPC** (`<target_npc>`): Fullest — agenda, instinct, weighted memories (insight/recent/npc_views), secrets, aliases
- **Activated NPCs** (`<activated_npc />`): Medium — name, disposition, bond, 1–2 best memories
- **Known NPCs** (`<known_npcs>`): Compact — name + disposition list

**Spatial tracking** (`last_location`): Updated only for `scene_present_ids` NPCs. Prompt builders inject `last_seen="..."` (activated) and `[at:Location]` (known). SPATIAL CONSISTENCY rule: NPCs at other locations cannot physically interact.

**Absent-NPC mention memories**: `memory_updates` can carry `absent: bool` flag. Bypasses presence guard; stored as `type="mention"`, `importance=3`. Cap: max 2 absent-mention entries per scene.

### Social Moves & Bond Mechanics

`SOCIAL_MOVES = {"compel", "make_connection", "test_bond"}`

| Move | WEAK_HIT | STRONG_HIT |
|---|---|---|
| `compel` | — | — |
| `make_connection` | bond +1 | bond +1, disposition ↑ one step |
| `test_bond` | — | bond +1, disposition ↑ one step |

MISS (all three): bond -1, spirit -1 or -2. Disposition ladder: `hostile → distrustful → neutral → friendly → loyal`. `loyal` requires `make_connection` or `test_bond` — cannot be compelled. Director-driven disposition shifts: Director can propose one-step `disposition_shift` ("improve"/"worsen") via `npc_reflections` — rare by design.

---

## Known Pitfalls & Anti-Patterns

*Hard-won lessons. Read before making changes.*

### NiceGUI / DOM
- **Vue reconciliation**: `ui.markdown()` uses `v-html` — all JavaScript DOM mutations (innerHTML patching, TreeWalker, MutationObserver) silently overwritten on next render. Server-side Python markup is the only reliable approach.
- **DOMPurify**: `sanitize=True` (default) strips injected `<span>` tags inside the `v-html` pipeline. The only reliable way to inject spans post-render is JS DOM manipulation (`_etHighlight()`). Dialog highlighting uses server-side `***Markdown***`. **Never prepend `<span class="sr-only">` to `ui.markdown()`** — span stripped, text stays visible. `ui.html()` wraps in a block `<div>` so `position: absolute` spans bleed. **Correct pattern for screen-reader attribution: `aria-label` on the container** (`.props('aria-label="..."')`).
- **Desktop Quasar drawer**: `ui.html()` innerHTML strips `class=` and `style=` on child elements inside a persistent drawer. Use `ui.element()` + `.style()` chain.
- **Touch tooltips**: `ui.tooltip()` unreliable on touch — use `_info_btn()` (click-to-dismiss `ui.menu()`) for settings UI.
- **`<h2>` font-size**: Browser default sets `<h2>` to ~1.5rem; `em`-based CSS compounds. Use `<div>` with direct `rem` sizing.

### AI / Tokens
- `max_tokens` is an upper bound, not a cost factor — always set generous headroom.
- **German ≈ 15–20% more tokens** — Director and Narrator budgets must account for this.
- Token budget constants are named module-level constants — never hardcode inline.
- **Structured Outputs replaced JSON repair** — do not reintroduce `json.loads(repair(text))` patterns.
- Narrator `PURE PROSE ONLY` rule — never add metadata templates or JSON examples to Narrator prompts; never add role-label prefixes.
- **Director `_bg_director` race condition**: `reset_stale_reflection_flags()` MUST be called on early-return — or `_needs_reflection` flags accumulate indefinitely (zombie-reflection loop). Diagnostic: if `importance_accumulator` == sum of all NPC memory importances and `last_reflection_scene=0`, Director has never completed for that NPC.

### NPC System
- Six-layer anti-duplicate system is delicate — test changes against all six layers.
- **Always use `_find_npc()`** — never iterate `game.npcs` directly by name.
- Deceased NPCs protected from fuzzy and description matches — only exact matches can trigger resurrection.
- `_apply_name_sanitization()` must be called at all four NPC entry points — missing one causes descriptor strings to persist as aliases.
- `scene_present_ids` must be passed to `_process_deceased_npcs()` — safety gate against false death reports.
- **`_find_npc()` comma-split**: Brain occasionally returns `target_npc` as comma-separated string. `_find_npc()` splits on commas, resolves only first token. Empty-string guard follows.

### Persistence
- **`SAVE_FIELDS`** is authoritative — transient fields not in it are silently dropped on save.
- `RollResult` dataclass in snapshots requires `dataclasses.asdict()` for JSON — `json.dumps` raises `TypeError`.
- `load_game()` is the backward-compatibility boundary — new fields must have sane defaults for old saves.
- `revelation_check` after momentum burn: `process_momentum_burn()` restores blueprint state — `pop("revelation_check", None)` from `session_log[-1]` required or log reports confirmed while blueprint treats it as pending.

### i18n
- Every user-visible string through `t(key, lang)` — no hardcoded strings.
- ARIA labels need **both** `de` and `en` entries.
- Voice/TTS labels resolved via `resolve_voice_id()` / `resolve_tts_backend()` — never assume label == ID.

### Deployment (Pi + Windows Dev)
- **PowerShell after SSH password prompts**: use `;` not `&&` — `&&` silently fails after a password prompt.
- SFTP auto-sync (`uploadOnSave: true`) pushes on save — restart the service after pushing `engine.py`.
- `edgetales_monitor.py` (watchdog + IONOS SMTP) is a separate service — don't confuse its log with app errors.

### Savegame Diagnostics (field name gotchas)
- `memory` (not `memories`), `last_location` (not `last_seen_scene`), `clock_type` (not `type`)
- `npcs` is a list not a dict; stats are flat on the dict
- Suspected bugs **must** be verified against `engine.py` source before concluding — false positives are common in savegame analysis

---

## Design Decisions

| Decision | Rejected Alternative | Reason |
|---|---|---|
| Server-side Python markup for entity highlighting | JavaScript DOM mutation after render | NiceGUI Vue reconciliation silently overwrites all JS DOM changes |
| Structured Outputs for all AI JSON calls | JSON repair (`json.loads(repair(text))`) | Eliminates entire error class; guarantees valid schema |
| Deferred Director (non-blocking, post-save) | Blocking Director before player sees narration | Reduces player-facing latency from ~4s to ~2.5s |
| Haiku for Brain/Director/Metadata, Sonnet for Narrator/Architect | Sonnet everywhere | Haiku ~10× cheaper and fast enough for structured-output tasks |
| Parallel Narrator + Story Architect at game start | Sequential calls | Halves startup wait (~15s vs ~30s) |
| `about_npc` field on memories (emergent relationships) | Dedicated NPC relationship data structure | No added complexity; relationships emerge organically from existing memory infrastructure |
| Fuzzy location matching (`_locations_match()`) | Strict string equality | "Main Hall" vs "the main hall" must not create spatial inconsistencies |
| Creativity seeds via `wonderwords` with explicit use-instruction | No seeds / random seeds without instruction | Without explicit instruction, seeds only shift atmosphere — not NPC names (convergence problem) |
| Shelved: NPC secret alias system | Implement it | Architecturally invasive; would destabilize core NPC/alias/merge systems |
| Opening Metadata Extractor (Haiku, separate call) | Narrator fills `<game_data>` JSON inline | Inline JSON in prose = entire error class. Separate call with Structured Outputs is clean. |
| `copy.copy(game)` snapshot for Architect thread | Shared reference | `parse_narrator_response()` mutations on main thread would race-condition Architect's input |
| `_xa(s)` helper for XML attribute escaping | Manual `.replace('"', '&quot;')` | Manual replace only covers `"` — misses `<` and `&`. `html.escape(str(s), quote=True)` covers all three. |
| `html.escape()` for XML element content | No escaping | AI-generated text in element positions can contain `<` or `&` — silently corrupts prompt structure |
| Engine owns alias bookkeeping on NPC rename | Let Haiku manage aliases in `npc_edit` | Haiku overwrites alias list before engine can preserve old name. `edits.pop("aliases")` makes engine sole authority. |

---

## i18n Reference

All UI strings in `i18n.py`. Structure: `TRANSLATIONS: dict[str, dict[str, Any]]`. Access via `t(key, lang)` where `lang ∈ {"de", "en"}`.

Key translation functions:

| Function | Purpose |
|---|---|
| `t(key, lang)` | Main lookup — returns string or raises KeyError |
| `ta(key, lang)` | ARIA label variant (separate `ARIA_LABELS` dict) |
| `get_genre_label(code, lang)` / `get_tone_label(code, lang)` / `get_archetype_label(code, lang)` | Code → localized label |
| `get_story_phase_labels(lang)` | Story arc phases: `{"setup": "Exposition", ...}` |
| `translate_consequence(text, lang)` | Consequence keys → target language (word-boundary regex, backward compat) |

**Archetype codes** (stable Dict keys in `_ARCHETYPE_PRIMARY_STAT` / `_ARCHETYPE_STAT_DEFAULTS` — renaming requires updating those structures):  
`outsider_loner`, `investigator`, `trickster`, `protector`, `hardboiled`, `scholar`, `healer`, `inventor`, `artist`  
Note: `protector` displays as "Krieger"/"Warrior"; `trickster` displays as "Trickbetrüger"/"Con Artist".

**Genre codes:** `dark_fantasy`, `high_fantasy`, `science_fiction`, `horror`, `mystery`, `steampunk`, `cyberpunk`, `urban_fantasy`, `victorian_crime`, `roman_empire`, `fairy_tale`, `slice_of_life_90s`, `outdoor_survival`, `post_apocalyptic`

**Tone codes:** `dark_gritty`, `grounded_drama`, `melancholic`, `absurd_grotesque`, `slow_burn_horror`, `cheerful_funny`, `romantic`, `slapstick`, `epic_heroic`, `pulp`, `cozy`, `tragicomic`

**Legacy code mapping** (may appear in old saves; `get_genre_label()`/`get_tone_label()` fall back to raw code string):  
`horror_mystery` → split `horror` + `mystery`; `historical_roman` → `roman_empire`; `serious_balanced` → `grounded_drama`; `tarantino` → `pulp`

---

## Elvira Test Bot

> ⚠️ **Internal only.** `elvira/` excluded from public GitHub repo. Never mention in `CHANGELOG.md`.

**Purpose**: Headless AI test player driving `engine.py` directly (bypassing NiceGUI). Generates realistic savegames and session logs for regression analysis. Uses Claude Haiku as player brain.

### File Layout

```
elvira/
├── elvira.py               — Bot entry point, session logic, 13-step turn loop
├── elvira_config.json      — Configuration (fully documented inline in the file)
├── logs/
│   └── elvira_engine_YYYY-MM-DD.log  — Raw engine log (redirected from rpg_engine logger)
└── elvira_session.json     — Primary diagnostic output
```

API key read from `config.json` (same file as main app).

**Director in Elvira**: `run_deferred_director()` called **synchronously** — unlike the UI which runs it as async background task. Ensures Director results always captured in the same save.

### Usage

```bash
python elvira/elvira.py                        # runs with elvira_config.json
python elvira/elvira.py --auto                 # Haiku picks all parameters freely
python elvira/elvira.py --turns 30             # override max turns per chapter
python elvira/elvira.py --config other.json    # custom config
```

Bot styles: `explorer`, `aggressor`, `dialogist`, `chaosagent`, `balanced`. `chaosagent` best for stress-testing edge cases. `aggressor` always burns momentum (no Haiku decision call).

### `elvira_session.json` — Primary Diagnostic File

**Top-level fields**: `engine_version`, `config` (full snapshot), `style`, `auto_mode`, `started_at`, `ended_at`, `total_turns`, `character`, `game_context` (genre/tone/archetype/wishes/stats), `story_blueprint` (structure_type, central_conflict, acts[], revelations, possible_endings), `chapters[]`, `violations[]`, `ended_reason`, `final_state` (incl. `triggered_transitions`, `triggered_director_phases`)

**Per-turn fields** (`turns[]`): `turn`, `chapter`, `scene`, `location`, `action`, `narration`, `narration_excerpt` (first 300 chars), `roll` (stat, d1, d2, action_score=min(d1+d2+stat,10), c1, c2, result, match, `burn_result` if burned), `burn_offered`/`burn_taken`, `director_ran`, `state_after` (health/spirit/supply/momentum/chaos/scene/location/time/scene_context/npc count/clock count), `npcs[]` (full snapshot: id/name/status/disposition/bond/agenda/instinct/arc/memory_count/last_memory/aliases), `clocks[]` (all incl. fired), `director_guidance` (only when `director_ran=true` — stale suppressed: narrator_guidance/pacing/arc_notes/act_transition/npc_reflections[]), `engine_log` (mirrors `session_log[-1]`: rich_summary/move/position/effect/dramatic_question/chaos_interrupt/director_trigger/consequences/clock_events/npc_target/npc_activation; conditional: `warnings`, `revelation_check`, `act_transitions`), `story_arc` (phase/title/goal/mood/story_complete), `violations[]`

### When to Use Which File

| File | Use for |
|---|---|
| `elvira_session.json` | Primary analysis — complete turn-by-turn audit trail |
| `users/elvira/saves/<n>.json` | Reload in UI; input for further Elvira runs (`load_existing: true`) |
| `users/elvira/saves/chapters/<n>/` | Full chat history per completed chapter |
| `elvira/logs/elvira_engine_*.log` | Deep engine internals when session.json shows an error |

---

*Changelog and detailed change history: `CHANGELOG.md`*  
*User documentation: `README.md`*
