#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge Tales - Narrative Solo RPG Engine 
===================================================
Central module for all UI-facing text, labels, and display strings.
Supports multiple languages with German as default/fallback.

Usage:
    from i18n import t, E, UI_LANGUAGES, DEFAULT_LANG, get_stat_labels, get_genres, ...
    lang = "de"                        # or "en"
    label = t("login.title", lang)     # → "EdgeTales"
    stats = get_stat_labels(lang)      # → {"edge": "Geschick", ...}
"""

# ===============================================================
# EMOJI / UNICODE CONSTANTS (shared across all modules)
# ===============================================================

E = {
    "castle": "\U0001F3F0",
    "rocket": "\U0001F680",
    "crystal": "\U0001F52E",
    "gear": "\u2699\uFE0F",
    "city": "\U0001F306",
    "swords": "\u2694\uFE0F",
    "dice": "\U0001F3B2",
    "black_heart": "\U0001F5A4",
    "scales": "\u2696\uFE0F",
    "moon_half": "\U0001F317",
    "skull": "\U0001F480",
    "candle": "\U0001F56F\uFE0F",
    "dagger": "\U0001F5E1\uFE0F",
    "search": "\U0001F50D",
    "speech": "\U0001F4AC",
    "shield": "\U0001F6E1\uFE0F",
    "books": "\U0001F4DA",
    "pen": "\u270D\uFE0F",
    "red_circle": "\U0001F534",
    "orange_circle": "\U0001F7E0",
    "white_circle": "\u26AA",
    "green_circle": "\U0001F7E2",
    "green_heart": "\U0001F49A",
    "purple_circle": "\U0001F7E3",
    "fear": "\U0001F628",
    "yellow_heart": "\U0001F49B",
    "heart_red": "\u2764\uFE0F",
    "heart_blue": "\U0001F499",
    "yellow_dot": "\U0001F7E1",
    "lightning": "\u26A1",
    "dark_moon": "\U0001F311",
    "brain": "\U0001F9E0",
    "mask": "\U0001F3AD",
    "pin": "\U0001F4CD",
    "warn": "\u26A0\uFE0F",
    "clock": "\u23F0",
    "book": "\U0001F4D6",
    "check": "\u2705",
    "play": "\u25B6",
    "scroll": "\U0001F4DC",
    "people": "\U0001F465",
    "floppy": "\U0001F4BE",
    "folder": "\U0001F4C2",
    "trash": "\U0001F5D1\uFE0F",
    "globe": "\U0001F30D",
    "mic": "\U0001F399\uFE0F",
    "question": "\u2753",
    "microphone": "\U0001F3A4",
    "fire": "\U0001F525",
    "flag": "\U0001F3C1",
    "refresh": "\U0001F504",
    "x_mark": "\u274C",
    "arrow_r": "\u2192",
    "checkmark": "\u2713",
    "dot": "\u00B7",
    "dash": "\u2014",
    "ndash": "\u2013",
    "tornado": "\U0001F32A\uFE0F",
    "leaf": "\U0001F343",
    "cherry": "\U0001F338",
    "plus": "\u2795",
    "star": "\u2728",
    "comet": "\u2604\uFE0F",
}


# ===============================================================
# NARRATION LANGUAGES (for AI narration, not UI)
# ===============================================================

LANGUAGES = {
    "Deutsch": "German",
    "English": "English",
    "Espa\u00F1ol": "Spanish",
    "Fran\u00E7ais": "French",
    "Portugu\u00EAs": "Portuguese",
    "Italiano": "Italian",
    "Nederlands": "Dutch",
    "\u0420\u0443\u0441\u0441\u043A\u0438\u0439": "Russian",
    "\u4E2D\u6587": "Chinese (Mandarin)",
    "\u65E5\u672C\u8A9E": "Japanese",
    "\uD55C\uAD6D\uC5B4": "Korean",
    "\u0627\u0644\u0639\u0631\u0628\u064A\u0629": "Arabic",
    "\u0939\u093F\u0928\u094D\u0926\u0940": "Hindi",
    "Bahasa Indonesia": "Indonesian",
    "T\u00FCrk\u00E7e": "Turkish",
    "Polski": "Polish",
    "Ti\u1EBFng Vi\u1EC7t": "Vietnamese",
    "\u0E44\u0E17\u0E22": "Thai",
    "Svenska": "Swedish",
    "Dansk": "Danish",
}


# ===============================================================
# UI LANGUAGE CONFIGURATION
# ===============================================================

# Available UI languages (require manual translation work)
UI_LANGUAGES = {
    "Deutsch": "de",
    "English": "en",
}

DEFAULT_LANG = "de"
FALLBACK_LANG = "de"


# ===============================================================
# UI STRINGS — flat key structure with dot notation
# ===============================================================

_STRINGS = {
    # ── GERMAN (default / fallback) ──────────────────────────
    "de": {
        # Connection / Loading
        "conn.loading": "Verbindung wird aufgebaut...",

        # Login
        "login.title": "EdgeTales",
        "login.subtitle": "Zugang nur mit Einladungscode.",
        "login.code_label": "Einladungscode",
        "login.error": "Falscher Code.",
        "login.rate_limited": "Zu viele Versuche. Bitte 5 Minuten warten.",
        "login.submit": "Eintreten",

        # User Selection
        "user.title": "EdgeTales",
        "user.subtitle": "A Narrative Solo\u2011RPG Engine",
        "user.who_plays": "Wer spielt?",
        "user.new_player": "Neuer Spieler",
        "user.name": "Name",
        "user.name_placeholder": "Dein Name...",
        "user.create": "Spieler anlegen",
        "user.manage": "Spieler verwalten",
        "user.remove_label": "Spieler entfernen",
        "user.confirm_delete": 'Wirklich "{name}" l\u00f6schen?',
        "user.yes": "Ja",
        "user.no": "Nein",
        "user.exists": 'Spieler "{name}" existiert bereits.',
        "user.api_hint": "API Key nach Spielerauswahl in den Einstellungen hinterlegen.",
        "user.api_missing": "Bitte API Key in den Einstellungen eingeben.",

        # Sidebar — Status
        "sidebar.kid_mode": "Kindermodus",
        "sidebar.crisis": "KRISE",
        "sidebar.crisis_kid": "IN NOT",
        "sidebar.finale": "FINALE",
        "sidebar.story_complete": "GESCHICHTE ABGESCHLOSSEN",
        "sidebar.scene": "Szene",
        "sidebar.momentum": "Momentum",
        "sidebar.health": "Gesundheit",
        "sidebar.spirit": "Willenskraft",
        "sidebar.supply": "Vorr\u00e4te",
        "sidebar.chaos": "Chaos",
        "sidebar.clocks": "Uhren",
        "sidebar.persons": "Personen",
        "sidebar.known_persons": "Bekannte",
        "sidebar.npc_aka": "auch bekannt als",
        "sidebar.chapter": "Kap.",
        "sidebar.3act": "3-Akt",
        "sidebar.act": "Akt",

        # Story Arc Phase Labels
        "story.setup": "Einf\u00fchrung",
        "story.confrontation": "Konfrontation",
        "story.climax": "Klimax",
        "story.ki_introduction": "Ki",
        "story.sho_development": "Sh\u014d",
        "story.ten_twist": "Ten",
        "story.ketsu_resolution": "Ketsu",

        # Sidebar — Actions
        "actions.recap": "Was bisher geschah...",
        "actions.recap_prefix": "Was bisher geschah...",
        "actions.recap_loading": "Erz\u00e4hler erinnert sich...",
        "actions.saves": "Spielst\u00e4nde",
        "actions.save_name": "Name",
        "actions.save": "Speichern",
        "actions.save_as": "Speichern unter...",
        "actions.save_as_placeholder": "Neuer Spielstandname...",
        "actions.save_as_btn": "Neuen Spielstand anlegen",
        "actions.saved": "Gespeichert!",
        "actions.active_save": "Aktiv: {name}",
        "actions.quick_save": "Schnellspeichern",
        "actions.load": "Laden",
        "actions.load_label": "Laden",
        "actions.load_confirm": "Aktuellen Fortschritt verwerfen und \u00ab{name}\u00bb laden?",
        "actions.delete": "L\u00f6schen",
        "actions.delete_confirm": "Spielstand \u00ab{name}\u00bb wirklich l\u00f6schen?",
        "actions.deleted": "Gel\u00f6scht!",
        "actions.new_game": "Neues Spiel",
        "actions.new_game_confirm": "Aktuelles Spiel beenden und neu starten?",
        "actions.export": "Export",
        # Export story
        "export.subtitle": "Eine Geschichte",
        "export.exported_at": "Exportiert am {timestamp}",
        "export.character": "CHARAKTER",
        "export.concept": "Konzept",
        "export.location": "Ort",
        "export.attributes": "Geschick {edge}  |  Herz {heart}  |  St\u00e4rke {iron}  |  Schatten {shadow}  |  Verstand {wits}",
        "export.story": "DIE GESCHICHTE",
        "export.footer": "Ende \u2014 {scenes} Szenen gespielt",
        "actions.switch_user": "Spieler wechseln",
        "actions.game_loaded": "Spielstand geladen: {name}, Szene {scene}",
        "actions.save_scene": "Szene {n}",
        "actions.save_chapter": "Kap. {n}",
        "actions.save_date": "{date}",
        "actions.no_saves": "Keine Spielst\u00e4nde vorhanden.",
        "actions.autosave": "Automatisch",

        # Settings
        "settings.title": "Einstellungen",
        "settings.api_key": "API Key",
        "settings.narration_lang": "Erz\u00e4hlsprache",
        "settings.ui_lang": "Oberfl\u00e4chensprache",
        "settings.kid_mode": "Kindermodus (8\u201312)",
        "settings.kid_tooltip": "Keine explizite Gewalt, keine Erwachsenenthemen. "
                                "Konflikte und Spannung bleiben erhalten, aber altersgerecht. "
                                "Denk an: Studio Ghibli, Harry Potter, Zelda.",
        "settings.tts": "Sprachausgabe (TTS)",
        "settings.tts_tooltip": "Liest die Erz\u00e4hlung des Narrators automatisch vor. "
                                "W\u00e4hle zwischen edge-tts (Online, Microsoft-Stimmen) "
                                "und Chatterbox (Offline, KI mit Voice Cloning).",
        "settings.backend": "Backend",
        "settings.voice": "Stimme",
        "settings.speed": "Tempo",
        "settings.device": "Ger\u00e4t",
        "settings.emotion": "Emotion (\u00dcbertreibung)",
        "settings.cfg_weight": "CFG-Gewicht (Texttreue)",
        "settings.voice_sample": "Stimm-Vorlage",
        "settings.voice_hint": "WAV-Dateien in /voices/ ablegen f\u00fcr Voice Cloning",
        "settings.preview_loading": "Vorschau wird generiert...",
        "settings.preview": "Vorschau",
        "settings.preview_fail": "Vorschau fehlgeschlagen: {error}",
        "settings.no_audio": "Keine Audiodaten erhalten.",
        "settings.stt": "Spracheingabe (STT)",
        "settings.stt_tooltip": "Aktionen per Sprache eingeben statt tippen. "
                                "Nutzt faster-whisper (lokal, offline). "
                                "Ben\u00f6tigt Mikrofon-Zugriff im Browser.",
        "settings.whisper_model": "Whisper-Modell",
        "settings.dice": "W\u00fcrfel",
        "settings.save_btn": "Speichern",
        "settings.saved_confirm": "Gespeichert!",

        # TTS / STT
        "tts.generating": "Sprachausgabe wird generiert...",
        "tts.no_audio": "Sprachausgabe: Keine Audiodaten erhalten. Ist edge-tts installiert?",
        "tts.error": "Sprachausgabe fehlgeschlagen: {error}",
        "tts.preview_text": "Die Nacht senkt sich \u00fcber die alte Stadt. Fackeln flackern im Wind, und irgendwo in der Ferne heult ein Wolf.",
        "stt.recording": "Aufnahme l\u00e4uft...",
        "stt.transcribing": "Wird transkribiert...",
        "stt.no_speech": "Keine Sprache erkannt.",
        "stt.error": "STT-Fehler: {error}",
        "stt.mic_error": "Mikrofon-Fehler: {error}",
        "stt.mic_https": "Mikrofon ben\u00f6tigt HTTPS. Bitte die Seite \u00fcber https:// aufrufen.",
        "stt.unknown": "Unbekannt",

        # Character Creation
        "creation.welcome": "**Willkommen!** In welcher Welt soll deine Geschichte spielen?",
        "creation.custom_idea": "Eigene Idee...",
        "creation.custom_genre_title": "**Eigenes Genre** \u2014 Beschreib deine Welt!",
        "creation.genre_placeholder": "Dein Genre...",
        "creation.next": "Weiter",
        "creation.tone_question": "**{genre}** \u2014 Welchen Ton soll die Geschichte haben?",
        "creation.custom_tone_btn": "Eigener Ton...",
        "creation.custom_tone_title": "**Eigener Ton** \u2014 Beschreib die Stimmung!",
        "creation.tone_placeholder": "Stimmung...",
        "creation.archetype_question": "**{tone}** \u2014 Was f\u00fcr ein Charakter willst du sein?",
        "creation.name_question": "**Wie hei\u00dft dein Charakter?**",
        "creation.name_placeholder": "Name deines Charakters...",
        "creation.desc_question": "M\u00f6chtest du noch etwas \u00fcber deinen Charakter erz\u00e4hlen? "
                                  "Wer ist er/sie, woher kommt er/sie? Beziehungen, Vergangenheit, Motivation. "
                                  "*(Optional \u2014 alles was du hier schreibst gilt als feststehende Vergangenheit)*",
        "creation.desc_placeholder": "z.B. Ein alter Veteran, der nach dem Krieg seine Frau Sophie in der Heimat zur\u00fccklie\u00df...",
        "creation.almost_done": "**Fast geschafft!** Noch zwei optionale Fragen \u2014 "
                                "du kannst sie auch einfach leer lassen.",
        "creation.wishes_label": "**W\u00fcnsche:** Was soll *zuk\u00fcnftig* in der Geschichte vorkommen?",
        "creation.wishes_placeholder": "z.B. ein treuer Hund als Begleiter, politische Intrigen, magische Artefakte...",
        "creation.wishes_hint": "W\u00fcnsche sind Dinge, die NOCH NICHT existieren, aber im Laufe der Story auftauchen sollen.",
        "creation.boundaries_label": "**Grenzen:** Was darf auf keinen Fall vorkommen?",
        "creation.boundaries_placeholder": "z.B. Gewalt gegen Kinder, Spinnen, bestimmte Phobien...",
        "creation.boundaries_hint": "Grenzen werden gespeichert und beim n\u00e4chsten Mal automatisch vorausgef\u00fcllt.",
        "creation.generating": "Charakter wird erstellt...",
        "creation.adjust": "Entwurf anpassen",
        "creation.background": "Hintergrund / Beschreibung",
        "creation.genre_desc": "Genre-Beschreibung",
        "creation.tone_desc": "Ton-Beschreibung",
        "creation.regenerate": "Mit \u00c4nderungen neu generieren",
        "creation.regenerating": "Neuer Entwurf wird erstellt...",
        "creation.drafts": "**{n} Entw\u00fcrfe** \u2014 W\u00e4hle deinen Favoriten:",
        "creation.start": "Abenteuer beginnen!",
        "creation.reroll": "Neu ausw\u00fcrfeln",
        "creation.world_awakens": "Die Welt erwacht...",
        "creation.backstory_title": "Hintergrund",
        "creation.wishes_title": "W\u00fcnsche",
        "creation.boundaries_title": "Grenzen",
        "creation.genre": "Genre",
        "creation.tone": "Ton",
        "creation.archetype": "Archetyp",
        "creation.error": "Fehler: {error}",

        # Game Loop
        "game.input_placeholder": "Was tust du?",
        "game.error": "Fehler: {error}",
        "game.invalid_api_key": "Ung\u00fcltiger API Key!",
        "game.still_processing": "Einen Moment \u2014 die vorherige Eingabe wird noch verarbeitet.",
        "game.scene_marker": "Szene {n} \u2014 {location}",

        # Momentum Burn
        "momentum.question": "**Momentum einsetzen?** {cost} \u2192 0 = **{result}**",
        "momentum.yes": "Ja!",
        "momentum.no": "Nein",
        "momentum.weak_hit": "Teilerfolg",
        "momentum.strong_hit": "Voller Erfolg",
        "momentum.gathering": "Lass uns den Lauf der Dinge \u00e4ndern\u2026",

        # Game Over
        "gameover.title": "**Abenteuer zu Ende.**",
        "gameover.kid": "Jedes Ende ist ein neuer Anfang!",
        "gameover.dark": "Das Schicksal hat zugeschlagen.",
        "gameover.new_chapter": "Neues Kapitel",
        "gameover.restart": "Komplett neu",
        "gameover.chapter_msg": "Kapitel {n}...",

        # Epilogue
        "epilogue.offer_title": "Die Geschichte hat ihr Ziel erreicht",
        "epilogue.offer_text": "Du kannst weiterspielen oder das Kapitel mit einem Epilog abschlie\u00dfen.",
        "epilogue.generate": "Epilog generieren",
        "epilogue.continue": "Weiterspielen",
        "epilogue.generating": "Epilog wird geschrieben\u2026",
        "epilogue.done_title": "Kapitel abgeschlossen",
        "epilogue.done_text": "Was m\u00f6chtest du als n\u00e4chstes tun?",
        "epilogue.new_chapter": "Neues Kapitel",
        "epilogue.restart": "Komplett neu",
        "epilogue.chapter_msg": "Kapitel {n}...",
        "epilogue.marker": "Epilog",

        # Chapter Archives
        "chapters.viewing": "\U0001F4D6 Kapitel {n}",
        "chapters.viewing_title": "\U0001F4D6 Kapitel {n}: {title}",
        "chapters.back": "Zur\u00fcck zum Spiel",
        "chapters.export": "Kapitel exportieren",
        "chapters.not_found": "Kapitelarchiv nicht gefunden",
        "chapters.chapter_label": "Kapitel {n}",

        # Dice Display
        "dice.action": "**Aktion:** {d1}+{d2}+{stat_value} = **{score}** vs **{c1}|{c2}**",
        "dice.match": "\u2604\uFE0F **Schicksalswurf!** Beide Herausforderungsw\u00fcrfel zeigen {value}!",
        "dice.match_short": "\u2604\uFE0F Schicksalswurf!",
        "dice.chaos_short": "\u26A1 Chaos!",
        "dice.position": "**Position:** {position} \u2014 **Effekt:** {effect}",
        "dice.consequences": "**Konsequenzen:** {text}",

        # Help
        "help.title": "Hilfe \u2014 Spielsystem",
        "help.dice_title": "**Wie funktioniert das W\u00fcrfelsystem?**",
        "help.dice_text": "Das Spiel nutzt ein System inspiriert von *Ironsworn/Starforged*.",
        "help.probe_title": "**Probe**",
        "help.probe_text": "Wenn du etwas Riskantes tust, wird gew\u00fcrfelt:",
        "help.probe_detail": "<b>2W6 + Attribut</b> (dein Aktionswurf, max. 10)<br>"
                             "gegen <b>2W10</b> (die Herausforderung)",
        "help.results_title": "**Ergebnisse**",
        "help.result_strong": "<b>Voller Erfolg</b>",
        "help.result_strong_desc": "Aktionswurf schl\u00e4gt beide W10 \u2192 Sauberer Sieg",
        "help.result_weak": "<b>Teilerfolg</b>",
        "help.result_weak_desc": "Schl\u00e4gt einen W10 \u2192 Erfolg mit Komplikation",
        "help.result_miss": "<b>Fehlschlag</b>",
        "help.result_miss_desc": "Schl\u00e4gt keinen W10 \u2192 Etwas geht schief",
        "help.match_title": "**Schicksalswurf (Match)**",
        "help.match_text": "Wenn beide Herausforderungsw\u00fcrfel (W10) die gleiche Zahl zeigen, ist es ein "
                           "Schicksalswurf \u2014 etwas Besonderes geschieht! Bei Erfolg + Match = ein "
                           "unerwarteter Vorteil. Bei Fehlschlag + Match = dramatische Eskalation.",
        "help.position_title": "**Position & Effekt**",
        "help.pos_controlled": "<b>Kontrolliert</b>",
        "help.pos_controlled_desc": "Vorteil, mildere Konsequenzen",
        "help.pos_risky": "<b>Riskant</b>",
        "help.pos_risky_desc": "Standard, alles ist m\u00f6glich",
        "help.pos_desperate": "<b>Verzweifelt</b>",
        "help.pos_desperate_desc": "Nachteil, h\u00e4rtere Konsequenzen",
        "help.stats_title": "**Attribute** (7 Punkte, je 0\u20133)",
        "help.stat_edge": "<b>Geschick</b> \u2014 Schnelligkeit, Heimlichkeit",
        "help.stat_heart": "<b>Herz</b> \u2014 Empathie, Mut, Charme",
        "help.stat_iron": "<b>St\u00e4rke</b> \u2014 Kraft, Ausdauer",
        "help.stat_shadow": "<b>Schatten</b> \u2014 List, T\u00e4uschung",
        "help.stat_wits": "<b>Verstand</b> \u2014 Wissen, Wahrnehmung",
        "help.tracks_title": "**Leisten** (je 0\u20135)",
        "help.track_health": "<b>Gesundheit</b> \u2014 K\u00f6rperlicher Zustand",
        "help.track_spirit": "<b>Willenskraft</b> \u2014 Mentaler Zustand",
        "help.track_supply": "<b>Vorr\u00e4te</b> \u2014 Ressourcen, Ausr\u00fcstung",
        "help.momentum_title": "**Momentum** (-6 bis +10)",
        "help.momentum_text": "Baut sich bei Erfolgen auf. Bei Fehlschlag oder Teilerfolg kannst du "
                              "Momentum einsetzen \u2014 setzt es auf 0, aber verbessert das Ergebnis.",
        "help.chaos_title": "**Chaos-Faktor**",
        "help.chaos_text": "Misst die Spannung (3\u20139). Steigt bei Fehlschl\u00e4gen, sinkt bei Erfolgen. "
                           "Hohes Chaos kann unerwartete Szenenunterbrechungen ausl\u00f6sen.",
        "help.clocks_title": "**Uhren**",
        "help.clocks_text": "Bedrohungen ticken im Hintergrund. Fehlschl\u00e4ge f\u00fcllen Bedrohungsuhren. "
                            "Volle Uhr = etwas Schlimmes passiert.",
        "help.crisis_title": "**Krise**",
        "help.crisis_text": "Gesundheit ODER Willenskraft auf 0 = Krisenmodus. "
                            "Beides auf 0 = dramatisches Finale.",
        "help.freedom_title": "**Spielerfreiheit**",
        "help.freedom_text": "Du kannst alles tun. Sag einfach, was du tust \u2014 die Welt reagiert. "
                             "Du kannst auch neue Elemente in die Welt einf\u00fchren.",
        "help.kid_title": "**Kindermodus**",
        "help.kid_text": "Kinderfreundliche Inhalte (8\u201312 Jahre). Keine Gewalt, keine Erwachsenenthemen, "
                         "hoffnungsvoller Ton. Spannung bleibt erhalten!",
    },

    # ── ENGLISH ──────────────────────────────────────────────
    "en": {
        # Connection / Loading
        "conn.loading": "Connecting...",

        # Login
        "login.title": "EdgeTales",
        "login.subtitle": "Access by invitation only.",
        "login.code_label": "Invitation Code",
        "login.error": "Wrong code.",
        "login.rate_limited": "Too many attempts. Please wait 5 minutes.",
        "login.submit": "Enter",

        # User Selection
        "user.title": "EdgeTales",
        "user.subtitle": "A Narrative Solo\u2011RPG Engine",
        "user.who_plays": "Who's playing?",
        "user.new_player": "New Player",
        "user.name": "Name",
        "user.name_placeholder": "Your name...",
        "user.create": "Create Player",
        "user.manage": "Manage Players",
        "user.remove_label": "Remove Player",
        "user.confirm_delete": 'Really delete "{name}"?',
        "user.yes": "Yes",
        "user.no": "No",
        "user.exists": 'Player "{name}" already exists.',
        "user.api_hint": "Set your API key in the settings after selecting a player.",
        "user.api_missing": "Please enter your API key in the settings.",

        # Sidebar — Status
        "sidebar.kid_mode": "Kid Mode",
        "sidebar.crisis": "CRISIS",
        "sidebar.crisis_kid": "IN TROUBLE",
        "sidebar.finale": "FINALE",
        "sidebar.story_complete": "STORY COMPLETE",
        "sidebar.scene": "Scene",
        "sidebar.momentum": "Momentum",
        "sidebar.health": "Health",
        "sidebar.spirit": "Spirit",
        "sidebar.supply": "Supply",
        "sidebar.chaos": "Chaos",
        "sidebar.clocks": "Clocks",
        "sidebar.persons": "Characters",
        "sidebar.known_persons": "Known",
        "sidebar.npc_aka": "aka",
        "sidebar.chapter": "Ch.",
        "sidebar.3act": "3-Act",
        "sidebar.act": "Act",

        # Story Arc Phase Labels
        "story.setup": "Setup",
        "story.confrontation": "Confrontation",
        "story.climax": "Climax",
        "story.ki_introduction": "Ki",
        "story.sho_development": "Sh\u014d",
        "story.ten_twist": "Ten",
        "story.ketsu_resolution": "Ketsu",

        # Sidebar — Actions
        "actions.recap": "Story so far...",
        "actions.recap_prefix": "Story so far...",
        "actions.recap_loading": "Narrator is remembering...",
        "actions.saves": "Save Games",
        "actions.save_name": "Name",
        "actions.save": "Save",
        "actions.save_as": "Save As...",
        "actions.save_as_placeholder": "New save name...",
        "actions.save_as_btn": "Create New Save",
        "actions.saved": "Saved!",
        "actions.active_save": "Active: {name}",
        "actions.quick_save": "Quick Save",
        "actions.load": "Load",
        "actions.load_label": "Load",
        "actions.load_confirm": "Discard current progress and load \u00ab{name}\u00bb?",
        "actions.delete": "Delete",
        "actions.delete_confirm": "Really delete save \u00ab{name}\u00bb?",
        "actions.deleted": "Deleted!",
        "actions.new_game": "New Game",
        "actions.new_game_confirm": "End current game and start fresh?",
        "actions.export": "Export",
        # Export story
        "export.subtitle": "A Story",
        "export.exported_at": "Exported on {timestamp}",
        "export.character": "CHARACTER",
        "export.concept": "Concept",
        "export.location": "Location",
        "export.attributes": "Finesse {edge}  |  Heart {heart}  |  Iron {iron}  |  Shadow {shadow}  |  Wits {wits}",
        "export.story": "THE STORY",
        "export.footer": "End \u2014 {scenes} scenes played",
        "actions.switch_user": "Switch Player",
        "actions.game_loaded": "Game loaded: {name}, Scene {scene}",
        "actions.save_scene": "Scene {n}",
        "actions.save_chapter": "Ch. {n}",
        "actions.save_date": "{date}",
        "actions.no_saves": "No save games found.",
        "actions.autosave": "Autosave",

        # Settings
        "settings.title": "Settings",
        "settings.api_key": "API Key",
        "settings.narration_lang": "Narration Language",
        "settings.ui_lang": "Interface Language",
        "settings.kid_mode": "Kid Mode (ages 8\u201312)",
        "settings.kid_tooltip": "No explicit violence, no adult themes. "
                                "Conflict and tension remain, but age-appropriate. "
                                "Think: Studio Ghibli, Harry Potter, Zelda.",
        "settings.tts": "Text-to-Speech (TTS)",
        "settings.tts_tooltip": "Reads the narrator's text aloud automatically. "
                                "Choose between edge-tts (online, Microsoft voices) "
                                "and Chatterbox (offline, AI with voice cloning).",
        "settings.backend": "Backend",
        "settings.voice": "Voice",
        "settings.speed": "Speed",
        "settings.device": "Device",
        "settings.emotion": "Emotion (Exaggeration)",
        "settings.cfg_weight": "CFG Weight (Text Fidelity)",
        "settings.voice_sample": "Voice Sample",
        "settings.voice_hint": "Place WAV files in /voices/ for voice cloning",
        "settings.preview_loading": "Generating preview...",
        "settings.preview": "Preview",
        "settings.preview_fail": "Preview failed: {error}",
        "settings.no_audio": "No audio data received.",
        "settings.stt": "Speech-to-Text (STT)",
        "settings.stt_tooltip": "Speak your actions instead of typing. "
                                "Uses faster-whisper (local, offline). "
                                "Requires microphone access in the browser.",
        "settings.whisper_model": "Whisper Model",
        "settings.dice": "Dice",
        "settings.save_btn": "Save",
        "settings.saved_confirm": "Saved!",

        # TTS / STT
        "tts.generating": "Generating speech...",
        "tts.no_audio": "TTS: No audio data received. Is edge-tts installed?",
        "tts.error": "TTS failed: {error}",
        "tts.preview_text": "Night falls over the ancient city. Torches flicker in the wind, "
                            "and somewhere in the distance, a wolf howls.",
        "stt.recording": "Recording...",
        "stt.transcribing": "Transcribing...",
        "stt.no_speech": "No speech detected.",
        "stt.error": "STT error: {error}",
        "stt.mic_error": "Microphone error: {error}",
        "stt.mic_https": "Microphone requires HTTPS. Please access the page via https://.",
        "stt.unknown": "Unknown",

        # Character Creation
        "creation.welcome": "**Welcome!** What world shall your story take place in?",
        "creation.custom_idea": "Custom Idea...",
        "creation.custom_genre_title": "**Custom Genre** \u2014 Describe your world!",
        "creation.genre_placeholder": "Your genre...",
        "creation.next": "Next",
        "creation.tone_question": "**{genre}** \u2014 What tone should the story have?",
        "creation.custom_tone_btn": "Custom Tone...",
        "creation.custom_tone_title": "**Custom Tone** \u2014 Describe the mood!",
        "creation.tone_placeholder": "Mood...",
        "creation.archetype_question": "**{tone}** \u2014 What kind of character do you want to be?",
        "creation.name_question": "**What is your character's name?**",
        "creation.name_placeholder": "Your character's name...",
        "creation.desc_question": "Want to tell us more about your character? "
                                  "Who are they, where do they come from? Relationships, past, motivation. "
                                  "*(Optional \u2014 everything you write here is treated as established history)*",
        "creation.desc_placeholder": "e.g. A grizzled veteran who left his wife Sophie behind after the war...",
        "creation.almost_done": "**Almost done!** Two more optional questions \u2014 "
                                "feel free to leave them blank.",
        "creation.wishes_label": "**Wishes:** What should appear *in the future* of your story?",
        "creation.wishes_placeholder": "e.g. a loyal dog companion, political intrigue, magical artifacts...",
        "creation.wishes_hint": "Wishes are things that DON'T EXIST YET but should appear over the course of the story.",
        "creation.boundaries_label": "**Boundaries:** What must absolutely not appear?",
        "creation.boundaries_placeholder": "e.g. violence against children, spiders, specific phobias...",
        "creation.boundaries_hint": "Boundaries are saved and pre-filled automatically next time.",
        "creation.generating": "Creating character...",
        "creation.adjust": "Adjust Draft",
        "creation.background": "Background / Description",
        "creation.genre_desc": "Genre Description",
        "creation.tone_desc": "Tone Description",
        "creation.regenerate": "Regenerate with Changes",
        "creation.regenerating": "Creating new draft...",
        "creation.drafts": "**{n} Drafts** \u2014 Pick your favorite:",
        "creation.start": "Begin Adventure!",
        "creation.reroll": "Reroll",
        "creation.world_awakens": "The world awakens...",
        "creation.backstory_title": "Backstory",
        "creation.wishes_title": "Wishes",
        "creation.boundaries_title": "Boundaries",
        "creation.genre": "Genre",
        "creation.tone": "Tone",
        "creation.archetype": "Archetype",
        "creation.error": "Error: {error}",

        # Game Loop
        "game.input_placeholder": "What do you do?",
        "game.error": "Error: {error}",
        "game.invalid_api_key": "Invalid API Key!",
        "game.still_processing": "One moment \u2014 still processing your previous input.",
        "game.scene_marker": "Scene {n} \u2014 {location}",

        # Momentum Burn
        "momentum.question": "**Burn Momentum?** {cost} \u2192 0 = **{result}**",
        "momentum.yes": "Yes!",
        "momentum.no": "No",
        "momentum.weak_hit": "Weak Hit",
        "momentum.strong_hit": "Strong Hit",
        "momentum.gathering": "Let us change the course of fate\u2026",

        # Game Over
        "gameover.title": "**Adventure Over.**",
        "gameover.kid": "Every ending is a new beginning!",
        "gameover.dark": "Fate has struck.",
        "gameover.new_chapter": "New Chapter",
        "gameover.restart": "Start Over",
        "gameover.chapter_msg": "Chapter {n}...",

        # Epilogue
        "epilogue.offer_title": "The story has reached its conclusion",
        "epilogue.offer_text": "You can keep playing or wrap up this chapter with an epilogue.",
        "epilogue.generate": "Generate Epilogue",
        "epilogue.continue": "Keep Playing",
        "epilogue.generating": "Writing epilogue\u2026",
        "epilogue.done_title": "Chapter Complete",
        "epilogue.done_text": "What would you like to do next?",
        "epilogue.new_chapter": "New Chapter",
        "epilogue.restart": "Start Over",
        "epilogue.chapter_msg": "Chapter {n}...",
        "epilogue.marker": "Epilogue",

        # Chapter Archives
        "chapters.viewing": "\U0001F4D6 Chapter {n}",
        "chapters.viewing_title": "\U0001F4D6 Chapter {n}: {title}",
        "chapters.back": "Back to game",
        "chapters.export": "Export chapter",
        "chapters.not_found": "Chapter archive not found",
        "chapters.chapter_label": "Chapter {n}",

        # Dice Display
        "dice.action": "**Action:** {d1}+{d2}+{stat_value} = **{score}** vs **{c1}|{c2}**",
        "dice.match": "\u2604\uFE0F **Fateful Roll!** Both challenge dice show {value}!",
        "dice.match_short": "\u2604\uFE0F Fateful Roll!",
        "dice.chaos_short": "\u26A1 Chaos!",
        "dice.position": "**Position:** {position} \u2014 **Effect:** {effect}",
        "dice.consequences": "**Consequences:** {text}",

        # Help
        "help.title": "Help \u2014 Game System",
        "help.dice_title": "**How does the dice system work?**",
        "help.dice_text": "The game uses a system inspired by *Ironsworn/Starforged*.",
        "help.probe_title": "**Roll**",
        "help.probe_text": "When you attempt something risky, dice are rolled:",
        "help.probe_detail": "<b>2d6 + Attribute</b> (your action roll, max 10)<br>"
                             "vs <b>2d10</b> (the challenge)",
        "help.results_title": "**Results**",
        "help.result_strong": "<b>Strong Hit</b>",
        "help.result_strong_desc": "Action roll beats both d10 \u2192 Clean success",
        "help.result_weak": "<b>Weak Hit</b>",
        "help.result_weak_desc": "Beats one d10 \u2192 Success with complication",
        "help.result_miss": "<b>Miss</b>",
        "help.result_miss_desc": "Beats neither d10 \u2192 Something goes wrong",
        "help.match_title": "**Fateful Roll (Match)**",
        "help.match_text": "When both challenge dice (d10) show the same number, it's a fateful roll "
                           "\u2014 something special happens! On a hit + match = an unexpected advantage. "
                           "On a miss + match = dramatic escalation.",
        "help.position_title": "**Position & Effect**",
        "help.pos_controlled": "<b>Controlled</b>",
        "help.pos_controlled_desc": "Advantage, milder consequences",
        "help.pos_risky": "<b>Risky</b>",
        "help.pos_risky_desc": "Standard, anything can happen",
        "help.pos_desperate": "<b>Desperate</b>",
        "help.pos_desperate_desc": "Disadvantage, harsher consequences",
        "help.stats_title": "**Attributes** (7 points, 0\u20133 each)",
        "help.stat_edge": "<b>Finesse</b> \u2014 Speed, stealth",
        "help.stat_heart": "<b>Heart</b> \u2014 Empathy, courage, charm",
        "help.stat_iron": "<b>Iron</b> \u2014 Strength, endurance",
        "help.stat_shadow": "<b>Shadow</b> \u2014 Cunning, deception",
        "help.stat_wits": "<b>Wits</b> \u2014 Knowledge, perception",
        "help.tracks_title": "**Tracks** (0\u20135 each)",
        "help.track_health": "<b>Health</b> \u2014 Physical condition",
        "help.track_spirit": "<b>Spirit</b> \u2014 Mental condition",
        "help.track_supply": "<b>Supply</b> \u2014 Resources, equipment",
        "help.momentum_title": "**Momentum** (-6 to +10)",
        "help.momentum_text": "Builds on successes. On a miss or weak hit, you can burn momentum "
                              "\u2014 resets to 0, but upgrades the result.",
        "help.chaos_title": "**Chaos Factor**",
        "help.chaos_text": "Measures tension (3\u20139). Rises on misses, falls on successes. "
                           "High chaos can trigger unexpected scene interrupts.",
        "help.clocks_title": "**Clocks**",
        "help.clocks_text": "Threats tick in the background. Misses fill threat clocks. "
                            "Full clock = something bad happens.",
        "help.crisis_title": "**Crisis**",
        "help.crisis_text": "Health OR Spirit at 0 = Crisis mode. "
                            "Both at 0 = dramatic finale.",
        "help.freedom_title": "**Player Freedom**",
        "help.freedom_text": "You can do anything. Just say what you do \u2014 the world responds. "
                             "You can also introduce new elements into the world.",
        "help.kid_title": "**Kid Mode**",
        "help.kid_text": "Kid-friendly content (ages 8\u201312). No violence, no adult themes, "
                         "hopeful tone. Tension is preserved!",
    },
}


# ===============================================================
# STRING LOOKUP
# ===============================================================

def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Look up a translated string. Falls back to German if key missing in target language."""
    text = _STRINGS.get(lang, {}).get(key)
    if text is None:
        text = _STRINGS.get(FALLBACK_LANG, {}).get(key, f"[{key}]")
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


