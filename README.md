# GIF Forge

Create and compress GIF animations through a graphical interface, with preview.

Converts video files or PNG image sequences to GIF. Uses `ffmpeg` for frame extraction
and `gifski` for palette generation and encoding. Both are bundled.

## Download

Grab a build from [Releases](../../releases):

|               File               | Platform |
|-------------------------------|---------------------------------------|
| `GifForge-windows-x86_64.zip` |           Windows 10/11               |
| `GifForge-macos-arm64.zip`    |            macOS, Apple Silicon       |
| `GifForge-macos-x86_64.zip`   |               macOS, Intel            |
| `GifForge-linux-x86_64.tar.gz`| Ubuntu 22.04+ and other glibc distros |

### Windows

1. Extract the archive.
2. Run `GifForge.exe`.
3. On the SmartScreen warning: **More info** → **Run anyway**. The build is unsigned.

### macOS

1. Extract the archive.
2. Move `GifForge.app` to Applications.
3. Right-click the app → **Open** → **Open**. Or run:
   `xattr -dr com.apple.quarantine /Applications/GifForge.app`

### Linux

```bash
tar -xzf GifForge-linux-x86_64.tar.gz
./GifForge/GifForge
```

If Qt fails with an `xcb` error:

```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1
```

## Run from source

```bash
git clone https://github.com/LordCabbage/gif-forge
cd gif-forge
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/fetch_binaries.py   # downloads ffmpeg, ffprobe, gifski into ./bin/
python gif_forge.py
```

`bin/` is gitignored. `tool_path()` checks `./bin/` first, then `PATH` — if the three
tools are already installed system-wide, skip the fetch step.

## Build

```bash
pip install pyinstaller
python scripts/fetch_binaries.py
pyinstaller gif_forge.spec --noconfirm
```


```bash
git tag v1.0.0
git push origin v1.0.0
```

## License

AGPL-3.0.

`gifski` is AGPL-3.0 (its author offers commercial licensing separately). Since its
binary ships inside every build, the distribution as a whole is AGPL-3.0.

Static ffmpeg builds come from
[eugeneware/ffmpeg-static](https://github.com/eugeneware/ffmpeg-static) (GPL).
