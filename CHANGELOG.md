# Changelog

All notable changes to EdgeTales are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [0.9.35]

### Added
- **`##` Correction System:** Players can prefix any input with `##` to correct a misunderstanding or wrong game state from the last turn. Two correction types are handled automatically:
  - **`input_misread`:** Brain misunderstood what the player did/said/thought. Full state rollback from `last_turn_snapshot`, Brain re-run with corrected intent, optional re-roll if the stat changes. Narrator rewrites the scene with a `<correction_context>` tag injecting specific guidance
  - **`state_error`:** World facts are wrong (wrong NPC identity, location, relationship). State patched in-place via atomic `state_ops` — no rollback, no re-roll, Narrator rewrites with corrections applied
- **`CORRECTION_OUTPUT_SCHEMA`:** Structured Output schema for the correction Brain. Fields: `correction_source`, `corrected_input`, `reroll_needed`, `corrected_stat`, `narrator_guidance`, `director_useful`, `state_ops[]`
- **`call_correction_brain()`:** Haiku call that analyses the `##` text against the last turn snapshot (player_input, brain, roll, narration) and returns a structured ops-dict. Graceful fallback to no-op `state_error` on API failure
- **`_apply_correction_ops()`:** Atomic state operation dispatcher. Supported ops: `npc_edit` (patch NPC fields), `npc_split` (one NPC → two, new UUID), `npc_merge` (absorb memories + aliases, remove source), `location_edit`, `scene_context`, `time_edit`, `backstory_append`
- **`_restore_from_snapshot()`:** Full GameState rollback for `input_misread` corrections. Restores all turn-mutable fields (resources, counters, spatial, narrative state via deepcopy), trims `session_log` and `narration_history` by one entry
- **`process_correction()`:** Main correction orchestrator. Dispatches by `correction_source`, re-runs Brain/Roll/Narrator as needed, updates session_log/narration_history in-place, optionally queues deferred Director when NPC state changed meaningfully
- **Correction badge:** Corrected narrator messages show a subtle `✎ Korrigiert` / `✎ Corrected` badge (new `.correction-badge` CSS class). New i18n keys: `correction.badge`, `correction.no_snapshot`
- **Turn snapshot system (`last_turn_snapshot`):** Transient GameState field (not in SAVE_FIELDS) capturing the full pre-turn state before any mutations — used by both the `##` correction flow and the existing momentum burn restore. Populated at the start of `process_turn()` via `_build_turn_snapshot()`
- **Creativity seed for output diversity:** `_creativity_seed()` generates 3 random words (nouns/adjectives) via the `wonderwords` library to perturb LLM token probabilities during character and scene generation. Injected into `call_setup_brain()` (character/world), `build_new_game_prompt()` (opening scene), and `build_new_chapter_prompt()` (chapter opening). Each seed includes an explicit instruction `"Use as loose inspiration for NPC names, locations, and scene details"` — without this, generic random words only shifted setting/atmosphere but Sonnet still converged on the same NPC names. The instruction anchors the seed words to the name-token decision. Solves deterministic convergence where identical archetypes (e.g. "plumber") always produced the same NPC names and scenarios. Built-in 30-word fallback list if wonderwords is unavailable. All three injection points log the seed value for diagnostics (`[Setup] creativity_seed=...`, `[Narrator] Opening creativity_seed=...`, `[Narrator] Chapter N opening creativity_seed=...`)
- **`wonderwords` dependency:** Added to `_REQUIRED` packages in `_ensure_requirements()` — auto-installed on first launch. Provides offline random English word generation (nouns, adjectives, verbs) with filtering by part of speech, length, and pattern

### Changed
- **`process_player_input()` (app.py):** `##` prefix detected before normal turn dispatch. If no snapshot is available, `ui.notify()` with `correction.no_snapshot` is shown and processing aborts early. Correction result replaces the last `assistant` message in `s["messages"]` (with `"corrected": True` flag) instead of appending. Chat container fully re-rendered via `render_chat_messages()` on correction

