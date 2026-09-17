# -*- coding: utf-8 -*-
"""构造级 + 入口级探针（端到端闸门的一部分）。

为什么需要它：`run_ci.py` 只 import 模块，**方法体内的隐式初始化依赖抓不到**。
已知同形态缺陷三处：
    font_pack_app:436         用了未导入的 errbox
    text_extract_app:313/322  用了仅定义在 convert_app 的 SCRIPT_TRANSLATE_FUNC
    convert_app:539/609       读只在线程启动器里赋值的 self._snap
本探针构造六个 App 并调用其入口方法，把这一类缺陷变成机器可查。

设计约束：
  * 需要桌面 tk（与 run_ui_smoke 同前提）；
  * 全部对话框打桩，绝不阻塞；
  * 只调用**安全入口**：不启动后台线程、不跑真实转换、不写用户数据；
  * 自清理：退出码 0=全过，1=有失败（可直接进 CI）。

用法: python run_app_probe.py
"""
import os
import sys
import threading
import time
import traceback

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 对话框打桩：任何弹窗都只记录，绝不阻塞 ──
_dialogs = []


def _stub(name):
    def _f(*a, **k):
        _dialogs.append((name, a[0] if a else "", a[1] if len(a) > 1 else ""))
        return "ok"
    return _f


def _patch_dialogs():
    from tkinter import messagebox, filedialog
    for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion"):
        if hasattr(messagebox, fn):
            setattr(messagebox, fn, _stub("messagebox." + fn))
    messagebox.askyesnocancel = _stub("messagebox.askyesnocancel")
    filedialog.askdirectory = _stub("filedialog.askdirectory")
    filedialog.askopenfilename = _stub("filedialog.askopenfilename")
    filedialog.asksaveasfilename = _stub("filedialog.asksaveasfilename")

    import toolkit_base
    import toolkit
    toolkit_base.errbox = _stub("errbox")
    toolkit.errbox = toolkit_base.errbox


_patch_dialogs()

import tkinter as tk  # noqa: E402

# 需要桌面：无显示环境按 SKIP 处理（退出码 0），绝不伪装成失败。
# ★ 光有 try/except 不够：在某些环境里 `tk.Tk()` **既不抛异常也不返回**（2026-09-17 实测：
#   GitHub runner 上本探针挂满 run_ci 的 600 秒超时，把整轮闸门拖死）。所以这里再加一道
#   **看门狗**：根窗口照旧在主线程建（Tk 要求），另起一条守护线程计时；超时仍未建出，就
#   打印同一条 SKIP 标识并硬退出（此时 Tk 调用可能永远阻塞，不能等清理逻辑跑完）。
#   超时秒数可用环境变量 `APP_PROBE_TK_TIMEOUT` 覆盖（默认 20 秒；正常建窗远小于 1 秒）。
_TK_BOOT_TIMEOUT = float(os.environ.get("APP_PROBE_TK_TIMEOUT", "20"))
_TK_BOOT_DONE = threading.Event()


def _tk_boot_watchdog():
    if not _TK_BOOT_DONE.wait(_TK_BOOT_TIMEOUT):
        print("SKIP run_app_probe: 无法创建 Tk 根窗口（需要桌面环境）: "
              "建窗 %.1f 秒未返回" % _TK_BOOT_TIMEOUT)
        sys.stdout.flush()
        os._exit(0)


threading.Thread(target=_tk_boot_watchdog, daemon=True).start()
try:
    try:
        from tkinterdnd2 import TkinterDnD  # noqa: F401
        _ROOT = TkinterDnD.Tk()
    except ImportError:
        _ROOT = tk.Tk()
    _ROOT.withdraw()
except Exception as _e:
    _TK_BOOT_DONE.set()
    print("SKIP run_app_probe: 无法创建 Tk 根窗口（需要桌面环境）: %s" % _e)
    sys.exit(0)
_TK_BOOT_DONE.set()

from apps.font_pack_app import FontPackApp          # noqa: E402
from apps.convert_app import ConvertApp             # noqa: E402
from apps.text_extract_app import TextExtractApp    # noqa: E402
from apps.xml_compare_app import XMLCompareApp      # noqa: E402
from apps.video_ogm_app import VideoOGMApp          # noqa: E402
from apps.fs_app import FSToolApp                   # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(name, fn):
    """fn 抛异常即 FAIL（并记录 traceback 摘要）；**显式返回 False 也算 FAIL**。

    早期只判异常，于是 `check("x", lambda: a == b)` 这类"纯布尔表达式"永远不会失败
    —— False 被静默丢弃，断言空转但 PASS 照加。返回 None 仍算通过。
    """
    global _PASS, _FAIL
    try:
        r = fn()
    except Exception as e:
        _FAIL += 1
        _FAILURES.append("%s -> %s: %s" % (name, type(e).__name__, e))
        print("  FAIL %s -> %s: %s" % (name, type(e).__name__, e))
        for line in traceback.format_exc().strip().splitlines():
            print("       " + line.rstrip())
        return
    if r is False:
        _FAIL += 1
        _FAILURES.append("%s -> 断言返回 False" % name)
        print("  FAIL %s -> 断言返回 False" % name)
        return
    _PASS += 1
    print("  PASS %s" % name)


def check_raises(name, fn, exc_types):
    """断言**恰好**抛出预期的业务异常（是校验行为，不是缺陷）。"""
    global _PASS, _FAIL
    try:
        fn()
    except exc_types:
        _PASS += 1
        print("  PASS %s（按预期拒绝）" % name)
        return
    except Exception as e:
        _FAIL += 1
        _FAILURES.append("%s -> 抛了非预期异常 %s: %s" % (name, type(e).__name__, e))
        print("  FAIL %s -> 非预期 %s: %s" % (name, type(e).__name__, e))
        return
    _FAIL += 1
    _FAILURES.append("%s -> 未拒绝（应抛 %s）" % (name, exc_types))
    print("  FAIL %s -> 未拒绝" % name)


