# PyInstaller spec: one folder holding two programs that share the engine.
#   hwp2x      console program (CLI)
#   hwp2x-gui  windowed program (GUI)      -> on macOS wrapped as hwp2x.app
# Build:  pyinstaller packaging/hwp2x.spec --noconfirm
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ENGINE = ROOT / "src" / "hwp2x" / "_engine"
if not (ENGINE / "runtime").exists():
    raise SystemExit("Bundled Java runtime missing: run  python scripts/build_engine.py  first")

datas = [
    (str(ENGINE / "hwp2x-engine.jar"), "hwp2x/_engine"),
    (str(ENGINE / "NOTICE.txt"), "hwp2x/_engine"),
    (str(ENGINE / "runtime"), "hwp2x/_engine/runtime"),
]

# Qt modules the app never touches; keeps the bundle small.
excludes = ["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDBus",
            "PySide6.QtPdf", "PySide6.QtSvg"]


def _keep(entry):
    # Qt ships ~7 MB of UI translations; the app only needs Korean and English.
    dest = entry[0].replace("\\", "/")
    if "/translations/" in dest:
        name = dest.rsplit("/", 1)[-1]
        return name.endswith(("_ko.qm", "_en.qm"))
    return True


def analysis(script):
    a = Analysis([str(ROOT / "packaging" / script)], pathex=[str(ROOT / "src")],
                 datas=datas, excludes=excludes, noarchive=False,
                 # writers are imported on demand, by format
                 hiddenimports=["hwp2x.writers.markdown", "hwp2x.writers.html", "hwp2x.writers.latex",
                                "hwp2x.writers.docx", "hwp2x.hwpx_reader", "PIL.BmpImagePlugin",
                                "PIL.GifImagePlugin", "PIL.TiffImagePlugin", "PIL.PngImagePlugin",
                                "PIL.JpegImagePlugin"])
    a.datas = [d for d in a.datas if _keep(d)]
    return a


cli_a = analysis("cli_entry.py")
gui_a = analysis("gui_entry.py")

cli_exe = EXE(PYZ(cli_a.pure), cli_a.scripts, [], exclude_binaries=True,
              name="hwp2x", console=True, upx=False)
gui_exe = EXE(PYZ(gui_a.pure), gui_a.scripts, [], exclude_binaries=True,
              name="hwp2x-gui", console=False, upx=False)

coll = COLLECT(cli_exe, cli_a.binaries, cli_a.datas,
               gui_exe, gui_a.binaries, gui_a.datas,
               name="hwp2x", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(coll, name="hwp2x.app", bundle_identifier="kr.hwp2x.app",
                 info_plist={
                     "CFBundleDisplayName": "hwp2x",
                     "CFBundleExecutable": "hwp2x-gui",
                     "CFBundleShortVersionString": "0.2.0",
                     "NSHighResolutionCapable": True,
                     "CFBundleDocumentTypes": [{
                         "CFBundleTypeName": "Hangul Document",
                         "CFBundleTypeExtensions": ["hwp", "hwpx"],
                         "CFBundleTypeRole": "Viewer",
                         "LSHandlerRank": "Alternate",
                     }],
                 })
