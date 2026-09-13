# -*- coding: utf-8 -*-
"""
STALKER Localization Toolkit — Hub
六个图形化工具统一入口：文件系统、编码转换、文本提取、
XML 校对、OGM 视频转换、汉化包生成，并托管插件扩展的栏目。
运行: python stalker_toolkit.py
"""
import os
import shutil
import sys
import time

# 引擎库路径注入 (stalker_fs / font_pack 在各自工具子目录)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(_BASE_DIR, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk
from tkinter import messagebox, ttk

# 让 `toolkit` / `apps` 无论从哪个工作目录启动都能被导入。
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from toolkit_version import full_version

from toolkit import (
    APP_NAME, BusyOverlay, HIDPI_STATUS, LogBox, PluginManager, SplitPane, T, _BaseTk, _make_pump,
    app_dir, apply_theme, apply_tk_defaults, apply_titlebar, color,
    ensure_package, load_user_theme, log_detail, log_path, log_summary,
    log_write_failed, install_tab_focus_reset,
    px, refresh_theme, save_user_theme, set_app_icon, set_gui_sink,
    sync_tk_scaling, take_log_buffer,
)
from apps.font_pack_app import FontPackApp
from apps.convert_app import ConvertApp
from apps.text_extract_app import TextExtractApp
from apps.xml_compare_app import XMLCompareApp
from apps.video_ogm_app import VideoOGMApp
from apps.fs_app import FSToolApp

# 六个内置栏目：模块级常量即"框架事实来源"。
# 放在这里而不是 `main()` 内部，是为了让 `run_hub_probe.py` 能核对**真实的**
# 内置清单 —— 探针此前自己手抄一份同名列表，Hub 少一个工具它也照样通过。
BUILTIN_TOOLS = [
    ("文件系统", FSToolApp),
    ("编码转换", ConvertApp),
    ("文本提取", TextExtractApp),
    ("XML校对", XMLCompareApp),
    ("视频转换", VideoOGMApp),
    ("汉化包生成", FontPackApp),
]

# ════════════════════════════════════════════════════════════════
# 1. 主题 (亮/暗两套, 单函数切换)
# ════════════════════════════════════════════════════════════════
# 依赖兜底：源码运行时缺包则自动安装（打包版依赖已内置）
#   tkinterdnd2 —— 拖拽支持
#   chardet     —— toolkit_textio.sniff_encoding 的统计探测
# 说明：这里曾以"全工程已无任何 chardet 调用"为由移除 chardet，但统计探测
# 一并被删掉了，于是 GBK / Big5 / 无 BOM 的 UTF-16 源文件全部被判成
# windows-1251（实测），而重构前的编码转换工具用 chardet 是能识别的。
# 该能力已恢复，因此依赖兜底也一并恢复。
for _imp, _pkg in (("tkinterdnd2", "tkinterdnd2"), ("chardet", "chardet")):
    ensure_package(_imp, _pkg)


# ════════════════════════════════════════════════════════════════
# 2. 启动绘制与分帧装配（白屏 / 可点击时间）
# ════════════════════════════════════════════════════════════════
# 症状（用户取证 2026-09-12，录屏 + 该次运行的运行日志）：
#   Tk 建根窗口用的是系统默认**白底**，而"第一次重绘"本来要等到 mainloop；
#   中间这段要扫插件、装配六个内置栏目 —— 本机实测源码态 0.31 s，冷冻版冷启动
#   1.47 s（build_11 录屏逐帧测得），整段窗口是"纯白 + 蓝色忙光标"，用户口径
#   就是"启动优化很差 / 卡住"。
# 处方：装配**之前**先按当前主题画一帧，并挂一句装载提示；装配过程中每装完一个
#   栏目再画一帧。所有"可见推进"都必须经过下面两个函数，探针按名字锁住这条契约。
def paint_now(root):
    """立刻重绘一次（启动白屏修复的落点）。返回 True 供探针断言。

    只调 `update_idletasks()`：它只处理**空闲任务**（映射 / 布局 / 重绘），
    **不取出输入事件** —— 装配尚未完成时不会重入用户回调，也不会在 mainloop
    之前响应关窗之类的窗口消息（`update()` 会，所以这里不用 `update()`）。
    """
    root.update_idletasks()
    return True