def main():
    print("=== 1. 构造六个 App（宿主 Tab 契约 build(parent)） ===")
    built = {}

    def make(key, cls):
        def _f():
            tab = tk.Frame(_ROOT)
            tab.pack()
            built[key] = cls(tab)
        return _f

    for key, cls in (("fs", FSToolApp), ("convert", ConvertApp), ("text", TextExtractApp),
                     ("xml", XMLCompareApp), ("video", VideoOGMApp), ("font", FontPackApp)):
        check("构造 %s" % key, make(key, cls))

    def video_no_encoder_scan_at_construct():
        """构造 VideoOGMApp **既不跑 `ffmpeg -encoders`，也不探测 ffmpeg**。

        两条都是"Hub 启动会一次性构造全部 6 个 App"逼出来的：
          * 历史缺陷：`Converter.__init__` 里同步跑 `_scan_encoders()` = `ffmpeg -encoders`
            （timeout=10s）—— 冷盘/杀软扫描下用户看到的就是"Hub 启动就卡住"；
          * 2026-09-14：`find_ffmpeg()` 也挪出构造期（冻结包里 ~373 ms，大头是
            `import imageio_ffmpeg`），改到动作入口（`_ensure_ffmpeg`）。
        两条**都必须验证"惰性没退化成永不执行"** —— 否则编码器选择会静默回退到 mpeg4、
        ffmpeg 也永远找不到，比卡顿更糟。
        只统计参数里带 `-encoders` 的调用；构造期本来会跑 `where` 之类的查找，把它们
        算进来会让这条锁因无关原因误红。
        """
        import apps.video_ogm_app as _v
        calls, finds = [], []
        orig_run, orig_find = _v.subprocess.run, _v.find_ffmpeg

        def spy(*a, **k):
            calls.append(a[0] if a else k.get("args"))
            return orig_run(*a, **k)

        def spy_find():
            finds.append(1)
            return orig_find()
        _v.subprocess.run = spy
        _v.find_ffmpeg = spy_find

        def _count_encoder_scans():
            return len([c for c in calls
                        if isinstance(c, (list, tuple)) and "-encoders" in c])
        try:
            app = VideoOGMApp(tk.Frame(_ROOT))
            hits = [c for c in calls if isinstance(c, (list, tuple)) and "-encoders" in c]
            assert not hits, "构造 VideoOGMApp 时跑了 ffmpeg -encoders：%r" % (hits[:1],)
            assert not finds, "构造 VideoOGMApp 时跑了 find_ffmpeg（构造期不该探测 ffmpeg）"
            assert app.converter is None, "构造完就已经有 converter 了（说明探测没被推迟）"
            assert not app.ffmpeg, "构造完 self.ffmpeg 就已经有值（同上）"
            # 惰性必须仍有效：显式走一次动作入口（_ensure_ffmpeg），它必须真的去探。
            app._ensure_ffmpeg()
            assert finds, "动作入口没有触发 ffmpeg 探测（能力被删掉了）"
            # 环境相关：这台机器上有没有 ffmpeg —— 有才继续验"编码器惰性扫描仍有效"。
            if app.converter is not None:
                before = _count_encoder_scans()
                app.converter._ensure_encoders()
                assert _count_encoder_scans() > before, \
                    "惰性扫描没有真的发生（能力被删掉了）"
        finally:
            _v.subprocess.run, _v.find_ffmpeg = orig_run, orig_find
    check("视频.构造 App 不探测 ffmpeg、也不跑 ffmpeg -encoders（Hub 启动不卡）"
          "，两者惰性仍有效",
          video_no_encoder_scan_at_construct)

    def video_ffprobe_is_async():
        """选/拖源文件时的 ffprobe 解析不得占 UI 线程。

        判据：把 `parse_video_info` 打桩成"睡 0.3 秒再成功返回"，调 `_on_source` 必须
        **立刻返回**（<0.15s），随后由 UI 泵把结果回主线程（`source_path`/`source_info`
        被写上）。历史实现是在 UI 线程里同步调它（内部 timeout=30）→ 大文件/网络盘白屏。
        """
        import apps.video_ogm_app as _v
        app = VideoOGMApp(tk.Frame(_ROOT))
        # 前置检查要求 ffprobe "是个存在的文件"；用探针自己的脚本当占位。
        # （先走一次惰性探测，免得 _on_source 里的探测把下面的打桩值覆盖掉。）
        app._ensure_ffmpeg()
        app.ffprobe = os.path.abspath(__file__)
        orig = _v.parse_video_info

        class _Info:
            ok = True

        def slow_parse(path, probe):
            time.sleep(0.3)
            return _Info(), ""

        _v.parse_video_info = slow_parse
        try:
            t0 = time.time()
            app._on_source("C:/nonexistent/probe.mp4")
            elapsed = time.time() - t0
            assert elapsed < 0.15, \
                "ffprobe 解析阻塞了 UI 线程 %.2fs（应改到工作线程）" % elapsed
            landed = False
            for _ in range(120):
                _ROOT.update()
                time.sleep(0.02)
                if app.source_path:
                    landed = True
                    break
            assert landed, "异步解析的结果没有回到主线程（_ui 没被调用？）"
            assert app.source_info is not None, "结果回来了但没写进 source_info"
        finally:
            _v.parse_video_info = orig
    check("视频.选源文件的 ffprobe 解析不阻塞 UI 线程（结果经 _ui 回主线程）",
          video_ffprobe_is_async)

    def video_ffmpeg_only_program_dir():
        """ffmpeg 只认两处：**用户手动指定** + **程序目录**（用户 2026-09-14 口径）。

        用户原话："ffmpeg不用检不检测，直接读目录下的就行，读不到再跳出窗口让用户手动选择。"
        判据分两层：
          * 源码层（AST 取 `find_ffmpeg` 的函数体）：不得再出现 imageio-ffmpeg /
            locate_exe / extra_dirs / PATH 搜索 —— 那些"到处找"的路径正是启动变慢
            与"到底用了哪个 ffmpeg 说不清"的来源；必须读 `app_dir()`。
          * 运行层：真跑一遍，返回值只能落在"程序目录"或"用户手动指定"这两处。
        """
        import ast
        from apps.video_ogm_app import find_ffmpeg
        base = os.path.dirname(os.path.abspath(__file__))
        src_p = os.path.join(base, "apps", "video_ogm_app.py")
        with open(src_p, encoding="utf-8") as f:
            src = f.read()
        fn = next((n for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef) and n.name == "find_ffmpeg"), None)
        assert fn is not None, "找不到 find_ffmpeg"
        # ★ 只扫**代码语句**，剥掉 docstring：函数的 docstring 里正解释"不再 import
        #   imageio / 不再搜 PATH"，按全文扫会被自己的说明文字喂饱（第一次就是这么红的）。
        stmts = [n for n in fn.body
                 if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                         and isinstance(n.value.value, str))]
        body = "\n".join(ast.get_source_segment(src, n) or "" for n in stmts)
        for banned in ("imageio", "locate_exe", "extra_dirs", "which("):
            assert banned not in body, \
                "find_ffmpeg 里又出现了 %r（用户口径：只读程序目录）" % banned
        assert "app_dir()" in body, "find_ffmpeg 没有读程序目录"
        from toolkit import load_user_value as _luv
        manual = _luv("ffmpeg", "path") or ""
        ff, _fp = find_ffmpeg()
        if ff:
            d = os.path.dirname(os.path.abspath(ff))
            assert d == os.path.abspath(base) or (
                manual and os.path.abspath(ff) == os.path.abspath(manual)), \
                "find_ffmpeg 返回了第三种来源：%s" % ff
    check("视频.ffmpeg 只认「用户手动指定 + 程序目录」（不再搜 PATH / 不 import imageio）",
          video_ffmpeg_only_program_dir)

    def video_missing_ffmpeg_dialog():
        """读不到 ffmpeg → 弹**带按钮的小窗口**；「自动安装」只有用户点它才跑。

        用户原话："ffmpeg自动安装的按钮放在弹窗里。"（即：自动安装保留，但不许后台偷偷跑）
        判据三件：
          * 弹窗里真的有「自动安装 / 手动选择 / 稍后」三个按钮；
          * 点「自动安装」→ 进 `_start_auto_install`（那里才起线程）；
          * 点「稍后」→ 什么都不做（不安装、不弹选择框）；
          * 源码层：`__init__` / `_ensure_ffmpeg` 里**不得**出现自动安装 —— 它只能挂在按钮上。
        """
        import ast
        import tkinter as _tk

        def _buttons(win):
            out = {}

            def walk(w):
                for c in w.winfo_children():
                    if isinstance(c, _tk.ttk.Button):
                        out[str(c.cget("text"))] = c
                    walk(c)
            walk(win)
            return out

        app = VideoOGMApp(tk.Frame(_ROOT))
        app._ffmpeg_probed = True              # 装作"已探测、程序目录下没有"
        calls = []
        app._start_auto_install = lambda: calls.append("auto")
        app._open_settings = lambda: calls.append("manual")

        def _pop():
            app._offer_ffmpeg_help()
            _ROOT.update_idletasks()
            tops = [w for w in app.root.winfo_children() if isinstance(w, _tk.Toplevel)]
            assert tops, "没有弹出帮助窗口"
            return tops[-1]

        w1 = _pop()
        names = sorted(_buttons(w1))
        assert set(names) >= {"自动安装", "手动选择", "稍后"}, "弹窗按钮不全：%r" % names
        _buttons(w1)["自动安装"].invoke()
        assert calls == ["auto"], "点『自动安装』没进自动安装入口：%r" % (calls,)
        w2 = _pop()
        _buttons(w2)["稍后"].invoke()
        assert calls == ["auto"], "点『稍后』不该做任何事：%r" % (calls,)

        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "apps", "video_ogm_app.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        for fname in ("__init__", "_ensure_ffmpeg"):
            fn = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == fname), None)
            assert fn is not None, "找不到 %s" % fname
            seg = ast.get_source_segment(src, fn) or ""
            assert "_auto_install_ffmpeg" not in seg, \
                "%s 里又出现自动安装了（用户口径：自动安装按钮放在弹窗里）" % fname
    check("视频.读不到 ffmpeg 时弹带按钮的窗口；『自动安装』只有点它才跑",
          video_missing_ffmpeg_dialog)

    def convert_task_shell_is_shared_taskrunner():
        """convert_app 的**任务壳**（running / 忙碌 UI / 线程 / 失败路径）统一走 TaskRunner。

        这是长期待办"忙碌/进度统一到 TaskRunner"的落点。代码里原先有一条注释说
        "本 App 不用 TaskRunner"，理由是暂停/继续状态机与三类任务 —— 那条理由对
        **暂停**成立（TaskRunner 没有暂停概念），但对**任务壳**不成立：running 标志
        与忙碌 UI 原本在本 App 另养了一份，正是所谓"两份来源"。

        边界（本锁只钉任务壳，不碰这两样）：
          * 暂停/继续（`pause_event` + 开始/暂停/取消三态）仍由本 App 管理；
          * 三种进度文案（convert/restore/clear）与"进度栏空闲收起"仍由本 App 管理
            （TaskRunner 的 `progress_update` 只写 "done / total"，套上去会改外观）。

        判据：构造后 `app.task` 是共享 TaskRunner 且空闲；跑一个**可控慢任务**时
        running=True 且三个启动按钮全禁用；运行期再走入口被拒并给出提示；
        任务结束后 running=False 且按钮恢复；源码里不得再自己起任务线程。
        """
        import threading as _th
        from apps.convert_app import ConvertApp
        from toolkit_widgets import TaskRunner as _TaskRunner

        app = ConvertApp(tk.Frame(_ROOT))
        assert isinstance(app.task, _TaskRunner), "convert_app 没有用共享 TaskRunner"
        assert app.task.running is False, "新构造的 App 就处于忙碌态"

        started, release = _th.Event(), _th.Event()

        def slow():
            started.set()
            release.wait(5)

        app.task.run(slow)
        started.wait(5)
        assert app.task.running is True, "任务跑起来后 running 没置位"
        busy = [str(b.cget("state")) for b in (app.start_btn, app.restore_btn, app.clear_btn)]
        assert busy == ["disabled"] * 3, "忙碌时三个启动按钮没有全部禁用：%r" % busy

        _dialogs.clear()
        app._busy_name = "转换"
        assert app._begin_task("恢复备份") is False, "运行期没有拒绝第二个任务"
        # 拒绝提示是**投递**到 UI 泵的（线程纪律：不在调用栈里直接碰控件）→ 先泵一次
        for _ in range(60):
            _ROOT.update()
            if any("已有任务正在运行" in str(d[2]) for d in _dialogs):
                break
            time.sleep(0.02)
        assert any("已有任务正在运行" in str(d[2]) for d in _dialogs), \
            "拒绝时没有给出提示（应有『已有任务正在运行』）；实收 %r" % (_dialogs[-2:],)

        release.set()
        for _ in range(150):
            _ROOT.update()
            if not app.task.running:
                break
            time.sleep(0.02)
        assert app.task.running is False, "任务结束后 running 没复位"
        rest = [str(b.cget("state")) for b in (app.start_btn, app.restore_btn, app.clear_btn)]
        assert rest == ["normal"] * 3, "任务结束后按钮没恢复：%r" % rest

        # 失败路径：worker 抛异常 → on_error 回主线程报出来（不静默）+ 忙碌态复位
        def boom():
            raise RuntimeError("probe-boom")
        _dialogs.clear()
        app.task.run(boom, on_error=app._task_error)
        for _ in range(150):
            _ROOT.update()
            if not app.task.running:
                break
            time.sleep(0.02)
        assert app.task.running is False, "失败后 running 没复位"
        assert any(d[0] == "errbox" for d in _dialogs), \
            "worker 抛异常没有被报出来（应回主线程弹 errbox）；实收 %r" % (_dialogs[-2:],)
        rest2 = [str(b.cget("state")) for b in (app.start_btn, app.restore_btn, app.clear_btn)]
        assert rest2 == ["normal"] * 3, "失败后按钮没恢复：%r" % rest2

        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "apps", "convert_app.py"), encoding="utf-8") as f:
            src = f.read()
        assert "threading.Thread(" not in src, \
            "convert_app 里还在自己起任务线程（应统一走 task.run）"
    check("编码转换.任务壳（忙碌/重入/线程）统一走 TaskRunner；暂停与三类进度文案仍归 App",
          convert_task_shell_is_shared_taskrunner)

    def font_picker_fixes():
        """字体选择器本轮修的四处（用户 2026-09-14 实测报告）。

        ① 预览图固定 `330x130`、缩放只放大字号 → 放大就被裁："只有那一个角落能显示、
           缩放没什么卵用"；现在**图随内容增长**（放大 = 整张图变大，滚动条可用）。
        ② 描述文字 `wraplength` 取的是它**自己**的宽度（布局早期为 1）被 80 下限兜住
           → 一个字符一行；现在跟随**窗格**宽度。
        ③ 字形判据把"取不到字形"的字 **跳过**（`if b is None: continue`），于是日文字体
           hpsimplifiedjpan（有 永你好化、没有 汉测试…）被判 **✓ 中文**，而预览里那几个字
           是整字宽的空洞；现在缺一个简体字就判 `missing`（fail-closed），并在标题里
           点出"缺：汉测试…"。
        ④ 选择结果只活在内存里 → 现在点『选择』（含"浏览其他目录"）就写 `user.ltx`
           的 `[font]` 段，下次启动读回。
        """
        import tempfile
        import toolkit_platform
        from apps.font_pack_app import FontPackApp

        def _walk(w):
            yield w
            for c in w.winfo_children():
                yield from _walk(c)

        with tempfile.TemporaryDirectory() as d:
            real_app_dir = toolkit_platform.app_dir
            toolkit_platform.app_dir = lambda: d
            win = None
            try:
                app = FontPackApp(tk.Frame(_ROOT))
                app._browse_font()
                _ROOT.update_idletasks()
                _ROOT.update()
                wins = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
                assert wins, "字体选择器没建出来"
                win = wins[-1]
                widgets = list(_walk(win))
                lb = next((w for w in widgets if isinstance(w, tk.Listbox)), None)
                assert lb is not None, "找不到字体列表"
                # ★ 预览 label 是**挂在预览画布上的 tk.Label**：不能"取第一个 Canvas"——
                #   `add_clipped` 的视口自己也是个 Canvas（探针第一版就抓错了对象，
                #   于是误报"预览图没出来"）。
                preview_lbl = next((w for w in widgets
                                    if isinstance(w, tk.Label)
                                    and isinstance(w.master, tk.Canvas)), None)
                assert preview_lbl is not None, "找不到预览 label（挂在画布上的 tk.Label）"

                def _mark_line(sub):
                    for i in range(lb.size()):
                        line = lb.get(i)
                        if sub in line:
                            return i, line
                    return None, ""
                # 等分片检测把标记填进列表（每片 24 个 × after(25)）
                for _ in range(500):
                    _ROOT.update()
                    _, l = _mark_line("simsun.ttc")
                    if l and ("✓" in l or "⚠" in l):
                        break
                    time.sleep(0.02)

                i_jpan, l_jpan = _mark_line("hpsimplifiedjpan-regular.ttf")
                i_simsun, l_simsun = _mark_line("simsun.ttc")
                if i_jpan is not None:
                    assert "⚠" in l_jpan, "日文字体（缺简体字）应判缺字形：%r" % l_jpan
                if i_simsun is not None:
                    assert "✓" in l_simsun, "simsun 应判含中文字形：%r" % l_simsun

                def _select(idx):
                    lb.selection_clear(0, "end")
                    lb.selection_set(idx)
                    lb.event_generate("<<ListboxSelect>>")
                    _ROOT.update()

                def _desc_label(path):
                    base = os.path.basename(path)
                    return next((w for w in _walk(win) if isinstance(w, tk.ttk.Label)
                                 and base in str(w.cget("text") or "")), None)

                # ③ 预览标题要点出缺哪些字（不再让人猜那排空洞是什么）
                if i_jpan is not None:
                    _select(i_jpan)
                    _ROOT.update_idletasks()
                    dl = _desc_label("hpsimplifiedjpan-regular.ttf")
                    assert dl is not None, "选中后没有描述标签"
                    txt = str(dl.cget("text"))
                    assert "缺" in txt, "缺字形的字体，描述里应点出缺哪些字：%r" % txt
                    # ③b 用户口径 2026-09-14："日语的，标明是日语字体，然后那些缺简体的就上繁体。"
                    #     日语/繁体字体（缺的简体字都能用繁体顶）必须**与"疑似缺字形"分开标**，
                    #     并在标题里列出"简体→繁体"的对应 —— 预览行已经换成繁体字形在画。
                    assert "日语" in l_jpan, "日文字体应在列表里标明「日语」：%r" % l_jpan
                    assert "日语" in txt, "预览标题应标明是日语字体：%r" % txt
                    assert "→" in txt and "繁体" in txt, \
                        "标题应说明缺的简体用繁体显示（含 简体→繁体 对应）：%r" % txt
                    assert "漢" in txt, "标题应给出具体对应（如 汉→漢）：%r" % txt

                target = i_simsun if i_simsun is not None else 0
                _select(target)
                _ROOT.update_idletasks()
                assert getattr(preview_lbl, "image", None) is not None, \
                    "预览图没出来：%r" % str(_desc_label(lb.get(target).split("  [")[0])
                                             .cget("text") if i_simsun is not None else "")
                w1 = int(preview_lbl.image.width())

                # ② 描述文字按窗格宽度换行（不是 80 那种"一字一行"）
                dl2 = _desc_label(lb.get(target).split("  [")[0])
                assert dl2 is not None, "找不到描述标签"
                wl = int(str(dl2.cget("wraplength")) or 0)
                pane_w = int(dl2.master.winfo_width())
                print("        描述标签 wraplength=%d  窗格宽=%d  预览图宽=%d"
                      % (wl, pane_w, w1))
                assert wl >= 160, "wraplength 没跟上来（用户实测是 80 → 一字一行）：%r" % wl
                assert pane_w <= 1 or wl >= pane_w - 24, \
                    "wraplength(%d) 没有跟随窗格宽度(%d)" % (wl, pane_w)

                # ① 放大后**图**要变大（不再是固定 330 宽 + 裁字）
                # 按钮按"有 invoke 且文本匹配"找：缩放/选择都是 ttk.Button，
                # 而 isinstance(..., tk.Button) 只认 Tk 原生按钮（第一版就栽在这）。
                def _btn(text):
                    return next((w for w in widgets
                                 if hasattr(w, "invoke")
                                 and str(w.cget("text")) == text), None)
                plus = _btn("+")
                assert plus is not None, "找不到放大按钮"
                plus.invoke()
                _ROOT.update()
                w2 = int(preview_lbl.image.width())
                assert w2 > w1, "放大后预览图没有变大（%d → %d）" % (w1, w2)

                # ④ 点『选择』→ 落盘到（临时）user.ltx，下次启动能读回
                pick_btn = _btn("选择")
                assert pick_btn is not None, "找不到『选择』按钮"
                _select(target)
                pick_btn.invoke()
                saved = toolkit_platform.load_user_value("font", "path")
                assert saved and os.path.isfile(saved), \
                    "点『选择』没有把字体写进 user.ltx：%r" % saved
                assert os.path.isfile(os.path.join(d, "user.ltx")), \
                    "user.ltx 没有落在应用目录（应写到 app_dir 下）"
            finally:
                toolkit_platform.app_dir = real_app_dir
                try:
                    if win is not None and win.winfo_exists():
                        win.destroy()
                except Exception:
                    pass
    check("字体选择器.预览随内容增长 / 描述按窗格换行 / 缺字形判据一致 / 选择即落盘"
          " / 日文字体标明且缺简体用繁体显示",
          font_picker_fixes)

    print()
    print("=== 2. 直接调用入口方法（绕过线程启动器 / UI 事件） ===")

    # convert: 曾经在绕过线程启动器时读未初始化的 self._snap -> AttributeError
    c = built.get("convert")
    if c is not None:
        check("convert.run_restore (无快照)", c.run_restore)
        check("convert.run_clear_backup (无快照)", c.run_clear_backup)

        # is_excluded 是"排除模式匹配"，返回 False 表示**不排除**。旧断言直接
        # `lambda: c.is_excluded("x.xml")` 拿返回值当判据 —— 传字面量 "x.xml"
        # （既不是真实路径、排除模式也默认空）本就应该返回 False，于是这条断言
        # 与它想说的语义正好相反。这里改成显式传快照、正面核对排除语义：
        # 无模式不排除；`*.xml` 命中 → 排除；模式不含通配符时按"子串在相对路径里"命中。
        def convert_is_excluded():
            base = {"source_dir": "", "output_dir": "", "file_exts": ".xml",
                    "target_enc": "utf-8", "source_enc": "auto", "recursive": True,
                    "backup_files": False, "exclude_pattern": "", "is_single_file": False}
            assert c.is_excluded("x.xml", dict(base)) is False, "排除模式为空时不应排除任何文件"
            hit = dict(base, exclude_pattern="*.xml")
            assert c.is_excluded("sub/x.xml", hit) is True, "`*.xml` 应命中 .xml 文件"
            assert c.is_excluded("sub/x.txt", hit) is False, "`*.xml` 不应命中 .txt 文件"
            sub = dict(base, exclude_pattern="sub")
            assert c.is_excluded("sub/x.txt", sub) is True, "模式 `sub` 应按子串命中相对路径"
            assert c.is_excluded("other/y.txt", sub) is False, "模式 `sub` 不应命中无关文件"
        check("convert.is_excluded（按排除模式判定，返回 False 表示不排除）",
              convert_is_excluded)
        # 无路径时抛业务异常是设计行为（由 run_convert 兜住并计入 failed）
        check_raises("convert.get_files (无路径)", c.get_files, Exception)
    else:
        print("  SKIP convert（构造失败）")

    # text_extract: scripts/ltx 分支曾引用未定义的 SCRIPT_TRANSLATE_FUNC
    t = built.get("text")
    if t is not None:
        check("text._start (空路径)", t._start)
        check("text._browse(source)", lambda: t._browse(t.source_path))
        check("text._browse(target)", lambda: t._browse(t.target_path))
    else:
        print("  SKIP text（构造失败）")

    # fs: 清空/重绘链（含 merged=None 后 _render）
    f = built.get("fs")
    if f is not None:
        check("fs._clear_db", f._clear_db)
        check("fs._clear_files", f._clear_files)
        check("fs._refresh_pack", f._refresh_pack)

        def fs_trees_have_hbar():
            """FS 页三棵树都要有**横向**滚动条（用户 2026-09-15："fs 的滚动条呢？"）。

            页面上两个 `ScrollPanel` 本来就有横条，但三棵 `CanvasTree` 只有竖条，
            且 `scrollregion` 的 x 范围恒为 0 —— 树是**路径列表**，深路径/长文件名的
            尾巴就那么被裁掉了。三处都用同一个 `CanvasTree` 默认值（`hbar=True`）。
            """
            for name in ("db_ctree", "ctree", "pack_ctree"):
                ct = getattr(f, name, None)
                assert ct is not None, "找不到 %s" % name
                assert getattr(ct, "hbar", None) is not None, "%s 没有横向滚动条" % name
                assert str(ct.canvas.cget("xscrollcommand")), \
                    "%s 的 xscrollcommand 没接上" % name
        check("fs：三棵树都有横向滚动条（长路径的尾巴能看到）", fs_trees_have_hbar)

        def fs_panel_does_not_scroll_for_elastic_tree():
            """面板里的树是**弹性**的：装得下的时候，面板**不许能滚**。

            用户口径（2026-09-15，原话）："不是竖条的问题，**是不该滚动的时候也滚**。"
            —— 复现：DB 列表只有 1 行，鼠标在面板上滚滚轮，那一行会**被拖到面板底部**、
            上面留一大片空白（视频里 9 秒全程如此）。
            根因：`ScrollPanel` 默认 `fit="content"`（内容按自然高、装不下就滚），
            而树的最小请求高（px(120)=180px）把"内容自然高"顶到视口之上 ——
            哪怕树里只有 1 行。面板里装的是弹性内容，纵向就该**跟视口**（fit="viewport"）。
            判据（矮窗口 + 只有 1 行）：
              ① 面板视口 `yview() == (0.0, 1.0)` —— 竖向根本没有可滚内容；
              ② 面板 `try_scroll(滚轮事件)` **不消费**（返回假值）；
              ③ 真发一次滚轮事件后 `yview()` 不变（"不该滚的时候不滚"的落地判据）；
              ④ 只有 1 行时树自己的竖条也不出现；第一行贴在画布**顶部**。
            """
            import toolkit_theme as _th3
            import toolkit_widgets as _tw3
            # ★ 夹具放**独立 Toplevel**（第二个 FSToolApp 实例），绝不动共享根窗口：
            #   根窗口里已经堆了六个 App 的页面，给它 deiconify+设尺寸会**永久**改变
            #   后续用例（id 画布滚轮锁）看到的布局 —— 2026-09-15 实测踩到。
            win = tk.Toplevel(_ROOT)
            try:
                win.geometry("%dx%d" % (_th3.px(1100), _th3.px(430)))   # 矮窗口
                app2 = FSToolApp(win)
                win.update_idletasks(); win.update()
                app2.db_files = ["Z:/fake.sq_base"]
                app2._refresh_db_list()
                # ★ 布局要**跑到位**再看：`ScrollPanel` 还有 `after(600)` 的对齐回调，
                #   不等就量到中间态（那一版偶发地把"面板竖条冒出来"当成缺陷）。
                for _ in range(14):
                    win.update_idletasks(); win.update()
                    try:
                        app2.db_panel._fit_request()
                    except Exception:
                        pass
                    time.sleep(0.05)
                panel, tree = app2.db_panel, app2.db_ctree
                assert len(tree.rows) == 1, "DB 列表行数应为 1，实际 %d" % len(tree.rows)
                yv = tuple(round(v, 4) for v in panel.view.canvas.yview())
                assert yv == (0.0, 1.0), (
                    "面板竖向还有可滚内容（不该滚的时候能滚）：yview=%r —— "
                    "面板 body req %d / 视口 %d" % (yv, panel.body.winfo_reqheight(),
                                                    panel.view.canvas.winfo_height()))
                ev = type("E", (), {"delta": -120, "time": 123456, "widget": panel.view.canvas})()
                got = panel.view.try_scroll(ev)
                assert not got, "面板不该消费滚轮（没有可滚内容）：%r" % (got,)
                before = tuple(panel.view.canvas.yview())
                panel.view.canvas.yview_scroll(1, "units")     # 强行滚一下也不该动
                win.update_idletasks()
                assert tuple(panel.view.canvas.yview()) == before, \
                    "面板被滚动了：%r → %r" % (before, tuple(panel.view.canvas.yview()))
                # ④ 树自己的竖条：**装得下**才要求它不出现（夹具故意很矮，画布可能连
                #    一行都放不下 —— 那时树自己滚是**对**的，与"面板不该滚"是两件事）。
                if tree.canvas.winfo_height() >= tree.ROW_H + 2:
                    assert not (tree.vbar.winfo_manager() and tree.vbar.winfo_width() > 1), \
                        "画布装得下一行，树自己的竖条不该出现（画布高 %d / 行高 %d）" % (
                            tree.canvas.winfo_height(), tree.ROW_H)
                items = tree.canvas.find_all()
                assert items, "树上没有画任何东西"
                y0 = min(tree.canvas.bbox(it)[1] for it in items if tree.canvas.bbox(it))
                assert y0 < tree.canvas.winfo_height() // 2, \
                    "第一行跑到画布下半部了（上面空一大片）：y=%d / 画布高=%d" % (
                        y0, tree.canvas.winfo_height())
                assert _tw3 is not None
            finally:
                try:
                    win.destroy()
                except Exception:
                    pass
        check("fs：弹性树的面板在没有可滚内容时**不许滚**（单行贴顶部）",
              fs_panel_does_not_scroll_for_elastic_tree)
    else:
        print("  SKIP fs（构造失败）")

    # ── 用户规则（2026-09-15 原话："没有滚动条就不应该滚动。……滚动代码只在有滚动
    #    条的地方有。"）：**条子没显示的地方，一律不许滚** ────────────────────
    # 三类都查：ScrollViewport（面板/页面，走 try_scroll 路由）、CanvasTree（自带绑定）、
    # **LogBox/Text**（Tk 的类绑定自带滚轮，根本不看我们的条子 —— 必须控件级拦）。
    def no_scroll_without_bar():
        import toolkit_widgets as _tw4
        win = tk.Toplevel(_ROOT)
        try:
            win.deiconify()                    # ★ withdrawn 的窗口里 ismapped 恒 0
            win.geometry("%dx%d" % (_tw4.px(420), _tw4.px(240)))
            fake = type("E", (), {"delta": -120, "time": 555001, "widget": win})()

            # ① Text（LogBox）：内容远超视口 → 条子真的看得见 → 不拦、能滚
            log = _tw4.LogBox(win, height=6, scrollbar=True)
            log.pack(fill="both", expand=True)
            for i in range(300):
                log.add("line %03d" % i)
            log._flush()                       # LogBox 是**批量**插入（after(80)），必须催一次
            for _ in range(8):
                win.update_idletasks(); win.update()
            assert _tw4.bar_shown(log._vbar), "内容远超视口时条子本该看得见"
            assert log._wheel_guard(fake) is None, "条子看得见时不该拦（正常滚动）"
            # 强制把条子藏起来（模拟"条子没了"的一切情形）→ 必须拦住、且真的滚不动
            log._vbar.pack_forget()
            win.update_idletasks(); win.update()
            # 自检**不许依赖被测函数**（bar_shown 正是被测对象）：直接看控件真实状态
            assert not log._vbar.winfo_manager() and not log._vbar.winfo_ismapped(), \
                "条子没藏成功，这条锁等于没跑"
            assert log._wheel_guard(fake) == "break", "没有滚动条却还允许滚（用户规则要求 break）"
            before = tuple(log.yview())
            log.event_generate("<MouseWheel>", delta=-120, x=10, y=10, when="now")
            for _ in range(8):
                win.update_idletasks(); win.update()
            assert tuple(log.yview()) == before, \
                "条子藏起来后滚轮仍然滚动了：%r → %r" % (before, tuple(log.yview()))

            # ② CanvasTree：多行 → 条子可见 → 能滚；藏起来 → 一下都不许动
            class _N:
                def __init__(self, n):
                    self.name = n; self.path = n; self.is_dir = False; self.size = 0
                    self.children = {}
                def add(self, c):
                    self.children[c.name] = c
                def dir_state(self):
                    return None
            root = _N("")
            for i in range(40):
                root.add(_N("f%02d.xml" % i))
            tree = _tw4.CanvasTree(win, with_chk=False)
            tree.get().pack(fill="both", expand=True)
            tree.set_root(root)
            for _ in range(8):
                win.update_idletasks(); win.update()
            assert _tw4.bar_shown(tree.vbar), "40 行装不下时树的条子本该看得见"
            assert tree.vbar.winfo_ismapped(), "树的条子没映射"
            tree.vbar.pack_forget()
            win.update_idletasks(); win.update()
            assert not tree.vbar.winfo_manager() and not tree.vbar.winfo_ismapped(), \
                "树的条子没藏成功"
            tb = tuple(tree.canvas.yview())
            tree._on_wheel(fake)
            win.update_idletasks(); win.update()
            assert tuple(tree.canvas.yview()) == tb, \
                "树的条子藏起来后 _on_wheel 仍然滚了：%r → %r" % (tb, tuple(tree.canvas.yview()))

            # ③ ScrollViewport：故意造成"能滚"的 scrollregion，再藏条子 → try_scroll 必须拒绝
            vp = _tw4.ScrollViewport(win, fit="content")
            vp.pack(fill="both", expand=True)
            _tw4.ttk.Label(vp.content, text="x" * 2000).pack()
            for _ in range(8):
                win.update_idletasks(); win.update()
            vp.canvas.configure(scrollregion=(0, 0, vp.canvas.winfo_width() + 400,
                                              vp.canvas.winfo_height() + 800))
            win.update_idletasks(); win.update()
            if _tw4.bar_shown(vp.vbar):
                vp.vbar.pack_forget()
                win.update_idletasks(); win.update()
            assert not vp.vbar.winfo_manager() and not vp.vbar.winfo_ismapped(), \
                "视口的条子没藏成功"
            vb = tuple(vp.canvas.yview())
            got = vp.try_scroll(fake)
            assert not got, "视口没有可见的条子却消费了滚轮（%r）" % (got,)
            assert tuple(vp.canvas.yview()) == vb, \
                "视口没有可见的条子却滚了：%r → %r" % (vb, tuple(vp.canvas.yview()))
        finally:
            try:
                win.destroy()
            except Exception:
                pass
    check("滚轮：**没有滚动条的地方一律不许滚**（Text / 树 / 视口，三类都验）",
          no_scroll_without_bar)

    # ── 用户 2026-09-17 报："加载上DB之后也显示'加载中'" ──────────────────────
    # 根因：`TaskRunner.run(status=...)` 写的是运行期文案，而 `_finish()` 只在调用方
    # **显式给了** final_status 时才改写 —— fs_app 的成功路径一个字都没写，于是
    # "加载中…"永远留在状态栏（失败路径反而会写，所以只在成功时露出来）。契约三条：
    #   ① 谁都没写收尾文案 → **恢复任务开始前的状态**（不许停在"…中"）；
    #   ② on_error 写的失败状态优先，不被恢复覆盖；
    #   ③ App 自己在完成回调里 set_status 的（"完成 · N 条"那种）优先，不被覆盖。
    def task_finish_never_leaves_running_text():
        import time as _t
        import toolkit_widgets as _tw5          # 各段各自 import（本文件按段隔离）

        app = built.get("fs")
        assert app is not None, "fs App 没构造出来"
        lbl = app.status_lbl

        def pump_until_idle(times=300):
            for _ in range(times):
                _ROOT.update_idletasks(); _ROOT.update()
                if not app.task.running:
                    return True
                _t.sleep(0.01)
            return False

        def run_task(work, status, on_error=None, final_status=None):
            ok = app.task.run(work, status=status, on_error=on_error,
                              final_status=final_status)
            assert ok, "任务没能启动（上一个还没结束？）"
            assert pump_until_idle(), "任务 3 秒内没结束"
            for _ in range(6):
                _ROOT.update_idletasks(); _ROOT.update()
            return lbl.cget("text")

        def set_idle():
            lbl.configure(text="就绪", style=_tw5.status_style_name("idle"))
            # ★ 故意**不同步** `_status_text`：真实 App 就是这样 —— 标签上的"就绪"是
            #   控件构造时写的，而 TaskRunner 从没写过状态（内部是空串）。恢复时必须
            #   用 `idle_status` 兜底，否则任务结束后状态栏会变成**空**（实测到的副作用）。
            app.task._status_text, app.task._status_kind = "", "idle"

        # ① 没人写收尾 → 恢复前置状态（用户报的就是这条）
        set_idle()
        got = run_task(lambda: _t.sleep(0.02), "加载中…")
        assert got == "就绪", \
            "任务结束后仍停在运行期文案（用户报的就是这个）：状态栏=%r" % (got,)

        # ② 失败状态优先
        def _boom():
            raise RuntimeError("模拟加载失败")

        got = run_task(_boom, "加载中…",
                       on_error=lambda e: app.task.set_status("加载失败: %s" % e, "err"))
        assert got.startswith("加载失败"), "失败状态被收尾覆盖了：%r" % (got,)

        # ③ App 自己在完成回调里写的状态优先
        def _self_report():
            _t.sleep(0.02)
            app._ui(lambda: app.task.set_status("完成 · 3 条", "ok"))

        got = run_task(_self_report, "提取中…")
        assert got == "完成 · 3 条", "App 自己写的完成文案被覆盖了：%r" % (got,)
        set_idle()
    check("任务壳：收尾后**不许停在「…中」**（没写收尾就恢复前置状态；失败/自报优先）",
          task_finish_never_leaves_running_text)

    # xml: 模式判定必须取自结果数据（行内 mode 与界面变量背离时曾 KeyError: lines_a）
    x = built.get("xml")
    if x is not None:
        import apps.xml_compare_app as xm

        stats_row = {"rel": "a.xml", "mode": "stats", "consistent": False,
                     "lines_a": 3, "lines_b": 4, "ids_a": 2, "ids_b": 2}

        def only_text_rows_ui_says_stats():
            x.mode_var.set(xm.MODE_STATS)
            x.results = [dict(stats_row, mode="text")]
            x._refresh_tree()

        def mixed_rows_ui_says_stats():
            x.mode_var.set(xm.MODE_STATS)
            x.results = [stats_row, {"rel": "b.xml", "mode": "text", "consistent": False,
                                     "ids_a": 1, "ids_b": 1, "only_a": ["i1"], "only_b": [],
                                     "text_diff": []}]
            x._refresh_tree()

        def stats_rows_ui_says_stats():
            x.mode_var.set(xm.MODE_STATS)
            x.results = [stats_row]
            x._refresh_tree()

        check("xml._refresh_tree (结果含 text 行 / 界面=stats)", only_text_rows_ui_says_stats)
        check("xml._refresh_tree (text 与 stats 混排)", mixed_rows_ui_says_stats)
        check("xml._refresh_tree (纯 stats 行)", stats_rows_ui_says_stats)
        check("xml._on_mode_change", x._on_mode_change)

        def id_box_wheel_follows_unified_rules():
            """id 差异画布的滚轮必须与全局规则一致（用户口径 2026-09-13/14）。

            > "一次只有一个滚动条能动。""隐藏的滚动条，代码里不算滚动条。"

            老实现是无条件 `yview_scroll` + 无条件 `"break"`：id 列表只有几行
            （滚动条被隐藏）时，滚轮被它吃掉、**外层页面反而滚不动** —— 与
            `CanvasTree._on_wheel` / `ScrollViewport.try_scroll` 那条规则不一致。
            判据 = **真调那个绑定下去的回调**，三种情形逐条断言：
              ① 装得下 → 返回 None（冒泡给外层）且 yview 不动；
              ② 装不下 → 返回 "break" 且 yview 真的动了；
              ③ 同一次事件已被别人声明独占（`wheel_claim` 先跑）→ 撤销自己的滚动、
                 仍然 "break"（不让同一次滚轮动两个滚动条）。
            """
            import types
            import toolkit_widgets as _W
            # 绑定下去的必须是**这个方法**（不是内联 lambda），否则统一规则没法复用
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "apps", "xml_compare_app.py"),
                      encoding="utf-8") as _fh:
                src = _fh.read()
            assert 'cv.bind("<MouseWheel>", self._id_wheel)' in src, \
                "id 画布的滚轮没走 _id_wheel（又变回内联 lambda？）"

            holder = tk.Frame(_ROOT)
            win = tk.Toplevel(_ROOT)
            try:
                # ★ 夹具必须在**已映射**的窗口里：`bar_shown()` 四看里含 `winfo_ismapped()`，
                #   而 withdrawn 的 `_ROOT` 里所有子控件 ismapped 恒 0 → 一律被判"没有条子"。
                win.deiconify()
                win.geometry("%dx%d" % (_W.px(520), _W.px(360)))
                holder = tk.Frame(win)
                holder.pack(fill="both", expand=True)
                box = x._build_id_list(holder, [("仅 A", "id%d" % i) for i in range(3)],
                                       height=200)
                _ROOT.update_idletasks(); _ROOT.update()
                cv = x._id_canvas
                assert box is not None and cv is not None, "id 列表没建出来"

                def wheel(delta, stamp):
                    return x._id_wheel(types.SimpleNamespace(delta=delta, time=stamp,
                                                             widget=cv))
                # ① 装得下：不吃事件
                r1 = wheel(-120, 111)
                assert r1 is None, "装得下时不该吃滚轮（应返回 None 冒泡），实际 %r" % (r1,)
                # ② 装不下：真滚 + break
                box2 = x._build_id_list(holder, [("仅 A", "id%d" % i) for i in range(200)],
                                        height=120)
                for _ in range(8):
                    win.update_idletasks(); win.update()
                cv = x._id_canvas
                # ★ 用户规则（2026-09-15）：**有滚动条的地方才滚**。200 条 id 装不下
                #   → 这里条子**必须真的出现**（装不下却没有条，本身就是用户报的那类缺陷）；
                #   条子在 → 滚轮照常滚、照常吃事件。
                assert _W.bar_shown(getattr(x, "_id_sb", None)), \
                    "内容装不下（200 条 id）却没有可见的滚动条 —— 这正是用户报的缺陷"
                before = cv.yview()
                r2 = wheel(-120, 222)
                after = cv.yview()
                assert r2 == "break", "真的滚动了就该吃掉事件，实际 %r" % (r2,)
                assert after != before, "返回 break 却没真的滚动：%r → %r" % (before, after)
                # ②b 条子被藏起来 → 一下都不许滚（哪怕 scrollregion 还很大）
                _hide_bar = True
                # ③ 独占：同一次事件（time 相同）已被别人声明 → 撤销自己的滚动
                _W._WHEEL_CLAIM[0] = 333
                before3 = cv.yview()
                r3 = wheel(-120, 333)
                assert r3 == "break", "被别人声明后仍要吃掉这次事件，实际 %r" % (r3,)
                assert cv.yview() == before3, \
                    "同一次滚轮已被别人声明，这里必须撤销自己的滚动：%r → %r" % (
                        before3, cv.yview())
                # ③b 条子被藏起来 → 一下都不许滚、也不许吃事件（用户规则 2026-09-15：
                #     "滚动代码只在有滚动条的地方有"）。放在独占判据**之后**，
                #     否则条子已经藏了，③ 的"被别人声明仍要吃事件"会拿到 None。
                if _hide_bar:
                    x._id_sb.pack_forget()
                    win.update_idletasks(); win.update()
                    assert not x._id_sb.winfo_manager() and not x._id_sb.winfo_ismapped(), \
                        "条子没藏成功，这条判据等于没跑"
                    before4 = cv.yview()
                    r4 = wheel(-120, 224)
                    assert r4 is None, "没有滚动条却还吃事件，实际 %r" % (r4,)
                    assert cv.yview() == before4, \
                        "没有滚动条却滚了：%r → %r" % (before4, cv.yview())
                assert box2 is not None
            finally:
                _W._WHEEL_CLAIM[0] = None
                for _w in (holder, win):
                    try:
                        _w.destroy()
                    except Exception:
                        pass
        check("滚轮：id 差异画布与全局规则一致（能滚才吃 + 独占声明）",
              id_box_wheel_follows_unified_rules)

        # 切换比较模式会**重建 Treeview**（列集合随模式变）。重建后必须重新
        # grid、重新绑事件、重新设滚动钩子与行着色 tag —— 曾漏掉这一步，于是
        # 用户切一次模式，表格区就变空、滚动条失效、双击详情与选中明细全废，
        # 而当时的探针只数了 get_children() 的行数，**看不见"控件不在布局里"**。
        def mode_switch_keeps_tree_usable():
            def snap():
                t = x.tree                     # 每次重取：切模式会换对象
                return (t.winfo_manager(), bool(t.grid_info()),
                        bool(str(t.cget("yscrollcommand"))),
                        bool(t.bind("<Double-1>")),
                        bool(t.bind("<<TreeviewSelect>>")),
                        bool(str(t.tag_configure("diff", "foreground"))))
            before = snap()
            assert before[0] == "grid", "重建前就不在 grid 里: %r" % (before,)
            vals = list(x.cb_mode.cget("values"))
            if len(vals) > 1:
                x.cb_mode.set(vals[-1])
                x._on_mode_change()
                x.root.update_idletasks()
                after = snap()
                assert all(after), "切换模式后布局/绑定/配色丢失: %r" % (after,)
                x.cb_mode.set(vals[0])
                x._on_mode_change()
                x.root.update_idletasks()
                assert all(snap()), "切回后布局/绑定/配色丢失"
        check("xml.切换模式后 Treeview 仍在布局中（重建后必须重新 grid/绑定）",
              mode_switch_keeps_tree_usable)

        def plugin_mode_row_safe():
            x.results = [{"rel": "x.xml", "consistent": False,
                          "mode": "某种插件模式", "plugin_a": 1, "plugin_b": 2}]
            rid = x.tree.insert("", "end", values=("x.xml",))
            x.tree.selection_set(rid)
            x._on_row_select(None)             # 曾 KeyError: 'ids_a'
        check("xml.插件模式的结果行被选中时不抛 KeyError", plugin_mode_row_safe)

        # 明细的 id 复制：**逐条**复制，而不是「复制全部 id」。
        # 需求变更记录：旧版散装工具有「复制全部 id」，中间版本按用户要求恢复过，
        # 随后用户判定"复制全部非常不好用"，改为明细里每条 id 各一个「复制id」按钮。
        # 这条锁住三件事：① 筛选行有「导出为表格」；② 全窗没有「复制全部 id」；
        # ③ 选中含 id 差异的行后，按钮数与 id 数一致，且点一下只复制那一个 id。
        def per_id_copy_buttons():
            def walk(w, out):
                for c in w.winfo_children():
                    out.append(c)
                    walk(c, out)
                return out

            def labels(w):
                return [str(c.cget("text")) for c in walk(w, [])
                        if c.winfo_class() in ("Button", "TButton")]

            assert "导出为表格" in labels(x.cb_filter.master), \
                "筛选行里没有「导出为表格」"
            assert not any("复制全部" in t for t in labels(x.root)), \
                "「复制全部 id」按钮仍然存在"

            x.mode_var.set(xm.MODE_STATS)
            row = {"rel": "probe.xml", "consistent": False, "mode": "stats",
                   "lines_a": 1, "lines_b": 2, "ids_a": 1, "ids_b": 2,
                   "only_a": ["pid_a"], "only_b": ["pid_b1", "pid_b2"],
                   "count_diff": [("pid_c", 1, 2)], "text_diff": [("pid_t", "x", "y")]}
            x.results = [row]
            x._refresh_tree()
            kids = x.tree.get_children()
            assert kids, "表格里没有行"
            x.tree.selection_set(kids[0])
            x._on_row_select(None)
            x.root.update_idletasks()
            btns = [c for c in walk(x._id_frame, [])
                    if c.winfo_class() in ("Button", "TButton")
                    and str(c.cget("text")) == "复制id"]
            assert len(btns) == 5, "逐条复制按钮数 %d != 5" % len(btns)
            btns[0].invoke()
            x.root.update_idletasks()
            copied = x.root.clipboard_get()
            assert copied == "pid_a", "点一条应只复制那一个 id，实际 %r" % copied
        check("xml.明细逐条「复制id」（无「复制全部 id」）且筛选行有「导出为表格」",
              per_id_copy_buttons)
    else:
        print("  SKIP xml（构造失败）")

    # video / font: 只调不涉及外部程序的入口
    v = built.get("video")
    if v is not None:
        check("video._set_ui_state", lambda: v._set_ui_state(False))
        check("video._cancel_convert (无进程)", v._cancel_convert)
    else:
        print("  SKIP video（构造失败）")

    fp = built.get("font")
    if fp is not None:
        check("font._lang_changed", lambda: fp._lang_changed("自定义"))
        check("font._lang_changed (eng)", lambda: fp._lang_changed("eng"))
        check("font._suf_changed", lambda: fp._suf_changed("自定义"))
        check("font._suf_changed (无)", lambda: fp._suf_changed("无"))
        check("font._open_out (无输出)", fp._open_out)
        check("font task 已接入统一任务壳", lambda: fp.task is not None)
    else:
        print("  SKIP font（构造失败）")

    print()
    print("=== 3. TaskRunner 生命周期（能力 1） ===")
    _check_taskrunner()

    print()
    print("=== 4. toolkit_textio 编码判定（能力 2，统一口径） ===")
    _check_textio()

    print()
    print("=== 5. toolkit_platform 平台层（能力 4） ===")
    _check_platform()

    print()
    print("=== 6. toolkit_constants 业务常量表（能力 5） ===")
    _check_constants()

    print()
    print("=== 7. HiDPI 缩放与标题栏统一 ===")
    _check_hidpi_and_titlebar()

    print()
    print("=== 8. 性能不变量（重活必须在工作线程 / 明细控件必须虚拟化） ===")
    _check_perf_invariants()

    print()
    print("=== 9. toolkit 兼容层契约（__all__ 与 import 逐一对齐） ===")
    _check_reexport_contract()

    print()
    print("=== 10. 日志保留（预发布不清理 / 正式版 100 上限）与管线并发/不静默 ===")
    _check_log_retention()
    _check_log_pipeline()

    print()
    print("=== 11. 残留防腐（重复实现 / 游离脚本 / temp 盲区） ===")
    _check_no_legacy_residue()

    print()
    print("=== 12. 输入框焦点/选中收敛（点空白取消、切页不残留） ===")
    _check_input_focus_policy()

    print()
    print("=== 结果 ===")
    if _FAILURES:
        print("失败明细：")
        for line in _FAILURES:
            print("  - " + line)
    print("PASS %d  FAIL %d" % (_PASS, _FAIL))
    print("（对话框被调用 %d 次，均已打桩未阻塞）" % len(_dialogs))
    return 1 if _FAIL else 0


