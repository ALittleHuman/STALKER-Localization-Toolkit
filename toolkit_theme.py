# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 主题（单文件）

设计约束（方案A）:
  1. 主题只有**一个文件**：新增主题只往 THEMES 里加数据，不新建文件。
  2. 亮/暗两套共用同一套样式代码，apply_theme(mode) 单函数切换。
  3. T 是模块级字典，apply_theme 以 clear()+update() **原地修改**。
     外部 `from toolkit import T` 拿到的是同一个对象，切主题不会失效；
     切勿把 T 重新绑定为新字典。
  4. **数据层本身不碰 Tk**（2026-09-12，Qt 试点接主题时加的约束）：
     `THEMES` / `_FONTS` / `palette()` / `color()` / `px()` 与具体 UI 技术无关，是亮/暗两套的
     **唯一真值来源**（见 `qt_pilot_theme.py`：Qt 侧按 AST 读这里的表，**不抄一份** ——
     抄一份就是漂移来源；探针再用子进程把这里的**运行时真值**取回来和 Qt 侧逐字段对拍）。
     所以 `from tkinter import ttk` 只在 `apply_theme()` 内部导入。
     **仍未解开的边界**（如实记，别当已解决）：`import toolkit_theme` 今天**还不能**在
     Qt 进程里成立 —— 它要 `toolkit_platform.load_user_value`，而
     `toolkit_platform → toolkit_base` 顶层就 `import tkinter` 且选 `TkinterDnD.Tk`。
     也就是说 **user.ltx 读写是 Qt 侧唯一的 Tk 依赖**（色板/字体/`px` 都不是）。
     冻结的 Qt 包里没有 Tcl/Tk，所以"主题持久化"必须先把 `app_dir()` 及其 ltx 助手
     挪到 Tk 无关模块 —— 这是迁移项，不是试点该顺手改的（ARCHITECTURE §11.3）。
