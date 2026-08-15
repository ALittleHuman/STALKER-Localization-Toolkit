#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check ffmpeg.exe / ffprobe.exe in the toolkit root directory.

Rules:
    * ffmpeg.exe must be a 7.x build. The ffmpeg 8.x libtheora encoder is
      buggy for STALKER OGM output, so the script will NOT install ffmpeg
      8.x or newer. A safe 7.1 ffmpeg is taken from the local
      imageio-ffmpeg package when available.
    * ffprobe.exe is only used for parsing, so any recent version is OK.
      If it is missing, the script downloads a gyan.dev archive and
      extracts ffprobe.exe only.
    * You can also supply a custom zip URL (for example a GitHub Release
      asset) with --url <ZIP_URL>.

Usage:
    python download_ffmpeg.py                # check / repair
    python download_ffmpeg.py --force        # reinstall both even if valid
    python download_ffmpeg.py --url <ZIP_URL> [--force]
"""

import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# gyan.dev latest archive, used ONLY for extracting ffprobe.exe.
DEFAULT_FFPROBE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

FFMPEG = os.path.join(HERE, "ffmpeg.exe")
FFPROBE = os.path.join(HERE, "ffprobe.exe")


def exe_valid(path):
    """Return True if path is a runnable ffmpeg/ffprobe style binary."""
    if not path or not os.path.isfile(path):
        return False
    try:
        proc = subprocess.run(
            [path, "-version"],
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode == 0
    except Exception:
        return False


def exe_version(path):
    """Return the first version string line for an exe, or ''."""
    try:
        proc = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.stdout.splitlines()[0] if proc.stdout else ""
    except Exception:
        return ""


def ffmpeg_major(path):
    """Return the major version number from ffmpeg -version, or None."""
    line = exe_version(path)
    m = re.search(r"ffmpeg version (\d+)", line)
    return int(m.group(1)) if m else None


def download(url, dest):
    """Download a URL to dest with a simple progress line."""
    print(f"downloading: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
        total = resp.length or 0
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done // 1024} / {total // 1024} KiB", end="", flush=True)
        print()


def extract_exe(zip_path, target_exe, dst):
    """Find target_exe inside a zip and copy it to dst."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith("/" + target_exe.lower())]
        if not names:
            raise FileNotFoundError(f"{target_exe} not found in archive")
        # Prefer a path containing 'bin'
        name = sorted(names, key=lambda n: ("/bin/" not in n.lower(), n))[0]
        with z.open(name) as src, open(dst, "wb") as out:
            shutil.copyfileobj(src, out)
        print(f"  extracted {target_exe} from {name}")


def ensure_ffmpeg_from_imageio(dst):
    """Copy the 7.1 ffmpeg from imageio-ffmpeg if available and valid."""
    try:
        import imageio_ffmpeg
        src = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        src = None

    if src and os.path.isfile(src) and ffmpeg_major(src) == 7:
        shutil.copyfile(src, dst)
        print(f"  copied imageio-ffmpeg 7.1 -> {dst}")
        return True

    print("  imageio-ffmpeg 7.1 is not available.")
    print("  Install it with:  python -m pip install imageio-ffmpeg")
    print("  Or place a 7.x ffmpeg.exe here manually.")
    return False


def ensure_ffmpeg_from_url(url, dst):
    """Download a custom zip and extract ffmpeg.exe, then check it is 7.x."""
    workdir = os.path.join(HERE, "temp", "ffmpeg_download")
    os.makedirs(workdir, exist_ok=True)
    zip_path = os.path.join(workdir, "ffmpeg.zip")
    try:
        download(url, zip_path)
        extract_exe(zip_path, "ffmpeg.exe", dst)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    major = ffmpeg_major(dst)
    if major != 7:
        print(f"  ERROR: ffmpeg version is {major}, but STALKER OGM needs 7.x.")
        if os.path.exists(dst):
            os.remove(dst)
        return False
    return True


def ensure_ffprobe(dst):
    """Download gyan.dev and extract only ffprobe.exe."""
    workdir = os.path.join(HERE, "temp", "ffmpeg_download")
    os.makedirs(workdir, exist_ok=True)
    zip_path = os.path.join(workdir, "ffmpeg.zip")
    try:
        download(DEFAULT_FFPROBE_URL, zip_path)
        extract_exe(zip_path, "ffprobe.exe", dst)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    force = "--force" in sys.argv
    url = None
    if "--url" in sys.argv:
        i = sys.argv.index("--url")
        url = sys.argv[i + 1]

    ffmpeg_ok = (not force) and exe_valid(FFMPEG) and ffmpeg_major(FFMPEG) == 7
    ffprobe_ok = (not force) and exe_valid(FFPROBE)

    if ffmpeg_ok and ffprobe_ok:
        print("ffmpeg.exe and ffprobe.exe are already valid.")
        print(f"  ffmpeg : {FFMPEG}")
        print(f"  ffprobe: {FFPROBE}")
        return 0

    if not ffmpeg_ok:
        print("ffmpeg.exe is missing, invalid, or not a 7.x build.")
        if url:
            ok = ensure_ffmpeg_from_url(url, FFMPEG)
        else:
            ok = ensure_ffmpeg_from_imageio(FFMPEG)
        if not ok:
            print("Could not obtain a safe 7.x ffmpeg automatically.")
            print("Fix options:")
            print("  1. python -m pip install imageio-ffmpeg")
            print("  2. python download_ffmpeg.py --url <ZIP_WITH_FFMPEG_7.X>")
            print("  3. copy ffmpeg.exe (7.x) here manually")
            return 1

    if not ffprobe_ok:
        print("ffprobe.exe is missing or invalid.")
        if url:
            workdir = os.path.join(HERE, "temp", "ffmpeg_download")
            os.makedirs(workdir, exist_ok=True)
            zip_path = os.path.join(workdir, "ffmpeg.zip")
            try:
                download(url, zip_path)
                extract_exe(zip_path, "ffprobe.exe", FFPROBE)
            except Exception as e:
                print(f"  custom zip ffprobe extraction failed: {e}")
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
        if not exe_valid(FFPROBE):
            try:
                ensure_ffprobe(FFPROBE)
            except Exception as e:
                print(f"  ffprobe download failed: {e}")
        if not exe_valid(FFPROBE):
            print("Could not obtain ffprobe.exe automatically.")
            print("Place ffprobe.exe here manually:")
            print(f"  {HERE}")
            return 1

    print("OK: ffmpeg.exe and ffprobe.exe are ready.")
    print("  " + exe_version(FFMPEG))
    print("  " + exe_version(FFPROBE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