def _check_hidpi_and_titlebar():
    """HiDPI 与标题栏主题的回归锁。

    这两条都踩过：
      * DPI：进程若不是 per-monitor 感知，Windows 会把整个窗口位图按系统缩放
        拉伸 —— 在 2.5K/150% 屏上就是"发糊"，而且旧代码不检查 HRESULT，
        失败也照样写"已应用"。
      * 像素常量：字体磅值由 Tk 按 scaling 换算，**像素值不会**。150% 屏上正文
        行高是 32px，而写死的 ROW_H=24 会让行比字矮、文字被裁。
      * 标题栏：`apply_titlebar` 以前只有 Hub 调，`build_gui` 与 `dialog_window`
        弹窗都漏了 —— 暗色主题下顶着一条亮色标题栏。
    """
    import tkinter.font as tkfont
    from tkinter import ttk
    import toolkit_base as tb
    import toolkit_theme as th
    import toolkit_widgets as W

    # 探针自己保证缩放已按本机 DPI 校正并重刷样式：宿主里这两步由
    # apply_tk_defaults 负责，而探针不经过 Hub，App 也刻意不碰主题。
    th.sync_tk_scaling(_ROOT)
    th.apply_theme()

    check("HiDPI：进程 DPI 感知状态有如实记录", lambda: bool(tb.HIDPI_STATUS))
    check("HiDPI：ui_scale() 为正数且 px() 单调",
          lambda: th.ui_scale() > 0 and th.px(100) > th.px(10) >= 0)

    def row_fits_font():
        ct = W.CanvasTree(tk.Frame(_ROOT), with_chk=True)
        try:
            need = tkfont.Font(font=th.T["font"]).metrics("linespace")
            assert ct.ROW_H >= need, "ROW_H=%d < 正文行高=%d" % (ct.ROW_H, need)
            assert ct.CHK >= 12 and ct.INDENT > ct.CHK
        finally:
            ct.frame.destroy()
    check("HiDPI：CanvasTree 行高容得下正文（不再裁字）", row_fits_font)

    def tree_row_items_aligned_to_checkbox():
        """行内三角/文件名必须与**勾选框**对齐（用户口径 2026-09-14）。

        > "这里图片上能看到勾选框和三角、文字是错位的，统一以勾选框为准。"

        现象（150% 屏实测，改前）：三角写死在 `(x-12, y+12)`、文件名写死在 `y+12`，
        而勾选框中心在 17.5 → 两者都高 5.5px；三角 bbox.x=-4，**左半边被画到画布外**。
        判据：真建树 + 真 populate + 读**画布图元的真实 bbox**（不是查源码）：
          ① 三角中心 == 勾选框中心（±1px，Tk 的 bbox 取整会差 0.5）；
          ② 文件名中心 == 勾选框中心（±1px）；
          ③ 三角**整条在画布内**（bbox.x ≥ 0）且不与勾选框重叠（右边界 < 勾选框左边界）。
        """
        import toolkit_widgets as _W

        class _N:
            def __init__(self, name, is_dir=False, path=""):
                self.name, self.is_dir, self.path = name, is_dir, path
                self.size, self.children, self.checked = 10, {}, False

            def dir_state(self):
                return None

        host = tk.Frame(_ROOT)
        ct = _W.CanvasTree(host, with_chk=True)
        try:
            host.pack(fill="both", expand=True)
            root = _N("textures", True, "textures")
            for nm in ("aaz", "act", "bmp"):
                root.children[nm] = _N(nm, False, "textures/" + nm)
            ct.set_root(root)
            ct._expanded.add(root)
            ct.populate()
            ct.canvas.configure(width=420, height=ct.ROW_H * 4)
            _ROOT.update_idletasks()
            _ROOT.update()
            c = ct.canvas
            bad = []
            for row in range(len(ct.rows)):
                y0 = row * ct.ROW_H
                band = [it for it in c.find_all() if c.bbox(it)
                        and c.bbox(it)[1] >= y0 - 6 and c.bbox(it)[3] <= y0 + ct.ROW_H + 6]
                box = next((c.bbox(it) for it in band
                            if c.type(it) == "rectangle"
                            and c.bbox(it)[2] - c.bbox(it)[0] >= ct.CHK - 2), None)
                if box is None:
                    continue
                box_cy = (box[1] + box[3]) / 2.0
                arrow = next((c.bbox(it) for it in band if c.type(it) == "polygon"), None)
                node = ct.rows[row][0]
                name_txt = next((c.bbox(it) for it in band if c.type(it) == "text"
                                 and c.itemcget(it, "text") == node.name), None)
                if arrow is not None:
                    if abs((arrow[1] + arrow[3]) / 2.0 - box_cy) > 1:
                        bad.append(("三角中心", row, arrow, box_cy))
                    if arrow[0] < 0 or arrow[2] > box[0]:
                        bad.append(("三角越界/压勾选框", row, arrow, box))
                if name_txt is not None:
                    if abs((name_txt[1] + name_txt[3]) / 2.0 - box_cy) > 1:
                        bad.append(("文件名中心", row, name_txt, box_cy))
            assert not bad, "树行内元素与勾选框错位（行/实测/期望）：%r" % (bad[:4],)
        finally:
            try:
                host.destroy()
            except Exception:
                pass
    check("HiDPI：树行内三角/文件名与勾选框对齐（三角整条在画布内、不压框）",
          tree_row_items_aligned_to_checkbox)

    def tree_has_usable_hbar():
        """树的横/竖滚动条必须**撑满、该收就收、该出就出**（用户 2026-09-15 两问）。

        > "fs的滚动条呢？"  → 树只有竖条、且 scrollregion 的 x 范围恒为 0（横向滚不动）
        > "我竖的滚动条是咋回事？" → 我第一版把横条 pack 在 `expand=True` 的画布**之后**，
        >   它只能分到残渣：实测恒为 **44x15 且常驻可见**（内容装得下也不收），
        >   白白多占 15px 高，还会把面板内容顶出去、让面板自己的竖条也冒出来
        >   （= 用户看到的"竖的滚动条不对劲"）。

        判据（真建树 + 真读几何，四条缺一不可）：
          ① **装得下**（3 行短名、宽高都够）→ 两条都收起（`winfo_manager() == ""`）；
          ② **超高**（80 行）→ 竖条可见且**高 ≈ 容器高**（不是残渣）；
          ③ **超宽**（长名字）→ 横条可见且**宽 ≈ 容器宽**（不是残渣）；
          ④ 两向接线：文本 → 条子（`get()` 跟上）、条子 → 文本（调 command 后真移动）。
        """
        import toolkit_widgets as _W
        import toolkit_theme as _th

        class _N:
            def __init__(self, name, is_dir=False, path=""):
                self.name, self.is_dir, self.path = name, is_dir, path
                self.size, self.children, self.checked = 10, {}, False

            def dir_state(self):
                return None

        # ★ 量滚动条必须给它一块**真空间**：探针的根窗口里已经塞了六个 App 的页面，
        #   再往根上 pack 一个固定尺寸的夹具会被挤成 1x1 → 画布恒"装不下" → 判据全假。
        #   所以夹具放**独立 Toplevel**（自己的窗口，自己的几何）。
        win = tk.Toplevel(_ROOT)
        win.geometry("%dx%d" % (_th.px(240), _th.px(160)))
        host = tk.Frame(win, width=_th.px(220), height=_th.px(120))
        host.pack_propagate(False)          # 固定窄容器：不这样会被 canvas 请求宽撑开
        ct = _W.CanvasTree(host, with_chk=True)
        try:
            host.pack()
            ct.get().pack(fill="both", expand=True)

            def fill(rows, long_name):
                root = _N("gamedata", True, "gamedata")
                for i in range(rows):
                    nm = ("f%03d_" % i) + ("n" * 40 if long_name else "n") + ".xml"
                    root.children[nm] = _N(nm, False, "gamedata/" + nm)
                ct.set_root(root)
                ct._expanded.add(root)
                ct.populate()
                _ROOT.update_idletasks()
                _ROOT.update()

            # 注：探针的根窗口是 withdraw 的，`winfo_ismapped()` 恒为 0 —— 这里只能看
            # "有几何管理器 + 拿到真实尺寸"（真机可见性由截图那张表核对）。
            def vis(bar):
                return bool(bar is not None and bar.winfo_manager()
                            and bar.winfo_width() > 1)

            assert ct.hbar is not None, "树没有横向滚动条"
            assert str(ct.canvas.cget("xscrollcommand")), "xscrollcommand 没接上"
            slack = _th.px(24)

            fill(3, False)                  # ① 装得下 → 两条都收起
            assert not vis(ct.vbar) and not vis(ct.hbar), \
                "内容装得下时两条都不该露出来（竖 %r / 横 %r）" % (
                    ct.vbar.winfo_manager(), ct.hbar.winfo_manager())

            fill(80, False)                 # ② 超高 → 竖条可见且撑满 (可能同时超宽→也允许横条)
            assert vis(ct.vbar), "80 行还不出现竖滚动条"
            assert ct.vbar.winfo_height() >= ct.frame.winfo_height() - slack, \
                "竖条没撑满（残渣）：条高 %d / 容器高 %d" % (
                    ct.vbar.winfo_height(), ct.frame.winfo_height())

            fill(80, True)                  # ③ 超宽 → 横条可见且撑满
            assert vis(ct.hbar), "超宽内容还不出现横滚动条"
            assert ct.hbar.winfo_width() >= ct.frame.winfo_width() - slack, \
                "横条没撑满（分到残渣了？）：条宽 %d / 容器宽 %d" % (
                    ct.hbar.winfo_width(), ct.frame.winfo_width())
            assert ct.canvas.xview()[1] < 1.0, \
                "超宽内容下横向没得滚（scrollregion 的 x 范围还是 0？）：%r" % (ct.canvas.xview(),)
            # ④ 两向接线
            ct.canvas.xview_moveto(1.0)
            _ROOT.update_idletasks()
            assert abs(ct.hbar.get()[1] - ct.canvas.xview()[1]) < 1e-6, \
                "条子没跟上文本：条子 %r 文本 %r" % (ct.hbar.get(), ct.canvas.xview())
            cmd = str(ct.hbar.cget("command"))
            assert cmd, "横条的 command 没接上"
            _ROOT.tk.call(cmd, "moveto", 0.0)
            _ROOT.update_idletasks()
            assert ct.canvas.xview()[0] == 0.0, "拖横条没能把文本移回最左：%r" % (ct.canvas.xview(),)
        finally:
            try:
                win.destroy()
            except Exception:
                pass

    def _walk_dirs(node):
        for c in node.children.values():
            if c.is_dir:
                yield c
                yield from _walk_dirs(c)

    check("HiDPI：树的横/竖滚动条撑满、该收就收、该出就出（含两向接线）",
          tree_has_usable_hbar)

    def treeview_rowheight_scaled():
        got = int(ttk.Style().lookup("Treeview", "rowheight") or 0)
        assert got == th.px(24), "Treeview rowheight=%d，应为 px(24)=%d" % (got, th.px(24))
    check("HiDPI：Treeview 行高按缩放换算", treeview_rowheight_scaled)

    def dialog_scaled_and_dark():
        geo = W._scale_geometry("650x450")
        assert geo == "%dx%d" % (th.px(650), th.px(450)), geo
        win = W.dialog_window(tk.Frame(_ROOT), "probe", size="650x450")
        try:
            win.update_idletasks()
            if sys.platform == "win32":
                import ctypes
                top = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)
                v = ctypes.c_int(-1)
                hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    top, 20, ctypes.byref(v), ctypes.sizeof(v))
                assert hr == 0 and v.value == 1, \
                    "dialog_window 的标题栏没有跟随主题（hr=%d 值=%d）" % (hr, v.value)
        finally:
            win.destroy()
    check("标题栏：dialog_window 弹窗也跟随主题（且尺寸按缩放）",
          dialog_scaled_and_dark)


