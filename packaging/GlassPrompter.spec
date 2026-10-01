# PyInstaller spec - run from the project root:  python -m PyInstaller packaging/GlassPrompter.spec
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Qt modules the app never imports - excluding them keeps the install small.
QT_EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtPrintSupport", "PySide6.QtConcurrent", "PySide6.QtStateMachine",
]

a = Analysis(
    [os.path.join(ROOT, "glass_prompter.pyw")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "glassprompter", "server", "static"), os.path.join("glassprompter", "server", "static"))],
    hiddenimports=["qrcode", "qrcode.constants"],
    excludes=QT_EXCLUDES + ["tkinter", "unittest", "pytest", "pydoc", "PIL"],
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
    icon=os.path.join(ROOT, "assets", "glassprompter.ico"),
    version=os.path.join(ROOT, "assets", "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GlassPrompter")