# ===============================================================
# LABEL DICTS — language-dependent display labels
# ===============================================================

_STAT_LABELS = {
    "de": {"edge": "Geschick", "heart": "Herz", "iron": "St\u00e4rke",
           "shadow": "Schatten", "wits": "Verstand"},
    "en": {"edge": "Finesse", "heart": "Heart", "iron": "Iron",
           "shadow": "Shadow", "wits": "Wits"},
}

_DISPOSITION_LABELS = {
    "de": {
        "hostile": f"{E['red_circle']} Feindlich",
        "distrustful": f"{E['orange_circle']} Misstrauisch",
        "neutral": f"{E['white_circle']} Neutral",
        "friendly": f"{E['green_circle']} Freundlich",
        "loyal": f"{E['green_heart']} Loyal",
    },
    "en": {
        "hostile": f"{E['red_circle']} Hostile",
        "distrustful": f"{E['orange_circle']} Distrustful",
        "neutral": f"{E['white_circle']} Neutral",
        "friendly": f"{E['green_circle']} Friendly",
        "loyal": f"{E['green_heart']} Loyal",
    },
}

_MOVE_LABELS = {
    "de": {
        "face_danger": "Gefahr trotzen",
        "compel": "\u00dcberzeugen",
        "gather_information": "Informationen sammeln",
        "secure_advantage": "Vorteil sichern",
        "clash": "Kampf",
        "strike": "Angriff",
        "endure_harm": "Schmerz ertragen",
        "endure_stress": "Stress ertragen",
        "make_connection": "Kontakt kn\u00fcpfen",
        "test_bond": "Bindung pr\u00fcfen",
        "resupply": "Versorgen",
        "world_shaping": "Welt formen",
    },
    "en": {
        "face_danger": "Face Danger",
        "compel": "Compel",
        "gather_information": "Gather Information",
        "secure_advantage": "Secure Advantage",
        "clash": "Clash",
        "strike": "Strike",
        "endure_harm": "Endure Harm",
        "endure_stress": "Endure Stress",
        "make_connection": "Make Connection",
        "test_bond": "Test Bond",
        "resupply": "Resupply",
        "world_shaping": "World Shaping",
    },
}