"""
import sys

from toolkit_platform import load_user_value, save_user_value


# ─── 色板 (唯一来源: 亮/暗两套, 样式代码共用同一函数) ───
# 2026-09-13 重画（用户授权"按你的审美"）：
#   * **层次**：bg → surface → surface2 三档拉开一点，内嵌区（输入/列表）用 entry_bg 比
#     surface **更暗**，视觉上"陷进去"；原来 entry_bg(#3a3d41) 比 surface2 还亮，
#     输入框像贴在面板上。
#   * **边框**：原来的 border #6e7681 太亮，满屏都是硬线；改成只比 surface2 亮一档的
#     弱色，让"分块"靠底色差而不是靠线。
#   * **强调色**：accent 换成更柔和的蓝（#4c8dff），并统一用它做 焦点/选中/主按钮。
#   * **语义色**去饱和一档（原来 green #4ec9b0 偏荧光）。
# 键名与数量**不许变**：Qt 侧按这份表映射，探针锁了 18 个颜色角色 + 6 个字体角色。
THEMES = {
    "dark": {
        "bg": "#1b1d23", "surface": "#22252c", "surface2": "#2b2f38",
        "border": "#363b46", "accent": "#4c8dff", "accent_hover": "#6ba0ff",
        "text": "#d6d9e0", "text_dim": "#8b919e", "text_bright": "#f0f2f6",
        "green": "#5cc08d", "red": "#e5686d", "yellow": "#d9b45b", "orange": "#d98d5b",
        "entry_bg": "#161920", "selected": "#2b4a7d",
        "scroll_border": "#2f333d",
        "sash": "#2f333d", "sash_light": "#4c8dff",
    },
    "light": {
        "bg": "#f6f7f9", "surface": "#ffffff", "surface2": "#eef0f4",
        "border": "#d3d7de", "accent": "#2f6fe4", "accent_hover": "#4a86f0",
        "text": "#2c3038", "text_dim": "#6b7280", "text_bright": "#14171c",
        "green": "#1f8a5f", "red": "#cf4444", "yellow": "#9a7b12", "orange": "#b5651d",
        "entry_bg": "#ffffff", "selected": "#d6e4ff",
        "scroll_border": "#cfd4dc",
        "sash": "#d3d7de", "sash_light": "#2f6fe4",
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


# ─── HiDPI：像素缩放系数 ───
# 设计稿里那些硬编码像素（列表行高、缩进、勾选框尺寸、Canvas 高度…）都是按
# **96 DPI（100% 缩放）** 定的。Tk 的 `tk scaling` 是"每磅像素数"，96 DPI 时为
# 4/3，所以 缩放系数 = scaling / (4/3) = scaling * 0.75。
# 关键区别：**字体的磅值由 Tk 自己按 scaling 换算，像素值不会**。
# 于是在 150% 的屏上，正文行高变成 32px 而写死的行高还是 24px —— 行比字矮，
# 文字被裁，看起来就是"糊"。凡是按 96 DPI 定的像素值都要过 `px()`。
_UI_SCALE = 1.0


def set_ui_scale(value):
    """由宿主在窗口创建后写入（见 `sync_tk_scaling`）。"""
    global _UI_SCALE
    try:
        _UI_SCALE = float(value) or 1.0
    except (TypeError, ValueError):
        _UI_SCALE = 1.0
    return _UI_SCALE


def ui_scale():
    """当前像素缩放系数（1.0 = 96 DPI 的设计值）。"""
    return _UI_SCALE


def px(value):
    """把按 96 DPI 定的像素值换算成当前缩放下的像素值。"""
    return int(round(value * _UI_SCALE))


def sync_tk_scaling(root):
    """按窗口所在显示器的实际 DPI 校正 Tk 的 scaling 与全局缩放系数。

    为什么需要：Tk 只在解释器初始化时按**当时的主显示器**算一次 `tk scaling`。
    若进程的 DPI 感知是建窗之后才设上的、或窗口开在另一块不同缩放的显示器上，
    字号与像素常量就会对不上。返回实际采用的 DPI（拿不到返回 None）。
    """
    if sys.platform != "win32":
        return None
    dpi = 0
    try:
        import ctypes
        dpi = int(ctypes.windll.user32.GetDpiForWindow(root.winfo_id()) or 0)
        if not dpi:
            dpi = int(ctypes.windll.user32.GetDpiForSystem() or 0)
    except Exception:
        dpi = 0
    if dpi <= 0:
        try:
            dpi = int(round(float(root.tk.call("tk", "scaling")) * 72))
        except Exception:
            dpi = 0
    if dpi <= 0:
        return None
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
    set_ui_scale(dpi / 96.0)
    return dpi


def palette(mode="dark"):
    """取指定模式的完整色板 (含字体键), 默认暗色."""
    p = dict(THEMES.get(mode, THEMES["dark"]))
    p.update(_FONTS)
    return p


# 默认暗色色板 (兼容直接引用 toolkit.T 的既有代码)
T = palette("dark")

# 当前主题模式 (hub 切换后重建工具时, 工具内部 apply_theme() 沿用此模式)
CURRENT_MODE = "dark"


# user_config_path 由 toolkit_platform 提供（user.ltx 是**所有**工具共用的
# 用户设置文件，不只是主题的）。这里只负责 [theme] 段：
# 读写都走 load_user_value / save_user_value，**不整文件覆盖** ——
# 否则存一次主题就会把 [ffmpeg] 等其它段一起抹掉。


def load_user_theme():
    """读取 user.ltx 中 [theme] mode, 缺省 dark."""
    mode = str(load_user_value("theme", "mode", "dark") or "dark").strip().lower()
    return mode if mode in ("dark", "light") else "dark"


def save_user_theme(mode):
    """保存主题到 user.ltx 的 [theme] 段（保留其它段）。"""
    return save_user_value("theme", "mode", mode)


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


# ─── 单函数主题模板: 亮/暗用同一套样式代码, mode 参数切换 ───
def apply_theme(mode=None):
    """统一主题模板 (唯一函数): 所有工具的配色/字体/控件样式由此函数配置.
    mode: "dark"/"light"; None 时沿用当前模式 (CURRENT_MODE).
    调用方: hub 启动/切换 + 各工具独立运行时."""
    from tkinter import ttk        # 见模块 docstring 第 4 条：只有这里真需要 Tk
    global CURRENT_MODE
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
    # 按钮：普通按钮**安静**（surface2 + 弱边框），悬停只微微提亮（原来悬停直接变强调色，
    # 满屏按钮一起变蓝很吵）；只有 `Accent.TButton`（主操作）是实心强调色。
    style.configure("TButton", background=P["surface2"], foreground=P["text"],
                    bordercolor=P["border"], relief="flat", padding=(12, 6), font=P["font"])
    style.map("TButton",
              background=[("pressed", P["selected"]), ("active", P["border"])],
              bordercolor=[("focus", P["accent"])],
              foreground=[("disabled", P["text_dim"])])
    style.configure("Accent.TButton", background=P["accent"], foreground="#fff",
                    bordercolor=P["accent"], relief="flat", padding=(12, 6),
                    font=(P["font"][0], P["font"][1], "bold"))
    style.map("Accent.TButton",
              background=[("pressed", P["accent_hover"]), ("active", P["accent_hover"])],
              foreground=[("disabled", P["text_dim"])])
    # 输入：底色比面板更暗（"陷进去"）+ 焦点描边用强调色（原来 focus 时底色变亮，很跳）
    style.configure("TEntry", fieldbackground=P["entry_bg"], foreground=P["text"],
                    bordercolor=P["border"], borderwidth=1, relief="solid",
                    padding=(8, 5), font=P["font_mono"])
    style.map("TEntry", bordercolor=[("focus", P["accent"])],
              lightcolor=[("focus", P["accent"])], darkcolor=[("focus", P["accent"])])
    style.configure("TCombobox", fieldbackground=P["entry_bg"], foreground=P["text"],
                    background=P["surface2"], arrowcolor=P["text_dim"],
                    bordercolor=P["border"], borderwidth=1, relief="solid",
                    padding=(6, 4), font=P["font"])
    style.map("TCombobox", fieldbackground=[("readonly", P["entry_bg"])],
              bordercolor=[("focus", P["accent"])])
    style.configure("TOptionMenu", background=P["surface2"], foreground=P["text"],
                    arrowcolor=P["text_dim"], bordercolor=P["border"],
                    relief="flat", padding=(10, 4), font=P["font"])
    style.configure("TMenubutton", background=P["surface2"], foreground=P["text"],
                    arrowcolor=P["text_dim"], bordercolor=P["border"],
                    relief="flat", padding=(10, 4), font=P["font"])
    # 勾选/进度/分隔/滚动
    style.configure("TCheckbutton", background=P["bg"], foreground=P["text"], font=P["font"])
    style.map("TCheckbutton", background=[("active", P["bg"])],
              foreground=[("disabled", P["text_dim"])])
    style.configure("TProgressbar", background=P["accent"], troughcolor=P["surface2"],
                    bordercolor=P["surface2"], lightcolor=P["accent"],
                    darkcolor=P["accent"], thickness=px(8))
    style.configure("TSeparator", background=P["border"])
    style.configure("TScrollbar", background=P["surface2"], troughcolor=P["bg"],
                    arrowcolor=P["text_dim"], bordercolor=P["scroll_border"],
                    lightcolor=P["scroll_border"], darkcolor=P["scroll_border"])
    style.map("TScrollbar", background=[("disabled", P["surface2"]),
                                        ("active", P["border"])])
    # ── 现代滚动条：**去掉两端的箭头按钮**，只留细滑块 ─────────────────────
    # 用户口径 2026-09-13："这滚动条啥玩意？和之前那次一毛一样。这种滚动条你是不会吗？"
    # 那不是"我造的"外观 —— 是 **ttk clam 主题的默认**：轨道 + 两端 ◀▶/▲▼ 按钮。
    # 一个 `style.layout` 就能把它换成"只有轨道 + 滑块"的扁平样式，全应用生效
    # （树、面板内视口、日志、文本框……所有 ttk 滚动条都在这一处定义）。
    for _o, _st in (("Vertical", "ns"), ("Horizontal", "ew")):
        _thumb = "%s.Scrollbar.thumb" % _o
        _trough = "%s.Scrollbar.trough" % _o
        try:
            style.layout("%s.TScrollbar" % _o, [
                (_trough, {"sticky": _st,
                           "children": [(_thumb, {"expand": "1", "sticky": "nswe"})]})])
        except Exception:
            pass
    # 滑块用 mid 色、轨道用底色（原来轨道比面板还亮，整条都在抢视线）
    style.configure("TScrollbar", background=P["border"], troughcolor=P["bg"],
                    bordercolor=P["bg"], lightcolor=P["border"], darkcolor=P["border"],
                    arrowcolor=P["bg"], arrowsize=1, gripcount=0,
                    relief="flat", borderwidth=0)
    style.map("TScrollbar", background=[("active", P["sash_light"]),
                                        ("disabled", P["surface2"])])
    for _o in ("Vertical", "Horizontal"):
        style.map(f"{_o}.TScrollbar.thumb", background=[("disabled", P["surface2"])])
        style.map(f"{_o}.Scrollbar.thumb", background=[("disabled", P["surface2"])])
    # 可拖拽分隔条 (统一 SplitPane / ttk.Panedwindow sash)
    # 悬停/拖动时 sash 亮强调色（`sash_light`）—— 用户能看出"这条抓得住"。
    style.configure("TPanedwindow", background=P["bg"], bordercolor=P["bg"])
    style.map("TPanedwindow", background=[("active", P["sash_light"])])
    style.configure("Sash", background=P["sash"], lightcolor=P["sash_light"],
                    darkcolor=P["sash"], bordercolor=P["bg"], sashthickness=px(6))
    style.map("Sash", background=[("active", P["sash_light"])])
    # 标签页：选中的页签与内容同色（连成一片），未选中的压在 surface 上；
    # 页签间距也放大一档（原来 14,6 显得挤）。
    style.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(2, 4, 0, 0))
    style.configure("TNotebook.Tab", background=P["surface"], foreground=P["text_dim"],
                    padding=(18, 8), font=P["font_sm"], bordercolor=P["bg"])
    style.map("TNotebook.Tab",
              background=[("selected", P["bg"])],
              foreground=[("selected", P["text_bright"]), ("active", P["text"])],
              expand=[("selected", (0, 0, 0, 0))])
    # 树：行高保持 px(24)（`run_app_probe` 有一条锁盯着"行高必须按缩放换算"，
    # 它的基准值就是 24 —— 视觉上想调它也应当先改锁与文档，而不是顺手改这里）。
    # 表头改成去饱和色（原来和数据区一样亮，看着像按钮）。
    style.configure("Treeview", background=P["surface"], foreground=P["text"],
                    fieldbackground=P["surface"], font=P["font_mono"],
                    borderwidth=0, rowheight=px(24))
    style.configure("Treeview.Heading", background=P["surface2"], foreground=P["text_dim"],
                    relief="flat", padding=(8, 6), font=P["font_header"])
    style.map("Treeview.Heading", background=[("active", P["border"])])
    style.map("Treeview", background=[("selected", P["selected"])],
              foreground=[("selected", P["text_bright"])])


def apply_tk_defaults(root, mode=None):
    """统一 tk 原生控件默认配色 (与 apply_theme 同一套色板; mode=None 用当前模式).
    每种控件类型一套样式, 与对应 ttk 样式视觉等价."""
    # 先把缩放校正过来，并**重新应用一次主题样式**。
    # 宿主通常是 apply_theme() 在前、apply_tk_defaults() 在后，而 apply_theme
    # 里凡是按 96 DPI 定的像素值都过 `px()`；不在这里重来一次，行高就会用
    # 100%（24px）的值去配 150% 的字体（正文行高 32px）→ 文字被裁。
    sync_tk_scaling(root)
    apply_theme(mode)
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