### Fixed
- **Double consequence application in `state_error` corrections:** `process_correction()` called `apply_consequences(game, roll, brain)` in the `state_error` path even though consequences were already applied by the original `process_turn()`. Without a rollback, this doubled all mechanical effects: health/spirit/supply/momentum deductions, clock ticks, bond changes, and crisis flags. Fix: read original consequences from `session_log[-1]` for prompt-building only, never re-apply them
- **Double chaos factor / scene intensity update in `state_error` corrections:** `update_chaos_factor()` and `record_scene_intensity()` were called unconditionally in Step 5, but for `state_error` corrections the original turn already recorded both. Fix: chaos and intensity updates now only run for `input_misread` (fresh re-run after rollback)
- **Session log / narration history corruption in `input_misread` corrections:** `_restore_from_snapshot()` correctly pops the last session_log and narration_history entries, but Step 5 used `[-1] = entry` (overwrite) instead of `append()` — replacing the entry *before* the corrected turn instead of adding the new one. Fix: `input_misread` now appends with proper length-cap trimming; `state_error` preserves original consequences/clock_events and only updates the summary text
- **Python 3.11 f-string syntax error on startup:** `_story_context_block()` used a backslash-escaped quote inside an f-string expression (`f'{" PAST_RANGE=\"true\"" ...}'`) — valid in Python 3.12+ but crashes with `SyntaxError: f-string expression part cannot include a backslash` on Python 3.11. Fix: extracted the conditional to a variable before the f-string

---

## [0.9.34]

### Added
- **Deceased NPC system:** New `status="deceased"` for NPCs killed during play. Metadata Extractor schema extended with `deceased_npcs` field — reports NPCs who die on-screen in the current narration. `_process_deceased_npcs()` sets status before memory updates run, ensuring dead NPCs are immediately excluded from all active processing
- **Deceased NPC guards:** Comprehensive protection across the NPC lifecycle: `_apply_memory_updates()` triggers resurrection instead of skipping; `_reactivate_npc()` blocks reactivation unless `force=True`; `_process_new_npcs()` refuses fuzzy-match and description-match merges into deceased NPCs (treats them as genuinely new characters); `_process_npc_renames()` skips deceased NPCs
- **NPC resurrection:** When a deceased NPC reappears physically (necromancy, undead, etc.), exact name match in `new_npcs` or `memory_updates` from the Metadata Extractor triggers `_reactivate_npc(force=True)` — NPC returns to `active` with full history intact. Fuzzy matches remain blocked to prevent accidental merges with similarly-named new characters
- **Deceased NPC sidebar section:** Collapsed ☠️ section shows deceased NPCs with strikethrough styling. New i18n keys `sidebar.deceased_persons` (DE: "Verstorben", EN: "Deceased")
- **`move` field in session_log:** Both dialog and action paths now write `brain.get("move")` to session_log entries. Previously missing entirely, limiting diagnostics and Director context

### Fixed
- **Dead NPCs remained active:** NPCs killed in narration kept `status=active` — continued receiving memory updates, reflections, appeared in prompts, and could be merged with new characters via fuzzy matching. Root cause: engine had no concept of NPC death. Savegame evidence: Kravik (shot in scene 19) received observation + reflection in scene 20 from new Trandoshaner characters misidentified as him
- **Two characters merged into one NPC slot:** When two NPCs of the same species/group appeared together (e.g. two Trandoshaner), the Metadata Extractor's fuzzy matching or description matching could merge them into a single NPC. When one died, the survivor's identity was absorbed into the dead one's slot. Now: deceased NPCs are excluded from all merge paths — new characters with similar descriptions become their own NPCs
- **`start_new_chapter()` death detection was fragile:** Chapter transitions detected dead NPCs by scanning for text markers in names and descriptions (`"(getötet)"`, `"killed"`, `"deceased"`). Replaced with clean `status == "deceased"` check — the canonical source of truth

### Changed
- **Director `act_transition` prompt improved:** `transition_trigger` extracted from dense XML attribute into its own `<transition_trigger>` tag for visibility. Director now sees `current_scene` and `scene_range` in `<story_arc>`, plus `PAST_RANGE="true"` flag when scene count exceeds range. Instruction rewritten from cautious ("when in doubt, set false") to evaluative: trigger clearly met → true; past range + spirit met → true; otherwise false. Emphasizes that content-driven transitions produce better pacing than scene_range fallback
- **Metadata Extractor NPC reference list:** Includes deceased NPCs marked `[DECEASED]` so the extractor can distinguish living from dead characters and avoid generating memories for the dead

