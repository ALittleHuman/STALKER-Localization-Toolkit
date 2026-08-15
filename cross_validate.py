# -*- coding: utf-8 -*-
"""
Cross-validation: Toolkit pack/unpack vs converter.exe (cv).

Formats under test: 11xx, 2215, 2945.

Direction 1 (main): Toolkit packs a DB -> cv unpacks it -> bytes must match
                    the original files exactly.
Direction 2 (same DB): Toolkit unpacks its own DB -> bytes must also match.

For 11xx we additionally build a DB whose file payloads are LZHUF-compressed
(this exercises the 11xx LZHUF decode path fixed in stalker_fs.py), then both
cv and Toolkit unpack it and must match the original files.

cv (converter.exe) does NOT support packing 11xx / 2215 / 2945
(see db_tools.cxx: db_packer rejects -11xx / -2215 / -2945), so
cv-pack -> Toolkit-unpack is not possible for these three formats.

Usage:
    python cross_validate.py
"""
import os
import sys
import struct
import shutil
import hashlib
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "file_system"))
import stalker_fs

CV = r"E:\Software\Games\STALKER\Localization\Tools\Tool\Stalker_Unpacker_2017\converter.exe"
OUT = os.path.join(HERE, "cross_validate_out")

# Relative to STALKER_Toolkit root; ASCII paths only for cv compatibility.
SOURCE_FILES = [
    "README.md",
    "video_ogm_tool.cfg.json",
    os.path.join("plugins", "nlc_sqfs.py"),
    "app_icon.ico",
]

FMT_FLAGS = [
    ("11xx", "-11xx"),
    ("2215", "-2215"),
    ("2945", "-2945"),
]


def log(msg):
    print(f"[xval] {msg}")


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def load_source_files():
    """Return [(rel_path_with_slash, data_bytes, is_dir)] for the chosen files."""
    files = []
    for rel in SOURCE_FILES:
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            log(f"SKIP missing source file: {rel}")
            continue
        with open(p, "rb") as f:
            data = f.read()
        files.append((rel.replace("\\", "/"), data, False))
    if len(files) < 2:
        raise SystemExit("not enough source files; check SOURCE_FILES")
    return files

SAMPLE_DIR = os.path.join(HERE, "cross_validate_samples")


def generate_sample_files():
    """Generate a wider set of files (empty, tiny, text, random, deep path)."""
    import random
    ensure_dir(SAMPLE_DIR)
    samples = []

    def add(rel, data):
        p = os.path.join(SAMPLE_DIR, rel.replace("/", os.sep))
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        samples.append((rel.replace("\\", "/"), data, False))

    add("sample_empty.bin", b"")
    add("sample_one_byte.bin", b"\x00")
    add("sample_text.txt", ("STALKER cross-validation line\n" * 500).encode("utf-8"))
    add("sample_random_1k.bin", bytes(random.randrange(256) for _ in range(1024)))
    add("sample_random_512k.bin", bytes(random.randrange(256) for _ in range(512 * 1024)))
    add("deep/a/b/c/sample_deep.bin", b"deep path payload")
    return samples


