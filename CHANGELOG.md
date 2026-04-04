# Changelog

All notable changes to EdgeTales are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

---

## [0.9.87]

### Fixed
- **Profile-only NPCs never received agenda/instinct from Director (`engine.py`):** Mid-game NPCs created via `new_npcs` are initialised with `agenda=""` and `instinct=""`. The recovery path — Director fills these via `needs_profile="true"` on `<reflect>` tags — was silently broken for low-engagement NPCs: the `<reflect>` inclusion gate requires `_needs_reflection=True`, which in turn requires `importance_accumulator ≥ 30`. A peripheral NPC mentioned once in dialogue (e.g. an absent club owner) accumulates only 1 seed memory (~3 importance points) and never reaches the threshold, so the Director never sees them and the agenda stays empty permanently. Fix: `build_director_prompt()` now evaluates a `needs_profile_flag` independently of `_needs_reflection`. Any active/background NPC with an empty `agenda` or `instinct` is included in the reflect section regardless of accumulator state. The `needs_profile="true"` attribute, Director schema fields, and `_apply_director_result()` agenda-fill logic are all unchanged — only the inclusion gate is widened. Once both fields are filled, the NPC drops out of subsequent Director prompts automatically (condition evaluates to False). Validated against Elvira session: Sandro Veith (mentioned once in T3 dialogue, `status=active`, 1 memory, `importance_accumulator≈3`) would now receive agenda/instinct on the same turn the Director fires for `new_npcs`.

- **Momentum was not reset to 2 after a burn (`engine.py`):** `process_momentum_burn()` correctly restored game state from the pre-turn snapshot (including the peak momentum value), but never applied the Ironsworn burn-reset rule: momentum resets to 2 as the cost of burning. As a result, a player who burned a MISS→WEAK_HIT or WEAK_HIT→STRONG_HIT while at momentum 10 kept that momentum for the next turn — bypassing the entire mechanic. Discovered via Elvira session log analysis (Turns 9 and 12 both showed `burn_taken: true` with `state_after.momentum: 10`). Fix: `game.momentum = 2` is now set immediately after snapshot restoration, before `apply_consequences` runs. This means the upgraded result's standard momentum gain (+2 standard / +3 great) is applied on top of the reset value rather than the peak, yielding a correct final momentum of 4–5 after a burn.

### Changed
- **`target_npc` now logged in `session_log` entries and Elvira session JSON (`engine.py`, `elvira.py`):** Social moves (`compel`, `make_connection`, `test_bond`) silently skip bond and disposition effects when Brain returns `target_npc: null` — previously invisible in all logs. `process_turn()` now writes `"target_npc": brain.get("target_npc")` into each action-turn `session_log` entry. `apply_consequences()` emits a `level="warning"` log line when a social move has no resolvable target. Elvira's `engine_log` capture now includes `"npc_target"` from the session_log entry. Together these make the null-target case immediately visible in `elvira_engine_*.log` and the session JSON.

- **Threat clocks now advance on WEAK_HIT at risky/desperate position (`engine.py`):** `apply_consequences()` previously only ticked threat clocks on MISS. A WEAK_HIT left the world entirely static — no matter how often the player succeeded-with-cost, threat pressure never accumulated via that path. New behaviour follows position: `controlled` → no tick (the player had the situation in hand); `risky` → 50% chance of 1 tick (`WEAK_HIT_CLOCK_TICK_CHANCE = 0.50`, the gap you left may have been exploited); `desperate` → guaranteed 1 tick (even a partial success at desperate stakes costs the world forward). The gradient is consistent with the existing MISS scale (risky MISS → 1 tick, desperate MISS → 2 ticks). Expected ticks per turn at typical roll distribution (~30% WEAK, ~30% MISS, mostly risky): 0.50 → 0.65, reducing expected time to fill a 6-segment threat clock from ~12 to ~9 turns. Director prompt clock description updated accordingly ("They advance on a MISS (guaranteed), on a WEAK_HIT at risky/desperate position (probabilistic), and autonomously…").

- **Clock ticks now always logged in `clock_events`, not only on clock firing (`engine.py`):** `apply_consequences()` previously appended to `clock_events` only when a clock reached its final segment (i.e., `fired = True`). Partial ticks — including all WEAK_HIT-triggered ticks unless they happened to complete the clock — produced no log entry, making them invisible in `session_log`, Elvira JSON, and the narrator prompt. Fixed for both MISS and WEAK_HIT paths: every tick now unconditionally appends an event with `"source": "miss"/"weak_hit"`, `"fired": bool`, and (for MISS) `"ticks": int`. Autonomous ticks (from `_tick_autonomous_clocks()`) already logged unconditionally and are unchanged. Discovered via Elvira session analysis: T9 and T16 (Justus/Berlin) showed clock state advancing on WEAK_HIT/risky with empty `clock_events` lists.

- **Unresolved social-move targets now visible in session JSON (`engine.py`):** `apply_consequences()` already emits a `level="warning"` log line when a social move (`compel`, `make_connection`, `test_bond`) has no resolvable target — but only to the file logger, not to the session JSON. `process_turn()` now performs a post-hoc annotation: if the move is social and `_find_npc()` fails for `brain["target_npc"]`, a `"warnings"` key is appended to `session_log[-1]` with entry `social_target_unresolved:'<tid>'`. This key is separate from `consequences[]` (which is Narrator-visible) to avoid polluting the prompt context. The entry survives a subsequent momentum burn because `process_momentum_burn()` only overwrites `result`, `consequences`, `clock_events`, and `chaos_interrupt` — not `warnings`. Discovered via Elvira session analysis: T2 (`npc_hafenmeister_unnamed`) and T4 (`npc_5, npc_6`) showed unresolved social targets with no JSON-visible signal.

- **Burn turns self-document in Elvira session JSON (`elvira.py`):** When a momentum burn is taken, `turn_record["roll"]["result"]` correctly retains the original dice outcome (e.g. `WEAK_HIT`) while `engine_log` reflects the post-burn resolution — previously creating an unexplained disconnect: `roll.result=WEAK_HIT` with `state_after.momentum=5` instead of the expected 10 (explained only by `reset(2) + STRONG_HIT gain(+3)`). Elvira now writes `turn_record["roll"]["burn_result"] = burn_info["new_result"]` immediately after a successful burn, making both the original roll and the upgraded outcome explicit in a single turn record. Discovered during session analysis when T9 and T13 appeared to have an unaccounted momentum drop.

- **Elvira `engine_log` now surfaces engine-level warnings (`elvira.py`):** The `engine_log` section in Elvira's session JSON previously captured only `consequences`, `clock_events`, and structural fields from `session_log[-1]`. It now also reads `sl.get("warnings")` and includes a `"warnings"` key when present — omitted entirely when empty, so clean turns produce no diff in log size. This makes engine warnings (e.g. unresolved social-move targets) directly visible in the session JSON without requiring a separate log-file lookup.

---

## [0.9.86]

### Fixed
- **`compel` no longer shifts NPC disposition on STRONG_HIT (`engine.py`):** `compel` and `make_connection` were treated identically on STRONG_HIT — both granted bond+1 and a full disposition step up. This allowed repeated successful compel rolls to push an NPC from `neutral` to `loyal` in two turns (observed in Elvira session: Jawas reached `loyal`/bond=3 within 6 turns of purely compel-based interaction). `compel` is now transactional: STRONG_HIT grants bond+1 only. Disposition shifts are restricted to `make_connection` and `test_bond` — moves where the relationship itself is the explicit or emergent focus.
- **`test_bond` was a dead move on success (`engine.py`):** `test_bond` appeared in `SOCIAL_MOVES` (and therefore cost bond-1 + spirit-1 on MISS), but STRONG_HIT and WEAK_HIT produced no unique outcome beyond momentum — identical to not using the move at all. STRONG_HIT now grants bond+1 and a disposition shift (same as `make_connection`): a relationship that holds under pressure deepens through the shared experience. WEAK_HIT unchanged (momentum+1 only — the bond held but without growth).
- **PDF export shows no story content for bot-generated saves (`engine.py`, `i18n.py`):** `export_story_pdf` uses `scene_marker` messages as the gate to begin writing narration content. Bot-generated saves (e.g. Elvira test sessions) call `save_game` without `chat_messages`, so the save file has `"chat_messages": []`. When such a save is loaded in the UI, only the "Spielstand geladen" status message exists in `s["messages"]` — no `scene_marker` is ever found, `story_started` stays `False`, and the PDF story section is silently empty. Fixed: track `content_written` in the loop; if `False` after all messages are processed, insert a clear explanatory note (`export.no_content` i18n key, DE + EN) instead of an empty section. Normal UI-played sessions are unaffected.
- **NPC-owned threat clocks were permanently stuck (`engine.py`):** `_tick_autonomous_clocks()` excluded all NPC-owned clocks with a blanket owner check, and `check_npc_agency()` only advanced NPC-owned `scheme` clocks — leaving NPC-owned `threat` clocks with no advancement path whatsoever. The opening metadata extractor can legitimately create NPC-owned threat clocks (e.g. "Obi-Wan's Patience" in an Elvira session), but they would never advance beyond their initial fill value regardless of in-game events. Fixed: `check_npc_agency()` now advances NPC-owned threat clocks in addition to scheme clocks, so an NPC's threat pressure grows when the agency check fires every 5 scenes. `_tick_autonomous_clocks()` retains its NPC-owned exclusion to prevent double-ticking on agency scenes (both functions would otherwise fire in the same turn). Note: `apply_consequences()` already ticks the first available threat clock on a MISS regardless of owner, so NPC-owned threat clocks also respond to bad rolls.

