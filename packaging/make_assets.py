"""Generate build assets: app icon (.ico) and Windows version resource for the .exe."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QGuiApplication  # noqa: E402

from glassprompter import APP_NAME, __version__  # noqa: E402
from glassprompter.ui.icon import write_ico  # noqa: E402

app = QGuiApplication([])
assets = os.path.join(ROOT, "assets")
os.makedirs(assets, exist_ok=True)
write_ico(os.path.join(assets, "glassprompter.ico"))

v = tuple(int(x) for x in __version__.split(".")) + (0,)
version_info = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'GlassPrompter'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Olatokunbo Ajayi'),
      StringStruct('OriginalFilename', 'GlassPrompter.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
with open(os.path.join(assets, "version_info.txt"), "w", encoding="utf-8") as f:
    f.write(version_info)
print("assets ready for", __version__)
