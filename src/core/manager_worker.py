"""Background process for the desktop GUI. No Tk calls, no automatic game launch."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

from modmanager.models import ROOT, RECEIPT, Settings, Plan, choose_action, settings_from_report
from modmanager.pipeline import (REPORT, digest, load_prepared,
                          read_manifest, write_json, workspace_lock, independent, reusable_preparation)
from modmanager.i18n import event as localized_event
from modmanager.reuse import (native_key, cache_build, restore_build, resources_match,
                       apply_resources, recover_resources)
from modmanager.engines import get_engine, ModRequest
from modmanager.paths import AppPaths
from modmanager.deployment import (validate_target, recover_deployment, replace_installation,
                            ensure_game_closed, JOURNAL)


def emit(kind, **data):
    print("HMBGUI " + json.dumps(localized_event(dict(type=kind, **data)), ensure_ascii=False), flush=True)


class Worker:
    def __init__(self, settings: Settings, force: bool = False, restore_all: bool | None = None):
        self.settings, self.force = settings, force
        self.engine = get_engine(settings.engine)
        self.paths = AppPaths.current(settings.data_root)
        self.restore_all = settings.variant == "vanilla" if restore_all is None else restore_all
        self.workspace = Path(settings.workspace).resolve()
        self.tools = Path(settings.tools_path).resolve()
        self.compiler_python = self.engine.compiler_python(self.tools)
        self.progress = self.engine.progress_parser()

    @property
    def mod_request(self) -> ModRequest:
        return ModRequest(self.workspace, self.tools, self.settings.variant, self.settings.clock,
                          self.settings.hold_ms, self.compiler_python)

    @property
    def cache_root(self):
        return Path(self.settings.native_cache).resolve() if self.settings.native_cache else self.paths.native_cache(self.engine.id)

    def stage(self, name: str, text: str) -> None:
        emit("progress", **self.progress.begin_stage(name))
        emit("log", text=text)

    def run(self, argv: list[str]) -> None:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        env["MOD_MANAGER_DATA"] = str(self.paths.root)
        for name in self.engine.isolated_build_variables:
            env.pop(name, None)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with subprocess.Popen(argv, cwd=ROOT, env=env, creationflags=flags,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            try:
                emit("child", pid=process.pid)
                assert process.stdout is not None
                for line in process.stdout:
                    text = line.rstrip()
                    emit("log", text=text)
                    progress = self.progress.feed(text)
                    if progress is not None:
                        emit("progress", **progress)
                code = process.wait()
            except BaseException:
                # A broken event stream must not leave the compiler running.
                # Descendant cancellation remains owned by the native job object.
                process.kill()
                process.wait()
                raise
        if code:
            raise RuntimeError("L'étape a échoué (code %d). Le journal contient le détail." % code)

    def validate(self):
        s = self.settings
        if not self.engine.capabilities.native_addons:
            raise ValueError("Ce moteur ne prend pas en charge les Addons de code.")
        validate_target(Path(s.game_dir), self.engine.id)
        if not 1 <= s.jobs <= 64 or not 40 <= s.hold_ms <= 500:
            raise ValueError("Vérifiez le nombre de tâches et le délai (40 à 500 ms).")
        if not 64 <= s.native_cache_limit_mib <= 65536:
            raise ValueError("La limite du cache doit être comprise entre 64 et 65536 Mo.")
        self.engine.validate_runtime_settings(s)
        self.engine.validate_tools(self.tools)
        if s.clock and s.variant == "item-wheel" and not self.engine.capabilities.wheel_clock:
            raise ValueError("Ce moteur ne prend pas en charge le réglage de la roue.")
        manifest = None
        if s.variant != "vanilla":
            _, manifest = read_manifest(Path(s.mods_repo), s.variant)
        if not Path(s.source).exists() and not reusable_preparation(s.workspace, s.source):
            raise ValueError("Le jeu original est introuvable. Sélectionnez son NUP ou son dossier.")
        if s.romfs and not Path(s.romfs).is_dir():
            raise ValueError("Le dossier RomFS sélectionné est introuvable.")
        independent(self.cache_root, [Path(s.game_dir), Path(s.source), self.workspace / "prepared",
                                      self.workspace / "addon", self.paths.compilation(self.workspace, self.engine.id)])
        return manifest

    def load(self) -> dict:
        report = load_prepared(self.workspace)
        if report.get("engine", "longshot") != self.engine.id:
            raise ValueError("Cette préparation appartient à un autre moteur.")
        if report["variant"] != self.settings.variant:
            raise ValueError("Ce dossier appartient à une autre variante. Choisissez « Nouveau projet ».")
        if self.settings.variant != "vanilla":
            manifest, _ = read_manifest(Path(self.settings.mods_repo), self.settings.variant)
            if digest(manifest) != report["manifest_sha256"]:
                raise ValueError("Le mod a changé depuis cette préparation. Créez un nouveau projet pour cette version.")
        if Path(report["source"]).resolve() != Path(self.settings.source).resolve():
            raise ValueError("Ce projet utilise un autre jeu original. Créez un nouveau projet pour changer de source.")
        return report

    def mod_needs_update(self, report):
        return self.engine.mod_needs_update(report, self.mod_request)

    def audit(self):
        self.stage("audit", "Comparaison de l'image et des points d'entrée…")
        self.run([self.compiler_python, "-B", str(ROOT / "audit_engine.py"), "--workspace", str(self.workspace),
                  "--tools", str(self.tools)])

    def executable(self) -> Path:
        game = Path(self.settings.game_dir)
        candidates = [game / name for name in self.engine.layout.executables]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def plan(self, report: dict, tool_signature: str) -> Plan:
        game = Path(self.settings.game_dir)
        exe = self.executable()
        game_exists = exe.is_file() and (game / self.engine.layout.image).is_file()
        exe_hash = digest(exe) if game_exists else None
        receipt_path = self.workspace / RECEIPT
        signature = self.engine.preparation_signature(self.workspace, report)
        code_matches = False
        if game_exists and not self.mod_needs_update(report) and report["build_status"].startswith("built"):
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                signature_matches = (receipt["prepared_signature"] == signature or
                                     receipt["prepared_signature"] == self.engine.preparation_signature(self.workspace, report, legacy=True))
                code_matches = (signature_matches and receipt["source_signature"] == tool_signature
                                and receipt["exe_sha256"] == exe_hash
                                and receipt.get("build_options", {"dlss": False}) == report.get("build_options", {"dlss": False}))
            else:
                # Adopt an existing CLI build only when its exact guest image and tool version agree.
                version = self.tools / "version.txt"
                installed_version = game / self.engine.layout.version
                same_version = (version.exists() and installed_version.exists() and
                                ("version=" + version.read_text().splitlines()[0].strip()) in installed_version.read_text().splitlines())
                code_matches = same_version and not report.get("build_options", {}).get("dlss") and (self.workspace / self.engine.layout.audit_file).is_file()
        if Path(report.get("game_dir", "")).resolve() != game.resolve():
            code_matches = False
        owner = game / ".hmb-owner.json"
        if owner.is_file() and json.loads(owner.read_text(encoding="utf-8")).get("workspace") != str(self.workspace):
            code_matches = False
        if code_matches:
            code_matches = self.engine.installed_code_matches(report, self.workspace, game)
        if code_matches:
            code_matches = self.engine.runtime_matches(report, game)
        marker_valid, settings_match = self.engine.installed_mod_settings(report, game, self.mod_request, exe_hash)
        code_matches = code_matches and marker_valid
        plan = choose_action(prepared=True, code_matches=code_matches, settings_match=settings_match,
                             game_exists=game_exists, force=self.force,
                             resources_match=(resources_match(self.workspace, report, game)
                                              if code_matches and settings_match and not self.force and report.get("variant")
                                              else True))
        if not self.settings.preserve_runtime_settings and plan.action == "ready" and report.get("variant") and not self.engine.preferences_match(game, self.settings.language, self.settings.button_prompts):
            return Plan("preferences", "Appliquer la langue et les icônes", "Réglages du jeu au prochain lancement : aucune compilation nécessaire.")
        return plan

    def prepare(self):
        if self.settings.variant == "vanilla":
            self.stage("prepare", "Préparation du programme original — aucun RomFS copié…")
            from modmanager.vanilla import prepare_vanilla
            prepare_vanilla(self.settings.source, self.workspace, self.tools, Path(self.settings.game_dir) / "romfs", engine_id=self.engine.id)
            return
        self.stage("prepare", "Reconstruction du mod depuis votre jeu original…")
        argv = [sys.executable, "-B", str(ROOT / "cli.py"), "prepare", "--source", self.settings.source,
                "--variant", self.settings.variant, "--workspace", str(self.workspace), "--tools", str(self.tools),
                "--mods-repo", self.settings.mods_repo, "--engine", self.engine.id]
        if self.settings.romfs and Path(self.settings.source).is_file():
            argv += ["--romfs", self.settings.romfs]
        self.run(argv)

    def adapt(self, report):
        self.engine.adapt_mod(report, self.mod_request, self.run, self.stage)

    def save_receipt(self, signature):
        report = load_prepared(self.workspace)
        game = Path(self.settings.game_dir)
        exe = self.executable()
        write_json(self.workspace / RECEIPT, {"source_signature": signature,
                   "prepared_signature": self.engine.preparation_signature(self.workspace, report), "exe_sha256": digest(exe),
                   "build_options": report.get("build_options", {"dlss": False})})
        if report.get("variant"):
            key = native_key(self.workspace, report, signature, self.settings.language)
            stats = cache_build(self.cache_root, key, game, self.settings.native_cache_limit_mib * 1024**2, engine_id=self.engine.id)
            emit("log", text="Cache compressé : %d build(s), %.1f Mo ; %d ancien(s) build(s) retiré(s)." %
                 (stats["builds"], stats["bytes"] / 1024**2, len(stats["evicted"])))
            write_json(game / ".hmb-active.json", {"schema": 1, "workspace": str(self.workspace),
                       "engine": self.engine.id,
                       "variant": report["variant"], "manifest": report.get("manifest", {"name": report["variant"], "version": ""}),
                       "build_options": report.get("build_options", {"dlss": False}),
                       "installed_overlay": report.get("installed_overlay", {})})
            emit("log", text="Build natif mémorisé : ce code pourra être réutilisé sans compilation.")

    def apply_runtime_preferences(self):
        if self.settings.preserve_runtime_settings:
            return
        self.engine.apply_preferences(self.settings, self.load(), self.compiler_python, self.run, self.stage)
        report = load_prepared(self.workspace)
        report["runtime_preferences"] = {"language": self.settings.language, "button_prompts": self.settings.button_prompts}
        write_json(self.workspace / REPORT, report)

    def execute(self, analyse=False):
        game = Path(self.settings.game_dir)
        if not analyse and game.is_dir():
            ensure_game_closed(self.engine.id)
            with workspace_lock(game):
                recover_deployment(game)
                return self._execute(analyse)
        return self._execute(analyse)

    def remember_active_profile(self):
        owner = Path(self.settings.game_dir) / ".hmb-owner.json"
        if not owner.is_file():
            return
        try:
            old_project = Path(json.loads(owner.read_text(encoding="utf-8"))["workspace"])
            if old_project.resolve() == self.workspace:
                return
            old_report = load_prepared(old_project)
            settings = settings_from_report(old_project, old_report)
            settings.game_dir = self.settings.game_dir
            settings.tools_path = self.settings.tools_path
            settings.engine = self.engine.id
            settings.native_cache = self.settings.native_cache
            settings.native_cache_limit_mib = self.settings.native_cache_limit_mib
            old = Worker(settings)
            old.audit()
            signature = old.engine.tools_signature(old.tools)
            if old.plan(old_report, signature).action in ("ready", "resources", "preferences"):
                old.save_receipt(signature)
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            emit("log", text="Ancien profil non mémorisé : " + str(error))

    def _execute(self, analyse=False):
        self.stage("audit", "Vérification du projet et des fichiers…")
        self.validate()
        if not analyse:
            recover_resources(Path(self.settings.game_dir))
        if not (self.workspace / REPORT).exists():
            plan = choose_action(prepared=False, code_matches=False, settings_match=False, game_exists=False)
            emit("plan", **plan.__dict__)
            if analyse:
                return
            self.prepare()
        report = self.load()
        self.stage("audit", "Vérification des sources du compilateur et du cache…")
        report.setdefault("build_work", str(self.paths.compilation(self.workspace, self.engine.id)))
        report.update(self.engine.prepare_runtime(self.settings, self.tools, self.compiler_python, self.run, read_only=analyse))
        if not analyse:
            write_json(self.workspace / REPORT, report)
        signature = self.engine.tools_signature(self.tools)
        self.audit()
        plan = self.plan(report, signature)
        emit("plan", **plan.__dict__)
        if analyse:
            return
        # The preparation may predate a tool update. Audit and build must use
        # the same explicitly selected tools, not the deleted historical version.
        if Path(report["tools_path"]).resolve() != self.tools:
            report["tools_path"] = str(self.tools)
            write_json(self.workspace / REPORT, report)
        game = Path(self.settings.game_dir)
        all_overlays = self.restore_all and (game / "mods").is_dir() and any((game / "mods").iterdir())
        if plan.action == "build" or all_overlays:
            # Prepared modules are workspace state, not installed-game state.
            # Snapshot the deployment only after adaptation, otherwise rollback
            # restores an inventory from before the modules were changed.
            self.adapt(report)
            report = self.load()
        if (plan.action == "build" or all_overlays) and game.is_dir():
            if all_overlays and plan.action != "build":
                # Code already proven vanilla: populate its snapshot before replacing
                # overlays, so this operation never invokes the compiler just for resources.
                self.save_receipt(signature)
            self.remember_active_profile()
            self.stage("finish", "Remplacement dans votre installation — RomFS et sauvegardes conservés…")
            if all_overlays:
                plan = Plan("build", "Restaurer le jeu vanilla", "Retrait de tous les mods actifs, sauvegardes conservées.")
            with replace_installation(self.workspace, report, game, disable_all_mods=self.restore_all):
                return self.apply_plan(plan, signature)
        return self.apply_plan(plan, signature)

    def apply_plan(self, plan: Plan, signature: str) -> None:
        """Execute one validated action, then record the successful installation.

        Native replacement is owned by the caller's deployment transaction.
        Never turn an unknown action into an implicit compilation.
        """
        messages = {
            "ready": "Projet déjà à jour. Aucune compilation nécessaire.",
            "preferences": "Langue et icônes appliquées sans compilation.",
            "resources": "Ressources appliquées sans compilation.",
            "configure": "Réglage appliqué sans compilation.",
            "build": "Compilation terminée. Le jeu est prêt à être testé.",
        }
        if plan.action not in messages:
            raise ValueError("Action inconnue : " + plan.action)
        report = self.load()
        if plan.action == "preferences":
            self.stage("configure", "Application de la langue et des icônes — aucune compilation…")
        elif plan.action == "resources":
            self.stage("finish", "Application des ressources — aucune compilation…")
            apply_resources(self.workspace, report, Path(self.settings.game_dir))
        elif plan.action == "configure":
            self.configure_mod()
            self.sync_resources()
        elif plan.action == "build":
            if self.restore_cached_build(report, signature):
                messages["build"] = "Build identique réutilisé et ressources appliquées. Aucune traduction ni compilation."
            else:
                self.compile_native()
                self.sync_resources()
        self.apply_runtime_preferences()
        self.save_receipt(signature)
        emit("complete", message=messages[plan.action])

    def configure_mod(self) -> None:
        """Apply a backend-qualified runtime setting without compilation."""
        self.engine.configure_mod(self.mod_request, Path(self.settings.game_dir), self.run, self.stage)

    def sync_resources(self) -> None:
        """Reload after native/clock writes before checking the owned overlay."""
        report = self.load()
        game = Path(self.settings.game_dir)
        if not resources_match(self.workspace, report, game):
            apply_resources(self.workspace, report, game)

    def restore_cached_build(self, report: dict, signature: str) -> bool:
        """Reuse only into a new target or an active replacement transaction."""
        game = Path(self.settings.game_dir)
        if self.force or (game.exists() and not (game / JOURNAL).is_file()):
            return False
        key = native_key(self.workspace, report, signature, self.settings.language)
        if not (self.cache_root / key).is_dir():
            return False
        self.audit()
        emit("plan", action="reuse", title="Réutiliser le build mémorisé",
             reason="Les fichiers natifs et les outils correspondent : aucune compilation.")
        self.stage("finish", "Réutilisation d’un build identique — aucune compilation…")
        restore_build(self.cache_root, key, self.workspace, report, game)
        return True

    def compile_native(self) -> None:
        """Run the selected compiler, preserving installation-owned preferences."""
        self.stage("read", "Reprise de la compilation avec le cache…")
        argv = [sys.executable, "-B", str(ROOT / "cli.py"), "build", "--workspace", str(self.workspace),
                "--python", self.compiler_python, "--game-dir", self.settings.game_dir, "--jobs", str(self.settings.jobs)]
        if not self.settings.preserve_runtime_settings:
            argv += ["--language", self.settings.language]
        self.run(argv)
        self.engine.finalize_build(self.mod_request, Path(self.settings.game_dir), self.run, self.stage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--analyse", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        Worker(Settings(**json.loads(args.settings.read_text(encoding="utf-8"))), args.force).execute(args.analyse)
    except BaseException as error:
        emit("log", text=traceback.format_exc())
        emit("error", message=str(error))
        raise SystemExit(1)
