"""Screen-reader support: helpers and source-level rules for app.py (offline, no browser)."""
import ast
import json
import re
from pathlib import Path

import i18n
import icons
from engine import E

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def test_plain_text_strips_ui_emoji():
    assert icons.plain_text(f"{E['dice']} Starker Treffer - Konfrontieren {E['comet']}") == \
        "Starker Treffer - Konfrontieren"
    assert icons.plain_text(f"{E['floppy']}  Spielstände") == "Spielstände"
    assert icons.plain_text(f"{E['red_circle']} Sturmflut") == "Sturmflut"     # dots too
    assert icons.plain_text("") == ""
    assert icons.plain_text(None) == ""


def test_plain_text_keeps_regular_text():
    assert icons.plain_text('Elin "die Kluge" - Akt 2') == 'Elin "die Kluge" - Akt 2'


def test_narration_lang_code_covers_all_languages():
    for label, english in i18n.LANGUAGES.items():
        assert i18n.narration_lang_code(label), f"no BCP 47 code for {english}"
    assert i18n.narration_lang_code("Deutsch") == "de"
    assert i18n.narration_lang_code("English") == "en"
    assert i18n.narration_lang_code("Klingonisch") == ""


def test_aprop_value_survives_nicegui_props_parser():
    """_aprop quotes values as Python literals (NiceGUI parses props with
    ast.literal_eval) - quotes and non-ASCII text must come back unchanged."""
    from nicegui.props import Props
    tree = ast.parse(APP)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_aprop")
    ns = {"_json": json, "plain_text": icons.plain_text}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "app.py", "exec"), ns)
    text = 'Spielstand Elin "die Kluge" löschen'
    parsed = Props.parse("flat round " + ns["_aprop"]("aria-label", f"{E['floppy']} {text}") + " dense")
    assert parsed == {"flat": True, "round": True, "aria-label": text, "dense": True}


def test_expansions_use_accessible_helper():
    """Quasar's default toggle label is English ('Expand "..."') with emoji names:
    every expansion goes through _expansion()."""
    assert APP.count("ui.expansion(") == 1          # the one inside _expansion()
    assert "def _expansion(" in APP


def test_every_dialog_has_an_accessible_name():
    lines = APP.split("\n")
    for i, line in enumerate(lines):
        if "ui.dialog()" in line and "def " not in line:
            window = "\n".join(lines[i:i + 8])
            assert ("aria-label" in window or "_label_dialog(" in window), \
                f"app.py:{i + 1} dialog without aria-label / _label_dialog"


def test_no_html_entities_in_props():
    """NiceGUI does not decode entities in prop values: '&quot;' would be read aloud."""
    assert "&quot;" not in APP


def test_sr_only_text_never_inside_markdown_or_html():
    assert not re.search(r"ui\.(markdown|html)\([^)]*sr-only", APP)