_RESULT_LABELS = {
    "de": {
        "STRONG_HIT": (f"{E['check']} Voller Erfolg", "success"),
        "WEAK_HIT": (f"{E['warn']} Teilerfolg", "warning"),
        "MISS": (f"{E['x_mark']} Fehlschlag", "error"),
    },
    "en": {
        "STRONG_HIT": (f"{E['check']} Strong Hit", "success"),
        "WEAK_HIT": (f"{E['warn']} Weak Hit", "warning"),
        "MISS": (f"{E['x_mark']} Miss", "error"),
    },
}

_POSITION_LABELS = {
    "de": {
        "controlled": f"{E['green_circle']} Kontrolliert",
        "risky": f"{E['orange_circle']} Riskant",
        "desperate": f"{E['red_circle']} Verzweifelt",
    },
    "en": {
        "controlled": f"{E['green_circle']} Controlled",
        "risky": f"{E['orange_circle']} Risky",
        "desperate": f"{E['red_circle']} Desperate",
    },
}

_EFFECT_LABELS = {
    "de": {"limited": "Begrenzt", "standard": "Standard", "great": "Gro\u00df"},
    "en": {"limited": "Limited", "standard": "Standard", "great": "Great"},
}

_TIME_LABELS = {
    "de": {
        "early_morning": "Fr\u00fcher Morgen", "morning": "Morgen", "midday": "Mittag",
        "afternoon": "Nachmittag", "evening": "Abend", "late_evening": "Sp\u00e4ter Abend",
        "night": "Nacht", "deep_night": "Tiefe Nacht",
    },
    "en": {
        "early_morning": "Early Morning", "morning": "Morning", "midday": "Midday",
        "afternoon": "Afternoon", "evening": "Evening", "late_evening": "Late Evening",
        "night": "Night", "deep_night": "Deep Night",
    },
}