### Changed
- **Narrator scene continuity and ending guidance (`engine.py`):** Analysis of a real 10-turn session (Elvira/Marcus Kellner) revealed that 5 of 9 scene transitions felt abrupt when reading narrations in sequence — the narrator opened directly with the player's action, bypassing the atmospheric residue of the previous scene's end. Three prompt rules updated: (1) `SCENE CONTINUITY` now explicitly distinguishes same-location (open with one bridging sentence holding the previous scene's atmosphere before the new action) from new-location (open with one sensory impression of the new space, indifferent to what preceded it — includes generic example). The bridging sentence is required even for very sparse player inputs. (2) `EMOTIONAL CARRY-THROUGH` unchanged. (3) `End scenes OPEN` replaced by `SCENE ENDING`: narrator must close each narration with a sentence naming the character's immediate unresolved inner state or open condition — not a cliffhanger, but an emotional/sensory suspension that gives the next scene something to anchor to.

---

## [0.9.85]

### Fixed
- **Roll log cap visibility (`engine.py`):** When `d1 + d2 + stat > 10`, the `roll_action()` cap applies silently. The previous log format `4+6+1=10` looked like an arithmetic error (4+6+1 = 11, not 10). Both roll log sites (normal turn and correction re-roll) now emit `4+6+1=11→10(cap)` when the cap fires, and `4+5+1=10` when it does not. Variables `_raw` / `_score_str` are local to each call site.
- **UI dice display cap visibility (`app.py`, `i18n.py`):** Same cap-invisibility problem in the Detailed dice display. `build_roll_data()` now computes `score_display` (e.g. `"11→10"` when capped, plain `"10"` when not). `dice.action` i18n key (DE + EN) updated from `{score}` → `{score_display}`. The `app.py` render call updated accordingly. `action_score` (integer) is preserved in the dict for any downstream numeric use.

---

## [0.9.84]

### Added
- **Off-screen death detection — `_check_death_corroboration(game)`:** The primary `deceased_npcs` extractor requires a physically-witnessed death (Karina must see it happen). This left a gap for off-screen deaths described as narrative fact in the narration — the NPC remained `active`, and subsequent scenes could revive them without any engine-level resistance. The new fallback scans observation-type memories written in the current scene and accumulates two independent signal types: (1) a *cross-NPC vote* — another NPC's memory with `about_npc=X`, `importance >= 9`, and `emotional_weight` in `{betrayed, devastated}`; (2) a *self-vote* — NPC X's own memory with `importance >= 9` and `emotional_weight == devastated`. Threshold: at least 1 cross-NPC vote AND total votes ≥ 2. This prevents false positives from single traumatic-but-non-lethal events (a massive betrayal that devastates only one side). Reflections are excluded — they are Director-generated and must not contribute to death detection. Called at the end of `_apply_narrator_metadata()`, after both `_process_deceased_npcs` and `_apply_memory_updates` have run, so all extractor-driven resurrections have already completed before the fallback fires. Validated against a real savegame (backtownw2.json): the function correctly fires at scene 15 (Reindl killed off-screen, cv=1 from Gramm's `about_npc` memory + sv=1 from Reindl's own memory) and stays silent at scene 14 (1 self-vote only, ambiguous) and scene 16 (resurrection memory `w=curious, imp=3` — far below threshold).
- **Opening-scene death detection:** `OPENING_METADATA_SCHEMA` now includes a `deceased_npcs` array (same `npc_id` structure as the regular metadata schema). `call_opening_metadata` instructs the extractor to list characters who clearly die in the opening narration, using the character's **full name** as reference (IDs are not yet assigned at extraction time — `_find_npc` resolves by name; the prompt explicitly forbids inventing IDs like "npc_1" to prevent wrong-NPC mismatches). `_process_deceased_npcs` is called after `_process_game_data` in `start_new_game` (immediately after the `introduced` loop) and after the full merge loop in `start_new_chapter` (so returning NPCs are reachable by name before the check runs). No `scene_present_ids` guard is applied — everything in an opening scene is physically witnessed. NPCs are always extracted with full schema (agenda, instinct, secrets) before being marked deceased, preserving narrative data for context continuity. Error fallback dict includes `"deceased_npcs": []` for schema consistency.

---

## [0.9.83]

### Fixed
- **German compound `emotional_weight` on reflections:** `_apply_director_guidance()` was assigning `ref.get("tone", "reflective")` to `emotional_weight`. The Director `tone` field is an unconstrained free-text compound (e.g. `"protective_guilt"` or German `"wachsam_kalkulierend"`) — unsuitable for importance scoring. `tone_key` is schema-required and enum-constrained (18 single English words, guaranteed by Structured Outputs). Fix: `emotional_weight` now uses `ref.get("tone_key") or "reflective"`. `tone` is preserved separately for narrative arc tracking. Savegame analysis showed `"wachsam_kalkulierend"`, `"schockiert_entblößt"`, `"kalkuliert_enttarnt"` as `emotional_weight` values — all unscored by `score_importance()`.
- **`last_tone` in Director prompt degraded by above fix:** `build_director_prompt()` was reading `last_tone` from `emotional_weight` (line 4710). After the `emotional_weight` fix, this would have yielded the enum word (`"conflicted"`) instead of the narrative compound (`"protective_guilt"`), weakening the Director's emotional arc context. Fix: `build_director_prompt()` now emits both `last_tone` (narrative compound from `tone` field, e.g. `"protective_guilt"`) and `last_tone_key` (enum word from `tone_key` field, e.g. `"conflicted"`) as separate attributes on `<reflect>` tags. Director instruction updated to use `last_tone` as emotional register / arc texture and `last_tone_key` as the enum category to evolve the new `tone_key` away from. Backward-compat: `last_tone` falls back to `emotional_weight` for saves predating the dual-tone system; `last_tone_key` is omitted if `tone_key` field absent.
- **Clock owner not updated on NPC rename:** `_merge_npc_identity()` updated `npc["name"]` and appended the old name to `npc["aliases"]`, but clock `owner` strings (which the Metadata Extractor writes as free NPC-name strings) were never updated. Any clock created while an NPC had a temporary description-name (e.g. "Eine Frau mittleren Alters") would permanently retain that name as owner after the identity reveal. `_tick_autonomous_clocks()` treats any owner not in `("", "world")` as NPC-controlled and skips it — so affected threat clocks silently stopped ticking. Fix: `_merge_npc_identity()` now accepts an optional `game` parameter; when provided, iterates `game.clocks` and updates any owner whose normalized form matches the old name. All 5 call sites updated to pass `game=game`. Normalized comparison (`_normalize_for_match`) catches whitespace/hyphen/case drift. Limitation: article-level drift in AI-written owner strings (e.g. "Die Frau" vs canonical "Eine Frau") is not covered — this is an AI clock-creation quality issue, not a rename bug.
- **`check_npc_agency()` scheme clocks never ticked:** The function compared `clock.get("owner") == npc["id"]` (e.g. `"npc_7"`), but the Metadata Extractor always writes owner as a name string (`"world"` or NPC name) — never as a raw ID. This comparison was always `False`, so NPC-owned scheme clocks advanced only via player MISS rolls, never via NPC agency. Fix: `check_npc_agency()` now builds a normalized name set per NPC (canonical name + all aliases) and matches `_normalize_for_match(clock_owner)` against it.
- **`load_game()` backward-compat repair for stale clock owners:** Saves made before the above fix may have clock owners that are now aliases of a renamed NPC. On load, a normalized `alias → canonical name` map is built from all NPC aliases; any clock owner that maps to a different canonical name is updated and logged.

---

## [0.9.81]

### Fixed
- **Zombie-reflection loop persists in fast-play sessions — `_bg_director` early-exit never reset flags:** Despite the 0.9.79/0.9.80 fixes, `app.py` still uses the background-task `_bg_director` pattern with `_director_gen` staleness guards. When a new turn starts before the background Director task executes (fast play, ~any turn played in under 1–2s), the guard at the top of `_bg_director` fires and returns early without calling `run_deferred_director`. The `_needs_reflection` flags and `importance_accumulator` values are therefore never reset, causing the Director to be triggered every subsequent scene in a perpetual zombie loop. Savegame analysis (elvira_run.json, scene 20): `director_trigger: "reflection:Konrad Barneck"` fired 10 of 20 scenes; Barneck `importance_accumulator=35` (exact sum of all 6 memory importances — never reset), Hedwig `importance_accumulator=96` (exact sum of all 16 memory importances — never reset); `last_reflection_scene=0` for both. Fix: the early-return path in `_bg_director` now calls `reset_stale_reflection_flags(_g)` (new `engine.py` function) and saves — clearing flags without running the Director API call, which would produce reflections on stale narration context.
- **`_should_call_director` trigger label always named first NPC in list, not most-pending:** The reflection-trigger check iterated `game.npcs` and returned on the first match, so `director_trigger` always showed e.g. `"reflection:Konrad Barneck"` even when Hedwig had 3× the accumulator. `build_director_prompt` already includes all `_needs_reflection` NPCs regardless, so this was a logging/diagnostics issue only. Fix: the trigger label now names the NPC with the highest `importance_accumulator` (`max()` over all pending-reflection NPCs).

- **`_check_story_completion` never triggered epilogue when Director transitions were missing:** The primary completion check required `penultimate_id` to be present in `triggered_transitions` (Director-confirmed act transition). When Director runs were consistently superseded by fast play (zero `act_transition: true` ever returned), `triggered_transitions` stayed empty and the primary check always failed. The fallback fired only at `final_end + 5` — 5 scenes past the story's end, which a player who stopped at scene 20 never reached. Savegame analysis (elvira_run.json): story ended at scene 20 = `final_end`, all 4 acts narratively complete, `triggered_transitions: []`, `epilogue_shown: false` — epilogue was permanently suppressed. Fix: when `scene_count >= final_end` and the primary check fails, `_check_story_completion` now performs a scene-range back-fill of `triggered_transitions` (identical logic to `_apply_director_guidance`) before re-evaluating. This ensures the epilogue fires at the correct scene even when the Director never recorded a transition.
- **`about_npc` self-references stored in NPC memories:** `_resolve_about_npc` resolved any NPC reference to its canonical `npc_id` but did not guard against the resolved ID matching the memory's own NPC. The Extractor occasionally set `about_npc` to the same NPC that owns the memory (e.g. a Barneck memory with `about_npc: "npc_1"`). Savegame analysis: Barneck scene-4 memory had `about_npc: "npc_1"`. Fix: `_resolve_about_npc` now accepts an optional `owner_id` parameter; if the resolved ID matches `owner_id`, it returns `None` and logs a rejection. Both call sites (`_apply_memory_updates` and `_apply_director_guidance`) pass `owner_id=npc.get("id")`.

### Added
- **`reset_stale_reflection_flags(game)`** — new public engine function that resets `_needs_reflection` and `importance_accumulator` to 0 for all active/background NPCs flagged for reflection. Called by the UI layer when a Director turn is skipped due to a superseding turn, preventing indefinite flag accumulation.

---

## [0.9.80]

### Fixed
- **Director race condition was documented but never implemented in `app.py`:** The [0.9.79] changelog entry described awaiting the Director inline and removing `_bg_director` / `_director_gen`, but `app.py` still contained the full old background-task pattern (`asyncio.create_task(_bg_director())`). Every new turn incremented `_director_gen` before the previous Director call could complete (~1–2s), causing the staleness guard to discard the result on virtually every turn — identical symptoms to the pre-fix state. Savegame analysis: Kassandra run (18 scenes), `last_reflection_scene=0` for both active NPCs; Lyra accumulator=149, Permian accumulator=61; `director_trigger: "reflection:Permian Kalt"` appears 13 times in session_log with zero stored reflections. Fix: `_bg_director` closure removed, `_director_gen` tracking removed (both lines), Director now awaited inline between first `save_game` and TTS. A `turn_gen` guard after the await prevents saving Director state if the user switched games during the ~1s window. Burn turns exempt: `director_ctx and not burn_info` ensures the Director is skipped when a momentum burn is pending (page reloads immediately after).

---

## [0.9.79]

### Fixed
- **Director results never persisted during fast play — race condition eliminated:** Previously the Director ran as a fully independent `asyncio.create_task` after narration was rendered. A three-guard staleness system (`_director_gen`) was intended to discard the Director's save if a newer turn had started, but in practice it fired on every turn played faster than the Director's API call duration (~1–2s), causing `director_guidance` to remain `{}` and `_needs_reflection` flags to accumulate indefinitely (savegame analysis: Vince acc=119, Mauer acc=94, zero stored reflections across 20 scenes). Fix: Director is now awaited inline in the turn handler, between the first `save_game` (pre-Director) and TTS. `processing=True` is still active during this ~1s window, so the send button stays disabled until Director completes — no race is possible. The entire `_bg_director` closure and `_director_gen` tracking are removed. Momentum-burn turns are exempt: Director is skipped when `burn_info` is set (the turn will be re-narrated via `process_momentum_burn` anyway).
- **`_apply_director_guidance` early exit left `_needs_reflection` permanently stuck on API failure:** When `call_director` returned `{}` (any API exception), `_apply_director_guidance` hit `if not guidance: return` and exited before the fallback reset loop. This meant `_needs_reflection` was never cleared, turning every subsequent scene into a fresh Director trigger that also failed — an infinite zombie-trigger loop. Fix: the early-return path now iterates `game.npcs` and resets all `_needs_reflection` flags and `importance_accumulator` values before returning, just as the normal fallback at the end of the function would.
- **Director reflection infinite loop:** Two compounding bugs caused `_needs_reflection` to never clear, locking the Director into `reflection:<NPC>` every eligible scene with zero stored reflections as the result.
  - **Bug A:** `reflected_ids` in the fallback was built from the full `npc_reflections` list before the processing loop. Any NPC whose reflection was rejected (empty string or truncated mid-sentence) was counted as "addressed", so the fallback skipped them and `_needs_reflection` stayed `True` permanently. Fix: introduce `successfully_reflected_ids` — a set populated only when a reflection actually passes all checks and is stored in memory. The fallback now uses this set exclusively.
  - **Bug B:** The fallback deliberately did not reset `importance_accumulator` ("it will re-trigger next threshold crossing"). But if the accumulator was already ≥ `REFLECTION_THRESHOLD` (savegame: Korda=93, Karl Thomsen=99), the very next call to `_apply_memory_updates()` — which runs every scene — immediately re-set `_needs_reflection = True` regardless. Fix: fallback now resets the accumulator to 0 alongside the flag, forcing a genuine re-accumulation before the next Director reflection trigger. Savegame analysis: `reflection:Korda` fired in 11 of 21 scenes; Karl Thomsen (acc=99, 21 memories) received zero reflections as a side effect.

---

## [0.9.78]

### Improved
- **3-act Story Architect prompt: qualitative parity with Kishōtenketsu.** Five targeted additions close the quality gap between the two structure prompts:
  (1) **Explicit act definitions** — Setup/Confrontation/Climax now carry purpose descriptions (working assumptions → challenged frame → reframing), analogous to Ki/Shō/Ten/Ketsu. Prevents the model from defaulting to training-data generics for these labels.
  (2) **Anti-escalation rule on the confrontation→climax transition** — `TRANSITION_TRIGGER` for Act 2→3 must be a REFRAMING EVENT, not merely an escalation of existing tension. Mirrors the Ten-rule constraint that produced the "echo of your former self" motif in Kishōtenketsu runs.
  (3) **Dual-layer `central_conflict`** — Must have a SURFACE LAYER (what the conflict appears to be at the start) and a HIDDEN LAYER (what it turns out to actually be about), emerging through Act 2 revelations and reframing the climax. Forces two-dimensional conflict thinking.
  (4) **Structurally anchored `thematic_thread`** — Now defined as a genuine open philosophical question (not a label), with explicit act anchoring: surfaces in Act 1, challenged in Act 2, confronted in Act 3. Prevents the thematic thread from floating as an orphaned bullet with no structural connection.
  (5) **Perception-shift revelation requirement + reframed endings** — At least one revelation must change how the player understands something already seen. Possible endings must address both external outcome AND thematic question (labels changed: triumphant/bittersweet/tragic → hard-won/bittersweet/pyrrhic as examples).

---

## [0.9.77]

### Changed
- **Narrator: `<tone_authority>` block added to system prompt.** The player's chosen tone is now injected as a first-class `<tone_authority>` element, positioned before `<rules>`, making it the dominant stylistic register for every scene. Explicitly instructs the narrator that tone governs sentence rhythm, scene energy, what details get highlighted, NPC behavior, and what makes a moment land — and that `<director_guidance>` must never override it. Fixes slapstick (and other non-dark tones) being gradually suppressed as Director guidance accumulated thematic weight.
- **Narrator: `<style>` block reduced to universal craft rules.** Removed "Terse and precise — one specific detail beats three general ones" and "Render emotion through behavior and sensation, not labels" from the `<style>` element. These were stylistically prescriptive (suited for dark/gritty or noir) and actively worked against comedy, whimsy, and high-energy tones. Remaining content: "The player is inside the world, not watching it. Integrate what the player brings seamlessly, as if it was always there." — both rules are truly universal. Tone-specific style guidance is now the responsibility of `<tone_authority>`.
- **Director: `<setting>` context block added.** `build_director_prompt()` now opens with `<setting genre="..." tone="..."/>`, giving the Director awareness of genre and tone for the first time.
- **Director: TONE RULE added to `<task>`.** `narrator_guidance` and `npc_guidance` must honor the story's tone. A comedy tone requires comedy-compatible beats; a dark tone requires weight. Prevents the Director from producing tonally neutral or drama-biased guidance that pulls the narrator away from the player's chosen register.
- **Director: `player_name` intentionally excluded from `<setting>`.** The Director does not need the player character's name for strategic guidance — omitting it prevents Haiku from referencing the protagonist by name in `narrator_guidance`, which was the root cause of third-person drift in the Narrator's prose.


### Changed
- **Narrator: SCENE CONTINUITY rule added.** New rule instructs the narrator to begin each scene in motion rather than with a fresh establishing paragraph, carrying forward the physical and situational thread from where the previous scene ended. Exception: when the player has moved to a new location (detectable via `<location>` vs `<prev_locations>`), the narrator briefly grounds the player in the new space before continuing. Prevents the common pattern of opening each scene as if the previous one had cleanly closed.
- **Narrator: EMOTIONAL CARRY-THROUGH rule added.** New rule instructs the narrator to carry the emotional weight of significant scene-ending beats (betrayal, loss, triumph, relief, intimacy, shock) into the opening of the next scene through body language, perception, and attention — not through narration. Emotional states do not reset between scenes. The rule explicitly excludes internal monologue: the character has not processed the event yet.
- **Narrator: thematic_thread surfacing rule added.** The existing `<story_arc>` rule expanded: when `<story_arc>` contains a `thematic_thread`, the narrator is now instructed to let it surface periodically through NPC dialog, character reactions, or incidental observations — as a question the world quietly keeps asking, not as lecture or internal monologue. Not mandatory every scene, but intended as a recurring undercurrent that gives campaigns emotional vertical coherence.
- **Action prompt task text extended with act-mood reference.** The `<task>` line in `build_action_prompt()` now instructs the narrator to let the current act's mood (from `<story_arc>`) shape the texture of the outcome — specifically noting that a STRONG_HIT in a desperate phase still carries the surrounding darkness. Prevents clean successes from feeling tonally mismatched with the story's current emotional register.
- **Dialog prompt task text extended with act-mood reference.** Parallel to the action prompt change: `build_dialog_prompt()` `<task>` now instructs the narrator that even a quiet conversation carries the weight of the surrounding act phase. Closes the asymmetry where action scenes were mood-anchored but dialog scenes were not.
- **Director `narrator_guidance` instruction extended with thematic_thread anchor.** The Director's field instruction for `narrator_guidance` now asks it to occasionally anchor the guidance to the `thematic_thread` from `<story_arc>` — surfacing the aspect most alive in the current moment. Closes the gap between the narrator being instructed to weave the thematic thread and the Director's guidance not reinforcing it.
- **Metadata Extractor `scene_context` instruction made explicit (both extractors).** The regular `call_narrator_metadata()` extractor had no definition for `scene_context` — Haiku inferred freely, producing inconsistent results ranging from purely factual to atmospheric. Now explicitly defined as: 1 sentence capturing current situation AND dominant mood/tension, with a concrete example and "extract from the narration; do not invent" safeguard. The Opening Metadata Extractor (`call_opening_metadata()`) had a vague "1-2 sentence summary" instruction; aligned to the same format including the anti-invention guard. `scene_context` feeds the Brain state block and NPC TF-IDF activation — a mood-anchored sentence improves both position/effect calibration and memory retrieval relevance.

### Fixed
- **NPC rename via `##` correction added old name as alias instead of changing the primary name.** When a player explicitly renamed an NPC (e.g. `## Benenne Unbekannter Rekrut 1 in Steve um`), the correction brain treated it as an alias addition (`fields.aliases`) rather than a name change (`fields.name`). Root cause: (1) aliases were not shown in the NPC summary visible to Haiku, so it had no context for the distinction; (2) the system prompt had no rule differentiating rename from alias-add; (3) the engine had no safety net to handle the name field correctly if it was set. Three-part fix: `_npc_line()` in `call_correction_brain` now includes aliases in the NPC summary; a dedicated NPC RENAME rule in the system prompt instructs Haiku to use `fields.name` for explicit renames and leave `fields.aliases=null`; `_apply_correction_ops` now captures the old name before applying edits and automatically moves it into aliases — also strips the new name from aliases as a defense if Haiku ignored the instruction.
- **XML attribute injection vulnerability in `<story_arc>` and `<reflect>` blocks.** AI-generated prose fields inserted as XML attribute values were unescaped — a `thematic_thread`, `central_conflict`, `act_goal`, or NPC `description` containing a literal `"` (e.g. `Was ist "Vertrauen"?`) would break the attribute boundary and corrupt the prompt XML silently. Same risk existed for `<` and `&`. Fix: added `_xa(s)` helper (`html.escape(str(s), quote=True)`) and applied it to all AI-prose attributes in `_story_context_block()` (`conflict`, `act_goal`, `mood`, `thematic_thread`) and `build_director_prompt()` (`conflict`, `thematic_thread`, `npc_desc`, `last_reflection`, `aliases`). The three pre-existing manual `.replace('"', '&quot;')` calls in `build_director_prompt` were replaced with `_xa()` — they were incomplete fixes that missed `<` and `&`. Added `import html` to stdlib imports.
- **`<revelation_ready>` element content unescaped.** The revelation text from the Story Architect was injected as XML element content without escaping — a revelation containing `<` (e.g. `"Der König ist <kein> Mensch"`) would corrupt the prompt's XML structure. Fixed with `html.escape()` (without `quote=True` — element content does not need quote escaping). Identified as follow-on gap during the `_xa()` review pass.
- **NPC rename + simultaneous alias edit would let Haiku overwrite engine alias logic.** If Haiku sent both `fields.name="Steve"` and `fields.aliases=[...]` in the same `npc_edit` op (despite the RENAME rule instructing `fields.aliases=null`), the edits loop would apply Haiku's alias list first, overwriting the existing aliases — then the engine rename bookkeeping would add the old name, but any pre-existing aliases Haiku omitted would be lost. Fixed: `edits.pop("aliases", None)` is applied before the loop whenever a rename is detected (`"name"` in edits). Alias bookkeeping for renames is exclusively engine-owned.
- **Remaining XML injection coverage pass.** Applied `_xa()` and `html.escape()` to all remaining unescaped AI-generated fields in prompt XML: `_npc_block()` (`target_npc` name + aliases attributes); `_activated_npcs_block()` (name, insight/recent memory hint, last_seen attributes); `<reflect>` tag in `build_director_prompt()` (name attribute + mem_text element content); `build_dialog_prompt()` and `build_action_prompt()` (director_guidance and npc_note element content); `build_new_chapter_prompt()` (returning_npc name + aliases attributes, description element content); `build_epilogue_prompt()` (npc name attribute, description element content). Completes the XML safety pass started with `_xa()` — all AI-prose fields in prompt XML are now consistently escaped.
- **`_scene_header()` helper introduced — single source of truth for `<world>`/`<character>` in all narrator prompts.** All five narrator prompt builders (`build_new_game_prompt`, `build_dialog_prompt`, `build_action_prompt`, `build_epilogue_prompt`, `build_new_chapter_prompt`) duplicated the `<world genre="..." tone="...">...</world><character name="...">...</character>` template verbatim with no escaping. `setting_genre`, `setting_tone`, and `player_name` in attribute position and `setting_description`, `character_concept` in element position were all raw. New `_scene_header(game)` helper applies `_xa()` to all attribute values and `html.escape()` to all element content. All five builders now call `_scene_header()` — eliminating the duplicate pattern and ensuring future prompt builders cannot regress.
- **`<location>`, `<situation>`, `<intent>`, `<player_words>`, `<world_add>`, `<npc_agency>` element content unescaped across all narrator prompt builders.** `game.current_location`, `game.current_scene_context`, `brain.player_intent`, `player_words` (direct player input — highest injection risk), `brain.world_addition`, and individual `npc_agency` strings were inserted raw as XML element content. Applied `html.escape()` consistently to all five prompt builders. `npc_agency` items are now individually escaped before joining with `|`.
- **`_npc_block()` element content unescaped.** AI-generated `agenda`, `instinct`, memory summary (`mem_str`), and serialised `secrets` JSON were inserted as raw XML element content inside `<target_npc>`. Applied `html.escape()` to all four fields. `secrets` JSON is serialised first, then escaped — handles any `<` or `&` that could appear in secret descriptions.
- **`_recent_events_block()` summary text unescaped.** AI-generated `rich_summary` / `summary` from `session_log` was inserted raw into `<recent_events>` element content. Applied `html.escape()` before truncation.
- **`_campaign_history_block()` chapter title attribute and summary element unescaped.** AI-generated chapter title was inserted raw into the `title="..."` attribute (injection risk for `"`) and chapter summary into element content. Applied `_xa()` to `title` and `html.escape()` to `summary`.
- **`build_director_prompt()` — `transition_trigger` element content and `latest_narration` unescaped.** The `<transition_trigger>` element content came from `story_blueprint` (AI-generated) and `<latest_scene>` contained a raw 1000-char slice of narrator output. Both now wrapped with `html.escape()`.
- **`_activated_npcs_block()` — `emotional_weight` was outside `_xa()` scope but inside attribute boundary.** The `recent` memory hint was built as `f'{_xa(event[:60])}({emotional_weight})'` — the closing `(weight)` portion was appended after `_xa()` but still inside the surrounding `"..."` attribute. A `"` or `&` in `emotional_weight` would break the attribute. Fixed by composing the full `event(weight)` string first, then passing the entire value to `_xa()`.
- **Second-pass XML escape audit: `call_brain()`, `_pacing_block()`, both metadata extractors.** Comprehensive re-scan of all prompt builders identified five additional unescaped fields: `player_message` in `<input>` (direct player input — highest injection risk) and `game.backstory` in `<backstory>` in `call_brain()` user_msg; `dramatic_question` in `<dramatic_question>` in `_pacing_block()` (Brain output injected into both narrator prompts); `game.player_name` and `game.current_location` as element content in both `call_narrator_metadata()` and `call_opening_metadata()` prompts. All five fixed with `html.escape()`. Note: `narration` content in `<narration>` tags passed to extractors is intentionally left unescaped — the extractor must read the prose verbatim, and escaping would corrupt extracted memory text and `scene_context` with HTML entities.
- **Third-pass XML escape audit: `phase` attribute, `prev_tone`, correction context, lore figures, NPC evolutions.** Final scan identified seven additional gaps: `act["phase"]` in attribute position in both `_story_context_block()` and `build_director_prompt()` (freeform string in schema, `mood` was already escaped but `phase` was not — inconsistency); `prev_tone` (`emotional_weight`) in `last_tone="..."` attribute in `build_director_prompt()`; `analysis['narrator_guidance']` in `<correction_context>` element in `_apply_correction()`; NPC names, descriptions, and aliases in `_lore_figures_block()` element content; duplicate lore NPC block in `build_new_chapter_prompt()`; `npc_evolutions` name and projection fields in `build_new_chapter_prompt()` element content. All fixed with `_xa()` or `html.escape()` as appropriate.
- **Fourth-pass XML escape audit: `structure_type`, `possible_endings` types, `rev_content`, `epilogue_text`, `bg_names`, `time_of_day`, `location_history`.** Exhaustive re-scan identified seven further gaps: `structure_type` in `structure="..."` attribute (freeform AI string) in both `_story_context_block()` and `build_director_prompt()`; `possible_endings[*].type` values embedded in `<story_ending>` element content; `rev_content` (revelation prose) in `<revelation>` element in `call_revelation_check()`; `epilogue_text` (narrator prose) in `<epilogue>` element in `call_chapter_summary()`; background NPC names and aliases in `<background_npcs>` in `build_new_chapter_prompt()`; `game.time_of_day` and `game.location_history` items embedded as element content in `<time>` and `<prev_locations>` across all four narrator prompt builders. To eliminate the repeated `time_ctx`/`loc_hist` local-variable pattern (three identical unescaped copies), introduced `_time_ctx(game)` and `_loc_hist(game)` helper functions alongside `_scene_header()` — all prompt builders now call these helpers. Full exhaustive re-scan confirmed no remaining unescaped AI-prose or player-input fields in any prompt XML context.
- **Fifth-pass XML escape audit: `_known_npcs_string`, `_npcs_present_string`, `current_time`.** Automated scanner with manual verification of all 19 flagged lines found three remaining gaps: NPC names and `last_location` in `_known_npcs_string()` (feeds `<known_npcs>` element in dialog and action prompts); NPC names, aliases and `last_location` in `_npcs_present_string()` (fallback `<npcs_present>` element); `game.time_of_day` in `<current_time>` in `call_narrator_metadata()`. All fixed with `html.escape()`. Remaining 18 scanner flags verified as safe: intentional unescaped `<narration>` blocks (extractors require verbatim prose), variables pre-escaped before interpolation, integer/enum values, hardcoded literals, and ReportLab PDF context.
- **Sixth-pass XML escape audit (Sherlock scan): `clock_triggered` attribute, `consequences` attribute, `campaign_ctx` element.** Structural analysis of carrier variables — variables built from AI content that are later interpolated into XML — found three further gaps missed by line-level scanning: (1) `clock["name"]` and `clock["trigger_description"]` (AI-generated clock name and trigger text) interpolated raw into `clock_triggered="name:trigger"` XML attribute in `build_action_prompt()` — both now wrapped with `_xa()`; (2) `target["name"]` (AI-generated NPC name) embedded in the `consequences` list entry `"name bond -1"`, which lands in `consequences="..."` XML attribute — now wrapped with `html.escape()`; (3) `ch.get("title","")` (AI-generated chapter title) inserted raw into `<campaign>` element content in `call_brain()` user_msg — now wrapped with `html.escape()`.
- **Seventh-pass XML escape audit (Einstein scan — system prompts and player-input XML blocks).** Fundamental lifecycle analysis — tracing all player-written and AI-generated strings from origin through GameState into system prompts — found four further gaps: (1) NPC names and aliases in `known_block` in `call_opening_metadata()` system prompt inserted raw into `<known_npcs>` element; (2) `content_lines` (player-written content restrictions) inserted raw into `<lines>` element in `_content_boundaries_block()` — direct player input, highest risk; (3) `player_wishes` (player-written future story desires) inserted raw into `<player_wishes>` element in `_content_boundaries_block()` — direct player input; (4) `backstory` (player-written canonical history) inserted raw into `<backstory>` element in `_backstory_block()`. All four fixed with `html.escape()`. Note: `game.player_name`, `setting_genre`, and `setting_tone` appearing in the same system prompt text are instruction-context strings (not XML-delimited attributes), so structural injection risk is negligible there.
- **Eighth-pass XML escape audit (exhaustive enumeration — all XML attribute and element variables).** Full formal enumeration of every `>{var}</` and `attr="{var}"` occurrence in the codebase, classified by data origin. Found three further gaps: (1) `n["name"]`, `n["aliases"]`, `n["last_location"]`, `n["description"]` all unescaped in `npc_refs` construction in `call_narrator_metadata()` — these flow into `<known_npcs>` element content; (2) `c["name"]` (AI-generated clock name) unescaped in `clock_summary` for Brain `<clocks>` element; (3) `rich_summary`/`summary` (AI prose) unescaped in `last_scenes` for Brain `<recent>` element. All three fixed with `html.escape()`. Full enumeration confirmed all remaining ✗-flagged variables as safe: integer values, constrained engine enums (`progress` = early/mid/late, `disposition`, `effect`, `position`, `pacing`), pre-escaped carrier variables (false positives), hardcoded string literals, and intentional unescaped `<narration>` blocks.

---

## [0.9.75]

### Fixed
- **Duplicate NPC at chapter boundary when extractor uses an alias as a new NPC name.** During `start_new_chapter()`, the returning-NPC merge loop only checked names — not aliases — against the extractor's freshly created NPCs. If a returning NPC (e.g. `"Ein erschöpfter Reiter"`) carried an alias (`"Dragoner Fink"`) that the Opening Metadata Extractor independently introduced as a new hollow NPC, both survived as separate entries: a hollow extractor NPC (0 memories, no context) and the rich returning NPC (full history). The Brain would activate the hollow NPC when the player mentioned the alias, silently discarding chapter-1 history. Fixed: the merge loop now performs a bidirectional alias check (returning alias ↔ extractor name, and returning name ↔ extractor aliases; minimum 4-char alias length to skip noise entries). On match, the returning NPC's history (memories, bond, importance_accumulator, last_reflection_scene, aliases, secrets) is merged into the hollow extractor NPC in-place; `_merge_npc_identity` renames the hollow NPC to the canonical returning name (extractor name becomes an alias); `id_remap` is populated so downstream `about_npc` references are rewritten correctly. Self-healing: if both the hollow and the rich NPC survive into a subsequent chapter transition, the alias-match fires there too and resolves the duplicate correctly.

---

## [0.9.74]

### Changed
- **Narrator task tags improved for action and dialog turns.** Action prompt: replaced generic "2-4 paragraphs of immersive narration" with a craft-focused instruction that encourages roll consequences to open new story questions rather than simply resolving them — scenes should end in motion with something shifted. Dialog prompt: replaced "focus entirely on atmosphere, dialog, and character interaction" with a directive to let the world breathe around the conversation through sensory details of place, light, sound, and texture, while still requiring something to shift between the characters by the end. Both changes apply every turn and are intended to improve narrative momentum and scene texture.
- **Narrator `<style>` block rewritten.** Replaced "Terse, vivid, sensory. Show, don't tell." with concrete craft direction: one specific detail beats three general ones; render emotion through behavior and sensation, not labels; the player is inside the world, not watching it.
- **NPC introduction rule in narrator system prompt expanded.** Replaced the single-line "give them distinct voices and traits" with a concrete craft instruction: NPCs' agenda and instinct are their behavioral engine; distinct voice comes from vocabulary level, sentence rhythm, and what a character deflects or refuses to acknowledge; one physical trait or habitual gesture makes them tangible.
- **Roll result guidance texts sharpened in `build_action_prompt()`.** MISS: added "physical, emotional, or narrative cost" to clarify cost types, and "a new complication emerges that creates fresh pressure or danger" to make failures story-generative rather than purely punishing. WEAK_HIT: replaced "tangible cost or complication" with "something lost, compromised, or complicated" to steer away from the default of taking physical damage. STRONG_HIT: replaced "Clean success" with a craft note that even victories have texture and should open what comes next, preventing flat resolution prose.

---

## [0.9.73]

### Fixed
- **Dead NPCs staying `active` after literary death descriptions.** The `deceased_npcs` metadata extractor prompt only listed explicit death vocabulary ("collapse", "stop breathing", etc.) — missing deaths described through physical sensation or literary language (e.g. *"die Beine treten zweimal, dann hört auch das auf"*). Haiku failed to flag NPCs as deceased when the narrator used this style. Prompt now explicitly covers literary/physical cessation patterns with German and English examples, making clear that the word "dead" or "died" is not required — permanent physical cessation described as final qualifies.
- **Remote NPCs receiving wrong `last_location` after player teleports/time-travels.** When the player moved to a new location mid-scene, any NPC receiving a `memory_update` in that same scene had `last_location` blindly overwritten with `game.current_location` — even NPCs who remained in the previous location (e.g. Plaček and Hanka staying in 2026 while the player time-jumps to 1933). Fixed in `_apply_memory_updates`: `last_location` is now only updated for NPCs whose ID is in `scene_present_ids` (physically activated in the scene). NPCs that are merely mentioned or observed remotely keep their existing location. Follow-up: added `pre_turn_lore_ids` exemption to the same guard — lore→active NPCs (physically appearing for the first time) were not in `scene_present_ids` (built before the metadata cycle) and would have received an empty `last_location` despite arriving on-screen.
- **Descriptor-named NPCs not merged when their real name is revealed.** `npc_renames` prompt was too narrow ("spy unmasked, alias discovered") — Haiku did not recognize the most common case: a descriptor-named NPC (e.g. "Die Frau im Wollhut") receiving a personal name ("Hanna") in a later scene. The prompt now explicitly covers this case with examples. Follow-up: `_absorb_duplicate_npc` now uses a richness score (memory count × 2 + bond × 2 + agenda × 3 + instinct × 3 + description × 1) to determine merge direction — if `dup` scores higher, its substantive fields (description, agenda, instinct, disposition, secrets, last_location, last_reflection_scene) overwrite `original`'s in-place while `original` retains its ID. `_needs_reflection` propagated from `dup` if set. Dead variable `orig_mems` removed.

---

## [0.9.72]

### Removed
- **`keywords` field removed from all NPC dicts.** Legacy stub from a previous keyword-based NPC activation system, fully superseded by TF-IDF scoring (`_compute_npc_tfidf_scores`). The field was never read or written after the TF-IDF migration — only `setdefault`-populated with `[]` for backward compatibility. Removed from 5 sites: active NPC creation, lore NPC creation, stub NPC creation in `_apply_memory_updates`, and migration setdefaults in `_ensure_npc_memory_fields` and `load_game`.

### Fixed
- **`world`-owned clocks never ticked autonomously.** `_tick_autonomous_clocks()` skipped any clock with a non-empty `owner` field. Since all world-owned clocks carry `owner: "world"` (non-empty string → truthy), the 18%-per-scene autonomous tick chance never fired for them — only player MISSes advanced world threat clocks. Fixed: the guard now skips only clocks whose owner is neither `""` nor `"world"`, matching the original intent (NPC-scheme clocks tick via `check_npc_agency`; world-threat clocks tick autonomously).
- **Truncated `rich_summary` stored in `session_log`.** The Director's `scene_summary` was written verbatim even when truncated mid-sentence by the model. The field is now validated before writing: if it lacks a sentence-terminating character, `_truncate_to_last_sentence()` scans backwards for the last complete sentence and stores that instead. If no complete sentence exists, the write is skipped entirely and the Brain's `summary` remains as fallback (logged as warning). New `_SENTENCE_ENDS` module-level tuple and `_truncate_to_last_sentence()` helper are shared with the existing NPC reflection truncation guard (which previously used an inline literal).

### Changed
- **`AUTONOMOUS_CLOCK_TICK_CHANCE` raised from 0.18 to 0.20.** Pairs with the world-clock fix above; slightly increases narrative pressure from threat clocks.
- **Tone "Tarantino-Style" renamed to "Pulp"** in `_TONES` for both `de` and `en` in `i18n.py`. Internal key `"tarantino"` unchanged.
- **Custom tone input in creation flow changed from single-line `ui.input` to `ui.textarea` (3 rows).** Gives players more comfortable space to describe a custom tone. `keydown.enter` submit binding removed (inappropriate for textarea).

---

## [0.9.71]

### Changed
- **Narrator: SENSORY RANGE + WORLD PERIPHERY rules added to system prompt.** Two new craft rules in `get_narrator_system()` address recurring atmospheric flatness. SENSORY RANGE instructs the narrator to include at least one non-visual sense per scene (sound, smell, texture, or temperature) — research-backed: non-visual senses anchor scenes in memory more durably than visual description alone. WORLD PERIPHERY instructs the narrator to include one small background detail per scene unrelated to the player's immediate action (a sound from another room, a stranger's exchange, a worn object, weather shifting) — signals that the world continues beyond the current moment and creates a "lived-in" feel. Both rules placed directly after the existing "Describe only sensory impressions" line, which they complement.

