"""Phone remote UI test: starts the app from source on a throw-away profile (headless) and drives the phone web app
in a mobile browser with Playwright.  Requires Node + Playwright (`npm i -g playwright`).

    python tools/phone_e2e.py           # exit 0 = every check passed; screenshots in ./shots/phone
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    home = tempfile.mkdtemp(prefix="gp_phone_")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, GLASSPROMPTER_HOME=home, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    os.environ["GLASSPROMPTER_HOME"] = home
    from glassprompter import __version__, config
    c = config.Config()
    c.load()
    c.s.first_run_done, c.s.auto_update, c.s.remote_enabled = True, False, True
    c.s.remote_port, c.s.pin, c.s.probe_version = port, "246810", __version__
    c.save()
    app = subprocess.Popen([sys.executable, os.path.join(ROOT, "glass_prompter.pyw")], env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/api/v1/health" % port, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        out = os.path.join(ROOT, "shots", "phone")
        os.makedirs(out, exist_ok=True)
        node_path = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, shell=os.name == "nt").stdout.strip()
        return subprocess.call(["node", os.path.join(ROOT, "tools", "phone_e2e.js"), str(port), out],
                               env=dict(os.environ, NODE_PATH=node_path))
    finally:
        app.terminate()


if __name__ == "__main__":
    sys.exit(main())