def write_source_tree(files, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    ensure_dir(dst)
    for rel, data, _ in files:
        p = os.path.join(dst, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(p) else None
        with open(p, "wb") as f:
            f.write(data)


def dir_snapshot(root):
    """Return {rel_path_normalized: sha256_hex} for every file under root."""
    snap = {}
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            with open(p, "rb") as f:
                snap[rel] = hashlib.sha256(f.read()).hexdigest()
    return snap


def compare_trees(expected_root, actual_root):
    exp = dir_snapshot(expected_root)
    act = dir_snapshot(actual_root)
    ok = True
    if exp.keys() != act.keys():
        missing = sorted(exp.keys() - act.keys())
        extra = sorted(act.keys() - exp.keys())
        log(f"  FAIL: file set differs; missing={missing[:5]} extra={extra[:5]}")
        ok = False
    for rel, digest in exp.items():
        if rel not in act:
            continue
        if act[rel] != digest:
            log(f"  FAIL: content differs: {rel}")
            ok = False
    return ok


def toolkit_pack(files, fmt):
    return stalker_fs.pack_db(files, fmt)


def toolkit_unpack(db, fmt, dst):
    ensure_dir(dst)
    entries = stalker_fs.unpack_db(db, fmt)
    count = 0
    for e in entries:
        if e.get("is_dir"):
            continue
        data = stalker_fs.extract_file(db, e)
        if data is None:
            continue
        rel = e["path"].replace("\\", "/")
        p = os.path.join(dst, rel.replace("/", os.sep))
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        count += 1
    return count


def cv_unpack(db_path, fmt_flag, dst):
    ensure_dir(dst)
    r = subprocess.run(
        [CV, "-unpack", fmt_flag, db_path, "-dir", dst],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        log(f"  cv unpack failed: {r.returncode}")
        log(f"  stdout: {r.stdout[:400]}")
        log(f"  stderr: {r.stderr[:400]}")
        return False
    return True


def build_11xx_lzhuf_db(files):
    """Manually build an 11xx DB with LZHUF-compressed file payloads.
    Entry layout: name\\0 + uncompressed(4) + offset(4) + size(4).
    File payload: lzhuf.encode(content) (textsize header + bitstream)."""
    header = bytearray()
    data = bytearray()
    for rel, content, is_dir in files:
        if is_dir:
            continue
        comp = stalker_fs.lzhuf.encode(content)
        path = rel.replace("/", "\\")
        header += path.encode("cp1251") + b"\x00"
        header += struct.pack("<III", 0, 8 + len(data), len(comp))  # uncompressed=0
        data += comp
    comp_header = stalker_fs.lzhuf.encode(bytes(header))
    db = struct.pack("<II", 0, len(data)) + bytes(data)
    db += struct.pack("<I", 0x80000001) + struct.pack("<I", len(comp_header)) + comp_header
    return bytes(db)


def run_direction(files, fmt, flag, lzhuf_payload=False):
    if lzhuf_payload:
        # cv xr_lzhuf::decompress on empty payload is risky; test empty file
        # only in the plain 11xx direction.
        files = [f for f in files if f[1]]
    fmt_dir = os.path.join(OUT, fmt)
    ensure_dir(fmt_dir)
    src_tree = os.path.join(fmt_dir, "src")
    write_source_tree(files, src_tree)

    # 1. Toolkit pack
    if lzhuf_payload:
        db = build_11xx_lzhuf_db(files)
        db_name = "toolkit_11xx_lzhuf.db"
    else:
        db = toolkit_pack(files, fmt)
        db_name = f"toolkit_{fmt}.db"
    db_path = os.path.join(fmt_dir, db_name)
    with open(db_path, "wb") as f:
        f.write(db)
    log(f"[{fmt}] packed {db_name}: {len(db)} bytes")

    # 2. cv unpack
    cv_out = os.path.join(fmt_dir, "cv_out")
    if os.path.exists(cv_out):
        shutil.rmtree(cv_out)
    if not cv_unpack(db_path, flag, cv_out):
        return False

    # 3. Toolkit unpack its own DB
    tk_out = os.path.join(fmt_dir, "tk_out")
    if os.path.exists(tk_out):
        shutil.rmtree(tk_out)
    n = toolkit_unpack(db, fmt, tk_out)
    log(f"[{fmt}] toolkit unpacked {n} files")

    # 4. Compare: source == cv_out == tk_out
    ok_cv = compare_trees(src_tree, cv_out)
    ok_tk = compare_trees(src_tree, tk_out)
    log(f"[{fmt}] source vs cv_out : {'PASS' if ok_cv else 'FAIL'}")
    log(f"[{fmt}] source vs tk_out : {'PASS' if ok_tk else 'FAIL'}")
    return ok_cv and ok_tk


def main():
    if not os.path.isfile(CV):
        raise SystemExit(f"converter.exe not found: {CV}")
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    ensure_dir(OUT)

    files = load_source_files() + generate_sample_files()
    log(f"source files ({len(files)}): {[f[0] for f in files]}")

    all_ok = True
    for fmt, flag in FMT_FLAGS:
        log(f"=== {fmt} : Toolkit pack -> cv unpack -> Toolkit unpack ===")
        ok = run_direction(files, fmt, flag)
        all_ok = all_ok and ok

    log("=== 11xx LZHUF payload: Toolkit-built DB -> cv + Toolkit unpack ===")
    ok = run_direction(files, "11xx", "-11xx", lzhuf_payload=True)
    all_ok = all_ok and ok

    print()
    if all_ok:
        print("ALL CROSS-VALIDATION PASSED")
    else:
        print("CROSS-VALIDATION FAILED; see messages above")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
