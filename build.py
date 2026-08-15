# -*- coding: utf-8 -*-
"""
Build STALKER Localization Toolkit with PyInstaller (onedir).

Usage:
    python build.py              # build to builds/build001
    python build.py --out DIR    # build to a custom directory

The build excludes the closed-source plugins/nlc_sqfs.py from the bundle.
ffmpeg.exe / ffprobe.exe are copied next to the exe when present locally.
"""
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# App constants come from the toolkit itself.
sys.path.insert(0, BASE)
from toolkit import APP_NAME, APP_VERSION  # noqa: E402

BUILDS_DIR = os.path.join(BASE, "builds")
DEFAULT_OUT = os.path.join(BUILDS_DIR, "build001")


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller installed.")


def write_version_info(path):
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({APP_VERSION.replace('.', ', ')}, 0),
    prodvers=({APP_VERSION.replace('.', ', ')}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'ALittleHuman'),
         StringStruct('FileDescription', '{APP_NAME}'),
         StringStruct('FileVersion', '{APP_VERSION}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', 'ALittleHuman'),
         StringStruct('OriginalFilename', '{APP_NAME}.exe'),
         StringStruct('ProductName', '{APP_NAME}'),
         StringStruct('ProductVersion', '{APP_VERSION}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(out_dir):
    ensure_pyinstaller()

    # Kill a stale running instance if it is locking previous build output.
    exe_name = f"{APP_NAME}.exe"
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/IM", exe_name],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    # Remove caches before bundling so no .pyc of the closed-source
    # plugin can leak into the build.
    for dp, dn, fn in os.walk(BASE):
        if "__pycache__" in dn:
            shutil.rmtree(os.path.join(dp, "__pycache__"), ignore_errors=True)

    temp_dir = os.path.join(BASE, "temp", "build")
    work_dir = os.path.join(temp_dir, "work")
    spec_dir = os.path.join(temp_dir, "spec")
    for d in (work_dir, spec_dir):
        os.makedirs(d, exist_ok=True)

    version_info = os.path.join(temp_dir, "version_info.txt")
    write_version_info(version_info)

    nlc_src = os.path.join(BASE, "plugins", "nlc_sqfs.py")
    nlc_tmp = os.path.join(BASE, "nlc_sqfs.py.build_backup")
    nlc_backed_up = False
    if os.path.isfile(nlc_src):
        os.replace(nlc_src, nlc_tmp)
        nlc_backed_up = True
        print("Temporarily moved plugins/nlc_sqfs.py out of the build.")

    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--onedir", "--windowed",
            "--name", APP_NAME,
            "--icon", os.path.join(BASE, "app_icon.ico"),
            "--version-file", version_info,
            "--paths", os.path.join(BASE, "file_system"),
            "--paths", os.path.join(BASE, "font_pack"),
            "--paths", os.path.join(BASE, "plugins"),
            "--add-data", f"{os.path.join(BASE, 'apps')};apps",
            "--add-data", f"{os.path.join(BASE, 'file_system')};file_system",
            "--add-data", f"{os.path.join(BASE, 'font_pack')};font_pack",
            "--add-data", f"{os.path.join(BASE, 'deps')};deps",
            "--add-data", f"{os.path.join(BASE, 'app_icon.ico')};.",
            "--distpath", out_dir,
            "--workpath", work_dir,
            "--specpath", spec_dir,
            os.path.join(BASE, "stalker_toolkit.py"),
        ]
        print("Running PyInstaller...")
        subprocess.check_call(cmd, cwd=BASE)
    finally:
        if nlc_backed_up and os.path.isfile(nlc_tmp):
            os.replace(nlc_tmp, nlc_src)
            print("Restored plugins/nlc_sqfs.py.")
        shutil.rmtree(temp_dir, ignore_errors=True)

    bundle_dir = os.path.join(out_dir, APP_NAME)
    if not os.path.isdir(bundle_dir):
        raise RuntimeError(f"Build output not found: {bundle_dir}")

    # Remove git placeholder files and any __pycache__ from the bundle.
    for dp, dn, fn in os.walk(bundle_dir):
        for f in fn:
            if f == ".gitkeep":
                os.unlink(os.path.join(dp, f))
        for d in dn:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dp, d), ignore_errors=True)

    # Runtime-writable directories live next to the exe, not inside _internal.
    for sub in ("plugins", "logs"):
        d = os.path.join(bundle_dir, sub)
        os.makedirs(d, exist_ok=True)
        print(f"Created {d}")

    # Keep a resident runtime.log in logs/ so the directory is never empty.
    runtime_log = os.path.join(bundle_dir, "logs", "runtime.log")
    if not os.path.isfile(runtime_log):
        with open(runtime_log, "w", encoding="utf-8") as f:
            f.write("")

    for exe in ("ffmpeg.exe", "ffprobe.exe"):
        src = os.path.join(BASE, exe)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(bundle_dir, exe))
            print(f"Copied {exe} -> {bundle_dir}")

    exe_path = os.path.join(bundle_dir, f"{APP_NAME}.exe")
    if not os.path.isfile(exe_path):
        raise RuntimeError(f"exe not found: {exe_path}")

    print("Build complete.")
    print("Output:", bundle_dir)
    print("Exe:", exe_path)
    print("Note: build excludes plugins/nlc_sqfs.py (closed source).")
    return bundle_dir


def main():
    out = DEFAULT_OUT
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 >= len(sys.argv):
            raise SystemExit("--out requires a directory argument")
        out = os.path.abspath(sys.argv[i + 1])
    build(out)


if __name__ == "__main__":
    main()