_DICE_DISPLAY_OPTIONS = {
    "de": [
        f"{E['x_mark']} Aus",
        f"{E['dice']} Einfach",
        f"{E['search']} Detailliert",
    ],
    "en": [
        f"{E['x_mark']} Off",
        f"{E['dice']} Simple",
        f"{E['search']} Detailed",
    ],
}

_NO_VOICE_SAMPLE_LABEL = {
    "de": "\u2014 Keine (Standard-Stimme) \u2014",
    "en": "\u2014 None (Default Voice) \u2014",
}

_WHISPER_MODELS = {
    "de": {
        "tiny": "Schnell (~1GB)", "base": "Balance (~1GB)",
        "small": "Genau (~2GB)", "medium": "Sehr genau (~5GB)",
        "large-v3": "Beste (~10GB, GPU)",
    },
    "en": {
        "tiny": "Fast (~1GB)", "base": "Balanced (~1GB)",
        "small": "Accurate (~2GB)", "medium": "Very accurate (~5GB)",
        "large-v3": "Best (~10GB, GPU)",
    },
}

_VOICE_OPTIONS = {
    "de": {
        "Conrad (M\u00e4nnlich, tief)": "de-DE-ConradNeural",
        "Killian (M\u00e4nnlich, klar)": "de-DE-KillianNeural",
        "Florian (M\u00e4nnlich, multilingual)": "de-DE-FlorianMultilingualNeural",
        "Katja (Weiblich, neutral)": "de-DE-KatjaNeural",
        "Amala (Weiblich, warm)": "de-DE-AmalaNeural",
        "Seraphina (Weiblich, multilingual)": "de-DE-SeraphinaMultilingualNeural",
        "Jonas (\u00D6sterreich, m\u00e4nnlich)": "de-AT-JonasNeural",
        "Ingrid (\u00D6sterreich, weiblich)": "de-AT-IngridNeural",
        "Jan (Schweiz, m\u00e4nnlich)": "de-CH-JanNeural",
        "Leni (Schweiz, weiblich)": "de-CH-LeniNeural",
    },
    "en": {
        "Conrad (Male, deep)": "de-DE-ConradNeural",
        "Killian (Male, clear)": "de-DE-KillianNeural",
        "Florian (Male, multilingual)": "de-DE-FlorianMultilingualNeural",
        "Katja (Female, neutral)": "de-DE-KatjaNeural",
        "Amala (Female, warm)": "de-DE-AmalaNeural",
        "Seraphina (Female, multilingual)": "de-DE-SeraphinaMultilingualNeural",
        "Jonas (Austria, male)": "de-AT-JonasNeural",
        "Ingrid (Austria, female)": "de-AT-IngridNeural",
        "Jan (Switzerland, male)": "de-CH-JanNeural",
        "Leni (Switzerland, female)": "de-CH-LeniNeural",
    },
}

