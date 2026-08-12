
"""
GIF Forge
Copyright (C) 2026 Cabbage

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

Per GPL-3.0 sections 4 and 5, copies and modified versions that are
distributed to others must retain the copyright and attribution
notices, including the one displayed in this program's interface.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog,
    QGraphicsOpacityEffect, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)



WIDTH_PRESETS = [
    ("Original", 0),
    ("1920", 1920),
    ("1280", 1280),
    ("960", 960),
    ("720", 720),
    ("480", 480),
    ("Custom…", -1),
]

FPS_PRESETS = [
    ("Original", 0.0),
    ("30", 30.0),
    ("24", 24.0),
    ("20", 20.0),
    ("15", 15.0),
    ("12", 12.0),
    ("10", 10.0),
    ("Custom…", -1.0),
]



IS_WINDOWS = sys.platform == "win32"
_EXE = ".exe" if IS_WINDOWS else ""

# CREATE_NO_WINDOW — чтобы на Windows не мигало чёрное окно консоли
_NO_WINDOW = {"creationflags": 0x08000000} if IS_WINDOWS else {}

# Общие kwargs для всех дочерних процессов: не падать на не-UTF8 выводе ffmpeg
_TEXT_IO = {"encoding": "utf-8", "errors": "replace"}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def tool_path(name: str) -> Optional[str]:
    local = _app_dir() / "bin" / (name + _EXE)
    if local.is_file():
        # PyInstaller иногда теряет бит +x при распаковке datas — чиним на месте
        if not IS_WINDOWS and not os.access(local, os.X_OK):
            try:
                local.chmod(local.stat().st_mode | 0o755)
            except OSError:
                pass
        return str(local)
    return shutil.which(name)


FFMPEG = tool_path("ffmpeg")
FFPROBE = tool_path("ffprobe")
GIFSKI = tool_path("gifski")


def check_tools() -> dict[str, Optional[str]]:
    return {"ffmpeg": FFMPEG, "ffprobe": FFPROBE, "gifski": GIFSKI}


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float

    @property
    def total_frames(self) -> int:
        return int(round(self.fps * self.duration))


def probe_video(path: str) -> Optional[VideoInfo]:
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True, **_TEXT_IO, **_NO_WINDOW,
        )
        lines = [ln for ln in r.stdout.strip().split("\n") if ln]
        num, den = lines[2].split("/")
        return VideoInfo(
            width=int(lines[0]),
            height=int(lines[1]),
            fps=float(num) / float(den) if float(den) else float(num),
            duration=float(lines[3]),
        )
    except Exception:
        return None


def probe_image_size(path: str) -> Optional[tuple[int, int]]:
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", path],
            capture_output=True, text=True, check=True, **_TEXT_IO, **_NO_WINDOW,
        )
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return None


@dataclass
class ConversionSettings:
    output_path: str
    width: int          # 0 = original
    fps: float          # 0 = original
    quality: int        # 1..100
    video_path: Optional[str] = None
    image_paths: List[str] = field(default_factory=list)


class ConversionWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, settings: ConversionSettings, video_info: Optional[VideoInfo]):
        super().__init__()
        self.settings = settings
        self.video_info = video_info
        self._cancelled = False
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_tail: deque[str] = deque(maxlen=8)

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self):
        try:
            if self.settings.video_path:
                self._convert_video()
            else:
                self._convert_images()
            if not self._cancelled:
                self.finished.emit(self.settings.output_path)
        except Exception as e:
            self.error.emit(str(e))

    def _convert_video(self):
        s = self.settings
        assert self.video_info is not None

        fps = s.fps if s.fps > 0 else self.video_info.fps

        with tempfile.TemporaryDirectory(prefix="gif_forge_") as tmpdir:
            vf_parts = [f"fps={fps:.6f}"]
            if s.width > 0:
                vf_parts.append(f"scale={s.width}:-2:flags=lanczos")
            vf = ",".join(vf_parts)

            pattern = os.path.join(tmpdir, "f_%05d.png")
            cmd = [FFMPEG, "-y", "-i", s.video_path, "-vf", vf, pattern]
            est = int(round(fps * self.video_info.duration))
            self._run_ffmpeg(cmd, est)
            if self._cancelled:
                return

            frames = sorted(Path(tmpdir).glob("f_*.png"))
            if not frames:
                raise RuntimeError("ffmpeg produced no frames")

            self.progress.emit(50, "Assembling GIF…")
            actual_w = probe_image_size(str(frames[0]))[0]
            cmd = [
                GIFSKI, "-o", s.output_path,
                "--fps", f"{fps:.3f}",
                "--quality", str(s.quality),
                "--width", str(actual_w),
                *[str(f) for f in frames],
            ]
            self._run_gifski(cmd, len(frames), base_percent=50)

    def _convert_images(self):
        s = self.settings
        if not s.image_paths:
            raise ValueError("No images selected")

        fps = s.fps if s.fps > 0 else 15.0
        first_size = probe_image_size(s.image_paths[0])
        if first_size is None:
            raise RuntimeError(f"Could not read image: {s.image_paths[0]}")
        target_w = s.width if s.width > 0 else first_size[0]

        self.progress.emit(0, "Encoding GIF…")
        cmd = [
            GIFSKI, "-o", s.output_path,
            "--fps", f"{fps:.3f}",
            "--quality", str(s.quality),
            "--no-sort",
            "--width", str(target_w),
            *s.image_paths,
        ]
        self._run_gifski(cmd, len(s.image_paths), base_percent=0)

    def _run_ffmpeg(self, cmd: list[str], est_frames: int):
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, **_TEXT_IO, **_NO_WINDOW,
        )
        for line in self._proc.stdout:
            if self._cancelled:
                self._proc.terminate()
                return
            line = line.rstrip()
            self._stderr_tail.append(line)
            m = re.search(r"frame=\s*(\d+)", line)
            if m and est_frames:
                pct = min(49, int(50 * int(m.group(1)) / max(est_frames, 1)))
                self.progress.emit(pct, f"Extracting frame {m.group(1)}/{est_frames}")
        self._proc.wait()
        if self._proc.returncode != 0 and not self._cancelled:
            tail = "\n".join(self._stderr_tail)
            raise RuntimeError(f"ffmpeg failed (exit {self._proc.returncode}).\n\n{tail}")

    def _run_gifski(self, cmd: list[str], total: int, base_percent: int):
        span = 100 - base_percent
        self._stderr_tail.clear()
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, **_TEXT_IO, **_NO_WINDOW,
        )
        for line in self._proc.stdout:
            if self._cancelled:
                self._proc.terminate()
                return
            line = line.rstrip()
            self._stderr_tail.append(line)
            m = re.search(r"Frame\s+(\d+)\s*/\s*(\d+)", line)
            if m:
                cur, tot = int(m.group(1)), int(m.group(2))
                pct = base_percent + int(span * cur / max(tot, 1))
                self.progress.emit(pct, f"Encoding frame {cur}/{tot}")
        self._proc.wait()
        if self._proc.returncode != 0 and not self._cancelled:
            tail = "\n".join(self._stderr_tail)
            raise RuntimeError(f"gifski failed (exit {self._proc.returncode}).\n\n{tail}")
        self.progress.emit(100, "Done")




class GifForge(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GIF Forge")
        self.resize(900, 780)

        self._video_info: Optional[VideoInfo] = None
        self._output_path: Optional[str] = None
        self._default_save_name: str = "output.gif"
        self._movie: Optional[QMovie] = None
        self._worker: Optional[ConversionWorker] = None
        self._thread: Optional[QThread] = None
        self._temp_dir = tempfile.TemporaryDirectory(prefix="gif_forge_out_")
        self._temp_counter = 0

        self._build_ui()
        self._verify_signature()
        self._check_dependencies()


    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_video_tab(), "Video → GIF")
        self.tabs.addTab(self._build_images_tab(), "Images → GIF")
        root.addWidget(self.tabs)

        root.addWidget(self._build_settings())

        row = QHBoxLayout()
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setMinimumHeight(40)
        self.convert_btn.clicked.connect(self._on_convert)
        row.addWidget(self.convert_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self.cancel_btn)

        self.progress = QProgressBar()
        row.addWidget(self.progress, stretch=1)

        self.status = QLabel("Ready")
        self.status.setMinimumWidth(180)
        row.addWidget(self.status)
        root.addLayout(row)

        root.addWidget(self._build_preview(), stretch=1)

    def _build_video_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("Select a video file (.mp4, .mov, .mkv, .webm)")
        self.video_edit.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_video)
        row.addWidget(self.video_edit, stretch=1)
        row.addWidget(browse)
        lay.addLayout(row)

        self.video_info_label = QLabel("No video loaded")
        self.video_info_label.setStyleSheet("color: #888; padding: 6px;")
        lay.addWidget(self.video_info_label)
        return w

    def _build_images_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        row = QHBoxLayout()
        b1 = QPushButton("Add PNGs…");  b1.clicked.connect(self._add_image_files)
        b2 = QPushButton("Add folder…"); b2.clicked.connect(self._add_image_folder)
        b3 = QPushButton("Remove selected"); b3.clicked.connect(self._remove_selected_images)
        b4 = QPushButton("Clear"); b4.clicked.connect(lambda: self.image_list.clear())
        for b in (b1, b2, b3, b4):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.image_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.image_list.setAlternatingRowColors(True)
        lay.addWidget(self.image_list, stretch=1)

        hint = QLabel("PNG only. Drag rows to reorder — list order = frame order.")
        hint.setStyleSheet("color: #888; padding: 4px;")
        lay.addWidget(hint)
        return w

    def _build_settings(self) -> QWidget:
        g = QGroupBox("Settings")
        grid = QGridLayout(g)

        grid.addWidget(QLabel("Width:"), 0, 0)
        self.width_combo = QComboBox()
        for label, _ in WIDTH_PRESETS:
            self.width_combo.addItem(label)
        self.width_combo.currentIndexChanged.connect(self._on_width_changed)
        grid.addWidget(self.width_combo, 0, 1)
        self.width_custom = QSpinBox()
        self.width_custom.setRange(16, 7680); self.width_custom.setValue(720)
        self.width_custom.setSuffix(" px"); self.width_custom.setEnabled(False)
        grid.addWidget(self.width_custom, 0, 2)

        grid.addWidget(QLabel("FPS:"), 1, 0)
        self.fps_combo = QComboBox()
        for label, _ in FPS_PRESETS:
            self.fps_combo.addItem(label)
        self.fps_combo.currentIndexChanged.connect(self._on_fps_changed)
        grid.addWidget(self.fps_combo, 1, 1)
        self.fps_custom = QSpinBox()
        self.fps_custom.setRange(1, 60); self.fps_custom.setValue(15)
        self.fps_custom.setSuffix(" fps"); self.fps_custom.setEnabled(False)
        grid.addWidget(self.fps_custom, 1, 2)

        grid.addWidget(QLabel("Quality:"), 2, 0)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100); self.quality.setValue(90)
        self.quality.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))
        grid.addWidget(self.quality, 2, 1)
        self.quality_label = QLabel("90"); self.quality_label.setMinimumWidth(30)
        grid.addWidget(self.quality_label, 2, 2)

        grid.setColumnStretch(1, 1)
        return g

    def _build_preview(self) -> QWidget:
        g = QGroupBox("Preview")
        lay = QVBoxLayout(g)
        self.preview = QLabel("No preview yet")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "background: #1a1a1a; color: #666; min-height: 320px; border-radius: 4px;"
        )
        lay.addWidget(self.preview, stretch=1)

        self.preview_info = QLabel("")
        self.preview_info.setStyleSheet("color: #888; padding: 4px;")
        self.preview_info.setWordWrap(True)
        lay.addWidget(self.preview_info)

        row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        row.addWidget(self.save_btn)

        self.open_folder_btn = QPushButton("Show in folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        row.addWidget(self.open_folder_btn)
        row.addStretch()

        signature = QLabel("created by Cabbage to VJ")
        signature.setStyleSheet("font-size: 15px; padding-right: 4px;")
        fade = QGraphicsOpacityEffect(signature)
        fade.setOpacity(0.80)
        signature.setGraphicsEffect(fade)
        row.addWidget(signature)

        lay.addLayout(row)
        return g

    def _verify_signature(self):
        """Refuses to run if the attribution label was removed or altered."""
        expected_text = "created by Cabbage to VJ"
        expected_opacity = 0.80
        found = False
        for label in self.findChildren(QLabel):
            if label.text() == expected_text:
                effect = label.graphicsEffect()
                if isinstance(effect, QGraphicsOpacityEffect) and abs(effect.opacity() - expected_opacity) < 0.01:
                    found = True
                    break
        if not found:
            QMessageBox.critical(
                self,
                "Integrity check failed",
                "This build has been modified: required attribution was removed.\n"
                "GifForge will not run without it."
            )
            sys.exit(1)

    def _check_dependencies(self):
        missing = [k for k, v in check_tools().items() if not v]
        if not missing:
            return
        QMessageBox.warning(
            self, "Missing tools",
            "Could not find: " + ", ".join(missing) + "\n\n"
            "If you are running a release build, the download may be corrupted — "
            "please re-download it.\n\n"
            "If you are running from source, either put the binaries next to the "
            "script in ./bin/ (python scripts/fetch_binaries.py) or install them "
            "system-wide:\n"
            "  macOS:   brew install ffmpeg gifski\n"
            "  Ubuntu:  sudo apt install ffmpeg && cargo install gifski\n"
            "  Windows: winget install Gyan.FFmpeg gifski"
        )


    def _on_width_changed(self, idx: int):
        self.width_custom.setEnabled(WIDTH_PRESETS[idx][1] == -1)

    def _on_fps_changed(self, idx: int):
        self.fps_custom.setEnabled(FPS_PRESETS[idx][1] == -1)

    def _chosen_width(self) -> int:
        _, val = WIDTH_PRESETS[self.width_combo.currentIndex()]
        return self.width_custom.value() if val == -1 else val

    def _chosen_fps(self) -> float:
        _, val = FPS_PRESETS[self.fps_combo.currentIndex()]
        return float(self.fps_custom.value()) if val == -1 else val


    def _pick_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select video",
            filter="Video (*.mp4 *.mov *.mkv *.webm *.avi *.m4v);;All files (*)",
        )
        if not path:
            return
        info = probe_video(path)
        if not info:
            QMessageBox.critical(self, "Cannot read video",
                                 f"Could not read video info from:\n{path}\n\n"
                                 "Make sure it's a valid video file.")
            return
        self.video_edit.setText(path)
        self._video_info = info
        self.video_info_label.setText(
            f"<b>{info.width}×{info.height}</b> &nbsp;·&nbsp; "
            f"<b>{info.fps:.3f} fps</b> &nbsp;·&nbsp; "
            f"<b>{info.duration:.2f}s</b> &nbsp;·&nbsp; ≈ {info.total_frames} frames"
        )

    def _add_image_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select PNG images", filter="PNG (*.png)"
        )
        self._add_validated(files)

    def _add_image_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder with PNGs")
        if not folder:
            return
        all_files = sorted(p for p in Path(folder).iterdir() if p.is_file())
        pngs = [str(p) for p in all_files if p.suffix.lower() == ".png"]
        skipped = len(all_files) - len(pngs)
        if not pngs:
            QMessageBox.warning(self, "No PNGs found",
                                f"No .png files in:\n{folder}")
            return
        self._add_validated(pngs)
        if skipped:
            QMessageBox.information(
                self, "Some files skipped",
                f"Added {len(pngs)} PNG file(s). Skipped {skipped} non-PNG file(s) "
                "(only PNG is supported)."
            )

    def _add_validated(self, paths: list[str]):
        non_png = [p for p in paths if not p.lower().endswith(".png")]
        if non_png:
            QMessageBox.critical(
                self, "Unsupported format",
                "Only PNG is supported. Found non-PNG file(s):\n\n" +
                "\n".join(non_png[:5]) + ("\n…" if len(non_png) > 5 else "") +
                "\n\nConvert to PNG first."
            )
            return
        for p in paths:
            self.image_list.addItem(QListWidgetItem(p))

    def _remove_selected_images(self):
        for item in self.image_list.selectedItems():
            self.image_list.takeItem(self.image_list.row(item))


    def _on_convert(self):
        is_video = self.tabs.currentIndex() == 0

        if is_video:
            if not self._video_info or not self.video_edit.text():
                QMessageBox.warning(self, "No video", "Pick a video file first.")
                return
            default = str(Path(self.video_edit.text()).with_suffix(".gif"))
        else:
            if self.image_list.count() == 0:
                QMessageBox.warning(self, "No images", "Add at least one PNG image.")
                return
            default = "output.gif"

        if not is_video:
            paths = [self.image_list.item(i).text() for i in range(self.image_list.count())]
            sizes = {probe_image_size(p) for p in paths}
            sizes.discard(None)
            if len(sizes) > 1 and self._chosen_width() == 0:
                QMessageBox.warning(
                    self, "Mixed image sizes",
                    "Selected images have different dimensions. "
                    "Choose an explicit Width (e.g. 1280) so all frames are resized "
                    "to the same size, or use images that all share the same size."
                )
                return
        else:
            paths = []

        self._temp_counter += 1
        tmp_path = os.path.join(self._temp_dir.name, f"preview_{self._temp_counter}.gif")
        self._default_save_name = os.path.basename(default)

        settings = ConversionSettings(
            output_path=tmp_path,
            width=self._chosen_width(),
            fps=self._chosen_fps(),
            quality=self.quality.value(),
            video_path=self.video_edit.text() if is_video else None,
            image_paths=[] if is_video else paths,
        )
        self._start_worker(settings)

    def _start_worker(self, settings: ConversionSettings):
        if self._movie:
            self._movie.stop()
            self._movie = None
        self.preview.clear()
        self.preview.setText("Converting…")
        self.preview_info.setText("")
        self.open_folder_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.convert_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)

        self._thread = QThread()
        self._worker = ConversionWorker(settings, self._video_info)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
            self.status.setText("Cancelling…")

    def _on_progress(self, pct: int, text: str):
        self.progress.setValue(pct)
        self.status.setText(text)

    def _on_finished(self, output_path: str):
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status.setText("Done")
        self.progress.setValue(100)
        self._output_path = output_path
        self.open_folder_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self._show_preview(output_path)

    def _on_error(self, msg: str):
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status.setText("Error")
        self.preview.setText("Conversion failed")
        # Show short summary; full stderr context lives in `msg`
        QMessageBox.critical(self, "Conversion error", msg)


    def _show_preview(self, path: str):
        movie = QMovie(path)
        movie.jumpToFrame(0)
        orig = movie.currentPixmap().size()
        movie.setScaledSize(self._fit(orig, self._preview_target()))
        self.preview.setMovie(movie)
        movie.start()
        self._movie = movie
        size_mb = os.path.getsize(path) / (1024 * 1024)
        self.preview_info.setText(
            f"<b>{orig.width()}×{orig.height()}</b> · <b>{size_mb:.2f} MB</b> · {path}"
        )

    def _preview_target(self) -> QSize:
        s = self.preview.size()
        return QSize(s.width() - 20, s.height() - 20)

    @staticmethod
    def _fit(orig: QSize, target: QSize) -> QSize:
        if orig.width() <= 0 or orig.height() <= 0:
            return target
        ratio = min(target.width() / orig.width(), target.height() / orig.height(), 1.0)
        return QSize(int(orig.width() * ratio), int(orig.height() * ratio))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._movie and self._output_path:
            self._movie.jumpToFrame(0)
            orig = self._movie.currentPixmap().size()
            self._movie.setScaledSize(self._fit(orig, self._preview_target()))

    def _on_save(self):
        if not self._output_path or not os.path.isfile(self._output_path):
            QMessageBox.warning(self, "Nothing to save", "Convert a GIF first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GIF as", self._default_save_name, filter="GIF (*.gif)"
        )
        if not path:
            return
        if not path.lower().endswith(".gif"):
            path += ".gif"
        try:
            shutil.copyfile(self._output_path, path)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self._output_path = path
        self.status.setText("Saved")

    def _open_output_folder(self):
        if not self._output_path:
            return
        folder = os.path.dirname(self._output_path)
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", self._output_path])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", folder])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", self._output_path], **_NO_WINDOW)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GIF Forge")
    win = GifForge()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