def paint_startup(root, hint_text="正在装载组件…"):
    """先画一帧再装配：白屏修复。返回提示标签。

    提示标签会被 `build_hub()` 开头的"清空 root 子控件"一并回收，不需要另建销毁
    路径；`style="Dim.TLabel"` 走的是 apply_theme 已定义好的样式，所以它和窗口
    底色同源，不会在深色主题上留一块浅色。
    """
    hint = ttk.Label(root, text=hint_text, style="Dim.TLabel")
    hint.pack(expand=True)
    paint_now(root)
    return hint


def build_tabs(root, tools, build_one, defer_rest=True, on_done=None):
    """栏目装配调度器：首个同步装配，其余每个交给一次 `root.after(1, …)`。

    为什么分帧（用户口径 2026-09-12"优化很差"的另一半）：六个栏目在真机上要
    1.5~2.0 s（build_11 运行日志逐项：文件系统 203 / 编码转换 484 / 文本提取 209 /
    XML校对 117 / 视频转换 198 / 汉化包生成 164 ms）。**同步装完才进 mainloop**
    的话，窗口虽然已经画出来却点不动 —— 用户看到一个深色窗口杵着不动一到两秒，
    仍然是"卡"。分帧之后 mainloop 在第一个栏目装好时就跑起来（实测 ~0.7 s），
    其余栏目在事件循环里一帧一个地补齐；期间界面是活的。

    build_one(label, factory) 由调用方提供（建 Frame / notebook.add / 异常兜底 /
    paint_now 都在里面）。on_done() 在最后一个栏目装配完时调用一次（Hub 用来收尾
    apply_theme）。返回 (已同步装配的标签列表, 剩余待装配数) —— 探针按这两个返回值
    锁"分帧"契约；`defer_rest=False` 走一次性装配（与旧实现逐字等价）。
    """
    pending = list(tools)
    done = []

    def _one():
        label, factory = pending.pop(0)
        build_one(label, factory)
        done.append(label)

    if not pending:
        if on_done is not None:
            on_done()
        return done, 0

    _one()
    if not defer_rest:
        while pending:
            _one()
        if on_done is not None:
            on_done()
        return done, 0

    def _step():
        # 窗口已经关掉时 after 回调仍可能被排上：TclError 直接收工，不再续链。
        try:
            if not pending:
                if on_done is not None:
                    on_done()
                return
            _one()
            root.after(1, _step)
        except tk.TclError:
            return

    root.after(1, _step)
    return done, len(pending)


