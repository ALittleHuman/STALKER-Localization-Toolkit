# -*- coding: utf-8 -*-
"""Qt 后端的主题映射 —— 把 `toolkit_theme` 的色板/字体映射成 QPalette + 样式表。

## 直接 import 那一份真值（不再抄表）

`THEMES` / `_FONTS` 是亮暗两套的**唯一真值来源**，Qt 侧不抄一份（抄一份就会漂移）。
本模块**直接 `import toolkit_theme`** 读它。

这件事在 2026-09-12 之前做不到：`toolkit_theme` 要 `toolkit_platform.load_user_value`，
而 `toolkit_platform → toolkit_base` 顶层就 `import tkinter` 并选 `TkinterDnD.Tk`。
当时的临时做法是按 AST 读源码里的字面量。后来把 `app_dir()` 这一条规则挪进
**Tk 无关的 `toolkit_paths.py`**（`toolkit_base` 仍 re-export），那条依赖就断了：
现在 `import toolkit_theme` 不会把 tkinter 拉进进程，真值可以**import 进来**，
`load_user_theme/save_user_theme` 也就能被 Qt 侧直接复用（主题持久化）。

探针里有一条**反向**的证明：拦截 `import tkinter` 之后再 import 本模块 ——
拿不到就走不下去，而不是"悄悄降级成一份内置色板"。

## 三条不能弄错的语义

* **`px()` 不要在这边用。** Tk 的 `px()` 是"按 96 DPI 定的像素值 × 缩放系数"，因为 Tk 只按
  显示器把**字号**换算过去、像素常量不会。Qt 的坐标/尺寸本来就是设备无关的逻辑像素，
  高 DPI 由 Qt 自己缩放 —— 在 Qt 侧再乘一次 `px()` 就是**双重缩放**（150% 屏上大 1.5 倍）。
  所以 `toolkit_theme.px(24)` 对应 Qt 的 `24`；行高这类量另由字体度量推出。
* **字体是磅值，两边同号。** Tk 字体元组 `(family, size[, "bold"])` 与 Qt 的
  `setPointSize/family/bold` 语义一致，直接映射即可（Tk 按 scaling 换算磅→像素，
  Qt 按 DPI 换算磅→像素，结果等价）。
* **采样真实像素要换算 device pixel ratio**（探针那边的口径）：`grab()` 给的是设备像素，
  `geometry()` 是逻辑像素。

## 持久化

`load_mode()` / `save_mode()` 直接转调 `toolkit_theme.load_user_theme/save_user_theme`
（`user.ltx` 的 `[theme]` 段）—— **不自己解析、也不整文件重写**：那份逻辑一旦抄错，
存一次主题就会把 `[ffmpeg]` 等段一起抹掉。探针用临时目录 + 预置的 `[ffmpeg]` 段真跑一遍，
核对两段都在。
"""
try:
    from PySide6 import QtGui, QtWidgets
    QT_AVAILABLE = True
    QT_IMPORT_ERROR = None
except Exception as e:                       # 缺 PySide6 时本模块仍可被导入（探针据此 SKIP）
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

# 同一份真值：直接 import（见模块 docstring；这条 import 不会把 tkinter 带进来）
try:
    import toolkit_theme as TT
    _THEME_IMPORT_ERROR = None
except Exception as e:
    TT = None
    _THEME_IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

# 色板里的**颜色**角色（`_FONTS` 之外的键）。顺序固定，探针按这份名单逐字段对拍。
COLOR_ROLES = ("bg", "surface", "surface2", "border", "accent", "accent_hover",
               "text", "text_dim", "text_bright", "green", "red", "yellow", "orange",
               "entry_bg", "selected", "scroll_border", "sash", "sash_light")
# 字体角色（与 toolkit_theme._FONTS 同键）。
FONT_ROLES = ("font", "font_sm", "font_mono", "font_title", "font_header", "font_stats")

# 唯一允许在本模块出现的颜色字面量：强调色**上面**的文字色。
# 为什么不从表里取：`toolkit_theme.apply_theme()` 里也是写死的 `"#fff"`（`Accent.TButton`），
# 表里没有这个角色 —— 在 Qt 侧新造一个角色就等于两个后端各有一份"白"，所以照抄同一处语义。
# 探针会锁"本模块的颜色字面量不超过 1 个"，新增字面量必须同时改这条注释与那份名单。
ON_ACCENT = "#ffffff"

