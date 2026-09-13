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
try:
    try:
        from tkinterdnd2 import TkinterDnD  # noqa: F401
        _ROOT = TkinterDnD.Tk()
    except ImportError:
        _ROOT = tk.Tk()
    _ROOT.withdraw()
except Exception as _e:
    print("SKIP run_app_probe: 无法创建 Tk 根窗口（需要桌面环境）: %s" % _e)
    sys.exit(0)

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
        """构造 VideoOGMApp 不得跑 `ffmpeg -encoders`（Hub 启动会一次性构造全部 6 个 App）。

        历史缺陷：`Converter.__init__` 里同步跑 `_scan_encoders()` = `ffmpeg -encoders`
        （timeout=10s）—— 冷盘/杀软扫描下用户看到的就是"Hub 启动就卡住"。现在惰性化：
        首次真正要选编码器时（已在转换的工作线程里）才扫。
        只统计参数里带 `-encoders` 的调用 —— 构造期本来会跑 `where` 之类的查找，
        把它们算进来会让这条锁因无关原因误红。
        """
        import apps.video_ogm_app as _v
        calls = []
        orig_run = _v.subprocess.run

        def spy(*a, **k):
            calls.append(a[0] if a else k.get("args"))
            return orig_run(*a, **k)
        _v.subprocess.run = spy
        try:
            app = VideoOGMApp(tk.Frame(_ROOT))
            hits = [c for c in calls if isinstance(c, (list, tuple)) and "-encoders" in c]
            assert not hits, "构造 VideoOGMApp 时跑了 ffmpeg -encoders：%r" % (hits[:1],)
            # 惰性扫描必须仍然存在：显式调一次要真的去跑 —— 否则"惰性"退化成"永不扫描"，
            # 编码器选择会静默回退到 mpeg4（比卡顿更糟）。
            # 注意：这次调用必须在 **spy 仍在位** 时做（spy 已在 finally 里还原过一次，
            # 那是本条锁自己的第一版 bug：还原后才调，于是计数没涨、锁自己变红）。
            if app.converter is not None:
                before = len(calls)
                app.converter._ensure_encoders()
                assert len(calls) > before, "惰性扫描没有真的发生（能力被删掉了）"
        finally:
            _v.subprocess.run = orig_run
    check("视频.构造 App 不跑 ffmpeg -encoders（Hub 启动不卡）、惰性扫描仍有效",
          video_no_encoder_scan_at_construct)

    def video_ffprobe_is_async():
        """选/拖源文件时的 ffprobe 解析不得占 UI 线程。

        判据：把 `parse_video_info` 打桩成"睡 0.3 秒再成功返回"，调 `_on_source` 必须
        **立刻返回**（<0.15s），随后由 UI 泵把结果回主线程（`source_path`/`source_info`
        被写上）。历史实现是在 UI 线程里同步调它（内部 timeout=30）→ 大文件/网络盘白屏。
        """
        import apps.video_ogm_app as _v
        app = VideoOGMApp(tk.Frame(_ROOT))
        # 前置检查要求 ffprobe "是个存在的文件"；用探针自己的脚本当占位
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
    else:
        print("  SKIP fs（构造失败）")

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
