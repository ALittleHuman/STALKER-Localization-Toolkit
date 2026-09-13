# -*- coding: utf-8 -*-
"""插件 UI 工厂（后端无关）—— Tk 实现。

## 为什么需要它

插件契约里只有三处与具体工具包耦合：

1. `api.widgets` —— 直接暴露 `toolkit_widgets`（Tk 专用）；
2. `register_panel(title, builder, …)` 的 `builder(parent)`；
3. `register_tool(name, builder, order)` 的 `builder(parent)`。

后两者的 builder 自己造控件，于是"同一份插件代码无法在另一个后端（Qt）上跑"。
本模块给出**同一套极小接口**的 Tk 实现，`PluginManager` 把它挂在 `api.ui` 上并同时暴露
`api.backend`，插件就可以写成：

    btn = api.ui.button(parent, "解包", on_click=...)
    row = api.ui.row(parent)
    api.ui.label(row, "格式：")

这样插件**只写一遍**，宿主换后端时插件不用改（`api.backend == "qt"` 时由 Qt 实现提供同一套方法）。

接口刻意保持最小：只覆盖插件面板/栏目真正需要的东西（标签、按钮、行容器、勾选框、单行输入、
多行文本、下拉），不试图复刻整套 Tk。**没有**放进来的东西（例如 `CanvasTree`）属于宿主内部件，
插件要树就应通过宿主提供的专用 API，而不是自己造控件 —— 这条边界写在这里，免得以后又长回去。
"""
import tkinter as tk
from tkinter import ttk

__all__ = ["TkUiFactory", "TkTextView", "UI_METHODS"]

# 后端必须实现的同一套方法（探针按这份清单核对 Tk / Qt 两侧一致）。
# 前 8 个是"造控件"，后 6 个是"改控件 / 拿用户输入" —— 后者是迁移
# `engine_utf8_patch` 时按实测补上的：插件真正需要的不只是造控件，还要
# 改标签文字、往只读文本视图里写报告、判控件是否还活着、以及三个标准对话框。
UI_METHODS = ("label", "button", "row", "checkbox", "entry", "text", "combo", "pack",
              "set_text", "text_view", "alive", "ask_yes_no", "ask_open_file",
              "ask_save_file")


class TkTextView:
    """只读多行文本视图（Tk 实现：Frame + Text + Scrollbar）。

    插件拿到的不是裸 `tk.Text`，而是这个小对象：`set_text/clear/alive`。
    这样插件的输出通道就与工具包解耦 —— 原本它直接 `box.configure(state=...)`
    + `box.delete/insert`，那段在 Qt 上完全没有对应写法。
    """

    def __init__(self, frame, text, scrollbar):
        self.widget = frame          # 供宿主布局用的容器
        self.text = text
        self.scrollbar = scrollbar

    def set_text(self, s):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", str(s))
        self.text.configure(state="disabled")

    def clear(self):
        self.set_text("")

    def alive(self):
        try:
            return bool(self.text.winfo_exists())
        except Exception:
            return False

    def get_text(self):
        try:
            return self.text.get("1.0", "end-1c")
        except Exception:
            return ""