---

## [0.9.33]

### Added
- **Structured Outputs for all JSON-returning AI calls:** Brain, Setup Brain, Director, Story Architect, and Chapter Summary now use Anthropic's Structured Outputs (`output_config` with `json_schema`) instead of free-form JSON with post-hoc repair. Schemas defined as module-level constants: `BRAIN_OUTPUT_SCHEMA`, `SETUP_BRAIN_OUTPUT_SCHEMA`, `DIRECTOR_OUTPUT_SCHEMA`, `STORY_ARCHITECT_OUTPUT_SCHEMA`, `CHAPTER_SUMMARY_OUTPUT_SCHEMA`
- **Narrator metadata extraction via Two-Call pattern:** New `call_narrator_metadata()` uses Haiku with Structured Outputs (`NARRATOR_METADATA_SCHEMA`) to extract game state changes (scene_context, location, time, memory_updates, new_npcs, npc_renames, npc_details) from narrator prose in a separate call. `_apply_narrator_metadata()` delegates to existing `_process_*` functions via JSON roundtrip. Three callsites: dialog, action, momentum burn
- **TF-IDF NPC activation:** New `_compute_npc_tfidf_scores()` replaces keyword-based NPC activation with zero-dependency TF-IDF cosine similarity. Builds NPC profiles from name, aliases, description, agenda, and last 5 memories. IDF naturally weights rare words (proper nouns, RPG terms) higher. Single computation per scene, shared across all NPCs. Max contribution raised 0.4 → 0.5 with noise threshold 0.05
- **Simplified stopwords:** `_STOPWORDS` module-level constant (DE+EN, ~130 words) replaces the dynamic 18-language loading system. Used only by `_description_match_existing_npc()` for duplicate detection
- **Cyrillic homoglyph sanitizer:** `_CYRILLIC_TO_LATIN` translation map (16 Cyrillic→Latin pairs) + context-aware `_fix_cyrillic_homoglyphs()` — only replaces Cyrillic chars in mixed-script words, preserves pure Cyrillic (Russian/Ukrainian) text. Applied in `call_narrator()`
- **STT variant matching:** `_edit_distance_le1()` Levenshtein distance ≤ 1 function + Step 4 in `_fuzzy_match_existing_npc()`. Catches single-char STT transcription errors (Chan→Chen, Wang→Wong, Meyer→Meier). Title-aware safety rules prevent false positives. `_fuzzy_match_existing_npc()` returns `(npc, match_type)` tuple to distinguish identity reveals from STT variants
- **NPC spatial tracking (`last_location`):** New field on every NPC, set at creation and updated on each memory. Prompt builders inject `last_seen` (activated NPCs) and `[at:Location]` (known NPCs) when location differs from player's current position. Expanded SPATIAL CONSISTENCY rule prevents narrator from having distant NPCs interact physically
- **Narrative Continuity Pipeline:** Three-part system for richer chapter transitions informed by drama theory (serialized TV structure, RPG campaign arcs):
  - **Chapter Summary extended:** `npc_evolutions` (projected NPC changes during time skip) and `thematic_question` (vertical emotional arc across chapters) added to `CHAPTER_SUMMARY_OUTPUT_SCHEMA`. Gives the Chapter Opening narrator concrete material for showing how the world evolved.
  - **Transition Triggers:** `transition_trigger` field on every act in `STORY_ARCHITECT_OUTPUT_SCHEMA`. Narrative conditions (player actions or story events) that signal act completion, replacing rigid scene-number boundaries. `scene_range` retained as fallback. Director evaluates trigger fulfillment via `act_transition` boolean; `get_current_act()` uses dual logic (trigger-first, scene_range-fallback). Tracked in `story_blueprint["triggered_transitions"]`.
  - **Thematic Thread:** `thematic_thread` field in blueprint, injected into every narrator prompt via `_story_context_block()`. Combined with `character_growth` + `thematic_question` from previous chapters, creates a vertical emotional narrative that persists across chapters.

