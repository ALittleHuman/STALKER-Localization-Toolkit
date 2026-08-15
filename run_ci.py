#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local CI / regression entry.

Runs automated checks that do not require a display:
    * compileall
    * import all modules
    * DB pack/unpack roundtrip for every format
    * cross_validate.py (only when the external converter.exe exists)
    * cleanup: __pycache__, temp/*, cross_validate_out

Usage:
    python run_ci.py            # full local regression
    python run_ci.py --fast     # skip cross_validate
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def cleanup():
    """Remove generated test artifacts and caches."""
    for name in ("cross_validate_out",):
        p = os.path.join(HERE, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    for dp, dn, fn in os.walk(HERE):
        if "__pycache__" in dn:
            shutil.rmtree(os.path.join(dp, "__pycache__"), ignore_errors=True)
    temp_dir = os.path.join(HERE, "temp")
    if os.path.isdir(temp_dir):
        for name in os.listdir(temp_dir):
            p = os.path.join(temp_dir, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except Exception:
                    pass
    logs_dir = os.path.join(HERE, "logs")
    if os.path.isdir(logs_dir):
        for name in os.listdir(logs_dir):
            if name == ".gitkeep":
                continue
            p = os.path.join(logs_dir, name)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except Exception:
                pass


def setup_paths():
    for sub in ("file_system", "font_pack", "plugins"):
        p = os.path.join(HERE, sub)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    sys.path.insert(0, HERE)


def step(name):
    print(f"\n=== {name} ===")


def main():
    fast = "--fast" in sys.argv
    setup_paths()
    ok = True

    step("compileall")
    import py_compile
    failed = []
    for dp, dn, fn in os.walk(HERE):
        if "__pycache__" in dp or "backup" in dp or "temp" in dp or ".git" in dp:
            continue
        for f in fn:
            if f.endswith(".py"):
                p = os.path.join(dp, f)
                try:
                    py_compile.compile(p, doraise=True)
                except Exception as e:
                    failed.append((p, e))
    if failed:
        for p, e in failed:
            print(f"  FAIL {p}: {e}")
        ok = False
    else:
        print("  OK")

    step("import modules")
    import importlib
    mods = [
        "toolkit",
        "file_system.stalker_fs",
        "plugins.nlc_sqfs",
        "stalker_toolkit",
    ]
    for m in mods:
        try:
            importlib.import_module(m)
            print(f"  OK {m}")
        except ModuleNotFoundError as e:
            # nlc_sqfs is a closed-source plugin kept out of the repository.
            if m == "plugins.nlc_sqfs" and not os.path.isfile(
                os.path.join(HERE, "plugins", "nlc_sqfs.py")
            ):
                print(f"  SKIP {m} (closed-source plugin not in repository)")
            else:
                print(f"  FAIL {m}: {e}")
                ok = False
        except Exception as e:
            print(f"  FAIL {m}: {e}")
            ok = False

    step("DB roundtrip all formats")
    try:
        import stalker_fs
        files = [
            ("a.txt", b"hello world", False),
            ("dir/b.bin", bytes(range(256)) * 10, False),
            ("dir/empty.bin", b"", False),
        ]
        for fmt in stalker_fs.FORMATS:
            db = stalker_fs.pack_db(files, fmt)
            entries = stalker_fs.unpack_db(db, fmt)
            assert entries, f"{fmt}: no entries"
            data_map = {f[0]: f[1] for f in files}
            for e in entries:
                if e["is_dir"]:
                    continue
                data = stalker_fs.extract_file(db, e)
                if data != data_map.get(e["path"]):
                    print(f"  FAIL {fmt} {e['path']} data mismatch")
                    ok = False
                    break
            else:
                print(f"  OK {fmt}")
    except Exception as e:
        print(f"  FAIL roundtrip: {e}")
        ok = False

    if not fast:
        step("cross_validate (external converter)")
        cv_py = os.path.join(HERE, "cross_validate.py")
        cv_exe = r"E:\Software\Games\STALKER\Localization\Tools\Tool\Stalker_Unpacker_2017\converter.exe"
        if os.path.isfile(cv_py) and os.path.isfile(cv_exe):
            proc = subprocess.run([sys.executable, cv_py], cwd=HERE,
                                  capture_output=True, text=True, timeout=600)
            if proc.returncode == 0:
                print("  OK")
            else:
                print("  FAIL")
                print(proc.stdout[-2000:])
                print(proc.stderr[-2000:])
                ok = False
        else:
            print("  SKIP (converter.exe not found)")

    cleanup()
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