_TTS_BACKENDS = {
    "de": {
        f"{E['globe']} edge-tts (Online)": "edge_tts",
        f"{E['brain']} Chatterbox (Offline/KI)": "chatterbox",
    },
    "en": {
        f"{E['globe']} edge-tts (Online)": "edge_tts",
        f"{E['brain']} Chatterbox (Offline/AI)": "chatterbox",
    },
}


# ── Label getters ──

def get_stat_labels(lang: str = DEFAULT_LANG) -> dict:
    return _STAT_LABELS.get(lang, _STAT_LABELS[FALLBACK_LANG])

def get_disposition_labels(lang: str = DEFAULT_LANG) -> dict:
    return _DISPOSITION_LABELS.get(lang, _DISPOSITION_LABELS[FALLBACK_LANG])

def get_move_labels(lang: str = DEFAULT_LANG) -> dict:
    return _MOVE_LABELS.get(lang, _MOVE_LABELS[FALLBACK_LANG])

def get_result_labels(lang: str = DEFAULT_LANG) -> dict:
    return _RESULT_LABELS.get(lang, _RESULT_LABELS[FALLBACK_LANG])

def get_position_labels(lang: str = DEFAULT_LANG) -> dict:
    return _POSITION_LABELS.get(lang, _POSITION_LABELS[FALLBACK_LANG])

