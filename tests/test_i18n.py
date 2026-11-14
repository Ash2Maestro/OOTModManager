"""Catalog completeness and real presentation translation, without game writes."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/core'))
from modmanager import i18n


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.messages = json.loads((ROOT/'i18n/en.json').read_text(encoding='utf-8'))['messages']
        i18n.configure('en', ROOT/'i18n')

    def tearDown(self):
        i18n.configure('fr')

    def test_all_qt_sources_have_an_english_translation(self):
        sources = []
        for path in [*ROOT.glob('src/ui/qml/*.qml'), *ROOT.glob('src/ui/cpp/*.cpp')]:
            sources.extend((path.name, json.loads(match.group(1))) for match in
                           re.finditer(r'\b(?:qsTr|tr)\(("(?:[^"\\]|\\.)*")\)', path.read_text(encoding='utf-8')))
        self.assertGreater(len(sources), 70)
        for path, source in sources:
            self.assertIn(source, self.messages, (path, source))
            self.assertTrue(self.messages[source].strip(), (path, source))

    def test_placeholders_match_and_french_catalog_is_explicit(self):
        french = json.loads((ROOT/'i18n/fr.json').read_text(encoding='utf-8'))['messages']
        placeholder = r'%(?:\.\d+)?[sdf]|%[1-9]'
        self.assertEqual(set(french), set(self.messages))
        for source, translated in self.messages.items():
            self.assertEqual(sorted(re.findall(placeholder, source)), sorted(re.findall(placeholder, translated)), source)
            self.assertEqual(french[source], source)

    def test_errors_keep_paths_and_progress_formats_numbers(self):
        path = r'G:\Bibliothèque\Paramètres\mod %1.zip'
        self.assertEqual(i18n.text('Dossier du jeu introuvable ou inaccessible : ' + path),
                         'Game folder was not found or is inaccessible: ' + path)
        self.assertEqual(i18n.text('Dossier du jeu non renseigné. Ouvrez Paramètres → Paramètres techniques.'),
                         'Game folder is not set. Open Settings → Technical settings.')
        self.assertEqual(i18n.text('Cache compressé : 3 build(s), 12.5 Mo ; 1 ancien(s) build(s) retiré(s).'),
                         'Compressed cache: 3 build(s), 12.5 MiB; 1 old build(s) removed.')
        self.assertEqual(i18n.text('code_017.c — réutilisé du cache'), 'code_017.c — reused from cache')

    def test_metadata_identifiers_and_raw_longshot_logs_are_unchanged(self):
        row = dict(id='bibliothèque', name='Bibliothèque', description='Paramètres', author='Journal',
                   subtitle='Addon de code', contentSummary='2 fichier(s) ExeFS · 4 fichier(s) RomFS')
        payload = dict(type='snapshot', catalog=[row], installed=[], active='vanilla', activeName='Jeu original')
        translated = i18n.event(payload)
        for key in ('id','name','description','author'):
            self.assertEqual(translated['catalog'][0][key], row[key])
        self.assertEqual(translated['catalog'][0]['subtitle'], 'Code Addon')
        self.assertEqual(translated['catalog'][0]['contentSummary'], '2 ExeFS file(s) · 4 RomFS file(s)')
        self.assertEqual(payload['catalog'][0]['subtitle'], 'Addon de code')
        raw = 'the Vulkan back end: with NVIDIA DLSS'
        self.assertEqual(i18n.event(dict(type='log',text=raw))['text'], raw)

    def test_missing_language_falls_back_without_changing_identifiers(self):
        i18n.configure('../en', ROOT/'i18n')
        self.assertEqual(i18n.text('Bibliothèque'), 'Bibliothèque')
        i18n.configure('zz', ROOT/'i18n')
        self.assertEqual(i18n.text('Bibliothèque'), 'Bibliothèque')

    def test_reported_build_diagnostics_are_fully_translated(self):
        cases = {
            'Audit du chargeur Longshot reussi ; gameplay encore non qualifie.':
                'Longshot loader audit passed; gameplay has not been validated yet.',
            '30 lectures/s : maintien transmis apres 0.133 s ; compteur HID preserve.':
                '30 polls/s: hold forwarded after 0.133 s; HID counter preserved.',
            'Cache partage : 401 objets ajoutes depuis 7 cache(s) ; Longshot verifie leurs cles avant reutilisation.':
                'Shared cache: 401 objects added from 7 cache(s); Longshot verifies their keys before reuse.',
            "Verification de l'environnement de compilation avant partage du cache…":
                'Checking the build environment before sharing the cache…',
            'Execution : C:/Games/OOT/example.exe --out "G:/Bibliothèque/OOT"':
                'Running: C:/Games/OOT/example.exe --out "G:/Bibliothèque/OOT"',
        }
        for source, expected in cases.items():
            self.assertEqual(i18n.event(dict(type='log', text=source))['text'], expected)
