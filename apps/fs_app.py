# -*- coding: utf-8 -*-
"""文件系统 App (FSToolApp)."""
from apps._bootstrap import (
    os, threading, subprocess, tempfile, shutil, Path,
    tk, ttk, filedialog, messagebox
)
import atexit

from toolkit import (
    color, dir_row, count_label, tool_header, CanvasTree, SplitPane, PluginManager,
    ScrollPanel,
    _make_pump, _HAS_DND, DND_FILES, log_summary, log_detail, plugin_slot_bar, tool_dropdown,
    plugin_options_area, tool_panel, TaskRunner, px,
    status_style_name, HOST_FS, LOC_CONTEXT, AREA_TOP_BAR, AREA_FORMAT, AREA_PACK_FORMAT,
    hidden_kwargs, output_ext_for, DEFAULT_PACK_BASENAME, invoke_plugin_callback
)

import stalker_fs
from stalker_fs import (FORMATS, pack_db, unpack_db, extract_file, auto_detect,
                         load_db, sqfs_check, sqfs_list, sqfs_extract, sqfs_pack)
ALL_FMTS = {**FORMATS, "sqfs": {"name": "SquashFS", "key": "sq", "scrambler": None, "pack": False}}
# 本工具用 ALL_FMTS 的键作为下拉取值、用 ["name"] 作为说明文字。sqfs 的说明名是
# "SquashFS"，若不做映射，下拉显示内部 id 而右侧说明显示 "SquashFS"（M6：同一个
# 东西两处名称不一致）。这里把两者的关系显式写死一处，下拉与说明都显示用户看得懂
# 的名字；"sqfs" 作为历史取值继续被识别（老配置/插件条目不会因此失效）。
_SQ_FMT_NAME = ALL_FMTS["sqfs"]["name"]
# ⚠ 判定用 `fmt.lower()`，所以**集合也必须是小写** —— 原实现把 "SquashFS" 原样放进来，
# 于是 `_is_sqfs_fmt("SquashFS")` 恒为 False：下拉里那个唯一的 SquashFS 条目因此绕过
# sqfs 分派，落到 pack_db 的历史兼容分支被**静默按 xdb 打包**（文件名还叫 .SquashFS.db）。
_SQ_FMT_IDS = {"sqfs", _SQ_FMT_NAME.lower()}


def _is_sqfs_fmt(fmt):
    """fmt 是否指 SquashFS（用户可见名 "SquashFS" 或历史 id "sqfs"）。"""
    return isinstance(fmt, str) and fmt.lower() in _SQ_FMT_IDS


class _Node:
    __slots__ = ("name", "path", "is_dir", "size", "size_comp", "offset", "use_lzhuf", "checked", "children", "source")

    def __init__(self, name, path, is_dir, size=0, offset=0, size_comp=0, use_lzhuf=False):
        self.name = name; self.path = path; self.is_dir = is_dir; self.size = size
        self.size_comp = size_comp
        self.offset = offset; self.checked = False; self.children = {}; self.source = None
        self.use_lzhuf = use_lzhuf

    def add(self, child):
        self.children[child.name] = child

    def merge(self, other):
        for name, child in other.children.items():
            if name in self.children:
                cur = self.children[name]
                if cur.is_dir and child.is_dir:
                    cur.merge(child)
            else:
                self.children[name] = child

    def toggle(self, checked):
        self.checked = checked
        if self.is_dir:
            for c in self.children.values():
                c.toggle(checked)

    def dir_state(self):
        """三态勾选: True=全部文件勾选, False=部分勾选, None=未勾选.
        按子树文件实际勾选计数 (修复: 目录半勾不再误判为未选)."""
        cnt = tot = 0
        stack = list(self.children.values())
        while stack:
            n = stack.pop()
            if n is None:
                continue
            if not n.is_dir:
                tot += 1
                if n.checked:
                    cnt += 1
            else:
                stack.extend(n.children.values())
        if tot == 0:
            return True if self.checked else None
        if cnt == 0:
            return None
        if cnt == tot:
            return True
        return False

    def collect(self, out):
        if not self.is_dir:
            if self.checked and self.source:
                out.append(self)
        elif not self.children and self.checked:
            out.append(self)
        else:
            for c in self.children.values():
                c.collect(out)


def _is_db(p):
    n = os.path.basename(p).lower(); d = n.rfind("."); return d >= 0 and n[d:d+3] == ".db"
def _is_sq(p):
    n = os.path.basename(p).lower(); d = n.rfind("."); return d >= 0 and n[d:d+3] == ".sq"


def _sqfs_extract_ok(got):
    """sqfs_extract 返回值 → 成功与否（H6）。

    引擎的约定（见 file_system/stalker_fs.py）：
        > 0  实际解出的文件数      → 成功
        - 1  按包批量/整镜像导出成功 → 成功
          0  失败（缺工具、镜像坏、rdsquashfs 返回非 0）
    旧代码调用后无条件 `ok += 1`，把失败也算成成功；而只判 `> 0` 又会把
    -1 这个成功码误判为失败，所以必须同时认这两种成功形态。
    """
    return isinstance(got, int) and got != 0