def _check_perf_invariants():
    """性能不变量 —— 全都用**调用次数/控件个数**判定，不用墙钟时间（避免 flaky）。

    这三条都是实测出来的真实卡顿，且都是"看着对、用起来卡"的类型：
      * fs 勾选一个未加载的包：解析 3 万条目要 1.15 秒，若在 UI 线程跑就整屏卡住；
      * XML 明细里给每条 id 建按钮：200 条差异换选一行要 1.48 秒；
      * XML 表格 detail 列调完整明细渲染：1 万行填充多花约 240ms。
    """
    import apps.xml_modes as xm

    # ① fs：勾选未加载的包必须**立刻返回**并把解析交给任务线程
    def fs_load_is_async():
        import tempfile as _tf
        import shutil as _sh
        import stalker_fs as _fs
        from apps.fs_app import FSToolApp
        tmp = _tf.mkdtemp(prefix="perf_probe_")
        try:
            p = os.path.join(tmp, "big.db")
            with open(p, "wb") as f:
                f.write(_fs.pack_db([("d/f%05d.txt" % i, b"x" * 20, False)
                                     for i in range(4000)], "xdb"))
            app = FSToolApp(tk.Frame(_ROOT))
            app.db_files = [p]
            app._refresh_db_list()
            node = app.db_ctree.root.children[os.path.basename(p)]
            app._db_toggle(node)
            assert app.task.running is True, "勾选后没有启动后台任务（说明是同步解析）"
            assert not app.loaded, "勾选后立刻就有 loaded —— 那不是异步"
            for _ in range(600):
                _ROOT.update()
                time.sleep(0.01)
                if not app.task.running:
                    break
            assert app.loaded.get(p) is not None, "后台任务没有把包加载出来"
            assert app.loaded[p].dir_state() is True, "勾选语义没有落地"
        finally:
            _sh.rmtree(tmp, ignore_errors=True)
    check("fs.勾选未加载的包 → 后台解析（不在 UI 线程同步跑）", fs_load_is_async)

    # ①b 数据安全：任务忙碌时 `_load_all_checked` 不得先清空
    def fs_busy_reentry_keeps_data():
        """任务忙碌时调 `_load_all_checked` 必须**先拒绝、后清空**，不能反过来。

        历史顺序：先 `loaded.clear()`/`raws.clear()`/`_clear_dec_tmp()`，再调
        `_load_async` —— 而后者在任务忙碌时返回 False 拒绝执行。于是"先清后拒"等于把
        **正在跑的**解包任务的数据抽走：raws 没了、dec_*.sqfs 被删，成片失败（日志里
        一堆"包已不在内存中"），用户只看到一句"正在加载其它包"。
        """
        import shutil as _sh2
        import tempfile as _tf2
        import stalker_fs as _fs2
        from apps.fs_app import FSToolApp as _FSApp
        tt = _tf2.mkdtemp(prefix="busy_reentry_")
        try:
            p = os.path.join(tt, "x.db")
            with open(p, "wb") as f:
                f.write(_fs2.pack_db([("a.txt", b"x", False)], "xdb"))
            app = _FSApp(tk.Frame(_ROOT))
            app.db_files = [p]
            app.loaded[p] = "SENTINEL"
            app.raws[p] = b"RAW-SENTINEL"
            app.task.running = True                  # 假装有任务正在跑
            try:
                app._load_all_checked()
            finally:
                app.task.running = False
            assert app.loaded.get(p) == "SENTINEL", \
                "忙碌时 loaded 被清空了 —— 正在跑的任务会丢数据"
            assert app.raws.get(p) == b"RAW-SENTINEL", "忙碌时 raws 被清空了"
        finally:
            _sh2.rmtree(tt, ignore_errors=True)
    check("fs.任务忙碌时 _load_all_checked 不清空已加载的包（不抽走正在跑的数据）",
          fs_busy_reentry_keeps_data)

    # ①c fs：往封包列表"添加目录"同样必须走任务线程（遍历 + 读盘都不能占 UI 线程）
    def fs_add_dir_is_async():
        """`_add_dir` 曾经在主线程 `sorted(rglob("*"))` 再逐个 `read()`。

        与 ① 是同一类问题（真实模组 gamedata 树上万文件、几百 MB），但 ① 只覆盖了
        "勾选加载一个包"，没覆盖"添加目录到封包列表"。判定方式同样只看**调用次数/
        状态**，不看墙钟时间：调用后必须立刻 `task.running is True` 且 files_data
        仍是空的（说明遍历还没做完，更没在主线程做完）。
        """
        import shutil as _sh4
        import tempfile as _tf4
        from apps.fs_app import FSToolApp as _FSApp4
        td = _tf4.mkdtemp(prefix="perf_probe_dir_")
        try:
            sub = os.path.join(td, "gamedata", "configs")
            os.makedirs(sub)
            for i in range(200):
                with open(os.path.join(sub, "f%03d.ltx" % i), "w", encoding="utf-8") as f:
                    f.write("x" * 50)
            app = _FSApp4(tk.Frame(_ROOT))
            app.input_var.set("")                      # 未设输入目录 → 用父目录当包根
            app._add_dir(os.path.join(td, "gamedata"))
            assert app.task.running is True, \
                "添加目录没有启动后台任务（说明 rglob/read 还在主线程上跑）"
            assert not app.files_data, "调用后立刻就有 files_data —— 那不是异步"
            for _ in range(600):
                _ROOT.update()
                time.sleep(0.01)
                if not app.task.running:
                    break
            rels = [x[0] for x in app.files_data]
            assert len(rels) == 200, "只加进来 %d 个文件" % len(rels)
            assert all(r.startswith("gamedata/") for r in rels), \
                "相对路径没有保留顶层目录: %s" % rels[:3]
            assert all(isinstance(x[1], bytes) and x[1] for x in app.files_data), \
                "有文件内容是空的 —— 读盘失败被静默吞掉了"
        finally:
            _sh4.rmtree(td, ignore_errors=True)
    check("fs.添加目录 → 后台遍历+读文件（不在 UI 线程同步跑）", fs_add_dir_is_async)

    # ② XML：明细里的 id 行必须虚拟化（控件数与 id 条数无关）
    def id_list_is_virtualized():
        x = XMLCompareApp(tk.Frame(_ROOT))
        try:
            x.mode_var.set(xm.MODE_STATS)
            row = {"rel": "v.xml", "consistent": False, "mode": "stats",
                   "lines_a": 1, "lines_b": 2, "ids_a": 1, "ids_b": 2,
                   "only_a": ["a%04d" % i for i in range(400)],
                   "only_b": [], "count_diff": [], "text_diff": []}
            x.results = [row]
            x._refresh_tree()
            kids = x.tree.get_children()
            x.tree.selection_set(kids[0])
            x._on_row_select(None)
            _ROOT.update_idletasks()
            n_rows = len(getattr(x, "_id_rows", {}) or {})
            assert 0 < n_rows <= 40, \
                "明细里常驻 %d 行 id 控件（400 条差异未虚拟化）" % n_rows
            total_ids = len(x._detail_ids(row))
            assert total_ids == 400, "id 条数不对：%d" % total_ids
        finally:
            for w in x.detail_frame.winfo_children():
                pass
    check("xml.明细 id 列表已虚拟化（400 条差异只建个位数控件）",
          id_list_is_virtualized)

    # ③ XML：detail 列不得调用完整明细渲染（每行一次 × 上万行）
    def detail_column_is_cheap():
        x = XMLCompareApp(tk.Frame(_ROOT))
        try:
            mode = x._active_mode()
            calls = []
            real = mode.get("detail_builder")
            mode["detail_builder"] = lambda *a, **k: (calls.append(1), "重")[1]
            try:
                row = {"rel": "c.xml", "consistent": False, "mode": "stats",
                       "lines_a": 1, "lines_b": 2, "ids_a": 1, "ids_b": 2,
                       "only_a": ["a", "b"], "only_b": ["c"],
                       "count_diff": [], "text_diff": []}
                x._row_values(row, mode, "diff")
            finally:
                mode["detail_builder"] = real
            assert not calls, "detail 列调用了完整明细渲染（每行都会付这个代价）"
        finally:
            pass
    check("xml.detail 列不调用完整明细渲染（按计数拼摘要）",
          detail_column_is_cheap)


