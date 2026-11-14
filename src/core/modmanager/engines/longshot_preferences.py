"""Longshot runtime preferences: no native compilation is needed."""
from pathlib import Path
import os
import re
from ..storage import no_links

LANGUAGES = {"Français (France)": "fr", "Français (Canada)": "fr-CA", "English (US)": "en-US",
             "English (UK)": "en-GB", "Deutsch": "de", "Italiano": "it", "Español": "es",
             "Español (Latinoamérica)": "es-419", "Português (Brasil)": "pt-BR", "Nederlands": "nl",
             "Polski": "pl", "Русский": "ru", "日本語": "ja", "한국어": "ko", "简体中文": "zh-Hans", "繁體中文": "zh-Hant"}
PROMPTS = {"Automatique": 0, "Nintendo Switch": 1, "Xbox": 2, "PlayStation 4": 3,
           "DualSense / PlayStation 5": 4, "Steam Deck": 5, "Clavier": 6}
FACES = {2: "xbox", 3: "ps4", 4: "ps5", 5: "steamdeck", 6: "keyboard"}


def canonical_language(value):
    value = LANGUAGES.get(value, value).strip()
    if value.lower() == "fr-fr":
        value = "fr"
    for code in LANGUAGES.values():
        if code.casefold() == value.casefold():
            return code
    raise ValueError("Langue Longshot inconnue : " + value)


def desired_files(game, language, button_prompts):
    game = Path(game)
    language = canonical_language(language)
    if button_prompts not in PROMPTS.values():
        raise ValueError("Type d'icônes de manette inconnu")
    language_path = game / "language.txt"
    options_path = game / "longshot_options.ini"
    for path in (game, language_path, options_path):
        no_links(path)
    text = options_path.read_text(encoding="utf-8") if options_path.is_file() else ""
    line = "button_prompts=%d" % button_prompts
    if re.search(r"(?m)^button_prompts\s*=.*$", text):
        text = re.sub(r"(?m)^button_prompts\s*=.*$", line, text)
    else:
        text = text.rstrip("\r\n") + ("\n" if text else "") + line + "\n"
    # Keep the available-language comments written by Longshot.
    old_language = language_path.read_text(encoding="utf-8") if language_path.is_file() else ""
    lines = old_language.splitlines()
    code_lines = [i for i, item in enumerate(lines) if item.strip() and not item.lstrip().startswith("#")]
    if code_lines:
        lines[code_lines[0]] = language
        for i in reversed(code_lines[1:]):
            del lines[i]
        language_text = "\n".join(lines) + "\n"
    else:
        language_text = "# Longshot game language\n" + language + "\n"
    return {language_path: language_text.encode("utf-8"), options_path: text.encode("utf-8")}


def preferences_match(game, language, button_prompts):
    return all(path.is_file() and path.read_bytes() == data for path, data in desired_files(game, language, button_prompts).items())


def apply_preferences(game, language, button_prompts):
    game = Path(game)
    if not (game / ".hmb-owner.json").is_file():
        raise ValueError("Cette installation n'est pas gérée par le manager")
    if button_prompts in FACES and not (game / "prompts" / FACES[button_prompts]).is_dir():
        raise ValueError("Ressources d'icônes absentes : régénérer les prompts Longshot avant application")
    wanted = desired_files(game, language, button_prompts)
    previous = {path: path.read_bytes() if path.is_file() else None for path in wanted}
    changed = [path for path, data in wanted.items() if previous[path] != data]
    try:
        for path in changed:
            temp = path.with_name(path.name + ".hmb-new")
            with temp.open("wb") as stream:
                stream.write(wanted[path])
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
    except BaseException:
        for path in changed:
            if previous[path] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous[path])
        raise
    return bool(changed)