### Fixed
- **Metadata Extractor silent failure:** `call_narrator_metadata()` used `extra_params={"output_config": ...}` instead of `output_config=...` as a direct kwarg. `_api_create_with_retry(**kwargs)` passed the nested dict to `client.messages.create()` which silently ignored the unknown parameter — Haiku responded as freetext instead of Structured Output, `json.loads()` failed, and the `except` block returned an empty fallback dict. Result: zero new NPCs discovered, zero memory updates, frozen scene_context across all scenes. Location/time updates still worked because they come from Brain, not the metadata extractor. Fix: single-line change from `extra_params={...}` to `output_config={...}`
- **Player authorship — name/content correction:** Narrator "polished" player words beyond grammar, correcting typos (`thornwall` → `Thornhill`), converting numbers to words (`5` → `fünf`), and capitalizing informal text. New `PRESERVE EXACTLY` rule: only punctuation and sentence-start capitalization are permitted changes. Wrong names, typos, slang, and informal language are canonical — they represent what the character actually said
- **Player authorship — invented dialog from action descriptions:** When player described a speech act without exact words (e.g. "I ask him about Thornhill and describe him"), the narrator invented specific quoted dialog with fabricated details (physical description the player never specified). New `DESCRIBED SPEECH` rule: action-described speech must be narrated as indirect speech or brief summary, never as invented quoted dialog for the player character
- **Player character created as NPC:** Metadata extractor had no knowledge of the player character's name — saw it in narration and created it as `new_npcs`. Guard in `_process_new_npcs()` only checked exact full-name match (`"hermann" != "hermann speedlaser"` → passed). NPC then got renamed via `npc_details` to full player name, received Director agenda/instinct/reflections, and activated via TF-IDF on every scene. Fix: (a) metadata extractor prompt now includes `<player_character>` with explicit exclusion instruction, (b) all player-name guards (`_process_new_npcs`, `_process_npc_renames`, `_apply_memory_updates` auto-stub) upgraded from exact-match to name-part intersection (any shared word blocks creation)
- **NPC descriptions as scene observations:** Metadata extractor produced event-like descriptions ("Der Chef, der laut Androhung Bernie zu Dünger verarbeiten könnte") instead of physical/role descriptions. New instruction: `description must be a PHYSICAL/ROLE description (appearance, occupation, species), NOT what they did in this scene`
- **Cyrillic homoglyph contamination in narrator output:** Sonnet occasionally emits Cyrillic lookalike characters (е/U+0435 instead of e/U+0065, о/U+043E instead of o/U+006F, т/U+0442 instead of t/U+0074, etc.) in otherwise Latin text, producing visually broken words like `kniест` instead of `kniest`. New context-aware `_fix_cyrillic_homoglyphs()` only replaces Cyrillic chars in mixed-script words (Latin+Cyrillic in same word) — purely Cyrillic words (authentic Russian/Ukrainian) are left untouched. Applied in `call_narrator()` before return
- **Deceased/mentioned characters created as NPCs:** Metadata extractor created NPCs for characters who were only mentioned in conversation or seen in photos, not physically present. Savegame evidence: "Tommy Chen" (deceased brother on photos) merged with "Wongs Mutter" (physically present) — extractor assigned the mentioned name to the present person's description, creating a ghost NPC with wrong identity, wrong memories, and an alias pointing to a completely different character. Fix: `call_narrator_metadata()` system prompt now explicitly distinguishes PHYSICALLY PRESENT characters (speaking, acting, reacting) from merely MENTIONED ones (in dialog, photos, memories, backstory). Exclusion list: deceased persons, historical/absent figures, unnamed roles. Anti-fusion rule: when a named person is mentioned in dialog but a different unnamed person is physically present, the NPC must be created for the physical person with their own name/description. Memory updates also restricted to physically present NPCs only
- **STT transcription variants creating duplicate NPCs:** Voice input (faster-whisper STT) transcribed "Mrs. Chen" as "Mrs. Chan" and "Mr. Wong" as "Mr. Wang" — single-vowel differences that bypassed fuzzy matching (≥5 char word overlap rule rejected "Chen"=4 chars). Metadata extractor created duplicate NPCs for the same character. Savegame evidence: npc_2 "Mrs. Chen" (active, bond=1, 5 memories) and npc_5 "Mrs. Chan" (background, bond=0, 1 memory). Fix: new `_edit_distance_le1()` function + Step 4 in `_fuzzy_match_existing_npc()` checks title-stripped name parts for Levenshtein distance ≤ 1. Safety rules: matching titles required when both have titles, ≥3 chars per name part, single untitled word needs ≥5 chars. STT matches add the variant as alias (for future exact-match hits) without renaming the existing NPC. `_fuzzy_match_existing_npc()` now returns `(npc, match_type)` tuple — `"identity"` for normal matches (triggers rename via `_merge_npc_identity()`) or `"stt_variant"` for edit-distance matches (adds alias only)
- **Markdown emphasis leaking into narration:** Narrator used `*word*` for emphasis and `*multi-word phrases*` for signs/thoughts, despite `PURE PROSE ONLY` rule. Orphaned asterisks (opening `*` without closing) appeared as visible characters in the UI; paired asterisks created unwanted markdown rendering and broke TTS. Fix: (a) `PURE PROSE ONLY` rule now explicitly prohibits `*italics*`, `**bold**`, `# headings` and instructs typographic emphasis via word choice instead, (b) `parse_narrator_response()` Step 8 now strips `***...***, **...**, *...*` paired emphasis and removes remaining orphaned `*` characters
- **NPC location teleportation:** NPCs at distant locations appeared to be physically present — heard through walls, interacting with the player, reacting in real-time — because the narrator had no information about where NPCs were last seen. Savegame evidence: Mr. Wong's workshop was on Canal Street (Chinatown), but in scenes 17-18 his mother's voice came "through the ceiling" of Mike's Brooklyn basement, and Officer Ramirez walked "down the stairs" to speak with Wong as if the workshop were next door. Fix: new `last_location` field on every NPC, set when NPCs are created and updated whenever they receive a memory. Prompt builders inject `last_seen="..."` (activated NPCs) and `[at:...]` (known NPCs) when an NPC's last location differs from the player's current location. Expanded SPATIAL CONSISTENCY rule tells the narrator that NPCs at different locations cannot be heard, seen, or interact directly — they must plausibly travel to the player's location first