def _check_textio():
    """编码判定原先散在三个 App 里各写一套，现统一到 toolkit_textio。
    这些断言把口径固定下来，防止某处又长回各自一套。"""
    import tempfile
    from toolkit_textio import (sniff_encoding, decode_bytes, read_text_bytes,
                                decode_file)

    cyr = "Привет, Сталкер".encode("windows-1251")
    utf = "你好，潜行者".encode("utf-8")
    decl = b'<?xml version="1.0" encoding="windows-1251"?><root/>'

    check("sniff_encoding: 多字节 UTF-8 优先（判据是'含多字节序列'，不是'能解码'）",
          lambda: sniff_encoding(utf) == "utf-8")
    check("sniff_encoding: XML 声明里的编码",
          lambda: sniff_encoding(decl) == "windows-1251")
    # 纯 ASCII 也"能按 UTF-8 解码"，但它没有多字节证据：不能冒充 utf-8，
    # 必须让位给声明。1.0.0 的"XML 声明改不掉"就是漏了这条区分。
    check("sniff_encoding: 纯 ASCII 不冒充 utf-8（让位给 XML 声明）",
          lambda: sniff_encoding(b'<?xml version="1.0" encoding="windows-1251"?><a>Hi</a>')
          == "windows-1251")
    check("sniff_encoding: 手动指定胜于自动（单字节源）",
          lambda: sniff_encoding(cyr, override="windows-1252") == "windows-1252")
    check("sniff_encoding: 手动指定胜不过多字节 UTF-8（用单字节解必乱码）",
          lambda: sniff_encoding(utf, override="windows-1252") == "utf-8")
    check("sniff_encoding: override='auto' 视为未指定",
          lambda: sniff_encoding(cyr, override="auto") == "windows-1251")
    check("sniff_encoding: 别名归一化（cp1251 → windows-1251）",
          lambda: sniff_encoding(cyr, override="cp1251") == "windows-1251")

    t, enc, forced = decode_bytes(cyr)
    check("decode_bytes: 1251 字节正确还原",
          lambda: (t == "Привет, Сталкер") and enc == "windows-1251" and forced is False)
    t2, enc2, forced2 = decode_bytes(b"\xef\xbb\xbf" + utf)
    check("decode_bytes: BOM 剥离后按 UTF-8",
          lambda: (t2 == "你好，潜行者") and enc2 == "utf-8")

    # 真实文件往返（临时目录，只读不依赖项目状态）
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.xml")
        with open(p, "wb") as f:
            f.write(cyr)
        rt, renc, rforced = read_text_bytes(p)
        check("read_text_bytes: 文件往返一致",
              lambda: rt == "Привет, Сталкер" and renc == "windows-1251"
              and rforced is False)
        legacy_t, legacy_enc = decode_file(p)
        check("decode_file: 兼容旧签名 (text, enc)",
              lambda: legacy_t == rt and legacy_enc == renc)

    # 保底必须永不抛异常（三份旧实现都靠它兜住"完全解不开"的文件）
    junk = bytes(range(256)) * 4
    jt, jenc, jforced = decode_bytes(junk)
    check("decode_bytes: 解不开时保底且标记 forced",
          lambda: isinstance(jt, str) and jenc == "latin-1" and jforced is True)


