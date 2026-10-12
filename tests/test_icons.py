"""UI icons: every emoji the interface shows must have a Lucide icon (icons.py)."""
import json
import re
from pathlib import Path

import i18n
import icons

ROOT = Path(__file__).resolve().parent.parent
# pictographs and symbols (arrows, dingbats, emoji planes)
EMOJI_RE = re.compile(r"[←-⇿⌀-⏿①-➿⤀-⯿\U0001F000-\U0001FAFF]")


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def _ui_texts():
    yield from i18n.E.values()
    for name in dir(i18n):
        obj = getattr(i18n, name)
        if name.startswith("_") and isinstance(obj, dict):
            yield from _strings(obj)
    yield (ROOT / "app.py").read_text(encoding="utf-8")


def _covered(ch):
    return ch in icons.EMOJI_ICON or ch in icons.DOT_COLORS or ch in icons.TYPOGRAPHIC


def test_every_ui_emoji_has_an_icon():
    missing = sorted({ch for txt in _ui_texts() for ch in EMOJI_RE.findall(txt) if not _covered(ch)})
    assert not missing, "Add to icons.EMOJI_ICON: " + ", ".join(f"{c} U+{ord(c):04X}" for c in missing)


def test_icon_names_exist_and_none_unused():
    used = set(icons.EMOJI_ICON.values()) | set(icons.MATERIAL_ICON.values())
    assert used <= set(icons.ICON_SVG), sorted(used - set(icons.ICON_SVG))
    assert set(icons.ICON_SVG) <= used, sorted(set(icons.ICON_SVG) - used)


def test_svg_bodies_are_plain_drawing():
    for name, body in icons.ICON_SVG.items():
        low = body.lower()
        assert "<script" not in low and " on" not in low and "href" not in low, name
        assert "currentcolor" in low, name          # icons take the text colour


def test_head_html_embeds_valid_data():
    html = icons.icon_head_html()
    m = re.search(r"var D = (\{.*?\});\n", html, re.S)
    data = json.loads(m.group(1))
    assert data["icons"] == icons.EMOJI_ICON and data["dots"] == icons.DOT_COLORS
    assert data["mi"] == icons.MATERIAL_ICON
    assert set(data["svg"]) == set(icons.ICON_SVG)


def test_choice_labels_use_one_symbol_per_meaning():
    """Genres, tones and archetypes each get their own symbol (no shared emoji)."""
    for table in (i18n._GENRES, i18n._TONES, i18n._ARCHETYPES):
        for lang, labels in table.items():
            firsts = [EMOJI_RE.search(v).group(0) for v in labels.values()]
            assert len(firsts) == len(set(firsts)), (lang, firsts)


def _material_names(src):
    names = set(re.findall(r"""icon\s*=\s*["']([a-z0-9_]+)["']""", src))
    names |= set(re.findall(r"""ui\.icon\(\s*["']([a-z0-9_]+)["']""", src))
    names |= set(re.findall(r"""\["icon"\]\s*=\s*["']([a-z0-9_]+)["']""", src))
    for block in re.findall(r"_COOP_(?:IMPULSE|BACKGROUND)_TILES = \((.*?)\n\)", src, re.S):
        names |= set(re.findall(r'\("[a-z_]+",\s*"([a-z0-9_]+)"\)', block))
    return names


def test_every_material_icon_has_a_lucide_icon():
    """Quasar icons used by the app (buttons, ui.icon, co-op tiles) are drawn as Lucide too."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    missing = sorted(_material_names(src) - set(icons.MATERIAL_ICON))
    assert not missing, "Add to icons.MATERIAL_ICON: " + ", ".join(missing)
