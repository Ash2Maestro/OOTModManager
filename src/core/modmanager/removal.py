"""List installed native packs/overlays and plan independent removal actions."""
from pathlib import Path
import shutil
import uuid
from .pipeline import no_links, safe_relative, tree_files
from .deployment import active_profile


def installed_mods(game):
    game = Path(game)
    if (game / ".hmb-deployment.json").exists():
        raise ValueError("Une application interrompue/en cours doit être terminée avant de désinstaller")
    result, managed = [], None
    report = active_profile(game)
    if report is not None:
        variant = report["variant"]
        managed = "00-OOT-" + variant
        if variant != "vanilla":
            result.append({"id": "native:" + variant, "kind": "native", "variant": variant,
                           "name": report["manifest"]["name"], "version": report["manifest"]["version"]})
            if variant == "wheel-and-shield":
                for child, name in (("item-wheel", "↳ Item Wheel"), ("manual-shield", "↳ Manual Shield")):
                    result.append({"id": "native:" + child, "kind": "native-component", "variant": child,
                                   "name": name, "version": report["manifest"]["version"]})
    folder = game / "mods"
    no_links(folder)
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.name.startswith(".") or path.name == managed:
                continue
            no_links(path)
            if path.is_dir():
                result.append({"id": "overlay:" + path.name, "kind": "overlay", "name": path.name, "version": ""})
    return result


def remaining_native(active, selected):
    if active == selected:
        return "vanilla"
    if active == "wheel-and-shield":
        if selected == "item-wheel":
            return "manual-shield"
        if selected == "manual-shield":
            return "item-wheel"
    raise ValueError("Ce mod n'est pas installé séparément dans le profil actif. Les fonctionnalités d'un pack unifié ne sont pas des mods séparés.")


def uninstall_overlay(game, identifier):
    game = Path(game).resolve()
    found = next((m for m in installed_mods(game) if m["id"] == identifier and m["kind"] == "overlay"), None)
    if found is None:
        raise ValueError("Le mod sélectionné n'est plus installé, ou fait partie du programme natif")
    name = identifier[len("overlay:"):]
    relative = safe_relative(name)
    if len(relative.parts) != 1:
        raise ValueError("Nom de mod invalide")
    source = game / "mods" / relative
    no_links(source)
    tree_files(source)
    trash = game / ".hmb-uninstall" / uuid.uuid4().hex
    no_links(trash)
    trash.parent.mkdir(exist_ok=True)
    source.rename(trash)
    # The requested, verified single overlay only. Never remove any game/RomFS folder.
    shutil.rmtree(trash)
