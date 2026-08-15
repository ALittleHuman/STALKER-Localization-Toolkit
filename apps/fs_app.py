# -*- coding: utf-8 -*-
"""文件系统 App (FSToolApp)."""
import os, sys, re, threading, struct, shutil, subprocess, tempfile, time, json, glob
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Set, Tuple, Union, Any, Callable
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(_BASE_DIR, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from toolkit import (
    T, color, apply_theme, apply_tk_defaults,
    dir_row, count_label, tool_header, tool_text,
    LogBox, CanvasTree, SplitPane, PluginManager,
    _make_pump, _role_of, refresh_theme, DEFAULT_ENCODINGS,
    fmt_size, read_text_file, parse_xml_texts,
    log_section, vscrollbar, drop_zone,
    _BaseTk, _HAS_DND, DND_FILES,
    log_to_file, errbox,
)

import stalker_fs
from stalker_fs import (FORMATS, pack_db, unpack_db, extract_file, auto_detect,
                         load_db, sqfs_check, sqfs_list, sqfs_extract, sqfs_pack)
ALL_FMTS = {**FORMATS, "sqfs": {"name": "SquashFS", "key": "sq", "scrambler": None, "pack": False}}
FMT_KEYS = ["auto"] + list(ALL_FMTS.keys())


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
    def __init__(self, master=None, plugins=None):
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
        if plugins is not None:
            self.plugins = plugins
        else:
            self.plugins = PluginManager(
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins"),
                log=self._log_plugin,
            )
            self.plugins.scan()
        self.running = False
        self._build_ui()
        self._ui = _make_pump(self.root)
        self.input_var.trace_add("write", self._on_input_change)
        if self.plugins.load_errors:
            for e in self.plugins.load_errors[:10]:
                self._log(e, "err")
            errs = "\n".join(self.plugins.load_errors[:10])
            self.root.after(600, lambda: messagebox.showwarning("插件加载失败", errs))

    # ═══ Plugin callback helpers ═══
    def _invoke_plugin_menu_cb(self, cb):
        """调用插件菜单回调：优先传宿主 app，兼容旧式无参回调。"""
        try:
            import inspect
            sig = inspect.signature(cb)
            if len(sig.parameters) >= 1:
                cb(self)
            else:
                cb()
        except (TypeError, ValueError):
            cb()

    def _invoke_plugin_option_cb(self, cb, value):
        """调用插件选项回调：优先传 (value, app)，兼容旧式 value / 无参回调。"""
        try:
            import inspect
            sig = inspect.signature(cb)
            n = len(sig.parameters)
            if n >= 2:
                cb(value, self)
            elif n == 1:
                cb(value)
            else:
                cb()
        except (TypeError, ValueError):
            cb(value)

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

        # ── 插件注册的选项 (register_option) ──
        self.plugin_option_vars = {}
        for opt in self.plugins.options:
            label = opt.get("label", "option")
            choices = list(opt.get("choices") or [])
            if not choices:
                continue
            var = tk.StringVar(value=choices[0])
            self.plugin_option_vars[label] = var
            cb = opt.get("callback")
            if callable(cb):
                var.trace_add("write", lambda *a, cb=cb, var=var: self._invoke_plugin_option_cb(cb, var.get()))
            opt_row = ttk.Frame(self.root); opt_row.pack(fill="x", padx=P, pady=(0,4))
            ttk.Label(opt_row, text=label, width=10).pack(side="left")
            om = tk.OptionMenu(opt_row, var, *choices)
            om.configure(bg=color("surface2"), fg=color("text"), activebackground=color("selected"),
                         activeforeground=color("text_bright"), font=color("font"), relief="flat", highlightthickness=0)
            om["menu"].configure(bg=color("surface2"), fg=color("text"), font=color("font"),
                                 activebackground=color("selected"), activeforeground=color("text_bright"))
            om.pack(side="left", padx=(4, 0))

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
            if mi.get("location", "context") != "context":
                continue
            self.db_ctree._ctx.add_separator()
            self.db_ctree._ctx.add_command(label=mi["label"], command=lambda cb=mi["callback"]: self._invoke_plugin_menu_cb(cb))

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
                try:
                    os.unlink(tf.name)
                except Exception as e:
                    self._log(f"  解密临时文件清理失败: {e}", "warn")
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
            elif self._try_plugin_decrypt(path):
                pass
            else:
                self._log("  无法识别 .sq 文件", "warn")
            return
        raw = load_db(path)
        fmt = self.fmt_var.get()
        entries = None
        if fmt == "auto":
            fmt = auto_detect(raw)
            if not fmt:
                # auto 模式也尝试插件格式
                for pf in self.plugins.formats:
                    try:
                        entries = pf["handler"]["unpack"](raw)
                        if entries:
                            fmt = pf["name"]
                            break
                    except Exception:
                        continue
        if fmt and fmt != "sqfs":
            if entries is None:
                plugin_fmt = next((f for f in self.plugins.formats if f["name"] == fmt), None)
                if plugin_fmt:
                    entries = plugin_fmt["handler"]["unpack"](raw)
                else:
                    entries = unpack_db(raw, fmt)
            if not entries:
                self._log(f"  {fmt}: 解析失败", "warn")
                return
            self.raws[path] = raw
            self.loaded[path] = self._build_model(entries, path)
            nf = sum(1 for e in entries if not e["is_dir"])
            self._log(f"  {fmt}: {len(entries)} 项, {nf} 文件", "ok")
            return
        # 标准识别失败：交给插件解密器，解密后再按 hsqs / X-Ray DB 解析。
        if self._try_plugin_decrypt(path):
            return
        self._log("  无法自动识别格式", "warn")

    def _try_plugin_decrypt(self, path):
        """Any file that failed standard recognition is offered to plugin decryptors."""
        entry = None
        try:
            if getattr(self, "plugins", None):
                entry = self.plugins.find_decryptor(path)
        except Exception:
            entry = None
        if not entry:
            return False
        try:
            raw = entry["decrypt"](path)
        except Exception as e:
            self._log(f"  插件解密错误: {e}", "err")
            return False
        if not raw:
            return False
        return self._load_decrypted(path, raw)

    def _load_decrypted(self, path, raw):
        """Parse decrypted bytes as SquashFS or X-Ray DB."""
        if raw[:4] in (b"hsqs", b"sqsh"):
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".sqfs", delete=False)
            try:
                tf.write(raw); tf.close()
                entries = sqfs_list(tf.name)
                if not entries:
                    self._log("  解密后 SquashFS 列表失败", "err")
                    return False
                self.raws[path] = b"DEC:" + tf.name.encode()
                self.loaded[path] = self._build_model(entries, path)
                nf = sum(1 for e in entries if not e["is_dir"])
                self._log(f"  插件解密: SquashFS {len(entries)} 项, {nf} 文件", "ok")
                return True
            except Exception as e:
                self._log(f"  解密后解析失败: {e}", "err")
                try:
                    if not tf.closed: tf.close()
                    os.unlink(tf.name)
                except Exception:
                    pass
                return False
        fmt = auto_detect(raw)
        entries = None
        if not fmt:
            for pf in self.plugins.formats:
                try:
                    entries = pf["handler"]["unpack"](raw)
                    if entries:
                        fmt = pf["name"]
                        break
                except Exception:
                    continue
        if fmt:
            if entries is None:
                entries = unpack_db(raw, fmt)
            if entries:
                self.raws[path] = raw
                self.loaded[path] = self._build_model(entries, path)
                nf = sum(1 for e in entries if not e["is_dir"])
                self._log(f"  插件解密: {fmt} {len(entries)} 项, {nf} 文件", "ok")
                return True
        self._log("  解密后数据无法识别", "err")
        return False

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
            desc = ((pf or {}).get("handler") or {}).get("description", "") or fmt
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

    def plugin_option(self, label):
        """读取插件选项当前值。label 为 register_option(label, choices) 中的 label。"""
        var = getattr(self, "plugin_option_vars", {}).get(label)
        return var.get() if var is not None else None

    def plugin_options(self):
        """返回所有插件选项的 {label: value} 字典。"""
        return {
            label: var.get()
            for label, var in getattr(self, "plugin_option_vars", {}).items()
        }

    def _pack_output_basename(self):
        """返回封包输出文件名（不含扩展名），无法可靠推断时返回 None。"""
        inp = self.input_var.get().strip()
        if inp and os.path.isdir(inp):
            return os.path.basename(os.path.normpath(inp))
        tops = []
        for rel, _, _ in self.files_data:
            top = rel.split("/", 1)[0]
            if top and top not in tops:
                tops.append(top)
        if len(tops) == 1 and tops[0]:
            top = tops[0]
            # 单文件封包时，去掉原扩展名；目录封包保留目录名
            if len(self.files_data) == 1 and "/" not in self.files_data[0][0]:
                return os.path.splitext(top)[0]
            return top
        return None

    def _pack(self):
        if self.running: return
        if not self.files_data: messagebox.showwarning("无文件", "请先添加文件"); return
        fmt = self.pack_fmt_var.get()
        out = self.pack_out_var.get().strip()
        ext = ".sqfs" if fmt == "sqfs" else ".db"
        base = self._pack_output_basename()
        if not out:
            initial = f"{base}{ext}" if base else f"packed{ext}"
            out = filedialog.asksaveasfilename(title="保存", defaultextension=ext, initialfile=initial)
            if not out: return; self.pack_out_var.set(out)
        elif os.path.isdir(out):
            if base:
                out = os.path.join(out, f"{base}{ext}")
            else:
                out = filedialog.asksaveasfilename(title="保存", defaultextension=ext,
                                                   initialdir=out, initialfile=f"packed{ext}")
                if not out: return; self.pack_out_var.set(out)
        else:
            if not os.path.splitext(out)[1]:
                out = out + ext
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


