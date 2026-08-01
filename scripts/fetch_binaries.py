#!/usr/bin/env python3

from __future__ import annotations

import gzip
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


FFMPEG_TAG = "b6.1.1"       # github.com/eugeneware/ffmpeg-static
GIFSKI_TAG = "1.34.0"       # github.com/ImageOptim/gifski

FFMPEG_BASE = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{FFMPEG_TAG}"
GIFSKI_URL = (
    f"https://github.com/ImageOptim/gifski/releases/download/{GIFSKI_TAG}"
    f"/gifski-{GIFSKI_TAG}.tar.xz"
)

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"



def detect() -> tuple[str, str]:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")

    if sys.platform == "darwin":
        return ("darwin-arm64" if arm else "darwin-x64"), "mac"
    if sys.platform.startswith("linux"):
        if arm:
            sys.exit("Linux arm64: no prebuilt gifski binary, use: cargo install gifski")
        return "linux-x64", "linux"
    if sys.platform == "win32":
        return "win32-x64", "win"
    sys.exit(f"Unsupported platform: {sys.platform}")



def download(url: str, dest: Path) -> None:
    print(f"  downloading {url}", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_ffmpeg(slug: str, exe_suffix: str) -> None:
    for name in ("ffmpeg", "ffprobe"):
        target = BIN / f"{name}{exe_suffix}"
        if target.exists():
            print(f"  skip {target.name} (already present)", flush=True)
            continue
        gz = BIN / f"{name}.gz"
        download(f"{FFMPEG_BASE}/{name}-{slug}.gz", gz)
        with gzip.open(gz, "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        gz.unlink()
        make_executable(target)
        print(f"  ok   {target.name}", flush=True)


def fetch_gifski(subdir: str, exe_suffix: str) -> None:
    target = BIN / f"gifski{exe_suffix}"
    if target.exists():
        print(f"  skip {target.name} (already present)", flush=True)
        return
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "gifski.tar.xz"
        download(GIFSKI_URL, archive)
        with tarfile.open(archive, "r:xz") as tar:
            member = f"{subdir}/gifski{exe_suffix}"
            src = tar.extractfile(member)
            if src is None:
                sys.exit(f"gifski archive has no {member}")
            BIN.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    make_executable(target)
    print(f"  ok   {target.name}", flush=True)


def main() -> None:
    slug, gifski_dir = detect()
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    print(f"Platform: {slug}", flush=True)
    BIN.mkdir(parents=True, exist_ok=True)
    fetch_ffmpeg(slug, exe_suffix)
    fetch_gifski(gifski_dir, exe_suffix)
    print(f"\nDone. Binaries in {BIN}", flush=True)


if __name__ == "__main__":
    main()
