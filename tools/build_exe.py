"""Build the Windows release: dist/mq-overlay/ (a folder with mq-overlay.exe), dist/mq-overlay-win.zip and, with
--installer, dist/mq-overlay-<version>-setup.exe (Inno Setup, tools/installer.iss: per-user install with a Start
menu entry, a desktop icon and an uninstaller; what a player downloads).

    uv run --group build tools/build_exe.py [--version 1.2.3] [--installer] [--own-bootloader]

PyInstaller bundles Python, the overlay, its data and only the Qt modules the overlay uses (Core, Gui, Widgets,
Svg). What PySide6 ships beyond that (Qt Quick, QML, the designer tools, a 20 MB software-OpenGL DLL, translations,
SSL) is left out, which takes the folder from about 200 MB to under 80 MB (31 MB zipped). The GitHub release
workflow (.github/workflows/release.yml) runs this on a tag.

Antivirus (2026-10-08, a player's Norton flagged the download and scanned at every start): the exe gets a version
resource (name, publisher, description; an exe without one looks suspicious), no UPX packing, and with
--own-bootloader PyInstaller's bootloader (the small program in mq-overlay.exe that starts Python) is compiled here
instead of taking the ready-made one, which malware uses too, so scanners know it. That needs a C compiler (Visual
Studio Build Tools; GitHub's Windows runners have it). Neither fixes the download warning: that is reputation, and
only code signing builds it."""

import argparse
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_QT = ["QtQml", "QtQuick", "QtQuickWidgets", "QtNetwork", "QtOpenGL", "QtOpenGLWidgets", "QtSql", "QtTest",
               "QtPrintSupport", "QtXml", "QtConcurrent", "QtDBus", "QtDesigner", "QtUiTools", "QtHelp"]
EXCLUDED_PY = ["tkinter", "unittest", "pydoc", "_ssl", "_hashlib"]
# shipped by PySide6 but never loaded by a QtWidgets app: the software OpenGL fallback and Qt's translations
TRIM = ["_internal/PySide6/opengl32sw.dll", "_internal/PySide6/translations"]
VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
          StringStruct('CompanyName', 'whyvnaa'),
          StringStruct('FileDescription', 'MQ Overlay: map overlay for Monkey Quest (MQReborn)'),
          StringStruct('FileVersion', '{text}'),
          StringStruct('InternalName', 'mq-overlay'),
          StringStruct('LegalCopyright', 'whyvnaa'),
          StringStruct('OriginalFilename', 'mq-overlay.exe'),
          StringStruct('ProductName', 'MQ Overlay'),
          StringStruct('ProductVersion', '{text}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def own_bootloader() -> None:
    """Reinstall the PyInstaller version in use from its source package, compiling the bootloader (needs a C
    compiler)."""
    version = importlib.metadata.version("pyinstaller")
    env = dict(os.environ, PYINSTALLER_COMPILE_BOOTLOADER="1")
    subprocess.run(["uv", "pip", "install", "--python", sys.executable, "--reinstall-package", "pyinstaller", "--no-cache",
                    "--no-binary", "pyinstaller", f"pyinstaller=={version}"], check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build mq-overlay.exe and the release zip")
    parser.add_argument("--version", default="", help="goes into the zip's name (mq-overlay-<version>-win.zip)")
    parser.add_argument("--installer", action="store_true", help="also build the setup exe (needs Inno Setup 6)")
    parser.add_argument("--own-bootloader", action="store_true",
                        help="compile PyInstaller's bootloader first (needs Visual Studio Build Tools)")
    args = parser.parse_args()
    if args.own_bootloader:
        own_bootloader()
    dist, work = ROOT / "dist", ROOT / "build"
    shutil.rmtree(dist / "mq-overlay", ignore_errors=True)
    launcher = work / "launch.py"
    work.mkdir(exist_ok=True)
    launcher.write_text("import sys\nfrom mq_overlay.__main__ import main\nsys.exit(main())\n", encoding="utf-8", newline="\n")
    icon = work / "icon.ico"  # PyInstaller wants an .ico on Windows: Qt converts the overlay's icon
    from PySide6.QtGui import QGuiApplication, QImage
    app = QGuiApplication([])
    if not QImage(str(ROOT / "data" / "icon.png")).scaled(256, 256).save(str(icon)):
        raise SystemExit("could not write the icon")
    del app
    text = args.version.lstrip("v") or "0.0.0"
    nums = tuple(([int(n) for n in text.split(".") if n.isdigit()] + [0] * 4)[:4])
    version_file = work / "version_info.txt"
    version_file.write_text(VERSION_INFO.format(nums=nums, text=text), encoding="utf-8", newline="\n")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "mq-overlay", "--windowed",
           "--distpath", str(dist), "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
           "--paths", str(ROOT / "src"), "--add-data", f"{ROOT / 'data'}{';' if sys.platform == 'win32' else ':'}mq_overlay/data",
           "--icon", str(icon), "--version-file", str(version_file), "--noupx"]
    for m in EXCLUDED_QT:
        cmd += ["--exclude-module", f"PySide6.{m}"]
    for m in EXCLUDED_PY:
        cmd += ["--exclude-module", m]
    subprocess.run(cmd + [str(launcher)], check=True)
    folder = dist / "mq-overlay"
    for rel in TRIM:
        p = folder / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    name = f"mq-overlay-{args.version}-win" if args.version else "mq-overlay-win"
    archive = shutil.make_archive(str(dist / name), "zip", dist, "mq-overlay")
    print(f"{folder}: {size / 2**20:.0f} MB; {archive}: {Path(archive).stat().st_size / 2**20:.1f} MB")
    if args.installer:
        iscc = next((p for p in (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
                                 Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
                                 Path(shutil.which("iscc") or "nowhere")) if p.exists()), None)
        if iscc is None:
            raise SystemExit("Inno Setup 6 (ISCC.exe) not found: install it from https://jrsoftware.org/isinfo.php")
        version = args.version.lstrip("v") or "0.0.0"
        subprocess.run([str(iscc), f"/DAppVersion={version}", f"/DSourceDir={folder}", f"/DOutputDir={dist}",
                        f"/DIconFile={icon}", str(ROOT / "tools" / "installer.iss")], check=True)
        setup = dist / f"mq-overlay-{version}-setup.exe"
        print(f"{setup}: {setup.stat().st_size / 2**20:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
