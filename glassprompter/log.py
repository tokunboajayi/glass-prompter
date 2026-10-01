"""Logging: rotating file log, crash capture for Python and native faults."""
import faulthandler
import logging
import logging.handlers
import os
import sys
import threading

from . import __version__
from .paths import log_dir

_fault_file = None
_configured = False


def setup(level=logging.INFO):
    global _fault_file, _configured
    if _configured:
        return logging.getLogger("glassprompter")
    d = log_dir()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(os.path.join(d, "glassprompter.log"), maxBytes=1_000_000,
                                              backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)
    if sys.stderr is not None:          # pythonw / frozen GUI builds have no console
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    try:
        _fault_file = open(os.path.join(d, "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(_fault_file)
    except Exception:
        pass

    crash = logging.getLogger("crash")

    def excepthook(t, v, tb):
        crash.critical("Unhandled exception", exc_info=(t, v, tb))

    def thread_hook(args):
        crash.critical("Unhandled exception in thread %s", getattr(args.thread, "name", "?"),
                       exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    _configured = True
    log = logging.getLogger("glassprompter")
    log.info("Glass Prompter %s starting (Python %s)", __version__, sys.version.split()[0])
    return log
