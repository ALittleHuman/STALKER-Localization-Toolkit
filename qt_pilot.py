# -*- coding: utf-8 -*-
"""Qt（PySide6）试点：文件系统页。

**定位**：这是一个**试点**，不是替换。Tk 版（`stalker_toolkit.py` + `apps/fs_app.py`）一行不动，
本文件独立运行、独立验证；试点用真实数字回答"换单表面渲染工具包能不能做到内容跟手"，
并暴露迁移中真正会踩到的坑（DPI、线程→UI 回传、勾选树、虚拟化列表、打包体积）。

功能与 Tk 版**同清单、同引擎**：
    格式下拉 / 自动检测 / 解包选中 / 批量解包 / 输入·输出目录 / 进度·状态 /
    数据包列表（勾选 + 状态列）/ 包内文件（搜索 + 勾选）/ 封包区（格式·输出·+文件·+目录·移除·清空·封包）/ 日志栏
业务调用**直接复用** `file_system/stalker_fs`：`unpack_db` / `pack_db` / `fmt_key` / `FORMATS`。
未接：插件槽（`PLUGINS.md` 契约）、主题系统、TaskRunner —— 见回执里列出的迁移待办。

用法：
    python qt_pilot.py              # 打开试点窗口
    python qt_pilot.py --selftest   # 引擎接线自检（临时目录内真实往返），退出码 0=通过
    python qt_pilot.py --bench      # 量实时拖动/窗口缩放，打印数字
"""
import os
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    QT_AVAILABLE = True
    QT_IMPORT_ERROR = None
except Exception as e:                      # 缺失时本模块仍可被解释器导入（探针据此 SKIP）
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

# 主题映射（色板/字体来自 toolkit_theme 这一份真值；本模块不再自己写颜色）
try:
    import qt_pilot_theme as theme
    THEME_AVAILABLE = True
    THEME_IMPORT_ERROR = None
except Exception as e:
    theme = None
    THEME_AVAILABLE = False
    THEME_IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

# 业务逻辑依赖（与 Tk 版一致），缺失时同样不阻断导入
try:
    sys.path.insert(0, os.path.join(BASE, "file_system"))
    from stalker_fs import FORMATS, extract_file, fmt_key, pack_db, unpack_db
    ENGINE_AVAILABLE = True
    ENGINE_IMPORT_ERROR = None
except Exception as e:
    ENGINE_AVAILABLE = False
    ENGINE_IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

# 与 Tk 版一致的界面文案/清单：探针按这份清单核对"同清单"
WINDOW_TITLE = "STALKER Localization Toolkit — 文件系统（Qt 试点）"
DB_PANEL_TITLE = "数据包列表（.db / .sq）"
FILE_PANEL_TITLE = "包内文件"
PACK_PANEL_TITLE = "封包"
DB_BUTTONS = ("扫描目录", "全选", "加载选中", "取消加载", "移除", "清空")
FILE_BUTTONS = ("全选", "全不选")
TOP_BUTTONS = ("解包选中", "批量解包")
PACK_BUTTONS = ("+文件", "+目录", "移除", "清空", "封包")
DIR_ROWS = ("输入", "输出")


def is_db_name(path):
    """与 Tk 版 `apps/fs_app.py` 完全相同的判定：**最后一个点**起三字符为 .db / .sq。

    注意这条规则**不收** `xxx.xdb`（最后一个点是 ".xdb"，前三字符是 ".xd"）——
    试点必须与 Tk 版一致，否则"同清单"就不成立（真实数据里 xdb 包名通常是 xxx.db）。
    """
    n = os.path.basename(path).lower()
    d = n.rfind(".")
    return d >= 0 and n[d:d + 3] in (".db", ".sq")


def iter_files(folder):
    """扫描目录下的数据包（与 Tk 版一致：只收一层，按上面的规则过滤）。"""
    out = []
    try:
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if os.path.isfile(p) and is_db_name(p):
                out.append(p)
    except Exception:
        pass
    return out


