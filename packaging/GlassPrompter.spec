# PyInstaller spec for Windows and macOS - run from the project root:
#   python -m PyInstaller packaging/GlassPrompter.spec
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from glassprompter import __version__  # noqa: E402
from glassprompter.paths import MODEL_NAME, build_dir  # noqa: E402

MAC = sys.platform == "darwin"
MODEL = os.environ.get("GLASSPROMPTER_MODEL") or os.path.join(build_dir(), "models", MODEL_NAME)
if not os.path.isfile(os.path.join(MODEL, "am", "final.mdl")):
    raise SystemExit("Speech model missing: " + MODEL)
VOICE = os.path.join(build_dir(), "voices", "en_US-lessac-medium.onnx")       # bundled natural voice
if not (os.path.isfile(VOICE) and os.path.isfile(VOICE + ".json")):
    raise SystemExit("Natural voice missing: " + VOICE)

# Qt modules the app never imports - excluding them keeps the install small.
QT_EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtPrintSupport", "PySide6.QtConcurrent", "PySide6.QtStateMachine",
]
hidden = ["qrcode", "qrcode.constants", "vosk", "sounddevice", "_sounddevice_data", "cffi", "piper", "piper.voice",
          "piper.config", "piper.phonemize_espeak", "piper.espeakbridge", "onnxruntime"]
if MAC:
    hidden += ["objc", "AppKit", "Foundation", "glassprompter.platform.macos"]
else:
    hidden += ["glassprompter.platform.windows"]

# vosk loads its engine with dlopen("libvosk.dyld") on macOS (.dll / .so elsewhere). PyInstaller's
# collect_dynamic_libs() only matches .dylib, so the Mac app shipped without Voice Follow. Collect it by name.
import glob as _glob
import vosk as _vosk
VOSK_LIBS = collect_dynamic_libs("vosk") + [(f, "vosk") for f in
                                            _glob.glob(os.path.join(os.path.dirname(_vosk.__file__), "*.dyld"))]
if not any(os.path.basename(f).startswith("libvosk.") for f, _ in VOSK_LIBS):
    raise SystemExit("vosk engine library not found next to " + _vosk.__file__)

a = Analysis(
    [os.path.join(ROOT, "glass_prompter.pyw")],
    pathex=[ROOT],
    binaries=VOSK_LIBS + collect_dynamic_libs("piper") + collect_dynamic_libs("onnxruntime"),
    datas=[(os.path.join(ROOT, "glassprompter", "server", "static"), os.path.join("glassprompter", "server", "static")),
           (MODEL, os.path.join("glassprompter", "models", MODEL_NAME)),
           (os.path.join(ROOT, "glassprompter", "fonts"), os.path.join("glassprompter", "fonts")),
           (VOICE, os.path.join("glassprompter", "voices")),
           (VOICE + ".json", os.path.join("glassprompter", "voices"))]
          + collect_data_files("_sounddevice_data")
          + collect_data_files("piper", excludes=["train/**", "tashkeel/**", "hebrew/**", "img/**", "templates/**"]),
    hiddenimports=hidden,
    excludes=QT_EXCLUDES + ["tkinter", "unittest", "pytest", "pydoc", "PIL", "piper.train", "torch"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GlassPrompter",
    icon=None if MAC else os.path.join(ROOT, "assets", "glassprompter.ico"),
    version=None if MAC else os.path.join(ROOT, "assets", "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GlassPrompter")

if MAC:
    app = BUNDLE(
        coll,
        name="Glass Prompter.app",
        icon=os.path.join(ROOT, "assets", "GlassPrompter.icns"),
        bundle_identifier="app.glassprompter",
        version=__version__,
        info_plist={
            "CFBundleName": "Glass Prompter",
            "CFBundleDisplayName": "Glass Prompter",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSUIElement": True,                         # lives in the menu bar, no Dock icon
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Voice Follow listens to you read so the script scrolls with your "
                                            "voice. Audio is processed on this Mac and never leaves it.",
            "NSLocalNetworkUsageDescription": "The phone remote lets your phone on the same Wi-Fi send scripts "
                                              "and control playback.",
            "NSHumanReadableCopyright": "Copyright (c) 2026 Olatokunbo Ajayi",
        },
    )
