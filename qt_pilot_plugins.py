# -*- coding: utf-8 -*-
"""Qt 插件宿主与 Qt 后端控件工厂（试点）。

## 这一层要回答的问题

插件契约（`PLUGINS.md`）与实现（`toolkit_plugins.PluginManager`）里，**只有三处**与 Tk 耦合：
`api.widgets`、`register_panel(builder)`、`register_tool(builder)`；其余注册项都是宿主渲染的
纯数据 + 回调。所以迁移的关键不是"重写插件系统"，而是：

1. 把**可移植的注册项**在 Qt 宿主里照原样消费（格式/解密器/命令/菜单项/下拉条目/比较模式）；
2. 给 builder 一路提供**后端无关的控件工厂** `api.ui`（Tk 实现在 `toolkit_plugin_ui.py`，
   Qt 实现就是本文件的 `QtUiFactory`），插件只写一遍就能跑在两个后端；
3. 对**只认 Tk 的旧插件**（例如 `engine_utf8_patch.py` 的 9 处 Tk 控件构造）**优雅降级并如实上报**，
   绝不让宿主崩掉。

## 实测结论（见 UI 回执第十一节）

* `nlc_sqfs.py`（**闭源第三方**）：0 处 Tk 构造 → **原样可用**，其"格式 + 解密器"在 Qt 宿主里
  正常落位；
* `engine_utf8_patch.py`（我方实验件）：命令/菜单项可移植，面板 builder 有 9 处 Tk 构造
  → 被识别为 `tk-only` 并列入报告（迁移时改用 `api.ui` 即可，纯机械改）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6 import QtWidgets
    QT_AVAILABLE = True
    QT_IMPORT_ERROR = None
except Exception as e:
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

# 与 Tk 工厂同一份接口清单：探针会核对两侧一致。
# **不能** import toolkit_plugin_ui —— 那个模块顶层 `import tkinter`，会把 Tk 拉进 Qt 侧进程
# （试点的一条锁就是"Qt 侧不得出现 tkinter"）。所以这里**读源码**取清单：
# 读不到就返回空元组，让探针那条断言**直接失败**，而不是悄悄降级成旧版的 8 个方法
# （降级过的清单会让"两侧一致"变成一条永远为真的锁）。
def _contract_methods():
    """从 `toolkit_plugin_ui.py` 里 AST 取出 `UI_METHODS`（不导入该模块）。"""
    try:
        import ast
        import io as _io
        import os as _os
        p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "toolkit_plugin_ui.py")
        with _io.open(p, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "UI_METHODS" for t in node.targets):
                return tuple(ast.literal_eval(node.value))
    except Exception:
        pass
    return ()


UI_METHODS = _contract_methods()

# Tk 专用模块名：用来识别"只认 Tk 的 builder"（源码级判定，见 classify_builder）
TK_MARKERS = ("tkinter", "tk.", "ttk.", "toolkit_widgets", ".tk", "winfo_", ".master")

# 运行期判定：发生在 Qt 父控件上的这些错误，形状就是"这段代码在按 Tk 用父控件"。
# 为什么必须补运行期判定：builder 常常是 lambda（`lambda p: _build_panel(api, p)`），
# `inspect.getsource` 只看得到那一行，源码里没有 Tk 标记 —— 实测就是这样漏判，
# 直到调用时才抛 `'QGroupBox' object has no attribute 'tk'`。
TK_ERROR_MARKERS = ("has no attribute 'tk'", "has no attribute 'winfo_",
                    "has no attribute 'master'", "unknown option", "bad option",
                    "expected a Tk", "TclError", "is not a Tk", "tkinter")


def _colors():
    """色板代理：**不再自带色值**，一律走 `qt_pilot_theme`（= toolkit_theme 那一份真值）。

    试点第一版这里是 5 个手抄的十六进制，注释还写着"与 Tk 暗色主题接近" —— "接近"就是漂移：
    工具包改了色板，插件面板不会跟着变，而且没人会发现。
    取不到主题时返回**空字典**，让控件回落到 Qt 自己的 palette + QSS（`qt_pilot_theme.apply`
    已经把整套色板挂到 QApplication 上了）—— 这里绝不留第二份硬编码色板。
    """
    try:
        import qt_pilot_theme as theme
        return dict((r, theme.role_color(r)) for r in
                    ("bg", "surface", "surface2", "text", "text_dim", "text_bright",
                     "accent", "border", "entry_bg", "selected", "green", "red", "yellow"))
    except Exception:
        return {}


def _theme_mod():
    """取主题模块（拿不到返回 None，调用方按"没有主题"处理）。"""
    try:
        import qt_pilot_theme as theme
        return theme
    except Exception:
        return None


if QT_AVAILABLE:

    class QtTextView:
        """只读多行文本视图（Qt 实现），与 `toolkit_plugin_ui.TkTextView` 同接口。"""

        def __init__(self, widget):
            self.widget = widget
            self.text = widget

        def set_text(self, s):
            self.text.setPlainText(str(s))

        def clear(self):
            self.text.clear()

        def alive(self):
            try:
                import shiboken6
                return bool(shiboken6.isValid(self.text))
            except Exception:
                return True

        def get_text(self):
            try:
                return self.text.toPlainText()
            except Exception:
                return ""

    class QtUiFactory:
        """`api.ui` 的 Qt 实现：与 `TkUiFactory` **同名同参**，插件无需分支。"""

        backend = "qt"

        def __init__(self, parent_hint=None):
            self._c = _colors()
            self.packed_noop = 0        # pack() 被调用次数（Qt 侧已由"创建即入布局"接管）
            self._hrows = {}            # id(父容器) → 该父容器里的"同一水平行"子容器

        # ── 内部：Qt 没有 Tk 的 pack，改用"创建即入父布局" ──────────────
        @staticmethod
        def _layout_for(parent):
            """取父控件布局；没有就建一个竖直的。

            这是 Tk→Qt 最容易踩的语义差：Tk 里控件创建后必须 `pack/grid` 才可见，
            而 Qt 里必须 `addWidget` 进布局。插件既是按 Tk 风格写的（先建后 pack），
            所以这里**在创建时就入布局**，`pack()` 于是退化为对齐提示 —— 同一份插件
            代码在两个后端都可见、不需要分支。
            """
            lay = parent.layout()
            if lay is None:
                lay = QtWidgets.QVBoxLayout(parent)
                lay.setContentsMargins(4, 4, 4, 4)
                lay.setSpacing(3)
            return lay

        # ── 容器 ──────────────────────────────────────────────────────
        def row(self, parent, side="top", fill="x", expand=False, padx=0, pady=0):
            """中立容器 —— 对应 Tk 的 `ttk.Frame`，**内部默认竖直排列**。

            这里必须竖直：Tk 里 `pack()` 不给 side 就是 `top`，所以一个 Frame 的子控件
            天然是自下而上的序列。早先这里建的是 `QHBoxLayout`，于是同一份插件代码
            （wrap = row(parent); 往里 pack 按钮行 / 路径标签 / 结果框）在 Qt 上会把
            后两者摆到按钮行**右边**，而 Tk 上它们在下方 —— 布局语义对不上。
            横向由 `pack(side="left")` 表达，见 pack()。
            """
            w = QtWidgets.QWidget(parent)
            lay = QtWidgets.QVBoxLayout(w)
            lay.setContentsMargins(padx, pady, padx, pady)
            lay.setSpacing(3)
            if expand:
                lay.addStretch(1)
            self._layout_for(parent).addWidget(w)
            return w

        def _hrow(self, parent):
            """取（或惰性建）父容器里的"同一水平行"子容器 —— Tk `pack(side="left")` 的落点。

            惰性建而不是预建：这样它按**第一次**出现 left/right 的位置插进竖直序列，
            与 Tk 的 pack 顺序一致（插件里"按钮行"在路径标签/结果框之前）。
            """
            import shiboken6
            hr = self._hrows.get(id(parent))
            if hr is not None:
                try:
                    if shiboken6.isValid(hr) and hr.parentWidget() is parent:
                        return hr
                except Exception:
                    pass
            hr = QtWidgets.QWidget(parent)
            hl = QtWidgets.QHBoxLayout(hr)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            hl.addStretch(1)               # 左对齐：多余宽度留给尾部
            self._layout_for(parent).addWidget(hr)
            self._hrows[id(parent)] = hr
            return hr

        def pack(self, widget, side="top", fill="x", expand=False, padx=0, pady=0, anchor=None):
            """Tk `pack()` 的 Qt 对等写法：控件创建时已入父布局，这里按 side 归位。

            - `side="top"/"bottom"`（默认）：留在父容器的竖直序列里（创建时就进去了）；
            - `side="left"/"right"`：从竖直序列摘出来，移进同一个水平行子容器。
            两边的结果因此与 Tk 一致，插件代码不需要分支。
            """
            self.packed_noop += 1
            try:
                parent = widget.parentWidget()
                if parent is not None and side in ("left", "right"):
                    hr = self._hrow(parent)
                    cur = parent.layout()
                    if cur is not None and widget not in self._children_of(hr):
                        cur.removeWidget(widget)
                    hl = hr.layout()
                    # 末尾那个 stretch 是"左对齐"用的，新控件一律插到它**前面**
                    hl.insertWidget(max(0, hl.count() - 1), widget)
                if expand:
                    sp = widget.sizePolicy()
                    sp.setHorizontalPolicy(sp.Policy.Expanding)
                    widget.setSizePolicy(sp)
            except Exception:
                pass
            return widget

        @staticmethod
        def _children_of(container):
            lay = container.layout()
            if lay is None:
                return []
            out = []
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if w is not None:          # 跳过 stretch / spacer
                    out.append(w)
            return out

        # ── 叶子（一律"创建即入父布局"，见 _layout_for 的说明）──────────
        def label(self, parent, text, style=None):
            """标签。`style` 是 Tk 的 ttk 样式名（`Dim.TLabel` 等），**必须真的生效**：
            试点第一版把它丢掉了，于是插件写的语义样式（次要文字/标题/成功色）在 Qt 上全变成正文色。
            颜色/字体一律来自 `qt_pilot_theme` 的角色表，这里不写任何色值。"""
            w = QtWidgets.QLabel(str(text), parent)
            th = _theme_mod()
            if th is not None:
                th.apply_label_style(w, style)
            else:
                c = self._c.get("text")
                if c:
                    w.setStyleSheet("color:%s;" % c)
            self._layout_for(parent).addWidget(w)
            return w

        def button(self, parent, text, on_click=None, width=None, style=None, state=None):
            w = QtWidgets.QPushButton(str(text), parent)
            if on_click is not None:
                w.clicked.connect(lambda _c=False: on_click())
            if width is not None:
                w.setMinimumWidth(int(width) * 8)
            if state == "disabled":
                w.setEnabled(False)
            th = _theme_mod()
            if th is not None:
                th.apply_button_style(w, style)      # `Accent.TButton` → accent 底
            self._layout_for(parent).addWidget(w)
            return w

        def checkbox(self, parent, text, variable=None, on_toggle=None):
            w = QtWidgets.QCheckBox(str(text), parent)
            if on_toggle is not None:
                w.toggled.connect(lambda _v: on_toggle())
            self._layout_for(parent).addWidget(w)
            return w

        def entry(self, parent, textvariable=None, width=None, show=None):
            w = QtWidgets.QLineEdit(parent)
            if width is not None:
                w.setMaximumWidth(int(width) * 8)
            if show:
                w.setEchoMode(QtWidgets.QLineEdit.Password)
            self._layout_for(parent).addWidget(w)
            return w

        def text(self, parent, height=6, width=None, wrap="word"):
            w = QtWidgets.QPlainTextEdit(parent)
            w.setMaximumHeight(int(height) * 18)
            w.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth if wrap != "none"
                              else QtWidgets.QPlainTextEdit.NoWrap)
            self._layout_for(parent).addWidget(w)
            return w

        def combo(self, parent, values=(), variable=None, width=None, on_change=None):
            w = QtWidgets.QComboBox(parent)
            w.addItems([str(v) for v in values])
            if on_change is not None:
                w.currentTextChanged.connect(lambda t: on_change(t))
            self._layout_for(parent).addWidget(w)
            return w

        # ── 改控件 / 拿用户输入（与 TkUiFactory 同名同参）────────────────
        def set_text(self, widget, text):
            try:
                widget.setText(str(text))
                return True
            except Exception:
                return False

        def alive(self, widget):
            """Qt 侧判定控件是否仍有效（用 shiboken 的 isValid）。"""
            if widget is None:
                return False
            try:
                import shiboken6
                return bool(shiboken6.isValid(widget))
            except Exception:
                return True

        def text_view(self, parent, height=12, mono=True):
            """只读结果视图（Qt 实现：QPlainTextEdit，只读）。"""
            w = QtWidgets.QPlainTextEdit(parent)
            w.setReadOnly(True)
            w.setMaximumHeight(int(height) * 18)
            w.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
            th = _theme_mod()
            if th is not None:
                f = th.make_font("font_mono" if mono else "font")
                if f is not None:
                    w.setFont(f)        # 等宽字体角色也来自色板（这里不再写死 "Consolas"）
            elif mono:
                f = w.font()
                f.setFamily("Consolas")
                w.setFont(f)
            self._layout_for(parent).addWidget(w)
            return QtTextView(w)

        def ask_yes_no(self, parent, title, message):
            r = QtWidgets.QMessageBox.question(
                parent if isinstance(parent, QtWidgets.QWidget) else None,
                str(title), str(message),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            return r == QtWidgets.QMessageBox.Yes

        def ask_open_file(self, parent, title, filetypes=None, initialdir=""):
            path, _f = QtWidgets.QFileDialog.getOpenFileName(
                parent if isinstance(parent, QtWidgets.QWidget) else None,
                str(title), initialdir, self._filter(filetypes))
            return path or ""

        def ask_save_file(self, parent, title, initialdir="", initialfile="", filetypes=None):
            start = os.path.join(initialdir, initialfile) if initialdir else initialfile
            path, _f = QtWidgets.QFileDialog.getSaveFileName(
                parent if isinstance(parent, QtWidgets.QWidget) else None,
                str(title), start, self._filter(filetypes))
            return path or ""

        @staticmethod
        def _filter(filetypes):
            """Tk 的 filetypes 形如 [("exe", "*.exe")] → Qt 的 "exe (*.exe)"。"""
            out = []
            for ft in (filetypes or ()):
                try:
                    label, pat = ft[0], ft[1]
                    out.append("%s (%s)" % (label, pat))
                except Exception:
                    continue
            return ";;".join(out)

    class PluginCompatReport:
        """一次扫描后"哪些插件贡献被落位、哪些被跳过、为什么"。"""

        def __init__(self):
            self.rows = []

        def add(self, plugin, kind, name, status, reason=""):
            self.rows.append({"plugin": plugin, "kind": kind, "name": name,
                              "status": status, "reason": reason})

        def counts(self):
            out = {}
            for r in self.rows:
                out[r["status"]] = out.get(r["status"], 0) + 1
            return out

        def lines(self):
            return ["%-26s %-16s %-22s %-9s %s"
                    % (r["plugin"], r["kind"], r["name"][:22], r["status"], r["reason"])
                    for r in self.rows]

    class QtPluginHost:
        """把 `PluginManager` 里的贡献渲染到 Qt 页面（只渲染可移植的部分）。"""

        def __init__(self, manager, window=None, log=None):
            self.pm = manager
            self.window = window
            self.log = log or (lambda msg, tag="info": None)
            self.report = PluginCompatReport()
            self.buttons = {}          # action_id -> [QPushButton]
            self.panels = []           # builder 落位后的 QWidget
            self.tabs = []             # (name, QWidget)

        # ── 可移植注册项 ──────────────────────────────────────────────
        def format_names(self):
            """插件贡献的封包格式名（宿主把这些塞进宿主自己的格式下拉）。"""
            return [f["name"] for f in getattr(self.pm, "formats", [])]

        def decryptor_count(self):
            return len(getattr(self.pm, "decryptors", []))

        def command_ids(self):
            return sorted(getattr(self.pm, "commands", {}).keys())

        def toolbar_actions(self, host):
            """某宿主页要显示的动作（两种注册形式都要认）。

            `register_menu_item` 有两种用法：**引用已注册命令**（`command="act"`）与
            **直接给回调**（`callback=fn`）。第一版只认前者，于是 `engine_utf8_patch.py`
            的工具栏项（用的正是 callback 形式）在 Qt 宿主里全部丢失 —— 这是实测抓到的
            兼容缺口，两种都必须支持。
            返回 [(键, 标签, 回调)]，键用于去重与查找按钮。
            """
            out = []
            seen = set()
            for it in getattr(self.pm, "menu_items", []):
                if it.get("host") != host:
                    continue
                if it.get("location") not in (None, "toolbar"):
                    continue
                # 管理器实际存的是 `command_id`（callback 形式在注册时已被自动转成内部命令），
                # 这里同时兼容 `command`/`callback` 两种历史写法。
                cid = it.get("command_id") or it.get("command")
                if cid:
                    spec = self.pm.commands.get(cid, {})
                    label = spec.get("label") or it.get("label") or cid
                    handler = spec.get("handler")
                else:
                    cb = it.get("callback")
                    if not callable(cb):
                        continue
                    label = it.get("label") or getattr(cb, "__name__", "动作")
                    handler = cb
                    cid = "cb:%s" % label
                if cid in seen:
                    continue
                seen.add(cid)
                out.append((cid, label, handler))
            return out

        def build_actions(self, parent_layout, host):
            """在某宿主页里按插件注册生成按钮。"""
            made = []
            for cid, label, handler in self.toolbar_actions(host):
                btn = QtWidgets.QPushButton(str(label))
                btn.clicked.connect(lambda _c=False, h=handler, c=cid: self._invoke(h, c))
                parent_layout.addWidget(btn)
                self.buttons.setdefault(cid, []).append(btn)
                made.append(cid)
                self.report.add("(命令)", "command", str(label), "ok")
            return made

        def _invoke(self, handler, cid):
            """调用插件回调：异常绝不冒到 Qt 事件循环。"""
            if not callable(handler):
                self.report.add("(命令)", "command", cid, "skip", "handler 不可调用")
                return
            try:
                import inspect
                n = len([p for p in inspect.signature(handler).parameters.values()
                         if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
                handler(None) if n >= 1 else handler()
                self.report.add("(命令)", "command", cid, "ok", "已调用")
            except Exception as e:
                self.report.add("(命令)", "command", cid, "fail", "%s: %s" % (type(e).__name__, e))
                self.log("插件命令 %s 执行失败：%s: %s" % (cid, type(e).__name__, e), "err")

        def build_options(self, parent_layout, host, area):
            """把 register_option（新建下拉）与 register_option_entry（加条目）落到 Qt 下拉。"""
            made = []
            for ent in getattr(self.pm, "option_entries", []):
                if ent.get("host") == host and (area is None or ent.get("area") == area):
                    made.append(("entry", ent.get("value")))
                    self.report.add(ent.get("plugin", "?"), "option_entry",
                                    str(ent.get("value")), "ok")
            for opt in getattr(self.pm, "options", []):
                if opt.get("host") != host:
                    continue
                if area is not None and opt.get("area") != area:
                    continue
                row = QtWidgets.QWidget()
                lay = QtWidgets.QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.addWidget(QtWidgets.QLabel(str(opt.get("label", ""))))
                cb = QtWidgets.QComboBox()
                cb.addItems([str(c) for c in opt.get("choices", [])])
                cbk = opt.get("callback")
                if callable(cbk):
                    cb.currentTextChanged.connect(lambda t, f=cbk: self._invoke_choice(f, t))
                lay.addWidget(cb)
                parent_layout.addWidget(row)
                made.append(("option", opt.get("label")))
                self.report.add(opt.get("plugin", "?"), "option",
                                str(opt.get("label")), "ok")
            return made

        # ── builder 一路（唯一需要后端判定的部分）──────────────────────
        @staticmethod
        def classify_builder(builder):
            """判定 builder 是否只认 Tk（源码级；取不到源码时按 unknown 处理）。"""
            try:
                import inspect
                src = inspect.getsource(builder)
            except Exception:
                return "unknown", "取不到源码"
            hits = [m for m in TK_MARKERS if m in src]
            if hits:
                return "tk-only", "源码里出现 Tk 标记：%s" % ", ".join(hits)
            return "portable", ""

        @staticmethod
        def _looks_like_tk_error(msg):
            m = str(msg)
            return any(k in m for k in TK_ERROR_MARKERS)

        def add_panel(self, title, builder, host, area):
            """落位一个插件面板：可移植 → 真建；tk-only → 上报并跳过（不崩）。"""
            kind, why = self.classify_builder(builder)
            if kind == "tk-only" or kind == "unknown":
                self.report.add(self._plugin_of_builder(builder), "panel", title,
                                "skip", "%s（%s）" % (kind, why or "未知"))
                return None
            box = QtWidgets.QGroupBox(str(title))
            lay = QtWidgets.QVBoxLayout(box)
            lay.setContentsMargins(4, 4, 4, 4)
            ui = QtUiFactory()
            try:
                builder(box, ui) if self._takes_ui(builder) else builder(box)
            except Exception as e:
                msg = "%s: %s" % (type(e).__name__, e)
                # 静态预检漏掉的情况（lambda/闭包）：按运行期错误形状判 tk-only，
                # 如实上报为 skip；其它异常才算 fail。两者都不冒到 Qt 事件循环。
                if self._looks_like_tk_error(msg):
                    self.report.add(self._plugin_of_builder(builder), "panel", title,
                                    "skip", "tk-only（运行期判定：%s）" % msg[:90])
                else:
                    self.report.add(self._plugin_of_builder(builder), "panel", title,
                                    "fail", msg)
                return None
            lay.addStretch(1)          # 内容顶部对齐（也表明这个布局确实在用）
            self.panels.append(box)
            self.report.add(self._plugin_of_builder(builder), "panel", title, "ok")
            return box

        def add_tool(self, name, builder):
            """落位插件栏目（顶级 Tab）。"""
            kind, why = self.classify_builder(builder)
            if kind != "portable":
                self.report.add(self._plugin_of_builder(builder), "tool", name,
                                "skip", "%s（%s）" % (kind, why or "未知"))
                return None
            page = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(page)
            lay.setContentsMargins(4, 4, 4, 4)
            try:
                builder(page, QtUiFactory()) if self._takes_ui(builder) else builder(page)
            except Exception as e:
                msg = "%s: %s" % (type(e).__name__, e)
                if self._looks_like_tk_error(msg):
                    self.report.add(self._plugin_of_builder(builder), "tool", name,
                                    "skip", "tk-only（运行期判定：%s）" % msg[:90])
                else:
                    self.report.add(self._plugin_of_builder(builder), "tool", name,
                                    "fail", msg)
                return None
            lay.addStretch(1)
            self.tabs.append((name, page))
            self.report.add(self._plugin_of_builder(builder), "tool", name, "ok")
            return page

        @staticmethod
        def _takes_ui(builder):
            try:
                import inspect
                names = list(inspect.signature(builder).parameters)
                return len(names) >= 2
            except Exception:
                return False

        def _plugin_of_builder(self, builder):
            for p in getattr(self.pm, "panels", []):
                if p.get("builder") is builder:
                    return p.get("plugin", "?")
            for t in getattr(self.pm, "tools", []):
                if t.get("builder") is builder:
                    return t.get("file", t.get("plugin", "?"))
            return getattr(builder, "__module__", "?")

        def render_all(self, host, layout, area=None):
            """把一个宿主页能接收的可移植贡献全部落位，返回报告。"""
            self.build_actions(layout, host)
            self.build_options(layout, host, area)
            for p in list(getattr(self.pm, "panels", [])):
                if p.get("host") == host and (area is None or p.get("area") == area):
                    box = self.add_panel(p.get("title", "插件面板"), p.get("builder"),
                                         host, p.get("area"))
                    if box is not None:
                        layout.addWidget(box)
            for t in list(getattr(self.pm, "tools", [])):
                self.add_tool(t.get("name", "插件"), t.get("builder"))
            return self.report