class TkUiFactory:
    """`api.ui` 的 Tk 实现（组件懒创建，不引入新的全局状态）。"""

    backend = "tk"

    def __init__(self, role_getter=None):
        # role_getter 由宿主注入（返回主题里的颜色/字体角色）；缺省直接问 toolkit.color，
        # 保证插件面板的文本框与工具包其余部分同色（迁移前这几行是插件自己 `color(...)` 调的）。
        if role_getter is None:
            try:
                from toolkit import color as role_getter
            except Exception:
                role_getter = None
        self._bg = role_getter or (lambda role="bg": None)

    def _role(self, name):
        try:
            return self._bg(name)
        except Exception:
            return None

    # ── 容器 ──────────────────────────────────────────────────────────
    def row(self, parent, side="top", fill="x", expand=False, padx=0, pady=0):
        f = ttk.Frame(parent)
        f.pack(side=side, fill=fill, expand=expand, padx=padx, pady=pady)
        return f

    def pack(self, widget, side="top", fill="x", expand=False, padx=0, pady=0, anchor=None):
        kw = {"side": side, "fill": fill, "expand": expand, "padx": padx, "pady": pady}
        if anchor is not None:
            kw["anchor"] = anchor
        widget.pack(**kw)
        return widget

    # ── 叶子 ──────────────────────────────────────────────────────────
    def label(self, parent, text, style=None):
        kw = {"text": text}
        if style:
            kw["style"] = style
        return ttk.Label(parent, **kw)

    def button(self, parent, text, on_click=None, width=None, style=None, state=None):
        kw = {"text": text}
        if on_click is not None:
            kw["command"] = lambda: on_click()
        if width is not None:
            kw["width"] = width
        if style:
            kw["style"] = style
        if state:
            kw["state"] = state
        return ttk.Button(parent, **kw)

    def checkbox(self, parent, text, variable=None, on_toggle=None):
        kw = {"text": text}
        if variable is not None:
            kw["variable"] = variable
        if on_toggle is not None:
            kw["command"] = lambda: on_toggle()
        return ttk.Checkbutton(parent, **kw)

    def entry(self, parent, textvariable=None, width=None, show=None):
        kw = {}
        if textvariable is not None:
            kw["textvariable"] = textvariable
        if width is not None:
            kw["width"] = width
        if show is not None:
            kw["show"] = show
        return ttk.Entry(parent, **kw)

    def text(self, parent, height=6, width=None, wrap="word"):
        kw = {"height": height, "wrap": wrap}
        if width is not None:
            kw["width"] = width
        return tk.Text(parent, **kw)

    def combo(self, parent, values=(), variable=None, width=None, on_change=None):
        kw = {"values": list(values)}
        if variable is not None:
            kw["textvariable"] = variable
        if width is not None:
            kw["width"] = width
        cb = ttk.Combobox(parent, **kw)
        if on_change is not None:
            def _changed(*_a):
                on_change(cb.get())
            cb.bind("<<ComboboxSelected>>", _changed)
        return cb

    # ── 改控件 / 拿用户输入 ───────────────────────────────────────────
    def set_text(self, widget, text):
        """设置标签文字（Tk: `configure(text=)`；Qt: `setText`）。"""
        try:
            widget.configure(text=str(text))
            return True
        except Exception:
            return False

    def alive(self, widget):
        """控件是否仍然存在（Hub 重建界面后旧面板会失效，插件据此跳过）。"""
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def text_view(self, parent, height=12, mono=True):
        """只读结果视图：结构与本插件迁移前**逐一对等**（Frame + Text + Scrollbar）。

        对等很重要：`run_ext_probe` 有锁检查"面板里有一个 state=disabled 的 tk.Text"，
        换成别的控件类型那条锁就会红 —— 迁移不能顺手改掉可观测的结构。
        """
        from tkinter import font as _tkfont
        frame = ttk.Frame(parent)
        # 不自挂载：与其它叶子一致，交给插件 `ui.pack(view.widget, ...)`（Qt 侧 pack 只是对齐提示）
        kw = {"height": height, "wrap": "word", "relief": "flat", "bd": 0,
              "highlightthickness": 1}
        if mono:
            fam = self._role("font_mono")
            if fam:
                kw["font"] = fam
            else:
                try:
                    kw["font"] = _tkfont.Font(font=("Consolas", 9)).actual()["family"]
                except Exception:
                    pass
        for role, key in (("surface", "bg"), ("text", "fg"), ("border", "highlightbackground")):
            v = self._role(role)
            if v:
                kw[key] = v
        if "fg" in kw:
            kw["insertbackground"] = kw["fg"]      # 迁移前就有的显式项，逐一对等
        box = tk.Text(frame, **kw)
        # 滚动条也走"平时隐藏、装不下才出现"那一套（与六个 App 同一份实现）。
        # 这里是**函数内 import**：本模块的设计目标是"最小契约实现"，顶层只依赖 tkinter；
        # 插件面板只存在于 Hub 进程里（那里 toolkit_widgets 必然已加载），
        # 拿不到时退回 ttk.Scrollbar —— 保证本模块被单独 import 时照样工作（探针会这么做）。
        try:
            from toolkit_widgets import AutoScrollbar as _SB
        except Exception:
            _SB = ttk.Scrollbar
        sb = _SB(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        box.configure(state="disabled")
        return TkTextView(frame, box, sb)

    def ask_yes_no(self, parent, title, message):
        from tkinter import messagebox
        try:
            return bool(messagebox.askyesno(title, message,
                                            parent=self._toplevel(parent)))
        except Exception:
            return False

    def ask_open_file(self, parent, title, filetypes=None, initialdir=""):
        from tkinter import filedialog
        try:
            return filedialog.askopenfilename(parent=self._toplevel(parent), title=title,
                                              initialdir=initialdir,
                                              filetypes=filetypes or ())
        except Exception:
            return ""

    def ask_save_file(self, parent, title, initialdir="", initialfile="", filetypes=None):
        from tkinter import filedialog
        try:
            return filedialog.asksaveasfilename(parent=self._toplevel(parent), title=title,
                                                initialdir=initialdir,
                                                initialfile=initialfile,
                                                filetypes=filetypes or ())
        except Exception:
            return ""

    @staticmethod
    def _toplevel(parent):
        """把任意"父对象"归一成可用的顶层窗口（插件可能传控件、App 实例或 None）。"""
        try:
            if parent is not None and hasattr(parent, "winfo_toplevel"):
                return parent.winfo_toplevel()
            if parent is not None:
                root = getattr(parent, "root", None)
                if root is not None and hasattr(root, "winfo_toplevel"):
                    return root.winfo_toplevel()
        except Exception:
            pass
        return getattr(tk, "_default_root", None)
