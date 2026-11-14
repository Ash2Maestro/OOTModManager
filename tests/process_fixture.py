"""Own disposable child/grandchild process, used by the Windows job test only."""
import json
import subprocess
import sys
import time

json.loads(sys.stdin.read())
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print("HMBGUI " + json.dumps(dict(type="child", pid=child.pid)), flush=True)
time.sleep(60)