class FSToolApp:
    """文件系统（X-Ray DB / SquashFS）工具。

    统一契约：只接收宿主 Tab（parent）——不自建根窗口、不应用主题、不自建日志面板；
    日志走全局两级通道（log_summary / log_detail）。
    插件宿主取进程级共享实例（PluginManager.shared()），与 Hub、插件栏目同源。
    """

    def __init__(self, parent):
        self.root = parent
        self.root.configure(bg=color("bg"))
        self.fmt_var = tk.StringVar(value="auto")
        self.input_var = tk.StringVar(); self.output_var = tk.StringVar()
        self._last_input = ""
        self._set_output = ""          # 用户/浏览显式设定过的输出值（不是自动推断出来的）
        self._auto_output = ""         # 最近一次由输入自动推断出来的输出值
        self.db_files = []; self.files_data = []
        self.loaded = {}; self.raws = {}; self.merged = None
        # 解密临时文件：全部落在本 App 自己的会话目录里，便于注销/退出时确定性清理
        self._tmpdir = None
        self._tmpfiles = set()
        self._tmp_lock = threading.Lock()
        self._busy = False
        atexit.register(self._cleanup_temp_dir)
        self.plugins = PluginManager.shared()
        self._ui = _make_pump(self.root)
        self._build_ui()
        # 统一任务壳：忙碌标志 / 进度 / 状态语义色 / 线程。
        #   封包   —— progress_started 起 indeterminate 动画，收尾 stopped 停止并复位；
        #   解包   —— 任务自己把进度条切成 determinate 并写"当前项数"，
        #             所以 task.progress_update 传 (已完成, 总项数)，由 _on_progress
        #             归一化成 0~100 写进进度条（适配的是 set_progress(pct) 的契约，
        #             而不是把条目计数直接当百分比）。
        self.task = TaskRunner(
            self.root, self._ui,
            on_busy=self._set_busy,
            status_setter=lambda text, kind="idle": self.status_lbl.configure(
                text=text, style=status_style_name(kind)),
            progress_setter=self._on_progress,
            progress_started=self._progress_show,
            progress_stopped=self._progress_hide,
        )
        # 插件右键项的 when 依赖 loaded：构造时先算一次（此刻 loaded 为空）
        self._refresh_plugin_context_menu()
        self.input_var.trace_add("write", self._on_input_change)

    # ═══ UI ═══
    def _build_ui(self):
        # 基础格式 + 插件注册的格式 + 插件往 ("fs","format") 加的条目
        self.fmt_keys = (["auto"] + [ALL_FMTS[k]["name"] for k in ALL_FMTS]
                         + [f["name"] for f in self.plugins.formats]
                         + self.plugins.option_entries_for(HOST_FS, AREA_FORMAT))
        self.pack_fmt_keys = ([k for k in self.fmt_keys if k != "auto"]
                              + self.plugins.option_entries_for(HOST_FS, AREA_PACK_FORMAT))
        P = 14
        tool_header(self.root, "STALKER X-Ray FS Tool")
        # 插件动作区（toolbar 槽；无插件注册时不创建任何控件）
        self._slot_bar = plugin_slot_bar(self.root, HOST_FS, app=self,
                                         context={"loaded": bool(self.loaded)})
        top = ttk.Frame(self.root); top.pack(fill="x", padx=P, pady=(0,4))
        # 统一走 toolkit 工厂：基础格式 + 插件往 ("fs","format") 加的条目；无插件时外观不变
        tool_dropdown(top, HOST_FS, AREA_FORMAT, self.fmt_var, self.fmt_keys,
                      label="格式", label_width=4, padx=(4, 8))
        self.fmt_desc = ttk.Label(top, text="自动检测", style="Dim.TLabel"); self.fmt_desc.pack(side="left")
        self.fmt_var.trace_add("write", self._on_fmt_change)
        ttk.Button(top, text="解包选中", command=self._unpack_checked).pack(side="right", padx=(4,0))
        ttk.Button(top, text="批量解包", command=self._unpack_batch).pack(side="right")

        # ── 插件新建的下拉（api.register_option，area="top_bar"）──
        # 统一由 toolkit 渲染：无注册时不创建控件；插件新增下拉无需改本文件。
        # 下拉的取值由插件自己通过 register_option(callback=...) 拿到（PLUGINS.md §3.4），
        # 所以这里不需要保留返回值/变量 —— 原先那对 `plugin_option()` / `plugin_options()`
        # 取值访问器全工程无人调用，连同 `plugin_option_vars` 一起删掉了。
        plugin_options_area(self.root, HOST_FS, area=AREA_TOP_BAR, app=self,
                            pack_kw={"fill": "x", "padx": P, "pady": (0, 4)})
        # ── 插件贡献的子栏目（api.register_panel，area="top_bar"）──
        tool_panel(self.root, HOST_FS, AREA_TOP_BAR, app=self,
                   pack_kw={"fill": "x", "padx": P, "pady": (0, 4)})

        for label, var, cmd, drop in [
            ("输入", self.input_var, self._browse_input, self._on_drop_input),
            ("输出", self.output_var, self._browse_output, self._on_drop_output)]:
            # 统一目录行 (toolkit.dir_row): 标签+输入框+浏览+拖拽
            dir_row(self.root, label, var, browse=cmd, drop=drop)

        # 状态行：**空闲时只占一行文字**，进度条在有任务时才出现。
        # 用户口径 2026-09-13（"布局也能改"）：原来进度条常驻、和"就绪"各占一行，
        # 而它 99% 时间是空的 —— 白占一行高度、还把下面的工作区顶下去。
        # 这与"滚动条平时隐藏"是同一条原则：**空着的东西不该占位**。
        pg = ttk.Frame(self.root); pg.pack(fill="x", padx=P, pady=(4, 2))
        self.progress = ttk.Progressbar(pg, mode="indeterminate")
        self.status_lbl = ttk.Label(pg, text="就绪", style=status_style_name("idle"),
                                    font=color("font_sm"))
        self.status_lbl.pack(side="left")
        self._progress_packed = False        # 进度条此刻有没有占位（见 _progress_show/hide）

        outer = SplitPane(self.root, orient="vertical")
        outer.pack(fill="both", expand=True, padx=P, pady=(0,2))
        pan = SplitPane(outer, orient="horizontal")
        # minsize 保住主工作区：原来封包面板（含一个 Canvas 请求）+ 权重分配会
        # 把「数据包列表 / 包内文件」压到 1~15 px（实测 1024x700、1280x860），
        # 而它是本工具的主要操作区。weight 3:1 已偏向它，minsize 只防被挤没。
        outer.add(pan, weight=3, minsize=px(160))
        self._build_db_panel(pan)
        self._build_file_panel(pan)
        self._build_pack_panel(outer)
        # 日志面板由 Hub 统一提供，工具内不再自建

    def _build_db_panel(self, pan):
        # 横向分栏的窗格走**裁剪式**：拖分隔条时这一侧的左边框不动、内容左对齐。
        # 面板本身用统一的 `ScrollPanel`（2026-09-13）：**面板里有东西显示不完全**
        # 就出它自己的滚动条（按钮行被遮住时能在面板底部横向滚，长列表能纵向滚）。
        panel = ScrollPanel(pan.add_clipped(weight=1), "数据包列表（.db / .sq）")
        panel.pack(fill="both", expand=True)
        left = panel.body
        self.db_panel = panel
        bar = ttk.Frame(left); bar.pack(fill="x", pady=(0,2))
        # 这几个按钮在后台任务期间会被禁用：它们会改 loaded/raws，改了之后
        # 运行中的工作线程再读到就会错（见 _set_busy）。
        self.db_btns = []
        for text, width, cmd, pad in (
                ("扫描目录", 8, self._scan_dir, (0, 0)),
                ("全选", 5, self._select_all_db, (4, 0)),
                ("加载选中", 8, self._load_selected, (4, 0)),
                ("取消加载", 8, self._unload_selected, (4, 0)),
                ("移除", 5, self._remove_db, (4, 0)),
                ("清空", 5, self._clear_db, (4, 0))):
            b = ttk.Button(bar, text=text, width=width, command=cmd)
            b.pack(side="left", padx=pad)
            self.db_btns.append(b)
        self.db_count = count_label(bar)
        li = ttk.Frame(left); li.pack(fill="both", expand=True)
        self.db_ctree = CanvasTree(li, with_chk=True,
                                   on_toggle=self._db_toggle, on_click=self._db_click,
                                   chk_state=self._db_chk_state,
                                   row_status=self._db_row_status,
                                   fmt_size=self._fmt_size, on_change=self._refresh_db_list)
        self.db_ctree.get().pack(side="left", fill="both", expand=True)
        if _HAS_DND:
            self.db_ctree.get().drop_target_register(DND_FILES)
            self.db_ctree.get().dnd_bind("<<Drop>>", self._on_drop_db_list)
        # 插件右键动作（context 槽）：菜单在 _refresh_plugin_context_menu 里就地重建，
        # 每次都按当前 loaded 重新过滤 when。这里直接复用 CanvasTree 自己的 _ctx 菜单
        # （CanvasTree 的按钮与命令闭包都绑在它上面，换一个新 Menu 对象会让按钮失效）。
        # CanvasTree 只在自己那个 <Button-3> 处理器里 post 该菜单，所以插件项要生效
        # 必须**再绑一次真正收到事件的 canvas**，而不是 helper 默认绑的 frame。
        self._ctx_menu = self.db_ctree._ctx
        # 记下"原有项"的条数：之后只从这一条往后增删插件项，
        # 既不重复追加，也不可能误删 CanvasTree 自己的菜单项。
        try:
            end = self._ctx_menu.index("end")
        except Exception:
            end = None
        self._ctx_base_count = (end + 1) if end is not None else 0
        self.db_ctree.canvas.bind("<Button-3>", self._post_ctx_menu, add="+")

    def _post_ctx_menu(self, e):
        """右键：先按当前 loaded 重建插件项，再弹出与 CanvasTree 同一个菜单。"""
        self._refresh_plugin_context_menu()
        self._ctx_menu.tk_popup(e.x_root, e.y_root)

    def _refresh_plugin_context_menu(self):
        """按当前 loaded 就地重算右键菜单里的插件项（when 因此不再是一次性死条件）。

        只删除/追加 `_ctx_base_count` 之后的条目（也就是本方法自己之前加的那些），
        原有菜单项原样保留 —— 顺序固定为「原有项 → 分隔符 → 插件项」。
        """
        menu = getattr(self, "_ctx_menu", None)
        if menu is None:
            return
        base = getattr(self, "_ctx_base_count", 0)
        try:
            end = menu.index("end")
            if end is not None and end >= base:
                menu.delete(base, "end")
        except Exception:
            pass
        try:
            if getattr(self, "plugins", None) is None:
                return
            items = self.plugins.menu_items_for(HOST_FS, LOC_CONTEXT,
                                                {"loaded": bool(self.loaded)})
        except Exception:
            return
        for it in items:
            cb = it.get("handler")
            if not callable(cb):
                continue
            # 与 toolbar 槽一致：经 invoke_plugin_callback 调用（传宿主 app，
            # 且插件回调抛异常时留痕而不是冒到 Tk）
            menu.add_command(label=it.get("label") or "动作",
                             command=lambda c=cb: invoke_plugin_callback(c, self))

    def _build_file_panel(self, pan):
        # 同上：统一的 ScrollPanel（面板内部自己的滚动条，出现条件 = 有东西显示不完全）。
        panel = ScrollPanel(pan.add_clipped(weight=2), "包内文件")
        panel.pack(fill="both", expand=True)
        right = panel.body
        self.file_panel = panel
        bar = ttk.Frame(right); bar.pack(fill="x", pady=(0,2))
        ttk.Button(bar, text="全选", width=6, command=self._check_all).pack(side="left")
        ttk.Button(bar, text="全不选", width=6, command=self._check_none).pack(side="left", padx=(4,0))
        self.entry_count = count_label(bar)
        sf = ttk.Frame(right); sf.pack(fill="x", pady=(0,2))
        ttk.Label(sf, text="搜索", width=4).pack(side="left")
        self.search_var = tk.StringVar(); self.search_var.trace_add("write", lambda *a: self._render())
        ttk.Entry(sf, textvariable=self.search_var, font=color("font_mono")).pack(side="left", fill="x", expand=True)
        ri = ttk.Frame(right); ri.pack(fill="both", expand=True)
        self.ctree = CanvasTree(ri, with_chk=True, fmt_size=self._fmt_size,
                                on_change=self._refresh_db_list)
        self.ctree.get().pack(side="left", fill="both", expand=True)

    def _build_pack_panel(self, parent):
        pf = ttk.LabelFrame(parent, text="封包", padding=4)
        # 封包栏也要有**最小高度**（2026-09-13 用户口径："封包只漏了一点点"）：
        # 没有它时，窗口一矮这一栏就被挤成十来像素（实测 10px），
        # 里面的"输出/浏览/封包"按钮全看不见 —— 而它是本工具的第二主操作区。
        parent.add(pf, weight=1, minsize=px(120))
        # Row 1: format + output + pack button
        row1 = ttk.Frame(pf); row1.pack(fill="x", pady=(0,2))
        self.pack_fmt_var = tk.StringVar(value="xdb")
        # 统一走 toolkit 工厂：主题一致（不再手写配色），插件也可往该下拉加条目
        tool_dropdown(row1, HOST_FS, AREA_PACK_FORMAT, self.pack_fmt_var, self.pack_fmt_keys,
                      label="格式", label_width=4, padx=(4, 8))
        ttk.Label(row1, text="输出", width=4).pack(side="left")
        self.pack_out_var = tk.StringVar()
        pe = ttk.Entry(row1, textvariable=self.pack_out_var, font=color("font_mono"))
        pe.pack(side="left", fill="x", expand=True, padx=(4,4))
        if _HAS_DND:
            pe.drop_target_register(DND_FILES)
            pe.dnd_bind("<<Drop>>", self._on_drop_pack_out)
        ttk.Button(row1, text="浏览", width=6, command=self._browse_pack_out).pack(side="left")
        self.pack_btn = ttk.Button(row1, text="封包", width=6, command=self._pack,
                                   style="Accent.TButton")
        self.pack_btn.pack(side="left", padx=(4,0))
        # Row 2: file list buttons
        bar = ttk.Frame(pf); bar.pack(fill="x", pady=(0,2))
        ttk.Button(bar, text="+文件", width=5, command=self._add_files).pack(side="left")
        ttk.Button(bar, text="+目录", width=5, command=self._add_dir).pack(side="left", padx=(4,0))
        ttk.Button(bar, text="移除", width=5, command=self._remove_files).pack(side="left", padx=(4,0))
        ttk.Button(bar, text="清空", width=5, command=self._clear_files).pack(side="left", padx=(4,0))
        self.pack_count = count_label(bar)
        # Row 3: tree-style file list — same CanvasTree component as file panel (no checkboxes)
        pi = ttk.Frame(pf); pi.pack(fill="x")
        self.pack_ctree = CanvasTree(pi, with_chk=False, fmt_size=self._fmt_size)
        self.pack_ctree.get().pack(side="left", fill="x", expand=True)
        if _HAS_DND:
            self.pack_ctree.get().drop_target_register(DND_FILES)
            self.pack_ctree.get().dnd_bind("<<Drop>>", self._on_drop_pack_list)

    # ═══ 任务忙碌态 / 进度 ═══
    def _set_busy(self, busy):
        """后台任务期间禁用会改 loaded/raws/files_data 的入口。

        没有这一步，解包线程迭代 self.loaded 的同时，用户点「取消加载/移除/清空」
        或在 DB 列表里勾包（会新增键）就能让工作线程抛
        RuntimeError: dictionary changed size during iteration，整批解包中断。
        真正的数据安全另有快照保证（见 _unpack_checked / _unpack_batch）。
        """
        self._busy = bool(busy)
        state = "disabled" if busy else "normal"
        for b in getattr(self, "db_btns", ()):
            try:
                b.configure(state=state)
            except Exception:
                pass
        for name in ("pack_btn",):
            b = getattr(self, name, None)
            if b is not None:
                try:
                    b.configure(state=state)
                except Exception:
                    pass

    def _progress_show(self):
        """有任务了：进度条**出现**在状态行右侧（空闲时不占位）。"""
        try:
            if not self._progress_packed:
                self.progress.pack(side="left", fill="x", expand=True, padx=(10, 0))
                self._progress_packed = True
            self.progress.start()
        except Exception:
            pass

    def _progress_hide(self):
        """任务收尾：停下、复位、**收掉**。"""
        try:
            self.progress.stop()
            self.progress.configure(mode="indeterminate")
            if self._progress_packed:
                self.progress.pack_forget()
                self._progress_packed = False
        except Exception:
            pass

    def _on_progress(self, v):
        """TaskRunner 的进度写入口：按当前模式把入参归一化成 0~100。"""
        try:
            if str(self.progress.cget("mode")) == "determinate":
                peak = float(self.task._progress_total or 1) or 1.0
                pct = float(v) * 100.0 / peak
            else:
                pct = 50.0        # indeterminate 下数值无意义，给个中性值
            self.progress.configure(value=max(0.0, min(100.0, pct)))
        except Exception:
            pass

    def _start_task_progress(self, total):
        """任务开始：清掉上一轮的进度值，再切成 determinate。"""
        try:
            self.progress.configure(mode="determinate", maximum=100.0, value=0.0)
        except Exception:
            pass
        self.task._progress_total = max(1, int(total))
        self.task.reset_progress()

    def _set_status(self, text, kind="idle"):
        """写状态文案 + 语义色（颜色必须经状态语义，不写字面量）。"""
        try:
            self.status_lbl.configure(text=text, style=status_style_name(kind))
        except Exception:
            pass

    # ═══ Model ═══
    def _build_model(self, entries, src):
        """Build file tree from archive entries (DB or plain SquashFS).
        src = package path; per-file source/offset/size for extraction.

        条目字段一律按"缺键也不能炸"读：解析完全交给插件/引擎，插件 handler
        返回缺键条目时这里曾直接 KeyError 冒到 Tk 回调（H8）。
        """
        root = _Node("", "", True)
        for e in entries or ():
            path = str(e.get("path") or "")
            if not path:
                continue
            is_dir = bool(e.get("is_dir"))
            parts = path.replace("\\", "/").split("/")
            n = root
            for i, part in enumerate(parts):
                sub_dir = (i < len(parts) - 1) or is_dir
                if part not in n.children:
                    n.add(_Node(part, "/".join(parts[:i + 1]), sub_dir,
                                0 if sub_dir else int(e.get("size_real") or 0),
                                0 if sub_dir else int(e.get("offset") or 0)))
                n = n.children[part]
            if not n.is_dir:
                size_real = int(e.get("size_real") or 0)
                n.source = src; n.offset = int(e.get("offset") or 0); n.size = size_real
                n.size_comp = int(e.get("size_comp") or size_real)
                n.use_lzhuf = bool(e.get("use_lzhuf", False))
        return root

    def _rebuild_merged(self):
        """重建合并树，并把"状态变了"广播到插件槽位与右键菜单。"""
        self.merged = _Node("", "", True)
        for root in self.loaded.values(): self.merged.merge(root)
        self._refresh_slot()

    # ═══ 插件槽位 ═══
    def _refresh_slot(self):
        """状态变化后重算 toolbar 槽位的 when，并重建右键菜单的插件项。

        调用点：_rebuild_merged() 末尾 —— 所有会改 self.loaded 的入口
        （加载选中 / 取消加载 / 清空 / 勾选 / 拖放加载）都经它，因此
        when={"loaded": True} 的插件命令在这些路径之后都会正确出现/消失，
        而不是只在 _load_all_checked 那一条路径上生效。
        """
        slot = getattr(self, "_slot_bar", None)
        if slot is not None:
            slot.refresh({"loaded": bool(self.loaded)})
        self._refresh_plugin_context_menu()

    # ═══ Render ═══
    def _render(self):
        q = self.search_var.get().strip().lower().replace("\\", "/")
        self.ctree.set_root(self.merged, q)
        nf = self.ctree.file_count()
        self.entry_count.configure(text=f"{nf} 文件" if nf else "")

    # ═══ DB list ═══
    def _add_db(self, path):
        if path not in self.db_files: self.db_files.append(path)
        self._refresh_db_list()

    def _scan_dir(self, d=None, then=None):
        """扫描目录里的包 → 加入 DB 列表。

        `rglob` 放在**工作线程**：真实模组的 gamedata 树动辄上万文件，主线程
        扫一遍就是几百毫秒到一两秒的卡顿。`then` 在主线程收尾后回调（拖放路径
        用它串起"扫描 → 加载"）。
        """
        d = d or self.input_var.get().strip()
        if not d or not os.path.isdir(d):
            if then is not None:
                then()
            return
        log_summary(f"扫描 {d} ...", "dim")

        def work():
            found = []
            for f in Path(d).rglob("*"):
                try:
                    if f.is_file() and (_is_db(str(f)) or _is_sq(str(f))):
                        found.append(str(f))
                except OSError:
                    continue
            self._ui(apply, found)

        def apply(found):
            added = 0
            for sf in found:
                if sf not in self.db_files:
                    self.db_files.append(sf); added += 1
            self.db_files.sort(key=lambda x: os.path.basename(x).lower())
            self._refresh_db_list()
            log_summary(f"新增 {added} 个, 共 {len(self.db_files)} 个", "ok")
            if then is not None:
                then()
        if not self.task.run(work, status="扫描目录中…", on_error=self._load_error):
            log_summary("正在执行其它任务，请稍候再试", "warn")

    def _refresh_db_list(self):
        """DB list = CanvasTree, each DB a single checkable leaf item."""
        root = _Node("", "", True)
        for f in self.db_files:
            n = _Node(os.path.basename(f), f, False)
            # 包可能在扫描之后被外部删除/改名，而本函数是勾选/重绘的回调，
            # 每次都无条件 getsize 会从 Tk 回调抛 FileNotFoundError（H7）。
            try:
                n.size = os.path.getsize(f)
            except OSError:
                n.size = 0
            n.source = f
            root.add(n)
        self.db_ctree.set_root(root)
        self.db_count.configure(text=f"{len(self.db_files)} 个" if self.db_files else "")

    def _db_chk_state(self, node):
        """DB checkbox shows its package's file-check state (partial-aware)."""
        db = node.source
        if db in self.loaded:
            return self.loaded[db].dir_state()
        return None

    def _db_row_status(self, node):
        """DB row shows load state."""
        db = node.source
        if db in self.loaded:
            return ("[已加载]", color("green"))
        return ("[未加载]", color("text_dim"))

    def _db_toggle(self, node):
        """Check/uncheck a DB: auto-load if needed, then toggle its files.

        加载走工作线程：未加载过的包要先解析，而解析大包在 UI 线程里会卡住界面。
        """
        db = node.source
        if db in self.loaded:
            st = self.loaded[db].dir_state()
            self.loaded[db].toggle(st is not True)
            self._rebuild_merged(); self._render(); self._refresh_db_list()
            return

        def after():
            root = self.loaded.get(db)
            if root is not None:
                root.toggle(True)          # 勾选 = 该包全部文件打勾
            self._rebuild_merged(); self._render(); self._refresh_db_list()
        if not self._load_async([db], "加载", then=after):
            log_summary("正在加载其它包，请稍候再试", "warn")

    def _db_click(self, node):
        """DB row click: selection only — do NOT toggle check on plain click
        (toggle happens via checkbox hit only; presence here also prevents the
        default leaf-click toggle path)."""
        pass

    def _forget_db(self, path):
        """从会话状态里摘掉一个包，并回收它专属的解密临时文件。

        必须先回收临时文件再清 raws —— _drop_dec_tmp 是从 raws 里读临时文件
        路径的，先 pop 就再也找不到它了。
        """
        self._drop_dec_tmp(path)
        self.loaded.pop(path, None)
        self.raws.pop(path, None)

    def _remove_db(self):
        doomed = set(self.db_ctree.get_selected_paths())
        if not doomed: return
        for f in doomed:
            if f in self.db_files:
                self.db_files.remove(f)
                self._forget_db(f)
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    def _clear_db(self):
        self.db_files = []; self.loaded.clear(); self.raws.clear(); self.merged = None
        # loaded/raws 都清空了，解密临时文件自然全部作废 —— 一并删除（H5）
        self._clear_dec_tmp()
        self._refresh_db_list(); self._render()
        self._refresh_slot()

    def _select_all_db(self):
        """Select all DB rows."""
        self.db_ctree.select_all()

    def _load_all_checked(self):
        """Load all DB files AND check all their contents (used after drag-drop).

        解析整批包放在工作线程里（拖入一个模组目录后往往有几十个包）。

        ★ **必须先确认拿得到执行权，再清空**。历史顺序是反的：先 `loaded.clear()` /
        `raws.clear()` / `_clear_dec_tmp()`，再调 `_load_async` —— 而它在任务忙碌时返回
        False 拒绝执行。于是"先清后拒"等于把**正在跑的**解包任务的数据抽走：raws 没了、
        dec_*.sqfs 被删，解包成片失败（日志里一堆"包已不在内存中"），而用户只看到一句
        "正在加载其它包"。
        """
        if self.task.running:
            log_summary("正在执行其它任务，请稍候再试", "warn")
            return
        self.loaded.clear(); self.raws.clear()
        self._clear_dec_tmp()
        if not self._load_async(list(self.db_files), "加载", check_all=True):
            log_summary("正在加载其它包，请稍候再试", "warn")

    def _load_selected(self):
        """Load SELECTED (not checked) DB packages; check state untouched."""
        todo = [n.source for n in self.db_ctree._sel
                if n.source and n.source not in self.loaded]
        if not todo:
            return
        if not self._load_async(todo, "加载选中"):
            log_summary("正在加载其它包，请稍候再试", "warn")

    def _unload_selected(self):
        """Unload SELECTED (not checked) DB packages; check state untouched."""
        for node in self.db_ctree._sel:
            self._forget_db(node.source)
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    # ═══ Load ═══
    # 加密包一律走通用插件解密路径（_try_plugin_decrypt / _load_decrypted）：
    # 工具本身不认识任何具体模组名，也不 import 任何具体插件模块。

    @staticmethod
    def _dec_path(raw):
        """解密临时文件路径 (raws 值为 b'DEC:...' 时), 否则 None."""
        if isinstance(raw, bytes) and raw.startswith(b"DEC:"):
            return raw[4:].decode()
        return None

    def _session_tmpdir(self):
        """本 App 专属的解密临时目录（懒建，进程退出/清空时整体回收）。"""
        d = self._tmpdir
        if d is None or not os.path.isdir(d):
            d = tempfile.mkdtemp(prefix="stalker_fs_dec_")
            self._tmpdir = d
        return d

    def _new_dec_temp(self, path):
        """为 path 建一个新的解密临时文件，返回 (fileobj, realpath)。

        raws 在会话内还要用（解包要按路径再读它），所以这里只登记不删除；
        真正的删除点在 _forget_db / _clear_db / 进程退出。
        """
        old = self._dec_path(self.raws.get(path))
        if old:
            self._drop_dec_tmp(path)
        fd, tmp = tempfile.mkstemp(prefix="dec_", suffix=".sqfs",
                                   dir=self._session_tmpdir())
        with self._tmp_lock:
            self._tmpfiles.add(tmp)
        return os.fdopen(fd, "wb"), tmp

    def _drop_dec_tmp(self, path):
        """删除 path 对应的解密临时文件（若该包确实有）。"""
        if not self._tmpfiles:
            return
        tmp = self._dec_path(self.raws.get(path))
        if not tmp:
            return
        with self._tmp_lock:
            self._tmpfiles.discard(tmp)
            left = not self._tmpfiles
        try:
            os.unlink(tmp)
        except OSError:
            pass
        d = self._tmpdir
        if left and d and os.path.isdir(d):
            try:
                os.rmdir(d)
            except OSError:
                pass  # 目录非空（仍有临时文件）就留着

    def _clear_dec_tmp(self):
        """删除本会话全部解密临时文件与临时目录。"""
        with self._tmp_lock:
            files = list(self._tmpfiles)
            self._tmpfiles.clear()
        for f in files:
            try:
                os.unlink(f)
            except OSError:
                pass
        d = self._tmpdir
        if d and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    def _cleanup_temp_dir(self):
        """进程退出兜底：不留解密镜像在临时目录里（H5）。"""
        try:
            self._clear_dec_tmp()
        except Exception:
            pass

    def _load(self, path, fmt=None):
        """加载一个包。所有异常在这里收敛成日志（err），绝不冒到 Tk 回调（H8）。

        `fmt` 由调用方在**主线程**读好传进来：本方法会被放进工作线程执行
        （见 `_load_async`），而 `tk.StringVar.get()` 是一次 Tcl 调用，不能跨线程。
        传 None 时按老语义自己读（同步调用路径）。
        """
        try:
            if fmt is None:
                fmt = self.fmt_var.get()
            log_summary(f"浏览: {os.path.basename(path)} ({fmt})", "hdr")
            if _is_sq(path):
                kind = sqfs_check(path)
                if kind == "sqfs":
                    entries = sqfs_list(path)
                    if entries:
                        self.raws[path] = b"SQFS"  # marker: extraction via rdsquashfs
                        self.loaded[path] = self._build_model(entries, path)
                        nf = sum(1 for e in entries if not e.get("is_dir"))
                        log_summary(f"  SquashFS: {len(entries)} 项, {nf} 文件", "ok")
                    else:
                        log_summary("  SquashFS 列表失败（镜像损坏或缺 rdsquashfs）", "err")
                        self._diagnose_sqfs(path)
                elif kind == "encrypted":
                    # 加密容器：交给插件解密器；只有"没有任何插件认领"才提示缺插件
                    if self._try_plugin_decrypt(path) is None:
                        log_summary("  未找到可解密该文件的插件", "warn")
                elif self._try_plugin_decrypt(path):
                    pass
                else:
                    log_summary("  无法识别 .sq 文件", "warn")
                return
            raw = load_db(path)
            if _is_sqfs_fmt(fmt):
                # 用户显式选了 SquashFS，但这个文件不是 SquashFS 镜像
                log_summary(f"  所选格式 {fmt} 与该文件不符（不是 SquashFS 镜像）", "warn")
                return
            entries = None
            if fmt == "auto":
                fmt = auto_detect(raw)
                if not fmt:
                    # auto 模式也尝试插件格式
                    for pf in self.plugins.formats:
                        try:
                            entries = pf["handler"]["unpack"](raw)
                            if entries:
                                fmt = pf["name"]
                                break
                        except Exception:
                            continue
            if fmt:
                if entries is None:
                    plugin_fmt = next((f for f in self.plugins.formats if f["name"] == fmt), None)
                    if plugin_fmt:
                        entries = plugin_fmt["handler"]["unpack"](raw)
                    else:
                        entries = unpack_db(raw, stalker_fs.fmt_key(fmt))
                if not entries:
                    log_summary(f"  {fmt}: 解析失败", "warn")
                    return
                self._drop_dec_tmp(path)
                self.raws[path] = raw
                self.loaded[path] = self._build_model(entries, path)
                nf = sum(1 for e in entries if not e.get("is_dir"))
                log_summary(f"  {fmt}: {len(entries)} 项, {nf} 文件", "ok")
                return
            # 标准识别失败：交给插件解密器，解密后再按 hsqs / X-Ray DB 解析。
            if self._try_plugin_decrypt(path):
                return
            log_summary("  无法自动识别格式", "warn")
        except Exception as e:
            # 文件消失 / 权限 / 引擎异常 / 插件条目缺键 —— 全部在这里留痕，
            # 而不是让 traceback 从 Tk 回调里冒出去（既不进 GUI 日志也不进 runtime 日志）。
            log_summary(f"  加载失败: {os.path.basename(path)} — "
                        f"{type(e).__name__}: {e}", "err")

    # ═══ 加载（工作线程 + 主线程收尾）═══
    def _load_async(self, paths, label="加载", check_all=False, then=None):
        """在**工作线程**里解析若干包，回到主线程再动状态与界面。

        为什么必须这样：实测解析一个 3 万条目的 DB 要 **1.15 秒**，而旧实现
        把 `_load` 整段放在 UI 线程里跑 —— 点一下勾选框就卡住整个界面；
        真实模组的包更大，几秒不响应很常见。

        线程安全边界：
            * `fmt` 在**主线程**读好再传进 `_load`（`StringVar.get()` 是 Tcl 调用，
              不能在工作线程里碰）；
            * `_load` 只做 I/O / 解析 / 写 `loaded`·`raws` / 记日志，**不碰任何控件**；
            * 所有界面更新（`_rebuild_merged` / `_render` / `_refresh_db_list`）
              都在 `ok()` 里经 `self._ui` 回主线程执行。
        返回 False 表示已有任务在跑（重入保护），调用方据此提示"正在加载"。
        """
        paths = [p for p in paths if p]
        if not paths:
            if then is not None:
                then()
            return True
        fmt = self.fmt_var.get()          # 主线程读，供工作线程使用
        done = []

        def work():
            for p in paths:
                self._load(p, fmt)
                done.append(p)
            self._ui(ok)

        def ok():
            if check_all:
                for p in done:
                    root = self.loaded.get(p)
                    if root is not None:
                        root.toggle(True)
            self._rebuild_merged()
            self._render()
            self._refresh_db_list()
            if then is not None:
                then()
        return self.task.run(work, status=f"{label}中…", on_error=self._load_error)

    def _load_error(self, exc):
        """加载任务的失败出口（TaskRunner 已在主线程回调，且自己会记一条 err 日志）。"""
        self.task.set_status(f"加载失败: {exc}", "err")

    def _diagnose_sqfs(self, sqfs_path):
        """在 sqfs_list 失败后手动运行 rdsquashfs，把返回码/输出写入日志。"""
        tool = stalker_fs._find_sqfs_tool()
        if not tool:
            log_summary("  缺少 SquashFS 工具：请确认 deps\\squashfs-tools-ng-1.3.2-mingw64 目录完整（需要 rdsquashfs.exe）", "err")
            return
        try:
            r = subprocess.run(
                [tool, "--describe", sqfs_path],
                capture_output=True, text=True, timeout=30,
                **hidden_kwargs(),
            )
            log_summary(f"  rdsquashfs 路径: {tool}", "dim")
            log_summary(f"  rdsquashfs 返回码: {r.returncode}", "err")
            if r.stderr:
                log_summary(f"  rdsquashfs stderr: {r.stderr.strip()[:400]}", "err")
            if r.stdout:
                log_summary(f"  rdsquashfs stdout: {r.stdout.strip()[:200]}", "err")
        except Exception as e:
            log_summary(f"  rdsquashfs 运行失败: {e}", "err")

    def _try_plugin_decrypt(self, path):
        """交给插件解密器。

        返回 True  = 已处理成功
        返回 None  = 没有任何插件认领该文件
        返回 False = 有插件认领，但解密/解析失败（细节已记入日志）
        """
        entry = None
        try:
            if getattr(self, "plugins", None):
                entry = self.plugins.find_decryptor(path)
        except Exception:
            entry = None
        if not entry:
            return None
        # 用插件自己声明的名字（PLUGIN_INFO.name）上报，工具不硬编码任何模组名
        name = (entry.get("info") or {}).get("name") or entry.get("plugin") or "解密插件"
        try:
            raw = entry["decrypt"](path)
        except Exception as e:
            log_summary(f"  {name}: 解密失败: {e}", "err")
            return False
        if not raw:
            return False
        return self._load_decrypted(path, raw, name)

    def _load_decrypted(self, path, raw, name="解密插件"):
        """Parse decrypted bytes as SquashFS or X-Ray DB."""
        if raw[:4] in (b"hsqs", b"sqsh"):
            tf = None
            try:
                tf, tmp = self._new_dec_temp(path)
                tf.write(raw); tf.close()
                entries = sqfs_list(tmp)
                if not entries:
                    # 失败路径同样不留镜像（成功才登记进 _tmpfiles）
                    with self._tmp_lock:
                        self._tmpfiles.discard(tmp)
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    self._diagnose_sqfs(tmp)
                    log_summary(f"  {name}: 解密后 SquashFS 列表失败", "err")
                    return False
                self.raws[path] = b"DEC:" + tmp.encode()
                self.loaded[path] = self._build_model(entries, path)
                nf = sum(1 for e in entries if not e.get("is_dir"))
                log_summary(f"  {name}: SquashFS {len(entries)} 项, {nf} 文件", "ok")
                return True
            except Exception as e:
                log_summary(f"  解密后解析失败: {e}", "err")
                if tf is not None:
                    try:
                        self._drop_dec_tmp(path)
                    except Exception:
                        pass
                return False
            finally:
                if tf is not None and not tf.closed:
                    try:
                        tf.close()
                    except Exception:
                        pass
        fmt = auto_detect(raw)
        entries = None
        if not fmt:
            for pf in self.plugins.formats:
                try:
                    entries = pf["handler"]["unpack"](raw)
                    if entries:
                        fmt = pf["name"]
                        break
                except Exception:
                    continue
        if fmt:
            if entries is None:
                entries = unpack_db(raw, stalker_fs.fmt_key(fmt))
            if entries:
                self._drop_dec_tmp(path)
                self.raws[path] = raw
                self.loaded[path] = self._build_model(entries, path)
                nf = sum(1 for e in entries if not e.get("is_dir"))
                log_summary(f"  {name}: {fmt} {len(entries)} 项, {nf} 文件", "ok")
                return True
        log_summary(f"  {name}: 解密后数据无法识别", "err")
        return False

    def _check_all(self):
        """全选: 直接勾选所有已加载包 (包含暂未合并的节点)."""
        for root_ in self.loaded.values():
            root_.toggle(True)
        if self.merged:
            self.merged.toggle(True)
        self._render(); self._refresh_db_list()

    def _check_none(self):
        """全不选: 直接取消所有已加载包."""
        for root_ in self.loaded.values():
            root_.toggle(False)
        if self.merged:
            self.merged.toggle(False)
        self._render(); self._refresh_db_list()

    # ─── Input events ───
    def _on_fmt_change(self, *a):
        fmt = self.fmt_var.get()
        if fmt == "auto":
            self.fmt_desc.configure(text="自动检测")
            return
        desc = ALL_FMTS.get(fmt, {}).get("name", "")
        if not desc:
            pf = next((f for f in self.plugins.formats if f["name"] == fmt), None)
            desc = ((pf or {}).get("handler") or {}).get("description", "") or fmt
        self.fmt_desc.configure(text=desc)

    def _on_input_change(self, *a):
        p = self.input_var.get().strip()
        if p != self._last_input:
            self._last_input = p
            # 输入变化不再无条件清空输出（旧版也不动输出）：用户先设好输出目录、
            # 再改输入路径时，输出被清掉是新增的副作用（M1）。只有在输出框里放的
            # 就是上一次由输入自动推断出来的值、而现在输入没了的情况下才重算。
            if not p and self.output_var.get().strip() == self._auto_output:
                self.output_var.set("")
                self._auto_output = ""
        if p and os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
            # 输入框改了路径：**只加载这一个包**，不动其它已加载的包、也不改组内勾选状态。
            # 历史这里调 `_load_all_checked()` —— 那会清空全部已加载的包、重载所有 db_files
            # 并把每个包的文件**全打勾**，与「加载选中」（保持勾选不变）的语义正好相反：
            # 用户辛苦勾好的文件在换一个输入包时全丢/被全选。
            self._add_db(p)
            if not self._load_async([p], "加载"):
                log_summary("正在执行其它任务，请稍候再试", "warn")

    def _on_drop_input(self, e):
        paths = self.root.tk.splitlist(e.data)
        if not paths: return
        if len(paths) == 1:
            p = paths[0]
            # 与旧版语义一致：单个**文件**才写输入框（trace 会自动加载单文件）；
            # 拖入单个**目录**只扫描，不动输入框（旧版只在"单个文件"时写）。
            if os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
                self.input_var.set(p)
                return
            if os.path.isdir(p):
                self._scan_and_load([p])
                return
            return
        dirs = []
        for p in paths:
            if os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
                self._add_db(p)
            elif os.path.isdir(p):
                dirs.append(p)
        if dirs:
            self._scan_and_load(dirs)
        else:
            self._load_all_checked()

    def _scan_and_load(self, dirs):
        """拖入目录的完整链路：扫描 → 加入列表 → 全部加载并打勾。

        整条链**在一个工作线程里跑完**，中间只在两处回主线程刷界面：
            * 扫描出结果就立刻把包列表显出来（用户马上看到反馈）；
            * 全部加载完再重建合并树/重绘。
        为什么不拆成两个任务：`TaskRunner` 的 `then` 回调发生在任务真正 finish
        之前，这时再起新任务会被重入保护挡掉。合成一个任务既简单又没有竞态。
        """
        dirs = [d for d in dirs if d and os.path.isdir(d)]
        if not dirs:
            return
        if self.task.running:
            log_summary("正在执行其它任务，请稍候再试", "warn")
            return
        fmt = self.fmt_var.get()
        self.loaded.clear(); self.raws.clear()
        self._clear_dec_tmp()
        log_summary(f"扫描 {len(dirs)} 个目录 ...", "dim")

        def work():
            found = set()
            for d in dirs:
                for f in Path(d).rglob("*"):
                    try:
                        if f.is_file() and (_is_db(str(f)) or _is_sq(str(f))):
                            found.add(str(f))
                    except OSError:
                        continue
            listed = sorted(found, key=lambda x: os.path.basename(x).lower())
            self._ui(self._apply_scan_result, listed)
            for p in listed:
                self._load(p, fmt)
            for r in self.loaded.values():
                r.toggle(True)
            self._ui(self._finish_scan_load)
        self.task.run(work, status="扫描并加载中…", on_error=self._load_error)

    def _apply_scan_result(self, listed):
        """主线程：把扫描到的包并进列表并刷新（扫描一结束就让用户看到结果）。"""
        added = 0
        for sf in listed:
            if sf not in self.db_files:
                self.db_files.append(sf); added += 1
        self.db_files.sort(key=lambda x: os.path.basename(x).lower())
        self._refresh_db_list()
        log_summary(f"新增 {added} 个, 共 {len(self.db_files)} 个", "ok")

    def _finish_scan_load(self):
        """主线程：加载全部完成后重建合并树并重绘。"""
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    def _on_drop_db_list(self, e):
        """Drop onto DB list: collect archive files, then auto-load+check all."""
        dirs = []
        for p in self.root.tk.splitlist(e.data):
            if os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
                self._add_db(p)
            elif os.path.isdir(p):
                dirs.append(p)
        if dirs:
            self._scan_and_load(dirs)
        else:
            self._load_all_checked()

    def _on_drop_pack_list(self, e):
        """Drop onto pack list: folders recurse, archives excluded.

        整批合成**一个**任务（而不是逐项调 _add_dir）：任务壳有重入保护，
        逐项调用时第二项起会被"正在执行其它任务"直接拒掉，拖三个文件夹只有一个进去。
        """
        jobs = []
        base = self._pack_root()
        for p in self.root.tk.splitlist(e.data):
            if os.path.isdir(p):
                jobs.append((p, base or str(Path(p).parent), True))
            elif os.path.isfile(p) and not self._is_pack_file(p):
                jobs.append((p, base, False))
        if jobs:
            self._add_to_pack(jobs, "目录添加" if all(j[2] for j in jobs) else "添加")
        else:
            self._refresh_pack()

    def _on_drop_output(self, e): self.output_var.set(e.data.strip("{}").strip())

    def _browse_input(self):
        p = filedialog.askopenfilename(title="选择文件")
        if not p:
            p = filedialog.askdirectory(title="选择目录")
        if not p: return
        self.input_var.set(p)
        # Single file: trace (_on_input_change) handles load. Directory: scan here.
        if os.path.isdir(p):
            self._scan_and_load([p])

    def _browse_output(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self._set_output_value(p)

    def _set_output_value(self, val):
        """写「输出」框，并记录这是显式设定（供 M1 判断能否自动重算）。"""
        self._set_output = val
        self.output_var.set(val)

    # ─── Pack ───
    @staticmethod
    def _is_pack_file(p):
        """True if file is an archive (.db* / .sq*) — excluded from packing."""
        return _is_db(p) or _is_sq(p)

    @staticmethod
    def _pack_ext(fmt):
        """封包输出扩展名：sqfs → .sqfs，其余格式带上格式名（xdb → .xdb.db）。

        toolkit_constants.output_ext_for 除 sqfs 外一律返回 .db，用它会让
        6 种格式的产物同名同扩展名、用户无法从文件名分辨（M3，旧版是 f".{fmt}.db"）。
        """
        if _is_sqfs_fmt(fmt):
            return output_ext_for("sqfs")   # 主题/常量层已定义的 sqfs 特例
        key = stalker_fs.fmt_key(fmt)       # 显示名（"XDB (CS/CoP)"）也要落到内部键
        if key:
            return f".{key}.db"
        return output_ext_for(fmt)          # 未知/空格式 → 常量层默认扩展名

    def _add_files(self, paths=None):
        """Add files to pack list. Non-archive files only."""
        if paths is None:
            paths = filedialog.askopenfilenames(title="选择文件 (非包文件)")
        if not paths:
            return
        base = self._pack_root()
        self._add_to_pack([(str(p), base, False) for p in paths], "文件添加")

    def _add_dir(self, d=None):
        """Recursively add a folder's non-archive files. Folder name kept as top dir
        unless input dir is set as pack root."""
        if d is None:
            d = filedialog.askdirectory(title="选择目录 (递归, 排除包文件)")
        if not d or not os.path.isdir(d): return
        # Pack root: input dir if set; else the dropped folder's PARENT so the
        # folder itself shows as a top-level node.
        base = self._pack_root() or str(Path(d).parent)
        self._add_to_pack([(str(d), base, True)], "目录添加")

    def _pack_root(self):
        """封包根目录：设了输入目录就用它；否则 None（逐项回退到父目录 / 文件名）。"""
        iv = self.input_var.get()
        return iv if iv and os.path.isdir(iv) else None

    def _add_to_pack(self, jobs, label):
        """把文件/目录加进封包列表 —— 遍历与读盘全部在**工作线程**。

        jobs = [(path, base_or_None, recursive)]；base=None 表示相对路径就用文件名。

        原先这两个入口都在主线程 `sorted(rglob("*"))` 再逐个 `read()`：真实模组的
        gamedata 树动辄上万文件、几百 MB，整块 UI 冻住（与"勾选加载一个包"同一类
        问题，而性能锁当时只覆盖了后者）。顺带修掉同一段里的两处：
          · 去重写成 `rel in [x[0] for x in self.files_data]` —— 每加一个文件就把
            整个列表重建一次，几千个文件就是几百万次字符串比较（二次方）；
          · `except Exception: continue` 静默丢文件（路径不在 base 之下时），
            现在计数并在日志里说明；读盘失败也从"只留一行错误"改为汇总上报。
        注意顺序：`work()` 里**不碰任何 Tk**，结果经 `self._ui` 回主线程 apply。
        """
        def work():
            found, skipped, failed = [], 0, []
            for path, base, recursive in jobs:
                if recursive:
                    try:
                        cand = sorted(Path(path).rglob("*"))
                    except OSError as ex:
                        failed.append((os.path.basename(path), str(ex)))
                        continue
                else:
                    cand = [Path(path)]
                root = Path(base) if base else None
                for f in cand:
                    try:
                        if not f.is_file() or self._is_pack_file(str(f)):
                            continue
                    except OSError:
                        continue                # 断链 / 权限：跳过这一个
                    if root is None:
                        rel = f.name
                    else:
                        try:
                            rel = str(f.relative_to(root)).replace("\\", "/")
                        except ValueError:
                            skipped += 1
                            continue
                    try:
                        with open(f, "rb") as fh:
                            data = fh.read()
                    except OSError as ex:
                        failed.append((f.name, str(ex)))
                        continue
                    found.append((rel, data))
            self._ui(apply_result, found, skipped, failed)

        def apply_result(found, skipped, failed):
            have = set(x[0] for x in self.files_data)
            added = 0
            for rel, data in found:
                if rel in have:
                    continue
                have.add(rel)
                self.files_data.append((rel, data, False))
                added += 1
            self._refresh_pack()
            for name, ex in failed:
                log_summary(f"  读取失败: {name} — {ex}", "err")
            tail = f"，{skipped} 个不在封包根之下已跳过" if skipped else ""
            log_summary(f"{label}: {added} 个文件 (排除包文件){tail}", "dim")

        if not self.task.run(work, status=f"{label}中…", on_error=self._load_error):
            log_summary("正在执行其它任务，请稍候再试", "warn")

    def _remove_files(self):
        doomed = set(self.pack_ctree.get_selected_paths())
        if not doomed: return
        self.files_data = [x for x in self.files_data if x[0] not in doomed]
        self._refresh_pack()

    def _clear_files(self): self.files_data = []; self._refresh_pack()

    def _refresh_pack(self):
        """Render pack files as a folder tree (reuses CanvasTree, no checkboxes)."""
        root = _Node("", "", True)
        for rel, data, _ in self.files_data:
            parts = rel.split("/")
            n = root
            for i, part in enumerate(parts):
                is_dir = i < len(parts) - 1
                if part not in n.children:
                    n.add(_Node(part, "/".join(parts[:i+1]), is_dir,
                               len(data) if not is_dir else 0))
                n = n.children[part]
        self.pack_ctree.set_root(root)
        self.pack_count.configure(text=f"{len(self.files_data)} 项" if self.files_data else "")

    def _browse_pack_out(self):
        p = filedialog.askdirectory(title="选择封包输出目录")
        if p: self.pack_out_var.set(p)

    def _on_drop_pack_out(self, e):
        paths = self.root.tk.splitlist(e.data)
        if paths and os.path.isdir(paths[0]): self.pack_out_var.set(paths[0])

    def _pack_output_basename(self):
        """返回封包输出文件名（不含扩展名），无法可靠推断时返回 None。"""
        inp = self.input_var.get().strip()
        if inp and os.path.isdir(inp):
            return os.path.basename(os.path.normpath(inp))
        tops = []
        for rel, _, _ in self.files_data:
            top = rel.split("/", 1)[0]
            if top and top not in tops:
                tops.append(top)
        if len(tops) == 1 and tops[0]:
            top = tops[0]
            # 单文件封包时，去掉原扩展名；目录封包保留目录名
            if len(self.files_data) == 1 and "/" not in self.files_data[0][0]:
                return os.path.splitext(top)[0]
            return top
        return None

    def _resolve_pack_target(self):
        """确定封包落盘路径，并把它回填进「输出」框。

        返回最终路径；用户取消选择框时返回 None。
        H1：原来的写法是 `if not out: return; self.pack_out_var.set(out)`，
        set 被放在 return 之后，永不执行 —— 用户选完文件名后「输出」框仍是空/旧
        目录，界面不反映实际落盘位置，输出框为空时再点「封包」会再弹一次保存框。
        """
        fmt = self.pack_fmt_var.get()
        ext = self._pack_ext(fmt)
        base = self._pack_output_basename()
        out = self.pack_out_var.get().strip()
        if not out:
            initial = f"{base}{ext}" if base else f"{DEFAULT_PACK_BASENAME}{ext}"
            out = filedialog.asksaveasfilename(title="保存", defaultextension=ext,
                                               initialfile=initial)
            if not out:
                return None
        elif os.path.isdir(out):
            if base:
                out = os.path.join(out, f"{base}{ext}")
            else:
                out = filedialog.asksaveasfilename(title="保存", defaultextension=ext,
                                                   initialdir=out,
                                                   initialfile=f"{DEFAULT_PACK_BASENAME}{ext}")
                if not out:
                    return None
        elif not os.path.splitext(out)[1]:
            out = out + ext
        # 无论走哪条分支，最终落盘路径都反映到「输出」框
        self.pack_out_var.set(out)
        return out

    def _pack(self):
        if self.task.running: return
        if not self.files_data: messagebox.showwarning("无文件", "请先添加文件"); return
        fmt = self.pack_fmt_var.get()
        out = self._resolve_pack_target()
        if not out: return
        log_summary(f"封包 ({fmt})...", "hdr")
        # 明确进入 indeterminate（封包没有可数的进度，只有"忙"）
        try:
            self.progress.configure(mode="indeterminate")
        except Exception:
            pass
        # 快照：工作线程不再直接迭代会变的列表
        files = list(self.files_data)

        def work():
            if _is_sqfs_fmt(fmt):
                ok = sqfs_pack(files, out)
                if not ok:
                    raise RuntimeError("SquashFS 封包失败 (缺 tar2sqfs?)")
                log_summary(f"完成: SquashFS → {out}", "ok")
            else:
                db = self._pack_with_format(files, fmt)
                with open(out, "wb") as f:
                    f.write(db)
                log_summary(f"完成: {len(db)} 字节 → {out}", "ok")

        # 忙碌标志/进度/状态/线程由 TaskRunner 统一处理（异常不静默）
        self.task.run(work, status="封包中...",
                      final_status=("完成", "ok"),
                      on_error=lambda e: log_summary(f"封包错误: {e}", "err"))

    def find_plugin_format(self, fmt):
        """取该格式名对应的插件格式记录；没有则 None。"""
        return next((f for f in self.plugins.formats if f["name"] == fmt), None)

    def _pack_with_format(self, files_data, fmt):
        """封包派发：插件格式优先，否则回落内置 pack_db。

        抽成独立方法是为了**可被直接测试**——"新格式只写插件即可用"这条
        验收标准必须能验证"派发真的选了插件 handler"，而不是只验证 handler 存在。
        """
        plugin_fmt = self.find_plugin_format(fmt)
        if plugin_fmt:
            return plugin_fmt["handler"]["pack"](files_data)
        # 下拉给的是**显示名**（"XDB (CS/CoP)"），引擎只认内部键 —— 在这里归一，
        # 否则 5/6 个内置格式直接抛 ValueError（M6 回归，build_10 带此 bug）。
        return pack_db(files_data, stalker_fs.fmt_key(fmt))

    # ═══ Unpack ═══
    @staticmethod
    def _package_folder(db_path):
        """gamedata.db0 / gamedata.sq_base -> 'gamedata'"""
        return os.path.splitext(os.path.basename(db_path))[0]

    def _resolve_output(self):
        """解包输出根目录：为空时按输入/已扫描包推断，并回填「输出」框。

        H1 的另一半：输出框必须反映真实的落盘根目录，否则界面与实际位置不一致。
        """
        out = self.output_var.get().strip()
        if not out:
            if self.db_files: out = os.path.dirname(self.db_files[0])
            elif self.input_var.get(): p = self.input_var.get().strip(); out = os.path.dirname(p) if os.path.isfile(p) else p
            else: out = os.getcwd()
            self._set_output_value(out)
        return out

    def _unpack_checked(self):
        if self.task.running: return
        nodes = []
        if self.merged: self.merged.collect(nodes)
        if not nodes: messagebox.showwarning("无勾选", "没有打勾的文件"); return
        out = self._resolve_output()
        if not messagebox.askokcancel("解包选中", f"输出到:\n{out}\n\n共 {len(nodes)} 项"): return
        log_summary(f"解包 {len(nodes)} 项...", "hdr")
        # 快照：线程启动后界面仍可写 loaded/raws，工作线程一律读本地副本（H2/H3）
        total = len(nodes)
        raws = dict(self.raws)
        self._start_task_progress(total)

        def work():
            made = set()
            # Group by source: sqfs sources use rdsquashfs, db sources use raw bytes
            sqfs_src = {n.source for n in nodes
                        if raws.get(n.source) == b"SQFS"
                        or self._dec_path(raws.get(n.source))}
            # rdsquashfs 是按包批量导出的：只有它返回 >0 才算这一包成功（H6 的一半）
            sqfs_ok = set()
            for src in sqfs_src:
                sp = src if raws.get(src) == b"SQFS" else self._dec_path(raws.get(src))
                want = [{"path": n.path} for n in nodes
                        if n.source == src and not n.is_dir]
                if not sp:
                    log_summary(f"  {os.path.basename(src)}: 无可用的 SquashFS 路径，跳过 {len(want)} 项", "err")
                    continue
                try:
                    got = sqfs_extract(sp, os.path.join(out, self._package_folder(src)), want)
                except Exception as ex:
                    got = 0
                    log_summary(f"  {os.path.basename(src)}: SquashFS 解包异常 {ex}", "err")
                if _sqfs_extract_ok(got):
                    sqfs_ok.add(src)
                else:
                    log_summary(f"  {os.path.basename(src)}: SquashFS 解包失败"
                                f"（返回 {got!r}），跳过 {len(want)} 项", "err")
            done = fail = skip = 0
            for i, n in enumerate(nodes):
                try:
                    pkg = self._package_folder(n.source) if n.source else ""
                    # 归档内路径**不可信**（入口就是"打开下载来的包"）：统一经
                    # safe_out_path 收敛，逃逸条目一律拒绝并计入失败，绝不写到输出目录外。
                    p = stalker_fs.safe_out_path(os.path.join(out, pkg), n.path)
                    if p is None:
                        log_summary(f"  拒绝越界路径: {n.path!r}", "err")
                        fail += 1
                        continue
                    raw = raws.get(n.source)
                    if raw == b"SQFS" or self._dec_path(raw):
                        # 已由上面的 sqfs_extract 批量处理
                        if n.source in sqfs_ok: done += 1
                        else: fail += 1
                        continue
                    if n.is_dir:
                        os.makedirs(p, exist_ok=True)
                        made.add(p)
                        done += 1
                        continue
                    if not raw:
                        # 线程运行期间该包被取消加载 —— 记录，不再静默跳过（H3）
                        log_detail(f"  跳过 {n.path}: 包已不在内存中 ({os.path.basename(n.source or '')})")
                        skip += 1
                        continue
                    data = extract_file(raw, {"offset": n.offset, "size_real": n.size,
                                              "size_comp": n.size_comp, "is_dir": False})
                    # 空文件（b""）是**合法**的：只有 None 才算解不出来。
                    # 历史写法是 `if not data:` —— 空文件被计失败、解包后文件直接消失。
                    if data is None:
                        log_detail(f"  失败 {n.path}: 解包无数据")
                        fail += 1
                        continue
                    if not stalker_fs.write_extracted_file(p, data):
                        log_detail(f"  失败 {n.path}: 写入失败")
                        fail += 1
                        continue
                    done += 1
                except Exception as ex:
                    fail += 1
                    log_summary(f"  失败 {n.path}: {ex}", "err")
                self._ui(self.task.progress_update, i + 1, total)
            # "完成 N 项"必须反映实际成功数，跳过/失败单独计数（H3）
            log_summary(f"完成: 成功 {done} / 共 {total} 项（失败 {fail}，跳过 {skip}）", "ok")
            self._ui(self._set_status,
                     f"完成: 成功 {done} / 共 {total} 项", "ok")

        self.task.run(work, status="解包中...",
                      on_error=lambda e: log_summary(f"解包错误: {e}", "err"))

    def _unpack_batch(self):
        if self.task.running: return
        if not self.loaded: messagebox.showwarning("无加载", "请先加载包"); return
        out = self._resolve_output()
        # 入口处一次快照：工作线程不再迭代会变的 self.loaded / self.raws（H2/H3）
        entries = list(self.loaded.items())
        total = len(entries)
        raws = dict(self.raws)
        if not messagebox.askokcancel("批量解包",
                                      f"输出到:\n{out}\n\n共 {total} 个已加载包"): return
        log_summary(f"批量解包 {total} 个包...", "hdr")
        self._start_task_progress(total)

        def work():
            ok = tf = fail = skip = 0
            for idx, (db_path, root) in enumerate(entries):
                basename = os.path.basename(db_path)
                raw = raws.get(db_path)
                pkg = self._package_folder(db_path)
                self._ui(self.task.set_status,
                         f"[{idx+1}/{total}] {basename}", "running")
                if not raw:
                    log_summary(f"  跳过 {basename}: 包已不在内存中", "warn")
                    skip += 1
                    self._ui(self.task.progress_update, idx + 1, total)
                    continue
                try:
                    dp = self._dec_path(raw)
                    if raw == b"SQFS":
                        # 引擎失败返回 0 —— 不再无条件算成功（H6）
                        got = sqfs_extract(db_path, os.path.join(out, pkg))
                        if not _sqfs_extract_ok(got):
                            fail += 1
                            log_summary(f"  {basename}: SquashFS 全解失败（返回 {got!r}）", "err")
                        else:
                            ok += 1
                            log_summary(f"  {basename} → {pkg}/: SquashFS 全解 {got} 项", "ok")
                        self._ui(self.task.progress_update, idx + 1, total)
                        continue
                    if dp:
                        got = sqfs_extract(dp, os.path.join(out, pkg))
                        if not _sqfs_extract_ok(got):
                            fail += 1
                            log_summary(f"  {basename}: 解密包全解失败（返回 {got!r}）", "err")
                        else:
                            ok += 1
                            log_summary(f"  {basename} → {pkg}/: 解密包全解 {got} 项", "ok")
                        self._ui(self.task.progress_update, idx + 1, total)
                        continue
                    nodes = []; root.collect(nodes)
                    files = [n for n in nodes if not n.is_dir]
                    for n in files:
                        data = extract_file(raw, {"offset": n.offset, "size_real": n.size,
                                                  "size_comp": n.size_comp, "is_dir": False})
                        if data is None:
                            continue        # 解不出来；空文件是 b""，会正常写出 0 字节
                        p = stalker_fs.safe_out_path(os.path.join(out, pkg), n.path)
                        if p is None:
                            log_summary(f"  拒绝越界路径: {n.path!r}", "err")
                            continue
                        if not stalker_fs.write_extracted_file(p, data):
                            log_summary(f"  失败 {n.path}: 写入失败", "err")
                    ok += 1; tf += len(files)
                    log_detail(f"  {basename} → {pkg}/: {len(files)} 文件")
                except Exception as ex:
                    # 单包失败不中断整体，但必须留痕（不静默）
                    fail += 1
                    log_summary(f"  {basename}: 错误 {ex}", "err")
                self._ui(self.task.progress_update, idx + 1, total)
            log_summary(f"完成: 成功 {ok} / 共 {total} 个包（失败 {fail}，跳过 {skip}），共 {tf} 文件", "ok")
            self._ui(self._set_status, f"完成: {ok}/{total} 个包, {tf} 文件", "ok")

        self.task.run(work, status="批量解包中...",
                      on_error=lambda e: log_summary(f"批量解包错误: {e}", "err"))

    # ═══ Util ═══
    @staticmethod
    def _fmt_size(sz):
        if sz >= 1048576: return f"{sz/1048576:.1f} MB"
        if sz >= 1024: return f"{sz/1024:.1f} KB"
        return f"{sz} B"

    # 日志纪律：重要结果（谁加载了、解了哪些项、成功/失败多少）走 log_summary —— 进
    # GUI 日志栏并落盘；纯明细（单文件跳过原因、每包的解包条数等）走 log_detail —— 只落盘。
    # 任务收尾（复位 running / 停进度 / 复位 indeterminate）由 TaskRunner 统一负责
