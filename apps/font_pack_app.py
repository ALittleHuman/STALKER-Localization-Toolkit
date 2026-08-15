# -*- coding: utf-8 -*-
"""汉化包生成 App (FontPackApp)."""
import os, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from toolkit import T, color, tool_header, dir_row, SplitPane, log_section, _make_pump
from font_pack import GAMES, ensure_pillow, build_package

class FontPackApp:
    def __init__(self, root):
        self.root = root
        if isinstance(root, tk.Tk):
            root.title("汉化包生成")
            root.geometry("860x640")
            root.minsize(760, 560)
        root.configure(bg=color("bg"))

        self.running = False
        self._build_ui()
        self._ui = _make_pump(self.root)
        self._log("就绪。选择汉化 XML 目录后点击生成。", "dim")

    # ─── UI ───
    def _build_ui(self):
        tool_header(self.root, "汉化包生成")
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root); top.pack(fill="x", **pad)

        # 配置行
        row1 = ttk.Frame(top); row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="游戏版本:").pack(side="left")
        self.game_var = tk.StringVar(value="SoC")
        g = ttk.OptionMenu(row1, self.game_var, "SoC", *GAMES.keys())
        g.config(width=6); g.pack(side="left", padx=(4, 16))

        # 加载语言: eng/rus/chs/自定义 (自定义才显示输入框)
        ttk.Label(row1, text="加载语言:").pack(side="left")
        lang_box = ttk.Frame(row1); lang_box.pack(side="left", padx=(4, 16))
        self.lang_sel = tk.StringVar(value="chs")
        self.lang_entry = tk.StringVar(value="chs")
        om = ttk.OptionMenu(lang_box, self.lang_sel, "chs", "eng", "rus", "chs", "自定义",
                            command=self._lang_changed)
        om.config(width=6); om.pack(side="left")
        self.lang_entry_box = tk.Entry(lang_box, textvariable=self.lang_entry, width=6,
                                       bg=T["entry_bg"], fg=color("text"), insertbackground=color("text"),
                                       relief="flat", bd=0, highlightthickness=1,
                                       highlightbackground=color("border"), highlightcolor=color("accent"), font=color("font"))
        self.lang_entry_box.pack_forget()  # 默认隐藏, 切自定义才显示

        # 尺寸
        ttk.Label(row1, text="尺寸:").pack(side="left")
        self.off_var = tk.StringVar(value="标准")
        om = ttk.OptionMenu(row1, self.off_var, "标准", "标准", "+3", "+5", "+7", "+9")
        om.config(width=4); om.pack(side="left", padx=(4, 16))

        # 字体后缀: 无/_chs/自定义 (自定义才显示输入框)
        ttk.Label(row1, text="后缀:").pack(side="left")
        suf_box = ttk.Frame(row1); suf_box.pack(side="left", padx=(4, 16))
        self.suf_sel = tk.StringVar(value="无")
        self.suf_entry = tk.StringVar(value="")
        om = ttk.OptionMenu(suf_box, self.suf_sel, "无", "无", "_chs", "自定义",
                            command=self._suf_changed)
        om.config(width=6); om.pack(side="left")
        self.suf_entry_box = tk.Entry(suf_box, textvariable=self.suf_entry, width=6,
                                      bg=T["entry_bg"], fg=color("text"), insertbackground=color("text"),
                                      relief="flat", bd=0, highlightthickness=1,
                                       highlightbackground=color("border"), highlightcolor=color("accent"), font=color("font"))
        self.suf_entry_box.pack_forget()  # 默认隐藏

        # 路径行 (统一 path_row)
        self.xml_var = tk.StringVar()
        self.font_var = tk.StringVar()
        self.out_var = tk.StringVar()
        dir_row(top, "XML目录:", self.xml_var, browse=self._browse_xml, drop=self._on_drop_xml)
        dir_row(top, "字体文件:", self.font_var, browse=self._browse_font, drop=self._on_drop_font)
        dir_row(top, "输出目录:", self.out_var, browse=self._browse_out, drop=self._on_drop_out)

        # 默认字体: 系统微软雅黑优先, 工具目录 msyh.ttf 后备
        for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf",
                     r"C:\Windows\Fonts\msyhl.ttc"):
            if os.path.exists(cand):
                self.font_var.set(cand); break
        else:
            local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "msyh.ttf")
            if os.path.exists(local):
                self.font_var.set(local)

        # 按钮行
        row3 = ttk.Frame(top); row3.pack(fill="x", pady=(6, 0))
        self.gen_btn = ttk.Button(row3, text="生成汉化包", command=self._generate)
        self.gen_btn.pack(side="left")
        ttk.Button(row3, text="打开输出目录", command=self._open_out).pack(side="left", padx=(8, 0))
        self.status_lbl = tk.Label(row3, text="", bg=color("bg"), fg=color("green"), font=color("font"))
        self.status_lbl.pack(side="right")

        # ═══ 可调分区: 日志区 (分隔条拖拽) ═══
        self._paned = SplitPane(self.root, orient="vertical")
        self._paned.pack(fill="both", expand=True, padx=10, pady=(2, 8))
        lower = ttk.Frame(self._paned)
        self._paned.add(lower, weight=1)
        self.progress = ttk.Progressbar(lower, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(0, 6))
        self.log_lf, self.log = log_section(lower, "日志", height=12)

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

    def _log(self, msg, tag=None):
        self._ui(lambda: self.log.add(msg, tag))

    def _browse_xml(self):
        d = filedialog.askdirectory(title="选择汉化 XML 目录 (xmlfiles)")
        if d: self.xml_var.set(d)

    def _on_drop_xml(self, event):
        """拖拽文件夹到 XML 目录框."""
        path = event.data.strip("{}").strip()
        if os.path.isdir(path):
            self.xml_var.set(path)

    def _on_drop_font(self, event):
        """拖拽字体文件到字体框."""
        path = event.data.strip("{}").strip()
        if os.path.isfile(path) and path.lower().endswith((".ttf", ".ttc", ".otf")):
            self.font_var.set(path)

    def _on_drop_out(self, event):
        """拖拽文件夹到输出目录框."""
        path = event.data.strip("{}").strip()
        if os.path.isdir(path):
            self.out_var.set(path)

    def _browse_font(self):
        """自建字体选择器: 列出 C:\\Windows\\Fonts 全部 ttf/ttc/otf + 当前字体目录."""
        import fnmatch as _fnm
        if not hasattr(self, "_font_cjk"):
            self._font_cjk = {}
        win = tk.Toplevel(self.root)
        win.title("选择字体文件")
        win.geometry("900x520")
        win.configure(bg=color("bg"))
        win.transient(self.root)

        bar = ttk.Frame(win); bar.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(bar, text="过滤:").pack(side="left")
        kw_var = tk.StringVar()
        kw_entry = tk.Entry(bar, textvariable=kw_var, bg=color("entry_bg"), fg=color("text"),
                            insertbackground=color("text"))
        kw_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

        body = SplitPane(win, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10)
        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=3)
        lb = tk.Listbox(list_frame, bg=color("entry_bg"), fg=color("text"),
                        selectbackground=color("selected"), selectforeground=color("text_bright"),
                        font=color("font"), relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=color("border"), highlightcolor=color("accent"))
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 右侧预览区 (可拖拽分隔条调宽度)
        pv = ttk.Frame(body)
        body.add(pv, weight=2)
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
        pv_canvas = tk.Canvas(pv, bg=color("bg"), height=250,
                              highlightthickness=1, highlightbackground=color("border"))
        pv_sb_v = ttk.Scrollbar(pv, orient="vertical", command=pv_canvas.yview)
        pv_sb_h = ttk.Scrollbar(pv, orient="horizontal", command=pv_canvas.xview)
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

        def quick_detect(path):
            """快速中文字形检测: 逐字符取字形包围盒, 多个不同 bbox = 真实字形
            (notdef 缺字形对全部字符渲染同一方块, bbox 全相同). 0.1ms/字体级."""
            try:
                from PIL import ImageFont as _PIF
                font = _PIF.truetype(path, 40)
                boxes = set()
                for ch in "永你好汉化测":
                    try:
                        b = font.getmask(ch).getbbox()
                    except Exception:
                        return False
                    if b is None:
                        continue
                    boxes.add(b)
                return len(boxes) > 1
            except Exception:
                return False

        def detect_all(start=0, batch=24):
            """分片批量检测字体, 完成后整体重填带标记列表 (Listbox 不支持单条改文本)."""
            items = getattr(win, "font_items", [])
            cache = self._font_cjk
            end = min(start + batch, len(items))
            for i in range(start, end):
                path = items[i]
                if path not in cache:
                    cache[path] = quick_detect(path)
            if end < len(items):
                win.after(25, lambda: detect_all(end))
            else:
                # 全部完成: 整体重填带标记 + 恢复选中当前字体
                cur = self.font_var.get().strip()
                lb.delete(0, "end")
                for path in items:
                    mark = "✓ 中文" if cache.get(path) else "⚠"
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
            dirs = [r"C:\Windows\Fonts"]
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
            # 后台分片自动识别中文字形
            win.after_idle(lambda: detect_all(0))
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
            """选中字体时用 PIL 渲染预览文字 (支持缩放), 多字墨迹极差检测中文字形."""
            sel = lb.curselection()
            items = getattr(win, "font_items", [])
            if not sel or not (0 <= sel[0] < len(items)):
                return
            path = items[sel[0]]
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
                # 中文字形检测: 逐字渲染"永你好"墨迹极差, notdef 方块全部相同 (极差≈0)
                ratios = []
                for ch in "永你好":
                    img2 = Image.new("L", (80, 80), 245)
                    d2 = ImageDraw.Draw(img2)
                    d2.text((4, 4), ch, font=font, fill=0)
                    px = img2.load()
                    dark = sum(1 for y in range(80) for x in range(80) if px[x, y] < 200)
                    ratios.append(dark / (80 * 80))
                rng = max(ratios) - min(ratios)
                # 三档: notdef 方块极差严格≈0 (0.000); 真字体极差 >0.008; 细笔手写体介于其间 (不误伤)
                warn = "  ⚠ 可能不含中文字形" if rng <= 0.001 else ""
                pv_name.configure(text=f"{os.path.basename(path)}  [{font.getname()[0]}]{warn}")
            except Exception:
                preview_lbl.configure(image="")
                pv_name.configure(text=f"{os.path.basename(path)}  (预览失败)")

        def pick(_=None):
            sel = lb.curselection()
            if not sel:
                return
            items = getattr(win, "font_items", [])
            if 0 <= sel[0] < len(items):
                self.font_var.set(items[sel[0]])
                win.destroy()

        def browse_other():
            f = filedialog.askopenfilename(title="选择字体文件",
                                           initialdir=os.path.dirname(self.font_var.get())
                                           if self.font_var.get() else r"C:\Windows\Fonts",
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
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa
        else:
            messagebox.showwarning("提示", "输出目录无效")

    def _generate(self):
        if self.running: return
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
        if not ensure_pillow():
            errbox("依赖缺失", "Pillow 安装失败，无法渲染字体"); return

        self.running = True
        self.gen_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_lbl.configure(text="生成中...", foreground=color("yellow"))
        game = self.game_var.get()
        off_txt = self.off_var.get()
        offset = int(off_txt[1:]) if off_txt.startswith("+") else 0
        full_cyr = True  # 默认完整西里尔支持
        self._log(f"开始生成: GAME={game}, 加载语言={lang}, 后缀={suffix!r}, 尺寸=+{offset}, 完整西里尔={full_cyr}", "hdr")

        def work():
            try:
                build_package(game, lang, xml_dir, font, out, suffix=suffix,
                              offset=offset, full_cyrillic=full_cyr, log=self._log)
                self._ui(lambda: self.status_lbl.configure(text="完成", foreground=color("green")))
            except Exception as e:
                self._log(f"错误: {e}", "err")
                self._ui(lambda: self.status_lbl.configure(text="失败", foreground=color("red")))
            self._ui(self._done)

        threading.Thread(target=work, daemon=True).start()

    def _done(self):
        self.running = False
        self.gen_btn.configure(state="normal")
        self.progress.stop()


