#!/usr/bin/env python3
"""
XML 文件比较工具 — GUI 版
两种比较模式：
  1. 行数/ID 统计 — 递归比较两个文件夹中同名 XML 文件的行数与 id 属性出现次数
  2. ID 文本对比 — 比较相同 id 的文本内容，检测多/少哪些 id
支持拖拽文件夹到窗口（需 tkinterdnd2）。
"""

# ═══ 高 DPI 适配 ═══
import ctypes
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from toolkit import color, T as _TK, LogBox, apply_theme as _TK_apply_theme, apply_tk_defaults as _TK_apply_tk_defaults
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import re
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from collections import Counter
from tkinter import Toplevel, Frame, Label, Button, Entry, StringVar
from tkinter import ttk, messagebox, filedialog
from tkinter.font import Font

# 拖放支持（可选）
try:
    from tkinterdnd2 import TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False


# ═══════════════════════════════════════════
#  核心逻辑
# ═══════════════════════════════════════════

ID_PATTERN = re.compile(r'''\bid\s*=\s*["']([^"']+)["']''', re.IGNORECASE)

# 未转义的 & 和 < (STALKER 原版 XML 里常见, 严格 XML 解析会报 not well-formed)
_AMP_BAD = re.compile(rb'&(?!amp;|lt;|gt;|quot;|apos;|#x?[0-9a-fA-F]+;)')
_LT_BAD = re.compile(rb'<(?![!/?a-zA-Z])')
_COMMENT_BAD = re.compile(rb'<!--(-+)')


def _fix_entities(raw: bytes) -> bytes:
    """把未转义的 & 和 < 转成实体，修正 <!-- 后多余的 -，容忍原版 XML 的格式缺陷。"""
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
    lines = len(text.splitlines())
    ids = Counter(ID_PATTERN.findall(text))
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
        root = ET.fromstring(raw)
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


