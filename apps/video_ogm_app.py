# -*- coding: utf-8 -*-
"""Auto-split app module."""
import os, sys, re, threading, struct, shutil, subprocess, tempfile, time, json, glob
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Set, Tuple, Union, Any, Callable
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(_BASE_DIR, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from toolkit import (
    T, color, apply_theme, apply_tk_defaults,
    dir_row, count_label, tool_header, tool_text,
    LogBox, CanvasTree, SplitPane, PluginManager,
    _make_pump, _role_of, refresh_theme, DEFAULT_ENCODINGS,
    fmt_size, read_text_file, parse_xml_texts,
    log_section, vscrollbar, drop_zone,
    _BaseTk, _HAS_DND, DND_FILES,
)

def _config_path() -> str:
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        d = os.getcwd()
    return os.path.join(d, "video_ogm_tool.cfg.json")


def _load_config() -> dict:
    cp = _config_path()
    if os.path.isfile(cp):
        try:
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(cfg: dict):
    try:
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def find_ffmpeg() -> tuple[Optional[str], Optional[str]]:
    ffmpeg_exe = None
    ffprobe_exe = None

    # ── 0. 检查 imageio-ffmpeg（7.1 的 theora 编码器无 8.x 的 bug）──
    imageio_ffmpeg_path = None
    try:
        import imageio_ffmpeg
        iexe = imageio_ffmpeg.get_ffmpeg_exe()
        if iexe and os.path.isfile(iexe):
            imageio_ffmpeg_path = iexe
    except Exception:
        pass

    # ── 1. 读取已保存的配置 ──
    cfg = _load_config()
    if cfg.get("ffmpeg") and os.path.isfile(cfg["ffmpeg"]):
        ffmpeg_exe = cfg["ffmpeg"]
    if cfg.get("ffprobe") and os.path.isfile(cfg["ffprobe"]):
        ffprobe_exe = cfg["ffprobe"]
    if ffmpeg_exe and ffprobe_exe:
        # 如果有 imageio 7.1，替换 ffmpeg（保留 ffprobe）
        if imageio_ffmpeg_path:
            ffmpeg_exe = imageio_ffmpeg_path
        return ffmpeg_exe, ffprobe_exe

    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        d = os.getcwd()
    for name in ("ffmpeg", "ffprobe"):
        p = os.path.join(d, f"{name}.exe")
        if os.path.isfile(p):
            if name == "ffmpeg":
                ffmpeg_exe = p
            else:
                ffprobe_exe = p

    search_dirs = [
        os.path.dirname(sys.executable),
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\tools\ffmpeg\bin",
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\ffmpeg\current\bin"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
    ]
    # 也搜索 E:/Software/Tools 下的 ffmpeg 目录
    try:
        import glob
        for ffdir in glob.glob(r"E:\Software\Tools\FFmpeg\*\bin"):
            search_dirs.append(ffdir)
    except Exception:
        pass
    for name in ("ffmpeg", "ffprobe"):
        if (name == "ffmpeg" and ffmpeg_exe) or (name == "ffprobe" and ffprobe_exe):
            continue
        for base in search_dirs:
            p = os.path.join(base, f"{name}.exe")
            if os.path.isfile(p):
                if name == "ffmpeg":
                    ffmpeg_exe = p
                else:
                    ffprobe_exe = p
                break

    for name in ("ffmpeg", "ffprobe"):
        if (name == "ffmpeg" and ffmpeg_exe) or (name == "ffprobe" and ffprobe_exe):
            continue
        try:
            result = subprocess.run(
                ["where", name], capture_output=True, text=True, shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                p = result.stdout.strip().split("\n")[0].strip()
                if os.path.isfile(p):
                    if name == "ffmpeg":
                        ffmpeg_exe = p
                    else:
                        ffprobe_exe = p
        except Exception:
            pass

    # ffmpeg 始终优先用 imageio 7.1（避免 8.x 的 theora bug），ffprobe 用系统版本
    if imageio_ffmpeg_path:
        ffmpeg_exe = imageio_ffmpeg_path

    if ffmpeg_exe and ffprobe_exe:
        _save_config({"ffmpeg": ffmpeg_exe, "ffprobe": ffprobe_exe})
    return ffmpeg_exe, ffprobe_exe


# ═══════════════════════════════════════════════════════════
# 视频信息
# ═══════════════════════════════════════════════════════════

@dataclass
class VideoStream:
    index: int = 0
    codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: int = 0
    pix_fmt: str = ""

@dataclass
class AudioStream:
    index: int = 0
    codec: str = ""
    channels: int = 0
    sample_rate: int = 0
    bitrate: int = 0

@dataclass
class VideoInfo:
    filepath: str = ""
    filename: str = ""
    size_mb: float = 0.0
    duration: float = 0.0
    container: str = ""
    video: Optional[VideoStream] = None
    audio: Optional[AudioStream] = None
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.video is not None or self.audio is not None


def parse_video_info(filepath: str, ffprobe_exe: str) -> tuple[Optional[VideoInfo], str]:
    """返回 (info, error_msg)。error_msg 为空表示成功"""
    if not ffprobe_exe:
        return None, "ffprobe 路径为空"
    if not os.path.isfile(ffprobe_exe):
        return None, f"ffprobe 不存在: {ffprobe_exe}"
    if not os.path.isfile(filepath):
        return None, f"文件不存在: {filepath}"

    try:
        result = subprocess.run(
            [ffprobe_exe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", filepath],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or "(无错误输出)"
            detail = (
                f"ffprobe: {ffprobe_exe}\n"
                f"文件: {os.path.basename(filepath)}\n"
                f"返回码: {result.returncode}\n"
                f"错误: {err[:400]}"
            )
            return None, detail
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return None, f"ffprobe 输出非 JSON: {e}"
    except subprocess.TimeoutExpired:
        return None, "ffprobe 超时"
    except OSError as e:
        return None, f"无法启动 ffprobe: {e}"

    info = VideoInfo(
        filepath=filepath,
        filename=os.path.basename(filepath),
        raw=data,
    )
    fmt = data.get("format", {})
    info.container = fmt.get("format_name", "")
    info.duration = float(fmt.get("duration", 0))
    info.size_mb = float(fmt.get("size", 0)) / (1024 * 1024)

    for s in data.get("streams", []):
        codec_type = s.get("codec_type", "")
        if codec_type == "video" and info.video is None:
            fps_str = s.get("avg_frame_rate", s.get("r_frame_rate", "0/1"))
            fps = 0.0
            if "/" in fps_str:
                parts = fps_str.split("/")
                if float(parts[1]) != 0:
                    fps = float(parts[0]) / float(parts[1])
            info.video = VideoStream(
                index=s.get("index", 0),
                codec=s.get("codec_name", ""),
                width=s.get("width", 0),
                height=s.get("height", 0),
                fps=fps,
                bitrate=int(s.get("bit_rate", 0)) if s.get("bit_rate") else 0,
                pix_fmt=s.get("pix_fmt", ""),
            )
        elif codec_type == "audio" and info.audio is None:
            info.audio = AudioStream(
                index=s.get("index", 0),
                codec=s.get("codec_name", ""),
                channels=s.get("channels", 0),
                sample_rate=int(s.get("sample_rate", 0)),
                bitrate=int(s.get("bit_rate", 0)) if s.get("bit_rate") else 0,
            )
    return info, ""


# ═══════════════════════════════════════════════════════════
# 转换引擎
# ═══════════════════════════════════════════════════════════

class Converter:
    SUPPORTED_INPUT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

    # 根据参考视频编码选择输出编码器
    # STALKER OGM 通常用 mpeg4/xvid；libtheora 兼容性差
    CODEC_MAP = {
        "mpeg4": "libxvid",
        "xvid": "libxvid",
        "msmpeg4v3": "libxvid",
        "theora": "libtheora",
    }

    def __init__(self, ffmpeg_exe: str, ffprobe_exe: str):
        self.ffmpeg = ffmpeg_exe
        self.ffprobe = ffprobe_exe
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._available_encoders: set[str] = set()
        self._scan_encoders()

    def _scan_encoders(self):
        """扫描可用的编码器"""
        try:
            result = subprocess.run(
                [self.ffmpeg, "-encoders"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            for line in result.stdout.split("\n"):
                # 格式: V....D libxvid  ...
                if line.startswith(" V") or line.startswith(" A"):
                    parts = line.split()
                    if len(parts) >= 2:
                        self._available_encoders.add(parts[1])
        except Exception:
            pass

    def _pick_video_encoder(self, reference_codec: str) -> str:
        """根据参考编码和可用编码器选择视频编码器"""
        preferred = self.CODEC_MAP.get(reference_codec, "libtheora")
        if preferred in self._available_encoders:
            return preferred
        # 回退
        fallbacks = ["libtheora", "libxvid", "mpeg4"]
        for fb in fallbacks:
            if fb in self._available_encoders:
                return fb
        return "mpeg4"  # 内置编码器，总可用

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    @staticmethod
    def can_convert(filepath: str) -> bool:
        return os.path.splitext(filepath)[1].lower() in Converter.SUPPORTED_INPUT

    def convert(self, input_path: str, output_path: str,
                reference_info: Optional[VideoInfo] = None,
                progress_callback=None) -> tuple[bool, str]:
        self._cancelled = False

        # 从参考 OGM 提取全部编码参数
        ref_vcodec = ""
        ref_w, ref_h, ref_fps = 0, 0, 0.0
        ref_vbitrate = 0
        ref_ar, ref_ac, ref_abitrate = 48000, 2, 160000

        if reference_info and reference_info.video:
            rv = reference_info.video
            ref_vcodec = rv.codec
            ref_w, ref_h = rv.width, rv.height
            ref_fps = rv.fps
            ref_vbitrate = rv.bitrate
        if reference_info and reference_info.audio:
            ra = reference_info.audio
            ref_ar = ra.sample_rate if ra.sample_rate > 0 else 48000
            ref_ac = ra.channels if ra.channels > 0 else 2
            ref_abitrate = ra.bitrate if ra.bitrate > 0 else 160000

        vcodec = self._pick_video_encoder(ref_vcodec)

        cmd = [self.ffmpeg, "-y", "-i", input_path]

        # 视频编码：参考有码率就匹配，没有就默认
        if vcodec in ("libxvid", "mpeg4"):
            vbr = ref_vbitrate if ref_vbitrate > 0 else 2500000
            cmd += ["-c:v", vcodec, "-b:v", str(vbr), "-pix_fmt", "yuv420p"]
        else:
            if ref_vbitrate > 0:
                cmd += ["-c:v", "libtheora", "-b:v", str(ref_vbitrate), "-pix_fmt", "yuv420p"]
            else:
                cmd += ["-c:v", "libtheora", "-q:v", "7", "-pix_fmt", "yuv420p", "-g", "30"]

        vf_parts = []
        need_scale = ref_w > 0 and ref_h > 0
        need_fps = ref_fps > 0
        if need_scale or need_fps:
            src_info, _ = parse_video_info(input_path, self.ffprobe)
            if need_scale and src_info and src_info.video:
                if src_info.video.width == ref_w and src_info.video.height == ref_h:
                    need_scale = False
            if need_fps and src_info and src_info.video:
                if abs(src_info.video.fps - ref_fps) < 0.01:
                    need_fps = False
        if need_scale:
            vf_parts.append(f"scale={ref_w}:{ref_h}")
        if need_fps:
            vf_parts.append(f"fps={ref_fps}")
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]

        cmd += [
            "-c:a", "libvorbis",
            "-b:a", str(ref_abitrate),
            "-ar", str(ref_ar),
            "-ac", str(ref_ac),
        ]
        cmd += ["-f", "ogg", output_path]

        try:
            self._proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError as e:
            return False, f"启动 ffmpeg 失败: {e}"

        duration_sec = 0.0
        if reference_info and reference_info.duration > 0:
            duration_sec = reference_info.duration
        else:
            info, _ = parse_video_info(input_path, self.ffprobe)
            if info and info.duration > 0:
                duration_sec = info.duration

        time_pat = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
        stderr_lines: list[str] = []
        for line in self._proc.stderr:
            stderr_lines.append(line)
            if self._cancelled:
                self._proc.terminate()
                return False, "已取消"
            m = time_pat.search(line)
            if m and duration_sec > 0 and progress_callback:
                h, mi, s, cs = map(int, m.groups())
                cur = h * 3600 + mi * 60 + s + cs / 100.0
                progress_callback(min(cur / duration_sec * 100, 99.5))

        ret = self._proc.wait()
        if self._cancelled:
            return False, "已取消"

        # 收集错误日志
        err_tail = "\n".join(stderr_lines[-8:]) if stderr_lines else ""

        if ret != 0:
            return False, f"ffmpeg 退出码 {ret}\n{err_tail[-300:]}"

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            return False, "输出文件为空"

        # 验证输出：检查时长和帧数
        out_info, _ = parse_video_info(output_path, self.ffprobe)
        if out_info and duration_sec > 0:
            ratio = out_info.duration / duration_sec if duration_sec > 0 else 0
            # 估算帧数
            expected_frames = int(duration_sec * (ref_fps if ref_fps > 0 else 30))
            actual_frames = 0
            if out_info.video:
                # 从 duration * fps 推算实际帧数
                actual_frames = int(out_info.video.fps * out_info.duration) if out_info.video.fps > 0 else 0
            if ratio < 0.8 or (expected_frames > 0 and actual_frames > 0 and actual_frames < expected_frames * 0.8):
                return False, (
                    f"输出不完整！\n"
                    f"  源时长: {duration_sec:.1f}s (约 {expected_frames} 帧)\n"
                    f"  输出时长: {out_info.duration:.1f}s (约 {actual_frames} 帧)\n"
                    f"  ffmpeg 日志:\n{err_tail[-400:]}"
                )

        return True, output_path


# ═══════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════

def _clean_dnd_path(data: str) -> str:
    path = data.strip()
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    return path.strip('"')


class VideoOGMApp:
    def __init__(self, master=None, ffmpeg_exe=None, ffprobe_exe=None, suppress_warn=False):
        # 未显式传入时自动探测 (单文件 hub 嵌入时 ffmpeg_exe 为 None)
        if not ffmpeg_exe or not ffprobe_exe:
            _fe, _fp = find_ffmpeg()
            if not ffmpeg_exe:
                ffmpeg_exe = _fe
            if not ffprobe_exe:
                ffprobe_exe = _fp
        self.ffmpeg = ffmpeg_exe
        self.ffprobe = ffprobe_exe
        self.converter = Converter(ffmpeg_exe, ffprobe_exe) if ffmpeg_exe and ffprobe_exe else None
        self.source_path = ""
        self.reference_path = ""
        self.source_info: Optional[VideoInfo] = None
        self.reference_info: Optional[VideoInfo] = None
        self.converting = False
        self.root = master or _BaseTk()
        apply_theme()
        apply_tk_defaults(self.root)
        if master is None:
            self.root.title("Video OGM Tool")
            self.root.geometry("680x620")
            self.root.minsize(500, 500)
        self.root.configure(bg=T["bg"])

        self._build_ui()
        self._ui = _make_pump(self.root)

        if not ffmpeg_exe:
            if not suppress_warn:
                self.root.after(500, self._warn_no_ffmpeg)
            threading.Thread(target=self._auto_install_ffmpeg, daemon=True).start()

    def _warn_no_ffmpeg(self):
        messagebox.showwarning(
            "未找到 ffmpeg",
            "未检测到 ffmpeg/ffprobe。\n\n"
            "点击底部「设置 ffmpeg」手动选择，\n"
            "或等待后台自动安装。",
        )

    def _build_ui(self):
        pad = {"padx": 12, "pady": (0, 0)}
        MAIN_PADX = 12

        # ── 顶部标题 ──
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=MAIN_PADX, pady=(10, 6))
        tool_header(header, "Video OGM Tool", side="left", padx=0, pady=0)
        # (标题已由 tool_header 统一)
        ttk.Label(header, text="视频参数查看 · MP4/MOV → OGM 转换",
                  style="Dim.TLabel").pack(side="left", padx=(10, 0))

        # ── 双槽：源文件 + 参考文件 ──
        slots = ttk.Frame(self.root)
        slots.pack(fill="x", padx=MAIN_PADX, pady=(0, 4))

        self.slot_source = drop_zone(slots, "源文件", "拖入 MP4 / MOV 或点击选择", on_file=self._on_source)
        self.slot_ref = drop_zone(slots, "参考 OGM（可选）", "拖入 OGM 或点击选择", on_file=self._on_reference)

        # ── 信息面板 + 下方操作区 (可拖拽分隔条) ──
        paned = SplitPane(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=MAIN_PADX, pady=(0, 4))
        info_frame = ttk.LabelFrame(paned, text="视频参数", padding=6)
        paned.add(info_frame, weight=3)
        lower = ttk.Frame(paned)
        paned.add(lower, weight=1)

        self.info_text = tk.Text(
            info_frame, height=10, wrap="word",
            font=("Consolas", 10), borderwidth=0,
            state="disabled",
        )
        self.info_text.pack(fill="both", expand=True)
        self._set_info("等待加载文件…")

        # ── 输出路径 ──
        out_frame = ttk.LabelFrame(lower, text="输出", padding=6)
        out_frame.pack(fill="x", padx=0, pady=(0, 2))

        out_row = ttk.Frame(out_frame)
        out_row.pack(fill="x")

        self.out_var = tk.StringVar()
        self.out_entry = ttk.Entry(out_row, textvariable=self.out_var, font=("Consolas", 10))
        self.out_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="浏览", width=6,
                   command=self._browse_output).pack(side="left", padx=(4, 0))

        # ── 进度 ──
        prog_frame = ttk.Frame(lower)
        prog_frame.pack(fill="x", padx=0, pady=(0, 2))

        self.progress = ttk.Progressbar(prog_frame, mode="determinate", length=100)
        self.progress.pack(fill="x")

        self.status_lbl = ttk.Label(
            prog_frame, text="就绪",
            style="Dim.TLabel",
        )
        self.status_lbl.pack(anchor="w")

        # ── 按钮 + 底部 ──
        bottom = ttk.Frame(lower)
        bottom.pack(fill="x", padx=0, pady=(2, 8))

        self.btn_go = ttk.Button(
            bottom, text="转换为 OGM", command=self._start_convert, state="disabled",
        )
        self.btn_go.pack(side="right")

        self.btn_cancel = ttk.Button(
            bottom, text="取消", command=self._cancel_convert,
        )
        self.btn_cancel.pack(side="right", padx=(0, 6))
        self.btn_cancel.pack_forget()

        self.footer = ttk.Label(
            bottom, text="",
            style="Dim.TLabel",
        )
        self.footer.pack(side="left")

        self.btn_cfg = ttk.Button(
            bottom, text="设置 ffmpeg", command=self._open_settings,
        )
        self.btn_cfg.pack(side="right", padx=(0, 12))
        self._update_footer()

    # ── 信息 ──

    def _set_info(self, text: str):
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", text)
        self.info_text.configure(state="disabled")

    def _update_footer(self):
        parts = []
        if _HAS_DND:
            parts.append("拖拽 ✓")
        if self.ffmpeg:
            parts.append("ffmpeg ✓")
        else:
            parts.append("ffmpeg ✗")
        self.footer.configure(text="  |  ".join(parts))

    # ── 文件加载 ──

    def _on_source(self, path: str):
        if not self.ffprobe or not os.path.isfile(self.ffprobe):
            messagebox.showwarning("ffprobe 不可用",
                "未正确配置 ffprobe。请点击底部「设置 ffmpeg」选择 ffmpeg.exe，\n"
                "然后确保同目录下有 ffprobe.exe。")
            return
        info, err = parse_video_info(path, self.ffprobe)
        if not info or not info.ok:
            messagebox.showerror("解析失败", f"无法解析:\n{path}\n\n{err}")
            return
        self.source_path = path
        self.source_info = info
        self.slot_source.show_file(path)
        self._refresh_display()
        self._auto_output()

    def _on_reference(self, path: str):
        if not self.ffprobe or not os.path.isfile(self.ffprobe):
            messagebox.showwarning("ffprobe 不可用",
                "未正确配置 ffprobe。请点击底部「设置 ffmpeg」配置。")
            return
        info, err = parse_video_info(path, self.ffprobe)
        if not info or not info.ok:
            messagebox.showerror("解析失败", f"无法解析:\n{path}\n\n{err}")
            return
        self.reference_path = path
        self.reference_info = info
        self.slot_ref.show_file(path)
        self.btn_go.configure(state="normal")
        self._refresh_display()

    def _auto_output(self):
        if not self.source_path:
            return
        src = Path(self.source_path)
        out = src.with_suffix(".ogm")
        if self.reference_path:
            out = Path(self.reference_path).parent / (src.stem + ".ogm")
        self.out_var.set(str(out))

    def _browse_output(self):
        init = self.out_var.get()
        if not init and self.reference_path:
            init = os.path.dirname(self.reference_path)
        path = filedialog.asksaveasfilename(
            title="保存为 OGM",
            defaultextension=".ogm",
            filetypes=[("OGM 视频", "*.ogm")],
            initialdir=os.path.dirname(init) if init else None,
            initialfile=os.path.basename(init) if init else None,
        )
        if path:
            self.out_var.set(path)

    # ── 信息展示 ──

    def _refresh_display(self):
        lines = []
        if self.reference_info:
            lines.append("══ 参考 OGM ══")
            lines.extend(self._fmt(self.reference_info))
            lines.append("")
        if self.source_info:
            lines.append("══ 源文件 ══")
            lines.extend(self._fmt(self.source_info))
            # 显示将使用的编码器
            if self.converter:
                lines.append(f"  输出编码: {self.converter._pick_video_encoder('')} (默认)")
            lines.append("")
        if self.source_info and self.reference_info:
            sv, rv = self.source_info.video, self.reference_info.video
            sa, ra = self.source_info.audio, self.reference_info.audio
            lines.append("══ 转换参数（匹配参考 OGM） ══")
            if sv and rv:
                lines.append(f"  视频编码: {rv.codec} -> {self.converter._pick_video_encoder(rv.codec) if self.converter else '?'}")
                ok_r = "OK" if sv.width == rv.width and sv.height == rv.height else "将缩放"
                ok_f = "OK" if abs(sv.fps - rv.fps) < 0.1 else "将调整"
                lines.append(f"  分辨率:   {sv.width}x{sv.height} -> {rv.width}x{rv.height}  [{ok_r}]")
                lines.append(f"  帧率:     {sv.fps:.2f} -> {rv.fps:.2f}  [{ok_f}]")
                if rv.bitrate > 0:
                    lines.append(f"  视频码率: {rv.bitrate/1000:.0f} kbps（匹配参考）")
            if sa and ra:
                ok_c = "OK" if sa.channels == ra.channels else "将调整"
                lines.append(f"  音频:     采样率 {ra.sample_rate}Hz  {ra.channels}ch  {ra.bitrate/1000:.0f}kbps")
                lines.append(f"            源 {sa.channels}ch -> {ra.channels}ch  [{ok_c}]")
        if not lines:
            lines.append("拖入视频文件查看参数")
        self._set_info("\n".join(lines))

    def _fmt(self, info: VideoInfo) -> list[str]:
        L = [f"  文件: {info.filename}", f"  大小: {info.size_mb:.1f} MB"]
        if info.duration > 0:
            m, s = divmod(int(info.duration), 60)
            L.append(f"  时长: {m}:{s:02d}")
        if info.video:
            v = info.video
            L.append(f"  视频: {v.codec}  {v.width}x{v.height}  {v.fps:.2f}fps"
                     + (f"  {v.bitrate/1000:.0f}kbps" if v.bitrate else ""))
        if info.audio:
            a = info.audio
            L.append(f"  音频: {a.codec}  {a.channels}ch  {a.sample_rate}Hz"
                     + (f"  {a.bitrate/1000:.0f}kbps" if a.bitrate else ""))
        return L

    # ── 转换 ──

    def _start_convert(self):
        if self.converting:
            return
        if not self.reference_path or not self.reference_info:
            messagebox.showwarning("缺少参考 OGM", "请先加载参考 OGM，输出参数必须与参考 OGM 一致。")
            return
        if not self.source_path:
            messagebox.showwarning("缺少源文件", "请先加载源文件。")
            return
        if not self.converter:
            messagebox.showwarning("ffmpeg 不可用", "未找到 ffmpeg。")
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning("缺少输出路径", "请指定输出路径。")
            return
        if not out.lower().endswith(".ogm"):
            out += ".ogm"
            self.out_var.set(out)
        if os.path.exists(out):
            if not messagebox.askyesno("文件已存在", f"覆盖?\n{out}"):
                return

        self.converting = True
        self._set_ui_state(False)
        self.progress["value"] = 0
        self.status_lbl.configure(text="转换中…")
        threading.Thread(target=self._convert_thread, args=(out,), daemon=True).start()

    def _convert_thread(self, output: str):
        def prog(pct):
            self._ui(lambda: self._on_progress(pct))

        ok, msg = self.converter.convert(
            self.source_path, output,
            reference_info=self.reference_info,
            progress_callback=prog,
        )

        def done():
            self.converting = False
            self._set_ui_state(True)
            if ok:
                self.progress["value"] = 100
                self.status_lbl.configure(text=f"完成: {os.path.basename(output)}")
                ni, _ = parse_video_info(output, self.ffprobe)
                if ni:
                    self._set_info("══ 转换完成 ══\n" + "\n".join(self._fmt(ni)))
            else:
                self.status_lbl.configure(text=f"失败: {msg}")

        self.root.after(0, done)

    def _on_progress(self, pct: float):
        self.progress["value"] = pct
        self.status_lbl.configure(text=f"转换中… {pct:.0f}%")

    def _cancel_convert(self):
        if self.converter:
            self.converter.cancel()
        self.status_lbl.configure(text="已取消")

    def _set_ui_state(self, enabled: bool):
        if enabled:
            self.btn_go.configure(state="normal")
            self.btn_cancel.pack_forget()
        else:
            self.btn_go.configure(state="disabled")
            self.btn_cancel.pack(side="right", padx=(0, 6), before=self.btn_go)

    # ── 设置 ──

    def _open_settings(self):
        path = filedialog.askopenfilename(
            title="选择 ffmpeg.exe",
            filetypes=[("ffmpeg.exe", "ffmpeg.exe"), ("可执行文件", "*.exe")],
        )
        if not path:
            return
        d = os.path.dirname(path)
        fp = os.path.join(d, "ffprobe.exe")
        if not os.path.isfile(fp):
            fp = filedialog.askopenfilename(
                title="选择 ffprobe.exe",
                filetypes=[("ffprobe.exe", "ffprobe.exe"), ("可执行文件", "*.exe")],
                initialdir=d,
            )
        if not fp or not os.path.isfile(fp):
            messagebox.showwarning("不完整", "需要 ffprobe.exe 才能解析视频参数。\n请确保 ffprobe.exe 在 ffmpeg 同目录，或手动选择。")
            return

        self.ffmpeg = path
        self.ffprobe = fp
        self.converter = Converter(path, fp)
        _save_config({"ffmpeg": path, "ffprobe": fp})
        self._update_footer()
        messagebox.showinfo("完成", f"ffmpeg: {path}\nffprobe: {fp}")

    def _auto_install_ffmpeg(self):
        try:
            import imageio_ffmpeg
            return
        except ImportError:
            pass
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "imageio-ffmpeg", "-q", "--timeout=30"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            import imageio_ffmpeg
            iexe = imageio_ffmpeg.get_ffmpeg_exe()
            if iexe and os.path.isfile(iexe):
                d = os.path.dirname(iexe)
                probe = os.path.join(d, "ffprobe.exe")
                if not os.path.isfile(probe):
                    return  # ffprobe 不存在，放弃

                def apply():
                    self.ffmpeg = iexe
                    self.ffprobe = probe
                    self.converter = Converter(iexe, probe)
                    _save_config({"ffmpeg": iexe, "ffprobe": probe})
                    self._update_footer()
                self.root.after(0, apply)
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

# ═══ 文件系统 ═══
import stalker_fs
from stalker_fs import (FORMATS, pack_db, unpack_db, extract_file, auto_detect,
                         load_db, sqfs_check, sqfs_list, sqfs_extract, sqfs_pack)
ALL_FMTS = {**FORMATS, "sqfs": {"name": "SquashFS", "key": "sq", "scrambler": None, "pack": False}}
FMT_KEYS = ["auto"] + list(ALL_FMTS.keys())

