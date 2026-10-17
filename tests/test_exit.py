import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_hard_exit_keeps_the_exit_code_and_flushes_output():
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from glassprompter.platform.common import hard_exit\n"
            "import threading, time\n"
            "threading.Thread(target=time.sleep, args=(30,), daemon=False).start()   # a busy worker at exit\n"
            "print('saved everything', end='')\n"
            "hard_exit(7)\n" % ROOT)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert r.returncode == 7 and r.stdout == "saved everything"