def _check_platform():
    """平台层原先散在四个 App（配置读写、外部程序定位、隐藏窗口、字体目录、
    打开资源管理器）。这里把口径与"不写盘的纯查找"约定固定下来。

    配置读写需要落盘，所以临时把 toolkit_platform.app_dir 指到临时目录，
    避免探针污染真实的应用目录。
    """
    import tempfile
    import toolkit_platform
    from toolkit_platform import (load_app_config, save_app_config, locate_exe,
                                  hidden_kwargs, system_font_dirs, open_in_explorer)

    with tempfile.TemporaryDirectory() as d:
        real_app_dir = toolkit_platform.app_dir
        toolkit_platform.app_dir = lambda: d
        try:
            cfg_name = "probe_platform"
            missing = load_app_config(cfg_name)
            check("load_app_config: 文件不存在返回 {}", lambda: missing == {})

            wrote = save_app_config(cfg_name, {"ffmpeg": "X:/none.exe", "n": 1})
            check("save_app_config: 返回 True 并落盘",
                  lambda: wrote is True and load_app_config(cfg_name).get("n") == 1)

            # 损坏的 JSON 不能让调用方崩（原先各处 try/except 各写一遍）
            p = os.path.join(d, f"{cfg_name}.cfg.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{ not json ")
            check("load_app_config: 损坏文件退化为 {}",
                  lambda: load_app_config(cfg_name) == {})

            # 配置里的路径不存在时必须继续往下找，而不是直接返回坏路径
            found = locate_exe("definitely_not_a_real_tool_xyz",
                               config_name=cfg_name, config_key="ffmpeg")
            check("locate_exe: 配置里的死路径被跳过（返回 None）",
                  lambda: found is None)

            # 只查找、不写盘：调用 locate_exe 前后配置文件内容不变
            before = open(p, "rb").read()
            locate_exe("python", extra_dirs=[os.path.dirname(sys.executable)])
            after = open(p, "rb").read()
            check("locate_exe: 是纯查找，不产生写盘副作用",
                  lambda: before == after)
        finally:
            toolkit_platform.app_dir = real_app_dir

    _hk = hidden_kwargs()
    check("hidden_kwargs: 返回 dict（Windows 下含 creationflags）",
          lambda: isinstance(_hk, dict)
          and (sys.platform != "win32" or "creationflags" in _hk))
    check("system_font_dirs: 返回非空列表", lambda: len(system_font_dirs()) > 0)
    check("open_in_explorer: 不存在的路径返回 False 而不是抛异常",
          lambda: open_in_explorer("X:/definitely/missing/path") is False)


def _check_constants():
    """业务常量表：取值集合与命名约定只写一次，防止各 App 漂移。"""
    from toolkit_constants import (output_ext_for, is_package_name,
                                   PKG_EXT_MARKERS, BACKUP_DIRNAME, BACKUP_SUFFIX,
                                   ENCODING_CHOICES, LEGACY_ENCODING,
                                   ID_PREFIX_TEMPLATE, GP_TEXTS_NAME, SC_TEXTS_NAME)

    check("output_ext_for: sqfs → .sqfs，其余 → .db",
          lambda: output_ext_for("sqfs") == ".sqfs" and output_ext_for("xdb") == ".db")
    check("is_package_name: 认出 .db 家族与 .sq/.sq_base",
          lambda: all(is_package_name(n) for n in
                      ("gamedata.db0", "all.db", "x.sq", "y.sq_base", "z.SQFS"))
          and not is_package_name("readme.txt"))
    check("is_package_name: 宽松标记是 '.db'/'.sq'（与 fs_app 原判定等价）",
          lambda: set(PKG_EXT_MARKERS) == {".db", ".sq"})
    check("备份约定单一来源", lambda: BACKUP_DIRNAME == "backup" and BACKUP_SUFFIX == ".bak")
    check("编码候选含 STALKER 常见的 1251 与 auto 在首位",
          lambda: ENCODING_CHOICES[0] == "auto" and "windows-1251" in ENCODING_CHOICES)
    check("缺省单字节编码为 windows-1251", lambda: LEGACY_ENCODING == "windows-1251")

    # 槽位名是 {abbr}（类型缩写），不是 {ftype}（全名）—— 名字改准，取值与产出 ID 不变
    _pre = ID_PREFIX_TEMPLATE.format(prefix="gs", abbr="gp", ts=123)
    check("ID 前缀模板可用（槽位名 {abbr}）", lambda: _pre == "sgtat_gs_gp_123")
    check("ID 前缀模板不再接受旧槽位名 {ftype}",
          lambda: "{ftype}" not in ID_PREFIX_TEMPLATE)
    check("文本产物名模板可用",
          lambda: GP_TEXTS_NAME.format(prefix="gs") == "gs_gameplay_texts.xml"
          and SC_TEXTS_NAME.format(prefix="gs") == "gs_scripts_texts.xml")


