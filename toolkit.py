# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 公共组件库
统一着色 (亮/暗两套色板, 单函数 apply_theme(mode) 切换)、全局主题、
公用日志 LogBox、通用 CanvasTree 文件树。个性化设置只需改 THEMES。
"""
import os
import re
import time
import tkinter as tk
import subprocess
import sys

from tkinter import ttk, filedialog, messagebox

APP_NAME = "STALKER Localization Toolkit"
APP_VERSION = "1.0.0"


def app_dir():
    """可写应用目录：PyInstaller onedir 中为 exe 所在目录，开发环境为项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

# tkinterdnd2 可选 (拖拽)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BaseTk = TkinterDnD.Tk; _HAS_DND = True
except ImportError:
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "tkinterdnd2"],
                       capture_output=True, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        from tkinterdnd2 import DND_FILES, TkinterDnD
        _BaseTk = TkinterDnD.Tk; _HAS_DND = True
    except ImportError:
        _BaseTk = tk.Tk; _HAS_DND = False; DND_FILES = None

# ─── 色板 (唯一来源: 亮/暗两套, 样式代码共用同一函数) ───
THEMES = {
    "dark": {
        "bg": "#1e1e1e", "surface": "#252526", "surface2": "#2d2d2d",
        "border": "#6e7681", "accent": "#007acc", "accent_hover": "#1a8ad4",
        "text": "#cccccc", "text_dim": "#9d9d9d", "text_bright": "#e0e0e0",
        "green": "#4ec9b0", "red": "#f14c4c", "yellow": "#dcdcaa", "orange": "#ce9178",
        "entry_bg": "#3a3d41", "selected": "#264f78",
        "scroll_border": "#3a3d41",
        "sash": "#3a3d41", "sash_light": "#4a4d51",
    },
    "light": {
        "bg": "#f5f5f5", "surface": "#ececec", "surface2": "#e0e0e0",
        "border": "#909090", "accent": "#0a6cb8", "accent_hover": "#1a7fc9",
        "text": "#3a3a3a", "text_dim": "#6e6e6e", "text_bright": "#2b2b2b",
        "green": "#2e7d32", "red": "#d64545", "yellow": "#a08000", "orange": "#b06e3c",
        "entry_bg": "#fafafa", "selected": "#d6e7f5",
        "scroll_border": "#c0c0c0",
        "sash": "#c0c0c0", "sash_light": "#d8d8d8",
    },
}
# 字体 (两套共用, 放这里便于个性化)
_FONTS = {
    "font": ("Segoe UI", 12), "font_sm": ("Segoe UI", 11),
    "font_mono": ("Consolas", 11),
    "font_title": ("Segoe UI", 14, "bold"),
    "font_header": ("Segoe UI", 12, "bold"),
    "font_stats": ("Segoe UI", 20, "bold"),
}


def palette(mode="dark"):
    """取指定模式的完整色板 (含字体键), 默认暗色."""
    p = dict(THEMES.get(mode, THEMES["dark"]))
    p.update(_FONTS)
    return p


# 默认暗色色板 (兼容直接引用 toolkit.T 的既有代码)
T = palette("dark")

# 当前主题模式 (hub 切换后重建工具时, 工具内部 apply_theme() 沿用此模式)
CURRENT_MODE = "dark"


def user_config_path():
    """用户配置文件路径: 应用目录/user.ltx."""
    return os.path.join(app_dir(), "user.ltx")


