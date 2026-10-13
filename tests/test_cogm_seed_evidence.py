"""Co-GM seeds only count as surfaced when the narration contains a detail the seed
brought NEW into the story (guard against over-eager seeds_surfaced claims), and
Co-GM input never establishes the protagonist's own past."""
import engine as E


def _hist(game, *scenes):
    game.narration_history = [{"scene": sc, "prompt_summary": "", "narration": txt}
                              for sc, txt in scenes]


def _seed(kind="plant_secret", text="", scene=3, chapter=1):
    return {"id": "s1", "kind": kind, "text": text, "scene": scene, "chapter": chapter,
            "used": False}


SECRET = "Im Keller hinter dem Gateway steht eine alte Tür mit dem Schild Schulung vier."


def test_shared_scene_words_are_no_evidence(game):
    _hist(game, (2, "Das Gateway blinkt. Tarik hält das Tablet."),
          (3, "Der Keller riecht nach Staub, das Gateway summt."))
    narr = "Tarik liest vom Tablet die Uptime des Gateway ab. Der Keller bleibt dunkel."
    assert not E._seed_has_evidence(game, _seed(text=SECRET, scene=3), narr)


def test_new_detail_is_evidence(game):
    _hist(game, (2, "Das Gateway blinkt."), (3, "Der Keller riecht nach Staub."))
    narr = "Hinter dem Gateway: eine Tür, darauf ein Schild - 'Schulung 4'."
    assert E._seed_has_evidence(game, _seed(text=SECRET, scene=3), narr)


def test_one_new_name_is_enough(game):
    _hist(game, (2, "Ruth starrt auf die Tastatur. Eine Stimme knistert."))
    seed = _seed(kind="answer", text="Ruth erkennt die Stimme ihrer Tochter Lenz.", scene=2)
    assert E._seed_has_evidence(game, seed, "Ruths Kopf ruckt hoch. „Lenz.“")


def test_now_answer_counts_from_its_own_scene(game):
    """A NOW answer's scene is the scene it was written for: words that first
    appeared there are still new and count."""
    _hist(game, (2, "Ruth starrt auf die Tastatur."), (3, "„Lenz“, flüstert Ruth."),
          (4, "Ruth sagt nichts mehr über Lenz."))
    seed = _seed(kind="now", text="Ruth erkennt ihre Tochter Lenz.", scene=3)
    assert E._seed_has_evidence(game, seed, "Ruth sagt nichts mehr über Lenz.")


def test_filler_words_prove_nothing(game):
    _hist(game, (2, "Der Raum ist still."))
    seed = _seed(text="Jemand hat etwas Wichtiges versteckt, schon immer.", scene=2)
    assert E._seed_stems("jemand etwas schon immer") == set()
    assert not E._seed_has_evidence(game, seed, "Jemand hustet. Wieder Stille, schon immer.")


def test_seed_without_new_details_trusts_the_model(game):
    _hist(game, (2, "Das Gateway blinkt hinter dem Tablet."))
    assert E._seed_has_evidence(game, _seed(text="Das Gateway blinkt.", scene=2), "Stille.")


def test_seed_from_earlier_chapter_uses_whole_history(game):
    game.chapter_number = 2
    _hist(game, (1, "Neues Kapitel. Das Gateway blinkt."))
    seed = _seed(text="Das Gateway gehört Ruth.", scene=9, chapter=1)
    assert not E._seed_has_evidence(game, seed, "Das Gateway blinkt weiter.")
    assert E._seed_has_evidence(game, seed, "Ruth legt die Hand auf das Gateway.")


def _offer(game, seed):
    c = E.coop_state(game)
    c["seeds"].append(seed)
    game.session_log[-1]["cogm"] = {"seeds_offered": [seed["id"]]}


def test_unsupported_claim_keeps_the_seed(game, monkeypatch):
    _hist(game, (3, "Das Gateway summt im Keller."))
    _offer(game, _seed(text=SECRET, scene=3))
    monkeypatch.setattr(E, "call_cogm_question", lambda *a, **k: {
        "question": "Wer kommt?", "npc_id": "", "seeds_surfaced": ["s1"]})
    E.generate_cogm_question(None, game, "Das Gateway summt weiter im Keller.")
    assert not E.coop_state(game)["seeds"][0]["used"]


def test_supported_claim_marks_the_seed(game, monkeypatch):
    _hist(game, (3, "Das Gateway summt im Keller."))
    _offer(game, _seed(text=SECRET, scene=3))
    monkeypatch.setattr(E, "call_cogm_question", lambda *a, **k: {
        "question": "Wer kommt?", "npc_id": "", "seeds_surfaced": ["s1"]})
    E.generate_cogm_question(None, game, "Eine Tür mit dem Schild 'Schulung 4'.")
    seed = E.coop_state(game)["seeds"][0]
    assert seed["used"] and seed["used_scene"] == game.scene_count


def test_question_rules_protect_the_protagonist(game, monkeypatch):
    seen = {}

    def fake_create(client, **kw):
        seen.update(kw)
        raise RuntimeError("stop")
    monkeypatch.setattr(E, "_api_create_with_retry", fake_create)
    try:
        E.call_cogm_question(None, game, "Szene.", "now", [])
    except RuntimeError:
        pass
    assert "never about the protagonist's own past" in seen["system"]
    assert "When in doubt, leave it out" in seen["system"]


def test_narrator_rule_keeps_protagonist_past_with_the_player(game):
    E.coop_set_question(game, "Wer ist das?", "now")
    E.coop_submit_answer(game, "Ein Bote.")
    E._coop_begin_turn(game)
    block = E._coop_block(game)
    assert "not in &lt;backstory&gt;" in block or "not in <backstory>" in block
    assert "never establish it as the protagonist" in block