def _check_reexport_contract():
    """toolkit.py 的对外契约：`__all__` 必须与它的 import 逐一对齐。

    这条锁补的是"pyflakes 整文件豁免被删掉"之后留下的空洞。`toolkit.py` 是纯
    re-export 层，文件里的 import 天然"在文件内未被使用"，所以静态检查只能靠
    `__all__` 判定"这个名字是有意导出的"。于是 `__all__` 一旦漂移就是两头出事：

      · import 了却漏进 `__all__` —— pyflakes 立刻报"imported but unused"
        （这正是我们想要的信号：它同时意味着 `from toolkit import *` 少一个名字）；
      · `__all__` 里写了不存在的名字 —— pyflakes **不报**（它只看名字是否被"用到"），
        但 `from toolkit import *` 会在运行期 AttributeError。

    所以必须两个方向都比：集合相等 + 无重复，另外再比一次**运行期**的
    `toolkit.__all__`（防有人用 `__all__.append(...)` 之类在运行期偷偷加名字，
    那样 AST 里看不到，静态那一半会瞎）。
    """
    import ast
    import io
    import toolkit

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit.py")
    tree = ast.parse(io.open(path, encoding="utf-8").read())

    exported, imported = None, []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            if isinstance(node.value, ast.List):
                exported = [e.value for e in node.value.elts
                            if isinstance(e, ast.Constant)]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imported += [a.asname or a.name for a in node.names]

    if not isinstance(exported, list) or not exported:
        check("toolkit.py 有模块级字面量 __all__（对外契约，静态检查的唯一依据）",
              lambda: False)
        return
    check("toolkit.py 有模块级字面量 __all__（对外契约，静态检查的唯一依据）",
          lambda: True)
    check("toolkit.py __all__ 无重复名",
          lambda: len(exported) == len(set(exported)))

    def _covered():
        miss = sorted(set(imported) - set(exported))
        assert not miss, "import 了但不在 __all__（对 import * 消失）: %s" % ", ".join(miss)

    def _no_ghost():
        ghost = sorted(set(exported) - set(imported))
        assert not ghost, "__all__ 里有非 import 名（import * 会 AttributeError）: %s" \
                          % ", ".join(ghost)

    def _runtime_same():
        assert list(toolkit.__all__) == exported, (
            "运行期 __all__ 与源码字面量不一致：多 %s / 少 %s"
            % (sorted(set(toolkit.__all__) - set(exported)),
               sorted(set(exported) - set(toolkit.__all__))))

    check("toolkit.py __all__ 覆盖全部 import", _covered)
    check("toolkit.py __all__ 不含未 import 的名字", _no_ghost)
    check("toolkit.py 运行期 __all__ 与源码字面量一致（防止运行期偷偷 append）",
          _runtime_same)
    check("toolkit.py __all__ 里的每个名字都能真取到",
          lambda: all(hasattr(toolkit, n) for n in exported))


def _check_log_retention():
    """日志保留：**预发布版不清理、正式版保留最近 100 个**（用户裁定 2026-09-12）。

    这条锁分两半，因为策略与执行是分开的：
      * 策略是纯函数 `retention_keep(标记)` —— 不必真去发一个正式版就能钉住"预发布不清理"；
      * 执行 `cleanup_logs()` 只动 `runtime_YYYYMMDD_HHMMSS.log`，且**必须**给本次会话
        的日志留位置、必须不碰 Hub 导出的 `log_*.txt`（那是用户主动产出的快照）。
    另外核对"策略确实接上了"：`toolkit_base` 在 import 期用 `APP_PRERELEASE` 设过它。
    """
    import toolkit_base as _TB
    import toolkit_log as _TL

    # ① 策略：预发布一律不清理；正式版（无标记）100
    check("日志：预发布版（ALPHA/BETA/RC）不设上限（测试期日志留给人工清）",
          lambda: all(_TL.retention_keep(p) is None
                      for p in ("ALPHA.7", "BETA.2", "RC.1", "alpha.1")))
    check("日志：正式版上限 = 100（无标记与 None 都算正式版）",
          lambda: _TL.retention_keep("") == 100 and _TL.retention_keep(None) == 100)

    def _policy_wired():
        assert _TL.policy_applied(), \
            "没有任何人设置过保留策略 —— toolkit_base 的 set_log_retention 接线被删了？"
        if "STALKER_LOG_KEEP" in os.environ:
            return                      # 排障覆盖态：不再比策略值
        assert _TL.current_keep() == _TL.retention_keep(_TB.APP_PRERELEASE), (
            "保留策略与 APP_PRERELEASE 不一致：current_keep=%r"
            % (_TL.current_keep(),))
    check("日志：策略已按 APP_PRERELEASE 接线（toolkit_base import 期设过一次）",
          _policy_wired)

    # ② 执行：130 个运行时日志 + 3 个"不是我们的"文件
    def _cleanup_behaviour():
        import shutil as _sh5
        import tempfile as _tf5
        td = _tf5.mkdtemp(prefix="log_retention_")
        try:
            logs = os.path.join(td, "logs")
            os.makedirs(logs)
            names = ["runtime_20260101_%06d.log" % (i * 7) for i in range(130)]
            for n in names:
                with open(os.path.join(logs, n), "w", encoding="utf-8") as f:
                    f.write("x")
            keep_me = ["log_20260101_000000.txt",          # Hub 导出的快照
                       "runtime_notatimestamp.log",        # 名字不合规范
                       "readme.txt"]
            for n in keep_me:
                with open(os.path.join(logs, n), "w", encoding="utf-8") as f:
                    f.write("keep")

            def _left():
                return sorted(n for n in os.listdir(logs)
                              if _TL._RUNTIME_RE.match(n))

            removed, kept = _TL.cleanup_logs(100, td)
            assert removed == 31, "删了 %d 个（130 个里应删 31 个）" % removed
            assert len(_left()) == 99, \
                "留下 %d 个（给本次会话预留 1 个，应留 99 个）" % len(_left())
            assert names[-1] in _left() and names[0] not in _left(), "留的不是最新的"
            assert all(n in os.listdir(logs) for n in keep_me), \
                "误删了非运行时日志（导出的 log_*.txt 是用户快照）"

            # ③ 本次会话的日志永远保留（哪怕它排不到最新、或上限很小）
            cur = _TL.log_name()
            with open(os.path.join(logs, cur), "w", encoding="utf-8") as f:
                f.write("session")
            _TL.cleanup_logs(5, td)
            assert cur in _left(), "本次会话的日志被删掉了"
            assert len(_left()) == 5, "上限 5 却留下 %d 个" % len(_left())
            assert all(n in os.listdir(logs) for n in keep_me), "第二轮清理误删了非运行时日志"
        finally:
            _sh5.rmtree(td, ignore_errors=True)
    check("日志：正式版清理只留最近 100 个、保留会话文件、不动导出快照",
          _cleanup_behaviour)


def _check_log_pipeline():
    """日志管线的并发与"不静默"（外部审计 2026-09-12 的 A-1/A-2/A-3）。

    三条都是"用起来才知道"的问题，且都属于**静默类**：
      * A-1 写盘无锁：多线程共写一个文件，append 无锁时日志行会交错 —— 排障时读到的
        是拼出来的假行，比丢一行更有害；
      * A-2 写失败静默：日志目录不可写时用户以为有日志、实际什么都没记；
      * A-3 缓冲竞态：`take_buffer()` 与并发 `_buffer_add()` 之间的窗口会让消息
        落进再也无人读取的列表（GUI 日志栏少一行，磁盘上却有）。

    A-1/A-3 的"竞态"没法用概率测试稳定复现（跑一百次也可能一次不中），所以这里用
    **确定性手法**：自己先拿住那把锁，再断言另一个线程**进不去**（未加锁就会立刻完成）。
    这不是"观察到了竞态"，而是"钉住了临界区存在且两个入口都走它" —— 注释如实写清楚。
    """
    import contextlib
    import io
    import threading
    import toolkit_log as _TL

    here = os.path.dirname(os.path.abspath(__file__))

    def _blocks(lock, fn, what):
        done = threading.Event()

        def _run():
            try:
                fn()
            finally:
                done.set()
        lock.acquire()
        try:
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            blocked = not done.wait(0.4)
        finally:
            lock.release()
        assert blocked, "%s 没有走临界区（没加锁）—— 并发下会交错/丢行" % what
        assert done.wait(5.0), "%s 释放锁后仍未完成（死锁？）" % what

    def _write_locked():
        _blocks(_TL._WRITE_LOCK,
                lambda: _TL.log_to_file("probe A-1 持锁测试", "info"), "log_to_file")
    check("日志：写盘走 _WRITE_LOCK 临界区（A-1，多线程共写同一文件）", _write_locked)

    def _buffer_locked():
        save_buf, save_flag = list(_TL._BUFFER), _TL._BUFFERING
        try:
            _blocks(_TL._BUFFER_LOCK,
                    lambda: _TL._buffer_add("probe A-3 持锁测试", "info"), "_buffer_add")
            _blocks(_TL._BUFFER_LOCK, _TL.take_buffer, "take_buffer")
        finally:
            _TL._BUFFER[:] = save_buf
            _TL._BUFFERING = save_flag
    check("日志：_buffer_add 与 take_buffer 共用 _BUFFER_LOCK（A-3，关闭缓冲与取走原子）",
          _buffer_locked)

    def _write_failure_visible():
        """写盘失败必须留痕（A-2）。造一个**文件**当日志目录 → open 必然失败。"""
        import tempfile
        td = tempfile.mkdtemp(prefix="log_fail_")
        try:
            fake = os.path.join(td, "not_a_dir")
            with open(fake, "w", encoding="utf-8") as f:
                f.write("x")
            saved = (_TL._LOG_DIR, _TL._LOG_FAILED, _TL._LOG_WARNED)
            buf = io.StringIO()
            try:
                _TL.set_log_dir(fake)
                with contextlib.redirect_stderr(buf):
                    _TL.log_to_file("这条写不出去", "err")
                assert _TL.log_write_failed() is not None, \
                    "写盘失败被静默吞掉了（A-2 回归）：标志位仍为空"
                assert "toolkit_log" in buf.getvalue(), "写盘失败没有往 stderr 留痕"
            finally:
                _TL._LOG_DIR, _TL._LOG_FAILED, _TL._LOG_WARNED = saved
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
    check("日志：写盘失败不静默（记 log_write_failed + stderr 留一行）", _write_failure_visible)

    def _hub_reports_failure():
        """AST 判定 Hub 真的**会**在启动时报告写盘失败。

        为什么不用"源码里出现这串字符"：那种检查会被**死代码**满足 ——
        实测把条件改成 `if False and log_write_failed() is not None:`，
        字符串检查照样过，而分支永不执行。所以要认出活的比较表达式：
        `if <log_write_failed()调用> is not None:` 且函数体里有 log_summary 上报。
        """
        import ast
        src = open(os.path.join(here, "stalker_toolkit.py"), encoding="utf-8").read()
        tree = ast.parse(src)

        def _is_failure_test(node):
            if not isinstance(node, ast.Compare) or len(node.ops) != 1:
                return False
            if not isinstance(node.ops[0], ast.IsNot):
                return False
            left, right = node.left, node.comparators[0]
            if not (isinstance(left, ast.Call)
                    and isinstance(left.func, ast.Name)
                    and left.func.id == "log_write_failed"):
                return False
            return isinstance(right, ast.Constant) and right.value is None

        def _reports(node):
            if not isinstance(node, ast.If) or not _is_failure_test(node.test):
                return False
            return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "log_summary" for n in ast.walk(node))
        assert any(_reports(n) for n in ast.walk(tree)), (
            "Hub 启动时不再**活的**检查/上报日志写盘失败 —— 用户会以为有日志可查"
            "（A-2 只修了一半；注意此判定必须是真分支，`False and ...` 不算）")
    check("日志：Hub 启动时会把写盘失败说出来（AST 判定，死代码不算）", _hub_reports_failure)


