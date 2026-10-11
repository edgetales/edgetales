"""Structured-output schemas: NPC-ID enums, API limits, static fallback, caching markers."""
import copy

import httpx
import pytest

import anthropic
import engine as E
from conftest import make_npc

jsonschema = pytest.importorskip("jsonschema")

# Anthropic structured-output limits (per request)
MAX_UNION_PARAMS = 16


def _walk(schema, fn):
    fn(schema)
    if isinstance(schema, dict):
        for v in schema.values():
            _walk(v, fn)
    elif isinstance(schema, list):
        for v in schema:
            _walk(v, fn)


def _union_count(schema):
    count = [0]

    def fn(node):
        if isinstance(node, dict):
            if isinstance(node.get("type"), list) or "anyOf" in node:
                count[0] += 1
    _walk(schema, fn)
    return count[0]


def _check_objects_strict(schema):
    """Every object: additionalProperties False and all properties required."""
    def fn(node):
        if isinstance(node, dict) and node.get("properties") is not None:
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) <= set(node["properties"])
    _walk(schema, fn)


def _game_with_npcs(n=3, extra_ids=()):
    g = E.GameState(player_name="P", scene_count=2)
    g.npcs = [make_npc(f"npc_{i}", f"NPC {i}") for i in range(1, n + 1)]
    for eid in extra_ids:
        g.npcs.append(make_npc(eid, f"Legacy {eid}"))
    return g


def test_id_enum_bucket_is_stable():
    g = _game_with_npcs(3)
    e1 = E._npc_id_enum(g)
    assert e1[0] == "npc_1" and e1[-1] == "npc_10" and len(e1) == 10
    g.npcs.append(make_npc("npc_4", "Vier"))
    assert E._npc_id_enum(g) == e1  # adding an NPC within the bucket: same schema
    g.npcs.append(make_npc("npc_10", "Zehn"))
    assert E._npc_id_enum(g)[-1] == "npc_20"


def test_id_enum_includes_legacy_ids():
    g = _game_with_npcs(2, extra_ids=("npc_ab12cd34",))
    assert "npc_ab12cd34" in E._npc_id_enum(g)


def test_id_enum_never_empty():
    g = E.GameState()
    assert len(E._npc_id_enum(g)) == E.NPC_ID_ENUM_BUCKET


@pytest.mark.parametrize("builder,static", [
    (E._metadata_schema_for, E.NARRATOR_METADATA_SCHEMA),
    (E._director_schema_for, E.DIRECTOR_OUTPUT_SCHEMA),
    (E._brain_schema_for, E.BRAIN_OUTPUT_SCHEMA),
])
def test_dynamic_schemas_valid_and_within_limits(builder, static):
    g = _game_with_npcs(4)
    sch = builder(g)
    jsonschema.Draft202012Validator.check_schema(sch)
    assert _union_count(sch) <= MAX_UNION_PARAMS
    _check_objects_strict(sch)
    assert static == copy.deepcopy(static)  # builder must not mutate the static schema
    assert _union_count(static) <= MAX_UNION_PARAMS


def test_static_schemas_within_limits():
    for sch in (E.NARRATOR_METADATA_SCHEMA, E.DIRECTOR_OUTPUT_SCHEMA, E.BRAIN_OUTPUT_SCHEMA,
                E.OPENING_METADATA_SCHEMA, E.CORRECTION_OUTPUT_SCHEMA):
        jsonschema.Draft202012Validator.check_schema(sch)
        assert _union_count(sch) <= MAX_UNION_PARAMS


