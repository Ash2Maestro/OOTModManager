# Traductions du manager

`fr.json` et `en.json` contiennent les textes partagés par l'interface Qt et le moteur
Python. Le format est `{ "language": "en", "name": "English", "messages": { ... } }`.
Les clés sont les textes sources français, les valeurs leur traduction. Les valeurs
du catalogue français reprennent le texte source. Une entrée absente garde sa source.

Qt utilise `qsTr()` dans le QML et `tr()` dans le C++, avec un `QTranslator` alimenté
par ces catalogues. Les ressources sont intégrées à l'exécutable ; `retranslate()`
actualise les vues lors du choix de langue. Le pont Python lit les mêmes catalogues
et traduit les champs de présentation des événements. Il ne traduit pas les noms,
descriptions ou auteurs fournis par les mods, ni les identifiants et chemins.
Les journaux techniques de Hookshot conservent leur texte d'origine.

## Ajouter une langue

1. Copier `fr.json` vers un fichier comme `es.json`, changer `language` et `name`,
   puis traduire les valeurs de `messages` en conservant les clés.
2. Conserver les paramètres : `%1`, `%2` pour Qt ; `%s`, `%d`, `%.1f` pour Python.
   Utiliser une phrase complète avec paramètres plutôt que des fragments concaténés.
3. Recompiler le projet. CMake détecte les catalogues JSON et le menu des langues
   se construit à partir de leurs métadonnées, sans modifier le QML.
4. Exécuter les tests du projet et contrôler les libellés longs dans l'interface.

Les codes acceptés sont `xx` ou `xx-YY`. Le français est le repli de référence.
La préférence `ui_language` appartient au manager et n'est jamais passée au jeu.
Les catalogues JSON communs évitent de maintenir deux traductions distinctes en
TS/QM pour Qt et PO/MO pour Python.

## Vérifier

```powershell
..\HookshotModBuilder\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_i18n.py
.\Build.cmd
```

Le test natif accepte `--smoke --smoke-language en` pour vérifier les vues et produire
une capture de démonstration sans enregistrer ce choix dans les paramètres utilisateur.
