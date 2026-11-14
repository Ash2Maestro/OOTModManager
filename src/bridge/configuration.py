"""Validate configured inputs before game operations; never create paths here."""
from pathlib import Path


def directory(value, label):
    if not value or not str(value).strip():
        raise ValueError(label + " non renseigné. Ouvrez Paramètres → Paramètres techniques.")
    path = Path(value)
    if not path.is_dir():
        raise ValueError(label + " introuvable ou inaccessible : " + str(path))
    return path


def game_directory(settings):
    from modmanager.engines import get_engine
    game = directory(settings.game_dir, "Dossier du jeu")
    if not get_engine(settings.engine).launch_command(game):
        raise ValueError("Aucun exécutable reconnu par ce moteur dans le dossier : " + str(game))
    return game


def build_inputs(settings):
    tools = directory(settings.tools_path, "Dossier des outils du moteur")
    from modmanager.engines import get_engine
    get_engine(settings.engine).validate_compiler(tools)
    if not settings.source or not str(settings.source).strip():
        raise ValueError("Source du jeu non renseignée. Sélectionnez votre NUP ou dossier extrait dans Paramètres.")
    from modmanager.pipeline import reusable_preparation
    if not Path(settings.source).exists() and not reusable_preparation(getattr(settings, 'workspace', ''), settings.source):
        raise ValueError("Source du jeu introuvable : " + settings.source)


def appearance_available(settings):
    return bool(settings.game_dir and settings.tools_path
                and (Path(settings.game_dir) / "romfs").is_dir()
                and Path(settings.tools_path).is_dir())