def get_effect_labels(lang: str = DEFAULT_LANG) -> dict:
    return _EFFECT_LABELS.get(lang, _EFFECT_LABELS[FALLBACK_LANG])

def get_time_labels(lang: str = DEFAULT_LANG) -> dict:
    return _TIME_LABELS.get(lang, _TIME_LABELS[FALLBACK_LANG])

def get_dice_display_options(lang: str = DEFAULT_LANG) -> list:
    return _DICE_DISPLAY_OPTIONS.get(lang, _DICE_DISPLAY_OPTIONS[FALLBACK_LANG])

def get_no_voice_sample_label(lang: str = DEFAULT_LANG) -> str:
    return _NO_VOICE_SAMPLE_LABEL.get(lang, _NO_VOICE_SAMPLE_LABEL[FALLBACK_LANG])

def get_whisper_models(lang: str = DEFAULT_LANG) -> dict:
    return _WHISPER_MODELS.get(lang, _WHISPER_MODELS[FALLBACK_LANG])

def get_voice_options(lang: str = DEFAULT_LANG) -> dict:
    """Return {display_label: voice_id} for the given UI language."""
    return _VOICE_OPTIONS.get(lang, _VOICE_OPTIONS[FALLBACK_LANG])

def get_tts_backends(lang: str = DEFAULT_LANG) -> dict:
    """Return {display_label: backend_code} for the given UI language."""
    return _TTS_BACKENDS.get(lang, _TTS_BACKENDS[FALLBACK_LANG])