# 语义标签样式：Tk 的 ttk 样式名 → 取哪个角色当前景色 + 哪个字体角色。
# 这份表让 `api.ui.label(parent, text, style="Dim.TLabel")` 在 Qt 上**真的变色**，
# 而不是像试点第一版那样把 style 参数丢掉。
LABEL_STYLES = {
    "TLabel": ("text", "font"),
    "Dark.TLabel": ("text", "font"),
    "Title.TLabel": ("text_bright", "font_title"),
    "Dim.TLabel": ("text_dim", "font_sm"),
    "Green.TLabel": ("green", "font_sm"),
    "Red.TLabel": ("red", "font_sm"),
    "Yellow.TLabel": ("yellow", "font_sm"),
    "Stats.TLabel": ("accent", "font_stats"),
    "Accent.TLabel": ("accent", "font_sm"),
    "Error.TLabel": ("red", "font_sm"),
}
# 按钮样式：风格名 → (底色角色 或 None=默认, 前景角色, 加粗)
BUTTON_STYLES = {
    "TButton": (None, None, False),
    "Accent.TButton": ("accent", None, True),
}

# 日志分级 → 角色（Tk 侧的 5 个分级与 toolkit_log 一致）
LOG_TAG_ROLES = {"ok": "green", "err": "red", "warn": "yellow",
                 "dim": "text_dim", "info": "text"}


class ThemeSourceError(RuntimeError):
    """拿不到色板（toolkit_theme 不可用 / 模式名不认识）—— 必须显式失败，不许静默降级成内置色。"""


def theme_source_ok():
    """取表是否成功（探针据此 FAIL；正常路径不会走到 False）。"""
    return TT is not None and bool(TT.THEMES) and bool(TT._FONTS)


def theme_import_error():
    return _THEME_IMPORT_ERROR


def modes():
    return tuple(sorted(TT.THEMES)) if TT is not None else ()


def palette(mode="dark"):
    """整套色板 + 字体（**就是** `toolkit_theme.palette(mode)`，不是同构副本）。"""
    if TT is None:
        raise ThemeSourceError("拿不到 toolkit_theme：%s" % (_THEME_IMPORT_ERROR,))
    if mode not in TT.THEMES:
        raise ThemeSourceError("未知主题 %r（可选 %s）" % (mode, modes()))
    return TT.palette(mode)


def font_spec(role, mode="dark"):
    """取字体角色 → `(family, point_size, bold)`。Tk 元组第三项是 "bold" 时加粗。"""
    if TT is None:
        return None
    spec = TT._FONTS.get(role)
    if not spec:
        return None
    family, size = spec[0], int(spec[1])
    bold = len(spec) > 2 and str(spec[2]).lower() == "bold"
    return family, size, bold


# ── 持久化：转调 toolkit_theme（**不自己解析/整文件重写** user.ltx）──────────
def load_mode():
    """读持久化的主题模式（`user.ltx` 的 `[theme] mode`，缺省 dark）。"""
    if TT is None:
        return "dark"
    try:
        return TT.load_user_theme()
    except Exception:
        return "dark"


def save_mode(mode):
    """把模式写回 `user.ltx`（保留其它段 —— 由 toolkit_platform 保证，不在这里重写文件）。"""
    if TT is None:
        return False
    try:
        return bool(TT.save_user_theme(mode))
    except Exception:
        return False


def make_font(role, mode="dark"):
    """字体角色 → QFont（磅值与 Tk 同号，见模块 docstring）。"""
    spec = font_spec(role, mode)
    if spec is None or not QT_AVAILABLE:
        return None
    family, size, bold = spec
    f = QtGui.QFont(family, size)
    f.setBold(bold)
    return f


def qpalette(mode="dark"):
    """色板 → QPalette（逐角色对应，探针会把每一项读回来对拍）。"""
    if not QT_AVAILABLE:
        return None
    P = palette(mode)
    pal = QtGui.QPalette()
    C = QtGui.QColor
    R = QtGui.QPalette.ColorRole
    mapping = (
        (R.Window, P["bg"]), (R.WindowText, P["text"]),
        (R.Base, P["surface"]), (R.AlternateBase, P["surface2"]),
        (R.Text, P["text"]), (R.PlaceholderText, P["text_dim"]),
        (R.Button, P["surface2"]), (R.ButtonText, P["text"]),
        (R.BrightText, P["red"]),
        (R.Highlight, P["accent"]), (R.HighlightedText, ON_ACCENT),
        (R.ToolTipBase, P["surface"]), (R.ToolTipText, P["text"]),
        (R.Link, P["accent"]), (R.LinkVisited, P["accent_hover"]),
        (R.Mid, P["border"]), (R.Dark, P["border"]), (R.Shadow, P["bg"]),
        (R.Light, P["surface2"]),
    )
    for role, value in mapping:
        pal.setColor(role, C(value))
    for role, value in ((R.HighlightedText, ON_ACCENT),):
        pal.setColor(QtGui.QPalette.ColorGroup.Disabled, role, C(value))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, R.Text, C(P["text_dim"]))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, R.ButtonText, C(P["text_dim"]))
    return pal