### Removed
- **`_auto_generate_keywords()`** (~75 lines): Keyword generation from NPC names/descriptions — replaced by TF-IDF
- **`_build_other_npc_names()`** (~17 lines): Cross-contamination filter helper — no longer needed
- **`_get_keyword_stopwords()`** (~10 lines): Language-aware stopword combiner — replaced by `_STOPWORDS` constant
- **`_NARRATION_LANG_TO_ISO`** (~20 lines): 18-language ISO code mapping — no longer needed
- **`_stopwords_cache` + `_load_stopwords()`** (~20 lines): Dynamic per-language stopword loading
- **`_BASE_KEYWORD_STOPWORDS` + `_RPG_KEYWORD_STOPWORDS`** (~45 lines): RPG-specific stopword lists
- **`_repair_json()`** (~45 lines): JSON repair for LLM output (trailing commas, missing commas, unescaped newlines) — Structured Outputs guarantee valid JSON
- **`_close_truncated_json()`** (~30 lines): Stack-based bracket-tracking for truncated JSON — no longer needed with guaranteed-complete schema responses
- **Narrator metadata instructions from prompts:** `build_dialog_prompt()` and `build_action_prompt()` no longer contain metadata XML templates or extraction rules. Narrator system prompt stripped of NPC rename/details/new_npcs rules
- **13-step metadata extraction from `parse_narrator_response()`:** Bracket-format parsers, code fence JSON extraction, untagged JSON detection, nuclear fallback, bold-bracket metadata — all removed. Parser retained as prose cleanup only (strips leaked XML/JSON/markdown from narration)

