# PyInstaller spec: one folder holding two programs that share the engine.
#   hwp2x      console program (CLI)
#   hwp2x-gui  windowed program (GUI)      -> on macOS wrapped as hwp2x.app
# Build:  pyinstaller packaging/hwp2x.spec --noconfirm
#
# Name, version and copyright come from src/hwp2x/about.py, so a release only
# needs the version bumped in src/hwp2x/__init__.py (and pyproject.toml).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ENGINE = ROOT / "src" / "hwp2x" / "_engine"
ICONS = ROOT / "packaging" / "icons"
if not (ENGINE / "runtime").exists():
    raise SystemExit("Bundled Java runtime missing: run  python scripts/build_engine.py  first")

sys.path.insert(0, str(ROOT / "src"))
from hwp2x import about  # noqa: E402

datas = [
    (str(ENGINE / "hwp2x-engine.jar"), "hwp2x/_engine"),
    (str(ENGINE / "NOTICE.txt"), "hwp2x/_engine"),
    (str(ENGINE / "runtime"), "hwp2x/_engine/runtime"),
    (str(ROOT / "src" / "hwp2x" / "assets"), "hwp2x/assets"),
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


def windows_version_file(exe_name: str, description: str) -> str:
    """Version resource shown in Explorer: Properties > Details."""
    nums = [int(x) for x in (about.VERSION.split(".") + ["0", "0", "0"])[:4] if x.isdigit()]
    nums = (nums + [0, 0, 0, 0])[:4]
    t = tuple(nums)
    text = f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204B0', [
      StringStruct('CompanyName', {about.COMPANY!r}),
      StringStruct('FileDescription', {description!r}),
      StringStruct('FileVersion', {about.VERSION!r}),
      StringStruct('InternalName', {exe_name!r}),
      StringStruct('LegalCopyright', {about.COPYRIGHT_ASCII!r}),
      StringStruct('OriginalFilename', {exe_name + '.exe'!r}),
      StringStruct('ProductName', {about.APP_NAME!r}),
      StringStruct('ProductVersion', {about.VERSION!r})])]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""
    path = Path(workpath) / f"{exe_name}-version.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


win = sys.platform == "win32"
icon = str(ICONS / ("hwp2x.ico" if win else "hwp2x.icns"))

cli_a = analysis("cli_entry.py")
gui_a = analysis("gui_entry.py")

cli_exe = EXE(PYZ(cli_a.pure), cli_a.scripts, [], exclude_binaries=True,
              name="hwp2x", console=True, upx=False, icon=icon,
              version=windows_version_file("hwp2x", f"{about.APP_NAME} (명령줄)") if win else None)
gui_exe = EXE(PYZ(gui_a.pure), gui_a.scripts, [], exclude_binaries=True,
              name="hwp2x-gui", console=False, upx=False, icon=icon,
              version=windows_version_file("hwp2x-gui", about.APP_NAME) if win else None)

coll = COLLECT(cli_exe, cli_a.binaries, cli_a.datas,
               gui_exe, gui_a.binaries, gui_a.datas,
               name="hwp2x", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(coll, name="hwp2x.app", bundle_identifier=about.BUNDLE_ID,
                 icon=str(ICONS / "hwp2x.icns"),
                 version=about.VERSION,
                 info_plist={
                     "CFBundleDisplayName": about.APP_NAME,
                     "CFBundleExecutable": "hwp2x-gui",
                     "CFBundleShortVersionString": about.VERSION,
                     "CFBundleVersion": about.VERSION,
                     "NSHumanReadableCopyright": f"{about.COPYRIGHT}. {about.LICENSE}.",
                     "NSHighResolutionCapable": True,
                     "LSApplicationCategoryType": "public.app-category.productivity",
                     "CFBundleDocumentTypes": [{
                         "CFBundleTypeName": "Hangul Document",
                         "CFBundleTypeExtensions": ["hwp", "hwpx"],
                         "CFBundleTypeRole": "Viewer",
                         "LSHandlerRank": "Alternate",
                     }],
                 })
