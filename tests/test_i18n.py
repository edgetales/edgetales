"""i18n completeness: DE/EN parity and every t()-key used in code exists."""
import re
from pathlib import Path

import i18n

ROOT = Path(__file__).resolve().parent.parent


def test_de_en_key_parity():
    de, en = set(i18n._STRINGS["de"]), set(i18n._STRINGS["en"])
    assert de == en, {"de_only": sorted(de - en), "en_only": sorted(en - de)}


def test_all_used_keys_exist():
    src = (ROOT / "app.py").read_text(encoding="utf-8") + (ROOT / "engine.py").read_text(encoding="utf-8")
    used = set(re.findall(r'''\bt\(\s*["']([a-z_]+\.[a-z0-9_]+)["']''', src))
    missing = used - set(i18n._STRINGS["de"])
    assert not missing, sorted(missing)


def test_placeholders_match_between_languages():
    ph = re.compile(r"\{(\w+)\}")
    for key, de_text in i18n._STRINGS["de"].items():
        en_text = i18n._STRINGS["en"][key]
        assert set(ph.findall(de_text)) == set(ph.findall(en_text)), key


def test_custom_archetype_label_is_translated():
    assert i18n.get_archetype_label("custom", "de") == "Eigene Idee"
    assert i18n.get_archetype_label("custom", "en") == "Custom idea"