if QT_AVAILABLE:

    class _Bridge(QtCore.QObject):
        """工作线程 → UI 的唯一通道（Qt 信号跨线程自动排队）。"""
        progress = QtCore.Signal(int)
        status = QtCore.Signal(str, str)
        log = QtCore.Signal(str, str)
        done = QtCore.Signal(str)

    class QtFSPage(QtWidgets.QWidget):
        """文件系统页（同清单、同引擎）。"""

        def __init__(self, parent=None, log_sink=None):
            super().__init__(parent)
            self.bridge = _Bridge()
            self._log_sink = log_sink
            self.dbs = []                 # [(path, size)]
            self.loaded = {}              # {path: [entry, ...]}
            self.pack_files = []          # [(name, abs_path)]
            self.busy = False
            self._build_ui()
            self._wire()

        # ── 控件清单（与 Tk 版对齐；objectName 供探针核对）────────────────
        def _build_ui(self):
            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(10, 8, 10, 8)
            root.setSpacing(4)

            title = QtWidgets.QLabel("STALKER X-Ray FS Tool")
            title.setObjectName("page_title")
            title.setProperty("role", "title")          # 由 QSS 按主题着色（不再自己 setFont）
            root.addWidget(title)

            # 顶部动作行：格式 + 自动检测 + 两个按钮
            top = QtWidgets.QHBoxLayout()
            top.addWidget(QtWidgets.QLabel("格式"))
            self.cb_fmt = QtWidgets.QComboBox()
            self.cb_fmt.setObjectName("cb_format")
            self.cb_fmt.addItems(["auto"] + [k for k in FORMATS] if ENGINE_AVAILABLE else ["auto"])
            top.addWidget(self.cb_fmt)
            self.lbl_auto = QtWidgets.QLabel("自动检测")
            self.lbl_auto.setObjectName("lbl_autodetect")
            top.addWidget(self.lbl_auto)
            top.addStretch(1)
            for text in TOP_BUTTONS:
                b = QtWidgets.QPushButton(text)
                b.setObjectName("btn_" + text)
                top.addWidget(b)
                if text == "解包选中":
                    self.btn_unpack_checked = b
                else:
                    self.btn_unpack_batch = b
            root.addLayout(top)

            # 输入/输出 目录行
            self.ed_input = QtWidgets.QLineEdit(); self.ed_input.setObjectName("ed_input")
            self.ed_output = QtWidgets.QLineEdit(); self.ed_output.setObjectName("ed_output")
            for label, edit in zip(DIR_ROWS, (self.ed_input, self.ed_output)):
                row = QtWidgets.QHBoxLayout()
                lab = QtWidgets.QLabel(label); lab.setObjectName("lbl_" + label)
                row.addWidget(lab)
                row.addWidget(edit, 1)
                b = QtWidgets.QPushButton("浏览")
                b.setObjectName("btn_browse_" + label)
                row.addWidget(b)
                b.clicked.connect(lambda _c=False, ed=edit: self._browse_into(ed))
                root.addLayout(row)

            # 进度 + 状态
            self.progress = QtWidgets.QProgressBar(); self.progress.setObjectName("progress")
            self.progress.setRange(0, 100)
            root.addWidget(self.progress)
            self.status = QtWidgets.QLabel("就绪"); self.status.setObjectName("status")
            root.addWidget(self.status)

            # 主区：上（数据包列表 | 包内文件）+ 下（封包）
            vsplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
            vsplit.setObjectName("split_outer")
            self.split_outer = vsplit
            top_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
            top_split.setObjectName("split_top")
            self.split_top = top_split

            # 数据包列表
            box_db = QtWidgets.QGroupBox(DB_PANEL_TITLE)
            box_db.setObjectName("panel_db")
            v = QtWidgets.QVBoxLayout(box_db)
            bar = QtWidgets.QHBoxLayout()
            self.db_buttons = []
            for text in DB_BUTTONS:
                b = QtWidgets.QPushButton(text); b.setObjectName("btn_db_" + text)
                bar.addWidget(b); self.db_buttons.append(b)
            bar.addStretch(1)
            self.lbl_db_count = QtWidgets.QLabel(""); self.lbl_db_count.setObjectName("lbl_db_count")
            bar.addWidget(self.lbl_db_count)
            v.addLayout(bar)
            self.tree_db = QtWidgets.QTreeWidget()
            self.tree_db.setObjectName("tree_db")
            self.tree_db.setHeaderLabels(["数据包", "大小", "状态"])
            self.tree_db.setRootIsDecorated(False)
            v.addWidget(self.tree_db, 1)
            top_split.addWidget(box_db)

            # 包内文件
            box_file = QtWidgets.QGroupBox(FILE_PANEL_TITLE)
            box_file.setObjectName("panel_file")
            v = QtWidgets.QVBoxLayout(box_file)
            bar = QtWidgets.QHBoxLayout()
            self.file_buttons = []
            for text in FILE_BUTTONS:
                b = QtWidgets.QPushButton(text); b.setObjectName("btn_file_" + text)
                bar.addWidget(b); self.file_buttons.append(b)
            bar.addStretch(1)
            v.addLayout(bar)
            srow = QtWidgets.QHBoxLayout()
            srow.addWidget(QtWidgets.QLabel("搜索"))
            self.ed_search = QtWidgets.QLineEdit(); self.ed_search.setObjectName("ed_search")
            srow.addWidget(self.ed_search, 1)
            v.addLayout(srow)
            self.tree_file = QtWidgets.QTreeWidget()
            self.tree_file.setObjectName("tree_file")
            self.tree_file.setHeaderLabels(["文件", "大小"])
            self.tree_file.setRootIsDecorated(False)
            v.addWidget(self.tree_file, 1)
            top_split.addWidget(box_file)

            vsplit.addWidget(top_split)

            # 封包
            box_pack = QtWidgets.QGroupBox(PACK_PANEL_TITLE)
            box_pack.setObjectName("panel_pack")
            v = QtWidgets.QVBoxLayout(box_pack)
            prow = QtWidgets.QHBoxLayout()
            prow.addWidget(QtWidgets.QLabel("格式"))
            self.cb_pack_fmt = QtWidgets.QComboBox(); self.cb_pack_fmt.setObjectName("cb_pack_format")
            self.cb_pack_fmt.addItems([k for k in FORMATS] if ENGINE_AVAILABLE else ["xdb"])
            prow.addWidget(self.cb_pack_fmt)
            prow.addWidget(QtWidgets.QLabel("输出"))
            self.ed_pack_out = QtWidgets.QLineEdit(); self.ed_pack_out.setObjectName("ed_pack_out")
            prow.addWidget(self.ed_pack_out, 1)
            b = QtWidgets.QPushButton("浏览"); b.setObjectName("btn_browse_pack")
            b.clicked.connect(lambda _c=False: self._browse_into(self.ed_pack_out))
            prow.addWidget(b)
            self.btn_pack = QtWidgets.QPushButton("封包"); self.btn_pack.setObjectName("btn_pack")
            prow.addWidget(self.btn_pack)
            v.addLayout(prow)
            brow = QtWidgets.QHBoxLayout()
            self.pack_buttons = []
            for text in PACK_BUTTONS:
                if text == "封包":
                    continue
                b = QtWidgets.QPushButton(text); b.setObjectName("btn_pack_" + text)
                brow.addWidget(b); self.pack_buttons.append(b)
            brow.addStretch(1)
            v.addLayout(brow)
            self.tree_pack = QtWidgets.QTreeWidget()
            self.tree_pack.setObjectName("tree_pack")
            self.tree_pack.setHeaderLabels(["待封包文件"])
            self.tree_pack.setRootIsDecorated(False)
            v.addWidget(self.tree_pack, 1)
            vsplit.addWidget(box_pack)
            vsplit.setSizes([600, 260])
            root.addWidget(vsplit, 1)

        def _wire(self):
            (dict(zip(DB_BUTTONS, self.db_buttons))["扫描目录"].clicked
             .connect(lambda: self.scan_dir()))
            (dict(zip(DB_BUTTONS, self.db_buttons))["全选"].clicked
             .connect(lambda: self._check_all_db(True)))
            (dict(zip(DB_BUTTONS, self.db_buttons))["取消加载"].clicked
             .connect(self.unload_checked))
            (dict(zip(DB_BUTTONS, self.db_buttons))["移除"].clicked.connect(self.remove_checked))
            (dict(zip(DB_BUTTONS, self.db_buttons))["清空"].clicked.connect(self.clear_dbs))
            (dict(zip(DB_BUTTONS, self.db_buttons))["加载选中"].clicked
             .connect(lambda: self.load_checked()))
            (dict(zip(FILE_BUTTONS, self.file_buttons))["全选"].clicked
             .connect(lambda: self._check_all_file(True)))
            (dict(zip(FILE_BUTTONS, self.file_buttons))["全不选"].clicked
             .connect(lambda: self._check_all_file(False)))
            self.ed_search.textChanged.connect(self._filter_files)
            self.btn_unpack_checked.clicked.connect(self.unpack_checked)
            self.btn_unpack_batch.clicked.connect(self.unpack_batch)
            (dict(zip([t for t in PACK_BUTTONS if t != "封包"], self.pack_buttons))["+文件"]
             .clicked.connect(self.add_pack_files))
            (dict(zip([t for t in PACK_BUTTONS if t != "封包"], self.pack_buttons))["+目录"]
             .clicked.connect(self.add_pack_dir))
            (dict(zip([t for t in PACK_BUTTONS if t != "封包"], self.pack_buttons))["移除"]
             .clicked.connect(self.remove_pack_files))
            (dict(zip([t for t in PACK_BUTTONS if t != "封包"], self.pack_buttons))["清空"]
             .clicked.connect(self.clear_pack_files))
            self.btn_pack.clicked.connect(self.do_pack)
            self.bridge.progress.connect(self.progress.setValue)
            self.bridge.status.connect(self.set_status)
            self.bridge.log.connect(self.log)

        # ── 基础 ──────────────────────────────────────────────────────────
        def log(self, msg, tag="info"):
            if self._log_sink is not None:
                self._log_sink(msg, tag)

        def set_status(self, text, kind="idle"):
            self.status.setText(text)

        def set_busy(self, busy):
            self.busy = busy
            for b in self.db_buttons + self.file_buttons + [self.btn_pack,
                                                            self.btn_unpack_checked,
                                                            self.btn_unpack_batch]:
                b.setEnabled(not busy)

        def _browse_into(self, edit):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择目录", edit.text() or BASE)
            if d:
                edit.setText(d)

        # ── 数据包列表 ────────────────────────────────────────────────────
        def scan_dir(self, folder=None):
            folder = folder or self.ed_input.text().strip() or BASE
            self.ed_input.setText(folder)
            found = iter_files(folder)
            self.dbs = [(p, os.path.getsize(p)) for p in found]
            self.tree_db.clear()
            for p, size in self.dbs:
                it = QtWidgets.QTreeWidgetItem([os.path.basename(p), _fmt_size(size), "未加载"])
                it.setCheckState(0, QtCore.Qt.Unchecked)
                it.setData(0, QtCore.Qt.UserRole, p)
                self.tree_db.addTopLevelItem(it)
            self.lbl_db_count.setText("%d 个" % len(self.dbs))
            self.log("扫描目录 %s：找到 %d 个数据包" % (folder, len(self.dbs)), "ok")
            return len(self.dbs)

        def _db_items(self):
            return [self.tree_db.topLevelItem(i) for i in range(self.tree_db.topLevelItemCount())]

        def _check_all_db(self, on):
            for it in self._db_items():
                it.setCheckState(0, QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)

        def checked_dbs(self):
            return [it.data(0, QtCore.Qt.UserRole) for it in self._db_items()
                    if it.checkState(0) == QtCore.Qt.Checked]

        def remove_checked(self):
            keep = [it for it in self._db_items() if it.checkState(0) != QtCore.Qt.Checked]
            self.tree_db.clear()
            for it in keep:
                self.tree_db.addTopLevelItem(it)
            self.lbl_db_count.setText("%d 个" % self.tree_db.topLevelItemCount())

        def clear_dbs(self):
            self.tree_db.clear()
            self.loaded.clear()
            self.dbs = []
            self.lbl_db_count.setText("")
            self.tree_file.clear()

        def unload_checked(self):
            for p in self.checked_dbs():
                self.loaded.pop(p, None)
                for it in self._db_items():
                    if it.data(0, QtCore.Qt.UserRole) == p:
                        it.setText(2, "未加载")
            self._refresh_files()

        # ── 加载（工作线程）──────────────────────────────────────────────
        def load_checked(self):
            return self.load_dbs(self.checked_dbs())

        def load_dbs(self, paths):
            if self.busy or not paths:
                return False
            self.set_busy(True)
            self.set_status("加载中…", "busy")

            def work():
                try:
                    for i, p in enumerate(paths, 1):
                        with open(p, "rb") as fh:
                            raw = fh.read()
                        entries = unpack_db(raw, fmt_key(self.cb_fmt.currentText()))
                        self.loaded[p] = entries
                        self.bridge.progress.emit(int(100 * i / len(paths)))
                        self.bridge.log.emit("已加载 %s：%d 项"
                                             % (os.path.basename(p), len(entries)), "ok")
                    self.bridge.status.emit("就绪", "idle")
                except Exception as e:
                    self.bridge.log.emit("加载失败：%s: %s" % (type(e).__name__, e), "err")
                    self.bridge.status.emit("加载失败", "err")
                finally:
                    self.bridge.done.emit("load")

            self.bridge.done.connect(self._after_load)
            threading.Thread(target=work, daemon=True).start()
            return True

        def _after_load(self, _what):
            try:
                self.bridge.done.disconnect(self._after_load)
            except Exception:
                pass
            for it in self._db_items():
                p = it.data(0, QtCore.Qt.UserRole)
                it.setText(2, "已加载" if p in self.loaded else "未加载")
            self._refresh_files()
            self.set_busy(False)

        def _refresh_files(self):
            """按**已加载表**重建包内文件树（不是按扫描列表 —— 直接 load_dbs 也要能显示）。"""
            self.tree_file.clear()
            for pkg, entries in self.loaded.items():
                for e in entries:
                    if e.get("is_dir"):
                        continue
                    it = QtWidgets.QTreeWidgetItem([e["path"], _fmt_size(e.get("size_real", 0))])
                    it.setCheckState(0, QtCore.Qt.Unchecked)
                    it.setData(0, QtCore.Qt.UserRole, (pkg, e))
                    self.tree_file.addTopLevelItem(it)

        def file_items(self):
            return [self.tree_file.topLevelItem(i)
                    for i in range(self.tree_file.topLevelItemCount())]

        def _check_all_file(self, on):
            for it in self.file_items():
                it.setCheckState(0, QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)

        def checked_files(self):
            return [it.data(0, QtCore.Qt.UserRole) for it in self.file_items()
                    if it.checkState(0) == QtCore.Qt.Checked]

        def _filter_files(self, text):
            text = (text or "").lower()
            for it in self.file_items():
                it.setHidden(bool(text) and text not in it.text(0).lower())

        # ── 解包 ─────────────────────────────────────────────────────────
        def unpack_checked(self):
            sel = self.checked_files()
            if not sel:
                self.log("没有勾选任何文件", "warn")
                return 0
            out = self.ed_output.text().strip()
            if not out:
                self.log("请先指定输出目录", "warn")
                return 0
            return self.unpack_files(sel, out)

        def unpack_batch(self):
            out = self.ed_output.text().strip()
            if not out:
                self.log("请先指定输出目录", "warn")
                return 0
            sel = [(p, e) for p in [x[0] for x in self.dbs]
                   for e in self.loaded.get(p, []) if not e.get("is_dir")]
            return self.unpack_files(sel, out)

        def unpack_files(self, sel, out_dir):
            """真实解包：按 entry 的 offset/size 从原始包中切出并写盘。"""
            if self.busy:
                return 0
            self.set_busy(True)
            self.set_status("解包中…", "busy")
            written = []
            try:
                rawcache = {}
                for i, (pkg, e) in enumerate(sel, 1):
                    raw = rawcache.get(pkg)
                    if raw is None:
                        with open(pkg, "rb") as fh:
                            raw = fh.read()
                        rawcache[pkg] = raw
                    data = extract_file(raw, e)
                    if data is None:
                        self.log("跳过目录条目：%s" % e.get("path"), "dim")
                        continue
                    dest = os.path.join(out_dir, e["path"].replace("/", os.sep))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as fh:
                        fh.write(data)
                    written.append((dest, data))
                    self.progress.setValue(int(100 * i / len(sel)))
                self.log("解包完成：%d 个文件 → %s" % (len(written), out_dir), "ok")
                self.set_status("就绪", "idle")
            except Exception as ex:
                self.log("解包失败：%s: %s" % (type(ex).__name__, ex), "err")
                self.set_status("解包失败", "err")
            finally:
                self.set_busy(False)
            return len(written)

        # ── 封包 ─────────────────────────────────────────────────────────
        def add_pack_files(self):
            paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "选择要封包的文件", BASE)
            for p in paths:
                self._add_pack_entry(os.path.basename(p), p)
            return len(paths)

        def add_pack_dir(self):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择要封包的目录", BASE)
            if not d:
                return 0
            n = 0
            for root, _dirs, files in os.walk(d):
                for name in files:
                    p = os.path.join(root, name)
                    rel = os.path.relpath(p, d).replace(os.sep, "/")
                    self._add_pack_entry(rel, p)
                    n += 1
            return n

        def _add_pack_entry(self, name, path):
            self.pack_files.append((name, path))
            self.tree_pack.addTopLevelItem(QtWidgets.QTreeWidgetItem([name]))

        def remove_pack_files(self):
            for it in list(self.tree_pack.selectedItems()):
                idx = self.tree_pack.indexOfTopLevelItem(it)
                if 0 <= idx < len(self.pack_files):
                    self.pack_files.pop(idx)
                self.tree_pack.takeTopLevelItem(idx)

        def clear_pack_files(self):
            self.pack_files = []
            self.tree_pack.clear()

        def do_pack(self, out_path=None):
            """真实封包：读文件 → pack_db → 写盘。"""
            if self.busy or not self.pack_files:
                return None
            out_path = out_path or self.ed_pack_out.text().strip()
            if not out_path:
                self.log("请先指定输出文件", "warn")
                return None
            self.set_busy(True)
            self.set_status("封包中…", "busy")
            try:
                files = []
                for name, path in self.pack_files:
                    with open(path, "rb") as fh:
                        files.append((name, fh.read(), False))
                raw = pack_db(files, fmt_key(self.cb_pack_fmt.currentText()))
                with open(out_path, "wb") as fh:
                    fh.write(raw)
                self.progress.setValue(100)
                self.log("封包完成：%d 个文件 → %s（%d 字节）"
                         % (len(files), out_path, len(raw)), "ok")
                self.set_status("就绪", "idle")
                return out_path
            except Exception as e:
                self.log("封包失败：%s: %s" % (type(e).__name__, e), "err")
                self.set_status("封包失败", "err")
                return None
            finally:
                self.set_busy(False)

    class PilotWindow(QtWidgets.QMainWindow):
        """试点主窗：页面 + 日志栏（真实迁移时日志栏由 Hub 提供）。"""

        def __init__(self):
            super().__init__()
            self.setWindowTitle(WINDOW_TITLE)
            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            lay = QtWidgets.QVBoxLayout(central)
            lay.setContentsMargins(6, 6, 6, 6)
            self.split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
            self.split.setObjectName("split_root")
            self.log_view = QtWidgets.QPlainTextEdit()
            self.log_view.setObjectName("log_view")
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumBlockCount(5000)
            self.page = QtFSPage(log_sink=self._append_log)
            self.split.addWidget(self.page)
            box = QtWidgets.QGroupBox("日志")
            box.setObjectName("panel_log")
            v = QtWidgets.QVBoxLayout(box)
            v.addWidget(self.log_view)
            self.split.addWidget(box)
            self.split.setSizes([700, 240])
            lay.addWidget(self.split)

            # 主题切换（试点要证明的不只是"能配色"，还有"能切换"）：
            # 亮/暗共用同一套样式代码，只有 mode 变 —— 与 Tk 侧 apply_theme(mode) 同层语义。
            bar = QtWidgets.QHBoxLayout()
            self.lbl_theme = QtWidgets.QLabel("")
            self.lbl_theme.setObjectName("lbl_theme")
            self.lbl_theme.setProperty("role", "dim")
            self.btn_theme = QtWidgets.QPushButton("切换主题")
            self.btn_theme.setObjectName("btn_theme")
            self.btn_theme.clicked.connect(self.toggle_theme)
            bar.addWidget(self.lbl_theme)
            bar.addStretch(1)
            bar.addWidget(self.btn_theme)
            lay.addLayout(bar)
            self._sync_theme_label()

            self.resize(1280, 860)          # 与 Tk 版同一逻辑尺寸

        # ── 主题 ──────────────────────────────────────────────────────
        def toggle_theme(self):
            if not THEME_AVAILABLE:
                return None
            # persist=True：写回 user.ltx 的 [theme] 段（与 Tk 侧 save_user_theme 同一份实现）
            m = theme.toggle(QtWidgets.QApplication.instance())
            self._sync_theme_label()
            self._append_log("已切换主题：%s（已写入 user.ltx）" % m, "info")
            return m

        def _sync_theme_label(self):
            if THEME_AVAILABLE:
                self.lbl_theme.setText("主题：%s" % theme.current_mode())

        def _append_log(self, msg, tag="info"):
            # 颜色来自主题映射（原先这里是 5 个手抄的十六进制 —— 与 toolkit_theme 会漂移）
            if THEME_AVAILABLE:
                self.log_view.appendHtml('<span style="color:%s">%s</span>'
                                         % (theme.log_color(tag), _esc(msg)))
            else:
                self.log_view.appendPlainText(msg)


