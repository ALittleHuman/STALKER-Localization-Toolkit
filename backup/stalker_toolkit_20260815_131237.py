# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 单文件整合版
主题/组件/六个工具 GUI/hub 全部集中于此文件, 杜绝多文件不一致.
运行: python stalker_toolkit.py
"""
import os, sys, re, threading, struct, shutil, subprocess, tempfile, time, json, glob
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Set, Tuple, Union, Any, Callable
import xml.etree.ElementTree as ET

# 引擎库路径注入 (stalker_fs / font_pack 在各自工具子目录)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(_BASE_DIR, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# tkinterdnd2 可选 (拖拽)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BaseTk = TkinterDnD.Tk; _HAS_DND = True
except ImportError:
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "tkinterdnd2"],
                       capture_output=True, timeout=120)
        from tkinterdnd2 import DND_FILES, TkinterDnD
        _BaseTk = TkinterDnD.Tk; _HAS_DND = True
    except ImportError:
        _BaseTk = tk.Tk; _HAS_DND = False; DND_FILES = None

# 引擎库 (各自领域逻辑, 保持独立)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ════════════════════════════════════════════════════════════════
# 1. 主题 (亮/暗两套, 单函数切换)
# ════════════════════════════════════════════════════════════════
THEMES = {
    "dark": {
        "bg": "#1e1e1e", "surface": "#252526", "surface2": "#2d2d2d",
        "border": "#6e7681", "accent": "#007acc", "accent_hover": "#1a8ad4",
        "text": "#cccccc", "text_dim": "#9d9d9d", "text_bright": "#e0e0e0",
        "scroll_border": "#3a3d41", "sash": "#3a3d41", "sash_light": "#4a4d51",
        "green": "#4ec9b0", "red": "#f14c4c", "yellow": "#dcdcaa", "orange": "#ce9178",
        "entry_bg": "#3a3d41", "selected": "#264f78",
    },
    "light": {
        "bg": "#f5f5f5", "surface": "#ececec", "surface2": "#e0e0e0",
        "border": "#909090", "accent": "#0a6cb8", "accent_hover": "#1a7fc9",
        "text": "#3a3a3a", "text_dim": "#6e6e6e", "text_bright": "#2b2b2b",
        "scroll_border": "#c0c0c0", "sash": "#c0c0c0", "sash_light": "#d8d8d8",
        "green": "#2e7d32", "red": "#d64545", "yellow": "#a08000", "orange": "#b06e3c",
        "entry_bg": "#fafafa", "selected": "#d6e7f5",
    },
}
_FONTS = {
    "font": ("Segoe UI", 12), "font_sm": ("Segoe UI", 11),
    "font_mono": ("Consolas", 11),
    "font_title": ("Segoe UI", 14, "bold"),
    "font_header": ("Segoe UI", 12, "bold"),
    "font_stats": ("Segoe UI", 20, "bold"),
}
CURRENT_MODE = "dark"


def palette(mode=None):
    p = dict(THEMES.get(mode or CURRENT_MODE, THEMES["dark"]))
    p.update(_FONTS)
    return p


def _make_pump(root):
    """线程安全 UI 调度器: 工作线程放队列, 主线程轮询执行."""
    import queue as _qq
    _q = _qq.Queue()

    def _ui(fn, *a, **k):
        _q.put((fn, a, k))

    def _pump():
        try:
            while True:
                fn, a, k = _q.get_nowait()
                try:
                    fn(*a, **k)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            root.after(30, _pump)
        except Exception:
            pass

    try:
        root.after(30, _pump)
    except Exception:
        pass
    return _ui


def color(role):
    """UI 配色总入口: border(框)/bg,surface(空白)/entry_bg(填充)/text 系列(字体)/
    green,red,yellow,orange(语义)/accent(强调)/selected(选中)."""
    return palette()[role]


T = palette("dark")


def apply_theme(mode=None):
    """统一主题模板: 亮/暗同一套样式代码."""
    global CURRENT_MODE, T
    if mode:
        CURRENT_MODE = mode
    T = palette()
    # 同步公共组件库主题 (SplitPane / 未来组件)
    try:
        import toolkit as _tk_toolkit
        _tk_toolkit.apply_theme(CURRENT_MODE)
    except Exception:
        pass
    P = T
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background=P["bg"], foreground=P["text"],
                    fieldbackground=P["entry_bg"], borderwidth=0, font=P["font"])
    style.configure("TFrame", background=P["bg"])
    style.configure("Dark.TFrame", background=P["surface"])
    style.configure("TLabelframe", background=P["surface"], foreground=P["text_bright"],
                    bordercolor=P["border"], borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", background=P["surface"],
                    foreground=P["text_bright"], font=P["font_header"])
    style.configure("TLabel", background=P["bg"], foreground=P["text"], font=P["font"])
    style.configure("Dark.TLabel", background=P["surface"], foreground=P["text"], font=P["font"])
    style.configure("Title.TLabel", background=P["bg"], foreground=P["text_bright"],
                    font=P["font_title"])
    style.configure("Dim.TLabel", background=P["bg"], foreground=P["text_dim"], font=P["font_sm"])
    style.configure("Green.TLabel", background=P["bg"], foreground=P["green"], font=P["font_sm"])
    style.configure("Red.TLabel", background=P["bg"], foreground=P["red"], font=P["font_sm"])
    style.configure("Yellow.TLabel", background=P["bg"], foreground=P["yellow"], font=P["font_sm"])
    style.configure("Stats.TLabel", background=P["bg"], foreground=P["accent"],
                    font=P["font_stats"])
    style.configure("TButton", background=P["surface2"], foreground=P["text"],
                    bordercolor=P["border"], relief="flat", padding=(12, 5), font=P["font"])
    style.map("TButton", background=[("active", P["accent"]), ("pressed", P["accent"])],
              foreground=[("active", "#fff"), ("pressed", "#fff")])
    style.configure("Accent.TButton", background=P["accent"], foreground="#fff",
                    font=(P["font"][0], P["font"][1], "bold"))
    style.map("Accent.TButton", background=[("active", P["accent_hover"])])
    style.configure("TEntry", fieldbackground=P["entry_bg"], foreground=P["text"],
                    bordercolor=P["border"], borderwidth=1, relief="solid",
                    padding=(8, 4), font=P["font_mono"])
    style.map("TEntry", fieldbackground=[("focus", P["surface"])],
              bordercolor=[("focus", P["accent"])])
    style.configure("TCombobox", fieldbackground=P["entry_bg"], foreground=P["text"],
                    background=P["surface2"], arrowcolor=P["text"],
                    bordercolor=P["border"], borderwidth=1, relief="solid")
    style.map("TCombobox", fieldbackground=[("readonly", P["entry_bg"])])
    style.configure("TOptionMenu", background=P["surface2"], foreground=P["text"],
                    arrowcolor=P["text"], bordercolor=P["border"], font=P["font"])
    style.configure("TMenubutton", background=P["surface2"], foreground=P["text"],
                    arrowcolor=P["text"], bordercolor=P["border"],
                    relief="flat", padding=(8, 3), font=P["font"])
    style.configure("TProgressbar", background=P["accent"], troughcolor=P["surface2"])
    style.configure("TSeparator", background=P["border"])
    style.configure("TScrollbar", background=P["surface2"], troughcolor=P["surface"],
                    arrowcolor=P["text_dim"], bordercolor=P["scroll_border"],
                    lightcolor=P["scroll_border"], darkcolor=P["scroll_border"])
    # thumb 占满(空列表/不可滚动)时处于 disabled 状态, 需配置该状态颜色, 否则残留 clam 默认浅灰
    style.map("TScrollbar", background=[("disabled", P["surface2"])])
    for _o in ("Vertical", "Horizontal"):
        style.map(f"{_o}.TScrollbar.thumb", background=[("disabled", P["surface2"])])
        style.map(f"{_o}.Scrollbar.thumb", background=[("disabled", P["surface2"])])
    # Panedwindow 分隔条 (sash)
    style.configure("TPanedwindow", background=P["bg"], bordercolor=P["bg"])
    style.configure("Sash", background=P["sash"], lightcolor=P["sash_light"], darkcolor=P["sash"])
    style.configure("TNotebook", background=P["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=P["surface"], foreground=P["text"],
                    padding=(14, 6), font=P["font_sm"])
    style.map("TNotebook.Tab", background=[("selected", P["surface2"])],
              foreground=[("selected", P["text_bright"])])
    style.configure("Treeview", background=P["surface"], foreground=P["text"],
                    fieldbackground=P["surface"], font=P["font_mono"],
                    borderwidth=0, rowheight=24)
    style.configure("Treeview.Heading", background=P["surface2"], foreground=P["text_bright"],
                    font=P["font_header"])
    style.map("Treeview", background=[("selected", P["selected"])],
              foreground=[("selected", P["text_bright"])])


def apply_tk_defaults(root, mode=None):
    """tk 原生控件统一配色 (与 apply_theme 同一色板)."""
    P = palette(mode)
    root.option_add("*Label.background", P["bg"])
    root.option_add("*Label.foreground", P["text"])
    root.option_add("*Label.font", P["font"])
    root.option_add("*Label.relief", "flat")
    root.option_add("*Label.borderWidth", 0)
    root.option_add("*Button.background", P["surface2"])
    root.option_add("*Button.foreground", P["text"])
    root.option_add("*Button.activeBackground", P["accent"])
    root.option_add("*Button.activeForeground", "#ffffff")
    root.option_add("*Button.disabledForeground", P["text_dim"])
    root.option_add("*Button.font", P["font"])
    root.option_add("*Button.relief", "flat")
    root.option_add("*Button.borderWidth", 0)
    root.option_add("*Button.highlightThickness", 0)
    root.option_add("*Button.padX", 12)
    root.option_add("*Button.padY", 4)
    root.option_add("*Button.takeFocus", False)
    root.option_add("*Entry.background", P["entry_bg"])
    root.option_add("*Entry.foreground", P["text"])
    root.option_add("*Entry.insertBackground", P["text"])
    root.option_add("*Entry.relief", "flat")
    root.option_add("*Entry.borderWidth", 0)
    root.option_add("*Entry.highlightThickness", 1)
    root.option_add("*Entry.highlightBackground", P["border"])
    root.option_add("*Entry.highlightColor", P["accent"])
    root.option_add("*Entry.font", P["font_mono"])
    root.option_add("*Checkbutton.background", P["bg"])
    root.option_add("*Checkbutton.foreground", P["text"])
    root.option_add("*Checkbutton.activeBackground", P["bg"])
    root.option_add("*Checkbutton.selectColor", P["surface2"])
    root.option_add("*Checkbutton.font", P["font"])
    root.option_add("*Checkbutton.relief", "flat")
    root.option_add("*Checkbutton.highlightThickness", 0)
    root.option_add("*Menu.background", P["surface2"])
    root.option_add("*Menu.foreground", P["text"])
    root.option_add("*Menu.activeBackground", P["selected"])
    root.option_add("*Menu.activeForeground", P["text_bright"])
    root.option_add("*Menu.font", P["font"])
    root.option_add("*Frame.background", P["bg"])
    root.option_add("*Labelframe.background", P["surface"])
    root.option_add("*Listbox.background", P["surface"])
    root.option_add("*Listbox.foreground", P["text"])
    root.option_add("*Listbox.selectBackground", P["selected"])
    root.option_add("*Text.background", P["surface"])
    root.option_add("*Text.foreground", P["text"])
    root.option_add("*Text.insertBackground", P["text"])
    root.option_add("*Canvas.background", P["surface"])


_BG_ROLES = ("bg", "surface", "surface2", "entry_bg", "selected")


def _role_of(color_val):
    """根据当前颜色值反推角色 (仅背景类, 避免与前景/滚动条色冲突导致切主题错位)."""
    if not color_val:
        return None
    for mode in ("dark", "light"):
        for role in _BG_ROLES:
            if THEMES[mode].get(role) == color_val:
                return role
    return None


def refresh_theme(w):
    """主题切换后递归刷新 tk 原生控件颜色 (不重建, 保留工作区/日志/状态)."""
    try:
        cls = w.winfo_class()
    except Exception:
        return
    try:
        if isinstance(w, LogBox):
            w.recolor()
        elif cls == "Canvas":
            w.configure(bg=T["surface"])
            ctree = getattr(w, "_ctree", None)
            if ctree is not None:
                ctree.recolor()
        elif cls == "Text":
            role = _role_of(str(w.cget("bg")))
            w.configure(bg=T.get(role or "surface", T["surface"]),
                        fg=T["text"], insertbackground=T["text"])
        elif cls == "Label":
            role = _role_of(str(w.cget("bg")))
            w.configure(bg=T.get(role or "bg", T["bg"]), fg=T["text"])
        elif cls == "Button":
            role = _role_of(str(w.cget("bg")))
            w.configure(bg=T.get(role or "surface2", T["surface2"]),
                        fg=T["text"], activebackground=T["accent"],
                        activeforeground="#ffffff", disabledforeground=T["text_dim"])
        elif cls == "Entry":
            w.configure(bg=T["entry_bg"], fg=T["text"], insertbackground=T["text"],
                        disabledbackground=T["entry_bg"], disabledforeground=T["text"],
                        highlightbackground=T["border"], highlightcolor=T["accent"])
        elif cls == "Checkbutton":
            role = _role_of(str(w.cget("bg")))
            w.configure(bg=T.get(role or "bg", T["bg"]), fg=T["text"],
                        activebackground=T.get(role or "bg", T["bg"]),
                        selectcolor=T["surface2"])
        elif cls == "Menubutton":
            w.configure(bg=T["surface2"], fg=T["text"],
                        activebackground=T["selected"], activeforeground=T["text_bright"])
        elif cls == "Menu":
            w.configure(bg=T["surface2"], fg=T["text"], activebackground=T["selected"],
                        activeforeground=T["text_bright"])
        elif cls in ("Frame", "Labelframe", "Toplevel"):
            role = _role_of(str(w.cget("bg")))
            w.configure(bg=T.get(role or "bg", T["bg"]))
    except Exception:
        pass
    for c in w.winfo_children():
        refresh_theme(c)


# ════════════════════════════════════════════════════════════════
# 2. 公共组件
# ════════════════════════════════════════════════════════════════
def fmt_size(sz):
    if sz >= 1048576:
        return f"{sz / 1048576:.1f} MB"
    if sz >= 1024:
        return f"{sz / 1024:.1f} KB"
    return f"{sz} B"


DEFAULT_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "cp1251", "cp1252", "latin-1"]


def read_text_file(path, encodings=None):
    encs = encodings or DEFAULT_ENCODINGS
    for i, enc in enumerate(encs):
        try:
            with open(path, "r", encoding=enc,
                      errors="ignore" if i == len(encs) - 1 else "strict") as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码: {path}")


def parse_xml_texts(text):
    try:
        import xml.etree.ElementTree as ET
        return list(ET.fromstring(text).itertext())
    except Exception:
        strip = re.compile(r"<[^>]+>")
        out = []
        for m in re.finditer(r"<text[^>]*>(.*?)</text>", text, re.S):
            out.append(strip.sub("", m.group(1)))
        for m in re.finditer(r"<string[^>]*>(.*?)</string>", text, re.S):
            out.append(strip.sub("", m.group(1)))
        return out


class LogBox(tk.Text):
    _BASE_TAGS = [("info", "text"), ("ok", "green"), ("err", "red"),
                  ("warn", "yellow"), ("dim", "text_dim"), ("hdr", "orange")]

    def __init__(self, parent, height=4, wrap="word", timestamp=False,
                 scrollbar=True, tags=None):
        super().__init__(parent, bg=T["surface"], fg=T["text"],
                         insertbackground=T["text"], font=T["font_mono"],
                         relief="flat", borderwidth=0, wrap=wrap,
                         state="disabled", height=height)
        self._timestamp = timestamp
        self._tag_roles = self._BASE_TAGS + (tags or [])
        self.recolor()
        if scrollbar:
            sb = ttk.Scrollbar(parent, orient="vertical", command=self.yview)
            self.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.pack(side="left", fill="both", expand=True)

    def recolor(self):
        """主题切换后刷新自身与 tag 颜色 (不重建 widget, 保留日志)."""
        self.configure(bg=T["surface"], fg=T["text"], insertbackground=T["text"])
        for tag, role in self._tag_roles:
            self.tag_configure(tag, foreground=T.get(role, role))

    def add(self, msg, tag=None):
        """追加日志 (批量刷新: 高频时攒批, 定时 flush, 减少 see/insert 调用)."""
        if tag is None:
            tag = "info"
        if self._timestamp:
            msg = f"[{time.strftime('%H:%M:%S')}] {msg}"
        pending = getattr(self, "_pending", None)
        if pending is None:
            pending = self._pending = []
            try:
                self.after(80, self._flush)
            except Exception:
                pass
        pending.append((msg, tag))
        if len(pending) >= 500:
            self._flush()

    def _flush(self):
        """批量写入待发日志, 一次 see, 限制最大行数."""
        pending = getattr(self, "_pending", None)
        self._pending = None
        if not pending:
            return
        self.configure(state="normal")
        for msg, tag in pending:
            self.insert("end", msg + "\n", tag)
        self.configure(state="disabled")
        # 限制行数 (防无限增长拖慢渲染)
        try:
            n = int(self.index("end-1c").split(".")[0])
            if n > 5000:
                self.delete("1.0", f"{n - 3000}.0")
        except Exception:
            pass
        self.see("end")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


def log_section(parent, title="日志", height=6, clear=True):
    lf = ttk.LabelFrame(parent, text=title, padding=4)
    lf.pack(fill="both", expand=True)
    btn = None
    if clear:
        btn = ttk.Button(lf, text="清空", width=5)
        btn.pack(side="right", anchor="n")
    log = LogBox(lf, height=height, wrap="word")
    log._log_role = True  # 标记: 真正的日志框 (hub 集成时隐藏, 结果展示区不隐藏)
    if btn is not None:
        btn.configure(command=log.clear)
    return lf, log


def dir_row(parent, label, var, browse=None, drop=None, add=None, width=8, state=None):
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 4))
    if label:
        ttk.Label(row, text=label, width=width).pack(side="left")
    e = tk.Entry(row, textvariable=var, bg=color("entry_bg"), fg=color("text"),
                 insertbackground=color("text"), relief="flat", bd=0,
                 disabledbackground=color("entry_bg"), disabledforeground=color("text"),
                 highlightthickness=1, highlightbackground=color("border"),
                 highlightcolor=color("accent"), font=T["font_mono"])
    if state:
        e.configure(state=state)
    e.pack(side="left", fill="x", expand=True, ipady=3)
    if drop is not None:
        try:
            if hasattr(e, "drop_target_register"):
                e.drop_target_register("DND_Files")
                e.dnd_bind("<<Drop>>", drop)
        except Exception:
            pass
    if browse:
        ttk.Button(row, text="浏览", width=6, command=browse).pack(side="left", padx=(6, 0))
    if add:
        ttk.Button(row, text=add[0], width=6, command=add[1]).pack(side="left", padx=(4, 0))
    return row, e


def count_label(parent, side="right"):
    lbl = ttk.Label(parent, text="", font=T["font_sm"], foreground=color("text_dim"))
    lbl.pack(side=side)
    return lbl

def tool_header(parent, text, **pack_kw):
    """统一工具页标题: 所有子工具同一样式, 仅文本不同."""
    kw = {"anchor": "w", "padx": 14, "pady": (14, 2)}
    kw.update(pack_kw)
    ttk.Label(parent, text=text, style="Title.TLabel").pack(**kw)
def tool_text(parent, text, kind="body", **pack_kw):
    """统一文本组件: 大标题 / 小标题 / 说明 / 正文 / 统计 / 语义文本."""
    kind_styles = {
        "title": "Title.TLabel",
        "subtitle": "Dim.TLabel",
        "body": "TLabel",
        "dim": "Dim.TLabel",
        "mono": "TLabel",
        "stat": "Stats.TLabel",
        "success": "Green.TLabel",
        "error": "Red.TLabel",
        "warn": "Yellow.TLabel",
    }
    style = kind_styles.get(kind, "TLabel")
    font = color("font_mono") if kind == "mono" else None
    kw = {"anchor": "w"}
    kw.update(pack_kw)
    lbl = ttk.Label(parent, text=text, style=style)
    if font:
        lbl.configure(font=font)
    lbl.pack(**kw)
    return lbl

def vscrollbar(parent, target):
    sb = ttk.Scrollbar(parent, orient="vertical", command=target.yview)
    target.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    return sb


def drop_zone(parent, title, placeholder, on_file=None):
    lf = ttk.LabelFrame(parent, text=title, padding=6)
    lf.pack(side="left", fill="both", expand=True, padx=(0, 6))
    lbl = tk.Label(lf, text=placeholder, anchor="center",
                   font=T["font"], bg=color("entry_bg"), fg=color("text_dim"),
                   relief="flat", bd=0,
                   highlightthickness=1, highlightbackground=color("border"),
                   highlightcolor=color("accent"))
    lbl.pack(fill="both", expand=True, ipady=6)

    def _click(e):
        path = filedialog.askopenfilename(title="选择文件")
        if path and on_file:
            on_file(path)

    def _drop(e):
        if on_file is not None and hasattr(e, "data"):
            path = str(e.data).strip("{}").strip()
            if path and os.path.isfile(path):
                on_file(path)
    lbl.bind("<Button-1>", _click)
    try:
        if hasattr(lbl, "drop_target_register"):
            lbl.drop_target_register("DND_Files")
            lbl.dnd_bind("<<Drop>>", _drop)
    except Exception:
        pass

    def show_file(path):
        lbl.configure(text=os.path.basename(path) if path else placeholder)
    lbl.show_file = show_file
    return lbl


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


class CanvasTree:
    """自绘文件树 (通用, 无 app 依赖)."""
    ROW_H = 24
    INDENT = 24
    CHK = 16
    CHK_PAD = 6

    def __init__(self, master, with_chk=True, on_toggle=None, on_click=None,
                 chk_state=None, row_status=None, fmt_size=None, on_change=None):
        self.with_chk = with_chk
        self.on_toggle = on_toggle
        self.on_click = on_click
        self.chk_state = chk_state
        self.row_status = row_status
        self.fmt_size = fmt_size or fmt_size
        self.on_change = on_change
        import tkinter.font as _tkf
        self._mfont = _tkf.Font(font=T["font_mono"])
        self.frame = ttk.Frame(master)
        self.canvas = tk.Canvas(self.frame, bg=T["surface"], highlightthickness=0,
                                height=300, bd=0)
        self.canvas._ctree = self  # 主题切换遍历时定位到本 wrapper
        self.vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._yscrollcmd)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        self.rows = []
        self._sel = set()
        self._expanded = set()
        self.root = None; self.q = ""
        self._press = None; self._drag = False
        self._ctx = tk.Menu(self.frame, tearoff=0, bg=T["surface2"], fg=T["text"], font=T["font"])
        self._ctx.add_command(label="选中打勾", command=lambda: self._ctx_set(True))
        self._ctx.add_command(label="取消打勾", command=lambda: self._ctx_set(False))
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_rclick)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", lambda e: self._draw())

    def get(self):
        return self.frame

    def recolor(self):
        """主题切换后刷新颜色并重绘 (不重建)."""
        self.canvas.configure(bg=T["surface"])
        try:
            self._ctx.configure(bg=T["surface2"], fg=T["text"])
        except Exception:
            pass
        self._draw()

    def set_root(self, root, q=""):
        self.root = root; self.q = q; self._expanded = set()
        self.populate()

    def populate(self):
        self.rows = []
        if self.root:
            self._collect(self.root, "", self.q, 0)
        self.canvas.configure(scrollregion=(0, 0, 0, max(len(self.rows) * self.ROW_H, 1)))
        self._draw()

    def _collect(self, node, parent_id, q, level):
        if node.path:
            if q:
                if q in node.path.lower():
                    self.rows.append((node, level, parent_id))
                elif not node.is_dir:
                    return
            else:
                self.rows.append((node, level, parent_id))
        kids = sorted(node.children.values(), key=lambda c: (not c.is_dir, c.name.lower()))
        if node.is_dir and node.path and not q and node not in self._expanded:
            return
        for c in kids:
            self._collect(c, node.path, q, level + 1)
        if node.is_dir and node.path and not q and not node.children and node in self._expanded:
            self.rows.append((None, level + 1, node.path))

    def file_count(self):
        if self.q:
            return sum(1 for n, _, _ in self.rows if n is not None and not n.is_dir)
        cnt = 0

        def walk(n):
            nonlocal cnt
            if not n.is_dir:
                cnt += 1
            for c in n.children.values():
                walk(c)
        if self.root:
            walk(self.root)
        return cnt

    def _chk_rect(self, row_idx):
        node, level, _ = self.rows[row_idx]
        if node is None or not self.with_chk:
            return None
        y = row_idx * self.ROW_H
        x = self.CHK_PAD + self.INDENT * level
        return (x, y + (self.ROW_H - self.CHK) // 2, x + self.CHK,
                y + (self.ROW_H - self.CHK) // 2 + self.CHK)

    def _yscrollcmd(self, *args):
        """滚动条更新时同步重绘可见行 (滚动后新行进入视口)."""
        self.vbar.set(*args)
        self._draw()

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 800
        rows = self.rows
        total = len(rows)
        if not total:
            return
        # 只渲染可见行 (视口附近), 大幅减少 create 调用
        y_top = c.canvasy(0)
        h = c.winfo_height() or 600
        start = max(0, int(y_top // self.ROW_H) - 1)
        end = min(total, int((y_top + h) // self.ROW_H) + 2)
        for i in range(start, end):
            node, level, _ = rows[i]
            y = i * self.ROW_H
            if node is not None and node in self._sel:
                c.create_rectangle(0, y, w, y + self.ROW_H, fill=T["selected"], outline="")
            if node is None:
                c.create_text(self.INDENT * level + 22, y + 12, text="(空)",
                              anchor="w", fill=T["text_dim"], font=T["font_mono"])
                continue
            x = self.CHK_PAD + self.INDENT * level
            if node.is_dir:
                self._draw_arrow(c, x - 12, y + 12, node in self._expanded)
            if self.with_chk:
                self._draw_chk(c, x, y + (self.ROW_H - self.CHK) // 2, node)
            tx = x + (self.CHK + 6 if self.with_chk else 2)
            c.create_text(tx, y + 12, text=node.name, anchor="w",
                          fill=T["text_bright"] if node in self._sel else T["text"],
                          font=T["font_mono"])
            if self.row_status is not None:
                stxt = self.row_status(node)
                if stxt:
                    text, color_ = stxt
                    c.create_text(tx + self._mfont.measure(node.name) + 10, y + 12,
                                  text=text, anchor="w", fill=color_, font=T["font_sm"])
            if not node.is_dir:
                c.create_text(w - 8, y + 12, text=self.fmt_size(node.size),
                              anchor="e", fill=T["text_dim"], font=T["font_mono"])

    def _draw_chk(self, c, x, y, node):
        c.create_rectangle(x, y, x + self.CHK, y + self.CHK, outline="#c8c8c8", width=1)
        if self.chk_state is not None:
            st = self.chk_state(node)
        else:
            st = node.dir_state() if node.is_dir else (True if node.checked else None)
        if st is True:
            c.create_line(x + 3, y + 8, x + 6, y + 11, x + self.CHK - 3, y + 4,
                          fill="#e0e0e0", width=2)
        elif st is False:
            c.create_line(x + 3, y + 8, x + self.CHK - 3, y + 8, fill="#e0e0e0", width=2)

    def _draw_arrow(self, c, ax, ay, expanded):
        if expanded:
            c.create_polygon(ax, ay - 4, ax + 8, ay - 4, ax + 4, ay + 4,
                             fill=T["text_dim"], outline="")
        else:
            c.create_polygon(ax, ay - 4, ax + 8, ay, ax, ay + 4, ax, ay - 4,
                             fill=T["text_dim"], outline="")

    def _hit_row(self, x, y):
        cy = self.canvas.canvasy(y)
        idx = int(cy // self.ROW_H)
        return idx if 0 <= idx < len(self.rows) else None

    def _hit_chk(self, x, y):
        cx = self.canvas.canvasx(x)
        cy = self.canvas.canvasy(y)
        idx = int(cy // self.ROW_H)
        if idx is not None:
            r = self._chk_rect(idx)
            if r and r[0] <= cx <= r[2] and r[1] <= cy <= r[3]:
                return idx
        return None

    def _on_press(self, e):
        self._press = (e.x, e.y); self._drag = False

    def _on_motion(self, e):
        if self._press is None:
            return
        if abs(e.y - self._press[1]) > 5:
            self._drag = True
            cy1 = self.canvas.canvasy(min(self._press[1], e.y))
            cy2 = self.canvas.canvasy(max(self._press[1], e.y))
            self._sel = set()
            for idx in range(int(cy1 // self.ROW_H), int(cy2 // self.ROW_H) + 1):
                if 0 <= idx < len(self.rows) and self.rows[idx][0] is not None:
                    self._sel.add(self.rows[idx][0])
            self._draw()

    def _on_release(self, e):
        if self._drag:
            self._press = None; self._drag = False; return
        idx = self._hit_row(e.x, e.y)
        self._press = None
        if idx is None:
            return
        node, _, _ = self.rows[idx]
        if node is None:
            return
        st = e.state
        if st & 0x4:
            if node in self._sel:
                self._sel.discard(node)
            else:
                self._sel.add(node)
        else:
            self._sel = {node}
        if self.with_chk and self._hit_chk(e.x, e.y) == idx:
            if self.on_toggle is not None:
                self.on_toggle(node)
            elif node.is_dir:
                st2 = node.dir_state(); node.toggle(st2 is not True)
            else:
                node.checked = not node.checked
            self._notify_change()
            self._draw()
            return
        if self.on_click is not None:
            self.on_click(node)
            self._draw()
            return
        if node.is_dir:
            self._toggle_expand(node)
            return
        if self.with_chk:
            node.checked = not node.checked
            self._notify_change()
        self._draw()

    def _notify_change(self):
        if self.on_change is not None:
            self.on_change()

    def _toggle_expand(self, node):
        if node in self._expanded:
            self._expanded.discard(node)
        else:
            self._expanded.add(node)
        self.populate()

    def _on_rclick(self, e):
        idx = self._hit_row(e.x, e.y)
        if idx is not None and self.rows[idx][0] is not None:
            node = self.rows[idx][0]
            if node not in self._sel:
                self._sel = {node}; self._draw()
        self._ctx.post(e.x_root, e.y_root)

    def _ctx_set(self, checked):
        for node in self._sel:
            node.toggle(checked)
        self._notify_change()
        self._draw()

    def _on_wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        self._draw()
        return "break"

    def get_selected_paths(self):
        return [n.path for n in self._sel if n.path]

    def select_all(self):
        self._sel = {n for n, _, _ in self.rows if n is not None}
        self._draw()


# 占位: 工具 GUI 将在此插入
# (每个工具 = 一个类, master 参数化, 内部逻辑从原文件迁移)

# ═══ 编码转换 ═══
def install_package(package):
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        return True
    except:
        return False

required = {"chardet": "chardet", "tkinterdnd2": "tkinterdnd2"}
for imp, pkg in required.items():
    try:
        __import__(imp)
    except ImportError:
        install_package(pkg)

# ====================== 导入库（带回退） ======================
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import chardet
    def _detect_encoding(raw):
        return chardet.detect(raw)
except ImportError:
    def _detect_encoding(raw):
        for enc in ["utf-8", "cp1251", "cp1252", "gbk"]:
            try:
                raw.decode(enc)
                return {"encoding": enc, "confidence": 0.8}
            except:
                continue
        return {"encoding": "utf-8", "confidence": 0.5}


# ====================== 主程序 ======================
class ConvertApp(ttk.Frame):
    def __init__(self, master=None):
        self.root = master or _BaseTk()
        super().__init__(self.root)
        self.pack(fill="both", expand=True)  # 铺满宿主 (tab/独立窗口)
        # 统一主题 (toolkit 单一来源)
        apply_theme()
        apply_tk_defaults(self.root)
        if master is None:
            self.root.title("编码转换工具")
            self.root.geometry("950x880")
            self.root.resizable(True, True)

        # 原有变量
        self.source_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.file_exts = tk.StringVar(value=".xml")
        self.target_enc = tk.StringVar(value="utf-8")
        self.source_enc = tk.StringVar(value="auto")
        self.recursive = tk.BooleanVar(value=True)
        self.backup_files = tk.BooleanVar(value=True)

        # 新增变量
        self.auto_verify = tk.BooleanVar(value=True)
        self.exclude_pattern = tk.StringVar()

        # 进度控制
        self.total = 0
        self.current = 0
        self.paused = False
        self.cancelled = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        import queue as _q
        self._ui_q = _q.Queue()
        try:
            self.root.after(30, self._ui_pump)
        except Exception:
            pass

        # 统计信息
        self.convert_stats = {
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'verified_ok': 0,
            'verified_fail': 0,
            'start_time': None,
            'end_time': None
        }

        # 标记当前是文件还是文件夹模式
        self.is_single_file = False

        self.output_dir.trace_add("write", self.on_output_dir_change)
        self.recursive.trace_add("write", self.on_recursive_change)
        self.init_ui()

    def init_ui(self):
        """界面 (统一组件: dir_row/log_section/color 模板)."""
        PAD = 14
        # ═══ 标题 ═══
        tool_header(self, "编码转换工具")
        # ═══ 可调分区: 上部设置区 / 下部日志区 (分隔条拖拽) ═══
        self._paned = SplitPane(self, orient="vertical")
        self._paned.pack(fill="both", expand=True, padx=PAD, pady=(2, 8))
        upper = ttk.Frame(self._paned)
        lower = ttk.Frame(self._paned)
        self._paned.add(upper, weight=3)
        self._paned.add(lower, weight=1)


        # ═══ 源目录 ═══
        source_frame = ttk.LabelFrame(upper, text="源文件夹 / 单个文件")
        source_frame.pack(fill="x", padx=PAD, pady=6)
        _, self.source_entry = dir_row(source_frame, "源", self.source_dir,
                                       browse=self.select_source,
                                       add=("清除", self.clear_source))

        # ═══ 输出目录 ═══
        out_frame = ttk.LabelFrame(upper, text="输出文件夹")
        out_frame.pack(fill="x", padx=PAD, pady=6)
        _, self.out_entry = dir_row(out_frame, "输出", self.output_dir,
                                    browse=self.select_output,
                                    add=("清除", self.clear_output))

        # ═══ 转换设置 ═══
        set_frame = ttk.LabelFrame(upper, text="转换设置")
        set_frame.pack(fill="x", padx=PAD, pady=6)
        set_frame.columnconfigure(5, weight=1)
        # 行0: 源/目标编码
        ttk.Label(set_frame, text="源编码：").grid(row=0, column=0, padx=(10, 4), pady=8, sticky="e")
        self.source_enc_combo = ttk.Combobox(set_frame, textvariable=self.source_enc,
            values=["auto", "utf-8", "gbk", "gb2312", "big5", "shift_jis", "euc-kr",
                    "windows-1251", "windows-1252", "iso-8859-1", "ascii", "utf-16"],
            width=14, state="readonly")
        self.source_enc_combo.grid(row=0, column=1, padx=(0, 6), sticky="w")
        ttk.Label(set_frame, text="自动检测可能不准确", style="Dim.TLabel").grid(row=0, column=2, padx=(0, 14), sticky="w")
        ttk.Label(set_frame, text="目标编码：").grid(row=0, column=3, padx=(12, 4), pady=8, sticky="e")
        ttk.Combobox(set_frame, textvariable=self.target_enc,
            values=["utf-8", "gbk", "gb2312", "windows-1251", "ascii", "utf-16", "big5"],
            width=14).grid(row=0, column=4, padx=(0, 10), sticky="w")
        # 行1: 扩展名 + 选项
        ttk.Label(set_frame, text="扩展名：").grid(row=1, column=0, padx=(10, 4), pady=8, sticky="e")
        ttk.Entry(set_frame, textvariable=self.file_exts, width=18).grid(row=1, column=1, padx=(0, 6), sticky="w")
        self.recursive_check = tk.Checkbutton(set_frame, text="递归子目录", variable=self.recursive)
        self.recursive_check.grid(row=1, column=2, padx=8, sticky="w")
        self.backup_check = tk.Checkbutton(set_frame, text="备份为.bak", variable=self.backup_files)
        self.backup_check.grid(row=1, column=3, padx=8, sticky="w")
        tk.Checkbutton(set_frame, text="自动校验", variable=self.auto_verify).grid(row=1, column=4, padx=8, sticky="w")
        # 行2: 排除模式
        ttk.Label(set_frame, text="排除模式：").grid(row=2, column=0, padx=(10, 4), pady=(0, 10), sticky="e")
        ttk.Entry(set_frame, textvariable=self.exclude_pattern, width=28).grid(row=2, column=1, columnspan=2, padx=(0, 6), sticky="w")
        ttk.Label(set_frame, text="通配符逗号分隔, 如 *backup*,temp*", style="Dim.TLabel").grid(row=2, column=3, columnspan=2, padx=8, sticky="w")

        # ═══ 操作按钮 ═══
        btn_frame = ttk.Frame(upper)
        btn_frame.pack(pady=(8, 2))
        self.start_btn = ttk.Button(btn_frame, text="开始转换", command=self.start_thread, width=14)
        self.start_btn.pack(side="left", padx=4)
        self.pause_btn = ttk.Button(btn_frame, text="暂停", command=self.toggle_pause, width=8, state="disabled")
        self.pause_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(btn_frame, text="取消", command=self.cancel_convert, width=8, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(btn_frame, text="恢复备份", command=self.start_restore_thread, width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="清空备份", command=self.start_clear_backup_thread, width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="打开输出", command=self.open_out_dir, width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="导出", command=self.export_stats, width=8).pack(side="left", padx=4)

        # ═══ 转换进度 (在下区, 日志上方) ═══
        prog_frame = ttk.LabelFrame(lower, text="转换进度")
        prog_frame.pack(fill="x", padx=PAD, pady=6)
        self.prog_var = tk.DoubleVar()
        self.prog_bar = ttk.Progressbar(prog_frame, variable=self.prog_var, maximum=100)
        self.prog_bar.pack(fill="x", padx=10, pady=(8, 2))
        self.prog_label = ttk.Label(prog_frame, text="0 / 0 文件", style="Dim.TLabel")
        self.prog_label.pack(pady=(0, 6))

        # ═══ 日志 (统一 log_section, hub 集成时隐藏) ═══
        self.log_lf, self.log_box = log_section(lower, "运行日志", height=10, clear=False)
        self.log_box._timestamp = True

        # ═══ 拖拽 (dir_row 已注册, 绑定处理) ═══
        try:
            if hasattr(self.source_entry, "drop_target_register"):
                self.source_entry.drop_target_register(DND_FILES)
                self.source_entry.dnd_bind("<<Drop>>", self.on_drop_source)
                self.out_entry.drop_target_register(DND_FILES)
                self.out_entry.dnd_bind("<<Drop>>", self.on_drop_output)
        except Exception:
            pass

    # ====================== 更新模式 ======================
    def update_mode_label(self):
        """根据当前模式更新递归复选框状态"""
        if self.is_single_file:
            # 单文件模式：禁用递归
            self.recursive.set(False)
            self.recursive_check.config(state=tk.DISABLED)
        else:
            # 文件夹模式：启用递归
            self.recursive_check.config(state=tk.NORMAL)

    def on_recursive_change(self, *args):
        """递归选项改变时更新标签"""
        if not self.is_single_file:
            self.update_mode_label()

    # ====================== 智能拖拽 ======================
    def on_drop_source(self, event):
        """智能拖拽：自动识别文件夹或文件"""
        path = event.data
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]
        
        if os.path.isdir(path):
            self.source_dir.set(path)
            self.is_single_file = False
            self.update_mode_label()
            self.log(f"已拖拽源目录：{path}")
        elif os.path.isfile(path):
            self.source_dir.set(path)
            self.is_single_file = True
            self.update_mode_label()
            self.log(f"已拖拽单个文件：{os.path.basename(path)}")
        else:
            self.log(f"无效路径：{path}")

    def on_drop_output(self, event):
        """拖拽输出目录"""
        path = event.data
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]
        if os.path.isdir(path):
            self.output_dir.set(path)
            self.log(f"已拖拽输出目录：{path}")

    # ------------------------------ 基础功能 ------------------------------
    def select_source(self):
        """合并的选择按钮：弹出菜单选择文件夹或文件"""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="选择文件夹", command=self._select_folder)
        menu.add_command(label="选择文件", command=self._select_file)
        
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _select_folder(self):
        """选择文件夹"""
        p = filedialog.askdirectory()
        if p:
            self.source_dir.set(p)
            self.is_single_file = False
            self.update_mode_label()
            self.log(f"已选择源目录：{p}")

    def _select_file(self):
        """选择单个文件"""
        exts = self.file_exts.get().replace(',', ' ').strip()
        if exts:
            filetypes = [("目标文件", exts), ("所有文件", "*.*")]
        else:
            filetypes = [("所有文件", "*.*")]
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            self.source_dir.set(p)
            self.is_single_file = True
            self.update_mode_label()
            self.log(f"已选择单个文件：{os.path.basename(p)}")

    def clear_source(self):
        """清除源文件/文件夹选择"""
        if self.source_dir.get():
            self.source_dir.set("")
            self.is_single_file = False
            self.recursive_check.config(state=tk.NORMAL)
            self.log("已清除源文件/文件夹选择")

    def select_output(self):
        p = filedialog.askdirectory()
        if p:
            self.output_dir.set(p)

    def clear_output(self):
        """清除输出文件夹选择"""
        if self.output_dir.get():
            self.output_dir.set("")
            self.log("已清除输出文件夹选择")

    def _ui(self, fn, *args, **kwargs):
        """从工作线程安全调度 UI 调用到主线程 (queue 队列, 主线程轮询泵)."""
        self._ui_q.put((fn, args, kwargs))

    def _ui_pump(self):
        """主线程轮询泵: 每 30ms 处理 UI 队列."""
        try:
            while True:
                fn, a, k = self._ui_q.get_nowait()
                try:
                    fn(*a, **k)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.after(30, self._ui_pump)
        except Exception:
            pass

    def _ensure_snap(self):
        """确保快照存在 (主线程直接调 get_files 等时刷新为最新值)."""
        if threading.current_thread() is threading.main_thread() or not getattr(self, "_snap", None):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'auto_verify': self.auto_verify.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }

    def log(self, msg):
        self._ui(self.log_box.add, msg)
    def clear_log(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete(1.0, tk.END)
        self.log_box.config(state=tk.DISABLED)

    def open_out_dir(self):
        d = self.output_dir.get() or (self.source_dir.get() if not self.is_single_file else os.path.dirname(self.source_dir.get()))
        if os.path.isdir(d):
            os.startfile(d)
        else:
            self._ui(messagebox.showwarning, "提示", "目录不存在")

    # ------------------------------ 智能备份 ------------------------------
    def on_output_dir_change(self, *args):
        if self.output_dir.get():
            self.backup_files.set(False)
            self.backup_check.config(state=tk.DISABLED)
        else:
            self.backup_check.config(state=tk.NORMAL)

    # ------------------------------ 排除模式匹配 ------------------------------
    def is_excluded(self, filepath):
        self._ensure_snap()

        pattern_str = self._snap['exclude_pattern'].strip()
        if not pattern_str:
            return False

        patterns = [p.strip() for p in pattern_str.split(',') if p.strip()]
        
        if not self.is_single_file and os.path.isdir(self._snap['source_dir']):
            src = self._snap['source_dir']
            try:
                if os.path.commonpath([filepath, src]) == src:
                    rel_path = os.path.relpath(filepath, src)
                else:
                    rel_path = filepath
            except ValueError:
                rel_path = filepath
        else:
            rel_path = filepath

        import fnmatch
        for pattern in patterns:
            if fnmatch.fnmatch(os.path.basename(filepath), pattern):
                return True
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if pattern.replace('*', '') in rel_path:
                return True

        return False

    # ------------------------------ 暂停/取消控制 ------------------------------
    def toggle_pause(self):
        """切换暂停状态"""
        if self.paused:
            self.paused = False
            self.pause_event.set()
            self._ui(self.pause_btn.config, text="暂停")
            self.log("===== 继续转换 =====")
        else:
            self.paused = True
            self.pause_event.clear()
            self._ui(self.pause_btn.config, text="继续")
            self.log("===== 暂停转换 =====")

    def cancel_convert(self):
        """取消转换"""
        if messagebox.askyesno("确认", "确定要取消当前转换任务吗？"):
            self.cancelled = True
            self.paused = False
            self.pause_event.set()
            self._ui(self.cancel_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, state=tk.DISABLED)
            self.log("===== 用户取消转换 =====")

    # ------------------------------ 自动校验 ------------------------------
    def verify_file(self, original_path, converted_path):
        """校验转换后的文件完整性"""
        try:
            if not os.path.exists(converted_path):
                return False, "文件不存在"

            orig_size = os.path.getsize(original_path)
            conv_size = os.path.getsize(converted_path)
            
            if orig_size == 0:
                if conv_size > 10:
                    return False, f"空文件转换后大小异常({conv_size}字节)"
                return True, "通过"

            target_enc = self._snap['target_enc'].lower()
            with open(converted_path, 'rb') as f:
                conv_raw = f.read()

            # 解码前剥离 BOM 字节 (输出带 BOM 也能正常校验, BOM 归入声明归一化比较)
            if conv_raw[:3] == b"\xef\xbb\xbf":
                conv_raw = conv_raw[3:]
            elif conv_raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                conv_raw = conv_raw[2:]

            try:
                conv_content = conv_raw.decode(target_enc)
            except:
                return False, f"无法用目标编码({target_enc})解码"

            with open(original_path, 'rb') as f:
                orig_raw = f.read()
            # 字节级剥离 BOM (与 convert_file 一致)
            if orig_raw[:3] == b"\xef\xbb\xbf":
                orig_raw = orig_raw[3:]
            elif orig_raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                orig_raw = orig_raw[2:]

            src_enc = self._get_source_encoding(orig_raw)

            try:
                orig_content = orig_raw.decode(src_enc, errors='replace')
            except:
                orig_content = orig_raw.decode("windows-1251", errors='replace')
            # 源 BOM 剥离 (与 convert_file 一致, 转换输出不带 BOM)
            if orig_content.startswith("\ufeff"):
                orig_content = orig_content[1:]
            if conv_content.startswith("\ufeff"):
                conv_content = conv_content[1:]  # 兼容: 转换侧已剥离, 此处双保险

            # XML 校验两条路:
            #  1) 无声明: 字符级严格相等
            #  2) 有声明: 声明除 encoding 外完全一致 + 转换后不带 BOM + 正文严格相等
            def _split_xml_decl(s):
                m = re.match(r"^\s*<\?xml[^>]*\?>", s, re.S)
                return (s[m.start():m.end()], s[m.end():]) if m else (None, s)

            orig_decl, orig_body = _split_xml_decl(orig_content)
            conv_decl, conv_body = _split_xml_decl(conv_content)

            if orig_decl is None:
                # 路 1: 无声明, 字符级严格相等
                if orig_content != conv_content:
                    return False, "内容不一致(无XML声明须完全一致)"
            else:
                # 路 2: 有声明
                if conv_decl is None:
                    return False, "XML声明缺失"
                # 声明归一化: BOM + 引号 + encoding 值一起归并比较
                def _norm_decl(decl):
                    d = decl.lstrip("\ufeff")
                    d = d.replace("'", '"')
                    d = re.sub(r'encoding\s*=\s*"[^"]*"', '', d, flags=re.I)
                    return d.strip()
                if _norm_decl(orig_decl) != _norm_decl(conv_decl):
                    return False, "XML声明不一致(除编码/引号/BOM外)"
                # 正文: 字符级严格相等
                if orig_body != conv_body:
                    return False, "内容不一致"

            return True, "通过"

        except Exception as e:
            return False, f"校验异常: {str(e)}"

    # ------------------------------ 日志导出 ------------------------------
    def export_log(self):
        """导出运行日志"""
        try:
            default_name = f"转换日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                initialfile=default_name
            )
            if filepath:
                log_content = self.log_box.get(1.0, tk.END)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                self.log(f"日志已导出到：{filepath}")
                self._ui(messagebox.showinfo, "成功", f"日志已保存到：\n{filepath}")
        except Exception as e:
            self._ui(messagebox.showerror, "错误", f"导出失败：{str(e)}")

    def export_stats(self):
        """导出统计信息"""
        try:
            default_name = f"转换统计_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
                initialfile=default_name
            )
            if filepath:
                stats = self.convert_stats
                duration = ""
                if stats['start_time'] and stats['end_time']:
                    delta = stats['end_time'] - stats['start_time']
                    duration = str(delta).split('.')[0]

                with open(filepath, 'w', encoding='utf-8-sig') as f:
                    f.write("编码转换统计报告\n")
                    f.write(f"生成时间,{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"源目录/文件,{self.source_dir.get()}\n")
                    f.write(f"处理模式,{'单个文件' if self.is_single_file else '文件夹'}\n")
                    f.write(f"输出目录,{self.output_dir.get() or '原地转换'}\n")
                    f.write(f"源编码,{self.source_enc.get()}\n")
                    f.write(f"目标编码,{self.target_enc.get()}\n")
                    f.write(f"文件总数,{self.total}\n")
                    f.write(f"成功转换,{stats['success']}\n")
                    f.write(f"跳过文件,{stats['skipped']}\n")
                    f.write(f"失败文件,{stats['failed']}\n")
                    f.write(f"校验通过,{stats['verified_ok']}\n")
                    f.write(f"校验失败,{stats['verified_fail']}\n")
                    f.write(f"耗时,{duration}\n")

                self.log(f"统计已导出到：{filepath}")
                self._ui(messagebox.showinfo, "成功", f"统计已保存到：\n{filepath}")
        except Exception as e:
            self._ui(messagebox.showerror, "错误", f"导出失败：{str(e)}")

    # ------------------------------ 备份相关 (.bak 格式) ------------------------------
    def get_backup_path(self, original_path):
        """获取原文件对应的.bak备份路径（源目录/backup/保持原目录结构）"""
        src_root = self.source_dir.get() if not self.is_single_file else os.path.dirname(self.source_dir.get())
        if not src_root:
            src_root = os.path.dirname(original_path) or os.getcwd()
        backup_root = os.path.join(src_root, "backup")
        os.makedirs(backup_root, exist_ok=True)

        try:
            rel_path = os.path.relpath(original_path, src_root)
            if rel_path.startswith(".."):
                rel_path = os.path.basename(original_path)
        except ValueError:
            rel_path = os.path.basename(original_path)
        backup_path = os.path.join(backup_root, rel_path) + ".bak"
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        return backup_path

    def backup_file(self, original_path):
        """将文件备份到源目录的backup子目录中（保持原目录结构）"""
        try:
            backup_path = self.get_backup_path(original_path)
            if not os.path.exists(backup_path):
                shutil.copy2(original_path, backup_path)
                self.log(f"[备份] {os.path.basename(original_path)} → {backup_path}")
            else:
                self.log(f"[备份跳过] {os.path.basename(original_path)} 已存在备份文件：{backup_path}")
        except Exception as e:
            self.log(f"[备份失败] {os.path.basename(original_path)} | {str(e)}")

    # ------------------------------ 恢复备份 (.bak 格式) ------------------------------
    def restore_file(self, bak_path):
        """将backup目录下的.bak备份文件恢复到原位置"""
        try:
            src_root = self.source_dir.get() if not self.is_single_file else os.path.dirname(self.source_dir.get())
            backup_root = os.path.join(src_root, "backup")
            rel_path = os.path.relpath(bak_path, backup_root)[:-4]
            original_path = os.path.join(src_root, rel_path)
            
            if os.path.exists(original_path):
                shutil.copy2(bak_path, original_path)
                self.log(f"[恢复] {os.path.basename(bak_path)} → {original_path}")
            else:
                self.log(f"[恢复失败] {os.path.basename(bak_path)} | 原文件不存在：{original_path}")
        except Exception as e:
            self.log(f"[恢复失败] {os.path.basename(bak_path)} | {str(e)}")

    def run_restore(self):
        """执行恢复备份逻辑（适配backup目录下的.bak格式）"""
        try:
            self.log("===== 开始恢复备份 =====")
            if not self._snap['source_dir']:
                self._ui(messagebox.showerror, "错误", "请选择源目录")
                return

            src_root = self._snap['source_dir'] if not self.is_single_file else os.path.dirname(self._snap['source_dir'])
            backup_root = os.path.join(src_root, "backup")
            if not os.path.exists(backup_root):
                self.log("未找到backup目录")
                self._ui(messagebox.showinfo, "提示", "未找到backup目录，无备份可恢复")
                return

            exts = [e.strip().lower() for e in self._snap['file_exts'].split(",") if e.strip()]
            if not exts:
                raise Exception("请输入文件扩展名，例如 .xml,.txt")

            bak_exts = [f"{e}.bak" for e in exts]
            backup_files = []
            for r, _, fs in os.walk(backup_root):
                for f in fs:
                    if any(f.lower().endswith(e) for e in bak_exts):
                        backup_files.append(os.path.join(r, f))
                if not self._snap['recursive']:
                    break

            self.total = len(backup_files)
            self.current = 0
            self._ui(self.prog_var.set, 0)
            self._ui(self.prog_label.config, text=f"0 / {self.total}")

            if self.total == 0:
                self.log("未找到.bak备份文件")
                self._ui(messagebox.showinfo, "提示", "未找到可恢复的.bak备份文件")
                return

            for f in backup_files:
                self.restore_file(f)
                self.current += 1
                self._ui(self.prog_var.set, (self.current / self.total) * 100)
                self._ui(self.prog_label.config, text=f"{self.current} / {self.total}")

            self.log("===== 恢复完成 =====")
            self._ui(messagebox.showinfo, "完成", f"恢复完成！\n总计：{self.total} 个.bak文件")

        except Exception as e:
            self.log(f"恢复异常：{str(e)}")
            self._ui(messagebox.showerror, "错误", str(e))

    def start_restore_thread(self):
        """启动恢复备份线程"""
        if messagebox.askyesno("确认", "恢复备份将替换当前文件，是否继续？"):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'auto_verify': self.auto_verify.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }
            threading.Thread(target=self.run_restore, daemon=True).start()

    # ------------------------------ 清空备份功能 ------------------------------
    def run_clear_backup(self):
        """执行清空backup目录下的.bak备份文件逻辑"""
        try:
            self.log("===== 开始清空备份 =====")
            if not self._snap['source_dir']:
                self._ui(messagebox.showerror, "错误", "请选择源目录")
                return

            src_root = self._snap['source_dir'] if not self.is_single_file else os.path.dirname(self._snap['source_dir'])
            backup_root = os.path.join(src_root, "backup")
            if not os.path.exists(backup_root):
                self.log("未找到backup目录")
                self._ui(messagebox.showinfo, "提示", "未找到backup目录，无备份可清空")
                return

            exts = [e.strip().lower() for e in self._snap['file_exts'].split(",") if e.strip()]
            if not exts:
                raise Exception("请输入文件扩展名，例如 .xml,.txt")

            bak_exts = [f"{e}.bak" for e in exts]
            backup_files = []
            for r, _, fs in os.walk(backup_root):
                for f in fs:
                    if any(f.lower().endswith(e) for e in bak_exts):
                        backup_files.append(os.path.join(r, f))
                if not self._snap['recursive']:
                    break

            self.total = len(backup_files)
            self.current = 0
            self._ui(self.prog_var.set, 0)
            self._ui(self.prog_label.config, text=f"0 / {self.total}")

            if self.total == 0:
                self.log("未找到.bak备份文件")
                self._ui(messagebox.showinfo, "提示", "未找到可清空的.bak备份文件")
                return

            for f in backup_files:
                try:
                    os.remove(f)
                    self.log(f"[删除备份] {os.path.basename(f)} → {f}")
                except Exception as e:
                    self.log(f"[删除失败] {os.path.basename(f)} | {str(e)}")
                self.current += 1
                self._ui(self.prog_var.set, (self.current / self.total) * 100)
                self._ui(self.prog_label.config, text=f"{self.current} / {self.total}")

            self.log("===== 清空备份完成 =====")
            self._ui(messagebox.showinfo, "完成", f"清空备份完成！\n总计处理：{self.total} 个文件")

        except Exception as e:
            self.log(f"清空备份异常：{str(e)}")
            self._ui(messagebox.showerror, "错误", str(e))

    def start_clear_backup_thread(self):
        """启动清空备份线程"""
        if messagebox.askyesno("确认", "确认要删除backup目录下所有.bak备份文件吗？此操作不可恢复！"):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'auto_verify': self.auto_verify.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }
            threading.Thread(target=self.run_clear_backup, daemon=True).start()

    # ------------------------------ 核心转换 ------------------------------
    def _get_source_encoding(self, raw_data):
        """获取源编码 (确定性优先):
        1. XML 声明 (权威) → 2. 严格 utf-8 解码测试 (确定性区分 utf-8/单字节)
        → 3. 手动指定 (非 utf-8 文件) → 4. cp1251 兜底."""
        # 1. XML 声明优先
        m = re.search(rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']',
                      raw_data[:500], re.I | re.S)
        if m:
            decl_enc = m.group(1).decode("ascii", "replace").strip().lower()
            if decl_enc in ("utf-8", "utf8"):
                return "utf-8"
            if decl_enc in ("windows-1251", "windows1251", "cp1251", "cp-1251"):
                return "windows-1251"
            if decl_enc:
                return decl_enc
        # 2. 严格 utf-8 解码测试 (确定性, 区分 utf-8 vs 单字节编码)
        try:
            raw_data.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        # 3. 手动指定 (对无声明且非 utf-8 的文件生效)
        specified_enc = self._snap['source_enc'].strip().lower()
        if specified_enc and specified_enc != "auto":
            return specified_enc
        # 4. cp1251 兜底 (STALKER 俄语场景)
        return "windows-1251"

    def get_files(self):
        self._ensure_snap()

        # 单文件模式
        if self.is_single_file:
            path = self._snap['source_dir'].strip()
            if os.path.isfile(path):
                if self.is_excluded(path):
                    self.log(f"[排除] {os.path.basename(path)}")
                    return []
                return [path]
            else:
                raise Exception("无效的文件路径")

        # 文件夹模式
        src = self._snap['source_dir'].strip()
        if not os.path.isdir(src):
            raise Exception("无效的源目录")
        exts = [e.strip().lower() for e in self._snap['file_exts'].split(",") if e.strip()]
        if not exts:
            raise Exception("请输入文件扩展名，例如 .xml,.txt")
        
        files = []
        for r, _, fs in os.walk(src):
            # 跳过backup目录
            if "backup" in os.path.relpath(r, src).split(os.sep):
                continue
            for f in fs:
                # 排除.bak文件
                if f.lower().endswith(".bak"):
                    continue
                if any(f.lower().endswith(e) for e in exts):
                    filepath = os.path.join(r, f)
                    if not self.is_excluded(filepath):
                        files.append(filepath)
                    else:
                        self.log(f"[排除] {os.path.basename(filepath)}")
            if not self._snap['recursive']:
                break
        return files

    def convert_file(self, path):
        """转换单个文件"""
        self._ensure_snap()
        if self.cancelled:
            return "cancelled"

        self.pause_event.wait()

        try:
            with open(path, "rb") as f:
                raw = f.read()
            # 字节级剥离 BOM (cp1251 解码 BOM 是乱码而非 \ufeff, 必须在解码前处理)
            if raw[:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
            elif raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                raw = raw[2:]
            
            src_enc = self._get_source_encoding(raw)
            target = self._snap['target_enc'].lower()

            # 日志: 准确反映编码来源
            decl_m = re.search(rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', raw[:500], re.I | re.S)
            if decl_m:
                enc_source = f"声明({src_enc})"
            elif self._snap['source_enc'].strip().lower() == "auto":
                enc_source = f"自动({src_enc})"
            else:
                enc_source = f"指定({src_enc})"

            if self._snap['output_dir']:
                if self.is_single_file:
                    out_path = os.path.join(self._snap['output_dir'], os.path.basename(path))
                else:
                    src_root = self._snap['source_dir']
                    try:
                        rel = os.path.relpath(path, src_root) if src_root else os.path.basename(path)
                    except ValueError:
                        rel = os.path.basename(path)
                    out_path = os.path.join(self._snap['output_dir'], rel)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
            else:
                out_path = path

            if src_enc == target:
                if self._snap['output_dir']:
                    shutil.copy2(path, out_path)
                self.log(f"[跳过] {os.path.basename(path)} | 源={enc_source}，已是目标编码")
                self.convert_stats['skipped'] += 1
                return "skipped"

            try:
                content = raw.decode(src_enc, errors="replace")
            except:
                fallback_enc = "windows-1251"
                content = raw.decode(fallback_enc, errors="replace")
                self.log(f"[警告] {os.path.basename(path)} | {src_enc}解码失败，使用{fallback_enc}")

            # 剥离源 BOM (U+FEFF 作为字符保留会令输出以 BOM 字节开头, 触发"转换后带BOM"校验)
            if content.startswith("\ufeff"):
                content = content[1:]

            if path.lower().endswith(".xml"):
                # XML 声明: 统一双引号 + 替换 encoding 值为目标编码 (保留其他属性)
                def _fix_xml_decl(m):
                    decl = m.group(0).replace("'", '"')
                    decl = re.sub(r"(encoding\s*=\s*\")[^\"]*(\")",
                                  lambda mm: mm.group(1) + self._snap['target_enc'] + mm.group(2),
                                  decl, flags=re.I)
                    return decl
                content = re.sub(r"<\?xml[^>]*\?>", _fix_xml_decl, content, count=1, flags=re.I)

            if not self._snap['output_dir'] and self._snap['backup_files']:
                self.backup_file(path)

            with open(out_path, "w", encoding=self._snap['target_enc'], errors="replace", newline="") as f:
                f.write(content)

            verify_result = ""
            if self._snap['auto_verify']:
                success, msg = self.verify_file(path, out_path)
                if success:
                    self.convert_stats['verified_ok'] += 1
                    verify_result = " | 校验通过"
                else:
                    self.convert_stats['verified_fail'] += 1
                    verify_result = f" | 校验失败: {msg}"

            self.convert_stats['success'] += 1
            self.log(f"[成功] {os.path.basename(path)} | {enc_source} → {target}{verify_result}")
            return "success"

        except Exception as e:
            self.convert_stats['failed'] += 1
            self.log(f"[失败] {os.path.basename(path)} | {str(e)}")
            return "failed"

    def run_convert(self):
        """执行转换"""
        try:
            self.paused = False
            self.cancelled = False
            self.pause_event.set()

            self.convert_stats = {
                'success': 0, 'skipped': 0, 'failed': 0,
                'verified_ok': 0, 'verified_fail': 0,
                'start_time': datetime.now(), 'end_time': None
            }

            self._ui(self.start_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, state=tk.NORMAL)
            self._ui(self.cancel_btn.config, state=tk.NORMAL)
            self._ui(self.pause_btn.config, text="暂停")

            self.log("===== 开始转换 =====")
            
            enc_setting = self._snap['source_enc'].strip().lower()
            if enc_setting == "auto":
                self.log("源编码：自动检测（chardet）")
            else:
                self.log(f"源编码：手动指定为 {enc_setting}")

            if not self._snap['source_dir']:
                self._ui(messagebox.showerror, "错误", "请选择源目录或文件")
                return

            files = self.get_files()
            self.total = len(files)
            self.current = 0
            self._ui(self.prog_var.set, 0)
            self._ui(self.prog_label.config, text=f"0 / {self.total}")

            if self.total == 0:
                self.log("未找到目标文件")
                self._ui(messagebox.showinfo, "完成", "未找到可转换文件")
                return

            for f in files:
                result = self.convert_file(f)
                self.current += 1
                self._ui(self.prog_var.set, (self.current / self.total) * 100)
                self._ui(self.prog_label.config, text=f"{self.current} / {self.total}")

                if result == "cancelled":
                    break

            self.convert_stats['end_time'] = datetime.now()
            duration = str(self.convert_stats['end_time'] - self.convert_stats['start_time']).split('.')[0]

            if self.cancelled:
                self.log(f"===== 转换已取消 =====")
                self.log(f"已处理：{self.current}/{self.total} 文件 | 耗时：{duration}")
            else:
                self.log("===== 全部完成 =====")

            stats = self.convert_stats
            summary = (
                f"\n========== 转换统计 ==========\n"
                f"总文件数：{self.total}\n"
                f"成功转换：{stats['success']}\n"
                f"跳过文件：{stats['skipped']}\n"
                f"失败文件：{stats['failed']}\n"
            )
            if self._snap['auto_verify']:
                summary += (
                    f"校验通过：{stats['verified_ok']}\n"
                    f"校验失败：{stats['verified_fail']}\n"
                )
            summary += (
                f"总耗时：{duration}\n"
                f"================================"
            )
            self.log(summary)

            msg = f"处理完成！\n总计：{self.total} 个文件\n"
            msg += f"成功：{stats['success']} | 跳过：{stats['skipped']} | 失败：{stats['failed']}\n"
            msg += f"耗时：{duration}"
            self._ui(messagebox.showinfo, "完成", msg)

        except Exception as e:
            self.log(f"异常：{str(e)}")
            self._ui(messagebox.showerror, "错误", str(e))
        finally:
            self._ui(self.start_btn.config, state=tk.NORMAL)
            self._ui(self.pause_btn.config, state=tk.DISABLED)
            self._ui(self.cancel_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, text="暂停")
            self.paused = False
            self.pause_event.set()

    def start_thread(self):
        self._snap = {
            'source_dir': self.source_dir.get(),
            'output_dir': self.output_dir.get(),
            'file_exts': self.file_exts.get(),
            'target_enc': self.target_enc.get(),
            'source_enc': self.source_enc.get(),
            'recursive': self.recursive.get(),
            'backup_files': self.backup_files.get(),
            'auto_verify': self.auto_verify.get(),
            'exclude_pattern': self.exclude_pattern.get(),
            'is_single_file': self.is_single_file,
        }
        threading.Thread(target=self.run_convert, daemon=True).start()

# ═══ 零散文本提取 ═══
RUS_LETTERS = "".join(chr(c) for c in range(0x0410, 0x0450)) + "\u0401\u0451"
RUS_LET_CPL = re.compile("[" + RUS_LETTERS + "]")
WORD_PATTERN = re.compile("[" + RUS_LETTERS + "a-zA-Z]")
SCRIPT_LINE_PERMIT_PTN = re.compile(
    r"([Mm]essage|[Tt]ext(?!ure)|(?<![a-z])[Nn]ews(?![a-z]))")
SCRIPT_LINE_SENSITIVE_PTN = re.compile(
    r"(exec|write|parse_names|load|(?<!de)script(?!ion)|call|"
    r"set(?![Tt]ext)|open|sound|effect|abort|print|console|cmd|return)")
SCRIPT_MATCH_SENSITIVE_PTN = re.compile(r'("[\s]*return)')
CFG_TAG_PTN = re.compile(
    r"<(?:text|bio|title|name)(?:| [ \S]*?[^/]) *?>([^<>]*?)</(?:text|bio|title|name)>")
CFG_ATTR_PTN = re.compile(r'(?:hint|name)\s*=\s*((?:"[^"]*")|' + r"(?:'[^']*'))")
SCRIPT_TRANSLATE_FUNC = "game.translate_string"


def _does_text_look_like_id(text: str) -> bool:
    if len(RUS_LET_CPL.findall(text)) > 0:
        return False
    if "_" in text:
        return True
    return " " not in text


def _does_text_look_like_script(text: str) -> bool:
    if len(RUS_LET_CPL.findall(text)) > 0:
        return False
    if '=' in text or '@' in text:
        return True
    for blk in [r":\d", r"load\s+~+"]:
        if re.compile(blk).search(text):
            return True
    return False


def _get_config_xml_texts(text: str) -> Set[str]:
    candidates = []
    for m in CFG_TAG_PTN.findall(text):
        if m.strip():
            candidates.append(m.strip())
    for m in CFG_ATTR_PTN.findall(text):
        if len(m) > 2:
            candidates.append(m[1:-1])
    return set(candidates)


def _escape_literal_text(text: str, quote: str = '"') -> str:
    escaped = text.replace("\\", '\\\\').replace("\n", '\\n')
    if quote == '"':
        escaped = escaped.replace('"', '\\"')
    elif quote == "'":
        escaped = escaped.replace("'", "\\'")
    return escaped


def _get_script_texts(text: str) -> Set[str]:
    result = set()
    for line in text.split("\n"):
        line = re.sub(r'--[\s\S]*$', '', line).strip()
        is_open, ongoing, is_escape, quote_char = False, '', False, None
        line_matches = set()
        for i, ch in enumerate(line):
            if ch in ('"', "'"):
                if ch == quote_char or quote_char is None:
                    if not is_open:
                        ongoing, quote_char, is_open = ch, ch, True
                        continue
                    if is_escape:
                        ongoing += ch; is_escape = False
                    else:
                        ongoing += ch; is_open = False; quote_char = None
                        if (not SCRIPT_MATCH_SENSITIVE_PTN.search(ongoing)
                                and WORD_PATTERN.search(ongoing)):
                            line_matches.add(ongoing)
                    continue
            if is_open:
                if ch == '\\':
                    is_escape = not is_escape
                    if not is_escape: ongoing += '\\\\'
                    else: ongoing += '\\'
                elif ch == 'n' and is_escape:
                    ongoing += '\n'; is_escape = False
                else:
                    ongoing += ch
        sorted_lm = sorted(line_matches, key=len, reverse=True)
        sac_line = line
        for lm in sorted_lm:
            qc = lm[0]
            sac_line = sac_line.replace(
                qc + _escape_literal_text(lm[1:-1], quote=qc) + qc, "")
        norm = sac_line.lower()
        if SCRIPT_LINE_PERMIT_PTN.search(norm):
            result = set(sorted_lm + list(result))
        elif not SCRIPT_LINE_SENSITIVE_PTN.search(norm):
            result = set(sorted_lm + list(result))
    return result


def _replace_from_text(text: str, replacement: Dict[str, str]) -> str:
    for key in sorted(replacement, key=len, reverse=True):
        text = text.replace(key, replacement[key])
    return text


def _escape_xml_content(text: str) -> str:
    for a, b in [('&', '&amp;'), ('"', '&quot;'), ("'", '&apos;'), ('<', '&lt;')]:
        text = text.replace(a, b)
    text = text.strip()
    return text if text else '\xa0'


def _split_text_at_length(text: str, n: int) -> List[str]:
    if not text: return [""]
    return [text[i*n:(i+1)*n] for i in range(len(text)//n)] + [text[(len(text)//n)*n:]]


def _normalize_xml_string(xml_str: str, need_fix_st: bool = True,
                          delete_header: bool = True) -> str:
    if need_fix_st: delete_header = True
    if "</" in xml_str:
        while xml_str and not xml_str.startswith("<"):
            xml_str = xml_str[1:]
    xml_str = re.sub(r'&[\s]+amp;', '&amp;', xml_str)
    xml_str = re.sub(r'&[\s]+lt;', '&lt;', xml_str)
    xml_str = re.sub(
        '&(?!ensp;|emsp;|nbsp;|lt;|gt;|amp;|quot;|copy;|reg;|trade;|times;|divide;)',
        '&amp;', xml_str)
    xml_str = re.sub(r'<!--[\s\S]*?-->', '', xml_str)
    if delete_header:
        xml_str = re.sub(r'<\?[^>]+\?>', '', xml_str)
    tc = (r'A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF'
          r'\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F'
          r'\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD')
    xml_str = re.sub(r'<(?![%s/])' % tc, '&lt;', xml_str).strip()
    if xml_str.startswith("&lt;?xml"): xml_str = "<" + xml_str[4:]
    if need_fix_st:
        if not xml_str.strip().startswith("<string_table>"):
            xml_str = "<string_table>" + xml_str + "</string_table>"
        xml_str = re.sub(r"</string_table>[\s\S]+", "</string_table>", xml_str)
    return xml_str


def _generate_text_xml(filepath: str, texts: Dict[str, str]):
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<string_table>']
    for tid, tcontent in texts.items():
        safe_id = _escape_xml_content(tid)
        safe_text = '\n'.join(
            _split_text_at_length(_escape_xml_content(tcontent), 1000))
        lines.append(f'\t<string id="{safe_id}">')
        lines.append(f'\t\t<text>{safe_text}</text>')
        lines.append('\t</string>')
    lines.append('</string_table>')
    with open(filepath, "w", encoding="utf-8") as f:
        f.write('\n'.join(lines) + '\n')


def _generate_output_file(filepath: str, text: str, encoding: str = "utf-8",
                          add_xml_header: bool = False):
    if add_xml_header and not text.strip().startswith("<?xml"):
        text = '<?xml version="1.0" encoding="utf-8"?>\n' + text.strip()
    with open(filepath, "w", encoding=encoding) as f:
        f.write(text)


def _parse_cfgxml(filepath: str, quiet: bool = False) -> Tuple[str, Set[str], str]:
    whole_text, success_enc = read_text_file(filepath)
    whole_text = _normalize_xml_string(whole_text, need_fix_st=False, delete_header=False)
    return (whole_text, _get_config_xml_texts(whole_text), success_enc)


def _local_read_text_file(path):
    """自包含回退 (与 toolkit.read_text_file 相同)."""
    for i, enc in enumerate(DEFAULT_ENCODINGS):
        try:
            with open(path, "r", encoding=enc,
                      errors="ignore" if i == len(DEFAULT_ENCODINGS) - 1 else "strict") as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def _parse_script(filepath: str, quiet: bool = False) -> Tuple[str, Set[str]]:
    whole_text = None
    for i, enc in enumerate(DEFAULT_ENCODINGS):
        try:
            flag = (i == len(DEFAULT_ENCODINGS) - 1)
            with open(filepath, "r", encoding=enc,
                      errors="ignore" if flag else "strict") as f:
                whole_text = f.read()
            if not quiet:
                print(f"  [{'FORCED ' if flag else ''}{enc}] {filepath}")
            break
        except UnicodeDecodeError:
            if not quiet: print(f"  [NOT {enc}] {filepath}")
    if whole_text is None:
        raise ValueError(f"Cannot decode {filepath}")
    return (whole_text, _get_script_texts(whole_text))


# ============================================================================
#  提取核心
# ============================================================================

def _extract_gameplay(src: str, dst: str, id_prefix: str, verbose: bool = True) -> dict:
    extracted, counter, fc, cc = {}, 0, 0, 0
    sp, tp = Path(src), Path(dst)
    for f in sorted(sp.rglob("*.xml")):
        rel = f.relative_to(sp)
        if any(p.startswith("translated_") or p == "text" for p in rel.parts):
            continue
        try:
            wt, cands, enc = _parse_cfgxml(str(f), quiet=not verbose)
        except Exception as e:
            if verbose: print(f"  SKIP {rel}: {e}")
            continue
        fc += 1; repls = {}
        for c in cands:
            if not c.strip() or _does_text_look_like_id(c): continue
            eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
            extracted[eid] = c; repls[c] = eid
            if verbose: print(".", end="", flush=True)
        out = tp / rel; out.parent.mkdir(parents=True, exist_ok=True)
        _generate_output_file(str(out),
                              _replace_from_text(wt, repls) if repls else wt,
                              encoding=enc)
        if verbose and not repls: print(f"  [0] {rel}")
    if verbose: print(f"\n  gameplay: {fc} files, {counter} strings, {cc} chars")
    return extracted


def _extract_scripts(src: str, dst: str, id_prefix: str, verbose: bool = True) -> dict:
    extracted, counter, fc, cc = {}, 0, 0, 0
    sp, tp = Path(src), Path(dst)
    for f in sorted(sp.rglob("*.script")):
        rel = f.relative_to(sp)
        if any(p.startswith("translated_") for p in rel.parts): continue
        try:
            wt, cands = _parse_script(str(f), quiet=not verbose)
        except Exception as e:
            if verbose: print(f"  SKIP {rel}: {e}")
            continue
        fc += 1; repls = {}
        for cq in cands:
            qc = cq[0]; c = cq[1:-1]
            if _does_text_look_like_id(c) or _does_text_look_like_script(c): continue
            eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
            extracted[eid] = c
            old = qc + _escape_literal_text(c, quote=qc) + qc
            repls[old] = f'{SCRIPT_TRANSLATE_FUNC}("{eid}")'
            if verbose: print(".", end="", flush=True)
        out = tp / rel; out.parent.mkdir(parents=True, exist_ok=True)
        _generate_output_file(str(out),
                              _replace_from_text(wt, repls) if repls else wt)
        if verbose and not repls: print(f"  [0] {rel}")
    if verbose: print(f"\n  scripts: {fc} files, {counter} strings, {cc} chars")
    return extracted


def run_extraction(source: str, target: str = "", prefix: str = "mod",
                   clean: bool = False, log_callback=None) -> dict:
    """提取文本. 一次性仅处理 gameplay 或 scripts 其中之一.
    target 为空 = 原地: 新文件写回源子目录, 提取 xml 放源根.
    target 有值 = 输出目录: 新建 gameplay/scripts 放新文件, xml 直接放输出根."""
    def log(msg):
        if log_callback: log_callback(msg)

    source = os.path.abspath(source)
    if not os.path.isdir(source):
        raise FileNotFoundError(f"Source not found: {source}")

    # 识别类型: 源目录本身是 gameplay/scripts, 或父目录含其一 (两者都有则拒绝)
    base = os.path.basename(source).lower()
    if base in ("gameplay", "scripts"):
        ftype = base
        src_sub = source
    else:
        subs = [s for s in ("gameplay", "scripts") if os.path.isdir(os.path.join(source, s))]
        if not subs:
            raise ValueError("源目录中未找到 gameplay 或 scripts 子目录")
        if len(subs) > 1:
            raise ValueError("仅支持一次性处理 gameplay 或 scripts 其中之一")
        ftype = subs[0]
        src_sub = os.path.join(source, ftype)

    # 输出布局
    if not target:
        out_root = source          # xml 放源根
        dst_sub = src_sub          # 新文件原地替换
        log("未指定输出目录: 原地替换, xml 输出到源目录")
    else:
        target = os.path.abspath(target)
        out_root = target          # xml 放输出根
        dst_sub = os.path.join(target, ftype)
        os.makedirs(dst_sub, exist_ok=True)
        log(f"输出: {dst_sub}/ 新文件 + {prefix}_{ftype}_texts.xml → {out_root}")

    ts = int(time.time())
    id_pre = f"sgtat_{prefix}_{ftype[:2]}_{ts}"
    log(f"ID 前缀: {id_pre}")

    stats = {"gp_files": 0, "gp_strings": 0, "gp_chars": 0,
             "sc_files": 0, "sc_strings": 0, "sc_chars": 0}
    if ftype == "gameplay":
        log("提取 gameplay 配置文本...")
        gp = _extract_gameplay(src_sub, dst_sub, id_pre, verbose=False)
        if gp:
            _generate_text_xml(os.path.join(out_root, f"{prefix}_gameplay_texts.xml"), gp)
            log(f"  gameplay: {len(gp)} 条 → {prefix}_gameplay_texts.xml")
        stats["gp_strings"] = len(gp)
        stats["gp_chars"] = sum(len(v) for v in gp.values())
        stats["gp_files"] = sum(1 for _ in Path(dst_sub).rglob("*.xml"))
    else:
        log("提取 scripts 脚本文本...")
        sc = _extract_scripts(src_sub, dst_sub, id_pre, verbose=False)
        if sc:
            _generate_text_xml(os.path.join(out_root, f"{prefix}_scripts_texts.xml"), sc)
            log(f"  scripts: {len(sc)} 条 → {prefix}_scripts_texts.xml")
        stats["sc_strings"] = len(sc)
        stats["sc_chars"] = sum(len(v) for v in sc.values())
        stats["sc_files"] = sum(1 for _ in Path(dst_sub).rglob("*.script"))

    stats["total"] = stats["gp_strings"] + stats["sc_strings"]
    stats["total_chars"] = stats["gp_chars"] + stats["sc_chars"]
    stats["target"] = out_root
    log(f"完成。总计 {stats['total']} 条文本（{stats['total_chars']:,} 字符）。")
    return stats


# ============================================================================
#  GUI — VS Code Dark+ 风格
# ============================================================================



class TextExtractApp:
    def __init__(self, root):
        self.root = root
        if isinstance(root, tk.Tk):
            self.root.title("STALKER 文本提取器")
            self.root.geometry("780x620")
            self.root.minsize(680, 520)
        self.root.configure(bg=color("bg"))
        self.source_path = tk.StringVar()
        self.target_path = tk.StringVar()
        self.prefix_var = tk.StringVar(value="gs")
        self.clean_var = tk.BooleanVar(value=True)  # 兼容: 旧属性 (已无 UI, 提取默认不清理)
        self.running = False
        apply_theme()
        self._build_ui()
        self._ui = _make_pump(self.root)
        self._setup_drag_drop()

    def _apply_theme(self):
        """统一配色模板: 全部由 toolkit.apply_theme 提供."""
        apply_theme()
    def _setup_drag_drop(self):
        try:
            import tkinterDnD
            if hasattr(self.root, "drop_target_register"):
                self.root.drop_target_register("DND_Files")
                self.root.dnd_bind("<<Drop>>", self._on_drop)
        except ImportError:
            pass

    def _on_drop(self, event):
        data = event.data
        paths = data.strip().split() if isinstance(data, str) else [data]
        for p in paths:
            p = p.strip("{}")
            if os.path.isdir(p):
                if not self.source_path.get():
                    self.source_path.set(os.path.normpath(p))
                elif not self.target_path.get():
                    self.target_path.set(os.path.normpath(p))
                break

    def _on_drop_source(self, event):
        """拖拽文件夹到源目录框."""
        path = event.data.strip("{}").strip()
        if os.path.isdir(path):
            self.source_path.set(os.path.normpath(path))

    def _on_drop_target(self, event):
        """拖拽文件夹到输出目录框."""
        path = event.data.strip("{}").strip()
        if os.path.isdir(path):
            self.target_path.set(os.path.normpath(path))

    def _build_dir_row(self, parent, label_text, var, browse_cmd, drop_cmd=None):
        """统一目录行 (toolkit.dir_row): 标签 + 输入框(边框) + 浏览 + 拖拽."""
        ttk.Label(parent, text=label_text).pack(anchor=tk.W)
        dir_row(parent, "", var, browse=browse_cmd, width=0, drop=drop_cmd)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        # ═══ 可调分区: 上部操作区 / 下部日志统计区 ═══
        self._paned = SplitPane(main, orient=tk.VERTICAL)
        self._paned.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        upper = ttk.Frame(self._paned)
        lower = ttk.Frame(self._paned)
        self._paned.add(upper, weight=3)
        self._paned.add(lower, weight=1)

        tr = ttk.Frame(upper); tr.pack(fill=tk.X, pady=(0, 10))
        tool_header(tr, "STALKER 文本提取", side=tk.LEFT, padx=0, pady=0)
        ttk.Label(tr, text="cfgxml + scriptE  ·  纯提取",
                  style="Dim.TLabel").pack(side=tk.RIGHT)

        self._build_dir_row(upper, "源目录",
                            self.source_path, lambda: self._browse(self.source_path),
                            self._on_drop_source)
        self._build_dir_row(upper, "输出目录",
                            self.target_path, lambda: self._browse(self.target_path),
                            self._on_drop_target)

        or_ = ttk.Frame(upper); or_.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(or_, text="前缀").pack(side=tk.LEFT)
        ttk.Entry(or_, textvariable=self.prefix_var, width=8).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(or_, text="  输出: {prefix}_gameplay_texts.xml + {prefix}_scripts_texts.xml",
                  style="Dim.TLabel").pack(side=tk.LEFT, padx=(16, 0))

        br = ttk.Frame(upper); br.pack(fill=tk.X, pady=(0, 4))
        self.extract_btn = ttk.Button(br, text="▶  提取文本", style="Accent.TButton",
                                       command=self._start)
        self.extract_btn.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(upper, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 8))

        ttk.Separator(lower, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        self.log_lf, self.log = log_section(lower, "日志", height=4)
        self._tag_map = {"success": "ok", "error": "err"}

        self.stats_frame = ttk.LabelFrame(lower, text=" 统计 ", padding=12)
        self.stats_frame.pack(fill=tk.X, pady=(8, 0))
        inner = ttk.Frame(self.stats_frame); inner.pack(fill=tk.X)
        labels = [("gameplay", "gp_stat", "gp_detail"),
                  ("scripts", "sc_stat", "sc_detail"),
                  ("总计", "total_stat", "total_detail")]
        for i, (title, stat_attr, detail_attr) in enumerate(labels):
            if i > 0:
                ttk.Separator(inner, orient=tk.VERTICAL).pack(
                    side=tk.LEFT, fill=tk.Y, padx=20)
            col = ttk.Frame(inner); col.pack(side=tk.LEFT, expand=True)
            ttk.Label(col, text=title, style="Dim.TLabel").pack()
            lbl = ttk.Label(col, text="—", style="Stats.TLabel"); lbl.pack()
            setattr(self, stat_attr, lbl)
            det = ttk.Label(col, text="", style="Dim.TLabel"); det.pack()
            setattr(self, detail_attr, det)

        st = ttk.Frame(main); st.pack(fill=tk.X, pady=(6, 0))
        self.status_lbl = ttk.Label(st, text="就绪", style="Green.TLabel")
        self.status_lbl.pack(side=tk.LEFT)
        ttk.Label(st, text="提取后可拖入 Hana 翻译", style="Dim.TLabel").pack(side=tk.RIGHT)

    def _browse(self, var):
        p = filedialog.askdirectory()
        if p: var.set(os.path.normpath(p))

    def _log(self, msg, tag="info"):
        self.log.add(msg, self._tag_map.get(tag, tag))

    def _clear_log(self):
        self.log.clear()

    def _start(self):
        src = self.source_path.get().strip()
        dst = self.target_path.get().strip()
        pfx = self.prefix_var.get().strip() or "mod"
        if not src: messagebox.showwarning("提示", "请指定源目录"); return
        if not os.path.isdir(src):
            messagebox.showerror("错误", f"源目录不存在：\n{src}"); return
        # 类型预检: 源目录本身是 gameplay/scripts, 或父目录含其一 (两者都有则拒绝)
        base = os.path.basename(src).lower()
        if base not in ("gameplay", "scripts"):
            subs = [s for s in ("gameplay", "scripts") if os.path.isdir(os.path.join(src, s))]
            if not subs:
                messagebox.showwarning("提示", "源目录中未找到 gameplay 或 scripts 子目录。"); return
            if len(subs) > 1:
                messagebox.showwarning("提示", "仅支持一次性处理 gameplay 或 scripts 其中之一。"); return
        if self.running: return
        self.running = True
        self.extract_btn.config(state=tk.DISABLED, text="提取中...")
        self.progress.start(10)
        self.status_lbl.config(text="正在提取...", style="Yellow.TLabel")
        for attr in ["gp_stat", "sc_stat", "total_stat", "gp_detail", "sc_detail", "total_detail"]:
            getattr(self, attr).config(text="..." if "stat" in attr else "")
        self._clear_log()
        self._log("═══ 开始提取 ═══", "dim")
        self._log(f"源: {src}")
        self._log(f"输出: {dst or '(未指定, 原地替换)'}")
        self._log(f"前缀: {pfx}"); self._log("")

        def worker():
            try:
                sts = run_extraction(src, dst, pfx, False,
                                     log_callback=lambda m: self._ui(self._log, m))
                self._ui(self._on_done, sts, None)
            except Exception as e:
                self._ui(self._on_done, None, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, stats, error):
        self.running = False; self.progress.stop()
        self.extract_btn.config(state=tk.NORMAL, text="▶  提取文本")
        if error:
            self._log(f"✕ 错误: {error}", "error")
            self.status_lbl.config(text="提取失败", style="Red.TLabel"); return
        self._log("", "dim"); self._log("═══ 完成 ═══", "success")
        self.gp_stat.config(text=str(stats["gp_strings"]))
        self.gp_detail.config(text=f"{stats['gp_files']} 文件 · {stats['gp_chars']:,} 字符")
        self.sc_stat.config(text=str(stats["sc_strings"]))
        self.sc_detail.config(text=f"{stats['sc_files']} 文件 · {stats['sc_chars']:,} 字符")
        self.total_stat.config(text=str(stats["total"]))
        self.total_detail.config(text=f"{stats['total_chars']:,} 字符")
        pfx = self.prefix_var.get().strip() or "mod"
        self._log(f"产物: {stats['target']}", "success")
        self._log(f"  {pfx}_gameplay_texts.xml", "success")
        self._log(f"  {pfx}_scripts_texts.xml", "success")
        self.status_lbl.config(text=f"完成 · {stats['total']} 条文本", style="Green.TLabel")


# ============================================================================
#  CLI
# ============================================================================

# ═══ XML 校对 ═══
ID_PATTERN = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

# 原版 XML 常见格式缺陷: 未转义的 &、<，以及 <!-- 后多余的 -
_AMP_BAD = re.compile(rb'&(?!amp;|lt;|gt;|quot;|apos;|#x?[0-9a-fA-F]+;)')
_LT_BAD = re.compile(rb'<(?![!/?a-zA-Z])')
_COMMENT_BAD = re.compile(rb'<!--(-+)')


def _fix_entities(raw: bytes) -> bytes:
    """把未转义的 & 和 < 转成实体、修正 <!-- 后多余的 -，容忍原版 XML 格式缺陷。"""
    raw = _AMP_BAD.sub(b'&amp;', raw)
    raw = _LT_BAD.sub(b'&lt;', raw)
    raw = _COMMENT_BAD.sub(b'<!--', raw)
    return raw


def collect_xml_files(root: Path) -> dict[str, Path]:
    files = {}
    for f in root.rglob("*.xml"):
        files[f.relative_to(root).as_posix()] = f
    return files


def read_file_text(filepath: Path) -> str:
    """读取文件，依次尝试 UTF-8 / Windows-1251 / GBK。"""
    for enc in ("utf-8", "windows-1251", "gbk"):
        try:
            return filepath.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return filepath.read_text(encoding="latin-1")


# ── 模式 1：行数/ID 统计 ──────────────────

def parse_file(filepath: Path) -> tuple[int, Counter]:
    text = read_file_text(filepath)
    # 行数统计用原始内容 (含 XML 声明), 反映实际文件行数
    lines = len(text.splitlines())
    if text.endswith(("\n", "\r")):
        lines += 1  # 末尾换行符产生的空行计入
    # ID 统计忽略 XML 声明 (含 BOM), 声明 encoding 差异不影响
    body = re.sub(r"^\s*\ufeff?\s*<\?xml[^>]*\?>\s*", "", text, count=1, flags=re.I | re.S)
    ids = Counter(ID_PATTERN.findall(body))
    return lines, ids


def compare_one(rel: str, fa: Path, fb: Path, na: str, nb: str) -> dict:
    la, ida = parse_file(fa)
    lb, idb = parse_file(fb)

    only_a = sorted(set(ida) - set(idb))
    only_b = sorted(set(idb) - set(ida))
    common = set(ida) & set(idb)
    count_diff = []
    for iid in sorted(common):
        if ida[iid] != idb[iid]:
            count_diff.append((iid, ida[iid], idb[iid]))

    consistent = (la == lb and not only_a and not only_b and not count_diff)
    return {
        "rel": rel,
        "mode": "stats",
        "consistent": consistent,
        "lines_a": la, "lines_b": lb,
        "ids_a": len(ida), "ids_b": len(idb),
        "only_a": only_a, "only_b": only_b,
        "count_diff": count_diff,
        "ida": ida, "idb": idb,
    }


def build_detail(r: dict, na: str, nb: str) -> str:
    """差异摘要（缩略版），列出最多 5 个具体 id 名。"""
    parts = []
    ld = abs(r["lines_a"] - r["lines_b"])
    has_id_diff = bool(r["only_a"] or r["only_b"] or r["count_diff"])

    if ld:
        parts.append(f"行差 {ld}")
        if not has_id_diff:
            parts.append("ID 一致")

    if r["only_a"]:
        preview = ", ".join(r["only_a"][:5])
        more = f" +{len(r['only_a']) - 5}" if len(r["only_a"]) > 5 else ""
        parts.append(f"仅{na}: {preview}{more}")

    if r["only_b"]:
        preview = ", ".join(r["only_b"][:5])
        more = f" +{len(r['only_b']) - 5}" if len(r["only_b"]) > 5 else ""
        parts.append(f"仅{nb}: {preview}{more}")

    if r["count_diff"]:
        preview = ", ".join(iid for iid, _, _ in r["count_diff"][:5])
        more = f" +{len(r['count_diff']) - 5}" if len(r["count_diff"]) > 5 else ""
        parts.append(f"次数不同: {preview}{more}")

    return "；".join(parts) if parts else ""


def build_full_detail(r: dict, na: str, nb: str) -> str:
    lines = []
    ld = abs(r["lines_a"] - r["lines_b"])
    if ld:
        lines.append(f"行数: {na}={r['lines_a']}, {nb}={r['lines_b']} (差 {ld})")
    if r["only_a"]:
        lines.append(f"\n仅 {na} 有的 id ({len(r['only_a'])} 个):")
        for iid in r["only_a"]:
            lines.append(f'  id="{iid}" ×{r["ida"][iid]}')
    if r["only_b"]:
        lines.append(f"\n仅 {nb} 有的 id ({len(r['only_b'])} 个):")
        for iid in r["only_b"]:
            lines.append(f'  id="{iid}" ×{r["idb"][iid]}')
    if r["count_diff"]:
        lines.append(f"\n出现次数不同的 id ({len(r['count_diff'])} 个):")
        for iid, ca, cb in r["count_diff"]:
            lines.append(f'  id="{iid}"  {na}:{ca} / {nb}:{cb}')
    return "\n".join(lines)


# ── 模式 2：ID 文本对比 ──────────────────

def parse_file_text_by_id(filepath: Path) -> dict[str, str]:
    """
    解析 STALKER 风格 XML，提取 id → 文本内容 映射。
    支持两种常见格式：
      <string id="xxx"><text>内容</text></string>
      <text id="xxx">内容</text>
    """
    result = {}
    try:
        raw = _fix_entities(filepath.read_bytes())
        try:
            root = ET.fromstring(raw)
        except Exception:
            # 无 XML 声明且是 CP1251 的情况 (原版常见), 手动指定编码
            root = ET.fromstring(raw.decode("windows-1251"))
        for elem in root.iter():
            eid = elem.get("id")
            if not eid:
                continue
            # 优先查找 <text> 子元素
            text_elem = elem.find("text")
            if text_elem is not None and text_elem.text:
                result[eid] = text_elem.text.strip()
            elif elem.text:
                result[eid] = elem.text.strip()
    except (ET.ParseError, Exception):
        pass
    return result


def compare_text_content(rel: str, fa: Path, fb: Path, na: str, nb: str) -> dict:
    """
    按 ID 比较两个 XML 文件的文本内容。
    返回 only_a（A 有 B 无的 id）、only_b（B 有 A 无的 id）、
    text_diff（文本不同的 id 及两方文本）。
    """
    ida = parse_file_text_by_id(fa)
    idb = parse_file_text_by_id(fb)

    only_a = sorted(set(ida) - set(idb))
    only_b = sorted(set(idb) - set(ida))
    common = set(ida) & set(idb)

    text_diff = []
    for iid in sorted(common):
        if ida[iid] != idb[iid]:
            text_diff.append((iid, ida[iid], idb[iid]))

    consistent = not only_a and not only_b and not text_diff
    return {
        "rel": rel,
        "mode": "text",
        "consistent": consistent,
        "ids_a": len(ida), "ids_b": len(idb),
        "only_a": only_a, "only_b": only_b,
        "text_diff": text_diff,
        "ida_text": ida, "idb_text": idb,
    }


def build_text_detail(r: dict, na: str, nb: str) -> str:
    """文本比较模式差异摘要，列出最多 5 个具体 id。"""
    parts = []
    diff_count = len(r.get("text_diff", [])) + len(r.get("only_a", [])) + len(r.get("only_b", []))

    if diff_count == 0:
        return ""

    if r["only_a"]:
        preview = ", ".join(r["only_a"][:5])
        more = f" +{len(r['only_a']) - 5}" if len(r["only_a"]) > 5 else ""
        parts.append(f"仅{na}: {preview}{more}")

    if r["only_b"]:
        preview = ", ".join(r["only_b"][:5])
        more = f" +{len(r['only_b']) - 5}" if len(r["only_b"]) > 5 else ""
        parts.append(f"仅{nb}: {preview}{more}")

    if r.get("text_diff"):
        preview = ", ".join(iid for iid, _, _ in r["text_diff"][:5])
        more = f" +{len(r['text_diff']) - 5}" if len(r["text_diff"]) > 5 else ""
        parts.append(f"文本不同: {preview}{more}")

    return "；".join(parts) if parts else ""


def build_full_text_detail(r: dict, na: str, nb: str) -> str:
    """文本比较模式完整差异明细。"""
    lines = []
    if r["only_a"]:
        lines.append(f"仅 {na} 有的 id ({len(r['only_a'])} 个):")
        for iid in r["only_a"]:
            text = r.get("ida_text", {}).get(iid, "")
            preview = text[:60] + ("…" if len(text) > 60 else "")
            lines.append(f'  id="{iid}"  →  {preview}')

    if r["only_b"]:
        lines.append(f"\n仅 {nb} 有的 id ({len(r['only_b'])} 个):")
        for iid in r["only_b"]:
            text = r.get("idb_text", {}).get(iid, "")
            preview = text[:60] + ("…" if len(text) > 60 else "")
            lines.append(f'  id="{iid}"  →  {preview}')

    if r.get("text_diff"):
        lines.append(f"\n文本不同的 id ({len(r['text_diff'])} 个):")
        for iid, ta, tb in r["text_diff"]:
            lines.append(f'  id="{iid}"')
            lines.append(f"    {na}: {ta}")
            lines.append(f"    {nb}: {tb}")
            lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════

# 模式配置
MODE_STATS = "行数/ID 统计"
MODE_TEXT = "ID 文本对比"
MODES = [MODE_STATS, MODE_TEXT]

FILTERS_STATS = ["全部", "不一致", "一致", "仅 A 有", "仅 B 有"]
FILTERS_TEXT = ["全部", "有差异", "文本不同", "仅 A 有", "仅 B 有"]


class XMLCompareApp:
    def __init__(self, master=None):
        if master is not None:
            self.root = master
        elif _HAS_DND:
            self.root = TkinterDnD.Tk()
        else:
            from tkinter import Tk
            self.root = Tk()

        if master is None:
            self.root.title("XML 比较工具")
            self.root.geometry("1100x700")
            self.root.minsize(800, 500)

        self.font_mono = color("font_mono")
        self.font_ui = color("font")
        apply_theme()
        apply_tk_defaults(self.root)

        self.results: list[dict] = []
        self.name_a = ""
        self.name_b = ""
        self.running = False

        self.mode_var = tk.StringVar(value=MODE_STATS)
        self.filter_var = tk.StringVar(value="不一致")
        self._current_detail_result = None

        self._build_ui()
        self._ui = _make_pump(self.root)
        self._setup_dragdrop()
        if master is None:
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 布局 ──────────────────────────────

    def _build_ui(self):
        top = tk.Frame(self.root)
        tool_header(self.root, "XML 校对")
        top.pack(fill="x", padx=12, pady=10)

        self.entry_a_var = tk.StringVar()
        self.entry_b_var = tk.StringVar()
        for label, key in [("文件夹 A:", "a"), ("文件夹 B:", "b")]:
            var = self.entry_a_var if key == "a" else self.entry_b_var
            _, entry = dir_row(top, label, var,
                               browse=lambda k=key: self._browse(k),
                               drop=lambda e, k=key: self._on_drop_dir(e, k), width=10)
            setattr(self, f"entry_{key}", entry)

        btn_row = tk.Frame(self.root)
        btn_row.pack(fill="x", padx=12, pady=(0, 4))

        self.btn_compare = tk.Button(btn_row, text="开始比较", font=self.font_ui,
                                  command=self._start_compare, width=12)
        self.btn_compare.pack(side="left", padx=(0, 8))

        tk.Button(btn_row, text="清除", font=self.font_ui,
               command=self._clear_entries, width=6).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="导出", font=self.font_ui,
               command=self._export, width=6).pack(side="left", padx=(0, 12))

        # 模式选择
        tk.Label(btn_row, text="比较模式:", font=self.font_ui).pack(side="left", padx=(0, 4))
        self.cb_mode = ttk.Combobox(btn_row, textvariable=self.mode_var,
                                    values=MODES, state="readonly", width=14)
        self.cb_mode.pack(side="left", padx=(0, 12))
        self.cb_mode.bind("<<ComboboxSelected>>", self._on_mode_change)

        self.lbl_status = tk.Label(btn_row, text="" if _HAS_DND else "拖拽不可用，请用浏览按钮",
                                font=self.font_ui, fg=color("text_dim"))
        self.lbl_status.pack(side="left")

        self.stat_frame = tk.Frame(self.root)
        self.stat_frame.pack(fill="x", padx=12)
        self.lbl_stat = tk.Label(self.stat_frame, text="", font=self.font_ui, fg=color("text_dim"))
        self.lbl_stat.pack(side="left")

        filter_row = tk.Frame(self.root)
        filter_row.pack(fill="x", padx=12, pady=(4, 0))
        tk.Label(filter_row, text="筛选:", font=self.font_ui).pack(side="left")
        self.cb_filter = ttk.Combobox(filter_row, textvariable=self.filter_var,
                                      values=FILTERS_STATS, state="readonly", width=10)
        self.cb_filter.pack(side="left", padx=4)
        self.cb_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())

        # ═══ 可调分区: 主表格 / 日志 (详情栏独立, 有差异时显示) ═══
        paned = SplitPane(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        self._paned = paned
        # 上层: 筛选框大框 (表格 + 内嵌详情栏, 中间可拖拽分隔)
        top_area = tk.Frame(paned)
        paned.add(top_area, weight=3)
        inner = SplitPane(top_area, orient="vertical")
        inner.pack(fill="both", expand=True)
        self._inner = inner

        tree_frame = tk.Frame(inner)
        inner.add(tree_frame, weight=3)

        # 日志区 (第二 pane, hub 集成时隐藏并重定向到全局日志)
        log_frame = tk.Frame(paned)
        paned.add(log_frame, weight=1)
        self.log_lf, self.log = log_section(log_frame, "日志", height=4)
        self.log._log_role = True

        # 详情栏 (内嵌于筛选框大框, 与表格之间可拖拽分隔; 平时隐藏)
        self.detail_frame = tk.Frame(inner)
        self._detail_text = LogBox(self.detail_frame, height=8, wrap="word", scrollbar=True,
                                   tags=[("diff", "red"), ("ok", "green"),
                                         ("only", "orange")])

        columns = ("rel", "status", "lines", "ids")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                 selectmode="browse")
        self.tree.heading("rel", text="文件 (相对路径)")
        self.tree.heading("status", text="状态")
        self.tree.heading("lines", text="行数")
        self.tree.heading("ids", text="ID 数")

        self.tree.column("rel", width=280, minwidth=150)
        self.tree.column("status", width=60, minwidth=50, anchor="center")
        self.tree.column("lines", width=120, minwidth=80, anchor="center")
        self.tree.column("ids", width=120, minwidth=80, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.tree.tag_configure("diff", foreground=color("red"))
        self.tree.tag_configure("ok", foreground=color("green"))
        self.tree.tag_configure("only", foreground=color("orange"))

    # ── 拖放 ──────────────────────────────

    def _setup_dragdrop(self):
        """仅目录框支持精准拖拽 (见 dir_row 的 drop), 不再注册整个窗口拖拽."""
        pass


    def _browse(self, key: str):
        path = filedialog.askdirectory(title=f"选择文件夹 {key.upper()}")
        if path:
            var = self.entry_a_var if key == "a" else self.entry_b_var
            var.set(path)


    def _on_drop_dir(self, event, key: str):
        """拖拽文件夹到目录框: 精准定位到 A 或 B."""
        raw = event.data
        try:
            paths = self.root.tk.splitlist(raw)
        except Exception:
            paths = [raw]
        dirs = [p for p in paths if os.path.isdir(p)]
        if not dirs:
            return
        var = self.entry_a_var if key == "a" else self.entry_b_var
        var.set(dirs[0])

    def _clear_entries(self):
        """清空两个目录栏。"""
        self.entry_a_var.set("")
        self.entry_b_var.set("")

    def _log(self, msg, tag="info"):
        """日志 (hub 集成时重定向到全局日志, 独立运行写到日志区)."""
        try:
            self._ui(lambda: self.log.add(msg, tag))
        except Exception:
            pass

    def _on_mode_change(self, event=None):
        """切换比较模式时更新筛选项和列标题, 并自动重新对比."""
        mode = self.mode_var.get()
        if mode == MODE_TEXT:
            self.cb_filter.config(values=FILTERS_TEXT)
            if self.filter_var.get() not in FILTERS_TEXT:
                self.filter_var.set("有差异")
            self.tree.heading("lines", text="差异 ID")
            self.tree.heading("ids", text="ID 总数")
        else:
            self.cb_filter.config(values=FILTERS_STATS)
            if self.filter_var.get() not in FILTERS_STATS:
                self.filter_var.set("不一致")
            self.tree.heading("lines", text="行数")
            self.tree.heading("ids", text="ID 数")
        # 用户切换模式且路径已填: 自动按新模式重新对比
        if event is not None and self.entry_a_var.get().strip() and self.entry_b_var.get().strip():
            self._start_compare()
        elif self.results:
            self._refresh_tree()

    def _start_compare(self):
        if self.running:
            return
        pa = self.entry_a_var.get().strip()
        pb = self.entry_b_var.get().strip()
        if not pa or not pb:
            messagebox.showwarning("路径缺失", "请先选择两个文件夹。")
            return
        if not Path(pa).is_dir():
            messagebox.showerror("路径无效", f"文件夹 A 不存在:\n{pa}")
            return
        if not Path(pb).is_dir():
            messagebox.showerror("路径无效", f"文件夹 B 不存在:\n{pb}")
            return

        self.running = True
        self.btn_compare.config(state="disabled", text="比较中...")
        self.lbl_status.config(text="正在扫描...", fg=color("yellow"))
        self.tree.delete(*self.tree.get_children())
        self.results = []
        self._current_detail_result = None

        mode = self.mode_var.get()
        threading.Thread(target=self._run_compare, args=(pa, pb, mode), daemon=True).start()

    def _run_compare(self, pa: str, pb: str, mode: str):
        try:
            root_a = Path(pa)
            root_b = Path(pb)
            self.name_a = root_a.name
            self.name_b = root_b.name

            files_a = collect_xml_files(root_a)
            files_b = collect_xml_files(root_b)

            common = sorted(set(files_a) & set(files_b))
            only_a = sorted(set(files_a) - set(files_b))
            only_b = sorted(set(files_b) - set(files_a))

            total = len(common)
            results = []

            for i, rel in enumerate(common):
                if mode == MODE_TEXT:
                    r = compare_text_content(rel, files_a[rel], files_b[rel],
                                             self.name_a, self.name_b)
                else:
                    r = compare_one(rel, files_a[rel], files_b[rel],
                                    self.name_a, self.name_b)
                results.append(r)
                if (i + 1) % 20 == 0 or i == total - 1:
                    self._ui(lambda c=i+1, t=total: self.lbl_status.config(
                        text=f"已比较 {c}/{t} 个文件...", fg=color("yellow")))

            for rel in only_a:
                results.append({
                    "rel": rel, "consistent": False, "mode": mode,
                    "only_side": "a",
                    "lines_a": 0, "lines_b": 0,
                    "ids_a": 0, "ids_b": 0,
                    "only_a": [], "only_b": [],
                    "count_diff": [], "text_diff": [],
                    "ida_text": {}, "idb_text": {},
                })
            for rel in only_b:
                results.append({
                    "rel": rel, "consistent": False, "mode": mode,
                    "only_side": "b",
                    "lines_a": 0, "lines_b": 0,
                    "ids_a": 0, "ids_b": 0,
                    "only_a": [], "only_b": [],
                    "count_diff": [], "text_diff": [],
                    "ida_text": {}, "idb_text": {},
                })

            self.results = results
            self._ui(self._on_done)
        except Exception as e:
            msg = str(e)
            self._ui(lambda: self._on_error(msg))

    def _on_done(self):
        self.running = False
        self.btn_compare.config(state="normal", text="开始比较")
        self.lbl_status.config(text="比较完成", fg=color("green"))

        cons = sum(1 for r in self.results if r.get("consistent"))
        incon = sum(1 for r in self.results
                    if not r.get("consistent") and "only_side" not in r)
        only_a = sum(1 for r in self.results if r.get("only_side") == "a")
        only_b = sum(1 for r in self.results if r.get("only_side") == "b")

        self.lbl_stat.config(
            text=f"一致 {cons}  |  不一致 {incon}  |  仅 {self.name_a} {only_a}  |  仅 {self.name_b} {only_b}")
        self._log(f"对比完成: 一致 {cons} | 不一致 {incon} | 仅 {self.name_a} {only_a} | 仅 {self.name_b} {only_b}", "ok")
        self._refresh_tree()

    def _on_error(self, msg: str):
        self.running = False
        self.btn_compare.config(state="normal", text="开始比较")
        self.lbl_status.config(text="出错", fg=color("red"))
        messagebox.showerror("比较出错", msg)

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._hide_detail()
        filt = self.filter_var.get()
        mode = self.mode_var.get()
        is_text = (mode == MODE_TEXT)

        for i, r in enumerate(self.results):
            if "only_side" in r:
                side = r["only_side"]
                if filt == "仅 A 有" and side != "a":
                    continue
                if filt == "仅 B 有" and side != "b":
                    continue
                if filt not in ("全部", "有差异", "仅 A 有", "仅 B 有"):
                    continue
                label = self.name_a if side == "a" else self.name_b
                tag = "only"
                vals = (r["rel"], f"仅{label}", "-", "-")
            elif r["consistent"]:
                if filt not in ("全部", "一致"):
                    continue
                tag = "ok"
                if is_text:
                    vals = (r["rel"], "✓", "0",
                            f"A:{r['ids_a']} / B:{r['ids_b']}")
                else:
                    vals = (r["rel"], "✓", f"A:{r['lines_a']} / B:{r['lines_b']}",
                            f"A:{r['ids_a']} / B:{r['ids_b']}")
            else:
                if is_text:
                    if filt not in ("全部", "有差异", "文本不同"):
                        continue
                    # 进一步筛选
                    only_a = len(r.get("only_a", []))
                    only_b = len(r.get("only_b", []))
                    text_d = len(r.get("text_diff", []))
                    if filt == "文本不同" and text_d == 0:
                        # "文本不同" = ID 相同但文本不同（不含 only 侧）
                        if only_a == 0 and only_b == 0:
                            continue
                        # still want to check: if only text_diff > 0
                    total_diff = only_a + only_b + text_d
                    tag = "diff"
                    vals = (r["rel"], "✗", str(total_diff),
                            f"A:{r['ids_a']} / B:{r['ids_b']}")
                else:
                    if filt not in ("全部", "不一致"):
                        continue
                    tag = "diff"
                    vals = (r["rel"], "✗", f"A:{r['lines_a']} / B:{r['lines_b']}",
                            f"A:{r['ids_a']} / B:{r['ids_b']}")

            self.tree.insert("", "end", iid=str(i), values=vals, tags=(tag,))

    def _on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self.results):
            return
        r = self.results[idx]
        if r.get("consistent") or "only_side" in r:
            return

        if r.get("mode") == "text":
            detail = build_full_text_detail(r, self.name_a, self.name_b) or "无差异"
        else:
            detail = build_full_detail(r, self.name_a, self.name_b) or "无差异"
        self._show_detail_popup(r["rel"], detail)

    def _on_row_select(self, event):
        """选中行: 有差异则显示详情栏 (第一行统计 + 缩进差异 id 列表), 否则隐藏."""
        sel = self.tree.selection()
        if not sel or not self._detail_text:
            self._hide_detail()
            return
        idx = int(sel[0])
        if idx >= len(self.results):
            self._hide_detail()
            return
        r = self.results[idx]

        # 仅"不一致"(非仅单侧、非一致) 才显示详情栏
        if "only_side" in r or r.get("consistent"):
            self._hide_detail()
            return

        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", "end")

        # 第一行: 文件 + 状态 + ID 数 (精准)
        self._detail_text.insert("1.0",
            f"[ {r['rel']} ] ✗ 不一致  ID 数: A={r['ids_a']} B={r['ids_b']}\n")

        # 缩进差异 id 列表
        lines = []
        if r.get("only_a"):
            lines.append(f"\n仅 {self.name_a} 有的 id ({len(r['only_a'])} 个):")
            for iid in r["only_a"]:
                lines.append(f"    {iid}")
        if r.get("only_b"):
            lines.append(f"\n仅 {self.name_b} 有的 id ({len(r['only_b'])} 个):")
            for iid in r["only_b"]:
                lines.append(f"    {iid}")
        if r.get("text_diff"):
            lines.append(f"\n文本不同的 id ({len(r['text_diff'])} 个):")
            for iid, ta, tb in r["text_diff"]:
                lines.append(f"    {iid}")
        if r.get("count_diff"):
            lines.append(f"\n出现次数不同的 id ({len(r['count_diff'])} 个):")
            for iid, ca, cb in r["count_diff"]:
                lines.append(f"    {iid}")
        if lines:
            self._detail_text.insert("end", "\n".join(lines))

        self._detail_text.config(state="disabled")
        self._show_detail()

    def _show_detail(self):
        """显示详情栏 (加入筛选框内部 paned, 与表格之间可拖拽分隔)."""
        try:
            if str(self.detail_frame) not in self._inner.panes():
                self._inner.add(self.detail_frame, weight=2)
        except Exception:
            pass

    def _hide_detail(self):
        """隐藏详情栏."""
        try:
            if str(self.detail_frame) in self._inner.panes():
                self._inner.forget(self.detail_frame)
        except Exception:
            pass


    def _export(self):
        """导出当前筛选视图到 CSV 文件（UTF-8 BOM，Excel 兼容）。"""
        if not self.results:
            messagebox.showinfo("提示", "没有可导出的数据，请先运行比较。")
            return

        path = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=f"xml_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return

        filt = self.filter_var.get()
        mode = self.mode_var.get()
        is_text = (mode == MODE_TEXT)
        na, nb = self.name_a, self.name_b

        rows = []
        for r in self.results:
            if "only_side" in r:
                side = r["only_side"]
                if filt == "仅 A 有" and side != "a":
                    continue
                if filt == "仅 B 有" and side != "b":
                    continue
                if filt not in ("全部", "有差异", "仅 A 有", "仅 B 有"):
                    continue
                label = na if side == "a" else nb
                rows.append((r["rel"], f"仅{label}", "-", "-", "-", "-", "文件仅在一侧存在"))
            elif r["consistent"]:
                if filt not in ("全部", "一致"):
                    continue
                if is_text:
                    rows.append((r["rel"], "一致", "0",
                                 str(r["ids_a"]), str(r["ids_b"]), ""))
                else:
                    rows.append((r["rel"], "一致",
                                 str(r["lines_a"]), str(r["lines_b"]),
                                 str(r["ids_a"]), str(r["ids_b"]), ""))
            else:
                if is_text:
                    if filt not in ("全部", "有差异", "文本不同", "仅 A 有", "仅 B 有"):
                        continue
                    detail = build_full_text_detail(r, na, nb).replace("\n", "；")
                    only_a = len(r.get("only_a", []))
                    only_b = len(r.get("only_b", []))
                    text_d = len(r.get("text_diff", []))
                    total_diff = only_a + only_b + text_d
                    rows.append((r["rel"], "不一致",
                                 str(total_diff),
                                 str(r["ids_a"]), str(r["ids_b"]),
                                 detail))
                else:
                    if filt not in ("全部", "不一致"):
                        continue
                    detail = build_full_detail(r, na, nb).replace("\n", "；")
                    rows.append((r["rel"], "不一致",
                                 str(r["lines_a"]), str(r["lines_b"]),
                                 str(r["ids_a"]), str(r["ids_b"]),
                                 detail))

        if not rows:
            messagebox.showinfo("提示", "当前筛选条件下没有数据可导出。")
            return

        cons = sum(1 for r in self.results if r.get("consistent"))
        incon = sum(1 for r in self.results if not r.get("consistent") and "only_side" not in r)
        oa = sum(1 for r in self.results if r.get("only_side") == "a")
        ob = sum(1 for r in self.results if r.get("only_side") == "b")

        import csv
        import io
        buf = io.StringIO()
        buf.write("\ufeff")
        w = csv.writer(buf)

        w.writerow(["XML 比较报告"])
        w.writerow([f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
        w.writerow([f"比较模式: {mode}"])
        w.writerow([f"文件夹 A: {self.entry_a_var.get().strip()}"])
        w.writerow([f"文件夹 B: {self.entry_b_var.get().strip()}"])
        w.writerow([f"筛选条件: {filt}"])
        w.writerow([f"一致: {cons} | 不一致: {incon} | 仅 {na}: {oa} | 仅 {nb}: {ob}"])
        w.writerow([])

        if is_text:
            w.writerow(["文件", "状态", "差异 ID 数", "A ID 总数", "B ID 总数", "差异详情"])
        else:
            w.writerow(["文件", "状态", "A 行数", "B 行数", "A ID 数", "B ID 数", "差异详情"])

        for row in rows:
            w.writerow(row)

        Path(path).write_text(buf.getvalue(), encoding="utf-8")
        messagebox.showinfo("导出完成", f"已导出 {len(rows)} 行到:\n{path}")

    def _show_detail_popup(self, filename: str, detail: str):
        win = tk.Toplevel(self.root)
        win.title(f"差异详情 — {filename}")
        win.geometry("650x450")
        win.minsize(400, 250)

        from tkinter import Text as TkText
        text = LogBox(win, wrap="word", scrollbar=False,
                      tags=[("diff", "red"), ("ok", "green"),
                            ("only", "orange")])
        text.pack(fill="both", expand=True)
        text.insert("1.0", detail)
        text.config(state="disabled")

        tk.Button(win, text="关闭", font=self.font_ui, command=win.destroy, width=10).pack(pady=(0, 8))

    def _on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ═══ 视频OGM ═══
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

from toolkit import SplitPane, PluginManager
# ═══ 文件系统 ═══
import stalker_fs
from stalker_fs import (FORMATS, pack_db, unpack_db, extract_file, auto_detect,
                         load_db, sqfs_check, sqfs_list, sqfs_extract, sqfs_pack)
ALL_FMTS = {**FORMATS, "sqfs": {"name": "SquashFS", "key": "sq", "scrambler": None, "pack": False}}
FMT_KEYS = ["auto"] + list(ALL_FMTS.keys())

def _is_db(p):
    n = os.path.basename(p).lower(); d = n.rfind("."); return d >= 0 and n[d:d+3] == ".db"
def _is_sq(p):
    n = os.path.basename(p).lower(); d = n.rfind("."); return d >= 0 and n[d:d+3] == ".sq"


class Node:
    """In-memory tree node."""
    __slots__ = ("name", "path", "is_dir", "size", "offset", "checked", "children", "source")
    def __init__(self, name, path, is_dir, size=0, offset=0):
        self.name = name; self.path = path; self.is_dir = is_dir; self.size = size
        self.offset = offset; self.checked = False; self.children = {}; self.source = None

    def add(self, child): self.children[child.name] = child

    def merge(self, other):
        for name, child in other.children.items():
            if name in self.children:
                cur = self.children[name]
                if cur.is_dir and child.is_dir: cur.merge(child)
            else:
                self.children[name] = child

    def toggle(self, checked):
        self.checked = checked
        if self.is_dir:
            for c in self.children.values(): c.toggle(checked)

    def dir_state(self):
        """None=unchecked, False=partial, True=all checked. Empty dirs use own flag."""
        if not self.children: return True if self.checked else None
        vals = []
        for c in self.children.values():
            if c.is_dir:
                v = c.dir_state()
                vals.append(False if v is None else (True if v is True else False))
            else:
                vals.append(c.checked)
        if not any(vals): return None
        if all(vals): return True
        return False

    def collect(self, out):
        if not self.is_dir:
            if self.checked and self.source: out.append(self)
        elif not self.children and self.checked:
            out.append(self)
        else:
            for c in self.children.values(): c.collect(out)



class FSToolApp:
    def __init__(self, master=None):
        self.root = master or _BaseTk()
        if master is None:
            self.root.title("STALKER X-Ray FS Tool")
            self.root.geometry("1100x800"); self.root.minsize(900, 600)
        self.root.configure(bg=color("bg"))
        apply_theme()
        self.fmt_var = tk.StringVar(value="auto")
        self.input_var = tk.StringVar(); self.output_var = tk.StringVar()
        self._last_input = ""
        self.db_files = []; self.files_data = []
        self.loaded = {}; self.raws = {}; self.merged = None
        self.plugins = PluginManager(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins"),
            log=self._log_plugin,
        )
        self.plugins.scan()
        self.running = False
        self._build_ui()
        self._ui = _make_pump(self.root)
        self.input_var.trace_add("write", self._on_input_change)

    # ═══ Theme ═══
    def _setup_theme(self):
        """统一配色模板: 全部由 apply_theme 提供."""
        apply_theme()
    # ═══ UI ═══
    def _build_ui(self):
        self.fmt_keys = ["auto"] + list(ALL_FMTS.keys()) + [f["name"] for f in self.plugins.formats]
        self.pack_fmt_keys = [k for k in self.fmt_keys if k != "auto"]
        P = 14
        tool_header(self.root, "STALKER X-Ray FS Tool")
        top = ttk.Frame(self.root); top.pack(fill="x", padx=P, pady=(0,4))
        ttk.Label(top, text="格式", width=4).pack(side="left")
        cb = tk.OptionMenu(top, self.fmt_var, *self.fmt_keys)
        cb.configure(bg=color("surface2"), fg=color("text"), activebackground=color("selected"),
                     activeforeground=color("text_bright"), font=color("font"), relief="flat", highlightthickness=0)
        cb["menu"].configure(bg=color("surface2"), fg=color("text"), font=color("font"),
                             activebackground=color("selected"), activeforeground=color("text_bright"))
        cb.pack(side="left", padx=(4,8))
        self.fmt_desc = ttk.Label(top, text="自动检测", style="Dim.TLabel"); self.fmt_desc.pack(side="left")
        self.fmt_var.trace_add("write", self._on_fmt_change)
        ttk.Button(top, text="解包选中", command=self._unpack_checked).pack(side="right", padx=(4,0))
        ttk.Button(top, text="批量解包", command=self._unpack_batch).pack(side="right")

        for label, var, cmd, drop in [
            ("输入", self.input_var, self._browse_input, self._on_drop_input),
            ("输出", self.output_var, self._browse_output, self._on_drop_output)]:
            # 统一目录行 (toolkit.dir_row): 标签+输入框+浏览+拖拽
            dir_row(self.root, label, var, browse=cmd, drop=drop)

        pg = ttk.Frame(self.root); pg.pack(fill="x", padx=P, pady=(4, 2))
        self.progress = ttk.Progressbar(pg, mode="indeterminate")
        self.progress.pack(fill="x")
        self.status_lbl = ttk.Label(pg, text="就绪", style="Dim.TLabel", font=color("font_sm")); self.status_lbl.pack(anchor="w")

        outer = SplitPane(self.root, orient="vertical")
        outer.pack(fill="both", expand=True, padx=P, pady=(0,2))
        pan = SplitPane(outer, orient="horizontal")
        outer.add(pan, weight=3)
        self._build_db_panel(pan)
        self._build_file_panel(pan)
        self._build_pack_panel(outer)
        self.log_lf, self.log = log_section(self.root, "日志", height=4)

    def _build_db_panel(self, pan):
        left = ttk.LabelFrame(pan, text="DB 文件列表", padding=4)
        pan.add(left, weight=1)
        bar = ttk.Frame(left); bar.pack(fill="x", pady=(0,2))
        ttk.Button(bar, text="扫描目录", width=8, command=self._scan_dir).pack(side="left")
        ttk.Button(bar, text="全选", width=5, command=self._select_all_db).pack(side="left", padx=(4,0))
        ttk.Button(bar, text="加载选中", width=8, command=self._load_selected).pack(side="left", padx=(4,0))
        ttk.Button(bar, text="取消加载", width=8, command=self._unload_selected).pack(side="left", padx=(4,0))
        ttk.Button(bar, text="移除", width=5, command=self._remove_db).pack(side="left", padx=(4,0))
        ttk.Button(bar, text="清空", width=5, command=self._clear_db).pack(side="left", padx=(4,0))
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
        for mi in self.plugins.menu_items:
            self.db_ctree._ctx.add_separator()
            self.db_ctree._ctx.add_command(label=mi["label"], command=mi["callback"])

    def _build_file_panel(self, pan):
        right = ttk.LabelFrame(pan, text="包内文件", padding=4)
        pan.add(right, weight=2)
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
        parent.add(pf, weight=1)
        # Row 1: format + output + pack button
        row1 = ttk.Frame(pf); row1.pack(fill="x", pady=(0,2))
        ttk.Label(row1, text="格式", width=4).pack(side="left")
        self.pack_fmt_var = tk.StringVar(value="xdb")
        pk = tk.OptionMenu(row1, self.pack_fmt_var, *self.pack_fmt_keys)
        pk.configure(bg=color("surface2"), fg=color("text"), activebackground=color("selected"),
                     activeforeground=color("text_bright"), font=color("font"), relief="flat", highlightthickness=0)
        pk["menu"].configure(bg=color("surface2"), fg=color("text"), font=color("font"),
                              activebackground=color("selected"), activeforeground=color("text_bright"))
        pk.pack(side="left", padx=(4,8))
        ttk.Label(row1, text="输出", width=4).pack(side="left")
        self.pack_out_var = tk.StringVar()
        pe = ttk.Entry(row1, textvariable=self.pack_out_var, font=color("font_mono"))
        pe.pack(side="left", fill="x", expand=True, padx=(4,4))
        if _HAS_DND:
            pe.drop_target_register(DND_FILES)
            pe.dnd_bind("<<Drop>>", self._on_drop_pack_out)
        ttk.Button(row1, text="浏览", width=6, command=self._browse_pack_out).pack(side="left")
        ttk.Button(row1, text="封包", width=6, command=self._pack, style="Accent.TButton").pack(side="left", padx=(4,0))
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

    # ═══ Model ═══
    def _build_model(self, entries, src):
        """Build file tree from archive entries (DB or plain SquashFS).
        src = package path; per-file source/offset/size for extraction."""
        root = _Node("", "", True)
        for e in entries:
            parts = e["path"].replace("\\", "/").split("/")
            n = root
            for i, part in enumerate(parts):
                is_dir = (i < len(parts) - 1) or e["is_dir"]
                if part not in n.children:
                    n.add(_Node(part, "/".join(parts[:i + 1]), is_dir,
                               0 if is_dir else e["size_real"],
                               0 if is_dir else e["offset"]))
                n = n.children[part]
            if not n.is_dir:
                n.source = src; n.offset = e["offset"]; n.size = e["size_real"]
                n.size_comp = e.get("size_comp", e["size_real"])
                n.use_lzhuf = e.get("use_lzhuf", False)
        return root

    def _rebuild_merged(self):
        self.merged = _Node("", "", True)
        for root in self.loaded.values(): self.merged.merge(root)

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

    def _scan_dir(self, d=None):
        d = d or self.input_var.get().strip()
        if not d or not os.path.isdir(d): return
        self._log(f"扫描 {d} ...", "dim"); added = 0
        for f in Path(d).rglob("*"):
            if f.is_file() and (_is_db(str(f)) or _is_sq(str(f))):
                sf = str(f)
                if sf not in self.db_files: self.db_files.append(sf); added += 1
        self.db_files.sort(key=lambda x: os.path.basename(x).lower())
        self._refresh_db_list(); self._log(f"新增 {added} 个, 共 {len(self.db_files)} 个", "ok")

    def _refresh_db_list(self):
        """DB list = CanvasTree, each DB a single checkable leaf item."""
        root = _Node("", "", True)
        for f in self.db_files:
            n = _Node(os.path.basename(f), f, False)
            n.size = os.path.getsize(f)
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
        """Check/uncheck a DB: auto-load if needed, then toggle its files."""
        db = node.source
        if db not in self.loaded:
            self._load(db)
        if db in self.loaded:
            st = self.loaded[db].dir_state()
            self.loaded[db].toggle(st is not True)
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    def _db_click(self, node):
        """DB row click: selection only — do NOT toggle check on plain click
        (toggle happens via checkbox hit only; presence here also prevents the
        default leaf-click toggle path)."""
        pass

    def _remove_db(self):
        doomed = set(self.db_ctree.get_selected_paths())
        if not doomed: return
        for f in doomed:
            if f in self.db_files:
                self.db_files.remove(f)
                self.loaded.pop(f, None); self.raws.pop(f, None)
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    def _clear_db(self):
        self.db_files = []; self.loaded.clear(); self.raws.clear(); self.merged = None
        self._refresh_db_list(); self._render()

    def _select_all_db(self):
        """Select all DB rows."""
        self.db_ctree.select_all()

    def _load_all_checked(self):
        """Load all DB files AND check all their contents (used after drag-drop)."""
        self.loaded.clear(); self.raws.clear()
        for f in self.db_files:
            self._load(f)
        for root in self.loaded.values():
            root.toggle(True)
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    def _load_selected(self):
        """Load SELECTED (not checked) DB packages; check state untouched."""
        for node in self.db_ctree._sel:
            db = node.source
            if db not in self.loaded:
                self._load(db)
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    def _unload_selected(self):
        """Unload SELECTED (not checked) DB packages; check state untouched."""
        for node in self.db_ctree._sel:
            db = node.source
            if db in self.loaded:
                del self.loaded[db]; del self.raws[db]
        self._rebuild_merged(); self._render(); self._refresh_db_list()

    # ═══ Load ═══
    def _load_nlc(self, path):
        """NLC encrypted sq_base: use PluginManager decryptor first,
        fall back to nlc_sqfs module. raws[path] = b'DEC:' + temp_path."""
        decrypt = None
        try:
            entry = self.plugins.find_decryptor(path) if getattr(self, "plugins", None) else None
            if entry:
                decrypt = entry["decrypt"]
        except Exception:
            pass
        if decrypt is None:
            try:
                import nlc_sqfs
                decrypt = nlc_sqfs.decrypt_sq
            except ImportError:
                self._log("  NLC 解密需要 nlc_sqfs.py 插件 (plugins 目录)", "warn")
                return
        try:
            dec = decrypt(path)
            if not dec or dec[:4] != b"hsqs":
                self._log("  NLC 解密失败 (非 hsqs 魔数)", "err")
                return
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".sqfs", delete=False)
            tf.write(dec); tf.close()
            entries = sqfs_list(tf.name)
            if not entries:
                self._log("  NLC 解密后解析失败", "err")
                try: os.unlink(tf.name)
                except: pass
                return
            self.raws[path] = b"DEC:" + tf.name.encode()
            self.loaded[path] = self._build_model(entries, path)
            nf = sum(1 for e in entries if not e["is_dir"])
            self._log(f"  NLC 解密: {len(entries)} 条, {nf} 文件", "ok")
        except Exception as e:
            self._log(f"  NLC 解密错误: {e}", "err")


    @staticmethod
    def _dec_path(raw):
        """NLC 解密临时文件路径 (raws 值为 b'DEC:...' 时), 否则 None."""
        if isinstance(raw, bytes) and raw.startswith(b"DEC:"):
            return raw[4:].decode()
        return None

    def _load(self, path):
        fmt = self.fmt_var.get()
        self._log(f"浏览: {os.path.basename(path)} ({fmt})", "dim")
        if _is_sq(path):
            kind = sqfs_check(path)
            if kind == "sqfs":
                entries = sqfs_list(path)
                if entries:
                    self.raws[path] = b"SQFS"  # marker: extraction via rdsquashfs
                    self.loaded[path] = self._build_model(entries, path)
                    nf = sum(1 for e in entries if not e["is_dir"])
                    self._log(f"  SquashFS: {len(entries)} 项, {nf} 文件", "ok")
                else:
                    self._log("  SquashFS 列表失败 (缺 rdsquashfs?) ", "err")
            elif kind == "nlc":
                self._load_nlc(path)
            else:
                self._log("  无法识别 .sq 文件", "warn")
            return
        raw = load_db(path)
        if fmt == "auto": fmt = auto_detect(raw)
        if not fmt or fmt == "sqfs": self._log("  无法自动识别格式", "warn"); return
        plugin_fmt = next((f for f in self.plugins.formats if f["name"] == fmt), None)
        if plugin_fmt:
            entries = plugin_fmt["handler"]["unpack"](raw)
        else:
            entries = unpack_db(raw, fmt)
        self.raws[path] = raw
        self.loaded[path] = self._build_model(entries, path)
        nf = sum(1 for e in entries if not e["is_dir"])
        self._log(f"  {fmt}: {len(entries)} 项, {nf} 文件", "ok")

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
            desc = (pf or {}).get("description", "") or fmt
        self.fmt_desc.configure(text=desc)

    def _on_input_change(self, *a):
        p = self.input_var.get().strip()
        if p != self._last_input:
            self._last_input = p
            self.output_var.set("")  # 输入变化即清空输出
        if p and os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
            self._add_db(p); self._load_all_checked()

    def _on_drop_input(self, e):
        paths = self.root.tk.splitlist(e.data)
        if not paths: return
        # 输入目录同步为拖入的第一个路径
        self.input_var.set(paths[0])
        if len(paths) == 1:
            if os.path.isfile(paths[0]) and (_is_db(paths[0]) or _is_sq(paths[0])):
                return  # trace (_on_input_change) 会自动加载单文件
            if os.path.isdir(paths[0]):
                self._scan_dir(paths[0])
                self._load_all_checked()
            return
        for p in paths:
            if os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
                self._add_db(p)
            elif os.path.isdir(p):
                self._scan_dir(p)
        self._load_all_checked()

    def _on_drop_db_list(self, e):
        """Drop onto DB list: collect archive files, then auto-load+check all."""
        for p in self.root.tk.splitlist(e.data):
            if os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
                self._add_db(p)
            elif os.path.isdir(p):
                self._scan_dir(p)
        self._load_all_checked()

    def _on_drop_pack_list(self, e):
        """Drop onto pack list: folders recurse, archives excluded."""
        for p in self.root.tk.splitlist(e.data):
            if os.path.isdir(p):
                self._add_dir(p)
            elif os.path.isfile(p) and not self._is_pack_file(p):
                self._add_files([p])
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
            self._scan_dir(p); self._load_all_checked()

    def _browse_output(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p: self.output_var.set(p)

    # ─── Pack ───
    @staticmethod
    def _is_pack_file(p):
        """True if file is an archive (.db* / .sq*) — excluded from packing."""
        return _is_db(p) or _is_sq(p)

    def _add_files(self, paths=None):
        """Add files to pack list. Non-archive files only."""
        if paths is None:
            paths = filedialog.askopenfilenames(title="选择文件 (非包文件)")
        base = Path(self.input_var.get()) if self.input_var.get() and os.path.isdir(self.input_var.get()) else Path(".")
        for p in paths:
            if not os.path.isfile(p) or self._is_pack_file(p): continue
            try: rel = str(Path(p).relative_to(base)).replace("\\", "/")
            except: rel = Path(p).name
            if rel in [x[0] for x in self.files_data]: continue
            with open(p, "rb") as f: self.files_data.append((rel, f.read(), False))
        self._refresh_pack()

    def _add_dir(self, d=None):
        """Recursively add a folder's non-archive files. Folder name kept as top dir
        unless input dir is set as pack root."""
        if d is None:
            d = filedialog.askdirectory(title="选择目录 (递归, 排除包文件)")
        if not d or not os.path.isdir(d): return
        # Pack root: input dir if set; else the dropped folder's PARENT so the
        # folder itself shows as a top-level node.
        if self.input_var.get() and os.path.isdir(self.input_var.get()):
            base = Path(self.input_var.get())
        else:
            base = Path(d).parent
        count = 0
        for f in sorted(Path(d).rglob("*")):
            if not f.is_file() or self._is_pack_file(str(f)): continue
            try: rel = str(f.relative_to(base)).replace("\\", "/")
            except: continue
            if rel in [x[0] for x in self.files_data]: continue
            with open(f, "rb") as fh: self.files_data.append((rel, fh.read(), False))
            count += 1
        self._refresh_pack()
        self._log(f"目录添加: {count} 个文件 (排除包文件)", "dim")

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

    def _pack(self):
        if self.running: return
        if not self.files_data: messagebox.showwarning("无文件", "请先添加文件"); return
        fmt = self.pack_fmt_var.get()
        out = self.pack_out_var.get().strip()
        ext = ".sqfs" if fmt == "sqfs" else f".{fmt}.db"
        if not out:
            out = filedialog.asksaveasfilename(title="保存", defaultextension=ext)
            if not out: return; self.pack_out_var.set(out)
        else:
            out = os.path.join(out, f"packed{ext}")
        self.running = True; self._log(f"封包 ({fmt})...", "hdr"); self.progress.start(10)
        self.status_lbl.configure(text="封包中...")
        def work():
            try:
                if fmt == "sqfs":
                    ok = sqfs_pack(self.files_data, out)
                    if not ok: raise RuntimeError("SquashFS 封包失败 (缺 tar2sqfs?)")
                    self._log(f"完成: SquashFS → {out}", "ok")
                else:
                    plugin_fmt = next((f for f in self.plugins.formats if f["name"] == fmt), None)
                    if plugin_fmt:
                        db = plugin_fmt["handler"]["pack"](self.files_data)
                    else:
                        db = pack_db(self.files_data, fmt)
                    with open(out, "wb") as f: f.write(db)
                    self._log(f"完成: {len(db)} 字节 → {out}", "ok")
                self._ui(lambda: self.status_lbl.configure(text="完成", foreground=color("green")))
            except Exception as e: self._log(f"封包错误: {e}", "err")
            self._ui(self._done)
        threading.Thread(target=work, daemon=True).start()

    # ═══ Unpack ═══
    @staticmethod
    def _package_folder(db_path):
        """gamedata.db0 / gamedata.sq_base -> 'gamedata'"""
        return os.path.splitext(os.path.basename(db_path))[0]

    def _resolve_output(self):
        out = self.output_var.get().strip()
        if not out:
            if self.db_files: out = os.path.dirname(self.db_files[0])
            elif self.input_var.get(): p = self.input_var.get().strip(); out = os.path.dirname(p) if os.path.isfile(p) else p
            else: out = os.getcwd()
            self.output_var.set(out)
        return out

    def _unpack_checked(self):
        if self.running: return
        nodes = []
        if self.merged: self.merged.collect(nodes)
        if not nodes: messagebox.showwarning("无勾选", "没有打勾的文件"); return
        out = self._resolve_output()
        if not messagebox.askokcancel("解包选中", f"输出到:\n{out}\n\n共 {len(nodes)} 项"): return
        self.running = True; self._log(f"解包 {len(nodes)} 项...", "hdr")
        self.progress.configure(mode="determinate", maximum=len(nodes), value=0)
        self.status_lbl.configure(text="解包中...")
        def work():
            made = set()
            try:
                # Group by source: sqfs sources use rdsquashfs, db sources use raw bytes
                sqfs_src = {n.source for n in nodes
                            if self.raws.get(n.source) == b"SQFS"
                            or self._dec_path(self.raws.get(n.source))}
                for src in sqfs_src:
                    sp = src if self.raws.get(src) == b"SQFS" else self._dec_path(self.raws.get(src))
                    sqfs_extract(sp, os.path.join(out, self._package_folder(src)),
                                 [{"path": n.path} for n in nodes if n.source == src and not n.is_dir])
                for i, n in enumerate(nodes):
                    pkg = self._package_folder(n.source) if n.source else ""
                    rel = n.path.replace("/", os.sep)
                    p = os.path.join(out, pkg, rel)
                    raw = self.raws.get(n.source)
                    if raw == b"SQFS" or self._dec_path(raw):
                        continue  # already handled by sqfs_extract batch above
                    if n.is_dir:
                        os.makedirs(p, exist_ok=True)
                        made.add(p)
                    else:
                        raw = self.raws.get(n.source)
                        if raw:
                            data = extract_file(raw, {"offset": n.offset, "size_real": n.size, "size_comp": n.size_comp, "is_dir": False})
                            if data:
                                d = os.path.dirname(p)
                                if d not in made:
                                    os.makedirs(d, exist_ok=True)
                                    made.add(d)
                                with open(p, "wb") as f: f.write(data)
                    self._ui(lambda v=i+1: self.progress.configure(value=v))
                self._log(f"完成: {len(nodes)} 项", "ok")
                self._ui(lambda: self.status_lbl.configure(text=f"完成: {len(nodes)} 项", foreground=color("green")))
            except Exception as e: self._log(f"错误: {e}", "err")
            self._ui(self._done)
        threading.Thread(target=work, daemon=True).start()

    def _unpack_batch(self):
        if self.running: return
        if not self.loaded: messagebox.showwarning("无加载", "请先加载包"); return
        out = self._resolve_output()
        if not messagebox.askokcancel("批量解包", f"输出到:\n{out}\n\n共 {len(self.loaded)} 个已加载包"): return
        fmt = self.fmt_var.get(); self.running = True
        self._log(f"批量解包 {len(self.loaded)} 个包...", "hdr")
        self.progress.configure(mode="determinate", maximum=len(self.loaded), value=0)
        def work():
            ok = tf = 0
            for idx, (db_path, root) in enumerate(self.loaded.items()):
                raw = self.raws.get(db_path)
                pkg = self._package_folder(db_path)
                self._ui(lambda i=idx: self.status_lbl.configure(text=f"[{i+1}/{len(self.loaded)}] {os.path.basename(db_path)}"))
                if not raw: continue
                try:
                    raw2 = self.raws.get(db_path)
                    dp = self._dec_path(raw2)
                    if raw2 == b"SQFS":
                        sqfs_extract(db_path, os.path.join(out, pkg))
                        ok += 1
                        self._log(f"  {os.path.basename(db_path)} → {pkg}/: SquashFS 全解", "dim")
                        continue
                    if dp:
                        sqfs_extract(dp, os.path.join(out, pkg))
                        ok += 1
                        self._log(f"  {os.path.basename(db_path)} → {pkg}/: NLC 解密全解", "dim")
                        continue
                    nodes = []; root.collect(nodes)
                    files = [n for n in nodes if not n.is_dir]
                    made = set()
                    for n in files:
                        data = extract_file(raw, {"offset": n.offset, "size_real": n.size, "size_comp": n.size_comp, "is_dir": False})
                        if data:
                            p = os.path.join(out, pkg, n.path.replace("/", os.sep))
                            d = os.path.dirname(p)
                            if d not in made:
                                os.makedirs(d, exist_ok=True)
                                made.add(d)
                            with open(p, "wb") as f: f.write(data)
                    ok += 1; tf += len(files)
                    self._log(f"  {os.path.basename(db_path)} → {pkg}/: {len(files)} 文件", "dim")
                except Exception as ex: self._log(f"  {os.path.basename(db_path)}: 错误 {ex}", "err")
                self._ui(lambda v=idx+1: self.progress.configure(value=v))
            self._log(f"完成: {ok}/{len(self.loaded)} 个包, 共 {tf} 文件", "ok")
            self._ui(lambda: self.status_lbl.configure(text=f"完成: {tf} 文件", foreground=color("green")))
            self._ui(self._done)
        threading.Thread(target=work, daemon=True).start()

    # ═══ Util ═══
    @staticmethod
    def _fmt_size(sz):
        if sz >= 1048576: return f"{sz/1048576:.1f} MB"
        if sz >= 1024: return f"{sz/1024:.1f} KB"
        return f"{sz} B"

    def _log(self, msg, tag="info"):
        self._ui(lambda: self.log.add(msg, tag))
    def _log_plugin(self, msg, tag="info"):
        """PluginManager log sink (may be called before _ui is ready)."""
        try:
            self._log(msg, tag)
        except Exception:
            pass
    def _done(self): self.running = False; self.progress.stop(); self.progress.configure(mode="indeterminate")
    def run(self):
        try:
            self.root.mainloop()
        finally:
            try:
                cleanup_sqfs_tools()
            except Exception:
                pass

# ═══ 汉化包生成 ═══
import font_pack
from font_pack import GAMES, ensure_pillow, build_package
# 汉化包生成 — 颜色常量 (单文件 T 映射)


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
            local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "msyh.ttf")
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
            messagebox.showerror("依赖缺失", "Pillow 安装失败，无法渲染字体"); return

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


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = _BaseTk()
    root.title("STALKER 汉化工具集")
    root.geometry("1280x860")
    root.minsize(1024, 700)
    root.configure(bg=T["bg"])
    apply_theme()
    apply_tk_defaults(root)

    TOOLS = [
        ("文件系统", FSToolApp),
        ("编码转换", ConvertApp),
        ("文本提取", TextExtractApp),
        ("XML校对", XMLCompareApp),
        ("视频转换", VideoOGMApp),
        ("汉化包生成", FontPackApp),
    ]

    def rebuild(nb, apps):
        for tab in nb.tabs():
            nb.forget(tab)
        apps.clear()
        for label, cls in TOOLS:
            tab = tk.Frame(nb, bg=color("bg"))
            nb.add(tab, text=label)
            try:
                apps[label] = cls(tab)
            except Exception as e:
                ttk.Label(tab, text=f"加载失败: {e}", style="Red.TLabel").pack(pady=30)
        apply_theme()

    def attach_log(apps, g_log):
        def hide(w):
            for c in w.winfo_children():
                if isinstance(c, LogBox) and getattr(c, "_log_role", False):
                    lf = c.master
                    pane = lf.master if lf is not None else None
                    panedw = pane.master if pane is not None else None
                    try:
                        if panedw is not None and panedw.winfo_class() == "TPanedwindow":
                            panedw.forget(pane)  # 移除整个日志 pane (无空背景/无用分隔条)
                        else:
                            (lf or c.master).pack_forget()
                    except Exception:
                        pass
                    return
                hide(c)
        for app in apps.values():
            if app is None:
                continue
            # 重定向到全局日志, 经 app._ui 泵保证线程安全
            if hasattr(app, "_ui") and callable(app._ui):
                if hasattr(app, "_log") and callable(app._log):
                    app._log = lambda msg, tag="info", a=app: a._ui(g_log.add, msg, tag)
                if hasattr(app, "log") and callable(app.log):
                    app.log = lambda msg, a=app: a._ui(g_log.add, msg)
            else:
                if hasattr(app, "_log") and callable(app._log):
                    app._log = lambda msg, tag="info": g_log.add(msg, tag)
                if hasattr(app, "log") and callable(app.log):
                    app.log = lambda msg: g_log.add(msg)
            hide(app.root)

    def build_hub(mode="dark"):
        """构建 hub 全部界面 (仅首次构建时销毁重建; 切主题只换色不重建)."""
        for w in root.winfo_children():
            w.destroy()
        apply_theme(mode)
        root.configure(bg=color("bg"))

        header = ttk.Frame(root)
        header.pack(fill="x", padx=14, pady=(12, 4))
        ttk.Label(header, text="STALKER 汉化工具集", style="Title.TLabel").pack(side="left")
        # 主题下拉框在右, 标签在其左侧
        theme_var = tk.StringVar(value="暗色" if mode == "dark" else "亮色")

        def on_theme(val):
            apply_theme("light" if val == "亮色" else "dark")
            root.configure(bg=color("bg"))
            refresh_theme(root)

        om = ttk.OptionMenu(header, theme_var, theme_var.get(), "暗色", "亮色", command=on_theme)
        om.pack(side="right")
        ttk.Label(header, text="主题:", style="Dim.TLabel").pack(side="right", padx=(0, 4))

        nb_paned = SplitPane(root, orient="vertical")
        nb_paned.pack(fill="both", expand=True, padx=10, pady=(4, 2))
        nb = ttk.Notebook(nb_paned)
        nb_paned.add(nb, weight=3)
        log_lf = ttk.LabelFrame(nb_paned, text="日志", padding=4)
        nb_paned.add(log_lf, weight=1)
        log_bar = ttk.Frame(log_lf); log_bar.pack(fill="x", pady=(0, 2))

        def export_log():
            """导出日志到 程序目录/logs/ (自动创建)."""
            try:
                g_log._flush()  # 先落盘 pending 缓冲日志
                logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
                os.makedirs(logs_dir, exist_ok=True)
                fn = os.path.join(logs_dir, f"log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(g_log.get("1.0", "end"))
                g_log.add(f"日志已导出: {fn}", "ok")
            except Exception as e:
                g_log.add(f"导出失败: {e}", "err")

        ttk.Button(log_bar, text="导出", width=6, command=export_log).pack(side="right")
        ttk.Label(log_bar, text="运行日志", style="Dim.TLabel").pack(side="left")
        g_log = LogBox(log_lf, height=6)
        apps = {}
        rebuild(nb, apps)
        attach_log(apps, g_log)

    build_hub("dark")
    root.mainloop()
