"""Co-op role choice: when the inviting user becomes the Co-GM, their running game
is copied into a new save of the invited user (copy_game_to_user)."""
import engine as E


def _setup(game):
    E.create_user("lars")
    E.create_user("jens")
    game.coop = {"seeds": [{"id": "s1", "kind": "rumor", "text": "Gerücht", "used": False}],
                 "signals": [], "partner": "alt"}
    game.chapter_number = 2
    chat = [{"role": "assistant", "content": "Szene eins"},
            {"role": "user", "content": "Ich gehe"}]
    E.save_game(game, "lars", chat, "pebby")
    E.save_chapter_archive("lars", "pebby", 1, [{"role": "assistant", "content": "Kapitel 1"}], "Anfang")
    return chat


def test_full_game_is_copied(game):
    chat = _setup(game)
    copy_, chat2, name = E.copy_game_to_user(game, chat, "jens", src_user="lars", src_save="pebby")
    assert name == "Elin"
    assert copy_.scene_count == game.scene_count and copy_.chapter_number == 2
    assert [n["name"] for n in copy_.npcs] == [n["name"] for n in game.npcs]
    assert copy_.coop["seeds"][0]["text"] == "Gerücht"          # Co-GM content travels
    assert [m["content"] for m in chat2] == ["Szene eins", "Ich gehe"]
    assert "Elin" in E.list_saves("jens")
    loaded, _ = E.load_game("jens", "Elin")
    assert loaded.scene_count == game.scene_count


def test_source_is_untouched_and_independent(game):
    chat = _setup(game)
    copy_, chat2, _ = E.copy_game_to_user(game, chat, "jens", src_user="lars", src_save="pebby")
    copy_.npcs[0]["name"] = "Geändert"
    chat2.append({"role": "user", "content": "neu"})
    assert game.npcs[0]["name"] == "Mara Voss"
    assert len(chat) == 2
    assert "pebby" in E.list_saves("lars")


def test_chapter_archives_travel_along(game):
    chat = _setup(game)
    _, _, name = E.copy_game_to_user(game, chat, "jens", src_user="lars", src_save="pebby")
    assert [a["chapter"] for a in E.list_chapter_archives("jens", name)] == [1]
    msgs, title = E.load_chapter_archive("jens", name, 1)
    assert title == "Anfang" and msgs[0]["content"] == "Kapitel 1"


def test_never_overwrites_existing_slot(game):
    chat = _setup(game)
    E.save_game(game, "jens", [], "Elin")
    _, _, name = E.copy_game_to_user(game, chat, "jens")
    assert name == "Elin_2"


def test_unknown_or_invalid_recipient(game):
    chat = _setup(game)
    assert E.copy_game_to_user(game, chat, "nobody") == (None, [], None)
    assert E.copy_game_to_user(game, chat, "../evil") == (None, [], None)
    assert E.copy_game_to_user(None, chat, "jens") == (None, [], None)


def test_i18n_has_no_duplicate_keys():
    """A duplicate key in a dict literal silently overrides the earlier text."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parent.parent / "i18n.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            dups = sorted({k for k in keys if keys.count(k) > 1})
            assert not dups, f"duplicate i18n keys: {dups}"