def resolve_voice_id(label: str) -> str:
    """Resolve a voice display label (any language) OR voice ID to its voice ID.
    Accepts both localized labels ('Conrad (Männlich, tief)') and raw IDs
    ('de-DE-ConradNeural') for backward compat with label-based and
    forward compat with code-based persistence."""
    # 1. Check if it's a display label (any language)
    for lang_opts in _VOICE_OPTIONS.values():
        if label in lang_opts:
            return lang_opts[label]
    # 2. Check if it's already a valid voice ID
    _all_ids = {vid for lang_opts in _VOICE_OPTIONS.values() for vid in lang_opts.values()}
    if label in _all_ids:
        return label
    return "de-DE-ConradNeural"

def resolve_tts_backend(label: str) -> str:
    """Resolve a TTS backend display label (any language) OR backend code to its code.
    Accepts both localized labels and raw codes ('edge_tts', 'chatterbox')."""
    # 1. Check if it's a display label (any language)
    for lang_opts in _TTS_BACKENDS.values():
        if label in lang_opts:
            return lang_opts[label]
    # 2. Check if it's already a valid backend code
    _all_codes = {c for lang_opts in _TTS_BACKENDS.values() for c in lang_opts.values()}
    if label in _all_codes:
        return label
    return "edge_tts"

def find_voice_label(voice_id: str, lang: str = DEFAULT_LANG) -> str:
    """Find the display label for a voice ID in the given language."""
    opts = get_voice_options(lang)
    for label, vid in opts.items():
        if vid == voice_id:
            return label
    return list(opts.keys())[0]

def find_tts_backend_label(code: str, lang: str = DEFAULT_LANG) -> str:
    """Find the display label for a backend code in the given language."""
    opts = get_tts_backends(lang)
    for label, c in opts.items():
        if c == code:
            return label
    return list(opts.keys())[0]


# ===============================================================
# DISPLAY OPTION DICTS — GENRES, TONES, ARCHETYPES
# Code-keyed internally, return {display_label: code} for UI
# ===============================================================

_GENRES = {
    "de": {
        "dark_fantasy": f"{E['castle']} Dark Fantasy",
        "high_fantasy": f"{E['scroll']} High Fantasy",
        "science_fiction": f"{E['rocket']} Sci-Fi",
        "horror_mystery": f"{E['crystal']} Horror / Mystery",
        "steampunk": f"{E['gear']} Steampunk",
        "cyberpunk": f"{E['city']} Cyberpunk",
        "urban_fantasy": f"{E['globe']} Urban Fantasy",
        "victorian_crime": f"{E['swords']} Viktorianischer Krimi",
        "historical_roman": f"{E['shield']} Historisch / R\u00f6misch",
        "fairy_tale": f"{E['green_heart']} Kinderm\u00e4rchenwelt",
        "slice_of_life_90s": f"{E['mic']} Slice of Life 1990er",
        "surprise": f"{E['dice']} \u00dcberrasch mich",
    },
    "en": {
        "dark_fantasy": f"{E['castle']} Dark Fantasy",
        "high_fantasy": f"{E['scroll']} High Fantasy",
        "science_fiction": f"{E['rocket']} Sci-Fi",
        "horror_mystery": f"{E['crystal']} Horror / Mystery",
        "steampunk": f"{E['gear']} Steampunk",
        "cyberpunk": f"{E['city']} Cyberpunk",
        "urban_fantasy": f"{E['globe']} Urban Fantasy",
        "victorian_crime": f"{E['swords']} Victorian Crime",
        "historical_roman": f"{E['shield']} Historical / Roman",
        "fairy_tale": f"{E['green_heart']} Fairy Tale World",
        "slice_of_life_90s": f"{E['mic']} Slice of Life 1990s",
        "surprise": f"{E['dice']} Surprise Me",
    },
}

