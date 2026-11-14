"""Reuse Longshot's installed renderer without configuring its optional features."""
from pathlib import Path
from ..storage import digest, no_links


def renderer(game, tools):
    game, tools = Path(game), Path(tools)
    version_file = game / 'longshot_version.txt'
    tools_version = tools / 'version.txt'
    if not version_file.is_file() or not tools_version.is_file():
        raise ValueError("Version Longshot introuvable. Choisissez une installation et ses outils complets.")
    version = next((line[8:].strip() for line in version_file.read_text(encoding='utf-8').splitlines()
                    if line.startswith('version=')), '')
    if not version or version != tools_version.read_text(encoding='utf-8').strip():
        raise ValueError("Le jeu et les outils Longshot sont de versions différentes. Mettez-les en cohérence avec Longshot Builder avant d'appliquer un mod.")
    for relative in ('bin/longshot_vk.dll', 'longshot_vk.dll', 'longshot_vk.so'):
        path = game / relative
        no_links(path)
        if path.is_file():
            return relative, digest(path)
    raise ValueError("Moteur graphique Longshot absent. Réparez l'installation avec Longshot Builder.")


def environment(report):
    path = Path(report['prebuilt_renderer'])
    no_links(path)
    if not path.is_file() or digest(path) != report['build_options']['renderer_sha256']:
        raise ValueError("Le moteur graphique de l'installation a changé ; relancez l'application du mod.")
    return {'LONGSHOT_VK_PREBUILT': str(path)}
