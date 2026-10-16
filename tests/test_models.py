"""Per-role model settings: config loading, kwargs mapping, option fallback, text extraction."""
import json
from types import SimpleNamespace

import httpx
import anthropic
import engine as E


def _write_cfg(**cfg):
    E.GLOBAL_CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")


def test_defaults_without_config():
    assert E.model_for("narrator") == E.NARRATOR_MODEL
    assert E.model_for("brain") == E.BRAIN_MODEL
    kw, role = E._apply_model_settings({"model": E.NARRATOR_MODEL, "max_tokens": 10})
    assert role == "narrator"
    assert kw["model"] == E.NARRATOR_MODEL
    assert kw["output_config"] == {"effort": "high"} and "thinking" not in kw


def test_config_file_maps_roles_and_merges_output_config():
    _write_cfg(narrator_model="claude-sonnet-5-5", narrator_effort="HIGH",
               narrator_thinking="between_tools", brain_model="claude-haiku-5-5",
               brain_effort="low", brain_thinking="disabled")
    kw, role = E._apply_model_settings({"model": E.NARRATOR_MODEL})
    assert role == "narrator"
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["output_config"] == {"effort": "high"}
    assert kw["thinking"] == {"type": "between_tools"}
    fmt = {"format": {"type": "json_schema", "schema": {"type": "object"}}}
    kw, role = E._apply_model_settings({"model": E.BRAIN_MODEL, "output_config": fmt})
    assert role == "brain" and kw["model"] == "claude-haiku-5-5"
    assert kw["output_config"]["format"] == fmt["format"]
    assert kw["output_config"]["effort"] == "low"
    assert fmt == {"format": {"type": "json_schema", "schema": {"type": "object"}}}  # not mutated


def test_invalid_values_are_ignored():
    _write_cfg(narrator_effort="turbo", narrator_thinking="always", narrator_model="  ")
    s = E.get_model_settings()["narrator"]
    assert s == {"model": E.NARRATOR_MODEL, "effort": "high", "thinking": None}


def test_role_defaults_without_config():
    _write_cfg()
    st = E.get_model_settings()
    assert st["narrator"] == {"model": "claude-sonnet-5-5", "effort": "high", "thinking": None}
    assert st["brain"] == {"model": "claude-haiku-5-5", "effort": None, "thinking": "disabled"}


def test_explicit_model_id_passes_through():
    _write_cfg(narrator_model="claude-sonnet-5-5", narrator_effort="max")
    kw, role = E._apply_model_settings({"model": "claude-opus-5-5"})
    assert role is None and kw == {"model": "claude-opus-5-5"}


def _bad_request(msg):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


class _Client:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = []

        class _M:
            def create(inner, **kw):
                self.calls.append(kw)
                if self.errors:
                    raise self.errors.pop(0)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")],
                                       usage=None)
        self.messages = _M()


def test_rejected_effort_is_dropped_and_remembered():
    _write_cfg(narrator_model="claude-sonnet-4-6", narrator_effort="xhigh")
    c = _Client([_bad_request("effort 'xhigh' is not supported for this model")])
    E._api_create_with_retry(c, max_retries=0, model=E.NARRATOR_MODEL, max_tokens=10)
    assert c.calls[0]["output_config"] == {"effort": "xhigh"}
    assert "output_config" not in c.calls[1]
    assert ("narrator", "effort") in E._REJECTED_OPTIONS
    E._api_create_with_retry(c, max_retries=0, model=E.NARRATOR_MODEL, max_tokens=10)
    assert "output_config" not in c.calls[2]


def test_rejected_thinking_disabled_uses_the_named_off_mode():
    # Sonnet 5.5 refuses "disabled"; dropping the option left adaptive thinking on,
    # which ate max_tokens of short calls (truncated or empty answers).
    _write_cfg(brain_model="claude-sonnet-5-5", brain_effort="high")
    c = _Client([_bad_request('To turn thinking off on this model, send "thinking": '
                              '{"type": "between_tools"} instead of {"type": "disabled"}.')])
    E._api_create_with_retry(c, max_retries=0, model=E.BRAIN_MODEL, max_tokens=10)
    assert c.calls[0]["thinking"] == {"type": "disabled"}
    assert c.calls[1]["thinking"] == {"type": "between_tools"}
    assert ("brain", "thinking") not in E._REJECTED_OPTIONS
    E._api_create_with_retry(c, max_retries=0, model=E.BRAIN_MODEL, max_tokens=10)
    assert c.calls[2]["thinking"] == {"type": "between_tools"}   # remembered, no new 400
    assert len(c.calls) == 3


def test_rejected_thinking_without_named_mode_is_dropped():
    _write_cfg(brain_thinking="adaptive")
    c = _Client([_bad_request("thinking is not supported for this model")])
    E._api_create_with_retry(c, max_retries=0, model=E.BRAIN_MODEL, max_tokens=10)
    assert "thinking" not in c.calls[1]
    assert ("brain", "thinking") in E._REJECTED_OPTIONS


def test_rejected_effort_keeps_structured_output_format():
    _write_cfg(brain_effort="max")
    fmt = {"format": {"type": "json_schema", "schema": {"type": "object"}}}
    c = _Client([_bad_request("output_config.effort: unsupported value")])
    E._api_create_with_retry(c, max_retries=0, model=E.BRAIN_MODEL, output_config=fmt)
    assert c.calls[1]["output_config"] == fmt


def test_unrelated_bad_request_still_raises():
    _write_cfg(narrator_effort="high")
    c = _Client([_bad_request("prompt is too long")])
    try:
        E._api_create_with_retry(c, max_retries=0, model=E.NARRATOR_MODEL)
        raise AssertionError("expected BadRequestError")
    except anthropic.BadRequestError:
        pass
    assert not E._REJECTED_OPTIONS


def test_response_text_skips_thinking_blocks():
    resp = SimpleNamespace(content=[
        SimpleNamespace(type="thinking", thinking="hmm"),
        SimpleNamespace(type="text", text='{"a": '),
        SimpleNamespace(type="text", text="1}"),
    ])
    assert E._response_text(resp) == '{"a": 1}'
    assert E._response_text(SimpleNamespace(content=[])) == ""


def test_brain_defaults_to_haiku_5_5_without_thinking():
    s = E.get_model_settings()["brain"]
    assert s["model"] == "claude-haiku-5-5" == E.BRAIN_MODEL
    assert s["thinking"] == "disabled"
    kw, _ = E._apply_model_settings({"model": E.BRAIN_MODEL})
    assert kw["thinking"] == {"type": "disabled"}


def test_brain_thinking_can_be_overridden():
    _write_cfg(brain_thinking="adaptive")
    assert E.get_model_settings()["brain"]["thinking"] == "adaptive"