def test_metadata_schema_accepts_ids_and_new_rejects_names():
    g = _game_with_npcs(2)
    v = jsonschema.Draft202012Validator(E._metadata_schema_for(g))
    base = {"scene_context": "x", "location_update": None, "time_update": None,
            "new_npcs": [], "npc_renames": [], "npc_details": [], "deceased_npcs": [],
            "lore_npcs": [], "exited_npc_ids": ["npc_1"]}
    ok = dict(base, memory_updates=[
        {"npc_id": "npc_1", "event": "e", "emotional_weight": "neutral",
         "about_npc": "npc_2", "absent": False, "new_npc_name": None},
        {"npc_id": "NEW", "event": "e", "emotional_weight": "neutral",
         "about_npc": None, "absent": False, "new_npc_name": "Brask"}])
    assert not list(v.iter_errors(ok))
    bad = dict(base, memory_updates=[
        {"npc_id": "Mara Voss", "event": "e", "emotional_weight": "neutral",
         "about_npc": None, "absent": False, "new_npc_name": None}])
    assert list(v.iter_errors(bad))
    bad2 = dict(base, memory_updates=[], exited_npc_ids=["frau_seidlitz"])
    assert list(v.iter_errors(bad2))


def test_brain_schema_target_is_id_or_null():
    g = _game_with_npcs(1)
    v = jsonschema.Draft202012Validator(E._brain_schema_for(g))
    doc = {"type": "action", "move": "compel", "stat": "heart", "approach": "",
           "target_npc": "npc_1", "dialog_only": False, "roll_needed": True, "player_intent": "",
           "world_addition": None, "position": "risky", "effect": "standard",
           "dramatic_question": "", "location_change": None, "time_progression": "none"}
    assert not list(v.iter_errors(doc))
    assert not list(v.iter_errors(dict(doc, target_npc=None)))
    assert list(v.iter_errors(dict(doc, target_npc="npc_1, npc_2")))


def test_resolve_new_npc_refs():
    ups = [{"npc_id": "NEW", "new_npc_name": " Brask ", "event": "a"},
           {"npc_id": "NEW", "new_npc_name": None, "event": "b"},
           {"npc_id": "npc_1", "new_npc_name": None, "event": "c"}]
    out = E._resolve_new_npc_refs(ups)
    assert [u["npc_id"] for u in out] == ["Brask", "npc_1"]
    assert all("new_npc_name" not in u for u in out)


# --- static-schema fallback --------------------------------------------------

def _bad_request(msg):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


class _Client:
    def __init__(self, fail_first_with=None):
        self.fail_first_with = fail_first_with
        self.schemas = []

        class _M:
            def create(inner, **kw):
                self.schemas.append(kw["output_config"]["format"]["schema"])
                if self.fail_first_with and len(self.schemas) == 1:
                    raise self.fail_first_with
                return "ok"
        self.messages = _M()


def test_structured_create_falls_back_on_schema_rejection():
    c = _Client(_bad_request("output_config.format.schema: enum too complex"))
    assert E._structured_create(c, {"dyn": 1}, {"static": 1}, model="m") == "ok"
    assert c.schemas == [{"dyn": 1}, {"static": 1}]
    assert E._NPC_ID_ENUM_DISABLED is True
    # Subsequent calls go straight to the static schema
    c2 = _Client()
    E._structured_create(c2, {"dyn": 1}, {"static": 1}, model="m")
    assert c2.schemas == [{"static": 1}]


def test_structured_create_reraises_unrelated_bad_request():
    c = _Client(_bad_request("prompt is too long"))
    with pytest.raises(anthropic.BadRequestError):
        E._structured_create(c, {"dyn": 1}, {"static": 1}, model="m")
    assert E._NPC_ID_ENUM_DISABLED is False


# --- prompt caching markers ---------------------------------------------------

def test_cached_system_block():
    blk = E._cached_system("abc")
    assert blk == [{"type": "text", "text": "abc", "cache_control": {"type": "ephemeral"}}]


def test_haiku_calls_send_cacheable_system_and_enum_schema(monkeypatch):
    captured = []

    def fake(client, max_retries=2, **kw):
        captured.append(kw)
        raise RuntimeError("stop")
    monkeypatch.setattr(E, "_api_create_with_retry", fake)
    g = _game_with_npcs(2)
    E.call_brain(None, g, "hi", E.EngineConfig())
    E.call_narrator_metadata(None, "Text", g, E.EngineConfig())
    for kw in captured:
        assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "enum" in str(kw["output_config"]["format"]["schema"])