---

## [0.9.70]

### Added
- **`ssl_extra_sans` config key** — list of additional IP addresses or hostnames to include in the auto-generated TLS certificate's SAN extension. Accepts a JSON array in `config.json` (e.g. `"ssl_extra_sans": ["77.21.237.27"]`) or a comma-separated string via the `SSL_EXTRA_SANS` environment variable. Useful for external testers accessing EdgeTales via a public IP that the Pi cannot self-detect.
- **Automatic public IP detection in cert generation** — `_fetch_public_ip()` queries `https://api.ipify.org` (5s timeout) at startup and automatically includes the current public IP in the SAN. This fixes WebSocket connections (WSS code 1006) for users accessing EdgeTales via its public IP from outside the local network. If detection fails (offline Pi, timeout), the startup continues without error.
- **`GET /download-cert`** — FastAPI endpoint (active only when `enable_https: true` without custom cert paths). Serves the auto-generated CA cert as `application/x-x509-ca-cert` with no `Content-Disposition` header, triggering iOS Safari's profile installation flow. After installation, users must enable trust in Settings → General → About → Certificate Trust Settings.

### Fixed
- **iOS Safari infinite reload / hang with auto-generated self-signed HTTPS certificate.** NiceGUI 3.x uses `crypto.randomUUID()` on page load for its implicit handshake. This Web Crypto API is gated to secure contexts; iOS Safari enforces this strictly and does not consider a page served with an uninstalled self-signed certificate a secure context — even after manually accepting the browser's SSL warning. The resulting `TypeError` caused the handshake to time out and NiceGUI to reload the page indefinitely. Root fix: `_generate_self_signed_cert()` now generates a certificate that satisfies all iOS 13+ requirements for simultaneous use as a CA root and TLS server cert: `BasicConstraints(ca=True, path_length=None)` (critical) — required by iOS to display the Certificate Trust Settings toggle; `ExtendedKeyUsage([serverAuth])` (non-critical) — mandatory for all TLS server certs per Apple's iOS 13 requirements; `KeyUsage(key_cert_sign=True, crl_sign=True, digital_signature=True)` (critical); `SubjectKeyIdentifier`; `SubjectAlternativeName`. Common Name updated from `"EdgeTales Local"` to `"EdgeTales Local CA"`. `_cert_is_ios_compatible(cert_path, key_path, required_san_ips)` replaces the old check helper and validates: `BasicConstraints(ca=True)`, `ExtendedKeyUsage(serverAuth)`, public-key fingerprint match between cert and key file (crash-mid-write protection), and presence of all required SAN entries (triggers regeneration if public IP changes). Expired certs now emit an explicit log message.
- **WSS connection fails with code 1006 for external users accessing via public IP.** The auto-generated certificate only contained local SANs (`raspi`, `127.0.0.1`, `127.0.1.1`). iOS Safari (and all browsers) require the connecting IP/hostname to appear in the cert's SAN — any mismatch causes the TLS handshake to fail at the WebSocket upgrade step, regardless of whether the cert is trusted. Fixed by auto-detecting the public IP via ipify.org and adding it to SAN during cert generation, with `ssl_extra_sans` as manual override.
- **`ssl_extra_sans` as plain string in config.json caused char-by-char iteration.** If a user wrote `"ssl_extra_sans": "77.21.237.27"` (a string) instead of `"ssl_extra_sans": ["77.21.237.27"]` (an array), `list()` on the string would iterate character-by-character, producing `['7','7','.','2','1',...]` instead of `['77.21.237.27']`. The cert would be regenerated on every startup as none of the single-char "entries" matched a valid IP. Fix: after the `file_cfg` override loop in `_load_server_config`, a string value for `ssl_extra_sans` is split on commas and stripped, producing the correct list. The ENV path already handled this correctly (comma-split was already in place there).
- **`app.storage.tab` not available after retries on iOS Safari.** `app.storage.tab` requires a `sessionStorage → WebSocket` roundtrip to establish the NiceGUI tab ID. The previous retry loop (5 × 0.5s = 2.5s) was too short for iOS Safari with a manually-trusted self-signed certificate. Extended to 30 × 1.0s (30s max). Desktop browsers succeed on the first attempt so there is no performance impact. A diagnostic log message is emitted after 5 failed attempts.
- **`key.pem` written without restricted file permissions.** Fixed: `key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)` after write. Wrapped in `try/except OSError`.
- **`~/.rpg_engine_ssl/` directory created world-traversable.** Fixed: `mkdir(mode=0o700, exist_ok=True)` plus explicit `cert_dir.chmod(0o700)` on every startup (retroactively fixes existing directories from older versions).
- **SAN IP list could contain duplicates from `getaddrinfo`.** Fixed: `_san_seen_ips` set deduplicates all IPs before appending.
- **Cert/key mismatch after crash mid-generation.** Fixed: public-key fingerprint comparison in `_cert_is_ios_compatible`.

---

## [0.9.69]

### Fixed
- **Pending NPC reflection silently lost after save/load cycle.** When an NPC's `importance_accumulator` reached the reflection threshold (≥ 30), `_needs_reflection=True` was set correctly — but `load_game()` unconditionally stripped it with `npc.pop("_needs_reflection", None)`. The accumulator value was preserved in the save (and correctly carried the threshold-crossed state), but the flag was gone. The NPC would only re-trigger a reflection if it happened to receive new memories in a subsequent turn; turns where the NPC was not in the spotlight would silently skip the Director call. Fix: the blind `pop()` is replaced with a reconstruct-from-accumulator pattern — if `importance_accumulator >= REFLECTION_THRESHOLD` on load, `_needs_reflection` is set to `True`; otherwise the flag is removed.
- **Metadata Extractor writes memory updates for NPCs not present in the scene.** `_apply_memory_updates()` had no guard against the Extractor hallucinating memory entries for NPCs that were neither activated nor mentioned in the current scene. Example: an NPC dismissed eight scenes earlier received a memory about the player's private flashback because the Extractor misread the narration context. Fix: `_apply_memory_updates()` gains three new optional parameters — `scene_present_ids` (set of NPC IDs from `activate_npcs_for_prompt`), `pre_turn_npc_ids` (set of IDs that existed before this turn's `new_npcs` were created), and `pre_turn_lore_ids` (set of IDs that had `status="lore"` before `_process_new_npcs` ran). When the first two are provided, memory updates for known, non-exempt NPCs absent from `scene_present_ids` are rejected with a warning log. Four exemptions prevent false positives: (1) freshly-created NPCs (not yet in `pre_turn_npc_ids`); (2) auto-created stubs (`pre_turn_npc_ids` is `None` in those paths); (3) NPCs with `status="lore"` or `status="deceased"` — lore always accumulates memories regardless of presence, and deceased NPCs are structurally excluded from `activate_npcs_for_prompt` so blocking them would permanently prevent resurrection via `memory_updates`; (4) NPCs in `pre_turn_lore_ids` — lore→active transitions lose their lore status before the guard runs, so their IDs are captured pre-cycle and exempted. Additionally, the premature `_reactivate_npc` call inside the auto-stub suppression path (`existing_by_name`) was removed — it ran before the guard and could promote a background NPC to active even when the memory was subsequently blocked; reactivation now happens correctly at line 5691 after the guard passes. `_apply_narrator_metadata()` captures all three ID sets before `_process_new_npcs()` and passes them through. All other call sites (correction flow, momentum burn) pass no guard sets and retain unchanged behaviour. Additionally, `pre_turn_lore_ids` is now captured *before* `_process_npc_renames` runs — `_process_npc_renames` → `_merge_npc_identity` can promote lore→active, which would have made the NPC's ID invisible to the exemption if captured afterward.
- **Save As does not copy chapter archives — only the current chapter is accessible in the new slot.** `do_save_as()` in `app.py` called `save_game()` but did not transfer the chapter archive files (`chapters/{save_name}/chapter_N.json`) to the new slot directory. Any previously completed chapters were invisible when loading the new save. Fix: new `copy_chapter_archives(username, src_name, dst_name)` helper added to `engine.py`; `do_save_as()` now calls `delete_chapter_archives()` on the destination slot first (purges stale chapters if an existing slot name is reused), then `copy_chapter_archives()` to transfer all source archives.

---

## [0.9.68]

