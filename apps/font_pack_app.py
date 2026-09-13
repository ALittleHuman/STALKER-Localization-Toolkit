# -*- coding: utf-8 -*-
"""汉化包生成 App (FontPackApp)."""
from apps._bootstrap import (
    os, tk, ttk, filedialog, messagebox
)

from toolkit import (color, tool_header, dir_row, SplitPane, _make_pump,
                     AutoScrollbar,
                     log_summary, log_detail,
                     plugin_slot_bar, plugin_entries, errbox,
                     tool_panel,
                     TaskRunner, status_style,
                     themed_entry, themed_listbox, dialog_window,
                     HOST_FONT, AREA_BOTTOM,
                     AREA_GAME, AREA_LANG, AREA_SIZE, AREA_SUFFIX,
                     system_font_dirs, open_in_explorer, px)
from font_pack import GAMES, ensure_pillow, build_package

class FontPackApp:
    """汉化包生成。

    统一契约：只接收宿主 Tab（parent）——不自建根窗口、不应用主题、不自建日志面板；
    日志走全局两级通道（log_summary / log_detail）。
    """

    def __init__(self, parent):
        self.root = parent
        self.root.configure(bg=color("bg"))

        self._ui = _make_pump(self.root)
        # 生成结果标志: 供插件命令的 when={"has_results": ...} 判定 (见 _slot_bar)
        self._has_results = False
        self._build_ui()
        # 统一任务壳：忙碌标志 / 进度 / 状态文案 / 线程
        self.task = TaskRunner(
            self.root, self._ui,
            on_busy=lambda busy: self.gen_btn.configure(
                state="disabled" if busy else "normal"),
            status_setter=lambda text, kind="idle": self.status_lbl.configure(
                text=text, foreground=status_style(kind)),
            progress_started=self.progress.start,
            progress_stopped=self.progress.stop,
        )
        log_summary("就绪。选择汉化 XML 目录后点击生成。", "dim")

    # ─── UI ───
    def _build_ui(self):
        tool_header(self.root, "汉化包生成")
        # 插件动作区（toolbar 槽；无插件注册时不创建任何控件）
        # 保存句柄：context 传**可调用对象**，每次 refresh() 重新求值当前状态；
        # 生成成功后在主线程调 _slot_bar.refresh()，带 when={"has_results": true} 的命令才会出现。
        self._slot_bar = plugin_slot_bar(self.root, HOST_FONT, app=self,
                                         context=lambda: {"has_results": self._has_results})
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root); top.pack(fill="x", **pad)

        # 配置行
        row1 = ttk.Frame(top); row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="游戏版本:").pack(side="left")
        self.game_var = tk.StringVar(value="SoC")
        g = ttk.OptionMenu(row1, self.game_var, "SoC", *GAMES.keys(),
                           *plugin_entries(HOST_FONT, AREA_GAME))
        g.config(width=6); g.pack(side="left", padx=(4, 16))

        # 加载语言: eng/rus/chs/自定义 (自定义才显示输入框)
        ttk.Label(row1, text="加载语言:").pack(side="left")
        lang_box = ttk.Frame(row1); lang_box.pack(side="left", padx=(4, 16))
        self.lang_sel = tk.StringVar(value="chs")
        self.lang_entry = tk.StringVar(value="chs")
        om = ttk.OptionMenu(lang_box, self.lang_sel, "chs", "eng", "rus", "chs", "自定义",
                            *plugin_entries(HOST_FONT, AREA_LANG),
                            command=self._lang_changed)
        om.config(width=6); om.pack(side="left")
        self.lang_entry_box = themed_entry(lang_box, textvariable=self.lang_entry, width=6,
                                           font_role="font")
        self.lang_entry_box.pack_forget()  # 默认隐藏, 切自定义才显示

        # 尺寸
        ttk.Label(row1, text="尺寸:").pack(side="left")
        self.off_var = tk.StringVar(value="标准")
        om = ttk.OptionMenu(row1, self.off_var, "标准", "标准", "+3", "+5", "+7", "+9",
                            *plugin_entries(HOST_FONT, AREA_SIZE))
        om.config(width=4); om.pack(side="left", padx=(4, 16))

        # 字体后缀: 无/_chs/自定义 (自定义才显示输入框)
        ttk.Label(row1, text="后缀:").pack(side="left")
        suf_box = ttk.Frame(row1); suf_box.pack(side="left", padx=(4, 16))
        self.suf_sel = tk.StringVar(value="无")
        self.suf_entry = tk.StringVar(value="")
        om = ttk.OptionMenu(suf_box, self.suf_sel, "无", "无", "_chs", "自定义",
                            *plugin_entries(HOST_FONT, AREA_SUFFIX),
                            command=self._suf_changed)
        om.config(width=6); om.pack(side="left")
        self.suf_entry_box = themed_entry(suf_box, textvariable=self.suf_entry, width=6,
                                          font_role="font")
        self.suf_entry_box.pack_forget()  # 默认隐藏

        # 完整西里尔: 默认**开**。
        # 关掉（= "复刻旧包"）会剔除原版 CharAdder 编码 bug 丢失的那 40 个**常用**西里尔，
        # 而引擎对缺失码位不是留空，而是把整张表填成**同一个字形**
        # （OGSR `GameFont.cpp:130` `TCMap[i] = vFirstValid`）。在含未翻译俄文的目标
        # （NLC 等俄文模组）上，这等于满屏重复字形 —— 即"乱码"。
        # 旧 GUI 默认关，是当初为了与原版整包逐字节一致；以可用性优先，改为默认开。
        # 控件用**经典 tk.Checkbutton**（不是 ttk）：本仓库另外三处勾选项都是
        # tk.Checkbutton（convert_app 两处、text_extract_app 一处），配色统一走
        # toolkit_theme.apply_tk_defaults 里的 `*Checkbutton.*` 选项；ttk 那套走的是
        # TCheckbutton 样式，是唯一的异类 —— 主题切换时 refresh_theme 也是按
        # winfo_class()=="Checkbutton" 分支刷新的，ttk 的类名 TCheckbutton 根本不会命中。
        # 标签只留控件名：说明（关 = 复刻旧包，俄文会缺字）本就是上面这段注释的内容，
        # 不该挤在勾选项文字里。
        self.cyr_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row1, text="完整西里尔",
                       variable=self.cyr_var).pack(side="left", padx=(0, 16))

        # 路径行 (统一 path_row)
        self.xml_var = tk.StringVar()
        self.font_var = tk.StringVar()
        self.out_var = tk.StringVar()
        dir_row(top, "XML目录:", self.xml_var, browse=self._browse_xml, drop=self._on_drop_xml)
        dir_row(top, "字体文件:", self.font_var, browse=self._browse_font, drop=self._on_drop_font)
        dir_row(top, "输出目录:", self.out_var, browse=self._browse_out, drop=self._on_drop_out)

        # 默认字体: 系统微软雅黑优先; 仓库根 msyh.ttf 后备
        # （当前仓库未附带该文件, 因此实际上通常走系统字体, 后备分支形同预留）。
        # 字体目录由 toolkit_platform.system_font_dirs() 按平台给出，不写死 C:\Windows\Fonts
        for _fd in system_font_dirs():
            for _n in ("msyh.ttc", "msyh.ttf", "msyhl.ttc"):
                cand = os.path.join(_fd, _n)
                if os.path.exists(cand):
                    self.font_var.set(cand); break
            if self.font_var.get():
                break
        else:
            local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "msyh.ttf")
            if os.path.exists(local):
                self.font_var.set(local)

        # 按钮行
        row3 = ttk.Frame(top); row3.pack(fill="x", pady=(6, 0))
        self.gen_btn = ttk.Button(row3, text="生成汉化包", command=self._generate)
        self.gen_btn.pack(side="left")
        ttk.Button(row3, text="打开输出目录", command=self._open_out).pack(side="left", padx=(8, 0))
        self.status_lbl = tk.Label(row3, text="", bg=color("bg"), fg=status_style("idle"), font=color("font"))
        self.status_lbl.pack(side="right")

        # ═══ 进度条（日志面板由 Hub 统一提供，工具内不再自建） ═══
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(6, 8))

        # ═══ 插件贡献的**底部**面板区（api.register_panel，area=AREA_BOTTOM）═══
        # 与 AREA_TOP_BAR 的区别是"位置"而不是"机制"：这里在现有控件全部排布**之后**
        # 用 side=tk.BOTTOM 抢占剩余空腔的底边，于是它是本 Tab 最靠底的插件区
        # （AREA_TOP_BAR 是插在标题下方）。放在 _build_ui 末尾是**必须的**：
        # pack 按调用顺序分配，早排进去就会被后来的 top 侧控件挤到中间。
        # 无插件注册该区域时不创建任何控件，外观与未接插件时完全一致。
        # side 用 Tk 常量而不是裸字符串：静态守卫按**调用窗口**扫裸槽位名，而这里的
        # bottom 是 pack 的贴边值、不是 area —— 写常量既更贴 Tk 习惯，也不必为此放宽
        # toolkit_guard.RAW_AREA_RE 里 AREA_BOTTOM 的保护（那会连带漏掉裸 area）。
        tool_panel(self.root, HOST_FONT, AREA_BOTTOM, app=self,
                   pack_kw={"side": tk.BOTTOM, "fill": "x", "padx": 10, "pady": (0, 8)})

    # ─── 逻辑 ───
    @staticmethod
    def _placeholder(entry, var, text="自定义"):
        """Entry 水印: 空时显示灰色隐字, 聚焦清空; 返回是否处于水印态."""
        st = {"ph": False}
        def show():
            st["ph"] = True
            entry.delete(0, "end")
            entry.insert(0, text)
            entry.configure(foreground=color("text_dim"))
        def on_focus_in(e):
            if st["ph"]:
                entry.delete(0, "end")
                var.set("")
                entry.configure(foreground=color("text"))
            st["ph"] = False
        def on_focus_out(e):
            if not var.get().strip():
                show()
            else:
                st["ph"] = False
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)
        if not var.get().strip():
            show()
        return st

    def _lang_changed(self, val):
        if val == "自定义":
            self.lang_entry.set("")
            self._lang_ph = self._placeholder(self.lang_entry_box, self.lang_entry, "自定义")
            self.lang_entry_box.pack(side="left", padx=(2, 0))
        else:
            self.lang_entry.set(val)
            self.lang_entry_box.pack_forget()

    def _suf_changed(self, val):
        if val == "自定义":
            self.suf_entry.set("")
            self._suf_ph = self._placeholder(self.suf_entry_box, self.suf_entry, "自定义")
            self.suf_entry_box.pack(side="left", padx=(2, 0))
        elif val == "_chs":
            self.suf_entry.set("_chs")
            self.suf_entry_box.pack_forget()
        else:  # 无
            self.suf_entry.set("")
            self.suf_entry_box.pack_forget()

    # 日志统一走全局通道（log_summary / log_detail），不再自建 LogBox

    def _browse_xml(self):
        d = filedialog.askdirectory(title="选择汉化 XML 目录 (xmlfiles)")
        if d: self.xml_var.set(d)

    def _dropped_paths(self, event):
        """tkdnd 的 event.data → 路径列表。

        多选时数据形如 `{C:\\a.ttf} {C:\\b.ttf}`（含空格/中文时带花括号），
        原先的 `event.data.strip("{}")` 只去掉**最外层**首尾花括号，会得到
        `C:\\a.ttf} C:\\b.ttf` 这种既非文件也非目录的字符串，于是多文件拖放
        被静默忽略。tk 的 splitlist 才是官方解析方式（与 fs_app/text_extract 口径一致）。
        """
        data = str(getattr(event, "data", "") or "").strip()
        if not data:
            return []
        try:
            items = list(self.root.tk.splitlist(data))
        except Exception:
            items = [data]
        paths = [p for p in (str(i).strip().strip("{}").strip() for i in items) if p]
        if paths and not any(os.path.exists(p) for p in paths):
            # 兜底: 若 tkdnd 给的是**未加花括号**的裸路径（Tcl 会把路径里的
            # `\a`/`\b`/`\n`/`\t` 当反斜杠转义吃掉, 如 C:\a\b.ttf → C:<BEL><BS>.ttf），
            # 而原始串本身确实是存在的路径, 就采信原始串。
            raw_path = data.strip("{}").strip()
            if raw_path and os.path.exists(raw_path):
                return [raw_path]
        return paths

    def _on_drop_xml(self, event):
        """拖拽文件夹到 XML 目录框（多选时取第一个目录）。"""
        paths = self._dropped_paths(event)
        dirs = [p for p in paths if os.path.isdir(p)]
        if dirs:
            self.xml_var.set(dirs[0])
        else:
            log_summary("拖放的项不是目录（XML 目录需要 xmlfiles 文件夹）: "
                        f"{paths[0] if paths else '空的拖放数据'}", "warn")

    def _on_drop_font(self, event):
        """拖拽字体文件到字体框（多选时取第一个 .ttf/.ttc/.otf）。"""
        paths = self._dropped_paths(event)
        fonts = [p for p in paths
                 if os.path.isfile(p) and p.lower().endswith((".ttf", ".ttc", ".otf"))]
        if fonts:
            self.font_var.set(fonts[0])
        else:
            log_summary("拖放的项不是字体文件（需要 .ttf/.ttc/.otf）: "
                        f"{paths[0] if paths else '空的拖放数据'}", "warn")

    def _on_drop_out(self, event):
        """拖拽文件夹到输出目录框（多选时取第一个目录）。"""
        paths = self._dropped_paths(event)
        dirs = [p for p in paths if os.path.isdir(p)]
        if dirs:
            self.out_var.set(dirs[0])
        else:
            log_summary("拖放的项不是目录（输出目录需要一个文件夹）: "
                        f"{paths[0] if paths else '空的拖放数据'}", "warn")

    def _browse_font(self):
        """自建字体选择器: 列出系统字体目录全部 ttf/ttc/otf + 当前字体目录."""
        import fnmatch as _fnm
        if not hasattr(self, "_font_cjk"):
            self._font_cjk = {}
        win = dialog_window(self.root, "选择字体文件", size="900x520")

        bar = ttk.Frame(win); bar.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(bar, text="过滤:").pack(side="left")
        kw_var = tk.StringVar()
        kw_entry = themed_entry(bar, textvariable=kw_var)
        kw_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 图例: 列表里的裸符号原先没有任何说明, 且"检测失败"与"缺字形"混为一谈。
        # 精简口径：只保留"符号 = 什么意思"，判据细节（包围盒全同 / notdef 方块）属实现，
        # 用户不需要在界面上读 —— 那部分在下面的代码注释与本文件的 docstring 里。
        ttk.Label(win, text="图例: ✓ 含中文字形 · ⚠ 疑似缺字形 · ? 检测失败（与字体无关）",
                  style="Dim.TLabel", wraplength=860).pack(fill="x", padx=10, pady=(0, 4))

        body = SplitPane(win, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10)
        # 两个窗格都是**裁剪式**（用户口径 2026-09-13）：拖分隔条时各自的远侧边框不动、
        # 内容左对齐，窄到装不下就出横向滚动条，而不是把里面的控件压扁。
        # 容器是视口的 content，控件要自己 pack 进去（原来由 Panedwindow 代管）。
        list_frame = ttk.Frame(body.add_clipped(weight=3))
        list_frame.pack(fill="both", expand=True)
        lb = themed_listbox(list_frame)
        sb = AutoScrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 右侧预览区 (可拖拽分隔条调宽度；同样裁剪，见上)
        pv = ttk.Frame(body.add_clipped(weight=2))
        pv.pack(fill="both", expand=True)
        pv_top = ttk.Frame(pv)
        pv_top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(pv_top, text="预览", style="Dim.TLabel").pack(side="left")
        zoom = {"v": 1.0}
        ttk.Button(pv_top, text="−", width=2, command=lambda: set_zoom(-0.5)).pack(side="right", padx=(2, 0))
        zoom_lbl = ttk.Label(pv_top, text="100%", style="Dim.TLabel", width=5)
        zoom_lbl.pack(side="right")
        ttk.Button(pv_top, text="+", width=2, command=lambda: set_zoom(0.5)).pack(side="right", padx=(2, 0))
        # Canvas 预览区 (宽度随分隔条自适应, 支持滚动查看放大细节)
        pv.columnconfigure(0, weight=1)
        pv.rowconfigure(1, weight=1)
        pv_canvas = tk.Canvas(pv, bg=color("bg"), height=px(250),
                              highlightthickness=1, highlightbackground=color("border"))
        pv_sb_v = AutoScrollbar(pv, orient="vertical", command=pv_canvas.yview)
        pv_sb_h = AutoScrollbar(pv, orient="horizontal", command=pv_canvas.xview)
        pv_canvas.configure(yscrollcommand=pv_sb_v.set, xscrollcommand=pv_sb_h.set)
        pv_canvas.grid(row=1, column=0, sticky="nsew")
        pv_sb_v.grid(row=1, column=1, sticky="ns")
        pv_sb_h.grid(row=2, column=0, sticky="ew")
        preview_lbl = tk.Label(pv_canvas, bg=color("bg"))
        pv_canvas.create_window((4, 4), window=preview_lbl, anchor="nw")
        preview_lbl.bind("<Configure>",
                         lambda e: pv_canvas.configure(scrollregion=pv_canvas.bbox("all")))
        pv_name = ttk.Label(pv, text="", style="Dim.TLabel", wraplength=380)
        pv_name.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        pv_name.bind("<Configure>",
                     lambda e: pv_name.configure(wraplength=max(80, pv_name.winfo_width())))
        win.bind("<Configure>",
                 lambda e: pv_canvas.configure(width=max(120, pv_canvas.winfo_width())))

        # 唯一的字形判定: 返回 "ok" / "missing" / "unknown"。
        # 列表标记与预览标题**共用**这一判据, 避免同一字体两处结论互相矛盾。
        CJK_MARK = {"ok": "✓ 中文", "missing": "⚠ 疑似缺字形", "unknown": "? 检测失败"}

        def glyph_status(path):
            """中文字形判定的唯一判据: 逐字符取字形包围盒, 多个不同 bbox = 真实字形
            (notdef 缺字形对全部字符渲染同一方块, bbox 全相同). 0.1ms/字体级.

            返回值区分三态: "unknown" 是**检测失败**（PIL 缺失 / 字体无法解析）,
            与"字体缺中文字形"不是一回事, 界面上必须分开显示。
            """
            try:
                from PIL import ImageFont as _PIF
                font = _PIF.truetype(path, 40)
                boxes = set()
                for ch in "永你好汉化测":
                    b = font.getmask(ch).getbbox()
                    if b is None:
                        continue
                    boxes.add(b)
                return "ok" if len(boxes) > 1 else "missing"
            except Exception:
                return "unknown"

        def cached_status(path):
            """带缓存的判定（缓存跨对话框复用, 避免重复解析字体文件）。"""
            cache = self._font_cjk
            st = cache.get(path)
            if st not in CJK_MARK:
                st = cache[path] = glyph_status(path)
            return st

        def detect_all(start=0, gen=None, batch=24):
            """分片批量检测字体, 完成后整体重填带标记列表 (Listbox 不支持单条改文本).

            gen 是检测链代次: 过滤框每敲一个字符 refresh() 就 +1, 旧链在下一片
            发现代次不符即中止 —— 否则系统字体数百个时会多条链并发重填列表。
            """
            if gen != getattr(win, "_detect_gen", 0):
                return
            items = getattr(win, "font_items", [])
            cache = self._font_cjk
            end = min(start + batch, len(items))
            for i in range(start, end):
                path = items[i]
                if cache.get(path) not in CJK_MARK:
                    cache[path] = glyph_status(path)
            if gen != getattr(win, "_detect_gen", 0) or not win.winfo_exists():
                return
            if end < len(items):
                win.after(25, lambda: detect_all(end, gen))
            else:
                # 全部完成: 整体重填带标记 + 恢复选中当前字体
                cur = self.font_var.get().strip()
                lb.delete(0, "end")
                for path in items:
                    mark = CJK_MARK[cache.get(path, "unknown")]
                    lb.insert("end", f"{os.path.basename(path)}  [{os.path.dirname(path)}]  {mark}")
                if cur in items:
                    idx = items.index(cur)
                    lb.selection_clear(0, "end")
                    lb.selection_set(idx)
                    lb.see(idx)
                    win.after_idle(show_preview)

        def refresh(*_):
            kw = kw_var.get().strip().lower()
            lb.delete(0, "end")
            font_items = []
            dirs = list(system_font_dirs())
            cur = self.font_var.get().strip()
            if cur and os.path.isdir(os.path.dirname(cur)):
                d2 = os.path.dirname(cur)
                if d2 not in dirs:
                    dirs.append(d2)
            seen = set()
            for d in dirs:
                try:
                    names = sorted(os.listdir(d))
                except Exception:
                    continue
                for n in names:
                    if not _fnm.fnmatch(n.lower(), "*.ttf") and not _fnm.fnmatch(n.lower(), "*.ttc") \
                       and not _fnm.fnmatch(n.lower(), "*.otf"):
                        continue
                    if kw and kw not in n.lower():
                        continue
                    full = os.path.join(d, n)
                    if full in seen:
                        continue
                    seen.add(full)
                    font_items.append(full)
                    lb.insert("end", f"{n}  [{d}]")
            win.font_items = font_items
            # 后台分片自动识别中文字形。代次 +1 让上一次 filtering 触发的旧检测链作废:
            # 过滤框每敲一个字符都会走到这里, 旧链若不停会并发重填列表并反复重置选中项。
            win._detect_gen = getattr(win, "_detect_gen", 0) + 1
            gen = win._detect_gen
            win.after_idle(lambda: detect_all(0, gen))
            # 定位当前字体 (若有)
            cur = self.font_var.get().strip()
            if cur in font_items:
                idx = font_items.index(cur)
                lb.selection_clear(0, "end")
                lb.selection_set(idx)
                lb.see(idx)
                win.after_idle(show_preview)

        def set_zoom(delta):
            zoom["v"] = max(0.5, min(4.0, round(zoom["v"] + delta, 1)))
            zoom_lbl.configure(text=f"{int(zoom['v'] * 100)}%")
            show_preview()

        def show_preview(_=None):
            """选中字体时用 PIL 渲染预览文字 (支持缩放)。

            中文字形结论与列表标记**同源**（cached_status → glyph_status）,
            不再另用"墨迹覆盖率"判据, 以免同一字体在列表与预览里结论矛盾。
            """
            sel = lb.curselection()
            items = getattr(win, "font_items", [])
            if not sel or not (0 <= sel[0] < len(items)):
                return
            path = items[sel[0]]
            st = cached_status(path)
            if st == "missing":
                warn = "  ⚠ 疑似缺中文字形（字形判据）"
            elif st == "unknown":
                warn = "  ? 检测失败（PIL 不可用或字体无法解析）"
            else:
                warn = ""
            try:
                from PIL import Image, ImageDraw, ImageFont as _PIF, ImageTk
                size = int(40 * zoom["v"])
                font = _PIF.truetype(path, size)
                img = Image.new("RGB", (330, 130), color("bg"))
                d = ImageDraw.Draw(img)
                d.text((12, 10), "汉化测试你好ABC", font=font, fill=color("text"))
                d.text((12, 62), "Привет 世界 123", font=font, fill=color("text_dim"))
                photo = ImageTk.PhotoImage(img)
                preview_lbl.configure(image=photo)
                preview_lbl.image = photo
                pv_name.configure(text=f"{os.path.basename(path)}  [{font.getname()[0]}]{warn}")
            except Exception:
                preview_lbl.configure(image="")
                pv_name.configure(text=f"{os.path.basename(path)}  (预览失败){warn}")

        def pick(_=None):
            sel = lb.curselection()
            if not sel:
                return
            items = getattr(win, "font_items", [])
            if 0 <= sel[0] < len(items):
                self.font_var.set(items[sel[0]])
                win.destroy()

        def browse_other():
            # 初始目录同样取自 toolkit_platform（不再写死 C:\Windows\Fonts）
            font_dirs = system_font_dirs()
            f = filedialog.askopenfilename(
                title="选择字体文件",
                initialdir=os.path.dirname(self.font_var.get())
                if self.font_var.get() else (font_dirs[0] if font_dirs else ""),
                filetypes=[("字体文件", "*.ttf *.ttc *.otf"), ("所有文件", "*.*")])
            if f:
                self.font_var.set(f)
                win.destroy()

        btn_bar = ttk.Frame(win); btn_bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn_bar, text="选择", command=pick).pack(side="left")
        ttk.Button(btn_bar, text="浏览其他目录...", command=browse_other).pack(side="left", padx=(8, 0))
        ttk.Button(btn_bar, text="取消", command=win.destroy).pack(side="right")

        kw_var.trace_add("write", refresh)
        lb.bind("<<ListboxSelect>>", show_preview)
        lb.bind("<Double-Button-1>", pick)
        refresh()
        win.grab_set()

    def _browse_out(self):
        d = filedialog.askdirectory(title="选择输出目录 (将生成 gamedata 子文件夹)")
        if d: self.out_var.set(d)

    def _open_out(self):
        d = self.out_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showwarning("提示", "输出目录无效")
            return
        # open_in_explorer 失败返回 False（权限/文件管理器关联缺失）；原先忽略返回值，
        # 于是点了按钮毫无反馈，用户以为工具没反应。
        if not open_in_explorer(d):
            messagebox.showwarning("打开失败",
                                   f"无法在文件管理器中打开：\n{d}\n"
                                   "（可能缺少文件管理器关联或权限不足，请手动打开该目录）")

    def _generate(self):
        if self.task.running: return
        xml_dir = self.xml_var.get().strip()
        font = self.font_var.get().strip()
        out = self.out_var.get().strip()
        # 加载语言
        if self.lang_sel.get() == "自定义":
            lang = self.lang_entry.get().strip()
            if not lang or getattr(self, "_lang_ph", {}).get("ph"):
                messagebox.showwarning("缺少语言", "自定义加载语言不能为空"); return
        else:
            lang = self.lang_sel.get()
        # 字体后缀
        if self.suf_sel.get() == "自定义":
            suffix = self.suf_entry.get().strip()
            if not suffix or getattr(self, "_suf_ph", {}).get("ph"):
                messagebox.showwarning("缺少后缀", "自定义后缀不能为空"); return
        else:
            suffix = "" if self.suf_sel.get() == "无" else self.suf_sel.get()
        if not xml_dir or not os.path.isdir(xml_dir):
            messagebox.showwarning("缺少输入", "请选择汉化 XML 目录"); return
        if not font or not os.path.exists(font):
            messagebox.showwarning("缺少字体", "请选择 TrueType 字体文件 (如 msyh.ttf)"); return
        if not out:
            messagebox.showwarning("缺少输出", "请选择输出目录"); return
        # 注意：依赖检查/安装**不在这里**做 —— `ensure_pillow()` 在缺 Pillow 时会跑
        # `pip install pillow`（timeout=180），放在 UI 线程里就是界面冻死最长 3 分钟且
        # 没有任何进度提示（看起来像崩了）。它现在在 work() 里（工作线程）执行。

        game = self.game_var.get()
        off_txt = self.off_var.get()
        offset = int(off_txt[1:]) if off_txt.startswith("+") else 0
        full_cyr = self.cyr_var.get()   # 默认开 = 保留完整西里尔（关掉 = 复刻旧包）
        log_summary(f"开始生成: GAME={game}, 加载语言={lang}, 后缀={suffix!r}, 尺寸=+{offset}, 完整西里尔={full_cyr}", "hdr")

        def work():
            # 依赖检查/安装放在**工作线程**里（见上面注释）：缺 Pillow 时这是最长 180 秒的
            # `pip install`，占着 UI 线程就是"点了没反应"。失败抛出去由 TaskRunner 记录并弹错。
            if not ensure_pillow():
                raise RuntimeError("Pillow 不可用，无法渲染字体"
                                   "（需要能访问 PyPI，或先手工执行 pip install pillow）")
            # 逐条目过程写「详细日志」（只落盘）：GUI 只显示开始/完成/错误
            build_package(game, lang, xml_dir, font, out, suffix=suffix,
                          offset=offset, full_cyrillic=full_cyr, log=log_detail)
            log_detail(f"  生成完成: GAME={game} 语言={lang} 后缀={suffix!r} 尺寸=+{offset} → {out}")
            # 成功收尾必须回主线程（refresh 会建/销毁 Tk 控件）
            self._ui(self._mark_generated)

        # 忙碌态/进度/按钮复位/收尾状态全部由 TaskRunner 在主线程统一处理；
        # 失败只改状态、**不再写 summary**：TaskRunner._wrapper 在 on_error 之后
        # 自己会写一条 `后台任务失败: ...`，这里再写就会出现两行同一异常。
        def _failed(e):
            self.task.set_status("失败", "err")
            # 弹窗给出原因：依赖装不上、字体不合格、磁盘写失败等都在这一步暴露。
            # （日志只由 TaskRunner 写一条 `后台任务失败: ...`，这里不重复写 summary。）
            errbox("生成失败", str(e))

        self.task.run(work, status="生成中...", on_error=_failed,
                      final_status=("完成", "ok"))

    def _mark_generated(self):
        """生成成功（已由 _ui 投递回主线程）：置位结果标志并重算插件动作区。

        has_results 原先是构造时写死的 dict 快照，带 when 的插件命令永远不出现；
        现在 context 是 lambda，refresh() 会重新求值。
        """
        self._has_results = True
        self._slot_bar.refresh()