class App:
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
        _TK_apply_theme()
        _TK_apply_tk_defaults(self.root)

        self.results: list[dict] = []
        self.name_a = ""
        self.name_b = ""
        self.running = False

        self.mode_var = StringVar(value=MODE_STATS)
        self.filter_var = StringVar(value="不一致")
        self._current_detail_result = None

        self._build_ui()
        self._setup_dragdrop()
        if master is None:
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 布局 ──────────────────────────────

    def _build_ui(self):
        top = Frame(self.root)
        top.pack(fill="x", padx=12, pady=10)

        from toolkit import dir_row
        for label, key in [("文件夹 A:", "a"), ("文件夹 B:", "b")]:
            _, entry = dir_row(top, label, StringVar(),
                               browse=lambda k=key: self._browse(k), width=10)
            setattr(self, f"entry_{key}", entry)

        btn_row = Frame(self.root)
        btn_row.pack(fill="x", padx=12, pady=(0, 4))

        self.btn_compare = Button(btn_row, text="开始比较", font=self.font_ui,
                                  command=self._start_compare, width=12)
        self.btn_compare.pack(side="left", padx=(0, 8))

        Button(btn_row, text="清除", font=self.font_ui,
               command=self._clear_entries, width=6).pack(side="left", padx=(0, 8))
        Button(btn_row, text="导出", font=self.font_ui,
               command=self._export, width=6).pack(side="left", padx=(0, 12))

        # 模式选择
        Label(btn_row, text="比较模式:", font=self.font_ui).pack(side="left", padx=(0, 4))
        self.cb_mode = ttk.Combobox(btn_row, textvariable=self.mode_var,
                                    values=MODES, state="readonly", width=14)
        self.cb_mode.pack(side="left", padx=(0, 12))
        self.cb_mode.bind("<<ComboboxSelected>>", self._on_mode_change)

        self.lbl_status = Label(btn_row, text="" if _HAS_DND else "拖拽不可用，请用浏览按钮",
                                font=self.font_ui, fg=color("text_dim"))
        self.lbl_status.pack(side="left")

        self.stat_frame = Frame(self.root)
        self.stat_frame.pack(fill="x", padx=12)
        self.lbl_stat = Label(self.stat_frame, text="", font=self.font_ui, fg=color("text_dim"))
        self.lbl_stat.pack(side="left")

        filter_row = Frame(self.root)
        filter_row.pack(fill="x", padx=12, pady=(4, 0))
        Label(filter_row, text="筛选:", font=self.font_ui).pack(side="left")
        self.cb_filter = ttk.Combobox(filter_row, textvariable=self.filter_var,
                                      values=FILTERS_STATS, state="readonly", width=10)
        self.cb_filter.pack(side="left", padx=4)
        self.cb_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())

        # 底部：id 明细面板
        detail_frame = Frame(self.root)
        detail_frame.pack(fill="x", padx=12, pady=(4, 8))
        detail_frame.grid_columnconfigure(0, weight=1)

        from tkinter import Text as TkText
        self._detail_text = LogBox(detail_frame, height=6, wrap="word", scrollbar=False,
                                   tags=[("diff", color("red")), ("ok", color("green")),
                                         ("only", color("orange"))])
        self._detail_text.grid(row=0, column=0, sticky="nsew")

        btn_copy = Button(detail_frame, text="复制全部 id", font=self.font_ui,
                          command=self._copy_detail_ids, width=12)
        btn_copy.grid(row=0, column=1, sticky="ns", padx=(6, 0))

        tree_frame = Frame(self.root)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))

        columns = ("rel", "status", "lines", "ids", "detail")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                 selectmode="browse")
        self.tree.heading("rel", text="文件 (相对路径)")
        self.tree.heading("status", text="状态")
        self.tree.heading("lines", text="行数")
        self.tree.heading("ids", text="ID 数")
        self.tree.heading("detail", text="差异详情")

        self.tree.column("rel", width=280, minwidth=150)
        self.tree.column("status", width=60, minwidth=50, anchor="center")
        self.tree.column("lines", width=120, minwidth=80, anchor="center")
        self.tree.column("ids", width=120, minwidth=80, anchor="center")
        self.tree.column("detail", width=400, minwidth=200)

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
        if not _HAS_DND:
            return
        try:
            if hasattr(self.root, "drop_target_register"):
                self.root.drop_target_register("*")
                self.root.dnd_bind("<<Drop>>", self._on_dnd_drop)
        except Exception:
            pass

    def _on_dnd_drop(self, event):
        """处理从资源管理器拖入的文件夹。"""
        raw = event.data
        paths = self.root.tk.splitlist(raw)
        dirs = [Path(p) for p in paths if Path(p).is_dir()]
        if not dirs:
            return
        self._on_drop_files(dirs)

    # ── 动作 ──────────────────────────────

    def _browse(self, key: str):
        path = filedialog.askdirectory(title=f"选择文件夹 {key.upper()}")
        if path:
            getattr(self, f"entry_{key}").delete(0, "end")
            getattr(self, f"entry_{key}").insert(0, path)

    def _on_drop_files(self, paths: list[Path]):
        """拖入文件夹：按顺序填入空位，已有内容则跳过。"""
        entries = [self.entry_a, self.entry_b]
        for p in paths:
            for entry in entries:
                if not entry.get().strip():
                    entry.delete(0, "end")
                    entry.insert(0, str(p))
                    break
        if self.entry_a.get().strip() and self.entry_b.get().strip():
            self.root.after(200, self._start_compare)

    def _clear_entries(self):
        """清空两个目录栏。"""
        self.entry_a.delete(0, "end")
        self.entry_b.delete(0, "end")

    def _on_mode_change(self, event=None):
        """切换比较模式时更新筛选项和列标题。"""
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
        # 如果已有结果，按新模式重新渲染
        if self.results:
            self._refresh_tree()

    def _start_compare(self):
        if self.running:
            return
        pa = self.entry_a.get().strip()
        pb = self.entry_b.get().strip()
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
                    self.root.after(0, lambda c=i+1, t=total: self.lbl_status.config(
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
            self.root.after(0, self._on_done)
        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda: self._on_error(msg))

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
        self._refresh_tree()

    def _on_error(self, msg: str):
        self.running = False
        self.btn_compare.config(state="normal", text="开始比较")
        self.lbl_status.config(text="出错", fg=color("red"))
        messagebox.showerror("比较出错", msg)

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        filt = self.filter_var.get()
        mode = self.mode_var.get()
        is_text = (mode == MODE_TEXT)

        for r in self.results:
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
                vals = (r["rel"], f"仅{label}", "-", "-", "文件仅在一侧存在")
            elif r["consistent"]:
                if filt not in ("全部", "一致"):
                    continue
                tag = "ok"
                if is_text:
                    vals = (r["rel"], "✓", "0",
                            f"A:{r['ids_a']} / B:{r['ids_b']}", "")
                else:
                    vals = (r["rel"], "✓", f"A:{r['lines_a']} / B:{r['lines_b']}",
                            f"A:{r['ids_a']} / B:{r['ids_b']}", "")
            else:
                if is_text:
                    if filt not in ("全部", "有差异", "文本不同", "仅 A 有", "仅 B 有"):
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
                    d_display = build_text_detail(r, self.name_a, self.name_b) or "无详情"
                    vals = (r["rel"], "✗", str(total_diff),
                            f"A:{r['ids_a']} / B:{r['ids_b']}", d_display)
                else:
                    if filt not in ("全部", "不一致"):
                        continue
                    tag = "diff"
                    d_display = build_detail(r, self.name_a, self.name_b) or "无详情"
                    vals = (r["rel"], "✗", f"A:{r['lines_a']} / B:{r['lines_b']}",
                            f"A:{r['ids_a']} / B:{r['ids_b']}", d_display)

            self.tree.insert("", "end", values=vals, tags=(tag,))

    def _on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
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
        """选中行时在底部面板显示完整 id 明细。"""
        sel = self.tree.selection()
        if not sel or not self._detail_text:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.results):
            return
        r = self.results[idx]

        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", "end")

        if "only_side" in r:
            side = r["only_side"]
            label = self.name_a if side == "a" else self.name_b
            self._detail_text.insert("1.0", f"[ {r['rel']} ] 仅存在于 {label}")
            self._current_detail_result = None
        elif r["consistent"]:
            self._detail_text.insert("1.0",
                f"[ {r['rel']} ] ✓ 一致  "
                f"ID 数: A={r['ids_a']} B={r['ids_b']}")
            self._current_detail_result = None
        else:
            if r.get("mode") == "text":
                detail = build_full_text_detail(r, self.name_a, self.name_b) or "无差异"
            else:
                detail = build_full_detail(r, self.name_a, self.name_b) or "无差异"
            self._detail_text.insert("1.0", f"[ {r['rel']} ]\n{detail}")
            self._current_detail_result = r

        self._detail_text.config(state="disabled")

    def _copy_detail_ids(self):
        """复制当前明细中的所有 id 名到剪贴板。"""
        r = getattr(self, "_current_detail_result", None)
        if not r:
            messagebox.showinfo("提示", "请先在表格中选择一个包含 id 差异的文件。")
            return
        ids = []
        if r.get("only_a"):
            ids.extend(r["only_a"])
        if r.get("only_b"):
            ids.extend(r["only_b"])
        if r.get("text_diff"):
            ids.extend(iid for iid, _, _ in r["text_diff"])
        if r.get("count_diff"):
            ids.extend(iid for iid, _, _ in r["count_diff"])
        if not ids:
            messagebox.showinfo("提示", "当前文件没有 id 差异。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(ids))
        messagebox.showinfo("已复制", f"已复制 {len(ids)} 个 id 到剪贴板。")

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
        w.writerow([f"文件夹 A: {self.entry_a.get().strip()}"])
        w.writerow([f"文件夹 B: {self.entry_b.get().strip()}"])
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
        win = Toplevel(self.root)
        win.title(f"差异详情 — {filename}")
        win.geometry("650x450")
        win.minsize(400, 250)

        from tkinter import Text as TkText
        text = LogBox(win, wrap="word", scrollbar=False,
                      tags=[("diff", color("red")), ("ok", color("green")),
                            ("only", color("orange"))])
        text.pack(fill="both", expand=True)
        text.insert("1.0", detail)
        text.config(state="disabled")

        Button(win, text="关闭", font=self.font_ui, command=win.destroy, width=10).pack(pady=(0, 8))

    def _on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()