### Changed
- **`parse_narrator_response()`:** Reduced from 18-step metadata extraction pipeline to 10-step prose cleanup. No longer extracts game state changes — that's now `call_narrator_metadata()`'s job. Retained: game_data parsing (opening scenes), XML/JSON/code-fence stripping, NPC introduction marking, disposition normalization. Step 8 expanded: strips paired markdown emphasis (`***`, `**`, `*`) and orphaned asterisks
- **Narrator system prompt:** New `PURE PROSE ONLY` rule instructs narrator to output only narrative text. Metadata-specific rules (NPC rename, details, new_npcs, surname establishment) removed. Spatial consistency rule simplified (no metadata update instruction). Explicit markdown prohibition added (`*italics*`, `**bold**`, `# headings`)
- **`call_narrator()`:** Tag logging simplified — only checks for `<game_data>` (opening/chapter scenes)
- **`_salvage_truncated_narration()`:** Only handles `<game_data>` tag, not all 8 metadata tags
- **`_should_call_director()` callsites:** `new_npcs_found` now uses `bool(metadata.get("new_npcs"))` instead of `'<new_npcs>' in raw`
- **`_ensure_npc_memory_fields()`:** Simplified signature (removed `player_name`, `other_npc_names` params). Keywords field preserved as `setdefault("keywords", [])` for savegame backward compatibility but no longer populated. New `last_location` field with `setdefault("", "")` for backward compat
- **`_activated_npcs_block()`:** Injects `last_seen="..."` attribute when NPC's last_location differs from player's current location
- **`_known_npcs_string()`:** Appends `[at:Location]` tag when NPC's last_location differs from player's current location
- **`_npcs_present_string()`:** Same `[at:Location]` tag for fallback path
- **`_apply_memory_updates()`:** Updated for `_fuzzy_match_existing_npc()` tuple return. Sets `last_location = game.current_location` on every memory addition. Auto-stub NPCs get `last_location` at creation
- **`_process_new_npcs()`:** New mid-game NPCs get `last_location = game.current_location` at creation. Player name guard upgraded from exact full-name match to name-part intersection. STT variant matches add alias without renaming (prevents wrong name becoming primary)
- **`_process_game_data()`:** Opening scene NPCs get `last_location` defaulting to `game.current_location`
- **Narrator system prompt SPATIAL CONSISTENCY:** Expanded: NPCs with `last_seen` at a different location than `<location>` are NOT physically present — cannot be heard, seen, or interact directly unless they plausibly travel to the player's location
- **`activate_npcs_for_prompt()`:** Step 4 replaced: keyword set intersection → TF-IDF cosine similarity. Reactivation reason changed from "keyword activation" to "context activation"
- **`retrieve_memories()`:** Removed `npc_keywords` from relevance scoring — context-word overlap with memory event text sufficient
- **`call_brain()`, `call_setup_brain()`:** Use Structured Outputs, removed `_repair_json()` / `_close_truncated_json()` fallbacks, simplified null-safety to in-place field coercion
- **`call_director()`:** Structured Outputs, removed JSON repair cascade, simplified retry logic
- **`call_story_architect()`:** Structured Outputs (Sonnet), removed 2-attempt retry with truncation handling. Prompt extended with `transition_trigger` and `thematic_thread` instructions. User message includes `character_growth` and `thematic_question` from previous chapters. Schema extended: `transition_trigger` per act, `thematic_thread` at top level. All fallback blueprints updated with transition_triggers and thematic_threads
- **`call_chapter_summary()`:** Structured Outputs, removed JSON repair. Schema extended: `npc_evolutions` (NPC change projections for time skip) and `thematic_question` (vertical emotional arc). max_tokens raised 400→800. Prompt extended with instructions for both new fields
- **`get_current_act()`:** Dual logic: (1) checks `story_blueprint["triggered_transitions"]` for Director-signaled act completions, (2) falls back to scene_range. Returns `transition_trigger` in act dict for downstream use
- **`build_director_prompt()`:** `<story_arc>` tag now includes `transition_trigger` and `thematic_thread` attributes. Task section includes `act_transition` boolean instruction
- **`DIRECTOR_OUTPUT_SCHEMA`:** New `act_transition` boolean field — Director signals when current act's transition_trigger has been fulfilled
- **`_apply_director_guidance()`:** Handles `act_transition: true` by appending act_id to `story_blueprint["triggered_transitions"]`
- **`_story_context_block()`:** Injects `thematic_thread` attribute into `<story_arc>` tag for narrator prompts
- **`build_new_chapter_prompt()`:** Injects `<npc_evolutions>` block from most recent campaign_history entry, giving narrator concrete time-skip hints. Task instruction added for using evolution hints through behavior/dialog
- **`load_game()`:** Simplified `_ensure_npc_memory_fields()` calls (no player_name/other_npc_names passthrough)
- **`call_narrator()`:** Cyrillic homoglyph sanitization (`_fix_cyrillic_homoglyphs()`) applied before return
- **`call_narrator_metadata()`:** Fixed `extra_params` → `output_config` kwarg (Structured Outputs now actually applied). Added `<player_character>` to prompt with exclusion instructions. Description quality rule added (physical/role, not scene events). New physically-present vs. merely-mentioned distinction for `new_npcs` with exclusion list (deceased, absent, historical). Anti-fusion rule prevents mixing mentioned names with present persons' descriptions. Memory updates restricted to physically present NPCs
- **`_fuzzy_match_existing_npc()`:** Returns `(npc, match_type)` tuple instead of plain NPC dict. New Step 4: STT variant matching via `_edit_distance_le1()` on title-stripped name parts. All callsites updated for tuple unpacking
- **`_process_npc_renames()`:** Player name guard upgraded from exact match to name-part intersection
- **Narrator system prompt `<player_authorship>`:** New `PRESERVE EXACTLY` rule (no name corrections, no number-to-word conversion, no content "improvement"). New `DESCRIBED SPEECH` rule (action-described speech → indirect speech, never invented quoted dialog)
- ~5,620 → ~5,475 lines (−145 net across all changes in this version)

