# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 通用组件（统一管理，供六个子工具与插件复用）

从 toolkit.py 拆出（方案A 第 4 步）。依赖方向单向: widgets -> theme -> base。
refresh_theme 放在本层：它需要引用 LogBox / CanvasTree.recolor，属组件职责。
"""
import os
import time

import tkinter as tk
from tkinter import ttk

from toolkit_theme import T, color, _role_of, apply_titlebar, px
from toolkit_textio import fmt_size
from toolkit_plugins import LOC_TOOLBAR

# CanvasTree 的 fmt_size 形参会遮蔽同名全局，所以在这里先取一份默认值。
_FMT_SIZE_DEFAULT = fmt_size

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


# ── 输入框的焦点 / 选中收敛（用户口径 2026-09-12）──────────────────────
# 现象（用户原话）：目录栏点进去后光标一直闪（**正常** —— 它要支持键盘输入路径），
# 但**点空白处取消不掉**；而且打开组件后仍停在"某个输入框被选中"的状态。
#
# Tk 的两个默认行为造成了它：
#   * 点 Label / Frame 这类**不可聚焦**控件时，Tk 不会改变焦点 → 焦点仍留在输入框；
#   * `root.focus_set()` 只把焦点拿走，**选中高亮仍留在原地**
#     （实测 `selection_present()` 依旧 True）→ 必须显式 `selection_clear()`。
TEXT_INPUT_CLASSES = ("Entry", "TEntry", "TCombobox", "TSpinbox", "Spinbox",
                      "Text", "TText")


def clear_input_selection(w):
    """清掉一个文本输入控件的选中高亮（按控件能力分派；失败不抛）。"""
    try:
        cls = w.winfo_class()
        if cls in ("Text", "TText"):
            w.tag_remove("sel", "1.0", "end")
        elif cls == "Listbox":
            w.selection_clear(0, "end")
        else:
            w.selection_clear()
        return True
    except Exception:
        return False


def neutralize_input_focus(root):
    """把焦点从文本输入控件上拿走，并清掉它们的选中高亮；返回被清掉选中的控件数。

    只动 `TEXT_INPUT_CLASSES`：**树 / 列表的选中是"内容选择"，不是输入框光标**，
    不该被顺手清掉（它们的键盘导航也要留着）。
    """
    cleared = 0
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass
        try:
            if w.winfo_class() in TEXT_INPUT_CLASSES and w.selection_present():
                if clear_input_selection(w):
                    cleared += 1
        except Exception:
            pass
    try:
        root.focus_set()
    except Exception:
        pass
    return cleared


def install_blank_click_unfocus(widget):
    """在 `widget` 所属 toplevel 上装一次"点空白处取消输入框的焦点与选中"。

    幂等：同一 toplevel 只装一次（`path_row` / `dir_row` / `themed_entry` 都会调它，
    一个组件里几十个输入框也只会挂一个绑定）。判定规则：

      * 点到的东西是输入类控件（或它的子孙）→ **不插手**，交给 Tk 正常处理
        （所以点另一个输入框时焦点会正常转移）；
      * 否则，**只有当前焦点确实落在文本输入控件上**时才动手 —— 点在树/列表的空白上
        不该把它们的键盘导航抢走。

    返回装上的回调（已装过则返回原有回调），便于探针断言。
    """
    try:
        tl = widget.winfo_toplevel()
    except Exception:
        return None
    if getattr(tl, "_dsh_blank_click_hooked", False):
        return getattr(tl, "_dsh_blank_click_handler", None)

    def _on_click(ev):
        try:
            w = ev.widget
        except Exception:
            return
        x = w
        while x is not None:
            try:
                if x.winfo_class() in TEXT_INPUT_CLASSES:
                    return                  # 点到输入框：让 Tk 自己处理
                if x is tl:
                    break
            except Exception:
                break
            x = getattr(x, "master", None)
        try:
            fw = tl.focus_get()
        except Exception:
            fw = None
        if fw is None:
            return
        try:
            if fw.winfo_class() in TEXT_INPUT_CLASSES:
                neutralize_input_focus(tl)
        except Exception:
            pass

    tl.bind("<Button-1>", _on_click, add="+")
    tl._dsh_blank_click_hooked = True
    tl._dsh_blank_click_handler = _on_click
    return _on_click


def install_tab_focus_reset(nb, root):
    """Notebook 切页时收敛输入框的焦点与选中；返回绑定的回调（便于探针直接调）。

    为什么需要它：Tk 切页**不会**动焦点 —— 上一个组件里的输入框即使已经不可见，
    焦点与选中高亮仍留着（切回去光标还停在那儿）。用户口径：打开任意组件后
    不应处于"某个输入框被选中"的状态。
    """
    def _on_change(_ev=None):
        return neutralize_input_focus(root)

    try:
        nb.bind("<<NotebookTabChanged>>", _on_change, add="+")
    except Exception:
        pass
    return _on_change


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
    install_blank_click_unfocus(e)          # 点空白处能取消输入框的焦点/选中
    _ttk.Button(row, text="浏览", width=6, command=browse).pack(side="left", padx=(6, 0))
    return row, e




def _make_pump(root):
    """线程安全 UI 泵: 后台线程把回调投递到队列, 主线程定时执行."""
    import queue as _qq
    _q = _qq.Queue()

    def _ui(fn, *a, **k):
        _q.put((fn, a, k))

    _pump_state = {"dead": False, "reported": False}

    def _root_alive():
        try:
            return bool(root.winfo_exists())
        except Exception:
            return False

    def _pump_trouble(err, phase):
        """泵出问题时留痕。**只报一次**，且只在 root 还活着时报 ——
        正常退出时 root 已销毁、重排程必然失败，那不是故障，不该刷日志。"""
        if _pump_state["reported"]:
            return
        _pump_state["reported"] = True
        try:
            import toolkit_log
            toolkit_log.detail(
                f"UI 回调队列异常（{phase}）: {type(err).__name__}: {err}", "err")
        except Exception:
            pass

    def _reschedule():
        """把 _pump 排回 Tk 事件循环。

        这里是**整个 UI 回调通道的命门**：原先失败被静默吞掉，于是此后所有排队回调
        （进度 / 状态 / on_done / on_error）**再也不执行** —— 任务线程其实已跑完，界面却
        永远停在"运行中"、按钮保持禁用，而且没有任何日志。所以：
          * `after` 成功 → 正常返回（热路径不碰 winfo_exists，避免多余 Tcl 调用）；
          * 失败且 root 已销毁 → 正常退出，直接返回，不重试也不报错；
          * 失败但 root 还活着 → **重试一次**，仍失败才置 `dead` 并留痕（只报一次）。
        """
        try:
            root.after(30, _pump)
            return
        except Exception as e:
            first = e
        if not _root_alive():
            return
        try:
            root.after(30, _pump)
            return
        except Exception:
            pass
        _pump_state["dead"] = True
        _pump_trouble(first, "重排程失败")

    def _pump():
        while True:
            try:
                fn, a, k = _q.get_nowait()
            except _qq.Empty:
                break                      # 队列空了 = **正常出口**，不是故障
            except Exception as e:
                _pump_trouble(e, "取队列失败")
                break
            try:
                fn(*a, **k)
            except Exception as e:
                # 不静默：UI 回调失败（控件已销毁、状态回调写错属性…）
                # 会让"任务跑完了但界面没变"，原先这里完全无声。
                # 只写落盘日志（detail），避免经由 GUI sink 递归回灌队列。
                try:
                    import toolkit_log
                    toolkit_log.detail(
                        f"UI 回调失败: {getattr(fn, '__name__', fn)} — "
                        f"{type(e).__name__}: {e}", "err")
                except Exception:
                    pass
        _reschedule()

    _reschedule()
    return _ui



# ═══════════════════════════════════════════════════════════════
# 任务与状态模型（能力 1：六个 App 共用，不再各抄一套任务壳）
# ═══════════════════════════════════════════════════════════════

# 状态语义 → 主题角色。所有"运行中/完成/失败"的着色都经此，不写字面量。
_STATUS_ROLES = {"running": "yellow", "ok": "green", "err": "red",
                 "warn": "yellow", "dim": "text_dim", "idle": "text"}


def status_style(kind):
    """状态语义 → 颜色（经 color()，随主题切换）。"""
    role = _STATUS_ROLES.get(kind, "text")
    try:
        return color(role)
    except Exception:
        return T.get(role, "")


# 状态语义 → ttk 样式名（对应 toolkit_theme.apply_theme 里注册的那些 *TLabel）
_STATUS_TTK_STYLES = {"running": "Yellow.TLabel", "ok": "Green.TLabel",
                      "err": "Red.TLabel", "warn": "Yellow.TLabel",
                      "dim": "Dim.TLabel", "idle": "Dim.TLabel"}


def status_style_name(kind):
    """状态语义 → ttk 样式名（用于 ttk.Label.configure(style=...)）。"""
    return _STATUS_TTK_STYLES.get(kind, "Dim.TLabel")


class TaskRunner:
    """统一后台任务壳：忙碌标志、进度条、状态文案、线程与完成回调。

    取代六个 App 里各自实现的那一套（`self.running` + `Progressbar.start/stop`
    + `threading.Thread(daemon=True)` + `self._ui(...)` 回主线程）。

    两种进度形态都支持：
        indeterminate（默认）——只表示"忙"，传 progress_started/stopped；
        determinate   ——另有 progress_update(done, total) / set_progress(pct)，
                         并可传 progress_var / progress_label 直接绑定控件。

    失败绝不静默：on_error 未提供时写 summary/err 日志。
    用法::

        self.task = TaskRunner(root, self._ui, on_busy=self._set_ui_state,
                               status_setter=lambda t, k="idle": lbl.configure(
                                   text=t, foreground=status_style(k)),
                               progress_started=self.progress.start,
                               progress_stopped=self.progress.stop)
        ...
        self.task.run(work)                       # 工作线程里跑 work()
        self.task.run(work, on_error=self._fail)  # 失败时回调
    """

    def __init__(self, root, ui, on_busy=None, status_setter=None,
                 progress_started=None, progress_stopped=None,
                 progress_var=None, progress_label=None, progress_setter=None):
        self._root = root
        self._ui = ui
        self._on_busy = on_busy
        self._status_setter = status_setter
        self._progress_started = progress_started
        self._progress_stopped = progress_stopped
        self._progress_var = progress_var
        self._progress_label = progress_label
        self._progress_setter = progress_setter
        self.running = False
        self._status_text = ""
        self._status_kind = "idle"
        self._error_status = None      # on_error 里 set_status(...) 写入的失败状态
        import threading as _th
        self._lock = _th.RLock()

    # ── 状态 ──
    def set_status(self, text, kind="idle"):
        """写入状态文案 + 语义色；同时记住，供主题切换后重取颜色。"""
        self._status_text = text
        self._status_kind = kind
        if self._status_setter is None:
            return
        try:
            self._status_setter(text, kind)
        except TypeError:
            try:
                self._status_setter(text)      # 兼容只接受 text 的旧回调
            except Exception:
                pass
        except Exception:
            pass

    def refresh_theme(self):
        """主题切换后按已记住的语义重取颜色（不改变文案与语义）。"""
        self.set_status(self._status_text, self._status_kind)

    # ── 进度 ──
    def set_progress(self, pct):
        """写入进度（0~100）。三种绑定方式任选其一：progress_var / progress_setter。"""
        if self._progress_setter is not None:
            try:
                self._progress_setter(pct)
            except Exception:
                pass
        if self._progress_var is not None:
            try:
                self._progress_var.set(pct)
            except Exception:
                pass

    def reset_progress(self):
        """任务开始前把进度归零。"""
        self.set_progress(0)

    def progress_update(self, done, total):
        """确定进度：按 done/total 更新进度条与文案。"""
        if total:
            self.set_progress(done * 100.0 / total)
        if self._progress_label is not None:
            try:
                self._progress_label.config(text=f"{done} / {total}")
            except Exception:
                pass

    def _start_progress(self):
        if self._progress_started is not None:
            try:
                self._progress_started()
            except Exception:
                pass

    def _stop_progress(self):
        if self._progress_stopped is not None:
            try:
                self._progress_stopped()
            except Exception:
                pass

    # ── 运行 ──
    def run(self, work, status=None, on_error=None, final_status=None):
        """在工作线程里执行 work()；已在跑则返回 False（重入保护）。

        final_status: (text, kind) —— 任务结束（成功或失败）后写入的收尾状态。
        """
        with self._lock:
            if self.running:
                return False
            self.running = True        # 必须在启动线程**之前**置位：
            # 否则瞬间完成的任务会在 start() 返回前就跑完 _finish，把标志复位，
            # 于是并发守卫失效。
            if self._on_busy is not None:
                try:
                    self._on_busy(True)
                except Exception:
                    pass

        if status is not None:
            self.set_status(status, "running")
        self._start_progress()
        import threading

        def _wrapper():
            try:
                work()
            except Exception as e:
                if on_error is not None:
                    # on_error **必须回到主线程**执行：各 App 的 on_error 都会
                    # set_status / 改控件，在工作线程里直接碰 Tk 是未定义行为。
                    # 原先这里直接 on_error(e)，失败路径就成了"后台线程改 Tk"。
                    self._ui(self._handle_error, on_error, e)
                try:
                    import toolkit_log
                    toolkit_log.summary(f"后台任务失败: {e}", "err")
                except Exception:
                    pass
            finally:
                # _handle_error 先入队、_finish 后入队，同一队列保证顺序：
                # _finish 读到的一定是 on_error 写下的失败状态。
                self._ui(self._finish, final_status)

        threading.Thread(target=_wrapper, daemon=True).start()
        return True

    def _handle_error(self, on_error, exc):
        """失败回调的**主线程**执行点：跑 App 的 on_error，并记住它写的状态。

        单独成方法而不是在 _wrapper 里内联，是因为 _wrapper 在工作线程上——
        这里必须由 _ui 投递回来执行。
        """
        try:
            on_error(exc)
        except Exception as e:
            try:
                import toolkit_log
                toolkit_log.detail(f"on_error 回调失败: {type(e).__name__}: {e}", "err")
            except Exception:
                pass
        # 错误回调若已写状态，则收尾不再用成功状态覆盖它
        self._error_status = self._status_text

    def _finish(self, final_status=None):
        """任务收尾（已投递回主线程）：复位忙碌态、停进度、写收尾状态。"""
        self.running = False
        self._stop_progress()
        if final_status is not None and self._error_status is None:
            try:
                self.set_status(final_status[0], final_status[1])
            except Exception:
                pass
        self._error_status = None
        if self._on_busy is not None:
            try:
                self._on_busy(False)
            except Exception:
                pass



# ═══ 同类功能各自一个函数 ═══
def themed_entry(parent, textvariable=None, width=None, font_role="font_mono",
                 state=None, **kw):
    """带主题边框的输入框。

    背景/前景/插入光标/边框高亮全部取自主题，调用方**不再手写配色**——
    原先 font_pack_app 有多处逐字重复的 9 个关键字串，正是本工厂要消掉的东西。
    """
    from tkinter import Entry as _Entry
    cfg = dict(textvariable=textvariable, bg=color("entry_bg"), fg=color("text"),
               insertbackground=color("text"), relief="flat", bd=0,
               highlightthickness=1, highlightbackground=color("border"),
               highlightcolor=color("accent"), font=color(font_role))
    if width is not None:
        cfg["width"] = width
    if state is not None:
        cfg["state"] = state
    cfg.update(kw)
    e = _Entry(parent, **cfg)
    install_blank_click_unfocus(e)          # 点空白处能取消输入框的焦点/选中
    return e


def themed_listbox(parent, width=None, height=None, **kw):
    """带主题配色的列表框（选色/边框/字体统一）。"""
    import tkinter as _tk
    cfg = dict(bg=color("entry_bg"), fg=color("text"),
               selectbackground=color("selected"), selectforeground=color("text_bright"),
               font=color("font"), relief="flat", bd=0, highlightthickness=1,
               highlightbackground=color("border"), highlightcolor=color("accent"))
    if width is not None:
        cfg["width"] = width
    if height is not None:
        cfg["height"] = height
    cfg.update(kw)
    return _tk.Listbox(parent, **cfg)


def dialog_window(parent, title, size=None, minsize=None, transient=True):
    """统一的模态弹窗外壳：置顶、跟随主题底色、**标题栏同样跟随主题**、可选尺寸。

    font_pack 的"选择字体"与 xml_compare 的"差异详情"原先各写一遍
    （Toplevel + title + geometry + configure(bg=...) + transient）。

    size / minsize 按 **96 DPI 的设计值**给（如 "650x450"），这里统一按当前缩放
    换算成物理像素 —— 否则 150% 屏上弹窗会明显偏小。
    """
    import tkinter as _tk
    win = _tk.Toplevel(parent)
    win.title(title)
    if size:
        win.geometry(_scale_geometry(size))
    if minsize:
        win.minsize(*[px(v) for v in minsize])
    win.configure(bg=color("bg"))
    if transient:
        try:
            win.transient(parent)
        except Exception:
            pass
    # 标题栏也被统一到主题代码里：以前只有 Hub 调 apply_titlebar，
    # 于是暗色主题下弹窗顶着一条亮色标题栏。
    try:
        apply_titlebar(win)
    except Exception:
        pass
    return win


def _scale_geometry(spec):
    """"650x450" → 按当前缩放换算后的 "975x675"；+X+Y 之类的偏移原样保留。"""
    try:
        geo, _sep, rest = str(spec).partition("+")
        w, _x, h = geo.partition("x")
        out = "%dx%d" % (px(int(w)), px(int(h)))
        return out + ("+" + rest if _sep else "")
    except Exception:
        return spec


def tool_button(parent, text, command=None, font_role="font", width=None, **kw):
    """统一按钮：样式与字体取自主题，不再逐处传 font=/配色。

    （ttk.Button 已由 apply_theme 的样式覆盖；本工厂主要服务 tk.Button，
    因为原生按钮的字体需要显式给 —— 原先各 App 反复写 font=self.font_ui。）
    """
    import tkinter as _tk
    cfg = dict(text=text, font=color(font_role))
    if command is not None:
        cfg["command"] = command
    if width is not None:
        cfg["width"] = width
    cfg.update(kw)
    return _tk.Button(parent, **cfg)


def tool_label(parent, text, font_role="font", fg_role=None, **kw):
    """统一原生标签：字体与前景色取自主题，不再逐处传 font=self.font_ui / fg=color(...)。

    需要语义色时传 fg_role（如 "text_dim"/"green"），需要动态改色则之后自己 configure。
    """
    import tkinter as _tk
    cfg = dict(text=text, font=color(font_role))
    if fg_role:
        cfg["fg"] = color(fg_role)
    cfg.update(kw)
    return _tk.Label(parent, **cfg)


def stat_grid(parent, items):
    """统一统计网格：每组 (标题, 数值属性名, 说明属性名) → 三个 ttk.Label。

    返回 {属性名: label} 字典；调用方按属性名更新即可。
    原先 text_extract_app 用 for + setattr 手搭一遍（含分隔线间距）。
    布局是"按 items 顺序横排 + 分隔线"，没有可配的列数 —— 原先的
    `columns=3` 形参完全没被用到（只有默认调用），已删除。
    """
    from tkinter import ttk as _ttk
    inner = _ttk.Frame(parent)
    inner.pack(fill="x")
    made = {}
    for i, (title, stat_attr, detail_attr) in enumerate(items):
        if i > 0:
            _ttk.Separator(inner, orient="vertical").pack(
                side="left", fill="y", padx=20)
        col = _ttk.Frame(inner)
        col.pack(side="left", expand=True)
        _ttk.Label(col, text=title, style=status_style_name("dim")).pack()
        lbl = _ttk.Label(col, text="—", style="Stats.TLabel")
        lbl.pack()
        det = _ttk.Label(col, text="", style=status_style_name("dim"))
        det.pack()
        made[stat_attr] = lbl
        made[detail_attr] = det
    return made


def dir_row(parent, label, var, browse=None, drop=None, add=None, width=8, state=None):
    """统一目录行: 标签 + 输入框(带边框) + 浏览按钮;
    可选: drop 拖拽回调, add 附加按钮 (text, command), state 输入框状态.
    返回 (row_frame, entry)."""
    from tkinter import ttk as _ttk
    from tkinter import Entry as _Entry
    row = _ttk.Frame(parent)
    # 留白（2026-09-13 排版统一）：组内行距 6、行与行之间靠这个 pady 拉开。
    # 原来只有 4px，六个页面里"输入/输出/搜索"这几行会挤成一片。
    row.pack(fill="x", pady=(0, 6))
    if label:
        _ttk.Label(row, text=label, width=width).pack(side="left", padx=(0, 6))
    e = _Entry(row, textvariable=var, bg=color("entry_bg"), fg=color("text"),
               insertbackground=color("text"), relief="flat", bd=0,
               disabledbackground=color("entry_bg"), disabledforeground=color("text"),
               highlightthickness=1, highlightbackground=color("border"),
               highlightcolor=color("accent"), font=T["font_mono"])
    if state:
        e.configure(state=state)
    e.pack(side="left", fill="x", expand=True, ipady=4)
    if drop is not None:
        try:
            if hasattr(e, "drop_target_register"):
                e.drop_target_register("DND_Files")
                e.dnd_bind("<<Drop>>", drop)
        except Exception:
            pass
    if browse:
        _ttk.Button(row, text="浏览", width=6, command=browse).pack(side="left", padx=(8, 0))
    if add:
        _ttk.Button(row, text=add[0], width=6, command=add[1]).pack(side="left", padx=(6, 0))
    install_blank_click_unfocus(e)          # 点空白处能取消输入框的焦点/选中
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
    """统一工具页大标题 (tool_text 的 title 别名) + 一条极细分隔线。

    用户授权（2026-09-13）"布局和交互也可以动，按你的审美来"。
    大标题下面那条 1px 弱线是**信息层级**的锚点：它把"页面标题"和"下面的表单"
    在视觉上分成两层，比加粗或用更亮的字更省地方。用弱色（border）而不是强调色，
    免得六个页面各飘一条蓝线。
    """
    wrap = ttk.Frame(parent)
    kw = {"anchor": "w", "padx": 14, "pady": (12, 0)}
    kw.update(pack_kw)
    wrap.pack(fill="x")
    lbl = tool_text(wrap, text, kind="title", **kw)
    # 用 ttk.Separator 而不是 tk.Frame：它的颜色由 `TSeparator` 样式给（= 主题的 border），
    # 切亮/暗主题时**自动**跟着变；tk.Frame 得自己接进 recolor 链路，反而多一处会忘的接线。
    ttk.Separator(wrap, orient="horizontal").pack(fill="x", padx=14, pady=(6, 8))
    return lbl

class ScrollPanel(ttk.LabelFrame):
    """**统一滚动面板**：带标题的面板 + 内部视口（横/纵滚动条自动隐藏）。

    用户口径 2026-09-13：

    > "这边几个按钮被遮住了，但是底下仍然没有滚动条出现。底下滚动条出现的条件是该窗口
    >  有东西显示不完全。包括控件和里面的内容。……这种控件不应该是统一写统一调用的吗？"

    所以这条做成**一个类、六页统一调用**，出现条件就是用户那句话：
    **面板里有东西显示不完全**（按内容实际需要 vs 可视区，不看窗格宽窄），
    滚动条画在**面板内部**（不是窗格级 —— 窗格级会画到面板外面，已撤）。

    用法（页面只往 `body` 里建东西）：

        panel = ScrollPanel(container, "包内文件")
        panel.pack(fill="both", expand=True)
        ttk.Button(panel.body, text="全选").pack(side="left")
    """

    def __init__(self, parent, title="", padding=6, **kw):
        super().__init__(parent, text=title, padding=padding, **kw)
        self.view = ScrollViewport(self, horizontal=True)
        self.view.pack(fill="both", expand=True)
        self.body = self.view.content          # 调用方往这里建控件

    def refresh(self):
        """内容变了（加/删控件、改文字）之后调用，让滚动条重新判断要不要出现。"""
        self.view._sync()

    def recolor(self):
        self.view.recolor()


class ScrollViewport(ttk.Frame):
    """可裁剪 + 可滚动的视口；滚动条**平时隐藏**，装不下才出现。

    用户口径（2026-09-12）：

    * 内容**保持自己的自然尺寸**，不因为视口变窄/变矮被压扁 —— 装不下就该滚；
    * 视口比内容大时，内容**铺满**视口（此时没有滚动条，也没有多余留白）；
    * 纵向默认开启；`horizontal=True` 再加横向（横向时内容**左对齐**、由 `anchor="nw"`
      保证，宽度取"自然宽度"而不是被拉平）。

    `minsize_y` / `minsize_x` 是"内容至少要多高/多宽"：宿主用它表达"两栏的最小高度之和"，
    于是窗口小于这个值时窗口级滚动条出现，而不是把两栏压没。

    为什么非用 Canvas：Tk 里只有 canvas 能把任意控件树"裁剪 + 滚动"。
    内容树挂在 `self.content` 下，调用方照旧 `pack`/`grid`。
    """

    def __init__(self, master=None, horizontal=False, minsize_y=0, minsize_x=0,
                 fit="viewport", **kw):
        super().__init__(master, **kw)
        self._horizontal = bool(horizontal)
        self._min_y = int(minsize_y or 0)
        self._min_x = int(minsize_x or 0)
        # fit="viewport"：内容高 = max(minsize_y, 视口高) —— 内容**跟着视口**（铺满、不溢出）。
        # fit="content" ：内容高 = max(内容请求高, minsize_y, 视口高) —— 内容**保持自己的高度**，
        #   视口矮了就滚。栏目区 pane 用后者：页面要 720 高时它不该被压扁，而该让 pane 自己滚
        #   （用户口径 2026-09-13："日志是不归主窗口滚动条管的" —— 反过来栏目区该自己管自己）。
        self._fit = fit if fit in ("viewport", "content") else "viewport"
        self.canvas = tk.Canvas(self, bg=color("bg"), highlightthickness=0, bd=0)
        self.vbar = AutoScrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = (AutoScrollbar(self, orient="horizontal", command=self.canvas.xview)
                     if self._horizontal else None)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        if self.hbar is not None:
            self.canvas.configure(xscrollcommand=self.hbar.set)
            self.hbar.pack(side="bottom", fill="x")
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=color("bg"))
        self.content._scroll_viewport = self     # 主题切换遍历时能找回视口
        self._win = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        # 内容自己变尺寸（加控件/换行）与视口变尺寸都要重算
        self.content.bind("<Configure>", lambda _e: self._sync(), add="+")
        self.canvas.bind("<Configure>", lambda _e: self._sync(), add="+")

    def _sync(self):
        """把内容窗口的尺寸与 scrollregion 对齐到"视口 ∪ 显式最小尺寸"。

        **不许用内容的"请求高度"**（2026-08-13 实机截图抓到的 bug）：容器（SplitPane 之类）
        的请求高度 = 内部各栏请求之和，通常**远大于**视口 —— 一旦把它当内容高度，
        视口就永远装不下：右侧常驻一条滚动条、而且内容底部被裁掉（实测发行包里"封包"
        面板下半截看不见）。高度只该由**显式的 `minsize_y`** 决定：
        窗口比它高 → 内容=视口（铺满、无滚动条）；比它矮 → 内容=最小高度（滚动条出现）。
        宽度只在 `horizontal=True`（左右分栏那种）时才用内容自然宽 —— 那是用户要的
        "装不下就横向滚、内容左对齐"，而纵向视口里内容照旧横向铺满。
        """
        try:
            vw = max(1, self.canvas.winfo_width())
            vh = max(1, self.canvas.winfo_height())
            if self._fit == "content":
                need_h = max(self.content.winfo_reqheight(), self._min_y, vh)
            else:
                need_h = max(self._min_y, vh)
            need_w = vw
            if self._horizontal:
                need_w = max(self.content.winfo_reqwidth(), self._min_x, vw)
            self.canvas.itemconfigure(self._win, width=need_w, height=need_h)
            self.canvas.configure(scrollregion=(0, 0, need_w, need_h))
        except Exception:
            pass

    def try_scroll(self, event):
        """给**全局滚轮路由**调用：能滚就滚、返回 True；滚不动返回 False。

        为什么需要它（用户口径 2026-09-13："窗口内还是不能滚轮操控"）：
        Tk 的滚轮只送到"指针下那个控件"的 bindtags（控件 → 类 → **顶层** → all），
        而面板内部的视口 canvas **不在**那条链上 —— 于是面板自己的视口永远收不到滚轮，
        只剩顶层那一个处理器在工作。正确做法不是给每个控件各绑一次，而是
        **一个路由**：从 `event.widget` 沿 `master` 链往上找第一个能滚的视口（见
        `stalker_toolkit` 里的 `_wheel_router`）。
        """
        try:
            before = self.canvas.yview()
            if before == (0.0, 1.0):
                return False                      # 装得下
            step = -1 if getattr(event, "delta", 0) > 0 else 1
            self.canvas.yview_scroll(step * 3, "units")
            return self.canvas.yview() != before
        except Exception:
            return False

    def scroll_wheel(self, event):
        """视口滚轮：**能滚才吃掉事件**，滚不动就放行（统一规则，与内层控件一致）。

        绑在 toplevel 上（见 Hub 主界面）。两条规则合起来才是用户要的"统一"：
          * 内层自己能滚的控件（树/文本框）：`CanvasTree._on_wheel` 只在真的滚了时 break；
            `tk.Text`/`tk.Listbox` 由 Tk 自己的类绑定处理（它**不** break）——
            所以这里要主动**跳过**它们，否则会出现"文本框滚了、整页也跟着滚"的双滚。
          * 内层滚不动的（空树、日志到底、面板空白处）：事件走到这里，由本视口滚整页。
        """
        try:
            w = getattr(event, "widget", None)
            inner = getattr(w, "_ctree", None) is not None          # CanvasTree 的画布
            try:
                import tkinter as _tk
                inner = inner or isinstance(w, (_tk.Text, _tk.Listbox))
            except Exception:
                pass
            if inner:
                return None                     # 交给内层自己，别双滚
            first, last = self.canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return None                     # 装得下 → 不拦截（放行给更外层）
            before = (first, last)
            step = -1 if getattr(event, "delta", 0) > 0 else 1
            self.canvas.yview_scroll(step * 3, "units")
            if self.canvas.yview() == before:
                return None                     # 已经在头/尾，滚不动了 → 交给外层
            return "break"
        except Exception:
            return None

    def recolor(self):
        """主题切换：canvas 底色要自己跟（滚动条走 ttk 样式）。"""
        try:
            self.canvas.configure(bg=color("bg"))
            self.content.configure(bg=color("bg"))
        except Exception:
            pass
        self._sync()


class AutoScrollbar(ttk.Scrollbar):
    """平时**隐藏**、内容超出时才出现的滚动条 —— `ttk.Scrollbar` 的直接替代。

    ## 用法（调用方一行都不用改）

        vsb = AutoScrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)      # 原样
        vsb.pack(side="right", fill="y")            # 原样（grid 也一样）

    本类记住调用方用的布局参数，之后按"内容装不装得下"自己出现/收起。

    ## 判定与滞回

    被滚控件每次滚动或尺寸变化都会回调 `set(first, last)`：
    `first <= 0 且 last >= 1` 即"完全装得下" → 收起。
    用 `>= 1`（而不是 `>= 0.999`）是**刻意留滞回**：滚动条一出现就占掉宽度，
    内容变窄后可能又"刚好装得下"→ 收起 → 又超出 → 出现，肉眼就是闪。
    真正装得下时 Tk 给的 `last` 恰好是 `1.0`，所以这条界线不会误判。

    ## 为什么需要它（用户口径 2026-09-12）

    滚动条不该常驻：装得下的时候它是纯噪声，还白占宽度、把内容挤窄。
    Tk 的 `ttk.Scrollbar` 没有这个能力，只能在组件层实现。
    """

    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._geom = None          # ("pack"/"grid"/"place", kwargs) —— 调用方的布局参数
        self._visible = True
        self._needed = None

    # ── 记住调用方的布局参数（三种几何管理器都覆盖）────────────────────
    def pack(self, **kw):
        self._geom = ("pack", dict(kw))
        return super().pack(**kw)

    def grid(self, **kw):
        self._geom = ("grid", dict(kw))
        return super().grid(**kw)

    def place(self, **kw):
        self._geom = ("place", dict(kw))
        return super().place(**kw)

    # ── 由被滚控件回调 ────────────────────────────────────────────────
    def set(self, first, last):
        try:
            lo, hi = float(first), float(last)
        except (TypeError, ValueError):
            return                      # 控件销毁时 Tk 会发空串，保持现状
        needed = not (lo <= 0.0 and hi >= 1.0)
        if needed != self._needed:
            self._needed = needed
            self._apply(needed)
        try:
            super().set(first, last)    # 交给 ttk.Scrollbar 画滑块位置
        except Exception:
            pass

    def needed(self):
        """当前是否需要（None = 还没收到过 set）。"""
        return self._needed

    def visible(self):
        return self._visible

    # ── 出现/收起 ─────────────────────────────────────────────────────
    def _apply(self, needed):
        try:
            if needed and not self._visible:
                self._show()
            elif not needed and self._visible:
                self._hide()
        except Exception:
            pass

    def _hide(self):
        if self._geom is None:
            # 还没布局过（构建期就收到了 set）——只记状态，等调用方 pack/grid 时
            # 由 `_needed` 在下次 set 时处理；此时它本来也没显示，不算错。
            self._visible = False
            return
        kind = self._geom[0]
        try:
            if kind == "pack":
                super().pack_forget()
            elif kind == "grid":
                self.grid_remove()      # grid_remove 会记住格位，放回时不用重算
            else:
                self.place_forget()
        finally:
            self._visible = False

    def _show(self):
        if self._geom is None:
            self._visible = True
            return
        kind, kw = self._geom
        try:
            if kind == "pack":
                super().pack(**kw)      # 注意：pack 放回会排在末尾（调用方一般只放一个滚轴）
            elif kind == "grid":
                self.grid(**kw)
            else:
                self.place(**kw)
        finally:
            self._visible = True


class BusyOverlay(tk.Frame):
    """启动/重建期间的**加载遮罩**：一个转圈 + 一行字，盖住内容区。

    用户口径 2026-09-13："整个窗口在没有完全加载的时候显示加载转圈，直接看着控件一个个
    跳出来太难看了。"

    背景：启动是**分帧装配**的（首栏目同步、其余每帧一个，见 `build_tabs`）—— 这是为了
    让 mainloop 尽早跑起来（否则窗口画出来却点不动 1~2 秒）。代价就是用户会看到控件逐个
    跳出来。遮罩把这段过程盖住，装配完由 `on_done` 摘掉。

    要点：
      * 动画用 `after` 逐帧改 `create_arc` 的 `start` 角（不用图片、不占线程）；
      * **看门狗**：`MAX_MS` 到点强制收掉 —— 万一 `on_done` 因为异常没被调用，
        遮罩绝不能永远盖着（那比"控件跳出来"严重得多）；
      * `stop()` 幂等，且会取消挂着的 `after`（不留孤儿定时器）。
    """

    R = 22            # 转圈半径（逻辑像素，实例化时按缩放换算）
    WIDTH = 4         # 线宽
    STEP_MS = 70      # 每帧间隔
    STEP_DEG = 30     # 每帧转多少度
    MAX_MS = 20000    # 看门狗：最多盖 20 秒

    def __init__(self, master=None, text="正在加载…", **kw):
        super().__init__(master, bg=color("bg"), **kw)
        self._after = None
        self._watch = None
        self._angle = 0
        self._scale = max(1, px(1))
        # 内容居中：外层铺满父容器，内层 place 到正中（第一版把 canvas/label 直接 pack
        # 在外层上 → 跑到顶部居中，实机截图里"转圈看不见、文字贴在上边"，很难看）。
        self._inner = tk.Frame(self, bg=color("bg"))
        self._inner.place(relx=0.5, rely=0.5, anchor="center")
        box = (self.R + self.WIDTH) * 2 * self._scale
        self._canvas = tk.Canvas(self._inner, width=box, height=box, bg=color("bg"),
                                 highlightthickness=0, bd=0)
        self._canvas.pack(pady=(0, 10))
        r = self.R * self._scale
        w = max(2, self.WIDTH * self._scale)
        c = box // 2
        # 底层：一整圈"轨道"（弱色）—— 没有它时单看一小段弧几乎看不见
        self._track = self._canvas.create_oval(c - r, c - r, c + r, c + r,
                                               outline=color("surface2"), width=w)
        # 上层：转动的弧（强调色），比第一版更长更粗
        self._arc = self._canvas.create_arc(c - r, c - r, c + r, c + r,
                                            start=0, extent=110, style="arc",
                                            outline=color("accent"), width=w)
        self._label = ttk.Label(self._inner, text=text, style="Dim.TLabel")
        self._label.pack()

    # ── 显示 / 收掉 ────────────────────────────────────────────────────
    def start(self):
        """铺满父容器并开始转。"""
        try:
            self.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            self.lift()
        except Exception:
            pass
        self._tick()
        try:
            if self._watch is not None:
                self.after_cancel(self._watch)
            self._watch = self.after(self.MAX_MS, self.stop)
        except Exception:
            self._watch = None
        return self

    def stop(self):
        """收掉遮罩并取消所有挂着的定时器（**幂等**）。"""
        for attr in ("_after", "_watch"):
            h = getattr(self, attr, None)
            if h is not None:
                try:
                    self.after_cancel(h)
                except Exception:
                    pass
                setattr(self, attr, None)
        try:
            self.place_forget()
        except Exception:
            pass
        return self

    def running(self):
        return self._after is not None

    def angle(self):
        return self._angle

    def _tick(self):
        self._after = None
        try:
            self._angle = (self._angle + self.STEP_DEG) % 360
            self._canvas.itemconfigure(self._arc, start=self._angle)
        except Exception:
            return
        try:
            if self.winfo_exists():
                self._after = self.after(self.STEP_MS, self._tick)
        except Exception:
            self._after = None

    def recolor(self):
        try:
            self.configure(bg=color("bg"))
            self._inner.configure(bg=color("bg"))
            self._canvas.configure(bg=color("bg"))
            self._canvas.itemconfigure(self._track, outline=color("surface2"))
            self._canvas.itemconfigure(self._arc, outline=color("accent"))
        except Exception:
            pass


def vscrollbar(parent, target):
    """统一垂直滚动条, 绑定 target 的 yview; 自动 pack 右侧（内容装得下时自动隐藏）."""
    sb = AutoScrollbar(parent, orient="vertical", command=target.yview)
    target.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    return sb


def drop_zone(parent, title, placeholder, on_file=None, filetypes=None, pick_title=None):
    """统一拖放槽: LabelFrame(标题) + 大点击/拖拽区域 (如视频OGM 源文件槽).

    点击与拖入**都**会走 on_file(path)：`_pick` 默认接一个文件选择框，
    这样占位文案里的"或点击选择"才是真的（此前 `_pick` 恒为 None，
    点击什么都没有发生，而两处占位文案都写着"或点击选择"）。
    filetypes / pick_title 供调用方自定义选择框。
    返回 label (可 show_file 更新文本)."""
    from tkinter import ttk as _ttk, filedialog as _fd
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

    def _pick():
        if on_file is None:
            return
        path = _fd.askopenfilename(
            title=pick_title or f"选择{title}",
            filetypes=list(filetypes) if filetypes else [("所有文件", "*.*")],
        )
        if path:
            on_file(path)

    lbl._pick = _pick

    def _click(e):
        if lbl._pick:
            lbl._pick()
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
                         state="disabled", height=height,
                         # 同 CanvasTree 的理由：`tk.Text` 默认请求宽度是 **80 字符**
                         # （≈640px），而窗格/窗口的"内容宽度"按请求宽度算 —— 会给
                         # ttk.Panedwindow 一个虚高的下限（拖分隔条被它挡住），
                         # 在裁剪窗格里还会让面板被撑到窗格之外。宽度本来就由 fill/expand 决定。
                         width=1)
        self._timestamp = timestamp
        self._tag_roles = self._BASE_TAGS + (tags or [])
        self.recolor()
        if scrollbar:
            sb = AutoScrollbar(parent, orient="vertical", command=self.yview)
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
        """清空日志（含尚未落屏的 pending 缓冲）。

        **必须经这里清空，不要直接 `widget.delete("1.0","end")`**：LogBox 建成后
        是 `state="disabled"`，而 Tk 对 disabled 的 Text 会**静默忽略** insert /
        delete —— 直接删点了没有任何反应，也不报错，很难查。
        """
        self._pending = None
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
    # 以下均为 **96 DPI 的设计值**；实例化时按当前缩放换算成 self.*（见 __init__）。
    # 不能写死：150% 屏上正文行高是 32px，而 ROW_H=24 会让行比字矮 —— 文字被裁，
    # 看起来就是"糊"。类属性只作为兜底，实际渲染一律走 self.*。
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
        self.fmt_size = fmt_size or _FMT_SIZE_DEFAULT
        self.on_change = on_change
        import tkinter.font as _tkf
        self._mfont = _tkf.Font(font=T["font_mono"])
        # 按当前缩放换算（px() 的基准是 96 DPI）。行高取"设计值"与"正文行高+余量"
        # 的较大者，保证任何缩放下文字都不会被裁。
        self.CHK_PAD = max(px(6), 2)
        self.CHK = max(px(14), 12)
        self.INDENT = max(px(24), self.CHK + px(8))
        self.ROW_H = max(px(24), self._mfont.metrics("linespace") + px(6))
        self.frame = ttk.Frame(master)
        # canvas 的 height 只是**请求最小值**（外面一律 pack(fill="both", expand=True)，
        # 有空间就会长）。原来给 px(300)：一页里两三个 CanvasTree 就把页面的请求高度
        # 顶到 700+ px，于是 Hub 的 Notebook 请求高度超过窗口，ttk.Panedwindow 只能把
        # 最后一个 pane（日志栏）压成 1 px（实测 1024x700 / 1280x860，见 UI 回执）。
        # px(120) 仍够显示 4~5 行，且不再绑架整页布局。
        # **宽度必须显式给小**（2026-09-13 实机抓到的 bug）：`tk.Canvas` 不给 width 时
        # 默认请求宽度是 **378px**，而窗格里的"内容宽度"就是按请求宽度算的 —— 于是
        # "内容比窗格宽"永远成立：面板被撑到窗格之外（**右边框被裁掉**）、
        # 底部还常驻一条横向滚动条。树本来就是宽度弹性的，请求宽度给 1 个设计像素即可
        # （外面一律 fill/expand，有空间就长）。
        self.canvas = tk.Canvas(self.frame, bg=T["surface"], highlightthickness=0,
                                height=px(120), width=px(1), bd=0)
        self.canvas._ctree = self  # 主题切换遍历时定位到本 wrapper
        self.vbar = AutoScrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._yscrollcmd)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        self.rows = []
        self._sel = set()
        self._expanded = set()
        self.root = None; self.q = ""
        self._press = None; self._drag = False
        self._draw_after = None
        self._ctx = tk.Menu(self.frame, tearoff=0, bg=T["surface2"], fg=T["text"], font=T["font"])
        self._ctx.add_command(label="选中打勾", command=lambda: self._ctx_set(True))
        self._ctx.add_command(label="取消打勾", command=lambda: self._ctx_set(False))
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_rclick)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # <Configure> 走**去抖**：拖窗口边框时 canvas 每次都变尺寸，逐次 delete("all")
        # 重建可见行是纯浪费（实测每个 Configure 一次整块重绘）。滚动/填充/换主题
        # 仍走直接调用 `_draw()`，只有"尺寸连续变化"这一路被推迟到最后一次之后。
        self.canvas.bind("<Configure>", self._on_configure)

    def _on_configure(self, _event=None):
        if self._draw_after is not None:
            try:
                self.after_cancel(self._draw_after)
            except Exception:
                pass
        try:
            self._draw_after = self.after(60, self._draw_idle)
        except Exception:
            self._draw_after = None

    def _draw_idle(self):
        self._draw_after = None
        self._draw()

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
                c.create_text(self.INDENT * level + self.CHK_PAD + self.CHK + px(6),
                      y + self.ROW_H // 2, text="(空)",
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
            # 勾选线按 CHK 等比给点（写死 3/8/6/11/4 的话，CHK 一放大就画歪）
            k = self.CHK
            c.create_line(x + k * 3 // 16, y + k * 8 // 16,
                          x + k * 6 // 16, y + k * 11 // 16,
                          x + k * 13 // 16, y + k * 4 // 16,
                          fill=T["text_bright"], width=max(1, px(2)))
        elif st is False:
            k = self.CHK
            c.create_line(x + k * 3 // 16, y + k * 8 // 16,
                          x + k * 13 // 16, y + k * 8 // 16,
                          fill=T["text_bright"], width=max(1, px(2)))

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
        """滚轮：**能滚才吃掉事件**，滚不动就让它冒泡给外层（统一规则）。

        用户口径 2026-09-13："不能在隐藏滚动条的那些小窗口操控，这很反直觉。"
        原来这里无条件 `return "break"` —— 树滚不动（只有几行/已到底）时也把事件吃掉，
        于是鼠标停在树上时**整页滚不动**。改成只在"yview 真的变了"时 break。
        """
        before = self.canvas.yview()
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        after = self.canvas.yview()
        self._draw()
        return "break" if after != before else None

    def get_selected_paths(self):
        return [n.path for n in self._sel if n.path]

    def select_all(self):
        self._sel = {n for n, _, _ in self.rows if n is not None}
        self._draw()


# ═══ 布局 ═══
class SplitPane(ttk.Panedwindow):
    """Unified ttk.Panedwindow wrapper.

    Why: raw ttk.Panedwindow usage was duplicated across tools, sash colors
    were inconsistent, and child widgets (especially self-drawn CanvasTree)
    did not refresh after dragging. This class keeps one sash style, one
    recolor path, and forces child refresh on sash release.

    另外两件 ttk 本身给不了、必须在这里补的事（均实测确认）：

    1. **pane 没有 minsize**。`ttk.Panedwindow` 的 pane 只认 `-weight`
       （`pane(..., minsize=)` → `TclError: unknown option "-minsize"`）；而
       `paneconfigure(..., minsize=)` 是 **tk 版** Panedwindow 的方法，ttk 运行时不认，
       抛的错还被 `except: pass` 吞掉 —— 于是本工程所有 `minsize=` 一直是空转，
       实测主工作区被挤到 55 px、日志栏被挤到 1 px。这里自己实现：`add(minsize=…)`
       记下来，在窗口尺寸变化与拖动结束后把 sash 收敛到"前面的 pane 至少 min"。
    2. **拖动时逐帧重排太贵，且不能让 motion 事件排队**。拖动每一步都要重排/重绘
       可见页里的全部 Tk 控件（每个控件一个 HWND）：实测每步 **33 ms 中位 / 63 ms
       最大**（六页全空的 Notebook 就要 16.9 ms，而且与数据量几乎无关）。鼠标每秒能
       发上百个 motion，若逐个处理，Tk 要排队啃完积压事件，分隔条落后光标几百毫秒
       —— 用户口径"一卡一卡"主要是这个滞后。因此 `LIVE_DRAG=True` 时**合并运动
       事件**：只记最新位置、最多排一次几何应用，滞后不超过一帧；松手再补一次收敛。
       （`LIVE_DRAG=False` 退回"只挪预览线"的旧形态，用于对照/排障。）
    3. **窗口尺寸变化（拖边框）比拖动分隔条贵得多**：实测每步 128~176 ms（当前
       *选中页*的控件重绘占一半以上，6 个页 vs 1 个页几乎没差别 —— 未选中的页不参与）。
       这里的对策是把我们自己的 Configure 处理**去抖**（`_clamp` 与
       `CanvasTree._draw` 都改成"最后一次 Configure 之后 60~120 ms 才做一次"），
       避免一次拖动风暴里重复做几十遍。
    """

    SASH_HIT = 6          # sash 命中容差（96 DPI 设计值）；实例化时按缩放换算
    # 拖动策略：
    #   "full"   完全实时（内容也逐帧重排）    ~85 ms/步 ≈ 12 fps   ← 现在的默认
    #   "line"   只挪预览线（拖动期 ≈1 ms）    松手才应用一次
    #   "freeze" 冻结窗格内容的重绘后实时跟手   32 ms/步 ≈ 31 fps
    # **为什么默认从 freeze 改回 full**（2026-09-13，用户实机截图）：
    # "冻结"= 对重窗格 `WM_SETREDRAW(0)`，那期间 Windows 不会重画它 —— 用户看到的就是
    # **整块栏目区空白**（连 Notebook 标签条都没了）。这是拿"正确性"换"跟手"，
    # 而"内容消失"是不可接受的观感缺陷（用户口径："组件的内容会不显示"）。
    # 注：我在夹具里用合成页 + 真页面、1500x900 与 1690x1040（最大化）各测一遍，
    # freeze 与 full 的墨迹曲线都几乎重合，**没能复现**那一次空白；但既然只有这条路径
    # 能把一个 pane 留在"不画"的状态（看门狗 5 s 是唯一兜底），就不该让它当默认。
    # 想两者兼得的正路是"裁剪代替重排"（见 `add()` 的 clip 计划与 ARCHITECTURE §3.4/§3.5），
    # 不是给冻结打补丁。
    # 用户 2026-09-13 定稿：**不实时动，松手一次重排**，但预览不能是一条线 ——
    # "拖拽的时候预览框不能只是一条线，而是要把那部分相应的背景也进行填充，不然很难看。"
    # line 档：拖动期一步几何都不改（只挪 1 个填色框 + 1 条 2px 亮线），松手真重排一次。
    # 这是三条路里唯一同时满足"跟手（≈1 ms/步）+ 不闪 + 不空白"的：
    # full 在 12 fps 挣扎、freeze 会把栏目区留成空白（都已实测/已否决）。
    LIVE_DRAG = "line"
    CLAMP_DEBOUNCE_MS = 120   # 窗口尺寸连续变化时，收敛推迟到"最后一次变化之后"
    FREEZE_MIN_WIDGETS = 40   # 控件数超过它的窗格才冻结重绘（日志栏那种不冻）
    FREEZE_MAX_MS = 5000      # 冻结最长存活时间（看门狗），防止卡在"再也不重绘"

    def __init__(self, master, orient="vertical", **kw):
        super().__init__(master, orient=orient, **kw)
        self._children = []
        self._mins = {}
        self._orient = orient
        self._drag = None
        self._drag_target = 0
        self._drag_total = 0
        self._drag_pending = False
        self._drag_line = None
        self._drag_fill = None
        # 用户主动收起的栏 → 它原来的最小值（撤下来存这儿）。
        # 为什么要"撤最小值"：`_clamp()` 在松手时与每次窗口 Configure 时都会跑，
        # 只要这一栏还挂着最小值，它就会把 sash 推回去 —— 那就是用户说的
        # "自动往上弹 / 改窗口大小又上来了"。撤掉之后，"收起"是**用户状态**，
        # 布局算法不再覆盖它；用户把它拉回超过原最小值时再自动恢复（见 _note_user_collapse）。
        self._saved_mins = {}
        # 收起时留的最小可见量：让分隔条仍然抓得住（完全 0 也可以，ttk 的 sash 本身有宽度，
        # 但留 2px 更稳、也看得见"这里是收起的"）。
        self.COLLAPSE_SLIVER = max(2, px(1))
        self._frozen = []
        self._thaw_after = None
        self._clamp_after = None
        self._clamping = False
        # clam 下 sash 本身就有几像素宽，150% 屏上更宽 —— 容差不跟着缩放的话，
        # 用户点在 sash 下半截会被判成"普通点击"，分隔条就"抓不住"。
        self.SASH_HIT = max(6, px(5))
        self.recolor()
        # 实例绑定先于类绑定执行；命中 sash 时返回 "break" 阻止 ttk 自己的逐事件重排。
        self.bind("<Button-1>", self._rb_press, add="+")
        self.bind("<B1-Motion>", self._rb_motion, add="+")
        self.bind("<ButtonRelease-1>", self._rb_release, add="+")
        self.bind("<Configure>", self._on_configure, add="+")
        # 安全网：拖动中途窗口被销毁/重建时也要解冻，绝不留下"再也不重绘"的窗口。
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event=None):
        if event is None or getattr(event, "widget", None) is self:
            self._thaw_pane_redraw()

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
        """Add a pane. weight maps to ttk.Panedwindow weight; minsize 由本类自己实现。

        注意 `paneconfigure`/`pane(..., minsize=)` 在 ttk 上都不成立（见类文档），
        所以 minsize 只能记在 `self._mins` 里、由 `_clamp()` 在几何变化后收敛。
        """
        super().add(pane, weight=weight)
        if minsize:
            self._mins[pane] = int(minsize)
        self._sync_children()
        return pane

    def add_clipped(self, weight=1, minsize=None, fit="viewport"):
        """建一个**裁剪式**窗格并返回"往里建东西的容器"（用户口径 2026-09-13）。

        与 `add()` 的差别正是用户要的那条：窗格沿分隔条方向**不重排内容**，而是**裁剪** ——

        * **远离分隔条的那侧边框不动**：内容挂在视口的 `anchor="nw"` 上，宽/高不随窗格变；
        * **内容左对齐**：视口内容不会被拉平居中；
        * **装不下就出滚动条**（横向分栏 → 横向滚动条），而不是把内容压扁。

        为什么用"返回容器"而不是"把已有控件塞进视口"：**Tk 不能给控件换父**
        （`master` 在创建时就定了），所以窗格里的控件必须在视口里**创建**。
        用法：`box = sp.add_clipped(weight=2)`，然后 `ttk.LabelFrame(box, ...)`。

        纵向分栏（上下两栏）**不**裁剪：那两栏要随窗口高度铺满，纵向的"装不下"
        由主界面那条窗口级滚动条负责（见 `stalker_toolkit.build_hub`）。

        **2026-09-13 反转：横向分栏也改成不裁剪。** 原来这里给左右两个窗格各配了一条
        横向滚动条（"窗格窄于内容就滚"），实机结果是两个必然的怪相：
          * 滚动条属于**窗格**、不属于**面板** → 它画在面板边框**外面**（用户截图："这个
            滚动条怎么还在窗口外面"）；
          * 每个窗格各自判断要不要滚 → "有的地方有、有的地方没有"，看着毫无规律。
        回到 Tk 的正常模型更干净：**窗格内的内容跟着窗格伸缩**，滚动条只出现在真正
        需要它的控件内部（树/文本框自己的 vbar/hbar）。窗格不会被压没 —— 那是
        `minsize` + `_clamp`（空间不够时按最小值比例分配）负责的。
        """
        vp = ScrollViewport(self, horizontal=False, fit=fit)
        self.add(vp, weight=weight, minsize=minsize)
        return vp.content

    def _panes(self):
        """实际 pane **控件**列表。

        为什么需要这个包装：`ttk.Panedwindow.panes()` 返回的是 Tcl 路径**字符串**
        （`self.tk.splitlist(...)`），不是控件对象。原代码直接把它当控件用
        （`p in alive`、`walk(pane)`、`pane.winfo_height()`），于是：
          * `_sync_children` 把字符串塞进 `_children` → `refresh_children()` 遍历的
            全是字符串、`winfo_children()` 直接抛 AttributeError 被吞掉 ——
            **"拖动后强制重绘 CanvasTree" 从未生效**；
          * 基于 pane 几何的 minsize 收敛同样空转。
        """
        out = []
        try:
            names = self.panes()
        except Exception:
            return out
        for name in names:
            try:
                out.append(self._nametowidget(name))
            except Exception:
                pass
        return out

    def _sync_children(self):
        """把 `_children` 与实际还在 panedwindow 里的 pane 对齐（保序）。

        去重 + 剔除已 forget 的旧 pane：`_children` 原先只增不减，反复
        add/forget（xml_compare 每次选中差异行都重建详情栏）会让它无限增长，
        refresh_children 也白遍历一堆死控件。
        """
        alive = self._panes()
        self._children = [p for p in self._children if p in alive]
        for p in alive:
            if p not in self._children:
                self._children.append(p)

    def forget(self, pane):
        """移除 pane，并同步 `_children`（ttk 的 forget 不会通知我们）。"""
        try:
            super().forget(pane)
        except Exception:
            pass
        self._mins.pop(pane, None)
        self._sync_children()
        return pane

    # ── minsize：ttk 不支持，自己收敛 ─────────────────────────────────────
    def _vertical(self):
        try:
            return str(self.cget("orient")) == "vertical"
        except Exception:
            return self._orient == "vertical"

    def _clamp(self):
        """把 sash 收敛到各 pane 的 minsize 之上。

        两趟：先**从右往左**保证后面的 pane 不小于它的 min（把 sash 往上/左推），
        再**从左往右**保证前面的 pane 不小于它的 min（把 sash 往下/右推）。
        只有总空间连"各 pane 最小值之和"都放不下时才让步 —— 让步顺序是"后面的 pane
        先挨饿"，因为主工作区通常在前面（两趟都用 `reserve` 留出其余 pane 的最小值）。
        """
        if self._clamping or not self._mins:
            return
        panes = self._panes()
        if len(panes) < 2:
            return
        self._clamping = True
        try:
            vertical = self._vertical()
            total = self.winfo_height() if vertical else self.winfo_width()

            def size(i):
                return (panes[i].winfo_height() if vertical else panes[i].winfo_width())

            def sash(i):
                try:
                    return int(self.sashpos(i))
                except Exception:
                    return None

            def move(i, pos):
                """落点必须夹在 [1, total-1]。

                实机抓到的 bug（2026-09-13）：页码里那个横向分栏曾经被压成 **1x1 px** ——
                因为 `sashpos` 被设到了**超出当前可用空间**的位置（窗口变小后陈旧值 /
                第二趟算出负值），ttk 会把**所有** pane 一起压扁，看起来就是"整个工作区
                塌了、拖动时右边乱动"。夹住之后最差也只是某一栏变薄，不会整块塌。
                """
                if total <= 2:
                    return False
                try:
                    self.sashpos(i, max(1, min(int(pos), total - 1)))
                    return True
                except Exception:
                    return False

            # 空间连"各 pane 最小值之和"都放不下：**按最小值比例分配**，每栏都留一点。
            # 不这么做的话，两趟收敛会互相打架（一趟往上推、一趟往下推），最后落到鞍点上
            # 由 ttk 压扁 —— 正是上面那个 1x1 的来源。
            mins_total = sum(self._mins.get(p, 0) or 0 for p in panes)
            if len(panes) == 2 and mins_total > total:
                m0 = self._mins.get(panes[0], 0) or 0
                share = int(total * m0 / float(mins_total)) if mins_total else total // 2
                move(0, share)
                return

            # 第一趟：从右往左，保证 pane[i+1] 不小于它的最小尺寸
            for i in range(len(panes) - 2, -1, -1):
                want = self._mins.get(panes[i + 1], 0)
                if not want:
                    continue
                need = want - size(i + 1)
                if need <= 0:
                    continue
                pos = sash(i)
                if pos is None:
                    continue
                floor = sum(self._mins.get(p, 0) or 0 for p in panes[:i + 1])
                move(i, max(pos - need, floor))
            # 第二趟：从左往右，保证 pane[i] 不小于它的最小尺寸
            for i in range(len(panes) - 1):
                want = self._mins.get(panes[i], 0)
                if not want:
                    continue
                need = want - size(i)
                if need <= 0:
                    continue
                pos = sash(i)
                if pos is None:
                    continue
                reserve = sum(self._mins.get(p, 0) or 0 for p in panes[i + 1:])
                move(i, min(pos + need, total - reserve))
        finally:
            self._clamping = False

    def _on_configure(self, _event=None):
        """尺寸变化后收敛一次 —— **去抖**：把工作推迟到"最后一次 Configure 之后"。

        不去抖的话，拖窗口边框时每个 WM_SIZE 都会排一次收敛；而收敛会改 sash 位置，
        又引发一轮 ttk 重排 + 重绘（实测每步 128~176 ms，其中我们自己这部分约 24 ms）。
        去抖后一次拖动风暴只在结束时收敛一次。
        """
        if self._clamping:
            return
        if self._clamp_after is not None:
            try:
                self.after_cancel(self._clamp_after)
            except Exception:
                pass
        try:
            self._clamp_after = self.after(self.CLAMP_DEBOUNCE_MS, self._clamp_idle)
        except Exception:
            self._clamp_after = None

    def _clamp_idle(self):
        self._clamp_after = None
        self._clamp()

    # ── 拖动：实时跟手（合并 motion）/ 可选预览线 ─────────────────────────
    def _freeze_pane_redraw(self):
        """拖动期间冻结**重**窗格内容的重绘（几何照算，只是先不画）。

        为什么：一次"含重绘"的实时应用要 85 ms（12 fps），其中重页面（当前选中
        栏目页的几十个控件）占大头；冻结它之后降到 32 ms（31 fps），窗格边框与
        分隔条仍然实时跟手，页面内容在松手时一次补画。
        只冻结控件数超过阈值的窗格：日志栏那种十来个控件的窗格重绘本来就很便宜，
        让它们照常实时重绘，用户能看到更多"跟手"的部分。
        失败一律忽略（非 Windows / 句柄异常）—— 冻结只是优化，不影响功能。
        """
        if self._frozen:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
        except Exception:
            return
        for pane in self._panes():
            try:
                if self._count_widgets(pane) <= self.FREEZE_MIN_WIDGETS:
                    continue
                h = int(pane.winfo_id())
                u.SendMessageW(h, 0x000B, 0, 0)      # WM_SETREDRAW = 0x000B
                self._frozen.append(h)
            except Exception:
                pass
        if self._frozen:
            # 看门狗：万一 release 事件没到达（焦点丢失/进程收发异常），也必须解冻 ——
            # 留在"再也不重绘"的状态就是整块界面变空白（用户录屏实证 2026-09-12）。
            try:
                if self._thaw_after is not None:
                    self.after_cancel(self._thaw_after)
                self._thaw_after = self.after(self.FREEZE_MAX_MS, self._thaw_pane_redraw)
            except Exception:
                self._thaw_after = None

    @staticmethod
    def _count_widgets(wd):
        n = 1
        for c in wd.winfo_children():
            n += SplitPane._count_widgets(c)
        return n

    def _thaw_pane_redraw(self):
        """恢复重绘，并让被冻结的整棵子树**立刻补画**一次。

        关键（用户录屏实证的 bug，2026-09-12）：只对 pane 自己 `InvalidateRect` 不够 ——
        `WM_SETREDRAW(0)` 之后子窗口也不会被重画，而重新打开父窗口的重绘**不会**让子窗口
        失效，于是页面留下一片空白 + 错位的陈旧像素（视频 t=12.3s / t=17.3s 两帧）。
        必须 `RedrawWindow(..., RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_UPDATENOW)`，
        让整棵子树立刻补画。
        """
        try:
            if self._thaw_after is not None:
                self.after_cancel(self._thaw_after)
        except Exception:
            pass
        self._thaw_after = None
        if not self._frozen:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            u.RedrawWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_uint]
            u.RedrawWindow.restype = ctypes.c_int
        except Exception:
            self._frozen = []
            return
        # INVALIDATE|ERASE|ALLCHILDREN —— **不要**加 RDW_UPDATENOW(0x0100)：
        # 它会同步强制整棵子树立刻重画，松手那一下实测从 ~100 ms 涨到 ~490 ms。
        # 只做"失效"，让正常绘制周期去补画，既修好了陈旧像素也不卡松手。
        flags = 0x0001 | 0x0004 | 0x0080
        for h in self._frozen:
            try:
                u.SendMessageW(h, 0x000B, 1, 0)
                u.RedrawWindow(ctypes.c_void_p(h), None, None, flags)
            except Exception:
                pass
        self._frozen = []

    def _sash_pos(self, index):
        try:
            return int(self.sashpos(index))
        except Exception:
            return 0

    def _sash_at(self, x, y):
        """(x,y) 命中哪条 sash（用 pane 实际几何判断，不依赖 ttk 内部状态）。"""
        panes = self._panes()
        if len(panes) < 2:
            return None
        vertical = self._vertical()
        for i in range(len(panes) - 1):
            pos = self._sash_pos(i)
            if (abs(y - pos) if vertical else abs(x - pos)) <= self.SASH_HIT:
                return i
        return None

    @staticmethod
    def _pane_bg(pane):
        """预览该用哪一栏的底色：面板（ttk.LabelFrame，如日志栏）用 surface，其余用 bg。"""
        try:
            if pane is not None and isinstance(pane, ttk.LabelFrame):
                return color("surface")
        except Exception:
            pass
        return color("bg")

    def _show_drag_line(self, x, y):
        """拖动期预览：**填色的区域**（不是一条线）。

        用户口径 2026-09-13："预览框不能只是一条线，而是要把那部分相应的背景也进行填充，
        不然很难看。" —— 只画 2px 线时看不出"这块会变成谁的"；填上那一栏的底色后，
        预览就成了"目标分栏已经长到这儿了"的样子。

        做法：在**当前 sash 位置**与**目标位置**之间铺一条填色带（属于"被长大的那一栏"），
        再在目标边界补 1px 亮线标出精确落点。两者都是 place 的普通 Frame，
        每步只改几何、不碰任何窗格内容 —— 这就是 line 档能 1 ms/步的原因。
        """
        if self._drag is None:
            return
        vertical = self._vertical()
        cur = self._sash_pos(self._drag)
        target = int(self._drag_target)
        grow = self._drag + 1 if target < cur else self._drag
        panes = self._panes()
        pane = panes[grow] if 0 <= grow < len(panes) else None
        fill = self._pane_bg(pane)
        if self._drag_fill is None:
            self._drag_fill = tk.Frame(self, bg=fill, bd=0, highlightthickness=0)
        if self._drag_line is None:
            self._drag_line = tk.Frame(self, bg=color("sash_light"), bd=0,
                                       highlightthickness=0)
        self._drag_fill.configure(bg=fill)
        lo, hi = min(cur, target), max(cur, target)
        try:
            if vertical:
                self._drag_fill.place(x=0, y=lo, relwidth=1.0, height=max(1, hi - lo))
                self._drag_line.place(x=0, y=max(0, target - 1), relwidth=1.0, height=2)
            else:
                self._drag_fill.place(x=lo, y=0, relheight=1.0, width=max(1, hi - lo))
                self._drag_line.place(x=max(0, target - 1), y=0, relheight=1.0, width=2)
            self._drag_fill.lift()
            self._drag_line.lift()
        except Exception:
            pass

    def _hide_drag_line(self):
        for w in (self._drag_fill, self._drag_line):
            if w is None:
                continue
            try:
                w.place_forget()
            except Exception:
                pass

    def _note_user_collapse(self, index):
        """松开分隔条后，把"用户主动收起 / 主动恢复"这件事记下来（用户口径 2026-09-13）。

        用户原话："日志栏做成可以完全收起的，不要自动往上弹。并且如果已经完全收起，
        那么在改变主窗口大小的时候，也不会再上来。"

        规则（只作用于这条 sash 两侧的两栏）：
          * 该栏被拖到**小于它的最小值** → 记为收起：把最小值从 `_mins` 撤下来存进
            `_saved_mins`。此后 `_clamp()`（松手时、以及每次窗口 Configure）都不再有
            依据把它推回去 —— 于是"收起"是稳定的用户状态。
          * 该栏又长到 ≥ 原最小值 → 取消收起：把最小值装回去。
        没挂最小值、也没收起的栏完全不受影响。
        """
        panes = self._panes()
        vertical = self._vertical()
        total = self.winfo_height() if vertical else self.winfo_width()
        # 尺寸判定要用**权威量**：`pane.winfo_height()` 在 ttk 还没重排完时是陈旧值
        # （实测两栏之和 518 > 总高 420），拿它判"够不够最小尺寸"会误判。
        # 所以两把尺子都用上，并各取**保守侧**：判"收起"取较小者（不因陈旧的大值漏判收起），
        # 判"恢复"取较大者（不因陈旧的小值误恢复）。
        try:
            pos = self._sash_pos(index)
            prev = self._sash_pos(index - 1) if index > 0 else 0
        except Exception:
            pos, prev = 0, 0
        by_sash = {index: max(0, pos - prev), index + 1: max(0, total - pos)}
        for i in (index, index + 1):
            if not (0 <= i < len(panes)):
                continue
            pane = panes[i]
            try:
                geo = pane.winfo_height() if vertical else pane.winfo_width()
            except Exception:
                geo = None
            ref = by_sash.get(i, 0)
            size_lo = ref if geo is None else min(geo, ref)
            size_hi = ref if geo is None else max(geo, ref)
            want = self._mins.get(pane)
            if want and size_lo < want:
                self._saved_mins[pane] = self._mins.pop(pane)     # 收起：撤最小值
            elif pane in self._saved_mins and size_hi >= self._saved_mins[pane]:
                self._mins[pane] = self._saved_mins.pop(pane)     # 拉回来了：恢复最小值

    def _pos_from_event(self, event):
        """把鼠标位置换算成合法的 sash 位置（夹在窗口内）。

        拖动期间用**按下时缓存**的尺寸，不做 Tcl 往返：motion 处理器每次调
        `winfo_height()` 都要过一次 Tcl（实测 ~1.5 ms），60 个 motion 就是 90 ms
        —— 而拖动期间窗口尺寸不可能变（变的是 sash），缓存值恒等于当前值。
        """
        vertical = self._vertical()
        total = self._drag_total
        if not total:
            total = self.winfo_height() if vertical else self.winfo_width()
        pos = event.y if vertical else event.x
        # 收起留 sliver：允许把某一栏拖到几乎全收起，但不给 0（`sashpos` 到 0 时 ttk
        # 会把两侧一起压扁，就是之前那个 1px 塌陷的另一条来路）。
        lo = self.COLLAPSE_SLIVER
        hi = max(lo + 1, total - self.COLLAPSE_SLIVER)
        return max(lo, min(int(pos), hi))

    def _rb_press(self, event):
        index = self._sash_at(event.x, event.y)
        if index is None:
            return None
        self._drag = index
        self._drag_total = self.winfo_height() if self._vertical() else self.winfo_width()
        self._drag_target = self._pos_from_event(event)
        self._drag_pending = False
        if self.LIVE_DRAG == "line":
            self._show_drag_line(event.x, event.y)
        elif self.LIVE_DRAG == "freeze":
            self._freeze_pane_redraw()
        return "break"          # 阻止 ttk 自己的逐事件重排

    def _rb_motion(self, event):
        if self._drag is None:
            return None
        self._drag_target = self._pos_from_event(event)
        if self.LIVE_DRAG == "line":
            self._show_drag_line(event.x, event.y)
        else:
            # 实时跟手，但**合并运动事件**：只记最新位置，最多排一次几何应用。
            # 为什么必须合并：每应用一次几何要 30+ ms（Tk 重排 + Win32 重绘），
            # 而鼠标每秒能发上百个 motion。逐事件处理的话 Tk 要排队啃完积压的
            # motion，分隔条会落后光标几百毫秒 —— 用户的主观感受就是"一卡一卡"。
            # 合并之后：拖动期只认最新位置，滞后最多一步（≈一帧）。
            if not self._drag_pending:
                self._drag_pending = True
                try:
                    self.after(1, self._apply_drag)
                except Exception:
                    self._drag_pending = False
        return "break"

    def _apply_drag(self):
        """合并后的唯一落点：把最新目标位置应用一次。"""
        self._drag_pending = False
        if self._drag is None:
            return
        self._set_sash(self._drag, self._drag_target)

    def _set_sash(self, index, pos):
        """设置 sash 位置；ttk 拒绝时**小步回退**再试。

        为什么要回退（2026-09-13 实测）：`ttk.Panedwindow` 自己也有最小尺寸
        （它按 pane 的**请求尺寸**算），所以"把某一栏拖到最底/最右"给出的位置可能超出
        它允许的最大值 —— `sashpos` 直接抛 TclError。老代码 `except: pass` 把它吞了，
        于是"拖到底"根本没落到最底（实测日志栏停在 104px，看着就是"收不起来"）。
        这里按 4px 步长往回退，直到 ttk 接受，保证"拖到底 = 尽量到底"。
        """
        step = 4
        cur = int(pos)
        for _ in range(64):
            try:
                self.sashpos(index, cur)
                return cur
            except Exception:
                cur -= step
                if cur <= 1:
                    break
        return None

    def _rb_release(self, event):
        index = self._drag
        if index is None:
            return None
        self._drag = None
        self._drag_target = self._pos_from_event(event)
        self._hide_drag_line()
        self._set_sash(index, self._drag_target)
        # 先判定"用户是不是把某一栏收起了"（撤/装最小值），再让 `_clamp` 收敛 ——
        # 顺序反了的话收起的栏会被立刻推回来。
        self._note_user_collapse(index)
        # 顺序：先解冻（让页面把新尺寸画出来），再补自绘控件与 minsize 收敛。
        self._thaw_pane_redraw()
        self.refresh_children()      # 自绘控件（CanvasTree）补一次重绘
        self._clamp()
        return "break"

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


# ═══════════════════════════════════════════════════════════════
# 插件槽位（统一寻址 host+location；确定性定位；无注册即不产生任何控件）
# ═══════════════════════════════════════════════════════════════

def invoke_plugin_callback(cb, app=None):
    """调用插件动作回调：优先传宿主 app，兼容旧式无参回调。

    插件回调抛异常**绝不静默、也绝不冒到 Tk**：写 summary/err 日志后返回 None。
    """
    import inspect
    try:
        n = len([p for p in inspect.signature(cb).parameters.values()
                 if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
    except (TypeError, ValueError):
        n = 1
    try:
        return cb(app) if n >= 1 else cb()
    except Exception as e:
        try:
            import toolkit_log
            toolkit_log.summary(
                f"插件回调执行失败: {e}（{getattr(cb, '__module__', '?')}）", "err")
        except Exception:
            pass
        return None


class PluginSlot:
    """插件槽位句柄：包装一个容器控件，并支持按新状态**重算**其中的命令。

    为什么需要它：`when` 条件原先只在构造时求值一次，之后运行期状态变化
    （fs 的 loaded 由空变有、xml 出结果）不会让带条件的命令出现——`when`
    因此是死条件。拿到本句柄后调用 `refresh()` 即可重算。

    兼容性：本对象支持解包为 frame（`frame = plugin_slot_bar(...)` 仍成立），
    并代理容器上的常用方法。无可见命令时 `frame is None`，`refresh()` 是空操作。
    """

    __slots__ = ("frame", "_parent", "_host", "_app", "_context", "_padx", "_pady")

    def __init__(self, parent, host, app, context, padx, pady):
        self._parent = parent
        self._host = host
        self._app = app
        self._context = context
        self._padx = padx
        self._pady = pady
        self.frame = None
        self.refresh()

    def _current_context(self):
        """取当前 context；允许传可调用对象 —— 状态会变时传 lambda 即可。"""
        ctx = self._context
        if callable(ctx):
            try:
                return ctx()
            except Exception:
                return None
        return ctx

    def refresh(self, context=None):
        """按 context 重算；无可见命令时销毁容器并置 frame=None。

        context 省略时复用构造时给的（可能是可调用对象，每次重算都重新求值）。
        传入新 dict 则替换之 —— 供"状态变了但不想包一个 lambda"的写法。
        """
        if context is not None:
            self._context = context
        if self.frame is not None:
            try:
                if not self.frame.winfo_exists():
                    self.frame = None
                else:
                    self.frame.destroy()
                    self.frame = None
            except Exception:
                self.frame = None
        from toolkit_plugins import PluginManager
        try:
            items = PluginManager.shared().menu_items_for(
                self._host, LOC_TOOLBAR, self._current_context())
        except Exception:
            return self
        items = [it for it in items if callable(it.get("handler"))]
        if not items:
            return self
        from tkinter import ttk as _ttk
        bar = _ttk.Frame(self._parent)
        bar.pack(fill="x", padx=self._padx, pady=self._pady)
        _ttk.Label(bar, text="插件:", style="Dim.TLabel").pack(side="left", padx=(0, 6))
        for it in items:
            btn = _ttk.Button(bar, text=it.get("label") or "动作")
            cb = it.get("handler")
            btn.configure(command=lambda c=cb: invoke_plugin_callback(c, self._app))
            btn.pack(side="left", padx=(0, 6))
        self.frame = bar
        return self

    # ── 常用代理，保持"返回控件"的既有用法可用 ──
    def __iter__(self):
        # 兼容 `bar, x = plugin_slot_bar(...)` 之类解包
        return iter((self.frame,))

    def pack(self, *a, **k):
        return self.frame.pack(*a, **k) if self.frame is not None else None

    def pack_forget(self):
        return self.frame.pack_forget() if self.frame is not None else None

    def winfo_exists(self):
        return bool(self.frame is not None and self.frame.winfo_exists())

    def __bool__(self):
        return self.frame is not None


def plugin_slot_bar(parent, host, app=None, context=None, padx=14, pady=(0, 4)):
    """统一插件动作区（location="toolbar"）。

    位置约定：**紧跟在 tool_header(...) 之后**调用，形成固定顺序
    「工具标题 → 插件动作区 → 工具内容」，各工具不得把它放到别处。

    context: 宿主当前状态，供命令的 when 条件过滤（如 {"loaded": True}）。
        传**可调用对象**时每次重算都重新求值 —— 状态会变的工具建议这样写，
        避免"构造时的快照被冻结、when 永远为假"。
    返回 `PluginSlot`（可解包出 frame；无可见命令时其 frame 为 None）。
    运行期状态变化后调用 `slot.refresh()` 重算即可让 when 生效。
    """
    return PluginSlot(parent, host, app, context, padx, pady)


def attach_plugin_context_menu(widget, host, app=None, menu=None, context=None):
    """把该组件 context 槽的插件命令挂到指定控件的右键菜单（location="context"）。

    - 无可见命令时**不绑定任何事件**，绝不吞掉控件原有的右键行为；
    - 传入控件已有的 tk.Menu 时，按固定顺序追加「原有项 → 分隔符 → 插件项」，
      避免与宿主自己的右键菜单互相覆盖（不传 menu 就会出现两个菜单抢着弹）；
    - context 供命令的 when 条件过滤；返回最终生效的 menu，无注册时返回 None。
    """
    from toolkit_plugins import PluginManager
    try:
        items = PluginManager.shared().menu_items_for(host, "context", context)
    except Exception:
        return None
    items = [it for it in items if callable(it.get("handler"))]
    if not items:
        return None
    import tkinter as _tk
    if menu is None:
        menu = _tk.Menu(widget, tearoff=0)
    if menu.index("end") is not None:
        menu.add_separator()
    for it in items:
        cb = it.get("handler")
        menu.add_command(label=it.get("label") or "动作",
                         command=lambda c=cb: invoke_plugin_callback(c, app))
    widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root), add="+")
    return menu


def plugin_entries(host, area=None, context=None):
    """取该 (host, area) 的插件下拉条目值——组件侧加条目一律用它，无需持有插件宿主。

    用法：``ttk.Combobox(..., values=BASE + plugin_entries("convert", "source_enc"))``
    """
    from toolkit_plugins import PluginManager
    try:
        return PluginManager.shared().option_entries_for(host, area, context)
    except Exception:
        return []


def invoke_plugin_option_callback(cb, value, app=None):
    """调用插件下拉回调：优先 (value, app)，兼容 (value) / ()——与 fs 既有语义一致。

    回调抛异常同样不静默：写 summary/err 日志后返回 None。
    """
    import inspect
    try:
        n = len(inspect.signature(cb).parameters)
    except (TypeError, ValueError):
        n = 1
    try:
        if n >= 2:
            return cb(value, app)
        if n == 1:
            return cb(value)
        return cb()
    except Exception as e:
        try:
            import toolkit_log
            toolkit_log.summary(
                f"插件选项回调执行失败: {e}（{getattr(cb, '__module__', '?')}）", "err")
        except Exception:
            pass
        return None


def tool_dropdown(parent, host, area, var, values, label=None, label_width=6,
                  context=None, on_change=None, width=None, side="left",
                  padx=(4, 0), pady=(0, 0)):
    """统一下拉菜单：基础值 + 该 (host, area) 的插件条目（保序去重）。

    组件的下拉一律用它建 ——「往该下拉加条目」因此是**结构保证**，不靠逐处接线。
    没有任何插件条目时，行为与外观同直接建 ttk.OptionMenu 完全一致。
    想"新建一个下拉"用 plugin_options_area（对应 api.register_option）。
    返回 OptionMenu 控件。
    """
    from toolkit_plugins import PluginManager
    vals = [str(v) for v in (values or [])]
    try:
        for v in PluginManager.shared().option_entries_for(host, area, context):
            if str(v) not in vals:
                vals.append(str(v))
    except Exception:
        pass
    if label:
        ttk.Label(parent, text=label, width=label_width).pack(side=side)
    default = var.get() if var.get() in vals else (vals[0] if vals else "")
    om = ttk.OptionMenu(parent, var, default, *vals)
    if width:
        om.configure(width=width)
    if on_change is not None:
        om.configure(command=on_change)
    om.pack(side=side, padx=padx, pady=pady)
    return om


def refresh_dropdown(widget, host, area, base, context=None):
    """**重设**下拉候选值：base + 该 (host, area) 的插件条目（保序去重）。

    组件运行期任何重设候选值的地方都必须调它，而不是直接 `config(values=...)`——
    否则插件条目会在切换/刷新时被**静默丢掉**（实测 xml 切换比较模式即如此）。
    支持 `ttk.Combobox` 与 `ttk.OptionMenu`；返回最终生效的值列表。
    """
    vals = [str(v) for v in (base or [])]
    try:
        from toolkit_plugins import PluginManager
        for v in PluginManager.shared().option_entries_for(host, area, context):
            if str(v) not in vals:
                vals.append(str(v))
    except Exception:
        pass
    if widget is None:      # 只取值、不配置控件（构造前先算候选值）
        return vals
    try:
        if isinstance(widget, ttk.OptionMenu):
            tv = str(widget.cget("textvariable") or "")
            cur = widget.getvar(tv) if tv else (vals[0] if vals else "")
            widget.set_menu(cur if cur in vals else (vals[0] if vals else ""), *vals)
        elif isinstance(widget, ttk.Combobox):
            widget.configure(values=vals)
    except Exception:
        pass
    return vals


def plugin_options_area(parent, host, area="top_bar", context=None, app=None, pack_kw=None):
    """渲染插件**新建**的下拉（api.register_option）——"本来没有下拉就新建一个"。

    无注册时不创建任何控件并返回 None。返回的 Frame 上挂 `.vars` 字典（标签→StringVar）。
    """
    from toolkit_plugins import PluginManager
    try:
        opts = PluginManager.shared().options_for(host, area, context)
    except Exception:
        return None
    if not opts:
        return None
    holder = ttk.Frame(parent)
    holder.pack(**(pack_kw or {"fill": "x", "pady": (0, 4)}))
    holder.vars = {}
    for opt in opts:
        choices = [str(c) for c in (opt.get("choices") or [])]
        if not choices:
            continue
        var = tk.StringVar(value=choices[0])
        row = ttk.Frame(holder)
        row.pack(fill="x", pady=(0, 2))
        ttk.Label(row, text=opt.get("label") or "选项", width=10).pack(side="left")
        ttk.OptionMenu(row, var, choices[0], *choices).pack(side="left", padx=(4, 0))
        cb = opt.get("callback")
        if callable(cb):
            var.trace_add("write",
                          lambda *a, c=cb, v=var: invoke_plugin_option_callback(c, v.get(), app))
        holder.vars[opt.get("label") or "选项"] = var
    return holder


def tool_panel(parent, host, area, context=None, app=None, pack_kw=None):
    """插件贡献的子栏目（api.register_panel）：每个面板一个 LabelFrame，按 order 排序。

    无贡献时不创建任何控件并返回 None；单个面板 builder 抛错只影响它自己。
    """
    from toolkit_plugins import PluginManager
    try:
        items = PluginManager.shared().panels_for(host, area, context)
    except Exception:
        return None
    if not items:
        return None
    holder = ttk.Frame(parent)
    holder.pack(**(pack_kw or {"fill": "x", "pady": (0, 4)}))
    holder.panels = []
    for p in items:
        lf = ttk.LabelFrame(holder, text=" " + (p.get("title") or "插件面板") + " ", padding=6)
        lf.pack(fill="x", pady=(0, 4))
        try:
            p["builder"](lf)
        except Exception:
            pass
        holder.panels.append(lf)
    return holder
