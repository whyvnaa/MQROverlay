"""Build the Windows release: dist/mq-overlay/ (a folder with mq-overlay.exe) and dist/mq-overlay-win.zip.

    uv run --group build tools/build_exe.py [--version 1.2.3]

PyInstaller bundles Python, the overlay, its data and only the Qt modules the overlay uses (Core, Gui, Widgets,
Svg). What PySide6 ships beyond that (Qt Quick, QML, the designer tools, a 20 MB software-OpenGL DLL, translations,
SSL) is left out, which takes the folder from about 200 MB to under 80 MB (31 MB zipped). The GitHub release
workflow (.github/workflows/release.yml) runs this on a tag."""

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build mq-overlay.exe and the release zip")
    parser.add_argument("--version", default="", help="goes into the zip's name (mq-overlay-<version>-win.zip)")
    args = parser.parse_args()
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
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "mq-overlay", "--windowed",
           "--distpath", str(dist), "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
           "--paths", str(ROOT / "src"), "--add-data", f"{ROOT / 'data'}{';' if sys.platform == 'win32' else ':'}mq_overlay/data",
           "--icon", str(icon)]
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