---

## [0.9.32]

### Added
- **Version display:** Sidebar shows `v0.9.32` at the bottom (small, centered, dimmed). `VERSION` constant in engine.py
- **Savegame version tracking:** `engine_version` (current) and `version_history` (chronological list) written as top-level JSON fields. Preserves history across saves — appends only when version changes. `get_save_info()` returns both fields
- **`_build_other_npc_names()` helper:** Builds set of name parts from all NPCs except one, used for keyword cross-contamination filtering

### Fixed
- **Ghost NPC from technical ID reference:** `_apply_memory_updates()` auto-stub creation now rejects `npc_id` values matching `^npc_\d+$` pattern. Previously, if the Narrator sent a memory_update with a raw NPC ID (e.g. `"npc_4"`) instead of a name, the system created a stub NPC with the ID string as its name — no description, no agenda, just noise. Savegame analysis showed `npc_4` with 2 neutral memories and keyword `['npc_4']`
- **Self-alias after NPC identity merge:** `_merge_npc_identity()` now removes the new name from aliases after rename (prevents current name appearing in own alias list) and skips merge entirely when old and new names are identical. `load_game()` cleans up self-aliases in existing saves. Savegame analysis showed `Professor Albrecht` with `aliases: ['Professor Albrecht', 'Dekan Werner']` — own name as alias caused redundant keyword activation
- **Truncated NPC reflections stored permanently:** `_apply_director_guidance()` now validates reflection text ends with sentence-terminating punctuation before storing. Truncated reflections (from Director `max_tokens` cutoff) are rejected with a warning — the `_needs_reflection` flag stays active so the Director retries next cycle. Savegame analysis found `"Albrecht hat Jana an den Rand getrieben. Sie ignoriert"` (mid-sentence cutoff) stored as importance-8 reflection
- **NPC keyword cross-contamination:** `_auto_generate_keywords()` now accepts `other_npc_names` parameter — name parts of all other NPCs are excluded from description-derived keywords. Prevents NPC A from activating when player mentions NPC B whose name appears in A's description. All 10 call sites updated to pass `_build_other_npc_names()`. Savegame analysis: Dr. Kessler (desc: "Anwältin, die Lena Hoffmann vertritt") had keywords `['lena', 'hoffmann']` — every mention of Lena false-activated Kessler
- **Missing academic titles in `_NAME_TITLES_EXTRA`:** Added `dekan`, `dekanin`, `prodekan`, `prodekanin`, `rektor`, `rektorin`, `prorektor`, `prorektorin`, `dozent`, `dozentin`, `privatdozent`, `privatdozentin`, `referent`, `referentin`, `direktor`, `direktorin`, `intendant`, `intendantin`, `sekretär`, `sekretärin`. Previously `"Dekan Werner"` generated `"dekan"` as a keyword (title not filtered)
- **Noisy German description keywords:** Added ~30 common German nouns to `_RPG_KEYWORD_STOPWORDS` that frequently appear capitalized in NPC descriptions but carry no identity signal: body parts (`hand`, `augen`, `haar`), temporal (`anfang`, `mitte`, `ende`), relational (`kollege`, `freund`, `tochter`), institutional (`anhörung`, `fakultätsmitglied`, `informationen`), role-generic (`tutorin`, `anwältin`). Savegame: Reinholdt had keywords `['hand', 'anfang', 'kollege']` from description
- **Location history near-duplicates:** `update_location()` now checks word overlap (>50%) between new entry and last history entry — replaces instead of appending. Prevents narrative variants of the same place from filling the history. Savegame showed `"Ihr privates Büro im Informatik-Gebäude nach einer langen Vorlesung"` and `"Janas privates Büro im Informatik-Gebäude"` as separate entries