### Fixed
- **`triggered_transitions=null` / `story_complete=null` / `revealed=null` in blueprint causes `TypeError`.** The Story Architect occasionally returns these fields as JSON `null` (explicit key with null value) instead of omitting them. `set(bp.get("revealed", []))` and similar calls only use the default when the key is **absent** — a `null` value bypasses the default and causes `set(None)` → `TypeError` in `get_current_act()`, `_check_story_completion()`, `_apply_director_guidance()`, `get_pending_revelations()`, and `_build_turn_snapshot()`. Fix: all affected sites now use `bp.get(key) or []` / `bp.get(key) or False` instead of `bp.get(key, default)`. `_apply_director_guidance()` additionally normalizes `triggered_transitions: None → []` before `setdefault`. `load_game()` strips all three null keys from the blueprint on load so the `or`-default pattern works correctly for existing saves.
- **`narration_history` entries missing `"scene"` field in all non-opening paths.** `start_new_game()` and `start_new_chapter()` were fixed in an earlier pass, but three further append sites still lacked the field: the dialog path in `process_turn()`, the action path in `process_turn()`, and the `narration_entry` dict in the `##` correction flow (used by both `input_misread` and `state_error` branches). Fix: `"scene": game.scene_count` added to all three remaining sites. `_check_story_completion()` used a pure scene counter (`scene_count >= final_end`) with no narrative awareness — it fired `story_complete=True` as soon as the planned scene range was exhausted, regardless of whether the central conflict had actually been resolved. Fix: two-stage trigger. Primary: the penultimate act must appear in `triggered_transitions` (Director confirmed the final act was narratively entered) AND `scene_count >= final_end`. Final acts have no `transition_trigger` by design, so the penultimate act's transition is the only reliable signal that the resolution phase is genuinely underway. Fallback: if no Director-confirmed transition exists (e.g. very long game without a clean phase trigger), `story_complete` fires at `final_end + 5` as a safety net. The +5 buffer is intentionally generous because Kishōtenketsu structures naturally run longer than 3-act ones. Once set, `story_complete` is never unset by this function.
- **Epilogue written in third person despite second-person game narration.** `build_epilogue_prompt` did not specify a narrative perspective — the model defaulted to a retrospective third-person voice ("He had done X...") because the `<task>` block framed the epilogue as a reflection rather than an active scene. Fix: explicit rule added to the task: `PERSPECTIVE: Second person singular ("you") throughout — the player remains the protagonist. Do NOT shift to third person.`
- **New chapter ignores epilogue — opens as if story conclusion never happened.** Three related root causes: (1) `generate_epilogue()` did not store the generated text anywhere accessible — `game.epilogue_text` did not exist; (2) `call_chapter_summary()` had no knowledge of the epilogue, so it summarized the mid-action GameState (location, session_log, current_scene_context) rather than the post-resolution state — producing `unresolved_threads` about in-progress mission steps instead of post-epilogue tensions; (3) `current_location` was never updated after the epilogue, so the chapter-2 opening was anchored to the last mid-chapter location (e.g. a 1933 safehouse instead of 2026 Berlin). Fix: (1) new field `GameState.epilogue_text = ""` stores the generated text; `generate_epilogue()` writes to it. (2) `call_chapter_summary()` gains optional `epilogue_text` parameter; when present, the epilogue is injected as an authoritative `<epilogue>` block in the Haiku prompt — summary, threads, and character growth are derived from the actual story conclusion. `CHAPTER_SUMMARY_OUTPUT_SCHEMA` extended with `post_story_location` (string) — where the protagonist physically ends up at the end of the epilogue. (3) `start_new_chapter()` reads `game.epilogue_text`, passes it to `call_chapter_summary()`, then sets `game.current_location = chapter_summary["post_story_location"]` before building the chapter-2 opening prompt. `epilogue_text` is cleared to `""` after use so it cannot bleed into subsequent chapter summaries. **Persistence note:** `epilogue_text` is included in `SAVE_FIELDS` — `app.storage.tab` does not survive `ui.navigate.reload()`, so the field must be written to disk after epilogue generation to still be available when the player clicks "New Chapter" after the reload.
- **Redundant `import re` in `score_importance()`.** The `re` module was imported locally inside the function despite already being imported at file level. Removed.
- **Redundant `mem_updates` re-read in `_apply_narrator_metadata()`.** `metadata.get("memory_updates", [])` was called twice — once at line 4396 (for slug resolution) and again at line 4419 (for applying). The second call was unnecessary since both use the same list reference (and `_resolve_slug_refs` patches npc_ids in-place). Removed the duplicate; second usage now reuses the variable from the first read.
- **Misleading comment about deceased NPC ordering in `_apply_narrator_metadata()`.** Comment said "so dead NPCs are skipped" — but `_apply_memory_updates()` intentionally resurrects deceased NPCs when the extractor reports memories for them. Corrected to accurately describe the actual behavior.
- **Momentum burn `narration_history` entry missing `scene` key.** The `narration_history` dict appended in `process_momentum_burn()` lacked the `"scene"` field that all other append sites include. Fix: `"scene": game.scene_count` added for consistency.

### Removed
- **Dead code `_try_call_director()`.** 22-line function (synchronous Director call wrapper) was never called — `process_turn()` uses the deferred pattern via `director_ctx` → `run_deferred_director()` instead.
- **Legacy momentum burn fallback (pre-v0.9.11 backward compat).** `process_momentum_burn()` contained a 25-line `else` branch for old `burn_info` dicts without `pre_snapshot`, plus inner fallback guards for `npc_bonds` and `clock_fills` fields. All burn paths have included `pre_snapshot` since v0.9.11; legacy backward compat removed. The dead `game.momentum = 0` before snapshot restore was also removed (snapshot always overwrites momentum).

---

## [0.9.67]

### Fixed
- **Stale chat history appended to new game after iOS bfcache reload mid-creation.** If the player locked their phone during the character creation confirm screen, iOS Safari restored the page from bfcache, killed the WebSocket, and triggered a `location.reload()`. On reload, `_select_user()` auto-loaded the last save into `s["messages"]`. When the player then confirmed character creation, `start()` called `s["messages"].append(...)` on the already-populated list — prepending the old story to the new opening scene and leaving the sidebar showing no character data. Fix: `s["messages"]` is now explicitly reset to `[]` in `start()` before the first append.
- **Duplicate NPC created when name or alias already belongs to an existing NPC (three-path fix).** Three deduplication gaps allowed phantom NPCs to be created: (1) The auto-stub path in `_apply_memory_updates` checked only against the player name before creating a new NPC — it did not verify whether a matching NPC already existed by name or alias. Fix: `_find_npc()` is now called on the humanized stub name before creation; if a match is found (name or any alias), the memory update is routed to the existing NPC and no stub is created. (2) `_absorb_duplicate_npc()` matched duplicates only by primary name — if the already-existing NPC carried the merged name as an alias rather than its primary name, the duplicate survived. Fix: match condition extended to also check the duplicate's alias set. (3) `_process_npc_renames()` called `_merge_npc_identity()` but never followed up with `_absorb_duplicate_npc()` — unlike `_process_npc_details()`, which already did. Fix: `_absorb_duplicate_npc()` now called after every rename.
- **NPC name matching not robust against hyphen/underscore/whitespace variants.** All NPC deduplication paths compared names via `.lower().strip()`, so `"Wacholder-im-Schnee"` and `"Wacholder im Schnee"` were treated as different NPCs, allowing phantom duplicates to slip through the fuzzy guard. Fix: new `_normalize_for_match(s)` helper collapses hyphens, underscores, and whitespace runs to a single space before lowercasing — comparison-only, stored names are never modified. Applied consistently across all dedup layers: `_find_npc()` (replaces the bespoke underscore-normalization block), `_fuzzy_match_existing_npc()` (exact-skip, substring, alias, word-overlap, and STT tokenization), `_absorb_duplicate_npc()` (matching and alias merge), `_merge_npc_identity()` (same-name guard, alias append dedup, and self-alias cleanup), `_process_new_npcs()` (`existing_names` set, lookup, and STT-variant alias append), `_process_npc_details()` (name-equality guard, extension check, and alias dedup), `_description_match_existing_npc()` (self-exclusion guard), `load_game()` self-alias backward-compat cleanup, correction-flow NPC merge path in `_apply_correction_ops()`, and the chapter-transition NPC merge loop in `start_new_chapter()`.
- **New game inherits version history of previous game in the same save slot.** `save_game()` read the existing file on disk to carry forward `version_history`, even when saving a brand-new game — so a new game started in the autosave slot accumulated the entire version history of the old game. Fix: when `scene_count ≤ 1` AND `chapter_number ≤ 1`, the version history is reset to a fresh list containing only the current version. Chapter transitions also reset `scene_count` to 1 but have `chapter_number > 1` — they correctly carry the history forward.
- **Lore NPC system: narratively significant figures who are never physically present now tracked as first-class NPCs.** Previously, characters like dead mentors, missing persons, or historical figures whose legacy drives the story were never recorded — their details scattered across other NPCs' memories or lost entirely. New status `"lore"` added alongside `active`, `background`, `deceased`. Lore NPCs collect memories and appear in a slim `<lore_figures>` narrator context block, but are never activated as scene participants and do not count against NPC limits. Transition `lore → active` happens automatically via `_reactivate_npc()` when the figure physically appears (e.g. time-travel, resurrection) — no special UI handling required; sidebar renders lore NPCs identically to background NPCs. Implementation: `_process_lore_npcs()` registers figures from new `lore_npcs` Metadata Extractor field; `NARRATOR_METADATA_SCHEMA` extended; Extractor prompt rule distinguishes lore (never present) from `new_npcs` (physically present, even if dead) and `deceased_npcs` (death depicted in prose); `_known_npcs_string()` excludes lore from scene NPC list; `_lore_figures_block()` builds the slim narrator context; all dedup paths (`_process_new_npcs`, `_merge_npc_identity`, `_apply_memory_updates`, `_description_match_existing_npc`) recognise lore status; `valid_statuses` in correction-ops updated.
- **Director generates English text mid-sentence in non-English narration games.** The Director prompt specified `in {lang}` per individual field, but the model still occasionally drifted to English in long, emotionally complex scenes. Fix: a hard top-level `LANGUAGE RULE` added to the `<task>` block, explicitly forbidding any partial English use and reiterating the requirement for all text fields in a single unambiguous sentence.
- **Player-name guards inconsistent with `_normalize_for_match()`.** Three player-name guards still used `.lower().strip()` instead of `_normalize_for_match()`: the auto-stub creation guard in `_apply_memory_updates()`, the rename-rejection guard in `_process_npc_renames()`, and the NPC filter in `_process_game_data()`. For player names containing hyphens (e.g. "Jean-Luc"), the old comparison would fail to match variants like "Jean Luc", allowing phantom stub NPCs or invalid renames. Fix: all three guards now use `_normalize_for_match()` consistently.
- **Opening-scene NPCs not visible in sidebar until scene 2.** `start_new_game()` and `start_new_chapter()` run `parse_narrator_response()` before `call_opening_metadata()` + `_process_game_data()`. Step 10 of the parser checks NPC names against the narration and sets `introduced=True` — but `game.npcs` is still empty at that point, so no NPCs are matched. `_process_game_data()` then creates NPCs with `introduced=False` (legacy default). The sidebar filters on `introduced=True`, so opening-scene NPCs were invisible until scene 2 when `parse_narrator_response()` ran again with a populated NPC list. Fix: both `start_new_game()` and `start_new_chapter()` now explicitly mark all NPCs as `introduced=True` immediately after `_process_game_data()`, since they were extracted from the narration by definition.

---

## [0.9.66]

### Fixed
- **Chapter transition loses NPCs from previous chapter (ID collision bug).** `start_new_chapter()` clears `game.npcs = []` then calls `_process_game_data()`, which reassigns IDs from `npc_1` to the new opening-scene NPCs. The subsequent merge loop then skipped returning chapter-1 NPCs by checking `old_npc["id"] in new_npc_ids` — but `npc_1` now referred to a different NPC (the new stranger), so returning NPCs like Birte Alsen (old `npc_1`) and Kasimir Rogg (old `npc_2`) were silently dropped. Fix: (1) removed the ID-based skip entirely — name-based deduplication is the only correct check after an ID reassignment; (2) reassign a fresh ID via `_next_npc_id()` when re-inserting returning NPCs, preventing any future collision; (3) `new_npc_names` set updated after each insertion to prevent hypothetical duplicates within the returning list.
- **Stale `about_npc` references after chapter transition.** As a follow-on to the ID-collision fix: returning NPCs get fresh IDs, but their memories carry `about_npc` values referencing the old IDs from the previous chapter. These no longer map to any NPC (or worse, point to the wrong one), silently breaking the NPC-to-NPC memory relevance boost in `retrieve_memories()`. Fix: after the merge loop, a single pass rewrites every `about_npc` value in all NPC memories using the `id_remap` dict built during re-insertion.
- **Clock `fired` field serialized as JSON `null` instead of `false`.** New clocks created by the Metadata Extractor did not include a `fired` field; the engine stored it as `None` which serializes to `null`. The `load_game()` backward-compat backfill check uses `"fired" not in clock` — this is `False` when `fired=null` is present as a key, causing the guard to be skipped. Fix: `_process_game_data()` now normalizes any `fired=None` to `fired=False` when adding new clocks. `load_game()` also normalizes `fired=None` → `False` for existing saves.
- **Revelation content truncated to 80 chars in narrator prompt.** `_story_context_block()` injected the pending revelation as an XML attribute with `[:80]` truncation. For revelations of 200–285 chars (typical), more than half the content was silently dropped — the narrator received an incomplete sentence and could not meaningfully act on the twist. Fix: revelation delivered as a dedicated `<revelation_ready weight="...">full content</revelation_ready>` element, no truncation.
- **Revelations marked as used regardless of narrator uptake.** `mark_revelation_used()` was called unconditionally after every scene in which a revelation was pending — even if the narrator ignored it entirely. Fix: new `call_revelation_check()` (Haiku, Structured Outputs, `REVELATION_CHECK_SCHEMA`) runs after `call_narrator_metadata()` and returns a boolean. `mark_revelation_used()` is now gated on a confirmed `True`. On extractor failure, defaults to `True` to prevent infinite pending loops. The `revelation_used` flag passed to `_should_call_director()` is also updated to use the actual confirmation result, so the Director is not falsely triggered for skipped revelations.
- **`<revelation_ready>` tag not stripped from narrator output.** The new `<revelation_ready>` XML element injected by `_story_context_block()` was missing from the prompt-echo strip list in `parse_narrator_response()` (Step 2). If the narrator echoed it back as part of the prose, it would survive all cleanup passes and appear verbatim in the player-facing text. Fix: `revelation_ready` added to the prompt-echo tag regex.

---

## [0.9.65]

### Changed
- **Dialog highlight: CSS fix for closing quote coverage.** `_highlight_dialog()` retains the proven `»***content***«` pattern (quotes outside `***` delimiters, required by CommonMark flanking rules). The visual issue of the closing quote sitting slightly outside the highlight box is fixed purely in CSS: `padding-right` on `em strong` increased from `0.50em` to `0.75em` so the marker background extends to cover the closing quote character. `margin-left: -0.5em` already covered the opening quote. No server-side HTML injection, no JS DOM manipulation — the original `***Markdown***` approach is the correct one.

### Fixed
- **Dialog highlight bleeds into surrounding narration text.** The DE quote pass wraps `„content"` → `„***content***"`, leaving the trailing ASCII `"` as a free character in the text. The subsequent ASCII double-quote pass then treated this `"` as an *opening* quote and matched all text up to the next `"` — causing entire paragraphs to be highlighted. Fix: negative lookbehind `(?<!\*\*\*)` added to the ASCII double-quote pattern so any `"` immediately following `***` (i.e. a DE-wrap closing quote) is never used as an ASCII opening quote. The `"` fallback in the DE closing character class is retained because the narrator occasionally produces ASCII `"` as closing despite the prompt rule.

### Fixed
- **Missing `def` line for `can_burn_momentum()`.** The function signature (`def can_burn_momentum(game, roll)`) was accidentally deleted in a prior edit, leaving only the docstring and body at module scope. Pylance reported 9 `"roll" is not defined` warnings (Ln 2967–2971) and 1 `"can_burn_momentum" is not defined` warning (Ln 6491). Restored the correct signature with type hints.
- **Dialog highlight: visible `***` control characters and double-highlight artefact.** Two separate bugs with a common root cause. (1) *Visible `***`*: `_highlight_dialog()` was placing quote characters *inside* the `***` delimiters (e.g. `***»content«***`). Guillemets and curly quotes are Unicode punctuation (Ps/Pe). CommonMark/markdown2 requires `***` to be left-flanking, which fails when immediately followed by punctuation — the parser left the `***` as literal visible text. Fix: quote characters placed *outside*: `»***content***«`. A `_wrap()` helper strips leading/trailing whitespace from the inner content so `***` never borders a space (would break right-flanking). (2) *Double-highlight / guillemet cross-match*: after the `»«` pass produced `»***content***«`, a sequential `«»` pass matched the resulting `«...»` span as a new opening, blending two adjacent dialog blocks into one highlight. Fix: both guillemet directions (`»«` and `«»`) are now processed in a **single combined regex pass** via alternation — prevents any cross-matching between successive quotes on the same line.
- **Narrator quote style enforced per language.** The narrator system prompt now contains an explicit `DIALOG QUOTES` rule that varies by narration language. German: `„Text."` (U+201E opens low, U+201C closes high) — standard German typographic convention. English: `"Text."` (U+201C/U+201D curly double quotes). Both rules explicitly forbid guillemets, straight ASCII `"`, and all other styles. Previously the model was free to choose and defaulted to straight ASCII `"..."` in German, causing inconsistent rendering and highlight failures. The `_highlight_dialog` regexes already cover both `„"` (DE) and `""` (EN) correctly — no regex changes needed.
- **NPC death via `##` correction sets wrong field.** When a player used `##` to report that an NPC had died, the correction brain wrote `"VERSTORBEN"` or `"DECEASED"` into the NPC's `description` field instead of setting `status = "deceased"`. Three root causes: (1) `CORRECTION_OUTPUT_SCHEMA` did not include `"status"` in `npc_edit.fields` — the model could not return it structurally; (2) `_apply_correction_ops()` `allowed` set did not contain `"status"` — it would have been silently dropped even if returned; (3) the correction brain system prompt had no instruction on how to report deaths. All three fixed: `status` added to schema (with `required`) and to `allowed`, validated against `{"active", "background", "inactive", "deceased"}`; prompt extended with explicit rule `"NPC DEATH: use npc_edit with fields.status='deceased' — do NOT write VERSTORBEN into description"`. Bonus: when `status="deceased"` is applied via correction, any existing death annotation (`VERSTORBEN`, `DECEASED`, `TOT`, `DEAD`) is automatically scrubbed from `description` via regex.
- **Metadata extractor misses supernatural/atmospheric NPC deaths.** The `deceased_npcs` extraction rule only gave concrete physical examples ("collapse, are killed, stop breathing"). Deaths described atmospherically or via supernatural forces (e.g. *"the river pulls him under, taking him forever"*) were not recognized as final. Rule extended to explicitly cover: consumed by fire, pulled under water/earth with no return described, destroyed by supernatural forces — framed as *"shown as FINAL AND IRREVERSIBLE in the prose"*.
- **Fired clocks accumulate indefinitely in `game.clocks`.** Clocks were flagged `fired: True` and hidden from the sidebar but never removed from `game.clocks`. They persisted until the chapter end (`game.clocks = []` in `start_new_chapter()`), silently bloating every narrator-metadata prompt with stale "already triggered" context. Fix: (1) all three fire sites (`apply_consequences`, `_tick_autonomous_clocks`, NPC scheme path) now record `fired_at_scene = game.scene_count`; (2) new `_purge_old_fired_clocks(game, keep_scenes=3)` removes clocks that fired more than 3 scenes ago — fired clocks are kept briefly so the narrator has short-term context (e.g. "the forensics team has arrived"), then discarded; (3) called at the start of every `process_turn()`; (4) `load_game()` backfills `fired_at_scene=0` for legacy saves with already-fired clocks — they are purged on the next turn. Sidebar clock filter unified to `not fired` (was `filled < segments`).
- **"STORY COMPLETE" badge persists in sidebar after choosing "Keep Playing".** When the epilogue offer was dismissed via "Keep Playing", `epilogue_dismissed` was set to `True` but `render_sidebar_status()` still showed the badge unconditionally. Fix: condition now additionally checks `not game.epilogue_dismissed`.