# ====================== 主程序 ======================
if __name__ == "__main__":
    # ══ 0. 日志最先 ══ 此后 DPI / 窗口 / 图标 / 主题 / 插件 / 组件的每一步都可被记录
    log_summary(f"=== {APP_NAME} {full_version()} 启动 ===")
    log_detail(f"Python {sys.version.split()[0]} | frozen={getattr(sys, 'frozen', False)} "
               f"| 应用目录 {app_dir()}")
    log_detail(f"日志文件 {log_path()}")

    # DPI 感知已在 toolkit_base 导入期统一设置（见 HIDPI_STATUS）。这里只如实记录
    # 结果 —— 旧写法自己调一次且不检查 HRESULT，失败也照样写"已应用"。
    log_detail(f"DPI: {HIDPI_STATUS}")

    root = _BaseTk()
    # 启动帧一律按**用户上次选的主题**画：原写法是先 `apply_theme()`（默认暗色）、
    # 再由 `build_hub(load_user_theme())` 切一次 —— 选了亮色的用户启动会先闪一下
    # 暗色。这里读一次，从头到尾只用这一个值。
    start_mode = load_user_theme()
    # 缩放必须在**用 px() 之前**同步：apply_tk_defaults 里也会同步一次，
    # 但它排在 geometry 之后 —— 顺序反了的话窗口尺寸就按 1.0 的系数算，
    # 在 150% 屏上仍然偏小（这正是端到端跑真 Hub 抓到的）。
    sync_tk_scaling(root)
    root.title(f"{APP_NAME} {full_version()}")
    set_app_icon(root)
    # 窗口尺寸按当前缩放换算：geometry/minsize 用的是**物理像素**，
    # 写死 1280x860 在 150% 屏上只有 853x573 逻辑像素，窗口会明显偏小。
    root.geometry(f"{px(1280)}x{px(860)}")
    root.minsize(px(1024), px(700))
    apply_theme(start_mode)
    root.configure(bg=T["bg"])
    apply_tk_defaults(root, start_mode)
    # ══ 启动白屏修复 ══ 装任何组件之前先画一帧（理由见 paint_startup 的说明）。
    paint_startup(root)
    # 标题栏跟随主题必须在顶层窗口**已映射**之后调，否则 GetParent 返回 0、
    # DwmSetWindowAttribute 打空（apply_titlebar 内部注释记的就是这个坑）；
    # 上一行的 update_idletasks() 正好让窗口完成映射。
    apply_titlebar(root, start_mode)
    log_detail("窗口 / 图标 / 启动主题 已就绪（已先绘制一帧，随后扫描插件 / 装配组件）")

    # 全局插件宿主：进程级共享实例（Hub 栏目 + 文件系统工具 + 插件栏目同源）。
    shared_plugins = PluginManager.shared(
        os.path.join(app_dir(), "plugins"),
        log=lambda msg, tag="info": log_detail(msg, tag),        # 扫描过程 → 详细日志
        summary=lambda msg, tag="info": log_summary(msg, tag),   # 加载结果 → 简略日志
    )
    log_summary(f"插件扫描完成: 发现 {len(shared_plugins.plugins)} 个，"
                f"错误 {len(shared_plugins.load_errors)} 个")
    for err in shared_plugins.load_errors[:10]:
        log_summary(err, "err")

    TOOLS = list(BUILTIN_TOOLS)
    # 插件栏目按 order 升序稳定插入（未指定者默认 0，保持注册顺序）；
    # 内置六工具固定在前 —— 顺序可调是为了"中间插入环节不打乱布局"。
    for tool in sorted(shared_plugins.tools,
                       key=lambda t: t.get("order", 0)):
        name = tool.get("name") or tool.get("info", {}).get("name", "插件")
        TOOLS.append((name, tool.get("builder")))

    def rebuild(nb, apps, defer_rest=True, on_done_extra=None):
        """装配全部栏目（调度见 build_tabs）。

        `defer_rest=True` 是**启动路径**：只同步装第一个栏目，其余分帧，好让
        mainloop 尽早跑起来；切主题 / 将来重建界面用 `defer_rest=False`（一次性
        装完，与旧实现一致）。注意 `apply_theme()` 由 on_done 在**全部装完后**
        调用一次 —— 它要配约 100 条 ttk 样式，绝不能进装配循环。

        `on_done_extra` 是**全部装完后**额外要做的事（启动路径用它摘掉加载遮罩）。
        """
        for tab in nb.tabs():
            nb.forget(tab)
        apps.clear()

        def _build_one(label, factory):
            tab = tk.Frame(nb, bg=color("bg"))
            # **不再关 pack_propagate**（2026-09-13 反转，用户："这些地方应该出现滚动条"）。
            # 原来关掉是因为：页面请求高度合计 900+，会把 Notebook 顶高、把日志栏压成 1px。
            # 现在栏目区 pane 已经是**自己会滚的裁剪视口**（fit="content"），顶高不再伤日志栏：
            # 页面说出自己需要多高 → 视口据此决定"要不要出纵向滚动条"。
            # 反过来，关掉 propagate 时页面请求高度是 **1px**，视口就以为"内容装得下" ——
            # 于是页面被裁掉一截却**连一条滚动条都没有**（用户实机截图圈出的右侧空条）。
            nb.add(tab, text=label)
            try:
                apps[label] = factory(tab)
                log_detail(f"组件已加载: {label}")
            except Exception as e:
                log_summary(f"组件加载失败: {label} — {e}", "err")
                ttk.Label(tab, text=f"加载失败: {e}", style="Red.TLabel").pack(pady=30)
            # 每装完一个栏目就画一帧（同步路径与分帧路径都经过这里）。
            paint_now(root)

        def _done():
            apply_theme()                 # 全部装完后才配 ttk 样式（绝不进装配循环）
            if on_done_extra is not None:
                try:
                    on_done_extra()
                except Exception as e:
                    log_detail("装配收尾失败: %s" % e, "warn")

        return build_tabs(root, TOOLS, _build_one, defer_rest=defer_rest,
                          on_done=_done)

    def build_hub(mode="dark"):
        """构建 hub 全部界面 (仅首次构建时销毁重建; 切主题只换色不重建)."""
        for w in root.winfo_children():
            w.destroy()
        apply_theme(mode)
        apply_titlebar(root, mode)
        root.configure(bg=color("bg"))

        header = ttk.Frame(root)
        # 留白统一（2026-09-13）：外壳 14 / 分组 10 / 组内 6。
        header.pack(fill="x", padx=16, pady=(14, 8))
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        # 主题下拉框在右, 标签在其左侧
        theme_var = tk.StringVar(value="暗色" if mode == "dark" else "亮色")

        def on_theme(val):
            mode = "light" if val == "亮色" else "dark"
            apply_theme(mode)
            save_user_theme(mode)
            apply_titlebar(root, mode)
            root.configure(bg=color("bg"))
            refresh_theme(root)

        om = ttk.OptionMenu(header, theme_var, theme_var.get(), "暗色", "亮色", command=on_theme)
        om.pack(side="right")
        ttk.Label(header, text="主题:", style="Dim.TLabel").pack(side="right", padx=(0, 4))

        # ── 栏目区"自己管自己"（用户口径 2026-09-13）──────────────────────
        # 用户明确："日志是不归主窗口滚动条管的"。所以不再用一条窗口级滚动条把两栏一起滚，
        # 而是让**栏目区**成为裁剪式窗格（`fit="content"`：内容保持自己需要的高度，
        # 装不下由**它自己**的滚动条解决），日志栏回到普通窗格、由它自己的滚动条管。
        # 两个 minsize 用同一组变量：否则"栏目的下限"与"日志的下限"会各说各话。
        min_top, min_log = px(260), px(110)
        # 栏目内容的**最小高度**（"页面至少需要多高才可用"）：窗口够高 → 内容随视口铺满；
        # 窗口不够 → 内容保持这个下限，由栏目区**自己的滚动条**解决（日志栏不受影响）。
        PAGE_MIN_H = px(430)
        nb_paned = SplitPane(root, orient="vertical")
        nb_paned.pack(fill="both", expand=True, padx=14, pady=(2, 6))
        nb_box = nb_paned.add_clipped(weight=3, minsize=min_top, fit="content")
        # 取视口必须用 `_panes()`（真控件）：`ttk.Panedwindow.panes()` 返回的是 Tcl 路径
        # **字符串** —— 对它取 `.scroll_wheel` 会抛 AttributeError，被 except 吞掉后
        # **滚轮绑定根本没装上**（用户实测 2026-09-13："没法滚轮滚动，只能把鼠标移上去
        # 才能滚动"）。这个坑 `SplitPane._panes()` 的 docstring 里早就写着，我还是踩了。
        try:
            nb_view = nb_paned._panes()[0]
        except Exception as e:
            nb_view = None
            log_summary(f"栏目区视口取不到：{e}", "warn")
        if nb_view is not None:
            nb_view._min_y = PAGE_MIN_H          # 视口下限 = 页面最小高度
            nb_view._sync()
            # 滚轮绑在**窗口**上，只滚栏目区那个视口：内层自己能滚的控件（日志/树/文本框）
            # 会自己消费并 break，事件到不了这里 —— "在树里滚树、在别处滚整页"。
            try:
                root.bind("<MouseWheel>", nb_view.scroll_wheel, add="+")
            except Exception as e:
                log_summary(f"栏目区滚轮绑定失败：{e}", "warn")
        # ── 统一滚轮路由（用户口径 2026-09-13："窗口内还是不能滚轮操控"）────────
        # Tk 只把滚轮送到"指针下那个控件"的 bindtags（控件 → 类 → 顶层 → all）；
        # 面板/页面内部的视口 canvas **不在**那条链上，所以给"顶层绑一个处理器"这种
        # 做法只能滚到最外层那一个视口。这里改成**一条路由**：
        #   ① 指针下是内层自己能滚的控件（文本框 / 列表 / 树）→ 交给它，别插手；
        #   ② 否则从指针下的控件沿 `master` 链往上找**第一个能滚的视口**并滚它；
        #   ③ 一个都滚不动 → 什么都不做（不再有"有的地方能滚有的不能"）。
        def _wheel_router(event):
            w = getattr(event, "widget", None)
            try:
                import tkinter as _tk
                if isinstance(w, (_tk.Text, _tk.Listbox)) or getattr(w, "_ctree", None):
                    return None                       # 内层自己滚
            except Exception:
                pass
            depth = 0
            while w is not None and depth < 60:
                fn = getattr(w, "try_scroll", None)
                if callable(fn):
                    try:
                        if fn(event):
                            return "break"
                    except Exception:
                        pass
                w = getattr(w, "master", None)
                depth += 1
            return None

        root.bind("<MouseWheel>", _wheel_router, add="+")
        nb = ttk.Notebook(nb_box)
        nb.pack(fill="both", expand=True)
        log_lf = ttk.LabelFrame(nb_paned, text="日志", padding=4)
        nb_paned.add(log_lf, weight=1, minsize=min_log)
        log_bar = ttk.Frame(log_lf); log_bar.pack(fill="x", pady=(0, 2))

        def export_log():
            """导出日志到 程序目录/logs/：GUI 简略日志 + 落盘的详细日志合并输出。"""
            try:
                g_log._flush()  # 先落盘 pending 缓冲日志
                logs_dir = os.path.join(app_dir(), "logs")
                os.makedirs(logs_dir, exist_ok=True)
                fn = os.path.join(logs_dir, f"log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("═══ 简略日志 (GUI) ═══\n")
                    f.write(g_log.get("1.0", "end"))
                    f.write(f"\n═══ 详细日志 ({os.path.basename(log_path())}) ═══\n")
                    try:
                        with open(log_path(), "r", encoding="utf-8") as src:
                            shutil.copyfileobj(src, f)
                    except Exception as e:
                        f.write(f"(详细日志读取失败: {e})\n")
                g_log.add(f"日志已导出: {fn}", "ok")
            except Exception as e:
                g_log.add(f"导出失败: {e}", "err")

        def clear_log():
            """清空 GUI 日志栏。

            旧的文件系统工具有自己的日志面板 + 「清空」按钮；重构后日志面板
            统一到 Hub（工具内不再各自建面板），但**清空入口一直没人补**，
            于是这条用户可达功能整体消失、只能等 5000 行自动截断。
            这里补在 Hub 上：一次覆盖六个内置工具与所有插件栏目。
            只清界面，不动本次的 runtime 日志文件 —— 详细日志仍可用「导出」取回。
            """
            try:
                g_log.clear()
                g_log.add("日志已清空（落盘的详细日志不受影响，仍可用「导出」取回）", "dim")
            except Exception as e:
                g_log.add(f"清空失败: {e}", "err")

        ttk.Button(log_bar, text="导出", width=6, command=export_log).pack(side="right")
        ttk.Button(log_bar, text="清空", width=6, command=clear_log).pack(
            side="right", padx=(0, 6))
        ttk.Label(log_bar, text="运行日志", style="Dim.TLabel").pack(side="left")
        g_log = LogBox(log_lf, height=6)

        # 日志通道接通：启动阶段（GUI 未就绪）的 summary 已缓冲，这里回放。
        # sink 经 _make_pump 投递到主线程，后台线程调 summary 也安全。
        _log_pump = _make_pump(root)
        set_gui_sink(lambda msg, tag="info": _log_pump(g_log.add, msg, tag))
        for _msg, _tag in take_log_buffer():
            g_log.add(_msg, _tag)
        log_detail("GUI 日志栏已接通")

        # A-2（外部审计 2026-09-12）：日志**写不出去**必须让用户看见。
        # 启动阶段那几次 log_summary/log_detail 已经试过写盘，这里读标志位即可；
        # 用 log_summary 说一句会再试一次写盘（同样失败 → 标志位不变），
        # 但能进日志栏 —— 用户至少知道"这次的日志没有文件可查"。
        if log_write_failed() is not None:
            log_summary(f"日志无法落盘：{log_write_failed()}"
                        "（本次运行的日志没有保存到文件）", "err")

        # 插件加载结果不再单独渲染：PluginManager 已通过 summary 通道上报，
        # 启动期进缓冲、此处随上面的回放进入日志栏；详细过程在本次的 runtime 日志里。

        apps = {}
        # 外壳（标题 / 标签页 / 日志栏）先落地并**画出来**，再装配栏目：
        # 日志栏此刻已经接通，所以这一句用户看得见（装配过程有反馈，不是干等）。
        log_summary("正在装配内置栏目…")

        # ── 加载遮罩（用户口径 2026-09-13）────────────────────────────────
        # "整个窗口在没有完全加载的时候显示加载转圈，直接看着控件一个个跳出来太难看了。"
        # 盖在**栏目区**上（日志栏不盖：它此刻已经能用，用户能看到"正在装配"那几行）。
        # 装配全部结束由 on_done_extra 摘掉；遮罩自己还有 20 s 看门狗兜底。
        busy = BusyOverlay(nb_box, text="正在加载组件…")
        busy.start()
        paint_now(root)
        paint_now(root)
        # 首个栏目同步装，其余分帧（见 build_tabs）：mainloop 因此早约 1.2 s 跑起来，
        # 窗口不再是"画出来了但点不动"。
        sync_done, rest = rebuild(nb, apps, on_done_extra=busy.stop)
        log_detail("首个栏目已就绪（%s），其余 %d 个分帧装配"
                   % ("、".join(sync_done), rest))

        # 打开/切换组件后，别停在"上一个组件的输入框被选中"的状态（用户口径 2026-09-12）：
        # Notebook 切页时 Tk **不会**动焦点 —— 上一个组件里的输入框即使已经不可见，
        # 焦点与选中高亮仍留着（切回去光标还停在那儿）。这里每次切页收敛一次。
        install_tab_focus_reset(nb, root)()          # 初次装配完也收敛一次

        # 布局体检数据进运行日志：用户报"布局不对/被挤没了"时，直接看这一行就够
        # （窗口尺寸、两栏实际高度、各自的最小值），不必再靠截图或录屏反推。
        # 放在 after(1)：此刻刚装配完、几何已经过一轮 idle，读数才有意义。
        def _log_layout():
            try:
                log_detail("布局: 窗口 %dx%d | 栏目区 h=%d (min %d) | 日志栏 h=%d (min %d)"
                           % (root.winfo_width(), root.winfo_height(),
                              nb.winfo_height(), px(260),
                              log_lf.winfo_height(), px(110)))
            except Exception:
                pass
        root.after(1, _log_layout)

    build_hub(start_mode)
    log_detail("进入主循环（首个栏目已就绪，其余分帧装配）")
    if shared_plugins.load_errors:
        root.after(
            800,
            lambda: messagebox.showwarning(
                "插件加载失败",
                "\n".join(shared_plugins.load_errors[:10]),
            ),
        )
    root.mainloop()