### Changed
- `_apply_memory_updates()`: rejects auto-stub for `npc_\d+` pattern IDs
- `_merge_npc_identity()`: same-name guard, self-alias cleanup after rename
- `_apply_director_guidance()`: reflection completeness check before storage
- `_auto_generate_keywords()`: new `other_npc_names` param for cross-contamination filter
- `_ensure_npc_memory_fields()`: new `other_npc_names` param passthrough
- `_NAME_TITLES_EXTRA`: +20 German academic/professional titles
- `_RPG_KEYWORD_STOPWORDS`: +30 common German description nouns
- `update_location()`: word-overlap dedup on history append
- `load_game()`: self-alias cleanup on load (backward compat)
- Reflection memory dict: explicit `tone` field alongside `emotional_weight`

---

## [0.9.31]

### Fixed
- **Story Architect truncation:** `max_tokens` increased 1200 → 2500 to prevent consistent JSON truncation with verbose German narration. Added `stop_reason` check + `_close_truncated_json()` salvage — the same pattern already used in `call_brain()` and `call_director()`. Savegame analysis showed both architect attempts failing at ~3100 chars with `Expecting ',' delimiter` errors, reliably triggering the generic fallback blueprint
- **Code fence parsing:** Regex patterns in `parse_narrator_response()` only matched `` ```json `` and `` ```xml `` — any other language identifier (e.g. `` ```game_data ``) leaked through to visible narration. Updated 4 regex patterns from `(?:json)?` to `(?:\w+)?` to match any code fence language. Hardened `_clean_narration()` in app.py as safety net (same regex fix)
- **Player name in NPC keywords (possessive forms):** The player name filter in `_auto_generate_keywords()` used exact match, missing possessive forms like `"zoey's"`, `"zoeys"`, `"peter's"`, `"peters"`. Changed to `startswith` check — `"zoey"` now filters all variants. Prevents false NPC activation when player mentions their own name
- **Chapter transition state carry-over:** `start_new_chapter()` now resets `director_guidance` to `{}` (previously carried over `pacing: "climax"` from the final scene into Scene 1 of the new chapter). Dead NPCs (name/description contains death markers in DE+EN) and low-engagement filler NPCs (bond=0, ≤1 memory, no agenda) are retired to `background` at chapter boundary. `location_history` is seeded with the new chapter's starting location after the opening scene is parsed
- **NPC description truncation protection:** New `_is_complete_description()` validates descriptions end with sentence-terminating punctuation (`. ! ? " » … ) – —`). `_process_npc_details()` and `_apply_director_guidance()` now reject incomplete descriptions when a valid existing description is available, instead of overwriting good data with truncated AI output. New descriptions for NPCs without any existing description are always accepted

### Changed
- `call_story_architect()`: `max_tokens` 1200 → 2500, added truncation handling via `_close_truncated_json()`
- `_auto_generate_keywords()`: player name filter uses `startswith` instead of exact match (catches possessive forms)
- `start_new_chapter()`: resets `director_guidance`, retires dead/filler NPCs, seeds `location_history`
- `_process_npc_details()`: validates description completeness before overwriting
- `_apply_director_guidance()`: validates description completeness before overwriting
- `parse_narrator_response()`: code fence regex matches any language identifier
- `_clean_narration()` (app.py): code fence regex matches any language identifier

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