---

## [0.9.64]

### Fixed
- **529 (API overloaded) retry waits too short.** `_api_create_with_retry()` used `2^attempt` for all error types (1s, 2s, 4s). For 529 this is far too short — Anthropic's overload state typically persists for 10–60 seconds. Two-part fix: (1) 529 now uses a separate base of 10s with exponential backoff capped at 30s per wait (10s, 20s, 30s, 30s, 30s); other transient errors (429, 500–503) keep the 2s base. (2) Narrator `max_retries` raised from 3 → 5 — the most critical call during game start runs in parallel with the Architect (which has its own graceful fallback) and must have enough retries to survive a brief overload period. Worst-case total wait on sustained 529: ~2 minutes before the error reaches the user.
- **"Narrator:" / "Player:" role labels visible in chat (English UI/narration).** Two separate but related root causes:
  - *Narrator prefix in AI output:* Sonnet occasionally prefixes English narration with `"Narrator:"` — the role name from the system prompt. Does not occur in German. Two-part fix: (1) `PURE PROSE ONLY` rule in `get_narrator_system()` extended with explicit instruction not to start with role labels; (2) `parse_narrator_response()` strips any leading `Narrator:` prefix as a case-insensitive regex safety net (Step 0).
  - *sr-only labels leaking as visible text:* Screen-reader attribution spans (`<span class="sr-only">Player:</span>`, `<span class="sr-only">Narrator:</span>`) were prepended to `ui.markdown()` content strings. Two approaches failed: (1) prepending to the markdown string — DOMPurify strips the `<span>` tags, leaving the text visible; (2) rendering via a separate `ui.html()` — NiceGUI wraps `ui.html()` in a block `<div>`, and the `position: absolute` span bleeds out visibly. Final fix: role attribution is now expressed as `aria-label` directly on the message container column (`.props('aria-label="..."')`). Screen readers announce the label before reading the column content. No visible text injected. Applies to all four render sites: `render_chat_messages()`, `process_player_input()` user bubble, narrator response, and `do_recap()`.
- **Scene marker not updated after `##` correction changes location name.** When a `state_error` correction renamed a location (e.g. "Siggis Kebab" → "Simons Kebab"), `_apply_correction_ops()` updated `game.current_location` and the narration was rewritten — but the scene marker above the scene still showed the old name. Root cause: scene markers are stored as pre-formatted strings in `s["messages"]` at render time and are not touched by the correction flow. Fix: the `_is_correction` branch in `process_player_input()` now finds the most recent `scene_marker` entry in `s["messages"]` and regenerates it from the updated `game.current_location` before the full chat re-render.

---

## [0.9.63]

### Fixed
- **CSS classes and styles stripped from `ui.html()` innerHTML on desktop.** In the Quasar drawer on desktop (persistent mode, ≥768px) `class=` and `style=` attributes on elements *inside* the `innerHTML` prop of `ui.html()` were discarded by the browser — attributes on the outer NiceGUI element (via `.classes()`/`.style()`) were unaffected. Full audit and fix of all affected locations across the UI: progress bars (Health/Spirit/Supply/Chaos/Clocks/Act) converted to `ui.element()` with child element and `.style()`; scene markers (2 locations) to `ui.html(text).classes("scene-marker")`; stat grid to `ui.element()` nesting; NPC cards (active + background) to `ui.element()` nesting with `ui.label()` for bond/alias/description; `correction-badge` to `ui.element()` wrapping `ui.html()`; `dice-simple` to `ui.html(text).classes()`; scroll anchor `<div id=...>` to `ui.element('div').props('id=...')`.
- **Stat attributes rendered twice in sidebar on desktop.** The `<span class="sr-only">` accessibility spans inside `ui.html()` (intended for screen readers) had their text content rendered as a visible text node on desktop — instead of e.g. "Edge / 1", three separate lines appeared: "Edge: 1 / Edge / 1". Fix: `<span class="sr-only">` removed entirely; `aria-label` now applied directly to the `.stat-item` div via `.props()`, with inner divs set to `aria-hidden="true"`. More semantically correct and robust against rendering differences.
- **Skip-to-content link was visible on all screens.** The accessibility skip link ("Skip to game log" / "Zum Spielverlauf springen") was always visible because `position: absolute; top: -100%` is calculated relative to the NiceGUI wrapper div (which has zero height), not the viewport. Since EdgeTales has no extended navigation (the header contains only a single button), the skip link provides no benefit. Removed the `ui.html` rendering from `_show_main_phase()` and the `.skip-link` CSS rule from `custom_head.html`. The i18n keys `aria.skip_to_content` are retained.
- **Scene marker heading oversized on desktop.** Scene markers were rendered as `<h2>` — the browser default stylesheet sets `h2` to ~1.5rem, causing `.scene-marker { font-size: 0.8em }` to be calculated relative to that. Fix: `<h2>` → `<div>` in both render locations (`render_chat_messages()` and `process_player_input()`). `font-size: 0.85rem` in `.scene-marker` now applies directly against the root font size. Redundant mobile override line (`.scene-marker { font-size: 0.8em }` in the `@media` block) removed.

---

## [0.9.62]

### Changed
- **`##` correction now available after reload.** `last_turn_snapshot` is no longer transient — it is now persisted in `SAVE_FIELDS`. After an accidental disconnection or browser reload, the snapshot of the last turn remains available, allowing a single `##` correction attempt. Older saves without this field behave as before (`None` default applies; correction remains available within the same turn once a new turn is played).

### Fixed
- **`Object of type RollResult is not JSON serializable` after first turn.** `last_turn_snapshot` contains a `RollResult` dataclass object in the `roll` field. Since the snapshot is now persisted in `SAVE_FIELDS`, `json.dumps` failed during auto-save. Fix: `save_game()` converts `snapshot["roll"]` to a plain dict via `dataclasses.asdict()` before serialization; `load_game()` reconstructs the object from it via `RollResult(**r)`. Older saves and snapshots without a `roll` field (dialog turns) are backward-compatible.
- **Dialog-highlight missing several quotation mark variants.** `_highlight_dialog()` only covered DE standard (`„..."`), EN curly (`"..."`), guillemets (`«...»`), and reversed guillemets (`»...«`). Three missing variants added: straight ASCII quotes (`"..."` U+0022) — used by Sonnet for embedded or murmured dialog fragments; EN single curly (`'...'` U+2018/U+2019) — UK-style primary quotes and nested quotes inside doubles; French single guillemets (`‹...›` U+2039/U+203A) — nested quotes inside `«»`. ASCII single quotes (U+0027) are intentionally excluded — would cause false positives on contractions like `don't`, `it's`.
- **Chaos interrupt animation not visible despite Visual Effects mode being active.** The chaos animations (`chaos-text-breathe`, red ambient glow) were exclusively controlled via the `data-chaos-high` attribute, which `render_sidebar_status()` only sets at `chaos_factor >= 7`. A chaos interrupt can fire at any chaos threshold (3–9) — at lower values `chaos < 7` remained and the animations were never triggered. Fix: new CSS class `.et-chaos` with a one-shot `chaos-interrupt-pulse` keyframe (red box-shadow flash, 3.5s ease-out, active in all narrator modes). `process_player_input()` sets the class on `msg_col` when `roll_data.chaos_interrupt` is set. Runs independently of the ambient glow system (which still applies at `chaos >= 7`).

---

## [0.9.61]

### Added
- **"Wrap Up Story" button in the menu.** When a player has dismissed the epilogue offer via "Keep Playing", a new button "Wrap Up Story" (DE: "Geschichte abschließen") appears in the menu above the Recap button. Only visible when `story_complete && epilogue_dismissed && !epilogue_shown`. Clicking it sets `epilogue_dismissed = False`, saves, and reloads — the epilogue offer then reappears in the chat normally. This allows the player to trigger the epilogue at any time without waiting for an automatic trigger.
- **Hint label in the epilogue offer.** A subtle hint text (`epilogue.dismiss_hint`) appears directly below the buttons in the epilogue offer block, pointing the player to the menu button before they click "Keep Playing". New i18n key pair in DE + EN.

### Fixed
- **Post-completion pacing: infinite `phase:climax` loop after epilogue dismiss.** When a player dismissed the epilogue offer and kept playing, `get_current_act()` was stuck forever in the final act (phase `climax`) because all transitions had already been triggered. As a result, `_should_call_director()` fired **every scene** with trigger `phase:climax`, the narrator permanently received "Guide toward conclusion in 1-2 scenes", and the Director endlessly pushed toward a finale the player had deliberately rejected. Fix: `get_current_act()` now returns a synthetic `aftermath` act when `story_complete + epilogue_dismissed`. `aftermath` is not in the phase-trigger list of `_should_call_director()`, causing the Director to fall back to the normal `interval` rhythm (every 3 scenes). `_story_context_block()` emits a dedicated `<story_ending>` instruction telling the narrator to follow organically rather than push toward a conclusion. `DIRECTOR_SYSTEM` explains `aftermath` as a "Season 2 setup" mode (consequences, relationships, new organic tension arcs — no forced finale).
- **Fired clocks persist as phantom threats in the Director prompt.** Fully filled clocks had no completion flag and continued to appear in the Director's `<clocks>` block with a full fill-bar as open threats. Fix: all four clock-fill sites (`apply_consequences` MISS path, `_tick_autonomous_clocks`, NPC scheme path) now set `"fired": True` when `filled >= segments`. `build_director_prompt()` separates active and fired clocks: active clocks get the full bar with percentage and type as before; fired clocks appear only as a compact list under `fired (already triggered, no longer active)`. `load_game()` sets `fired=True` retroactively for existing saves with full clocks missing the flag (backward-compat).
- **NPC agenda becomes stale after story-changing events.** The Director could structurally never overwrite agendas — the `agenda` field in `npc_reflections` only fills empty fields (`needs_profile="true"`). NPCs whose goals had fundamentally changed through defeat, betrayal, or revelation retained their outdated agendas permanently. Fix: two new fields `updated_agenda` and `updated_instinct` in `DIRECTOR_OUTPUT_SCHEMA` (analogous to `updated_description`, always-overwriting when non-null). `_apply_director_guidance()` applies them after the fill-empty logic and logs Old→New. Prompt instructions explain when the Director should use them: for fundamental goal changes due to a story turning point — not for minor mood shifts.
- **Location variants break spatial guards and NPC proximity hints.** The Metadata Extractor sometimes returned `location_update` with appended qualifiers (e.g. `"Serge's Home in Lyon"` instead of `"Serge's Home"`). Since all three spatial comparisons used strict `==`, affected NPCs were incorrectly classified as "absent" — the dedup spatial guard in `_description_match_existing_npc()` excluded them, and prompt builders showed unnecessary `[at:...]` hints. Three-part fix: (1) New helper `_locations_match(a, b)` with fuzzy comparison: multi-word locations use word-set subset after stop-word filtering (`"Serge's Home"` ⊆ `"Serge's Home in Lyon"` → True); single-word locations use prefix-match instead of subset to prevent city name overflow. All three comparison sites updated. (2) `update_location()` now also uses `_locations_match` — qualifier variants of the current location are not treated as a real location change and `current_location` remains canonical. (3) Extractor prompt instruction for `location_update` clarified: always null when location is unchanged, short name without qualifiers on actual location change.
- **Act transitions: missing guard for final act + gaps in `triggered_transitions`.** Two related bugs in `_apply_director_guidance()`: (1) When the Director signalled `act_transition=true` while in the final act (e.g. climax with `PAST_RANGE=true`), the final act was still recorded in `triggered_transitions` — semantically wrong, since the last act by design has no transition trigger (the loop in `get_current_act()` explicitly excludes `acts[-1]`). New guard: if `act_idx >= len(acts) - 1` the signal is ignored and logged. (2) Intermediate acts skipped via scene_range fallback (Director never set `act_transition=true` within their window) were missing from `triggered_transitions`, causing gaps (e.g. `['act_0', 'act_2']` instead of `['act_0', 'act_1', 'act_2']`). Gameplay was not broken (scene_range fallback continued to work), but data was inconsistent. New back-fill: when recording an act, all preceding un-triggered acts with an exceeded scene_range are also marked.
- **Descriptor aliases polluting the NPC sidebar.** The dedup system correctly accumulates lookup aliases from descriptions the AI used before a name reveal (e.g. `"A second man in a brown doublet"`, `"The man in the brown doublet"`). These are valuable for name search and Brain target recognition, but ugly as UI display. The sidebar previously showed all aliases unfiltered under "also known as". Fix: new helper `_display_aliases(aliases)` in `app.py` filters out: aliases with >4 words, snake_case stubs (underscore), and article-started aliases with ≥3 words. Two-word epithets with article (`der Fass-Schläger`, `Die Schreiberin`) are preserved. Internally (Brain, Director, Extractor, `_find_npc`) all aliases remain visible — no lookup regression.
- **`location_history` dedup used inconsistent overlap logic.** The deduplication check when writing to `location_history` used its own word-overlap threshold (>50%), while all other location comparisons now use `_locations_match()`. The old logic did not filter stop words and had a different fuzzy threshold, which could lead to inconsistent results. `update_location()` now uses `_locations_match()` for history dedup, consistent with all other location comparisons in the engine.
- **Kishotenketsu finale never recognized as a Director trigger.** `_should_call_director()` fired phase triggers for `"climax"`, `"resolution"`, and `"ten_twist"`, but not for `"ketsu_resolution"` — the final phase of the Kishotenketsu structure type. The Director was therefore never phase-triggered in the Kishotenketsu finale, only running via the interval fallback (every 3 scenes). `"ketsu_resolution"` added to the trigger list; comment explains the symmetry between both structure types.
- **Descriptor aliases from `npc_merge` correction ops not sanitized.** When the correction flow merged two NPCs (`npc_merge` op), the `source` name was adopted as an alias in `target` without sanitization. If `source` was a descriptor name (`"A man in a brown doublet"`), it ended up unsanitized in the alias list. `_apply_name_sanitization(target)` is now called after the absorb step, before `source` is removed.
- **`_absorb_duplicate_npc` missing alias sanitization and memory consolidation.** The organic duplicate-absorb path (Metadata Extractor detects identity reveal → `_process_npc_details()` → `_absorb_duplicate_npc()`) adopted aliases from the absorbed NPC without `_apply_name_sanitization()` — descriptor names could stick as aliases, the same problem as with `npc_merge` in the correction flow. Additionally, the path did not call `_consolidate_memory()` after the memory transfer: an NPC with 25 entries absorbing another with e.g. 10 entries would end up with 35 uncompressed memories until the next organic consolidation. Both gaps closed: `_apply_name_sanitization(original)` and `_consolidate_memory(original)` are now called at the end of `_absorb_duplicate_npc()`.
- **`story_blueprint` mutations not surviving `##` correction and momentum burn rollback.** `_build_turn_snapshot()` did not back up `story_blueprint` — only NPCs, clocks, and resources were restored. Three sub-fields can change during a turn: `revealed` (when `mark_revelation_used()` is called), `triggered_transitions` (when the Director signals an act transition), and `story_complete` (when `_check_story_completion()` sets the flag). On `##` correction of such a turn these mutations remained permanent — a used revelation could never reappear, a prematurely triggered act transition stuck, a set `story_complete` triggered the epilogue flow. Fix: `_build_turn_snapshot()` now captures `bp_revealed`, `bp_triggered_transitions`, and `bp_story_complete` as list copies; `_restore_from_snapshot()` and the momentum burn restore path write them back. Backward-compatible: older snapshots without these keys skip the restore steps.
- **`_npcs_present_string` still using strict location equality.** The fallback NPC string function for `build_dialog_prompt`/`build_action_prompt` (when `activated_npcs=None`) used `npc_loc.lower() != player_loc` instead of `_locations_match`. Was the last of five location comparison sites not yet updated to fuzzy logic. Fixed.
- **Recovery moves gave no positive resource consequences.** `endure_harm`, `endure_stress`, and `resupply` had only MISS loss logic in `apply_consequences()`, but no resource gain on STRONG_HIT or WEAK_HIT — despite that being the core function of these moves. STRONG_HIT: +1 to the corresponding resource (Health/Spirit/Supply), +2 with `effect="great"`. WEAK_HIT: +1. No consequence entry if resource is already at 5 (max). The consequence appears in the `consequences` array and thus in the dice UI and session log. Crisis-exit check after recovery works correctly: when Health rises from 0 to 1 via `endure_harm` STRONG_HIT, `crisis_mode = False`.

---

## [0.9.60]

### Fixed
- **Quasar `q-focus-helper` flash removed on all buttons.** Quasar injects an empty `<span class="q-focus-helper">` into every button to render hover/active background effects. This element briefly lit up as a narrow rectangle on click — most visibly on Back, Next, Confirm, Hamburger, and drawer-close buttons. Previously suppressed only for `.choice-btn`; now suppressed globally via `.q-btn .q-focus-helper { display: none !important; }` in `custom_head.html`. Focus indication is retained via the existing `outline: 2px solid var(--accent-light)` on `:focus-visible`.
- **Missing `aria-label` on save card info button.** The `icon=info_outline` button on save slot cards had no `aria-label`, making it unnamed for screen readers. New i18n keys `aria.save_info` (DE: "Spielstand-Info anzeigen" / EN: "Show save info") added to `i18n.py`; button props updated in `app.py`.
- **Phantom delete button now `aria-hidden`.** The invisible placeholder button that keeps the delete column stable for the `autosave` slot had no `aria-hidden` attribute, so screen readers could discover and announce an unlabelled interactive element. Added `aria-hidden="true"` to its props.

---

## [0.9.59]

### Added
- **Autonomous clock ticking.** Threat clocks now advance independently of player roll results. Each scene, every unfilled threat clock that is not owner-controlled rolls an 18% chance (`AUTONOMOUS_CLOCK_TICK_CHANCE`) to tick forward by 1 segment. Ticks are logged and appended to `clock_events` in the session log. New helper `_tick_autonomous_clocks(game)` called at the end of both the dialog and action paths in `process_turn()`. Ensures world-event clocks progress even during successful or dialog-heavy sessions.
- **Director sees all clocks.** `build_director_prompt()` now injects a `<clocks>` block listing every clock with name, type, visual fill bar (`█░`), ratio, percentage and trigger description. `DIRECTOR_SYSTEM` explains what clocks represent and instructs the Director to reference them in `arc_notes` and `narrator_guidance` when ≥50% filled or recently ticked.
- **Director `tone` field enforces lowercase.** Prompt instruction for `tone` in NPC reflections now reads `1-3 lowercase English words, underscore-separated` instead of just `1-3 English words`. Prevents values like `"Vindicated_hopeful"` or `"Protective_loyal, emerging_confidence"` — these get copied into `emotional_weight` and should be consistently formatted. When a user logs in, EdgeTales now loads the save slot they last used instead of always defaulting to `autosave`. The active slot name is written to `settings.json` as `last_save` in three places: when a save is manually loaded via the sidebar, when a new game is created (writes `"autosave"`), and on login (reads `last_save`, falls back to `"autosave"` if that slot no longer exists, then falls back to no game if neither exists).