def load_user_theme():
    """读取 user.ltx 中保存的主题, 缺省 dark."""
    try:
        with open(user_config_path(), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("mode"):
                    val = line.split("=", 1)[1].strip().lower()
                    if val in ("dark", "light"):
                        return val
    except Exception:
        pass
    return "dark"


def save_user_theme(mode):
    """保存主题到 user.ltx."""
    try:
        with open(user_config_path(), "w", encoding="utf-8") as f:
            f.write("[theme]\nmode = " + mode + "\n")
    except Exception:
        pass


def _hex_to_colorref(hex_color):
    """将 '#RRGGBB' 转为 Windows COLORREF (0x00BBGGRR)。"""
    try:
        s = hex_color.lstrip("#")
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return (b << 16) | (g << 8) | r
    except Exception:
        return None


def apply_titlebar(root, mode=None):
    """Windows 标题栏跟随主题：先切沉浸式明暗模式，再在 Win11 上设置
    与工具色板一致的标题栏背景/文字颜色。失败时静默忽略。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        if mode is None:
            mode = CURRENT_MODE
        # Tk 的 winfo_id() 返回的是客户区子窗口句柄，真正的顶层窗口
        # （带标题栏）是它的父窗口。对子窗口调用 DwmSetWindowAttribute
        # 会返回 ERROR_INVALID_HANDLE (0x80070006)，导致标题栏不变色。
        # 注意：窗口在 mainloop 前可能尚未完成映射，此时 GetParent 会
        # 返回 0，需要先 update_idletasks() 让顶层窗口创建完成。
        hwnd = root.winfo_id()
        user32 = ctypes.windll.user32
        top = user32.GetParent(hwnd)
        if not top:
            try:
                root.update_idletasks()
            except Exception:
                pass
            top = user32.GetParent(root.winfo_id())
        top = top or hwnd
        dwm = ctypes.windll.dwmapi
        value = 1 if mode == "dark" else 0
        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 = Windows 11/10 1903+;
        # 19 = 旧版 1903 之前。DwmSetWindowAttribute 失败时返回 HRESULT，
        # 不会抛 Python 异常，所以必须检查返回值并回退。
        hr = dwm.DwmSetWindowAttribute(
            top, 20, ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))
        if hr != 0:
            hr = dwm.DwmSetWindowAttribute(
                top, 19, ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))
        # Win11 22000+ 支持自定义标题栏颜色；旧系统上这些调用会返回
        # 非 0 HRESULT，静默忽略即可，上面已保证明暗模式生效。
        if hr == 0:
            P = palette(mode)
            bg_ref = _hex_to_colorref(P["bg"])
            text_ref = _hex_to_colorref(P["text"])
            border_ref = _hex_to_colorref(P["border"])
            if bg_ref is not None:
                # DWMWA_CAPTION_COLOR = 35, DWMWA_TEXT_COLOR = 36,
                # DWMWA_BORDER_COLOR = 34 (Windows 11)。
                dwm.DwmSetWindowAttribute(
                    top, 35, ctypes.byref(ctypes.c_int(bg_ref)), ctypes.sizeof(ctypes.c_int))
                if text_ref is not None:
                    dwm.DwmSetWindowAttribute(
                        top, 36, ctypes.byref(ctypes.c_int(text_ref)), ctypes.sizeof(ctypes.c_int))
                if border_ref is not None:
                    dwm.DwmSetWindowAttribute(
                        top, 34, ctypes.byref(ctypes.c_int(border_ref)), ctypes.sizeof(ctypes.c_int))
        if hr == 0:
            # 强制刷新非客户区，让 DWM 立即用新属性重绘标题栏。
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                top, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass

def _ico_to_photoimages(ico_path, sizes=(16, 24, 32, 48, 64)):
    """Extract several sizes from an .ico as tk.PhotoImage for crisp HiDPI icons."""
    try:
        import io
        import tkinter as tk
        from PIL import Image
        img = Image.open(ico_path)
        out = []
        for s in sizes:
            try:
                im = img.resize((s, s), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                out.append(tk.PhotoImage(data=buf.getvalue()))
            except Exception:
                continue
        return out or None
    except Exception:
        return None


def set_app_icon(win):
    """Set the window/taskbar icon to app_icon.ico (works in dev and PyInstaller).

    Uses iconphoto() with 16/24/32/48/64 px images so Windows can pick a crisp
    size for title bar and taskbar on HiDPI displays. Falls back to iconbitmap().
    """
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "app_icon.ico"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "app_icon.ico"))
    for p in candidates:
        if not os.path.isfile(p):
            continue
        imgs = _ico_to_photoimages(p)
        if imgs:
            try:
                win.iconphoto(True, *imgs)
                # Keep references alive for the lifetime of the window.
                win._toolkit_icons = imgs
                return True
            except Exception:
                pass
        try:
            win.iconbitmap(default=p)
            return True
        except Exception:
            continue
    return False


def log_to_file(msg, tag="error"):
    """Append a timestamped line to logs/runtime.log for tracing."""
    try:
        logs_dir = os.path.join(app_dir(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, "runtime.log")
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{tag}] {msg}\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


_BG_ROLES = ("bg", "surface", "surface2", "entry_bg", "selected")



def errbox(title, msg):
    """Error dialog that also writes into logs/runtime.log."""
    log_to_file(msg, "error")
    messagebox.showerror(title, msg)

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





# ─── 单函数主题模板: 亮/暗用同一套样式代码, mode 参数切换 ───
def apply_theme(mode=None):
    """统一主题模板 (唯一函数): 所有工具的配色/字体/控件样式由此函数配置.
    mode: "dark"/"light"; None 时沿用当前模式 (CURRENT_MODE).
    调用方: hub 启动/切换 + 各工具独立运行时."""
    global CURRENT_MODE, T
    if mode:
        CURRENT_MODE = mode
    P = palette(CURRENT_MODE)
    T.clear()
    T.update(P)
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    # 全局默认
    style.configure(".", background=P["bg"], foreground=P["text"],
                    fieldbackground=P["entry_bg"], borderwidth=0, font=P["font"])
    # 容器
    style.configure("TFrame", background=P["bg"])
    style.configure("Dark.TFrame", background=P["surface"])
    style.configure("TLabelframe", background=P["surface"], foreground=P["text_bright"],
                    bordercolor=P["border"], borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", background=P["surface"],
                    foreground=P["text_bright"], font=P["font_header"])
    # 标签
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
    # 按钮
    style.configure("TButton", background=P["surface2"], foreground=P["text"],
                    bordercolor=P["border"], relief="flat", padding=(12, 5), font=P["font"])
    style.map("TButton", background=[("active", P["accent"]), ("pressed", P["accent"])],
              foreground=[("active", "#fff"), ("pressed", "#fff")])
    style.configure("Accent.TButton", background=P["accent"], foreground="#fff",
                    font=(P["font"][0], P["font"][1], "bold"))
    style.map("Accent.TButton", background=[("active", P["accent_hover"])])
    # 输入 (统一带边框)
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
    # 勾选/进度/分隔/滚动
    style.configure("TCheckbutton", background=P["bg"], foreground=P["text"], font=P["font"])
    style.configure("TProgressbar", background=P["accent"], troughcolor=P["surface2"])
    style.configure("TSeparator", background=P["border"])
    style.configure("TScrollbar", background=P["surface2"], troughcolor=P["surface"],
                    arrowcolor=P["text"], bordercolor=P["scroll_border"],
                    lightcolor=P["scroll_border"], darkcolor=P["scroll_border"])
    style.map("TScrollbar", background=[("disabled", P["surface2"])])
    for _o in ("Vertical", "Horizontal"):
        style.map(f"{_o}.TScrollbar.thumb", background=[("disabled", P["surface2"])])
        style.map(f"{_o}.Scrollbar.thumb", background=[("disabled", P["surface2"])])
    # 可拖拽分隔条 (统一 SplitPane / ttk.Panedwindow sash)
    style.configure("TPanedwindow", background=P["bg"], bordercolor=P["bg"])
    style.configure("Sash", background=P["sash"], lightcolor=P["sash_light"],
                    darkcolor=P["sash"])
    # 标签页
    style.configure("TNotebook", background=P["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=P["surface"], foreground=P["text"],
                    padding=(14, 6), font=P["font_sm"])
    style.map("TNotebook.Tab", background=[("selected", P["surface2"])],
              foreground=[("selected", P["text_bright"])])
    # 树
    style.configure("Treeview", background=P["surface"], foreground=P["text"],
                    fieldbackground=P["surface"], font=P["font_mono"],
                    borderwidth=0, rowheight=24)
    style.configure("Treeview.Heading", background=P["surface2"], foreground=P["text_bright"],
                    font=P["font_header"])
    style.map("Treeview", background=[("selected", P["selected"])],
              foreground=[("selected", P["text_bright"])])


def apply_tk_defaults(root, mode=None):
    """统一 tk 原生控件默认配色 (与 apply_theme 同一套色板; mode=None 用当前模式).
    每种控件类型一套样式, 与对应 ttk 样式视觉等价."""
    P = palette(mode or CURRENT_MODE)
    # Label
    root.option_add("*Label.background", P["bg"])
    root.option_add("*Label.foreground", P["text"])
    root.option_add("*Label.font", P["font"])
    root.option_add("*Label.relief", "flat")
    root.option_add("*Label.borderWidth", 0)
    root.option_add("*Label.padX", 0)
    root.option_add("*Label.padY", 0)
    # Button (flat 无 3D 边框, active 高亮, 与 ttk TButton 一致)
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
    # Entry (highlight 自定义边框, 与 ttk TEntry 一致)
    root.option_add("*Entry.background", P["entry_bg"])
    root.option_add("*Entry.foreground", P["text"])
    root.option_add("*Entry.insertBackground", P["text"])
    root.option_add("*Entry.relief", "flat")
    root.option_add("*Entry.borderWidth", 0)
    root.option_add("*Entry.highlightThickness", 1)
    root.option_add("*Entry.highlightBackground", P["border"])
    root.option_add("*Entry.highlightColor", P["accent"])
    root.option_add("*Entry.font", P["font_mono"])
    root.option_add("*Entry.padX", 8)
    root.option_add("*Entry.padY", 4)
    # 下拉菜单 (tk.Menu, 含 ttk.OptionMenu 内部菜单)
    root.option_add("*Menu.background", P["surface2"])
    root.option_add("*Menu.foreground", P["text"])
    root.option_add("*Menu.activeBackground", P["selected"])
    root.option_add("*Menu.activeForeground", P["text_bright"])
    root.option_add("*Menu.font", P["font"])
    root.option_add("*Menu.relief", "flat")
    # 勾选框 (原生 ✓ 样式, 统一配色)
    root.option_add("*Checkbutton.background", P["bg"])
    root.option_add("*Checkbutton.foreground", P["text"])
    root.option_add("*Checkbutton.activeBackground", P["bg"])
    root.option_add("*Checkbutton.selectColor", P["surface2"])
    root.option_add("*Checkbutton.font", P["font"])
    root.option_add("*Checkbutton.relief", "flat")
    root.option_add("*Checkbutton.borderWidth", 0)
    root.option_add("*Checkbutton.highlightThickness", 0)
    # 容器
    root.option_add("*Frame.background", P["bg"])
    root.option_add("*Labelframe.background", P["surface"])
    root.option_add("*Labelframe.foreground", P["text_bright"])
    # 列表/文本/画布
    root.option_add("*Listbox.background", P["surface"])
    root.option_add("*Listbox.foreground", P["text"])
    root.option_add("*Listbox.selectBackground", P["selected"])
    root.option_add("*Listbox.selectForeground", P["text_bright"])
    root.option_add("*Text.background", P["surface"])
    root.option_add("*Text.foreground", P["text"])
    root.option_add("*Text.insertBackground", P["text"])
    root.option_add("*Canvas.background", P["surface"])


def fmt_size(sz):
    """字节数格式化: B / KB / MB."""
    if sz >= 1048576:
        return f"{sz / 1048576:.1f} MB"
    if sz >= 1024:
        return f"{sz / 1024:.1f} KB"
    return f"{sz} B"


# ─── 公共功能 (本质相同的逻辑统一实现, 子功能用参数区分) ───
DEFAULT_ENCODINGS = ["utf-8-sig", "utf-8", "windows-1251", "windows-1252", "gb18030", "latin-1"]


def read_text_file(path, encodings=None):
    """多编码读取文本文件: 依次尝试编码, 返回 (内容, 成功编码).
    全部失败时最后一种编码以 ignore 容错读出. 适合原版游戏文件(多编码)."""
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
    """从 XML 文本提取所有文本节点内容 (容错).
    ET 解析优先 (保留 \\t); 失败时正则回退抓 <text>/<string> 内容并解标签."""
    import re
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
        return list(root.itertext())
    except Exception:
        strip_re = re.compile(r"<[^>]+>")
        texts = []
        for m in re.finditer(r"<text[^>]*>(.*?)</text>", text, re.S):
            texts.append(strip_re.sub("", m.group(1)))
        for m in re.finditer(r"<string[^>]*>(.*?)</string>", text, re.S):
            texts.append(strip_re.sub("", m.group(1)))
        return texts


def collect_files(root_dir, exts=None, exclude_dirs=()):
    """递归收集文件: exts 为扩展名集合(小写, 含点)或 None 收全部;
    exclude_dirs 为相对路径前缀元组. 返回排序后的绝对路径列表."""
    out = []
    for dp, dn, fns in os.walk(root_dir):
        rel = os.path.relpath(dp, root_dir).replace("\\", "/")
        if rel != "." and any(rel.startswith(p) for p in exclude_dirs):
            continue
        for fn in fns:
            if exts and os.path.splitext(fn)[1].lower() not in exts:
                continue
            out.append(os.path.join(dp, fn))
    return sorted(out)


def path_row(parent, label, var, browse, mono=True):
    """统一浏览行: Label + Entry + 浏览按钮 (VS Code Dark+).
    label 宽度 8; mono=True 用等宽字体. 返回 (row_frame, entry)."""
    from tkinter import ttk as _ttk
    from tkinter import Entry as _Entry
    row = _ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 4))
    _ttk.Label(row, text=label, width=8).pack(side="left")
    e = _Entry(row, textvariable=var, bg=T["entry_bg"], fg=T["text"],
               insertbackground=T["text"], relief="flat", bd=0,
               highlightthickness=1, highlightbackground=T["border"],
               highlightcolor=T["accent"],
               font=T["font_mono"] if mono else T["font"])
    e.pack(side="left", fill="x", expand=True, ipady=3)
    _ttk.Button(row, text="浏览", width=6, command=browse).pack(side="left", padx=(6, 0))
    return row, e




def _make_pump(root):
    """线程安全 UI 泵: 后台线程把回调投递到队列, 主线程定时执行."""
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

# ═══ 颜色分类总函数: 所有 UI 着色经此获取 ═══
def color(role):
    """UI 配色总入口 (单函数管所有颜色).
    角色分类:
      border      框(边框)颜色
      bg/surface  空白/面板底色
      entry_bg    填充部分颜色 (输入框/填充区)
      text/text_dim/text_bright  字体分类 (普通/次要/高亮)
      green/red/yellow/orange    字体语义色 (成功/错误/警告/强调)
      accent/accent_hover        强调色/悬停
      selected    选中填充"""
    return palette(CURRENT_MODE)[role]


# ═══ 同类功能各自一个函数 ═══
def dir_row(parent, label, var, browse=None, drop=None, add=None, width=8, state=None):
    """统一目录行: 标签 + 输入框(带边框) + 浏览按钮;
    可选: drop 拖拽回调, add 附加按钮 (text, command), state 输入框状态.
    返回 (row_frame, entry)."""
    from tkinter import ttk as _ttk
    from tkinter import Entry as _Entry
    row = _ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 4))
    if label:
        _ttk.Label(row, text=label, width=width).pack(side="left")
    e = _Entry(row, textvariable=var, bg=color("entry_bg"), fg=color("text"),
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
        _ttk.Button(row, text="浏览", width=6, command=browse).pack(side="left", padx=(6, 0))
    if add:
        _ttk.Button(row, text=add[0], width=6, command=add[1]).pack(side="left", padx=(4, 0))
    return row, e


def count_label(parent, side="right"):
    """统一计数标签 (灰色小字, 如 '3 文件'/'5 项')."""
    from tkinter import ttk as _ttk
    lbl = _ttk.Label(parent, text="", font=T["font_sm"], foreground=color("text_dim"))
    lbl.pack(side=side)
    return lbl

def tool_text(parent, text, kind="body", **pack_kw):
    """统一文本组件: 大标题 / 小标题 / 说明 / 正文 / 统计 / 语义文本.

    kind:
      title    大标题 (Title.TLabel)
      subtitle 小标题/分区说明 (Dim.TLabel)
      body     正文 (TLabel)
      dim      次要说明 (Dim.TLabel)
      mono     等宽正文 (TLabel + font_mono)
      stat     统计数字 (Stats.TLabel)
      success  成功/绿色 (Green.TLabel)
      error    错误/红色 (Red.TLabel)
      warn     警告/黄色 (Yellow.TLabel)
    """
    from tkinter import ttk as _ttk
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
    lbl = _ttk.Label(parent, text=text, style=style)
    if font:
        lbl.configure(font=font)
    lbl.pack(**kw)
    return lbl


def tool_header(parent, text, **pack_kw):
    """统一工具页大标题 (tool_text 的 title 别名)."""
    kw = {"anchor": "w", "padx": 14, "pady": (14, 2)}
    kw.update(pack_kw)
    return tool_text(parent, text, kind="title", **kw)

def vscrollbar(parent, target):
    """统一垂直滚动条, 绑定 target 的 yview; 自动 pack 右侧."""
    from tkinter import ttk as _ttk
    sb = _ttk.Scrollbar(parent, orient="vertical", command=target.yview)
    target.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    return sb


def drop_zone(parent, title, placeholder, on_file=None):
    """统一拖放槽: LabelFrame(标题) + 大点击/拖拽区域 (如视频OGM 源文件槽).
    on_file(path) 回调; 返回 label (可 show_file 更新文本)."""
    from tkinter import ttk as _ttk
    import tkinter as _tk
    lf = _ttk.LabelFrame(parent, text=title, padding=6)
    lf.pack(side="left", fill="both", expand=True, padx=(0, 6))
    lbl = _tk.Label(lf, text=placeholder, anchor="center",
                    font=T["font"], bg=color("entry_bg"), fg=color("text_dim"),
                    relief="flat", bd=0,
                    highlightthickness=1, highlightbackground=color("border"),
                    highlightcolor=color("accent"))
    lbl.pack(fill="both", expand=True, ipady=6)
    lbl._on_file = on_file
    lbl._placeholder = placeholder
    lbl._pick = None

    def _click(e):
        if lbl._pick:
            lbl._pick()
    def _drop(e):
        if on_file is not None and hasattr(e, "data"):
            from tkinter import filedialog as _fd
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
        lbl.configure(text=os.path.basename(path) if path else lbl._placeholder)
    lbl.show_file = show_file
    return lbl


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
    """统一日志区块: LabelFrame(标题) + 清空按钮 + LogBox.
    返回 (frame, logbox); hub 集成时隐藏返回的 frame 即可整体隐藏日志区."""
    from tkinter import ttk as _ttk
    lf = _ttk.LabelFrame(parent, text=title, padding=4)
    lf.pack(fill="both", expand=True)
    btn = None
    if clear:
        btn = _ttk.Button(lf, text="清空", width=5)
        btn.pack(side="right", anchor="n")
    log = LogBox(lf, height=height, wrap="word")
    log._log_role = True  # 标记: 真正的日志框 (hub 集成时隐藏, 结果展示区不隐藏)
    if btn is not None:
        btn.configure(command=log.clear)
    return lf, log


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
        c.create_rectangle(x, y, x + self.CHK, y + self.CHK, outline=T["text_dim"], width=1)
        if self.chk_state is not None:
            st = self.chk_state(node)
        else:
            st = node.dir_state() if node.is_dir else (True if node.checked else None)
        if st is True:
            c.create_line(x + 3, y + 8, x + 6, y + 11, x + self.CHK - 3, y + 4,
                          fill=T["text_bright"], width=2)
        elif st is False:
            c.create_line(x + 3, y + 8, x + self.CHK - 3, y + 8, fill=T["text_bright"], width=2)

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
class SplitPane(ttk.Panedwindow):
    """Unified ttk.Panedwindow wrapper.

    Why: raw ttk.Panedwindow usage was duplicated across tools, sash colors
    were inconsistent, and child widgets (especially self-drawn CanvasTree)
    did not refresh after dragging. This class keeps one sash style, one
    recolor path, and forces child refresh on sash release.
    """

    def __init__(self, master, orient="vertical", **kw):
        super().__init__(master, orient=orient, **kw)
        self._children = []
        self._orient = orient
        self.recolor()
        self.bind("<ButtonRelease-1>", self._on_sash_release, add="+")

    def recolor(self):
        """Apply current theme to the paned window and its sash."""
        try:
            style = ttk.Style()
            style.configure("TPanedwindow", background=color("bg"),
                            bordercolor=color("bg"))
            style.configure("Sash", background=color("sash"),
                            lightcolor=color("sash_light"),
                            darkcolor=color("sash"))
            self.configure(background=color("bg"))
        except Exception:
            pass

    def add(self, pane, weight=1, minsize=None):
        """Add a pane. weight maps to ttk.Panedwindow weight."""
        if minsize is not None:
            try:
                self.paneconfigure(pane, minsize=minsize)
            except Exception:
                pass
        super().add(pane, weight=weight)
        self._children.append(pane)
        return pane

    def refresh_children(self):
        """Force child widgets to redraw/refresh after a sash drag.

        Self-drawn widgets (CanvasTree, tk.Canvas) need this because ttk
        does not emit useful per-pane resize notifications on some platforms.
        """
        def walk(w):
            try:
                ctree = getattr(w, "_ctree", None)
                if ctree is not None and hasattr(ctree, "_draw"):
                    ctree._draw()
            except Exception:
                pass
            for c in w.winfo_children():
                walk(c)

        for pane in self._children:
            try:
                walk(pane)
            except Exception:
                pass

    def _on_sash_release(self, _event):
        self.refresh_children()


# ═══════════════════════════════════════════════════════════════
# PluginManager — minimal plugin host for the toolkit
# ═══════════════════════════════════════════════════════════════

class PluginManager:
    """Scan a plugins/ directory and host extension points.

    A plugin is a Python file in the plugin directory (or a direct
    subdirectory) that defines PLUGIN_INFO and register(api). It may
    also expose plain functions for backward compatibility.

    Optional allow-list: plugins/enabled.txt
        One plugin file name per line (# comments ignored). If the file
        exists and is non-empty, only the listed plugins are loaded.

    Extension points:
      * decryptor(check, decrypt)
      * format(name, handler)
      * menu_item(label, callback, location="context")
      * option(label, choices, callback=None)
      * tool(name, builder)
    """

    def __init__(self, plugins_dir, log=None):
        self.plugins_dir = plugins_dir
        self.log = log or (lambda msg, tag="info": None)
        self.plugins = []
        self.decryptors = []
        self.formats = []
        self.menu_items = []
        self.options = []
        self.tools = []
        self.load_errors = []

    def _enabled_allowlist(self):
        path = os.path.join(self.plugins_dir, "enabled.txt")
        if not os.path.isfile(path):
            return None
        names = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        names.append(line)
        except Exception:
            return None
        return names if names else None

    @staticmethod
    def _match_allow(name, allow):
        """Match allow-list entries; '*' and '?' wildcards are supported."""
        import fnmatch
        return any(fnmatch.fnmatch(name, pat) for pat in allow)

    def _iter_plugin_files(self):
        """Yield (relative_name, absolute_path) for all loadable plugins."""
        allow = self._enabled_allowlist()
        files = []
        for dp, dn, fn in os.walk(self.plugins_dir):
            dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
            for f in fn:
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, self.plugins_dir).replace("\\", "/")
                files.append((rel, full))
        files.sort(key=lambda x: x[0])
        if allow is None:
            return files
        return [(rel, full) for rel, full in files if self._match_allow(rel, allow)]

    def scan(self):
        """Import all plugin files and call their register()."""
        self.plugins = []
        self.decryptors = []
        self.formats = []
        self.menu_items = []
        self.options = []
        self.tools = []
        self.load_errors = []
        if not os.path.isdir(self.plugins_dir):
            return self.plugins

        for rel, path in self._iter_plugin_files():
            modname = "toolkit_plugin_" + re.sub(r"[^0-9A-Za-z_]", "_", rel[:-3])
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(modname, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                msg = f"plugin load failed: {rel}: {e}"
                self.load_errors.append(msg)
                self.log(msg, "err")
                continue
            info = getattr(mod, "PLUGIN_INFO", {})
            api = self._make_api(rel, info)
            registered = False
            if hasattr(mod, "register"):
                try:
                    mod.register(api)
                    registered = True
                except Exception as e:
                    msg = f"plugin register failed: {rel}: {e}"
                    self.load_errors.append(msg)
                    self.log(msg, "err")
            if not registered:
                # backward compatibility: bare functions in the plugin
                if hasattr(mod, "decrypt_sq"):
                    api.register_decryptor(
                        lambda p, m=mod: getattr(m, "open_sq")(p) is not None,
                        mod.decrypt_sq,
                    )
                    registered = True
            self.plugins.append({"file": rel, "info": info, "module": mod,
                                 "registered": registered})
            self.log(f"plugin loaded: {rel}", "ok")
        return self.plugins

    def _make_api(self, filename, info):
        pm = self

        class Api:
            def register_decryptor(self, check, decrypt):
                pm.decryptors.append({
                    "plugin": filename,
                    "info": info,
                    "check": check,
                    "decrypt": decrypt,
                })

            def register_format(self, name, handler):
                pm.formats.append({
                    "plugin": filename,
                    "info": info,
                    "name": name,
                    "handler": handler,
                })

            def register_menu_item(self, label, callback, location="context"):
                pm.menu_items.append({
                    "plugin": filename,
                    "info": info,
                    "label": label,
                    "callback": callback,
                    "location": location,
                })

            def register_option(self, label, choices, callback=None):
                pm.options.append({
                    "plugin": filename,
                    "info": info,
                    "label": label,
                    "choices": choices,
                    "callback": callback,
                })

            def register_tool(self, name, builder):
                """Register a new Hub tab. builder(parent) builds the tab UI."""
                pm.tools.append({
                    "plugin": filename,
                    "info": info,
                    "name": name,
                    "builder": builder,
                })

        return Api()

    def find_decryptor(self, path):
        """Return the first registered decryptor that accepts path, else None."""
        for d in self.decryptors:
            try:
                if d["check"](path):
                    return d
            except Exception:
                continue
        return None