def _check_no_legacy_residue():
    """防"模块化残留"再长回来：三条防腐锁（2026-09-12 残留排查的产物）。

    排查一次只能清掉当时那一批；**没有锁的地方**下次重构还会再积一层。这三条锁的都是
    "已经踩过一次"的形态：
      * 重复实现：App 里再定义一份公共层已有的函数（`decode_file` 遮蔽过公共层那份）；
      * 游离脚本：根目录多出一个 `run_*.py` 却没人把它纳入静态扫描（`_gui_text_audit.py` 就是）；
      * 盲区堆积：`temp/` 里放 `.py` 源文件（它同时在 CI 的 `_SKIP_PARTS` 与死代码审计的
        `SKIP_DIRS` 里，放进去的旧副本没人看得见 —— 919 行的旧 `fs_app` 就在那躺了很久）。
    """
    import ast
    import io
    here = os.path.dirname(os.path.abspath(__file__))

    def _no_shadowing():
        import apps.xml_compare_app as XC
        import toolkit_textio as TT
        assert XC.decode_file is TT.decode_file, (
            "xml_compare_app 又自己定义了一份 decode_file（遮蔽公共层）："
            "%r 不是 %r" % (XC.decode_file, TT.decode_file))
        src = io.open(os.path.join(here, "apps", "xml_compare_app.py"),
                      encoding="utf-8").read()
        tree = ast.parse(src)
        local = [n.name for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "decode_file"]
        assert not local, "xml_compare_app.py 里又出现了本地 def decode_file"
    check("残留防腐：App 不得再遮蔽公共层的 decode_file（重复实现）", _no_shadowing)

    def _run_scripts_registered():
        ci_src = io.open(os.path.join(here, "run_ci.py"), encoding="utf-8").read()
        missing = [n for n in sorted(os.listdir(here))
                   if n.startswith("run_") and n.endswith(".py")
                   and ('"%s"' % n) not in ci_src]
        assert not missing, (
            "这些 run_*.py 没进 run_ci.py 的 pyflakes 名单 → 不被任何静态检查覆盖: %s"
            % ", ".join(missing))
    check("残留防腐：每个 run_*.py 都在静态扫描名单里（不许再出现游离脚本）",
          _run_scripts_registered)

    def _temp_has_no_sources():
        temp_dir = os.path.join(here, "temp")
        bad = []
        if os.path.isdir(temp_dir):
            for dp, _dn, fn in os.walk(temp_dir):
                bad += [os.path.join(dp, n) for n in fn if n.endswith(".py")]
        assert not bad, (
            "temp/ 下有 .py 源文件 —— 它同时是 CI 与死代码审计的盲区，"
            "旧实现副本放这里等于没登记: %s"
            % ", ".join(os.path.relpath(b, here) for b in bad[:5]))
    check("残留防腐：temp\\ 下不得放 .py 源文件（CI/审计双盲区）", _temp_has_no_sources)


    def _eol_declared_matches_reality():
        """行尾**声明**（.editorconfig / .gitattributes）必须与实际文件一致。

        外部审计 2026-09-12 指出：41 个 `.py` 里 5 个纯 CRLF、其余纯 LF，却**没有任何声明**
        —— 于是"顺手用某个工具重写一遍"就可能把 CRLF 文件整体改成 LF（几十 KB 的假 diff），
        或者把某个文件搞成混合行尾（我在注入工装里已经踩过两次）。
        锁的含义：**声明写的 crlf，文件就必须是纯 CRLF；没声明的 .py 必须是纯 LF**。
        """
        import re as _re
        src = open(os.path.join(here, ".editorconfig"), encoding="utf-8").read()
        declared = {}
        section = None
        for line in src.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif section and line.replace(" ", "").startswith("end_of_line="):
                declared[section] = line.split("=", 1)[1].strip().lower()
        crlf_declared = {k for k, v in declared.items() if v == "crlf"}
        assert crlf_declared, ".editorconfig 里没有声明任何 CRLF 文件（声明被删了？）"

        skip = ("builds", "backup", "deps", ".git", "__pycache__", "logs", "temp")
        bad = []
        for dp, dn, fn in os.walk(here):
            dn[:] = [d for d in dn if d not in skip]
            for n in fn:
                if not n.endswith(".py"):
                    continue
                p = os.path.join(dp, n)
                rel = os.path.relpath(p, here).replace("\\", "/")
                b = open(p, "rb").read()
                crlf = b.count(b"\r\n")
                lf = b.count(b"\n") - crlf
                want_crlf = rel in crlf_declared
                if crlf and lf:
                    bad.append("%s 行尾混合（CRLF=%d LF=%d）" % (rel, crlf, lf))
                elif want_crlf and lf:
                    bad.append("%s 声明为 CRLF 实际是 LF" % rel)
                elif not want_crlf and crlf:
                    bad.append("%s 未声明却含 CRLF（声明里没它）" % rel)
        assert not bad, "行尾与声明不一致：%s" % "; ".join(bad[:5])

        # .gitattributes 里同样的 5 个文件也要声明（两份声明不许漂移）
        ga = open(os.path.join(here, ".gitattributes"), encoding="utf-8").read()
        missing = [f for f in sorted(crlf_declared)
                   if not _re.search(r"^%s\s+text\s+eol=crlf\s*$" % _re.escape(f), ga, _re.M)]
        assert not missing, ".gitattributes 没声明这些 CRLF 文件：%s" % ", ".join(missing)
    check("行尾声明：.editorconfig / .gitattributes 与实际文件一致（防整文件假 diff）",
          _eol_declared_matches_reality)


def _check_input_focus_policy():
    """输入框的焦点 / 选中收敛（用户口径 2026-09-12）。

    用户报的两件事：① 目录栏点进去后光标常闪（**正常**，它要支持键盘输入路径），
    但**点空白处取消不掉**；② 打开任意组件后仍停在"某个输入框被选中"的状态。

    Tk 的两个默认行为造成它：点 Label / Frame 这类不可聚焦控件**不改焦点**；
    而 `focus_set()` 只把焦点拿走、**选中高亮仍残留**（实测 `selection_present()` 依旧 True）。
    所以本节的断言必须同时检查"焦点"和"选中高亮"两件事 —— 只看焦点会漏掉一半。
    """
    import tkinter as tk
    from tkinter import ttk
    import toolkit_widgets as W

    # ⚠ 必须用**独立 Toplevel**：探针的 `_ROOT` 是 withdraw 的，其子控件
    # `winfo_ismapped()==0`，而 Tk **拒绝把焦点给未映射控件**（`focus_force` 也不行）。
    # Toplevel 会被正常映射 → 焦点/点击路径可以真跑；结束时销毁，不留窗口。
    # ⚠ 窗口还得**够大**：pack 到没空间的控件同样不会被映射（实测 360x180 时
    # e2/Notebook 全 unmapped → 焦点断言会因为"前置条件不成立"而假失败）。
    top = tk.Toplevel(_ROOT)
    top.geometry("640x560")
    try:
        fr = tk.Frame(top)
        fr.pack(fill="both", expand=True)
        var = tk.StringVar(value="C:/some/path")
        _row, e = W.path_row(fr, "目录", var, lambda: None)
        lbl = ttk.Label(fr, text="空白区")
        lbl.pack(fill="both", expand=True)
        lb = tk.Listbox(fr)
        lb.pack()
        lb.insert("end", "a")
        e2 = W.themed_entry(fr)
        e2.pack()
        top.update()

        def _click(w):
            w.event_generate("<Button-1>", x=2, y=2)
            top.update()

        def _force_focus(w):
            w.focus_force()
            top.update()

        # 三个输入框工厂**各自**都要装上钩子 —— 每个工厂单独用一个新 Toplevel，
        # 否则先建的工厂会替后建的把钩子装上，注入就抓不到"某个工厂漏装"。
        def _factory_installs_hook(which):
            def _f():
                t = tk.Toplevel(_ROOT)
                t.geometry("420x140")
                try:
                    f = tk.Frame(t)
                    f.pack(fill="both", expand=True)
                    if which == "path_row":
                        W.path_row(f, "目录", tk.StringVar(value="a"), lambda: None)
                    elif which == "dir_row":
                        W.dir_row(f, "目录", tk.StringVar(value="a"))
                    else:
                        W.themed_entry(f)
                    t.update()
                    assert getattr(t, "_dsh_blank_click_hooked", False), \
                        "%s 没有装「点空白取消」钩子" % which
                finally:
                    t.destroy()
            return _f
        for _w in ("path_row", "dir_row", "themed_entry"):
            check("输入框：%s 自动装上「点空白取消」钩子" % _w, _factory_installs_hook(_w))

        def _blank_click_cancels():
            _force_focus(e)
            e.selection_range(0, "end")
            top.update()
            assert top.focus_get() is e, "前置条件不成立：Entry 没拿到焦点"
            assert e.selection_present(), "前置条件不成立：文本没被选中"
            _click(lbl)
            assert top.focus_get() is not e, "点空白后焦点仍留在输入框（用户报的就是这个）"
            assert not e.selection_present(), "点空白后选中高亮仍残留（focus_set 不负责清它）"
        check("输入框：点空白处 → 焦点离开 **且** 选中高亮消失", _blank_click_cancels)

        def _list_focus_kept():
            _force_focus(lb)
            _click(lbl)
            assert top.focus_get() is lb, "点空白把 Listbox 的键盘焦点抢走了"
        check("输入框：焦点在列表上时点空白不抢焦点（树/列表导航要留着）", _list_focus_kept)

        def _click_other_entry_moves_focus():
            _force_focus(e)
            _click(e2)
            assert top.focus_get() is e2, "点另一个输入框时焦点没有正常转移"
        check("输入框：点另一个输入框 → 焦点正常转移（钩子不插手）",
              _click_other_entry_moves_focus)

        def _neutralize_clears_and_reports():
            _force_focus(e)
            e.selection_range(0, "end")
            top.update()
            n = W.neutralize_input_focus(top)
            assert n >= 1, "neutralize_input_focus 没清掉任何选中高亮"
            assert not e.selection_present(), "调用后选中高亮仍在"
            assert top.focus_get() is not e, "调用后焦点仍在输入框"
        check("输入框：neutralize_input_focus 清选中并返回被清数量",
              _neutralize_clears_and_reports)

        def _tab_switch_clears_state():
            """② 的行为面：切页（= 打开另一个组件）必须清掉上一个组件的输入框态。"""
            nb = ttk.Notebook(fr)
            t1, t2 = tk.Frame(nb), tk.Frame(nb)
            nb.add(t1, text="A")
            nb.add(t2, text="B")
            nb.pack(fill="x")
            v = tk.StringVar(value="x:/y")
            _r2, te = W.path_row(t1, "目录", v, lambda: None)
            reset = W.install_tab_focus_reset(nb, top)
            assert callable(reset), "install_tab_focus_reset 没有返回回调"
            nb.select(t1)
            top.update()
            _force_focus(te)
            te.selection_range(0, "end")
            top.update()
            assert top.focus_get() is te and te.selection_present(), "前置条件不成立"
            nb.select(t2)
            top.update()
            assert not te.selection_present(), "切页后输入框的选中高亮还在（用户报的②）"
            assert top.focus_get() is not te, "切页后焦点仍留在输入框"
        check("输入框：切页（打开另一个组件）清掉上一个组件的输入框选中态",
              _tab_switch_clears_state)
    finally:
        try:
            top.destroy()
        except Exception:
            pass
        _ROOT.update()

    def _hub_wires_tab_reset():
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "stalker_toolkit.py"), encoding="utf-8").read()
        assert "install_tab_focus_reset(" in src, \
            "Hub 装配处没装「切页收敛输入框焦点」—— 打开组件后仍会停在选中态"
    check("输入框：Hub 装配处确实装了切页收敛（源码漂移锁）", _hub_wires_tab_reset)


def _check_taskrunner():
    """终止态必须干净：运行标志复位、进度停、忙碌回调收尾、状态不被覆盖。"""
    import time
    from toolkit import TaskRunner

    def wait_for(pred, timeout=5.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            _ROOT.update()
            if pred():
                return True
            time.sleep(0.01)
        return False

    # A. 成功路径
    st = {}

    def setter(text, kind="idle"):
        st["text"], st["kind"] = text, kind

    events = []
    tr = TaskRunner(_ROOT, lambda fn, *a: fn(*a),
                    on_busy=lambda busy: events.append(busy),
                    status_setter=setter,
                    progress_started=lambda: events.append("start"),
                    progress_stopped=lambda: events.append("stop"))
    started = tr.run(lambda: None, status="跑", final_status=("完成", "ok"))
    ok_lifecycle = wait_for(lambda: not tr.running)
    check("TaskRunner 成功路径：跑完即复位",
          lambda: bool(started and ok_lifecycle and tr.running is False))
    check("TaskRunner 成功路径：进度先起后停",
          lambda: "start" in events and "stop" in events)
    check("TaskRunner 忙碌回调 True→False",
          lambda: events[0] is True and events[-1] is False)
    check("TaskRunner 收尾写成功状态",
          lambda: st.get("text") == "完成" and st.get("kind") == "ok")

    # B. 失败路径：on_error 写的状态不得被 final_status 覆盖
    st2 = {}
    seen = {}

    def setter2(text, kind="idle"):
        st2["text"], st2["kind"] = text, kind

    def boom():
        raise RuntimeError("故意失败")

    def on_err(e):
        seen["err"] = e
        tr2.set_status("失败", "err")

    tr2 = TaskRunner(_ROOT, lambda fn, *a: fn(*a), status_setter=setter2)
    tr2.run(boom, status="跑", on_error=on_err, final_status=("完成", "ok"))
    wait_for(lambda: not tr2.running)
    check("TaskRunner 失败路径：错误回调被调用",
          lambda: isinstance(seen.get("err"), RuntimeError))
    check("TaskRunner 失败路径：状态为『失败』而非『完成』",
          lambda: st2.get("text") == "失败" and st2.get("kind") == "err")

    # C. 重入保护
    hold = {"go": False}
    tr3 = TaskRunner(_ROOT, lambda fn, *a: fn(*a))
    tr3.run(lambda: wait_for(lambda: hold["go"], timeout=2.0))
    second = tr3.run(lambda: None)
    check("TaskRunner 重入保护：二次调用被拒", lambda: second is False)
    hold["go"] = True
    wait_for(lambda: not tr3.running)

    # D. 确定进度形态
    class _Var:
        def __init__(self):
            self.v = None

        def set(self, x):
            self.v = x

    class _Lbl:
        def __init__(self):
            self.t = None

        def config(self, **k):
            self.t = k.get("text")

    _v, _l = _Var(), _Lbl()
    tr4 = TaskRunner(_ROOT, lambda fn, *a: fn(*a), progress_var=_v, progress_label=_l)
    tr4.progress_update(3, 12)
    check("TaskRunner 确定进度：百分比与文案",
          lambda: _v.v == 25.0 and _l.t == "3 / 12")


if __name__ == "__main__":
    _code = 1
    try:
        _code = main()
    finally:
        try:
            _ROOT.destroy()
        except Exception:
            pass
    # 探针自身不留下任何文件
    import shutil
    _pc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps", "__pycache__")
    if not os.environ.get("DSH_APP_PROBE_KEEP_PYC"):
        shutil.rmtree(_pc, ignore_errors=True)
    sys.exit(_code)