### Changed
- **Archetype-aware stat validation in `call_setup_brain`.** Two-layer safety net replaces the old single-fallback approach. Layer 0: clamp each stat 0–3 (unchanged). Layer 1: if sum ≠ 7, reset to archetype-specific defaults (`_ARCHETYPE_STAT_DEFAULTS`) instead of the blind `heart:2/wits:2` fallback. Layer 2: enforce the primary stat ≥ 2 per archetype (outsider_loner→shadow, investigator/scholar/inventor→wits, trickster→shadow, protector/hardboiled→iron, healer/artist→heart) — if below 2, points are taken from the highest non-primary stat. Custom archetype skips Layer 2. All corrections are logged as warnings. Prompt rule updated: explicit primary-stat mapping added.
- **Em-dash and en-dash replaced by regular hyphen in all AI output.** `parse_narrator_response()` Step 8.5 previously normalized spacing around em-dashes and kept them. Now both em-dash (`—`, U+2014) and en-dash (`–`, U+2013) are replaced with a spaced regular hyphen (` - `), regardless of surrounding whitespace. Same replacement applied in `call_recap()` and `generate_epilogue()`, which previously bypassed `parse_narrator_response()`.
- **Load confirmation dialog wording corrected.** "Aktuellen Fortschritt verwerfen und … laden?" → "Aktuelles Spiel verlassen und … laden?" (DE) / "Leave current game and load …?" (EN). The old wording implied unsaved data loss; since every turn auto-saves, no progress is actually discarded.

---

## [0.9.58]

### Fixed
- **Em-dash spacing normalized in narrator output.** Recent model versions started generating em-dashes without surrounding spaces (`word—word` instead of `word — word`). New Step 8.5 in `parse_narrator_response()` applies `re.sub(r'\s*—\s*', ' — ', narration)` — catches all variants (no spaces, space only before, space only after) and normalizes to exactly one space on each side. Applied to all narrator output paths: normal turns, corrections, epilogue, chapter openings.
- **Save delete and Save-As no longer trigger full page reload.** Previously deleting a save or using "Save As" called `ui.navigate.reload()`, destroying the entire page state — chat scroll position, footer, sidebar — forcing the player to navigate back manually. New `on_refresh` callback in `render_sidebar_actions()` rebuilds only the sidebar actions section in-place. The saves expansion stays open (`saves_open=True` on refresh) so the player sees the updated list immediately. Chat, footer, scroll position, and game state remain untouched. Implementation: `_show_main_phase()` wraps `render_sidebar_actions()` in a `sidebar_actions_container` with a self-referencing `_refresh_sidebar_actions()` callback that clears and re-renders only that container.
- **Chapter view enter/exit no longer triggers full page reload.** All four chapter-view transitions (enter archived chapter, back to current chapter from sidebar, exit via chat banner, exit via footer) replaced `ui.navigate.reload()` with in-process re-renders. The two exits inside `_show_main_phase()` call `await _show_main_phase()` directly (rebuilds content + footer without HTTP round-trip). The two sidebar buttons use a new `on_chapter_view_change` callback on `render_sidebar_actions()` — `_show_main_phase` passes itself as this callback. Result: chapter browsing is instant, no WebSocket reconnect, no scroll reset.
- **TTS audio player cleanup: only the latest player is kept.** Previously every TTS call appended a new `<audio>` element to the DOM; over 20+ turns with TTS enabled, dead players with expired temp-file URLs accumulated. `do_tts()` now tracks the current player in `s["_tts_player"]` and deletes the previous one before rendering a new one. `render_audio_player()` returns the element reference for tracking. Voice preview in settings is unaffected (no tracking needed).
- **Director race condition guard.** New `_director_gen` session counter, incremented at the start of every turn in `process_player_input()`. The background Director task captures this value and checks it twice: once before calling `run_deferred_director()` (skips the API call entirely if a newer turn already started — avoids mutating a game object that another thread is modifying), and once before `save_game()` (avoids overwriting a newer save). Previously only `_turn_gen` was checked, which guards against save-slot switches but not consecutive turns in the same slot.
- **Recap fallback no longer triggers page reload.** When `do_recap()` couldn't find the chat container reference (edge case, e.g. session state race), it fell back to `ui.navigate.reload()`. Now shows a toast notification instead — the recap is already saved in message history and appears on the next natural page render.
- **Save deletion resilient to filesystem errors.** `delete_save()` in the confirm-delete handler is now wrapped in try/except. If the file deletion fails (e.g. permission issue on Raspberry Pi), the error is logged, the dialog closes, and the sidebar refreshes cleanly — the un-deleted save reappears in the list instead of leaving the UI in a broken state.
- **Save info popover reduced from ~8 elements to 2 per card.** Previously each save card's info tooltip created a `ui.column()` + up to 7 individual `ui.html()` elements. Now all info lines are concatenated into a single HTML string rendered in one `ui.html()` call inside `ui.menu()`. With 10 saves, this eliminates ~60 unnecessary NiceGUI elements from the sidebar DOM.
- **Entity highlighting scoped for live turns.** `_etHighlight(data, scopeNew)` in `custom_head.html` now accepts a scope flag. When `scopeNew=true`, only elements with `.et-new` CSS class are processed instead of all `.chat-msg.assistant` elements. `process_player_input()` adds `.et-new` to the new message column and calls `_inject_entity_highlights(game, scope_new=True)`. For corrections, the duplicate `_inject_entity_highlights` call after `render_chat_messages()` is eliminated (it already calls it internally). Full-render path (`render_chat_messages`) remains unscoped — walks all messages as before.

---

## [0.9.57]

### Added
- **Game Over — Black Curtain.** `render_game_over()` now displays a dramatic fullscreen overlay: skull (💀 / ⭐ in kid mode), title, subtitle, red divider line, and flavor text appear in a staggered sequence (0.3s–2.5s). Overlay fades out after 5.2s, revealing the NiceGUI buttons. Injected as a `position:fixed` div via `ui.run_javascript()`, with `pointer-events:none` so buttons remain clickable even during the animation. All CSS animations defined in `custom_head.html` (`._go_overlay`, `._go_skull`, `._go_title`, etc.)
- **Kid Mode Game Over:** displays ⭐ instead of 💀 and a friendlier flavor text.
- **Momentum Burn — Rewind Effect.** Just before `ui.navigate.reload()` after confirming a burn, a VHS rewind effect plays: horizontal scan lines rush upward, golden chroma shimmer (three CSS layers: `_rw_lines`, `_rw_flash`, `_rw_chrom`). Effect runs for 550ms; Python waits with `asyncio.sleep(0.55)` so the new text appears only after the visual peak. CSS is dynamically injected via a `<style>` tag and removed after playback. Replaces the earlier amber burst effect.
- **New i18n keys:** `gameover.flavor` (`"{name} lies still. The story falls silent."`) and `gameover.flavor_kid` — DE + EN.
- **Cinzel font** (`wght@300;400;700;900`) added to Google Fonts import in `custom_head.html` (used by Game Over overlay title).

### Fixed
- **`narrator_font` now loaded in `load_user_settings()`.** The setting was written to user config in `save_cfg()` but never read back into session state on load. After any reload (e.g. after Momentum Burn) dialog highlights and entity highlighting were missing. Fix: `s["narrator_font"] = cfg.get("narrator_font", "sans")` added to `load_user_settings()`.
- **Scene marker missing `w-full` in `process_player_input()`.** The live-rendered scene marker (between scenes after a turn) was missing `.classes("w-full")` — the wrapping NiceGUI `<div>` was too narrow, causing `text-align: center` to appear left-aligned. `render_chat_messages()` already had the class correctly; only the live render path did not.

### Changed
- **Dialog highlight: `margin-left: -0.5em` added.** The symmetric `padding: 0 0.5em` was pushing the first character of each quote inward from the body text margin. With `margin-left: -0.5em` the text remains flush-left with the prose — the marker background overhangs slightly to the left, like a real highlighter pen on paper.

---

## [0.9.56]

### Added
- **Entity Highlighting in EdgeTales Design Mode.** NPC names and the player name are color-highlighted in narrator text — data-driven from GameState, no word lists. Disposition colors: friendly/loyal → muted green, hostile/aggressive → muted red, fearful/wary → amber. Player name in accent gold. Neutral NPCs remain uncolored. Inside dialog highlights, slightly brighter variants for contrast against the marker background. New Python functions: `_build_entity_data(game)` (builds payload from NPCs + player name, sorted longest-first), `_inject_entity_highlights(game)` (JS call after render). New JS function `_etHighlight(data)` in `custom_head.html` walks text nodes via `TreeWalker` and wraps matches in `<span>` elements. Injection at two points: `render_chat_messages()` (page load) and `process_player_input()` (live turns). CSS classes: `.et-npc-warm`, `.et-npc-hostile`, `.et-npc-wary`, `.et-player`
- **Setup info tooltip on save cards.** New ℹ️ button on each save card (between Load and Delete) shows the creation parameters: genre, tone, archetype, concept, backstory, wishes, content boundaries. Scrollable for long content (`max-height: 320px; overflow-y: auto`). Genre/tone/archetype codes resolved to localized labels via `get_genre_label()`/`get_tone_label()`/`get_archetype_label()`. Button only shown when at least one field is populated. Uses `_info_btn()` pattern with `ui.menu()` (click-to-dismiss). `get_save_info()` extended: now returns `setting_tone`, `setting_archetype`, `character_concept`, `backstory`, `player_wishes`, `content_lines`
- **`setting_archetype` in GameState.** New field `setting_archetype: str` in `GameState` and `SAVE_FIELDS`. `start_new_game()` stores the chosen archetype code. Existing saves without the field show no archetype row in the tooltip (graceful degradation).
- i18n keys: `save_info.genre`, `save_info.tone`, `save_info.archetype`, `save_info.concept`, `save_info.backstory`, `save_info.wishes`, `save_info.boundaries` (DE + EN)

### Changed
- **Dialog highlight color: Teal → Dark Red.** Marker effect changed from `hsl(159, 52%, 49%)` (teal) to `hsl(0, 52%, 20%)` (dark red/maroon). Stronger glow (0.47 vs 0.25). Dialog text brightness 86% instead of 89%. Left border-radius from 0.5em to 0.7em (softer marker entry).
- **Health vignette significantly strengthened.** Transparent center now starts at 22% instead of 28%. Edge darkening 0.85 instead of 0.65. Opacity scale: 3→0.18 (was 0.10), 2→0.40 (0.28), 1→0.62 (0.48), 0→0.82 (0.65). At health 0 only a narrow tunnel remains readable in the center.

---

## [0.9.55]

### Fixed
- **Scene marker centering consistent.** `width: 100%` added directly to the `.scene-marker` CSS in `custom_head.html`. Previously the width was only on the NiceGUI wrapper div (`.classes("w-full")`), which Quasar applies after the initial paint — `text-align: center` therefore did not reliably take effect on first load. With explicit `width: 100%` in the stylesheet the marker is correctly centered from the very first paint.
- **Double-click guard in character creation.** "Create Story" and "Re-roll" buttons now disable each other on first click (`start_btn.disable(); reroll_btn.disable()`) to prevent parallel API calls. On error both buttons are re-enabled. On the success path `ui.navigate.reload()` makes re-enabling unnecessary.

---

## [0.9.54] — EdgeTales Design Mode (Work in Progress)

### Added
- **"EdgeTales Design" reading mode** (`narrator_font = "highlight"`). New entry in the font dropdown (DE/EN: "EdgeTales Design"). Activates a bundle of atmospheric reading effects that are inactive in the normal `serif`/`sans` modes. Status: Work in Progress — being refined through testing.

- **Dialog Highlight:** Spoken dialog (all quote types: `„"` DE, `""` EN curly, `«»` / `»«` guillemets) is wrapped server-side in `_highlight_dialog()` with `***...**` (bold-italic Markdown) — including the quote marks. CSS selector `.chat-msg.assistant em strong` renders the text marker: `linear-gradient(to right, ...)` with organic `border-radius: 0.5em 0.3em`. Initial color: Teal (h=159, s=52%, l=49%). No HTML injection — passes cleanly through DOMPurify/`setHTML`.

- **`_highlight_dialog(text)`** — new helper function in `app.py` (after `_clean_narration`). Called in `render_chat_messages()` and `process_player_input()` when `narrator_font == "highlight"`.

- **Chaos text motion:** From `chaos_factor >= 8`, narrator text breathes minimally (`letter-spacing`/`word-spacing` pulses every 4s, ease-in-out). Active in highlight mode only.

- **Chaos Ambient:** From `chaos_factor >= 7`, a subtle red edge shimmer pulses (`body::after`, radial-gradient, 5s cycle). Independent of font mode. JS call in `render_sidebar_status()` sets/removes `data-chaos-high` attribute.

- **Health Vignette:** When `health <= 3`, the field of view narrows via a radial dark overlay (`body[data-narrator-font="highlight"]::before`, opacity via CSS variable `--health-vignette`). Scale: 5/4→0.0, 3→0.10, 2→0.28, 1→0.48, 0→0.65. 4s CSS transition. JS call in `render_sidebar_status()`.

- **Live font switching:** Font selection takes effect immediately after saving without a browser reload. `save_cfg()` sets `data-narrator-font` directly via JS. Reload only required when switching to/from `highlight` (server-side Markdown re-processing needed).

### Changed
- **Font dropdown renamed and simplified.** Crimson Pro removed. Three options: "Serif" / "Sans-Serif" / "EdgeTales Design" (DE+EN). Google Fonts now loads only Inter. Default serif is now Georgia/Times New Roman.
- **`i18n.py`:** `narrator_font_crimson` key removed, remaining keys updated to new short labels.
- **`save_cfg()` bugfix:** `old_font` was previously read after being overwritten — the reload trigger for highlight mode switches never fired. Read order corrected.

### Technical Notes
- Dialog highlight uses `***Markdown***` instead of `<span>` injection because NiceGUI's `ui.markdown()` sanitizes via `setHTML()` (no Safari support) or DOMPurify — both reliably stripped injected spans.
- `body::before` (health vignette) and `body::after` (chaos ambient) as separate pseudo-elements so both can be active simultaneously.
- **`_status_context_block(game)`** — new helper in `engine.py`. Maps current Health/Spirit/Supply values to 6 narrative stages each (5→0) and injects a `<character_state>` block into the narrator system prompt. The narrator is told explicitly what the numbers mean atmospherically (e.g. h=3 → "injured — clearly hurting, moving with effort"), without numbers appearing in prose. Instruction: reflect condition through body language and sensory detail, maintain consistency across scenes. Only active when `game` is present (opening calls without GameState are unaffected).

---

## [0.9.53]