def _fmt_size(n):
    try:
        n = int(n)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def make_app(argv=None):
    """创建 QApplication（含 DPI 策略 + 主题），便于探针/bench 复用。"""
    argv = list(sys.argv if argv is None else argv)
    try:
        QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    if THEME_AVAILABLE:
        # 不传 mode：apply() 会读 user.ltx 的 [theme] mode（上次选了什么就是什么）
        theme.apply(app)
    return app


# ══════════════════════════════════════════════════════════════════════
# 自检 / 基准（探针与回执用；不依赖人工点击）
# ══════════════════════════════════════════════════════════════════════
def selftest():
    """真实往返自检：临时目录里 pack → 扫描 → 加载 → 解包 → 逐字节比对。"""
    import shutil
    import tempfile

    results = []

    def ok(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="qt_pilot_")
    try:
        src = os.path.join(tmp, "src")
        out = os.path.join(tmp, "out")
        os.makedirs(src)
        payload = {}
        for i in range(5):
            name = "text_%02d.txt" % i
            data = ("内容 %d —— 与 Tk 版同一引擎往返。" % i).encode("utf-8") * (i + 1)
            with open(os.path.join(src, name), "wb") as fh:
                fh.write(data)
            payload[name] = data
        raw = pack_db([(n, d, False) for n, d in payload.items()], "xdb")
        db_path = os.path.join(tmp, "test.db")
        with open(db_path, "wb") as fh:
            fh.write(raw)
        ok("pack_db 产出非空", len(raw) > 0, "%d 字节" % len(raw))

        page = QtFSPage()
        n = page.scan_dir(tmp)
        ok("扫描目录找到数据包", n == 1, "找到 %d" % n)

        assert page.load_dbs([db_path]) is True
        deadline = time.time() + 20
        while page.busy and time.time() < deadline:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)
        entries = page.loaded.get(db_path, [])
        ok("加载后条目数与原始文件数一致", len(entries) == len(payload),
           "entries=%d" % len(entries))
        ok("包内文件树已填充", page.tree_file.topLevelItemCount() == len(payload),
           "tree=%d" % page.tree_file.topLevelItemCount())

        written = page.unpack_files([(db_path, e) for e in entries
                                     if not e.get("is_dir")], out)
        ok("解包写盘数量正确", written == len(payload), "%d 个" % written)
        same = 0
        for name, data in payload.items():
            p = os.path.join(out, name)
            if os.path.isfile(p) and open(p, "rb").read() == data:
                same += 1
        ok("解包内容与原始逐字节一致", same == len(payload), "%d/%d" % (same, len(payload)))

        page.pack_files = [(n_, os.path.join(src, n_)) for n_ in payload]
        outdb = os.path.join(tmp, "repack.db")
        got = page.do_pack(outdb)
        ok("封包写盘成功", got and os.path.isfile(outdb))
        if got:
            with open(outdb, "rb") as fh:
                raw2 = fh.read()
            ent2 = unpack_db(raw2, "xdb")
            same2 = 0
            for e in ent2:
                if e.get("is_dir"):
                    continue
                name = e["path"].split("/")[-1]
                if extract_file(raw2, e) == payload.get(name):
                    same2 += 1
            ok("重新封包后逐字节一致", same2 == len(payload), "%d/%d" % (same2, len(payload)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results


def bench(repeats=30):
    """量实时拖动分隔条 / 窗口缩放（与 Tk 侧同一口径：每帧真重排 + 真绘制）。"""
    win = PilotWindow()
    win.show()
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()

    h = win.split.height() or 900
    start, end = int(h * 0.45), int(h * 0.70)
    drag = []
    for k in range(repeats):
        pos = start + (end - start) * k // max(1, repeats - 1)
        t0 = time.perf_counter()
        win.split.setSizes([pos, max(1, h - pos)])
        app.processEvents()
        win.split.repaint()
        app.processEvents()
        drag.append((time.perf_counter() - t0) * 1000.0)
    drag.sort()

    res = []
    for k in range(8):
        big = (k % 2 == 0)
        t0 = time.perf_counter()
        win.resize(1280 + (40 if big else 0), 860 + (40 if big else 0))
        app.processEvents()
        win.repaint()
        app.processEvents()
        res.append((time.perf_counter() - t0) * 1000.0)
    res.sort()
    win.close()
    return {"drag_med": drag[len(drag) // 2], "drag_max": drag[-1],
            "resize_med": res[len(res) // 2], "resize_max": res[-1]}


def sample_theme_colors(mode="dark", app=None, show=True):
    """按 `mode` 渲染一组控件，采样它们的**真实像素**，回一个字典。

    为什么放在这里而不是探针里：开发态的探针锁与**冻结包里的** `--themecheck` 都要用它 ——
    采样口径（尤其是 device pixel ratio 那条）写两份必然漂移。
    实测教训：`grab()` 出来的是**设备像素**，而 `geometry()`/`mapTo()` 是**逻辑像素**，
    150% 缩放下差 1.5 倍；不换算就会采到"隔壁那个控件"的颜色（按钮采成分组框底色）。
    """
    if not QT_AVAILABLE or not THEME_AVAILABLE:
        return {}
    app = app or QtWidgets.QApplication.instance()
    theme.apply(app, mode)
    host = QtWidgets.QWidget()
    host.setObjectName("theme_sample")
    host.resize(460, 400)
    v = QtWidgets.QVBoxLayout(host)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    grp = QtWidgets.QGroupBox("分组")
    gv = QtWidgets.QVBoxLayout(grp)
    gv.setContentsMargins(20, 20, 20, 20)
    lab = QtWidgets.QLabel("正文样例")
    dim = QtWidgets.QLabel("次要样例")
    theme.apply_label_style(dim, "Dim.TLabel")
    btn = QtWidgets.QPushButton("普通按钮")
    acc = QtWidgets.QPushButton("强调按钮")
    theme.apply_button_style(acc, "Accent.TButton")
    ed = QtWidgets.QLineEdit("文本")
    box = QtWidgets.QPlainTextEdit("结果")
    pgb = QtWidgets.QProgressBar()
    pgb.setRange(0, 100)
    pgb.setValue(50)
    for w in (lab, dim, btn, acc, ed, box, pgb):
        gv.addWidget(w)
    gv.addSpacing(18)          # 分组框内部留一块**纯填充**（避开子控件与边框）
    v.addWidget(grp)
    v.addSpacing(18)           # 宿主自己留一块纯填充（露出 host 的 bg）
    if show:
        host.show()
    else:
        host.ensurePolished()
    app.processEvents()
    img = host.grab().toImage()
    dpr = float(img.devicePixelRatio() or 1.0)

    def at(widget, rx=0.5, ry=0.5):
        tl = widget.mapTo(host, QtCore.QPoint(0, 0))
        x = int((tl.x() + widget.width() * rx) * dpr)
        y = int((tl.y() + widget.height() * ry) * dpr)
        x = max(0, min(img.width() - 1, x))
        y = max(0, min(img.height() - 1, y))
        return QtGui.QColor(img.pixel(x, y)).name()

    def mid(widget, rx=0.12):
        return at(widget, rx, 0.5)

    got = {
        "host_bg": at(host, 0.5, 1.0 - 9.0 / max(1, host.height())),
        "group": at(grp, 0.5, 1.0 - 9.0 / max(1, grp.height())),
        "button": mid(btn),
        "accent_button": mid(acc),
        "entry": mid(ed),
        "textview": at(box, 0.85, 0.7),
        "progress_chunk": at(pgb, 0.25, 0.5),
        "dim_role": dim.property("role"),
        "dim_font_pt": dim.font().pointSize(),
        "title_font_pt": theme.make_font("font_title").pointSize(),
        "dpr": dpr,
    }
    host.close()
    host.deleteLater()
    app.processEvents()
    return got


# 采样点 → 色板角色（`--themecheck` 与探针共用同一份期望）
SAMPLE_ROLES = {"host_bg": "bg", "group": "surface", "button": "surface2",
                "accent_button": "accent", "entry": "entry_bg",
                "textview": "entry_bg", "progress_chunk": "accent"}


def theme_check():
    """冻结包/源码态都能跑的主题自检：来源、隔离、真实像素、切换、持久化。

    返回 `(PASS 行列表, FAIL 行列表)`。**不写用户的 user.ltx** —— 持久化那步把
    `toolkit_platform.app_dir` 重定向到临时目录（与 run_app_probe 同一打桩方式）。
    """
    ok, bad = [], []
    if not THEME_AVAILABLE:
        return ok, ["无法导入 qt_pilot_theme：%s" % (THEME_IMPORT_ERROR,)]

    def chk(name, cond, detail=""):
        (ok if cond else bad).append(name + (("  [%s]" % detail) if detail else ""))
        return bool(cond)

    import sys as _sys
    chk("主题真值来自 toolkit_theme（直接 import）", theme.theme_source_ok(),
        "modes=%s" % (theme.modes(),))
    chk("本进程没有 tkinter", "tkinter" not in _sys.modules,
        "tkinter in sys.modules=%s" % ("tkinter" in _sys.modules,))

    app = QtWidgets.QApplication.instance()
    samples = {}
    for m in theme.modes():
        s = sample_theme_colors(m, app, show=(QtWidgets.QApplication.platformName()
                                              != "offscreen"))
        samples[m] = s
        P = theme.palette(m)
        wrong = [k for k, role in SAMPLE_ROLES.items() if s.get(k) != P[role]]
        chk("真实像素 == 色板（%s）" % m, not wrong,
            "dpr=%s%s" % (s.get("dpr"), ("  不符: %s" % wrong) if wrong else ""))
    if len(samples) >= 2:
        a, b = samples["dark"], samples["light"]
        chk("亮/暗切换真的换了像素", a.get("host_bg") != b.get("host_bg"),
            "dark=%s light=%s" % (a.get("host_bg"), b.get("host_bg")))
    chk("语义样式生效（Dim.TLabel → role=dim + font_sm 磅值）",
        samples.get("dark", {}).get("dim_role") == "dim"
        and samples.get("dark", {}).get("dim_font_pt") == theme.font_spec("font_sm")[1])

    # 持久化：临时目录里真写一次，确认写的是 [theme] 段且不动别的段
    import os as _os
    import tempfile
    try:
        import toolkit_platform as tp
        d = tempfile.mkdtemp(prefix="qt_themecheck_")
        real = tp.app_dir
        tp.app_dir = lambda: d
        try:
            tp.save_user_values("ffmpeg", {"path": r"E:\x\ffmpeg.exe"})
            theme.save_mode("light")
            first = open(_os.path.join(d, "user.ltx"), "rb").read().decode("utf-8")
            got = theme.load_mode()
            theme.save_mode("dark")
            second = open(_os.path.join(d, "user.ltx"), "rb").read().decode("utf-8")
        finally:
            tp.app_dir = real
        chk("持久化：[theme] 写入并读回", ("[theme]" in first and got == "light"),
            "got=%r" % (got,))
        chk("持久化：不吞别的段（[ffmpeg] 两次写入后都在）",
            "[ffmpeg]" in first and "ffmpeg.exe" in first
            and "[ffmpeg]" in second and "ffmpeg.exe" in second)
    except Exception as e:
        chk("持久化：临时目录往返", False, "%s: %s" % (type(e).__name__, e))
    theme.apply(app, "dark")
    return ok, bad


def main(argv):
    if not QT_AVAILABLE:
        print("PySide6 不可用：%s" % QT_IMPORT_ERROR)
        return 2
    if not ENGINE_AVAILABLE:
        print("stalker_fs 不可用：%s" % ENGINE_IMPORT_ERROR)
        return 2
    if "--themecheck" in argv:
        # 冻结包里的主题自检：**off-screen 渲染**，不弹窗（构建验证时不该抢桌面焦点）
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = make_app(argv)
    if "--selftest" in argv:
        rows = selftest()
        bad = 0
        for name, good, detail in rows:
            print("  %s %s%s" % ("PASS" if good else "FAIL", name,
                                 ("  [%s]" % detail) if detail else ""))
            bad += 0 if good else 1
        print("PASS %d  FAIL %d" % (len(rows) - bad, bad))
        return 1 if bad else 0
    if "--bench" in argv:
        r = bench()
        print("Qt 试点 bench：实时拖动 中位 %.2f ms 最大 %.2f ms ；窗口缩放 中位 %.2f ms 最大 %.2f ms"
              % (r["drag_med"], r["drag_max"], r["resize_med"], r["resize_max"]))
        return 0
    if "--themecheck" in argv:
        good, bad = theme_check()
        for line in good:
            print("  PASS %s" % line)
        for line in bad:
            print("  FAIL %s" % line)
        # 机器可读行（**纯 ASCII**）：冻结 exe 的 stdout 编码取决于控制台代码页，
        # 中文行在别的进程里捕获时可能变成乱码 —— 验证脚本按这一行解析才可靠。
        print("THEMECHECK ok=%d bad=%d tkinter=%s"
              % (len(good), len(bad), "tkinter" in sys.modules))
        return 1 if bad else 0
    win = PilotWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