def stylesheet(mode="dark"):
    """色板 → QSS。

    覆盖试点真正用到的控件类；**每个颜色都来自色板**，不做任何"看起来差不多"的发明。
    """
    P = palette(mode)
    f = dict((r, font_spec(r)) for r in FONT_ROLES)

    def ff(role):
        spec = f.get(role)
        if not spec:
            return ""
        fam, size, bold = spec
        return "font-family:'%s';font-size:%dpt;%s" % (
            fam, size, "font-weight:bold;" if bold else "")

    qss = []
    qss.append("QWidget { background:%s; color:%s; %s }" % (P["bg"], P["text"], ff("font")))
    qss.append("QLabel { background:transparent; color:%s; %s }" % (P["text"], ff("font")))
    qss.append("QLabel[role=\"dim\"] { color:%s; %s }" % (P["text_dim"], ff("font_sm")))
    qss.append("QLabel[role=\"title\"] { color:%s; %s }" % (P["text_bright"], ff("font_title")))
    qss.append("QLabel[role=\"header\"] { color:%s; %s }" % (P["text_bright"], ff("font_header")))
    qss.append("QLabel[role=\"stats\"] { color:%s; %s }" % (P["accent"], ff("font_stats")))
    for role in ("green", "red", "yellow", "orange"):
        qss.append("QLabel[role=\"%s\"] { color:%s; %s }" % (role, P[role], ff("font_sm")))
    qss.append("QGroupBox { background:%s; border:1px solid %s; margin-top:8px; %s }"
               % (P["surface"], P["border"], ff("font_header")))
    qss.append("QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px;"
               " color:%s; background:%s; %s }"
               % (P["text_bright"], P["surface"], ff("font_header")))
    qss.append("QPushButton { background:%s; color:%s; border:1px solid %s;"
               " padding:5px 12px; %s }" % (P["surface2"], P["text"], P["border"], ff("font")))
    qss.append("QPushButton:hover { background:%s; color:%s }" % (P["accent"], ON_ACCENT))
    qss.append("QPushButton:pressed { background:%s }" % P["accent_hover"])
    qss.append("QPushButton:disabled { color:%s }" % P["text_dim"])
    qss.append("QPushButton[style=\"accent\"] { background:%s; color:%s; font-weight:bold }"
               % (P["accent"], ON_ACCENT))
    qss.append("QLineEdit, QPlainTextEdit, QTextEdit { background:%s; color:%s;"
               " border:1px solid %s; selection-background-color:%s;"
               " selection-color:%s; %s }"
               % (P["entry_bg"], P["text"], P["border"], P["selected"],
                  P["text_bright"], ff("font_mono")))
    qss.append("QLineEdit:focus, QPlainTextEdit:focus { border:1px solid %s }" % P["accent"])
    qss.append("QComboBox { background:%s; color:%s; border:1px solid %s; padding:3px 6px }"
               % (P["entry_bg"], P["text"], P["border"]))
    qss.append("QComboBox QAbstractItemView { background:%s; color:%s;"
               " selection-background-color:%s; selection-color:%s }"
               % (P["surface"], P["text"], P["selected"], P["text_bright"]))
    qss.append("QCheckBox { background:transparent; color:%s; %s }" % (P["text"], ff("font")))
    qss.append("QProgressBar { background:%s; border:1px solid %s; text-align:center;"
               " color:%s }" % (P["surface2"], P["border"], P["text"]))
    qss.append("QProgressBar::chunk { background:%s }" % P["accent"])
    qss.append("QScrollBar:vertical { background:%s; width:12px; margin:0 }" % P["surface"])
    qss.append("QScrollBar::handle:vertical { background:%s; min-height:24px;"
               " border:1px solid %s }" % (P["surface2"], P["scroll_border"]))
    qss.append("QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0 }")
    qss.append("QScrollBar:horizontal { background:%s; height:12px; margin:0 }" % P["surface"])
    qss.append("QScrollBar::handle:horizontal { background:%s; min-width:24px;"
               " border:1px solid %s }" % (P["surface2"], P["scroll_border"]))
    qss.append("QSplitter::handle { background:%s }" % P["sash"])
    qss.append("QSplitter::handle:hover { background:%s }" % P["sash_light"])
    qss.append("QTabWidget::pane { border:1px solid %s; background:%s }"
               % (P["border"], P["bg"]))
    qss.append("QTabBar::tab { background:%s; color:%s; padding:6px 14px; %s }"
               % (P["surface"], P["text"], ff("font_sm")))
    qss.append("QTabBar::tab:selected { background:%s; color:%s }"
               % (P["surface2"], P["text_bright"]))
    qss.append("QHeaderView::section { background:%s; color:%s; border:0;"
               " padding:4px 6px; %s }" % (P["surface2"], P["text_bright"], ff("font_header")))
    qss.append("QTreeView, QTreeWidget { background:%s; color:%s;"
               " alternate-background-color:%s; selection-background-color:%s;"
               " selection-color:%s; %s }"
               % (P["surface"], P["text"], P["surface2"], P["selected"],
                  P["text_bright"], ff("font_mono")))
    qss.append("QMenu { background:%s; color:%s; border:1px solid %s }"
               % (P["surface"], P["text"], P["border"]))
    qss.append("QMenu::item:selected { background:%s; color:%s }"
               % (P["accent"], ON_ACCENT))
    qss.append("QToolTip { background:%s; color:%s; border:1px solid %s }"
               % (P["surface"], P["text"], P["border"]))
    qss.append("QMainWindow, QStatusBar { background:%s; color:%s }"
               % (P["bg"], P["text"]))
    return "\n".join(qss)