### Changed
- **Info tooltips in Settings: hover → click-to-dismiss (mobile-friendly).** All 4 info icons in Settings (Kid Mode, TTS, STT, Screen Reader) now use `ui.menu()` instead of `ui.tooltip()`. The popover opens on click, stays visible until the user taps elsewhere, and is no longer obscured by a finger. New helper function `_info_btn(tip_text)` in `app.py`. ARIA label on the button is preserved for screen readers.
- **CSS variable system completed.** `custom_head.html` `:root` extended with 9 semantic variables: `--user-border` (#C45C3A, terracotta for user messages), `--success` / `--success-dim`, `--error` / `--error-dark` / `--error-dim` / `--error-border`, `--accent-border` / `--accent-dim-strong`. All previously hardcoded hex values in `custom_head.html` and `app.py` replaced with variables: track fills, dice display colors, STT waveform, correction badge border, retry banner, game over card, chapter banner, epilogue/momentum cards, STT status text, delete button, success labels, help text inline spans. Only remaining hardcoded values: spirit blue (#2563eb/#60a5fa) and scrollbar white — both semantically independent.
- **Chapter archive banner harmonized.** Background was previously `rgba(106,76,147,0.15)` (purple) — an outlier with no anchor in the color system. Now `var(--accent-dim)` / `var(--accent-border)`, consistent with all other content cards.
- **Choice button hover transition.** `transition: border-color 0.15s ease, background-color 0.15s ease` on `.choice-btn.q-btn` — color change on hover is now smooth instead of instant.
- **Scene marker visually improved.** `display: block` with `border-top` / `border-bottom` instead of flexbox lines — works correctly with multi-line location names. `letter-spacing: 0.06em` (reduced from 0.12em), font-size 0.80em. Removed `—` decorators from Python code since borders handle the separation.
- **Sidebar: Chaos display cleaned up.** Orange circle emoji and visible danger level removed (redundant alongside progress bar). Danger level moved into the progress bar's `aria-label` (`role="progressbar"` + `aria-valuenow/min/max` + `aria-label="Chaos 5 of 9 — medium"`). Visually the row now only shows `🌪 Chaos: 5/9`.
- **Typography: Inter + Crimson Pro.** Google Fonts via `<link preconnect>` + single combined request. Inter (variable font `wght@300..700`) as global UI font on `body`. Crimson Pro (`ital,wght@0,400;0,600;1,400;1,600`) optional for narrator messages (`.chat-msg.assistant`) — selectable via setting (see below).
- **Sidebar: NPC expansion fully structured.** Expansion header now shows `Disposition emoji + label — Name` (e.g. `💚 Loyal — Emilia`) instead of just the name. Expanded: `Bond: X/Y`, aliases in italics if present, then description — name and disposition symbol no longer appear redundantly in the body. Implemented via `.npc-card` CSS class. Background NPCs: same expander structure per person (individual expander per NPC inside the group expander), slightly dimmed via `opacity:0.75`. Deceased NPCs: strikethrough with padding.
- **Momentum burn card: urgency via glow animation.** New CSS class `.burn-card` with 2s keyframe `burn-glow` — subtle amber glow on box-shadow pulses gently. Amber label row (`🔥 Momentum`) above the Markdown text as a visual anchor.
- **Export button renamed.** "Export" → "PDF Export" (DE + EN), book emoji removed. Applies to sidebar button and chapter export button.
- **Narrator font as user setting.** New dropdown in Settings: Crimson Pro (serif), System sans-serif (default for new accounts), System serif. Selection takes effect live without saving, persisted to user config. Font controlled via `data-narrator-font` attribute on `body`, CSS attribute selectors override the base rule.

### Added
- `_info_btn(tip_text)` — helper function in `app.py`. Renders a flat-round icon button with `ui.menu()` as child; touch-friendly replacement for hover-based `ui.tooltip()`.
- CSS variables: `--user-border`, `--success`, `--success-dim`, `--error`, `--error-dark`, `--error-dim`, `--error-border`, `--accent-border`, `--accent-dim-strong`
- CSS classes: `.npc-card`, `.npc-name`, `.npc-meta`, `.npc-desc`, `.burn-card`
- CSS keyframe: `@keyframes burn-glow`
- i18n keys: `settings.narrator_font`, `settings.narrator_font_crimson`, `settings.narrator_font_sans`, `settings.narrator_font_serif`, `sidebar.bond`, `aria.chaos_bar` (DE + EN)

---

## [0.9.52]

### Changed
- **Sidebar: "Schnellspeichern" → "Speichern"** (DE), "Quick Save" → "Save" (EN). Shorter, clearer label for the primary save action
- **Sidebar: Trash emoji removed from "Neues Spiel" / "New Game" button.** Also removed from "Komplett neu" / "Start Fresh" buttons in Game Over and Epilogue cards. Trash emoji remains only on "Spieler entfernen" (user management) where it fits semantically
- **Savegame card title uses `ui.html` instead of `ui.markdown`.** Prevents underscores and hyphens in save names from being rendered as italic/bold formatting. Display names are HTML-escaped for safety
- **"Überrasch mich" / "Surprise Me" genre replaced with "Outdoor Survival"** (`outdoor_survival` code, 🍃 leaf emoji). Fixed genre, not random — consistent with all other genre options
- **Backstory textarea enlarged** from `rows=2` to `rows=4` in the personalize step. The placeholder example text now fits without scrolling
- **Confirmation dialogs for destructive sidebar actions:**
  - "Neues Spiel" / "New Game" now shows confirmation dialog using existing `actions.new_game_confirm` i18n strings (skipped when no game is active)
  - "Laden" / "Load" (play button on save cards) shows confirmation dialog using existing `actions.load_confirm` strings (skipped when loading the already-active save)
  - All confirmation "Ja"/"Yes" buttons use `color="positive"` (green) instead of `color="negative"` (red)
- **Creation flow: back navigation on every step.** New `creation.back` i18n key (DE: "Zurück", EN: "Back"). Back buttons on: genre_custom → genre, tone → genre, tone_custom → tone, archetype → tone, personalize → archetype, wishes → personalize, confirm → wishes. Text inputs (custom genre/tone, character name, backstory) are pre-filled when returning. Back handlers clear downstream choices (e.g. going back to tone clears archetype selection)
- **Quasar focus-helper hidden on choice buttons** (`display: none !important` on `.choice-btn .q-focus-helper`). Eliminates the narrow inner rectangle visible on genre/tone/archetype buttons when selected. Keyboard accessibility preserved via existing `:focus-visible` outline

### Added
- `creation.back` i18n key (DE: "Zurück", EN: "Back")
- `_creation_back_to_genre()`, `_creation_back_to_tone()`, `_creation_back_to_archetype()`, `_creation_back_to_personalize()`, `_creation_back_to_wishes()` — creation flow back-navigation handlers
- `import html as html_mod` in app.py for safe HTML escaping of save names

---

## [0.9.51]

### Changed
- **Opening NPCs/Clocks via Structured Outputs instead of inline `<game_data>` JSON:** The Narrator no longer produces JSON for opening scenes. Previously, `build_new_game_prompt()` and `build_new_chapter_prompt()` included a `<game_data>` JSON template that the Narrator was instructed to fill in after its prose. When Sonnet wrapped the JSON in markdown code fences (` ```json ... ``` `) instead of clean `<game_data>` tags, the parser couldn't extract it — NPCs were never registered, the entire NPC system was silently dead (total=0) while the story appeared normal from prose alone. **New architecture:** Narrator writes PURE PROSE ONLY (consistent with normal turns). A new `call_opening_metadata()` function (Haiku, Structured Outputs, `OPENING_METADATA_SCHEMA`) extracts NPCs with full schema (name, description, agenda, instinct, secrets, disposition) plus clocks, location, scene_context, and time_of_day from the finished narration — guaranteed-valid JSON. For chapter openings, accepts `known_npcs` parameter so the extractor only creates genuinely new characters. `_process_game_data()` now sets `bond=0`, `bond_max=4` defaults and auto-generates clock IDs (`clock_N`) since these mechanical fields no longer come from the Narrator template. Cost: ~$0.0002 + ~300ms per opening (one additional Haiku call). The old `<game_data>` extraction in `parse_narrator_response()` (Steps 1–1.5) remains as a safety-net for legacy context-window echoes
- **Chapter transition preserves deceased NPCs:** `start_new_chapter()` now includes `status="deceased"` NPCs in the returning-NPC list. Previously only active + background NPCs were saved before the chapter transition, silently dropping deceased NPCs from game state

### Added
- **Full roll logging:** Every dice roll is now logged with complete details: `[Roll] face_danger (iron=1): 2+3+1=6 vs [4,8] → WEAK_HIT`. Previously only match rolls (c1==c2) were logged. Applies to both normal turns in `process_turn()` and correction re-rolls. Enables post-session verification that the Narrator follows dice constraints

---

## [0.9.50]

### Changed
- **Help section rewritten for players, not developers:** Complete overhaul of the "Help — Game System" sidebar section. All texts rewritten from a player's perspective with plain language instead of system terminology. New structure flows naturally: "How do you play?" → Player Freedom → Dice Rolls → Results → Match → Position & Effect → Attributes → Tracks → Momentum → Chaos → Clocks → Crisis → Kid Mode → Correction
- **New intro section replaces Ironsworn reference:** Opens with "Just write what your character does or says" and three varied examples (action, exploration, direct dialogue) instead of "The game uses a system inspired by Ironsworn/Starforged"
- **Player Freedom moved to second position:** Previously buried near the bottom after Crisis. Now immediately follows the intro, establishing the core principle before explaining mechanics
- **Dice notation explained inline:** "2W6" / "2d6" now followed by "W6 = sechsseitiger Würfel" / "d6 = six-sided die" — one-time explanation, reader transfers to W10/d10
- **All list sections get intro sentences:** Results ("Every roll has three possible outcomes:"), Attributes ("Your character has five traits..."), Tracks ("Three tracks show how your character is doing:")
- **Position & Effect explained for players:** New intro text explains *what it means* ("How dangerous is the situation?"). Descriptions rewritten: "You have the upper hand. Even a failure won't hurt much" instead of "Advantage, milder consequences"
- **Momentum text explains full lifecycle:** Starts at 2, rises with successes, drops on misses (can go negative), spend to upgrade result + scene re-narrated in your favor, resets to 0. Previous text said "resets to starting value" (incorrect — burn resets to 0, not 2)
- **Chaos, Clocks, Crisis rewritten:** Chaos: "something unexpected may disrupt the scene" instead of "trigger unexpected scene interrupts". Clocks: "When a clock fills up, the threat strikes" instead of "Full clock = something bad happens". Crisis: explains what happens ("your character is struggling and every further failure becomes more dangerous") instead of formula notation ("Health OR Spirit at 0 = Crisis mode")
- **Result descriptions more natural:** "Everything goes to plan" instead of "Clean success", "Success, but with a catch" instead of "Success with complication"

### Added
- **Correction mode help section:** New section at the end of the help panel explaining the `##` prefix for correcting the last turn. Player-facing language: "Something went wrong? Type ## before your message to correct the last turn." with concrete example. New i18n keys: `help.correction_title`, `help.correction_text`, `help.correction_example` (DE + EN)

### Removed
- **i18n keys:** `help.dice_title`, `help.dice_text` (replaced by `help.intro_title`, `help.intro_text`)

---

## [0.9.49]

### Changed
- **`max_tokens` refactored to named constants at model ceiling:** All 9 API calls previously used hardcoded `max_tokens` values (512–6000) that caused systematic output truncation — especially in the Director (descriptions cut at ~60 chars, 60+ rejections per session) and Narrator openings (game_data JSON lost). Now uses named constants at the top of engine.py, all set to the model maximum (8192 for both Haiku and Sonnet). Structured Output calls self-terminate when the JSON schema is complete, so the higher limit only prevents truncated string fields. Free-prose calls (Narrator, Recap) self-regulate via prompt instructions. **Constants:** `BRAIN_MAX_TOKENS`, `SETUP_BRAIN_MAX_TOKENS`, `RECAP_MAX_TOKENS`, `METADATA_MAX_TOKENS`, `DIRECTOR_MAX_TOKENS`, `CHAPTER_SUM_MAX_TOKENS`, `CORRECTION_MAX_TOKENS` (all 8192), `NARRATOR_MAX_TOKENS`, `STORY_ARCH_MAX_TOKENS` (both 8192). No cost impact — you only pay for tokens actually generated

### Added
- **Orphaned input retry button on page reload:** When the page reloads after a disconnect or crash while an AI response was pending, the player's last input sits unanswered. `_show_main_phase()` now detects this after `render_chat_messages()`: if the last non-marker message is a `user` message and no processing is active, an amber-styled retry bar appears below the message with a refresh button. Clicking it calls `process_player_input(..., is_retry=True)` with the original text (including `##` prefix reconstruction for corrections). The bar self-deletes on click. ARIA: `role="alert"` on the bar, `aria-hidden="true"` on the decorative warning emoji, `aria-label` on the retry button
- **New i18n keys:** `game.retry_orphan` (DE: "Keine Antwort erhalten.", EN: "No response received.")

---

## [0.9.48]

### Fixed
- **False NPC merge from description cross-references (Name-Reference Guard):** `_description_match_existing_npc()` could falsely merge two distinct NPCs when the new NPC's description *referenced* an existing NPC by name. Real-world case: Narrator wrote that an Offizier received a whisper from "the Page in bordeauxroter Livree" — the Extractor created a new NPC "Offizier" whose description contained the words `bordeauxroter` and `livree`. The description matcher found these words overlapping with the existing Page NPC's name and description, triggering a merge that absorbed the Offizier into the Page. **Fix:** Before calculating word overlap, the matcher now strips words that appear in the candidate NPC's name or aliases (≥4 chars) from the new description's word set. If the new NPC's description merely *mentions* an existing NPC, those name-words are reference tokens, not identity evidence. Legitimate identity-reveal matches (where descriptions share distinctive non-name words like role descriptors, physical traits, or location terms) are unaffected

### Added
- **Character creation textarea length limits:** All free-text fields in character creation now have `maxlength` with Quasar's `counter` prop showing a live `X / Y` character count. Backstory: 800 chars, Wishes: 400 chars, Content Boundaries: 400 chars. Applied to both initial input and edit textareas in the confirmation step (6 textareas total). Prevents unbounded text from inflating every turn's prompt (backstory and content_boundaries are injected into Brain, Narrator, and Story Architect prompts). Existing saves with longer text are not affected — limits apply only to new input

---

## [0.9.47]

### Fixed
- **Deceased NPC presence guard too strict — mentioned NPCs now included:** `_process_deceased_npcs()` only accepted death reports for *activated* NPCs (TF-IDF score ≥ 0.7, full context in prompt). NPCs that were merely *mentioned* (score 0.3–0.7, name-only in prompt) were rejected by the guard even when the Narrator wrote their on-screen death. Real-world case: Finn was reported dead by another NPC in the narration, but Finn was only in the mentioned list (not activated) — the guard rejected his death as "likely a dialog claim". This caused a cascade: Finn stayed `status=active`, the Director assigned him new agenda/instinct *after* his narrative death, and the Chapter 2 opening narrator brought him back alive. **Fix:** `scene_present_ids` now includes both `activated_npcs` and `mentioned_npcs` IDs at all three call sites (`process_turn`, `process_correction`, `process_momentum_burn`). The guard still blocks deaths of NPCs with zero scene relevance (not activated, not mentioned, no current-scene memory)

### Changed
- **Director `max_tokens` raised from 4500 → 6000:** Log analysis of a 20-scene session showed 19 truncated descriptions rejected vs only 6 that passed (76% rejection rate). At 3 simultaneous reflections + descriptions + agenda/instinct for new NPCs, 4500 tokens is consistently insufficient. 6000 provides ~33% headroom. Haiku cost impact negligible (~$0.0002/call increase)
- **Metadata Extractor `max_tokens` raised from 2800 → 3500:** 8 of 19 metadata calls (42%) produced truncated `npc_details` descriptions that were rejected by the completeness guard. 3500 provides ~25% headroom for sessions with many NPCs and detailed `npc_details` updates
- **Narrator consistency: most recent narration kept in full (Option B):** `narration_history` entries are now stored without truncation. When building the narrator's conversation history in `call_narrator()`, only older entries ([-3] and [-2]) are truncated to `MAX_NARRATION_CHARS` (1500); the most recent entry ([-1]) is passed in full. Previously all entries were truncated at write time, which caused the narrator to lose critical end-of-scene information (character states, cliffhangers, reveals). Real-world case: Scene 16 (2201 chars) described Finn alive on a stool — truncation at char 1500 cut exactly before this, so the narrator in scene 17 invented Finn's death, directly contradicting the previous scene
- **Narrator consistency: factual event timeline injected (Option C):** New `_recent_events_block(game)` injects the last 7 `session_log` entries (using Director's `rich_summary` when available, Brain's `summary` as fallback) as a `<recent_events>` block into both `build_dialog_prompt()` and `build_action_prompt()`. Narrator system prompt rule: these are ESTABLISHED FACTS that must not be contradicted. Addresses multi-scene consistency drift (e.g. box contents changing across 3 scenes) by giving the narrator a factual backbone independent of the prose conversation history. Token overhead: ~100-200 tokens per call (~$0.001)

---

## [0.9.46]

### Fixed
- **Director split-personality reflections — aliases now visible in Director prompts:** The Director prompt (`build_director_prompt()`) showed NPC names but not aliases. When an NPC had been renamed (e.g. "Der gepanzerte Soldat" → aliases "Grevik", "Der gepanzerte Verhandler"), memories referencing the alias names appeared as if they were about a different person. The Director wrote reflections treating one NPC as two — e.g. *"Der gepanzerte Soldat scheitert gegen Greviks Verzweiflung"*. These contradictory reflections then permanently polluted the memory pool. **Three-part fix:** (1) NPC overview list now includes `aka ...` for NPCs with aliases. (2) `<reflect>` tags now carry an `aliases="..."` attribute. (3) `DIRECTOR_SYSTEM` prompt contains explicit instruction: aliases = same character, use primary name consistently
- **Metadata Extractor NPC disambiguation — location + description in reference list:** The Extractor's `<known_npcs>` reference list only showed `npc_id=Name`. When multiple NPCs had similar names or descriptions (e.g. "Der Einäugige" the barkeeper vs a soldier described as "Einäugiger Soldat"), the Extractor could misattribute memories to the wrong NPC. Now the reference list includes `[at:Location]` and a short description (`— desc[:60]`) per NPC, plus a new `NPC DISAMBIGUATION` instruction that tells the Extractor to prefer NPCs whose location matches `<current_location>`. Complements the existing code-level spatial guard in `_description_match_existing_npc()`
- **Empty-memory NPC repair on load (backward compat):** `load_game()` previously only logged a warning for active/background NPCs with no memories. Now generates a seed memory from the NPC's description + disposition (same logic as `_process_new_npcs()` seed memory, importance ≥ 3). Fixes NPCs from older saves (pre-seed-memory) or data loss scenarios. Log entry: `[Load] Repaired empty memory for '...'`

### Changed
- **Director `max_tokens` raised from 3500 → 4500:** Log analysis of a 20-scene German session showed systematic truncation when the Director generated 3+ simultaneous NPC reflections with description updates. The `_is_complete_description()` guard correctly rejected all truncated descriptions, but the high rejection rate (39 truncations in 22 calls in an earlier session at 2800, still frequent at 3500) indicated insufficient budget. 4500 provides ~29% headroom over the previous value. Haiku cost impact negligible (~$0.0001/call increase)

---

## [0.9.45]

### Fixed
- **Snake_case NPC slug resolution (`_resolve_slug_refs`):** When the Metadata Extractor creates `new_npcs` and `memory_updates` in the same response, it can't know the assigned `npc_id`s for the new NPCs. It invents snake_case slugs like `frau_seidlitz` or `moderator_headset` as references. Previously these unresolvable references caused `_apply_memory_updates()` to auto-create hollow stub NPCs — duplicates of the real NPCs just created by `_process_new_npcs()` in the same metadata cycle. New `_resolve_slug_refs()` runs after `_process_new_npcs()` and before `_apply_memory_updates()`: converts slugs to word-sets (`{moderator, headset}`) and matches them against freshly created NPC names (`{moderator, mit, headset}`) via subset check. Successfully resolves 4 of 5 slug types from the triggering savegame. Unresolvable slugs still fall through to the existing auto-stub path (now with humanized names, see below)
- **`_find_npc()` underscore normalization:** New search step 2b between exact-name and alias matching. If the reference contains underscores, replaces them with spaces and retries against all NPC names and aliases. Catches `frau_seidlitz` → `Frau Seidlitz` in any `_find_npc()` caller (Brain target resolution, memory updates, Director, corrections). Defense-in-depth behind `_resolve_slug_refs()` — catches cases where slugs appear outside the metadata cycle (e.g. Director reflections referencing NPCs by slug)
- **Auto-stub NPC name humanization:** When `_apply_memory_updates()` creates a stub NPC as last resort, snake_case names are now converted to Title Case with spaces (`kandidatin_blonde` → `Kandidatin Blonde`). Only applies to pure snake_case (no spaces already present). Technical ID pattern `npc_\d+` is excluded (existing guard). Defense-in-depth: even if slug resolution and underscore normalization both miss, the stub at least gets a human-readable display name
- **`npc_merge` correction smart direction:** The `##` correction system's `npc_merge` op now scores both NPCs by richness (memory count + description + agenda + instinct) and swaps merge direction if the AI designated the richer NPC as source. Previously the AI frequently merged well-described NPCs *into* empty stubs, losing the display name, description, agenda, and instinct. Additionally, the survivor now inherits description/agenda/instinct from the absorbed NPC if its own fields are empty

---

## [0.9.44]

### Fixed
- **False deceased marking from dialog claims (Leo-Lausemaus-Bug):** When an NPC's death was only *claimed* by another character in dialog (e.g. Brenner says "Leo ist tot" as a bluff/test), the Metadata Extractor incorrectly reported the NPC as deceased. Once marked deceased, the NPC was excluded from all processing — and the fragile resurrection path (requiring exact npc_id match in `new_npcs` or `memory_updates`) rarely triggered, leaving the NPC permanently dead even after the player explicitly contradicted the claim
- **Two-layer fix — prompt + code guard:**
  1. **Extractor prompt rewritten:** `deceased_npcs` instruction now explicitly distinguishes narrator-depicted deaths (NPC collapses, is killed on-screen) from dialog claims/reports/allegations. The key sentence: *"Do NOT mark an NPC as deceased if their death is only CLAIMED, REPORTED, or ALLEGED by another character in dialog"*
  2. **Presence guard in `_process_deceased_npcs()`:** New `scene_present_ids` parameter (set of activated NPC IDs) passed from all 4 call sites (`process_turn` dialog/action paths, `process_correction`, `process_momentum_burn`). If the NPC was not activated in the current scene AND has no memory from the current scene (which would indicate a mid-scene introduction via `new_npcs`), the deceased report is rejected with a warning log. This catches cases where the prompt fix alone might not suffice — belt-and-suspenders approach
- **Narrator truncation despite `end_turn` stop reason:** Sonnet occasionally returns `end_turn` (not `max_tokens`) with text that ends mid-word or mid-sentence. Previously, `_salvage_truncated_narration()` only ran on `max_tokens`. Now `call_narrator()` also checks if the prose ends on a non-sentence-ending character (`.!?"»«…)–—*`) and applies the same salvage logic. Logs a distinct warning: `"Response appears truncated despite end_turn"`
- **Mid-sentence truncation not salvaged on `end_turn`:** Sonnet occasionally returns `stop_reason="end_turn"` despite cutting off mid-word (e.g. narration ending with "...ein dick"). Previously `_salvage_truncated_narration()` only triggered on `stop_reason="max_tokens"`, so these broken endings passed through to the player. Now `call_narrator()` checks all `end_turn` responses for incomplete prose endings (last character not in sentence-terminal set `.!?"»«…)–—*`). If detected, the same salvage function trims to the last complete sentence

---

## [0.9.43]

### Added
- **Language onboarding dialog for first-time users:** When a newly created player is selected for the first time (empty `settings.json`), a persistent modal dialog appears prompting the user to choose their UI language and narration language before entering the app. The dialog uses `aria-label` on the dialog element itself, hides the decorative globe emoji from screen readers, and leverages Quasar's built-in focus trapping. Language dropdowns show native labels ("Deutsch", "English", "Français"…) so non-default-language speakers can self-serve. Choices are saved to `settings.json` immediately, and `load_user_settings()` re-runs after confirmation to ensure all label resolutions use the chosen language
- **Sensible defaults for new users:** The onboarding dialog sets `dice_display: 1` (Simple), `stt_enabled: true`, `whisper_size: "medium"`, and `sr_chat: true` via `setdefault()` on the new user's config
- **ARIA on settings info icons:** All four info icons in `render_settings()` (Kid Mode, TTS, STT, Screen Reader in Chat) now have `tabindex="0"`, `role="img"`, and `aria-label` with the tooltip text. Previously these icons were invisible to screen readers and unreachable by keyboard — the tooltip explanations were hover-only
- **Decorative emoji ARIA hiding:** Emojis that add no semantic value are now hidden from screen readers via `aria-label` overrides on their parent elements:
  - 🎭 mask emoji on character name (sidebar + creation confirm) → screen reader reads only the name
  - 📍 pin emoji on location line (sidebar + creation confirm) → replaced with localized prefix "Ort:" / "Location:" via new `aria.location` i18n key
  - ⚔️ swords emoji on login page title → screen reader reads only "EdgeTales"
- **New i18n keys:** `onboarding.title`, `onboarding.subtitle`, `onboarding.confirm` (DE + EN), `aria.location` (DE: "Ort", EN: "Location")

---

## [0.9.42]

### Fixed
- **`CORRECTION_OUTPUT_SCHEMA` broken since introduction — `##` corrections now actually work:** The `fields` property in `state_ops` items was defined as `{"type": ["object", "null"]}` without `properties` or `additionalProperties: false`. Anthropic's Structured Outputs API rejects schemas where any object type lacks these. Every `call_correction_brain()` call failed with a 400 error, falling back to a no-op `state_error` that only rewrote the narration without applying any state patches (`npc_edit`, `npc_split`, `npc_merge`, etc.). The `fields` object now defines all 7 editable NPC properties (`name`, `description`, `disposition`, `agenda`, `instinct`, `aliases`, `bond`) as nullable — null meaning "unchanged". The `_apply_correction_ops()` handler filters out null values before applying edits

---

## [0.9.41]

### Fixed
- **NPC identity reveal via `npc_details` now triggers merge instead of rejection:** When the Metadata Extractor sends `npc_details` with a `full_name` that differs completely from the NPC's current name (e.g. `npc_id:"npc_7"` "Der Jungfahrer" → `full_name:"Finn"`), the engine now treats this as an identity reveal via `_merge_npc_identity()` instead of logging a warning and doing nothing. Previously, this created duplicate NPCs with split memory pools — the old NPC retained early memories while a newly created NPC accumulated later ones, causing the Narrator to lose context about the character's history
- **Duplicate NPC absorption after identity reveal (`_absorb_duplicate_npc`):** New helper function that runs after `_process_npc_details` performs an identity reveal. If `_process_new_npcs` (which runs earlier in the same metadata cycle) already created a duplicate NPC with the revealed name, the function absorbs the duplicate's memories, description, agenda, instinct, and aliases into the original NPC, then removes the duplicate. Handles the specific race where the Metadata Extractor sends both `new_npcs:[{"name":"Finn"}]` and `npc_details:[{"npc_id":"npc_7","full_name":"Finn"}]` in the same response

### Changed
- **Director `max_tokens` raised from 2800 → 3500:** Log analysis showed 39 truncated NPC descriptions across 22 Director calls in a single session (avg ~1.8 per call). The truncation guard correctly rejected all of them, but the high rate indicates the 2800 budget was insufficient when the Director needs to output reflections + descriptions + guidance for multiple NPCs simultaneously. The increase matches the Narrator's 3500 budget and adds ~25% headroom for German-language output
- **Legacy `last_seen` field cleanup in `load_game()`:** Opening-scene NPC templates sometimes included a `last_seen` field (AI-generated). This field was never used by the engine (which uses `last_location`), but persisted as dead data in savegames. Now stripped on load
- **Empty-memory diagnostic in `load_game()`:** Active/background NPCs with `introduced=True` but no memories now trigger a `[Load] WARNING` log entry, helping detect potential data loss (every mid-game NPC should have at least a seed memory from `_process_new_npcs`)

---

## [0.9.40]

### Added
- **Screen reader accessibility (ARIA):** Comprehensive WCAG-informed accessibility layer for blind and visually impaired users. All ARIA labels are localized (DE + EN) via the `t()` i18n system
  - **Page landmarks:** Skip-to-content link, `role="main"` on content area, `aria-label` on header, sidebar drawer, and footer
  - **Chat log:** `role="log"` + `aria-live="polite"` on chat container — screen readers announce new narration automatically. Scene markers use `<h2>` elements enabling heading navigation (H-key on VoiceOver/NVDA) for scene-jumping
  - **sr-only role prefixes:** Every chat message is prefixed with an invisible "Spieler:" / "Erzähler:" / "Zusammenfassung:" label, embedded directly in the markdown string (no extra DOM element, no layout impact)
  - **Stat grid:** Each stat item contains a sr-only span with the combined label+value ("Geschick: 2"), with the visual children marked `aria-hidden="true"`. All numeric values explicitly cast to `int()` to prevent VoiceOver reading "2 Punkt null null"
  - **Track bars (Health, Spirit, Supply, Clocks):** `aria-hidden="true"` — the adjacent text label already conveys the same information, preventing double-reading
  - **Chaos track:** sr-only danger level suffix ("— hoch" / "— critical") appended to the visible label. Progressbar hidden from screen readers
  - **Story arc progressbar:** Retains `role="progressbar"` with `aria-valuenow/min/max` + `aria-label` — unique information not conveyed by adjacent text
  - **Icon-only buttons:** `aria-label` on hamburger menu, drawer close, send, mic, retry, save-load, save-delete buttons. All localized. Mic button label toggles dynamically between "Aufnahme starten" / "Aufnahme stoppen"
  - **Save slot buttons:** `aria-label` includes the save name ("Spielstand MeinAbenteuer laden" / "Spielstand MeinAbenteuer löschen")
  - **Creation flow:** `role="group"` + `aria-label` on genre/tone/archetype choice grids. All text inputs and textareas have `aria-label` matching their placeholder text
  - **Toast notifications:** `MutationObserver` in `custom_head.html` sets `aria-live="assertive"` on Quasar's notification container — all `ui.notify()` toasts are now announced by screen readers
  - **Error states:** `role="alert"` on login error label and inline retry row. STT status row has `role="status"` + `aria-live="polite"`
  - **Loading states:** `role="status"` on all spinner containers (TTS indicator, creation spinners, momentum burn, turn processing)
  - **Momentum burn card:** `role="alertdialog"` for immediate screen reader attention
  - **Correction badge:** `aria-label` on the "✎ Korrigiert" badge
  - **Audio player:** `aria-label` ("Sprachausgabe" / "Narration audio")
- **"Screen reader in chat" toggle** (`settings.sr_chat`): New setting in user preferences (default: on). When disabled, narrator text, player inputs, and recaps get `aria-hidden="true"` and the chat container loses `role="log"` / `aria-live`. Scene markers remain accessible (h2 headings). Designed for blind users who prefer TTS for story narration and the screen reader only for UI navigation — prevents double-reading of every passage
- **Dynamic `lang` attribute:** `document.documentElement.lang` is set via JS after session init and updated in `_show_main_phase()` to match the user's UI language. Fixes VoiceOver speaking with the wrong accent (e.g. English accent for German UI)
- **Drawer `aria-hidden` toggle:** When the sidebar drawer opens on mobile (< 768px overlay mode), `aria-hidden="true"` is set on `.q-page` and `.q-footer` to prevent screen reader bleed-through. Removed on drawer close
- **Skeleton ARIA label refresh:** All skeleton elements (hamburger button, drawer, footer, content area) have their `aria-label` re-set in `_show_main_phase()` with the correct user language, fixing stale labels from the default-language page build
- **Focus management on phase transitions:** New `_focus_element()` helper. Login phase → focus on invite code input. User selection → focus on first player button. Main phase → cascading focus priority (footer input → choice buttons → card buttons → text inputs)
- **Focus-visible indicators:** `:focus-visible` CSS with `2px solid var(--accent-light)` on all elements + Quasar overrides. Only appears on keyboard navigation, not on mouse click
- **`.sr-only` CSS class** in `custom_head.html`: Standard visually-hidden pattern (1px, absolute, clipped)
- **`.skip-link` CSS** in `custom_head.html`: Hidden link that appears on Tab focus, jumps to `#chat-log`

### Changed
- **STT recording no longer blocks on permission dialog:** `await ui.run_javascript(...)` for the `getUserMedia` call replaced with fire-and-forget `ui.run_javascript(...)` wrapping an async IIFE. Previously, Chrome's microphone permission dialog caused a full page deadlock (JS blocked → Python blocked → NiceGUI event loop frozen → all UI unresponsive until permission granted). Now Python returns immediately to the event loop, and all communication happens via `$emit` events as before
- **`position: relative` on `.stat-item`:** Fixes VoiceOver's focus rectangle being offset from the actual stat element (sr-only span's `position: absolute` needs a positioned parent for correct bounding box calculation)