_TONES = {
    "de": {
        "dark_gritty": f"{E['black_heart']} D\u00fcster & Gnadenlos",
        "serious_balanced": f"{E['scales']} Ernst, aber fair",
        "melancholic": f"{E['moon_half']} Melancholisch",
        "absurd_grotesque": f"{E['skull']} Absurd & Grotesk",
        "slow_burn_horror": f"{E['candle']} Langsamer Grusel",
        "cheerful_funny": f"{E['yellow_heart']} Fr\u00f6hlich & Lustig",
        "romantic": f"{E['heart_red']} Romantisch",
        "slapstick": f"{E['mask']} Slapstick",
        "epic_heroic": f"{E['lightning']} Episch & Heroisch",
        "tarantino": f"{E['fire']} Tarantino-Style",
        "cozy": f"{E['green_heart']} Cozy & Gem\u00fctlich",
        "tragicomic": f"{E['brain']} Tragikomisch",
    },
    "en": {
        "dark_gritty": f"{E['black_heart']} Dark & Gritty",
        "serious_balanced": f"{E['scales']} Serious but Fair",
        "melancholic": f"{E['moon_half']} Melancholic",
        "absurd_grotesque": f"{E['skull']} Absurd & Grotesque",
        "slow_burn_horror": f"{E['candle']} Slow-Burn Horror",
        "cheerful_funny": f"{E['yellow_heart']} Cheerful & Fun",
        "romantic": f"{E['heart_red']} Romantic",
        "slapstick": f"{E['mask']} Slapstick",
        "epic_heroic": f"{E['lightning']} Epic & Heroic",
        "tarantino": f"{E['fire']} Tarantino-Style",
        "cozy": f"{E['green_heart']} Cozy & Comfy",
        "tragicomic": f"{E['brain']} Tragicomic",
    },
}

_ARCHETYPES = {
    "de": {
        "outsider_loner": f"{E['dagger']} Einzelg\u00e4nger / Eremit",
        "investigator": f"{E['search']} Ermittler / Neugieriger",
        "trickster": f"{E['speech']} Betr\u00fcger / Charmeur",
        "protector": f"{E['shield']} Besch\u00fctzer / Krieger",
        "hardboiled": f"{E['fire']} Harter Hund / Veteran",
        "scholar": f"{E['books']} Gelehrter / Mystiker",
        "healer": f"{E['heart_red']} Heiler / Medikus",
        "inventor": f"{E['gear']} Handwerker / Erfinder",
        "artist": f"{E['microphone']} K\u00fcnstler / Barde",
    },
    "en": {
        "outsider_loner": f"{E['dagger']} Outsider / Loner",
        "investigator": f"{E['search']} Investigator / Curious",
        "trickster": f"{E['speech']} Trickster / Charmer",
        "protector": f"{E['shield']} Protector / Warrior",
        "hardboiled": f"{E['fire']} Hardboiled / Veteran",
        "scholar": f"{E['books']} Scholar / Mystic",
        "healer": f"{E['heart_red']} Healer / Medic",
        "inventor": f"{E['gear']} Crafter / Inventor",
        "artist": f"{E['microphone']} Artist / Bard",
    },
}


def get_genres(lang: str = DEFAULT_LANG) -> dict:
    """Returns {display_label: internal_code} dict for UI buttons."""
    code_to_label = _GENRES.get(lang, _GENRES[FALLBACK_LANG])
    return {label: code for code, label in code_to_label.items()}


def get_tones(lang: str = DEFAULT_LANG) -> dict:
    """Returns {display_label: internal_code} dict for UI buttons."""
    code_to_label = _TONES.get(lang, _TONES[FALLBACK_LANG])
    return {label: code for code, label in code_to_label.items()}


def get_archetypes(lang: str = DEFAULT_LANG) -> dict:
    """Returns {display_label: internal_code} dict for UI buttons."""
    code_to_label = _ARCHETYPES.get(lang, _ARCHETYPES[FALLBACK_LANG])
    return {label: code for code, label in code_to_label.items()}


def get_genre_label(code: str, lang: str = DEFAULT_LANG) -> str:
    """Get display label for a genre code."""
    return _GENRES.get(lang, _GENRES[FALLBACK_LANG]).get(code, code)


def get_tone_label(code: str, lang: str = DEFAULT_LANG) -> str:
    """Get display label for a tone code."""
    return _TONES.get(lang, _TONES[FALLBACK_LANG]).get(code, code)


def get_archetype_label(code: str, lang: str = DEFAULT_LANG) -> str:
    """Get display label for an archetype code."""
    return _ARCHETYPES.get(lang, _ARCHETYPES[FALLBACK_LANG]).get(code, code)


# ===============================================================
# STORY ARC PHASE LABEL MAPPING
# ===============================================================

def get_story_phase_labels(lang: str = DEFAULT_LANG) -> dict:
    """Returns {phase_key: display_label} for story arc phases."""
    return {
        "setup": t("story.setup", lang),
        "confrontation": t("story.confrontation", lang),
        "climax": t("story.climax", lang),
        "ki_introduction": t("story.ki_introduction", lang),
        "sho_development": t("story.sho_development", lang),
        "ten_twist": t("story.ten_twist", lang),
        "ketsu_resolution": t("story.ketsu_resolution", lang),
    }


# ===============================================================
# CONSEQUENCE TRANSLATION (backward-compatible with saved games)
# ===============================================================

_CONSEQUENCE_TERMS = {
    "de": {
        # Neutral keys → German
        "health": "Gesundheit",
        "spirit": "Willenskraft",
        "supply": "Vorr\u00e4te",
        "momentum": "Momentum",
        "bond": "Bindung",
    },
    "en": {
        # Neutral keys → English
        "health": "Health",
        "spirit": "Spirit",
        "supply": "Supply",
        "momentum": "Momentum",
        "bond": "Bond",
        # Old German keys → English (backward compat for saved games)
        "Gesundheit": "Health",
        "Willenskraft": "Spirit",
        "Vorr\u00e4te": "Supply",
        "Bindung": "Bond",
    },
}


def translate_consequence(text: str, lang: str = DEFAULT_LANG) -> str:
    """Translate a consequence string from neutral keys (or legacy German) to target language.
    Backward-compatible: old German consequences in saved games display correctly in any language.
    Uses word boundaries to prevent substring collisions (e.g. NPC named 'Bond')."""
    import re
    terms = _CONSEQUENCE_TERMS.get(lang, {})
    if not terms:
        return text
    result = text
    for key, translated in terms.items():
        result = re.sub(rf'\b{re.escape(key)}\b', translated, result)
    return result