_CURRENT = {"mode": "dark"}


def current_mode():
    return _CURRENT["mode"]


def apply(app=None, mode=None, persist=False):
    """把主题落到 QApplication（Palette + 样式表 + 默认字体）。返回实际生效的 mode。

    与 Tk 侧 `apply_theme(mode)` 是同一层语义：**单函数切换**、亮暗共用一套样式代码。

    `mode=None` → 读**持久化**的设置（`user.ltx` 的 `[theme] mode`，缺省 dark）：
    这正是启动路径要的语义（上次选了什么，这次还是什么）。
    `persist=True` → 应用后写回设置（用户点"切换主题"走这条）。
    """
    if mode is None:
        mode = load_mode()
    if mode not in modes():
        raise ThemeSourceError("未知主题 %r（可选 %s）" % (mode, modes()))
    _CURRENT["mode"] = mode
    if persist:
        save_mode(mode)
    m = _CURRENT["mode"]
    if not QT_AVAILABLE:
        return m
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return m
    pal = qpalette(m)
    if pal is not None:
        app.setPalette(pal)
    app.setStyleSheet(stylesheet(m))
    f = make_font("font", m)
    if f is not None:
        app.setFont(f)
    return m


def toggle(app=None, persist=True):
    """切到另一套（用户点的那一下），默认**写回** user.ltx 的 [theme] 段。"""
    return apply(app, "light" if current_mode() == "dark" else "dark", persist=persist)


def role_color(role, mode=None):
    """取角色色值（等价 Tk 的 `color(role)`，但按给定 mode 而不是全局 CURRENT_MODE）。"""
    return palette(mode or current_mode())[role]


def log_color(tag, mode=None):
    """日志分级 → 色值（Tk 侧 `toolkit_log` 的分类保持同一套角色）。"""
    return role_color(LOG_TAG_ROLES.get(tag, "text"), mode)


def apply_label_style(widget, style):
    """把 Tk 的 ttk 样式名映射到 Qt 控件（颜色 + 字体 + role 属性供 QSS 命中）。"""
    if not style or not QT_AVAILABLE:
        return widget
    fg_role, font_role = LABEL_STYLES.get(style, ("text", "font"))
    f = make_font(font_role)
    if f is not None:
        widget.setFont(f)
    if fg_role in ("text", "text_bright", "text_dim"):
        widget.setProperty("role", {"text": "normal", "text_bright": "title",
                                    "text_dim": "dim"}[fg_role])
    else:
        widget.setProperty("role", fg_role)
    try:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
    except Exception:
        pass
    return widget


def apply_button_style(widget, style):
    """Tk 的按钮样式 → Qt（`Accent.TButton` 走 accent 底 + 强调色上的文字）。"""
    if not style or not QT_AVAILABLE:
        return widget
    bg_role, _fg_role, bold = BUTTON_STYLES.get(style, (None, None, False))
    if bg_role:
        widget.setProperty("style", "accent")
    f = make_font("font")
    if f is not None:
        f.setBold(bool(bold))
        widget.setFont(f)
    try:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
    except Exception:
        pass
    return widget