### i18n
- **31 new `aria.*` keys** (DE + EN): `skip_to_content`, `menu_open`, `menu_close`, `send_message`, `start_recording`, `stop_recording`, `chat_log`, `sidebar`, `main_content`, `input_area`, `player_says`, `narrator_says`, `recap_says`, `chaos_low/medium/high/critical`, `story_progress`, `stat_item`, `momentum_stat`, `correction_badge`, `retry`, `loading`, `narration_audio`, `genre_selection`, `tone_selection`, `archetype_selection`, `load_save`, `delete_save`
- **4 new `settings.*` keys** (DE + EN): `sr_chat`, `sr_chat_tooltip`

---

## [0.9.39]

### Added
- **NPC-to-NPC relationships via `about_npc` field:** NPC memories can now reference another NPC they are about. When the player tells Sophie that Bruce is attractive, or when Sophie witnesses Bruce doing something notable, the resulting memory is tagged with `about_npc: "npc_2"`. This creates a web of NPC-to-NPC opinions that emerges organically from gameplay without a separate relationship system
- **`about_npc` in `NARRATOR_METADATA_SCHEMA`:** New optional field (`string|null`) on `memory_updates`. The metadata extractor tags memories that are primarily about another NPC (gossip, warnings, witnessed actions) with that NPC's id. Memories about the player or general events get `null`
- **`about_npc` in `DIRECTOR_OUTPUT_SCHEMA`:** New optional field (`string|null`) on `npc_reflections`. Director can now write reflections about an NPC's feelings toward another NPC (e.g. Sophie reflecting on her growing attraction to Bruce), tagged with the referenced NPC's id
- **NPC-relationship memory boost in `retrieve_memories()`:** New `present_npc_ids` parameter. Memories with `about_npc` matching a present NPC get a +0.6 relevance boost (capped at 1.0). Effect: when Sophie has an old memory about Bruce and Bruce is in the current scene, that memory rises in ranking — Sophie "thinks of it" because he's right there
- **`npc_views:` line in `_npc_block()`:** When building the target NPC's prompt context, memories tagged with `about_npc` for a present NPC are collected into a dedicated `npc_views:` line. The narrator sees e.g. `npc_views: Bruce: Player told me Bruce is attractive(intrigued)` and can weave the NPC's opinion into the scene naturally
- **Player gossip extraction rule in metadata extractor prompt:** Explicit instruction that player-initiated NPC-to-NPC communication (gossip, warnings, lies, compliments, romantic suggestions) MUST be captured as a separate `memory_update` with `about_npc` set — even if other events also happened to that NPC in the same scene. An NPC can now receive multiple memories per scene for distinctly different events

### Changed
- **`present_npc_ids` threaded through prompt builders:** `build_dialog_prompt()` and `build_action_prompt()` now collect the IDs of all NPCs present in the scene (target + activated) and pass them through `_npc_block()`, `_activated_npcs_block()`, and `retrieve_memories()`. Zero additional API cost — the set is computed once and reused
- **Director system prompt expanded for NPC-to-NPC dynamics:** `DIRECTOR_SYSTEM` now instructs the Director to consider how NPCs feel about each other (alliances, rivalries, attraction, distrust), not just about the player. Reflection prompt includes `about_npc` field documentation with example

---

## [0.9.38]

### Added
- **NPC name sanitization (`_sanitize_npc_name`, `_apply_name_sanitization`):** Strips parenthetical annotations from NPC names and extracts them as aliases. Recognizes explicit alias hints (`auch bekannt als`, `also known as`, `aka`, `genannt`, `called`) and generic epithets. Examples: `"Cremin (auch bekannt als Cremon)"` → name `"Cremin"`, alias `"Cremon"`; `"Barrel (der Fass-Schläger)"` → name `"Barrel"`, alias `"der Fass-Schläger"`. The raw annotated name is also preserved as an alias for backward search compatibility. Self-alias cleanup prevents the clean name from appearing in its own alias list
- **Backward-compat NPC name cleanup in `load_game()`:** Existing saves with parenthetical NPC names are sanitized on load. The cleanup runs after self-alias removal and before other migrations

### Changed
- **Parallel Narrator + Story Architect in `start_new_game()`:** The opening scene narrator call (Sonnet, max_tokens=3500) and the story blueprint architect call (Sonnet, max_tokens=4000) now run simultaneously via `concurrent.futures.ThreadPoolExecutor`. Previously sequential (~30s total), now completes in `max(narrator, architect)` time (~15s). Safe because the architect uses genre/tone/setting/character (fully populated from setup brain) and gets `"none yet"` for NPCs — the blueprint is about story arcs, not NPC details
- **Parallel Narrator + Story Architect in `start_new_chapter()`:** Same parallelization for chapter openings. Uses `copy.copy(game)` as a frozen snapshot for the architect thread, preventing race conditions with `parse_narrator_response()` which mutates `game.npcs`. The architect receives returning NPCs from the pre-parse state, ideal for campaign continuity
- **`scene_intensity_history` cap reduced 10 → 5:** `record_scene_intensity()` now caps at 5 entries, matching the `get_pacing_hint()` read window (`[-5:]`). Reduces save file ballast. GameState field comment already said "Last 5"

### Fixed
- **Parenthetical annotations in NPC names:** AI-generated names like `"Barrel (der Fass-Schläger)"` or metadata-extractor merge artifacts like `"Cremin (auch bekannt als Cremon)"` no longer persist as display names. Root cause: `_merge_npc_identity()` and `_process_npc_details()` accepted the full annotated string because the substring check (`old_lower in new_lower`) matched. Fix: `_sanitize_npc_name()` applied at all four NPC name entry points: `_merge_npc_identity()`, `_process_npc_details()`, `_process_new_npcs()`, `_process_game_data()`

---

## [0.9.37]

### Changed
- **Deferred save_game after rendering (app.py):** `save_game()` in `process_player_input()` moved from before rendering to after scroll completion. Player sees narration immediately — file I/O no longer blocks display. Save still runs before Director background task and TTS/burn paths
- **Director max_tokens raised 1200 → 2800:** German prose with 2+ NPC reflections regularly exceeded 1200 tokens, causing `JSONDecodeError: Unterminated string` on Structured Output truncation. Diagnosed via real savegame: 2 NPCs with `_needs_reflection=True` + full `narrator_guidance` + `npc_guidance` for 4 NPCs exceeded the limit at char 3519. 2800 provides headroom for 4–5 simultaneous reflections in German
- **All max_tokens limits raised for headroom:** German output requires ~15–20% more tokens than English. Previous limits were tuned for English and caused silent truncation on verbose German sessions. New values: `call_recap` 512 → 1200, `call_story_architect` 2500 → 4000, `call_narrator` 2500 → 3500, `call_narrator_metadata` 2000 → 2800, `call_chapter_summary` 800 → 1500, `call_correction_brain` 800 → 1500. `call_brain` and `call_setup_brain` remain at 512 (compact fixed schemas, no truncation risk). No cost impact — `max_tokens` is an upper bound, not a target

---

## [0.9.36]

### Added
- **Ephemeral correction input with fade-out:** `##`-prefixed correction messages now appear with a green left border (`.chat-msg.user.correction` CSS class), then fade out over 0.5s once the corrected narration arrives. The correction input is removed from message history before saving — it never persists in savegames or appears after reload. The `✎ Korrigiert` badge on the corrected narration remains as the permanent indicator
- **Rotating loading messages during world creation:** The "world awakens" loading text now cycles every 10 seconds through three atmospheric messages with a smooth 0.4s cross-fade: "Die Welt erwacht..." → "Schicksale werden verflochten..." → "Dein Abenteuer nimmt Gestalt an..." (DE) / "The world awakens..." → "Fates are being intertwined..." → "Your adventure takes shape..." (EN). New i18n keys: `creation.world_awakens_2`, `creation.world_awakens_3`
- **Spatial guard for NPC description matching:** `_description_match_existing_npc()` now skips candidates whose `last_location` differs from `game.current_location`. Prevents false merges when two NPCs at different locations share generic description words (e.g. "Unterarmen" matching a diner owner and a dockworker). Empty locations are treated as "potentially present" for backward compatibility

### Changed
- **`##` correction input display:** The `##` prefix is stripped before rendering and storing the player message. Previously the raw `## text` was passed to `ui.markdown()`, which rendered it as an H2 heading (large bold text). Now shows as normal text with a green `border-left` instead of the default orange
- **Correction re-render uses container context:** `render_chat_messages()` after correction is now called inside `with chat_container:`, fixing a bug where re-rendered elements landed outside the scrollable area — causing the inability to scroll after a correction
- **Correction scroll targets scene marker:** After correction re-render, the two-step scroll now targets the last scene marker (returned by `render_chat_messages()`) instead of `None`. The chat scrolls to the corrected scene's marker after the fade-out completes
- **Description match effective overlap threshold raised:** `_description_match_existing_npc()` now requires `effective_overlap >= 2.0` (was 1.5). A single shared word like "Unterarmen" (score 1.0) no longer triggers a false merge
- **Description match long-compound threshold raised:** Long-compound bonus now requires `>= 12` characters (was 10). Generic body-part words like "Unterarmen" (10 chars) no longer receive the distinctive-term bonus. Truly distinctive compounds like "NVA-Kommandant" (14 chars) still qualify

### Fixed
- **NPC introduction detection for multi-part names:** `parse_narrator_response()` Step 10 previously checked only the full NPC name as a substring (e.g. `"geschäftsführer clemens totewald"`). NPCs whose full name never appeared verbatim in narration — only partial references like "Totewald" — stayed `introduced: False` indefinitely, hiding them from the sidebar despite being active with memories. Fix: Step 10 now also checks individual name parts (≥4 chars, excluding known titles from `_NAME_TITLES`) against the narration text
- **False NPC merges via description matching across locations:** Two NPCs at different locations could be merged if their descriptions shared a single 10+ character word (e.g. "Unterarmen" in a diner owner and a dockworker). Root cause: `_description_match_existing_npc()` had no spatial awareness and the overlap threshold was too low. Fix: spatial guard + raised thresholds (see Changed)

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
