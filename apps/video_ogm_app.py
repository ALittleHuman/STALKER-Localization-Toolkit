# -*- coding: utf-8 -*-
"""OGM 视频转换 App (VideoOGMApp)."""
from apps._bootstrap import (
    os, sys, re, threading, subprocess, json, dataclass, field, Path, Optional, tk,
    ttk, filedialog, messagebox
)

from toolkit import (
    color, tool_header, SplitPane, _make_pump, TaskRunner, status_style_name,
    HOST_VIDEO, AREA_TOP_BAR, T, drop_zone, _HAS_DND, errbox, log_summary, log_detail,
    plugin_slot_bar, plugin_options_area, dialog_window,
    app_dir, hidden_kwargs, load_user_value, save_user_values
)

# 手动指定的 ffmpeg/ffprobe 记在**共用的** user.ltx 里（[ffmpeg] 段），
# 不单独开 video_ogm_tool.cfg.json —— 见 toolkit_platform 的说明。
# 只有"手动设置"会写这里；从程序目录读到的结果不落盘。
_CFG_SECTION = "ffmpeg"


def find_ffmpeg() -> tuple[Optional[str], Optional[str]]:
    """定位 ffmpeg / ffprobe —— **只认两处**（用户口径，2026-09-14）。

    用户原话："ffmpeg不用检不检测，直接读目录下的就行，读不到再跳出窗口让用户手动选择。"

      1. `user.ltx` 的 `[ffmpeg] path/probe` —— **只**由"设置 ffmpeg"手动写入，
         是用户的显式意图，所以排在最前；
      2. **程序目录**（`app_dir()`）下的 `ffmpeg.exe` / `ffprobe.exe` —— 发行版里
         `build.py` 会把它们复制到 exe 旁；源码版 `download_ffmpeg.py` 下到项目根，
         两者都等于 `app_dir()`。

    这里**不再**搜 PATH / 常见安装目录，也**不再** import imageio-ffmpeg：那些
    "到处找"的路径正是启动变慢（冻结包里 ~373 ms）与"到底用了哪个 ffmpeg 说不清"
    的来源。读不到就返回 (None, None)，由调用方弹出小窗口 —— 里面有「自动安装」与
    「手动选择」两个按钮（用户口径："ffmpeg自动安装的按钮放在弹窗里。"）。

    版本安全性：程序目录里的二进制是 `download_ffmpeg.py` **校验过**才落下的
    （它显式拒绝 ffmpeg 8.x —— 8.x 的 theora 编码器对 STALKER OGM 有 bug），
    实测本目录是 `7.1-essentials_build`，与原先被优先使用的 imageio 7.1 同一版本线。
    """
    user_ffmpeg = load_user_value(_CFG_SECTION, "path")
    user_ffprobe = load_user_value(_CFG_SECTION, "probe")
    manual_ffmpeg = user_ffmpeg if (user_ffmpeg and os.path.isfile(user_ffmpeg)) else None
    manual_ffprobe = user_ffprobe if (user_ffprobe and os.path.isfile(user_ffprobe)) else None

    local_ffmpeg = os.path.join(app_dir(), "ffmpeg.exe")
    local_ffprobe = os.path.join(app_dir(), "ffprobe.exe")
    ffmpeg_exe = manual_ffmpeg or (local_ffmpeg if os.path.isfile(local_ffmpeg) else None)
    ffprobe_exe = manual_ffprobe or (local_ffprobe if os.path.isfile(local_ffprobe) else None)
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
            **hidden_kwargs(),
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
        self._encoders_scanned = False      # 惰性扫描，见 _ensure_encoders

    def _ensure_encoders(self):
        """惰性扫描一次可用编码器（首次真正要选编码器时才做）。

        为什么不放在 `__init__`：Hub 启动时会**一次性构造全部 6 个 App**，而这里要跑
        `ffmpeg -encoders`（timeout=10s）—— 冷盘/杀软扫描下用户看到的就是"Hub 启动就卡住"。
        改到首次需要时再扫：那时已经在转换的工作线程里。
        失败也**不再静默**：原先 `except Exception: pass` 会让集合为空、后续静默回退到
        mpeg4，用户与日志都不知道输出编码被换掉了。
        """
        if self._encoders_scanned:
            return
        self._encoders_scanned = True
        try:
            result = subprocess.run(
                [self.ffmpeg, "-encoders"],
                capture_output=True, text=True, timeout=10,
                **hidden_kwargs(),
            )
            for line in result.stdout.split("\n"):
                # 格式: V....D libxvid  ...
                if line.startswith(" V") or line.startswith(" A"):
                    parts = line.split()
                    if len(parts) >= 2:
                        self._available_encoders.add(parts[1])
        except Exception as e:
            log_summary(f"编码器探测失败（{type(e).__name__}: {e}）—— 将按内置编码器回退，"
                        f"输出编码可能与参考不一致", "warn")

    def _pick_video_encoder(self, reference_codec: str) -> str:
        """根据参考编码和可用编码器选择视频编码器"""
        self._ensure_encoders()
        preferred = self.CODEC_MAP.get(reference_codec, "libtheora")
        if preferred in self._available_encoders:
            return preferred
        # 回退
        fallbacks = ["libtheora", "libxvid", "mpeg4"]
        for fb in fallbacks:
            if fb in self._available_encoders:
                return fb
        # 走到这里说明一个可用编码器都没探测到：必须留痕（否则用户只看到"画质/兼容性变了"）
        log_summary("没有探测到可用编码器，回退到内置 mpeg4（输出编码与参考不一致）", "warn")
        return "mpeg4"  # 内置编码器，总可用

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def reset_cancel(self):
        """开始新任务前**在主线程**调用：清除上一次的取消请求。

        取消标志原先由 convert() 自己在开头清零，于是"用户点在 convert()
        真正开始之前"的取消会被无声清掉 —— 界面已显示"已取消"，ffmpeg
        却照跑到底。改为：清零发生在新任务启动前（主线程），convert() 只读它。
        """
        self._cancelled = False

    def convert(self, input_path: str, output_path: str,
                reference_info: Optional[VideoInfo] = None,
                progress_callback=None) -> tuple[bool, str]:
        # 注意：这里**不再**清零 _cancelled（见 reset_cancel 的说明）。
        if self._cancelled:
            return False, "已取消"

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

        # 先解析源文件信息：用于判断是否有音轨，以及后续缩放/帧率/进度
        src_info, src_err = parse_video_info(input_path, self.ffprobe)
        duration_sec = 0.0
        if src_info and src_info.duration > 0:
            duration_sec = src_info.duration

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

        # 音频轨：源**确认无音轨**才禁用，避免把有音轨的源静默转成无声 OGM。
        # 旧版无条件写 -c:a（源没音频流时该选项被 ffmpeg 忽略，并不会报错），
        # 因此这里的取舍是：ffprobe 解析失败（src_info 为 None）时按旧行为
        # 保留音频选项，并明确告警——上一版会当作"无音轨"直接 -an。
        if src_info is None:
            log_summary(f"警告: 无法解析源文件音轨信息，按保留音轨处理（{src_err}）", "warn")
            cmd += [
                "-c:a", "libvorbis",
                "-b:a", str(ref_abitrate),
                "-ar", str(ref_ar),
                "-ac", str(ref_ac),
            ]
        elif src_info.audio:
            cmd += [
                "-c:a", "libvorbis",
                "-b:a", str(ref_abitrate),
                "-ar", str(ref_ar),
                "-ac", str(ref_ac),
            ]
        else:
            cmd += ["-an"]
        cmd += ["-f", "ogg", output_path]
        # 完整命令行写「详细日志」（只落盘）：排障时最需要，但没必要刷 GUI
        log_detail("ffmpeg 命令: " + " ".join(str(c) for c in cmd))

        try:
            self._proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                **hidden_kwargs(),
            )
        except OSError as e:
            return False, f"启动 ffmpeg 失败: {e}"

        time_pat = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
        stderr_lines: list[str] = []
        for line in self._proc.stderr:
            stderr_lines.append(line)
            if self._cancelled:
                self._proc.terminate()
                self._proc.wait()
                if os.path.isfile(output_path):
                    try:
                        os.remove(output_path)
                    except Exception:
                        pass
                return False, "已取消"
            m = time_pat.search(line)
            if m and duration_sec > 0 and progress_callback:
                h, mi, s, cs = map(int, m.groups())
                cur = h * 3600 + mi * 60 + s + cs / 100.0
                progress_callback(min(cur / duration_sec * 100, 99.5))

        ret = self._proc.wait()
        if self._cancelled:
            if os.path.isfile(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            return False, "已取消"

        # 收集错误日志
        err_tail = "\n".join(stderr_lines[-8:]) if stderr_lines else ""

        if ret != 0:
            return False, f"ffmpeg 退出码 {ret}\n{err_tail[-300:]}"

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            return False, ("输出文件不存在或为空"
                           if not os.path.isfile(output_path) else "输出文件为空")

        # 验证输出：较长视频检查时长/帧数完整性，短视频只确认有视频轨。
        # 源本身没有视频轨（纯音频源）时不做"必须有视频轨"的判定 ——
        # 那会把 ffmpeg 已经成功产出、文件也非空的音频型 OGM 误报成失败。
        src_has_video = bool(src_info and src_info.video)
        out_info, _ = parse_video_info(output_path, self.ffprobe)
        if out_info is None:
            return False, f"输出文件无法解析\n{err_tail[-400:]}"
        if out_info.video is None and src_has_video:
            return False, f"输出文件无法解析为视频\n{err_tail[-400:]}"
        if duration_sec >= 1.0:
            ratio = out_info.duration / duration_sec if duration_sec > 0 else 0
            if ratio < 0.8:
                return False, (
                    f"输出不完整！\n"
                    f"  源时长: {duration_sec:.1f}s\n"
                    f"  输出时长: {out_info.duration:.1f}s\n"
                    f"  ffmpeg 日志:\n{err_tail[-400:]}"
                )
            # 帧数校验只在**两端帧率都可信**时才做，两个前提缺一不可：
            #   1) 输出帧率可信：OGM/Theora 容器根本不保存帧率，ffprobe 对
            #      所有 .ogm 都给出 r_frame_rate=1/1 → fps*duration 恒等于
            #      "秒数"。实测一个 3 秒、ffmpeg 自己报告编码成功的转换，
            #      在这里被算成"约 3 帧"并误报「输出不完整」。
            #   2) 基准帧率可信：没有参考 OGM 时原先硬编码按 30fps 预期，
            #      低帧率源（本项目里的过场视频就有 3~4fps 的）必然被判失败。
            # 时长比例那一关才是真正能抓"转码被截断"的判据，保留。
            out_fps = out_info.video.fps if out_info.video else 0.0
            base_fps = ref_fps if ref_fps > 0 else (
                src_info.video.fps if src_has_video else 0.0)
            if out_fps >= 5.0 and base_fps >= 5.0:
                expected_frames = int(duration_sec * base_fps)
                actual_frames = int(out_fps * out_info.duration)
                if expected_frames > 0 and actual_frames < expected_frames * 0.8:
                    return False, (
                        f"输出不完整！\n"
                        f"  源时长: {duration_sec:.1f}s (按 {base_fps:.2f}fps 约 {expected_frames} 帧)\n"
                        f"  输出时长: {out_info.duration:.1f}s (约 {actual_frames} 帧)\n"
                        f"  ffmpeg 日志:\n{err_tail[-400:]}"
                    )

        return True, output_path


# ═══════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════
class VideoOGMApp:
    """OGM 视频转换。

    统一契约：只接收宿主 Tab（parent）——不自建根窗口、不应用主题、不自建日志面板；
    日志走全局两级通道（log_summary / log_detail）。ffmpeg / ffprobe 自动探测。
    """

    def __init__(self, parent):
        # ★ 构造期**不探测** ffmpeg（2026-09-14 改惰性）。为什么值这一刀：
        #   原来的 `find_ffmpeg()` 会到处找（PATH / 常见目录 / imageio-ffmpeg），
        #   在冻结包里要 ~373 ms（大头是 `import imageio_ffmpeg`），而 Hub 启动会
        #   **一次性构造全部 6 个 App** —— 用户看到的就是"打开就卡一下"。
        #   探测推迟到**真正要用**时：选/拖源文件、选参考 OGM、点转换（见 _ensure_ffmpeg）。
        #   ★ 探测口径也变了（用户 2026-09-14 定）：**只读程序目录**，读不到就弹窗口
        #     让用户手动选 —— 见 find_ffmpeg 的 docstring。现在一次探测只是
        #     "两次 os.path.isfile + 一次 user.ltx 读"；保持惰性是为了启动那一刻
        #     连这点开销和弹窗都不发生。
        #   在此之前状态栏显示 "ffmpeg 未检测" —— 不是 ✗（那会谎报"找不到"）。
        self.ffmpeg = None
        self.ffprobe = None
        self.converter = None
        self._ffmpeg_probed = False
        self.source_path = ""
        self.reference_path = ""
        self.source_info: Optional[VideoInfo] = None
        self.reference_info: Optional[VideoInfo] = None
        self.root = parent
        self.root.configure(bg=color("bg"))

        self._ui = _make_pump(self.root)
        self._build_ui()
        # 统一任务壳：忙碌标志 + 按钮/取消按钮切换 + 状态语义色 + 线程。
        # 进度为**百分比**（0~100），由 _on_progress 按转换器回调直接写。
        self.task = TaskRunner(
            self.root, self._ui,
            on_busy=self._set_ui_state,
            status_setter=lambda text, kind="idle": self.status_lbl.configure(
                text=text, style=status_style_name(kind)),
        )

    def _ensure_ffmpeg(self):
        """惰性探测 ffmpeg/ffprobe（幂等，只做一次）。返回 converter 是否可用。

        探测口径见 `find_ffmpeg()`：**只读程序目录**（外加用户手动指定的那一对）。
        读不到就**弹出手动选择窗口**（用户口径："读不到再跳出窗口让用户手动选择"）——
        不再到处找、也不再后台自动安装。

        失败也置位：否则每点一次按钮都要重弹一次选择窗口。调用方用 `_ffmpeg_probed`
        判断"这一次是不是我弹的"，避免再叠一层"ffprobe 不可用"的提示。
        """
        if self._ffmpeg_probed:
            return self.converter is not None
        self._ffmpeg_probed = True
        ffmpeg_exe, ffprobe_exe = find_ffmpeg()
        self.ffmpeg = ffmpeg_exe
        self.ffprobe = ffprobe_exe
        self.converter = (Converter(ffmpeg_exe, ffprobe_exe)
                          if ffmpeg_exe and ffprobe_exe else None)
        if self.converter:
            log_summary(f"ffmpeg: {self.ffmpeg}", "ok")
            log_summary(f"ffprobe: {self.ffprobe}", "ok")
        else:
            log_summary("程序目录下没有 ffmpeg/ffprobe —— 弹窗让用户选", "warn")
            # 延到本次事件处理返回之后再弹：拖放入口也在主线程事件里，
            # 别在拖放回调内部开模态文件框。
            self.root.after(0, self._offer_ffmpeg_help)
        self._update_footer()
        return self.converter is not None

    def _build_ui(self):
        MAIN_PADX = 12

        # ── 顶部标题 ──
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=MAIN_PADX, pady=(10, 6))
        tool_header(header, "Video OGM Tool", side="left", padx=0, pady=0)
        # 插件动作区（toolbar 槽；无插件注册时不创建任何控件）。
        # context 传**可调用对象**：原来传的是构造时的字典快照，那时两个路径
        # 必然为空，于是 when={"has_source": True} 之类的命令永远不出现。
        self._slot_bar = plugin_slot_bar(self.root, HOST_VIDEO, app=self,
                                         context=self._slot_context)
        # 插件新建的下拉（api.register_option，area="top_bar"）：无注册时不创建控件
        plugin_options_area(self.root, HOST_VIDEO, area=AREA_TOP_BAR, app=self)
        # (标题已由 tool_header 统一)
        ttk.Label(header, text="视频参数查看 · MP4/MOV/AVI/MKV/WebM/M4V → OGM 转换",
                  style="Dim.TLabel").pack(side="left", padx=(10, 0))

        # ── 双槽：源文件 + 参考文件 ──
        slots = ttk.Frame(self.root)
        slots.pack(fill="x", padx=MAIN_PADX, pady=(0, 4))

        self.slot_source = drop_zone(
            slots, "源文件", "拖入视频文件，或点击选择",
            on_file=self._on_source,
            filetypes=[("视频文件", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v"),
                       ("所有文件", "*.*")],
            pick_title="选择源视频文件")
        self.slot_ref = drop_zone(
            slots, "参考 OGM", "拖入原 OGM 以匹配其参数，或点击选择",
            on_file=self._on_reference,
            filetypes=[("OGM 视频", "*.ogm"), ("所有文件", "*.*")],
            pick_title="选择参考 OGM")

        # ── 信息面板 + 下方操作区 (可拖拽分隔条) ──
        paned = SplitPane(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=MAIN_PADX, pady=(0, 4))
        info_frame = ttk.LabelFrame(paned, text="视频参数", padding=6)
        paned.add(info_frame, weight=3)
        lower = ttk.Frame(paned)
        paned.add(lower, weight=1)

        self.info_text = tk.Text(
            info_frame, height=10, wrap="word",
            font=T["font_mono"], borderwidth=0,
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
        self.out_entry = ttk.Entry(out_row, textvariable=self.out_var, font=T["font_mono"])
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
        if self.converter or self.ffmpeg:
            parts.append("ffmpeg ✓")
        elif self._ffmpeg_probed:
            parts.append("ffmpeg ✗")
        else:
            # 还没探测（惰性：探测在第一次真正要用时才做）——如实显示"未检测"，
            # 不要显示 ✗：那是"找过但没找到"的意思，会谎报。
            parts.append("ffmpeg 未检测")
        self.footer.configure(text="  |  ".join(parts))

    # ── 文件加载 ──

    def _slot_context(self):
        """插件 when 条件用的实时状态（每次重算都重新求值）。"""
        return {"has_source": bool(self.source_path),
                "has_reference": bool(self.reference_path)}

    def _refresh_slot(self):
        """状态变了就重算插件槽，让 when 条件真正生效。"""
        try:
            self._slot_bar.refresh()
        except Exception:
            pass

    def _probe_async(self, path, on_ok, on_err):
        """在工作线程里跑 ffprobe，结果回主线程交给回调。

        ★ 为什么必须异步：`parse_video_info` 内部是 `subprocess.run(..., timeout=30)`。
        在 UI 线程里跑时，拖入一个大 mkv / 网络盘文件就会白屏最长 30 秒（拖放与「浏览」
        两条入口都会中）。工作线程只算、回主线程才碰控件（项目纪律：工作线程连
        StringVar.get() 都不许）。
        并发保护：同一时刻只允许一次探测，避免连点/连拖堆出一串线程。
        """
        if getattr(self, "_probing", False):
            return
        self._probing = True

        def work():
            try:
                info, err = parse_video_info(path, self.ffprobe)
            except Exception as e:
                info, err = None, "%s: %s" % (type(e).__name__, e)

            def done():
                self._probing = False
                if info is not None and info.ok:
                    on_ok(info)
                else:
                    on_err(err)
            self._ui(done)          # 回主线程
        threading.Thread(target=work, daemon=True).start()

    def _on_source(self, path: str):
        # 惰性探测：动作入口才做（见 __init__ 的说明）。首次探测若读不到程序目录下的
        # ffmpeg/ffprobe，`_ensure_ffmpeg` 已经弹了"手动选择"窗口 —— 这里不再叠提示。
        first_probe = not self._ffmpeg_probed
        if not self._ensure_ffmpeg():
            if not first_probe:
                messagebox.showwarning(
                    "ffmpeg 不可用",
                    "未找到 ffmpeg/ffprobe。请点击底部「设置 ffmpeg」手动选择。")
            return
        if not self.ffprobe or not os.path.isfile(self.ffprobe):
            messagebox.showwarning("ffprobe 不可用",
                "未正确配置 ffprobe。请点击底部「设置 ffmpeg」选择 ffmpeg.exe，\n"
                "然后确保同目录下有 ffprobe.exe。")
            return

        def ok(info):
            self.source_path = path
            self.source_info = info
            self.slot_source.show_file(path)
            self._refresh_display()
            self._auto_output()
            # 注意：这里**不**解禁转换按钮。参考 OGM 是必需的，按钮只在加载了参考
            # 之后才可用（见 _on_reference）；"灰着且不解释"是有意为之。
            self._refresh_slot()

        self._probe_async(path, ok,
                          lambda err: errbox("解析失败", f"无法解析:\n{path}\n\n{err}"))

    def _on_reference(self, path: str):
        # 同 _on_source：惰性探测 + 首次读不到时由 _ensure_ffmpeg 弹手动选择窗口。
        first_probe = not self._ffmpeg_probed
        if not self._ensure_ffmpeg():
            if not first_probe:
                messagebox.showwarning(
                    "ffmpeg 不可用",
                    "未找到 ffmpeg/ffprobe。请点击底部「设置 ffmpeg」手动选择。")
            return
        if not self.ffprobe or not os.path.isfile(self.ffprobe):
            messagebox.showwarning("ffprobe 不可用",
                "未正确配置 ffprobe。请点击底部「设置 ffmpeg」配置。")
            return

        def ok(info):
            self.reference_path = path
            self.reference_info = info
            self.slot_ref.show_file(path)
            self.btn_go.configure(state="normal")
            self._refresh_display()
            self._refresh_slot()

        self._probe_async(path, ok,
                          lambda err: errbox("解析失败", f"无法解析:\n{path}\n\n{err}"))

    def _auto_output(self):
        if not self.source_path:
            return
        src = Path(self.source_path)
        out = src.with_suffix(".ogm")
        if self.reference_path:
            out = Path(self.reference_path).parent / (src.stem + ".ogm")
        # 源与参考同目录同主名时（X.mp4 + X.ogm），上面算出来的输出就是
        # **参考文件本身**。原来的实现只靠一次"覆盖?"确认挡着，确认一下就把
        # 参考 OGM 毁了。这里直接改到源文件目录，避免默认值指向输入。
        try:
            if self.reference_path and os.path.normcase(str(out)) == \
                    os.path.normcase(os.path.abspath(self.reference_path)):
                out = src.with_name(src.stem + ".new.ogm")
        except Exception:
            pass
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
            lines.append("")
        if self.source_info and self.reference_info:
            sv, rv = self.source_info.video, self.reference_info.video
            sa, ra = self.source_info.audio, self.reference_info.audio
            lines.append("══ 转换参数（匹配参考 OGM） ══")
            if sv and rv:
                # 不再在这里单独打印"输出编码: xxx (默认)"：
                # 它和下一行的"视频编码: 参考 -> 实际"会在参考为 mpeg4/xvid
                # 时同屏显示两个互斥的编码器名。
                lines.append(f"  视频编码: {rv.codec} -> {self.converter._pick_video_encoder(rv.codec) if self.converter else '?'}")
                ok_r = "OK" if sv.width == rv.width and sv.height == rv.height else "将缩放"
                # 阈值与 convert() 里真正决定是否插入 fps 滤镜的判据保持一致（0.01），
                # 否则 23.98 vs 24.00 会显示 [OK] 却仍然插入了 -vf fps=...
                ok_f = "OK" if abs(sv.fps - rv.fps) < 0.01 else "将调整"
                lines.append(f"  分辨率:   {sv.width}x{sv.height} -> {rv.width}x{rv.height}  [{ok_r}]")
                lines.append(f"  帧率:     {sv.fps:.2f} -> {rv.fps:.2f}  [{ok_f}]")
                if rv.bitrate > 0:
                    lines.append(f"  视频码率: {rv.bitrate/1000:.0f} kbps（匹配参考）")
            if sa and ra:
                ok_c = "OK" if sa.channels == ra.channels else "将调整"
                # 显示**实际会传给 ffmpeg 的值**：convert() 对 0 值回退成
                # 48000 / 2ch / 160kbps，这里原先直接打印参考的原始 0 值。
                ar = ra.sample_rate if ra.sample_rate > 0 else 48000
                ac = ra.channels if ra.channels > 0 else 2
                abr = ra.bitrate if ra.bitrate > 0 else 160000
                lines.append(f"  音频:     采样率 {ar}Hz  {ac}ch  {abr/1000:.0f}kbps")
                lines.append(f"            源 {sa.channels}ch -> {ac}ch  [{ok_c}]")
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
        if self.task.running:
            return
        # 参考 OGM **必需**（用户决策）：输出必须按参考 OGM 的参数生成，才能与
        # 游戏引擎一致；「按钮不可用且不额外解释」是有意为之，不要为了"让用户
        # 理解"加提示文案，也不要改成可选。（旧散装版允许无参考，属旧版缺陷，
        # 不应继承。）
        if not self.reference_info:
            return
        if not self.source_path:
            messagebox.showwarning("缺少源文件", "请先加载源文件。")
            return
        if self.converter is None:
            # 惰性探测（正常路径上，选源文件时就已经探过了；这里是兜底与"探针注入了
            # converter"的兼容：已有 converter 就绝不覆盖它）。见 __init__ 的说明。
            self._ensure_ffmpeg()
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

        log_summary(f"开始转换: {self.source_path} -> {out}", "ok")
        self.progress["value"] = 0
        # 取消标志在新任务启动前（主线程）清零：见 Converter.reset_cancel
        self.converter.reset_cancel()

        def work():
            def prog(pct):
                self._ui(self._on_progress, pct)
            ok, msg = self.converter.convert(
                self.source_path, out,
                reference_info=self.reference_info,
                progress_callback=prog,
            )
            # 输出文件的 ffprobe 也放在**工作线程**里跑：parse_video_info 内部
            # 是 subprocess.run(..., timeout=30)，放主线程会让界面在"转换完成"
            # 那一刻僵住最长 30 秒（审计记过这条）。解析结果随回调一起回主线程。
            out_info = parse_video_info(out, self.ffprobe)[0] if ok else None
            self._ui(self._convert_done, out, ok, msg, out_info)

        # 忙碌标志 + 按钮/取消按钮切换由 TaskRunner 负责
        self.task.run(work, status="转换中…", on_error=self._convert_error)

    def _convert_done(self, output: str, ok: bool, msg: str, out_info=None):
        """业务结果回显（主线程）；任务壳状态由 TaskRunner 负责。

        `out_info` 是工作线程里解析好的输出文件信息（见 work()）—— 主线程这里
        **不再**调用 parse_video_info，否则最长会僵住 30 秒。
        """
        if ok:
            self.progress["value"] = 100
            self.task.set_status(f"完成: {os.path.basename(output)}", "ok")
            log_summary(f"转换完成: {output}", "ok")
            if out_info:
                # 标明这些数字属于**输出文件**，而不是把面板里原本的
                # 源/参考参数对比一起抹掉。
                cur = self.info_text.get("1.0", "end").strip()
                head = "══ 输出文件（本次转换结果） ══\n" + "\n".join(self._fmt(out_info))
                self._set_info((cur + "\n\n" + head) if cur else head)
        elif msg == "已取消":
            # 取消不是失败：原先这里会把它覆盖成红色"失败: 已取消"
            self.progress["value"] = 0
            self.task.set_status("已取消", "warn")
            log_summary("转换已取消", "warn")
        else:
            self.progress["value"] = 0
            self.task.set_status(f"失败: {msg}", "err")
            log_summary(f"转换失败: {msg}", "err")

    def _convert_error(self, e):
        self.progress["value"] = 0
        self.task.set_status(f"失败: {e}", "err")
        log_summary(f"转换异常: {e}", "err")

    def _on_progress(self, pct: float):
        """pct 为 **0~100 的百分比**（Converter 回调口径，见 convert() 里
        `progress_callback(min(cur / duration_sec * 100, 99.5))`）。

        这里曾把它当成 0~1 的比例再乘 100，于是进度条 1% 就满格、
        状态文字出现「转换中… 9950%」。
        """
        try:
            val = float(pct)
            self.progress["value"] = val
            self.task.set_status(f"转换中… {val:.0f}%", "running")
        except Exception:
            pass

    def _cancel_convert(self):
        log_summary("用户取消转换", "warn")
        if self.converter:
            self.converter.cancel()
        self.task.set_status("已取消", "warn")

    def _set_ui_state(self, enabled: bool):
        if enabled:
            self.btn_go.configure(state="normal")
            self.btn_cancel.pack_forget()
        else:
            self.btn_go.configure(state="disabled")
            self.btn_cancel.pack(side="right", padx=(0, 6), before=self.btn_go)
        # 转换途中禁止改 ffmpeg：原来只在按钮上禁 btn_go，用户仍能点
        # "设置 ffmpeg" 把 self.converter 换成新对象，正在跑的 ffmpeg 就失去
        # 句柄（"取消"作用于新对象，旧进程成孤儿继续写文件）。
        try:
            self.btn_cfg.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

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
        # 手动指定之后就算"探测过了"：本会话不该再去跑一遍自动探测把这个选择顶掉。
        self._ffmpeg_probed = True
        # 记进共用的 user.ltx（[ffmpeg] 段）；写失败不静默：明确告知"本次可用但不记住"
        if not save_user_values(_CFG_SECTION, {"path": path, "probe": fp}):
            log_summary("警告: 无法写入 user.ltx，下次启动需重新指定 ffmpeg", "warn")
            messagebox.showwarning("设置未保存",
                                   "ffmpeg 路径本次可用，但未能写入 user.ltx，下次启动需重新指定。")
        log_summary(f"手动设置 ffmpeg: {path}", "ok")
        self._update_footer()
        messagebox.showinfo("完成", f"ffmpeg: {path}\nffprobe: {fp}\n\n已记住，下次启动继续使用。")

    # ── 找不到 ffmpeg 时的处理：小窗口 + 用户点按钮（2026-09-14 用户口径）──

    def _offer_ffmpeg_help(self):
        """程序目录下没有 ffmpeg/ffprobe 时弹的小窗口（**非阻塞**）。

        为什么自建弹窗而不是 messagebox：messagebox 给不了自定义按钮，而这里要
        **把"自动安装"做成一个按钮** —— 用户原话："ffmpeg自动安装的按钮放在弹窗里。"
        自动安装因此不再在后台偷偷跑，必须用户点。

        为什么不用 grab_set / wait_window：非阻塞才不会在探针构造与驱动页面时把进程
        卡住，用户也可以先干别的再回来点。窗口由 `_ensure_ffmpeg` 经
        `root.after(0, …)` 弹出（免得在拖放回调内部开模态框）。
        """
        try:
            win = dialog_window(self.root, "未找到 ffmpeg / ffprobe", size="430x165")
        except Exception as e:
            # 弹窗都建不出来时退回最直接的路径：直接给手动选择（不静默失败）
            log_summary(f"帮助弹窗创建失败（{type(e).__name__}: {e}）—— 直接手动选择", "warn")
            self._open_settings()
            return
        ttk.Label(win, text=("程序目录下没有 ffmpeg.exe / ffprobe.exe。\n"
                             "可以自动安装，或手动指定你已有的那一对。"),
                  style="Dim.TLabel", justify="left").pack(anchor="w", padx=12, pady=(12, 8))
        row = ttk.Frame(win)
        row.pack(anchor="e", padx=12, pady=(0, 12))

        def _pick_auto():
            win.destroy()
            self._start_auto_install()

        def _pick_manual():
            win.destroy()
            self._open_settings()

        ttk.Button(row, text="自动安装", command=_pick_auto).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="手动选择", command=_pick_manual).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="稍后", command=win.destroy).pack(side="left")

    def _start_auto_install(self):
        """点了"自动安装"之后：工作线程里装，结果回主线程应用（主线程才碰控件）。"""
        log_summary("开始自动安装 ffmpeg…（可能要下载几百 MB，期间界面可用）", "warn")
        try:
            self.task.set_status("正在自动安装 ffmpeg…", "running")
        except Exception:
            pass
        threading.Thread(target=self._auto_install_ffmpeg, daemon=True).start()

    def _auto_install_ffmpeg(self):
        """**仅在用户点"自动安装"后**在工作线程里跑；只做 IO/子进程，绝不碰控件。

        两条路，先试项目自己的安装器：
          1. 程序目录下的 `download_ffmpeg.py` —— 本项目**校验过**的安装脚本
             （显式拒绝 ffmpeg 8.x；ffmpeg 与 ffprobe 一起装到程序目录）。源码版就在手边；
          2. 退回 imageio-ffmpeg（py 包）：它**只带 ffmpeg、不带 ffprobe**，
             所以拿到之后还要在同目录找 ffprobe，找不到就如实告诉用户差什么。
        """
        pair = self._install_via_script() or self._install_via_imageio()
        self._ui(self._apply_installed, pair)

    def _install_via_script(self):
        """跑程序目录下的 `download_ffmpeg.py`；成功且两个文件都在 → 返回那一对。"""
        base = app_dir()
        installer = os.path.join(base, "download_ffmpeg.py")
        if not os.path.isfile(installer):
            return None
        try:
            rc = subprocess.run([sys.executable, installer], cwd=base,
                                capture_output=True, text=True, timeout=1800,
                                **hidden_kwargs())
        except Exception as e:
            log_summary(f"运行 download_ffmpeg.py 异常：{e}", "warn")
            return None
        if rc.returncode != 0:
            tail = ((rc.stderr or "") + (rc.stdout or "")).strip()[-200:]
            log_summary(f"download_ffmpeg.py 退出码 {rc.returncode}：{tail}", "warn")
            return None
        ff = os.path.join(base, "ffmpeg.exe")
        fp = os.path.join(base, "ffprobe.exe")
        if os.path.isfile(ff) and os.path.isfile(fp):
            return ff, fp
        log_summary("download_ffmpeg.py 跑完但程序目录里仍缺 ffmpeg/ffprobe", "warn")
        return None

    def _install_via_imageio(self):
        """退回 imageio-ffmpeg：装包 → 取 ffmpeg → 同目录还要有 ffprobe（它不带）。"""
        def _exe():
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()

        try:
            iexe = _exe()
        except Exception:
            iexe = None
        if not iexe:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "imageio-ffmpeg",
                     "-q", "--timeout=180"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    **hidden_kwargs())
            except Exception as e:
                log_summary(f"自动安装 imageio-ffmpeg 失败：{e}", "warn")
                return None
            try:
                # 装完必须**重新 import**：旧实现就是这里踩过 UnboundLocalError
                # （局部名未绑定 → 被最外层 except 吞掉 → 本会话永不生效）。
                iexe = _exe()
            except Exception as e:
                log_summary(f"自动安装后仍拿不到 ffmpeg：{e}", "warn")
                return None
        if not iexe or not os.path.isfile(iexe):
            log_summary("自动安装没产出可用的 ffmpeg", "warn")
            return None
        probe = os.path.join(os.path.dirname(iexe), "ffprobe.exe")
        if not os.path.isfile(probe):
            log_summary("自动安装只拿到 ffmpeg（imageio 不带 ffprobe）—— 请改用「手动选择」",
                        "warn")
            return None
        return iexe, probe

    def _apply_installed(self, pair):
        """主线程：把自动安装拿到的 ffmpeg/ffprobe 接上（失败明确告知，不静默）。"""
        if not pair:
            try:
                self.task.set_status("自动安装失败", "err")
            except Exception:
                pass
            messagebox.showwarning(
                "自动安装未完成",
                "没能自动装好 ffmpeg/ffprobe。\n\n"
                "请点底部「设置 ffmpeg」手动选择你已有的 ffmpeg.exe"
                "（同目录需有 ffprobe.exe）。")
            return
        ff, fp = pair
        self.ffmpeg, self.ffprobe = ff, fp
        self.converter = Converter(ff, fp)
        self._ffmpeg_probed = True
        self._update_footer()
        log_summary(f"自动安装完成：{ff}", "ok")
        try:
            self.task.set_status("ffmpeg 已就绪", "ok")
        except Exception:
            pass

