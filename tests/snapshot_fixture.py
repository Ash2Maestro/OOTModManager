"""Minimal read-only engine response for native application-state tests."""
import json
import sys
from pathlib import Path
import time

request = json.loads(sys.stdin.read())
if request.get('action') == 'resolve_source':
    values = request['settings']
    time.sleep(.2)
    print('HMBGUI ' + json.dumps(dict(type='source_detected', game_dir=values['game_dir'],
          engine=values['engine'], previous_source=values['source'],
          source=str(Path(values['game_dir']) / 'original.nup'))), flush=True)
    raise SystemExit(0)
if request.get('action') == 'apply':
    # Simulate an older backend returning its default locale with build settings.
    print('HMBGUI ' + json.dumps(dict(type='installed', settings=dict(request['settings'], ui_language='fr'))), flush=True)
empty = request.get("settings", {}).get("mods_repo", "").endswith("empty-library")
print("HMBGUI " + json.dumps(dict(type="snapshot", catalog=[] if empty else [
    dict(id="item-wheel",name="Wheel",version="1.0.0"),
    dict(id="manual-shield",name="Shield",version="1.0.0")], installed=[], active="vanilla",
    activeName="Vanilla",languages=[],prompts=[],assets="")),flush=True)
