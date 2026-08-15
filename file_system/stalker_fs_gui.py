"""STALKER X-Ray FS Tool — clean rewrite"""
import ctypes
try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except: pass
import os, sys, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BaseTk = TkinterDnD.Tk; _HAS_DND = True
except ImportError:
    # auto-install optional drag-drop dependency
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "tkinterdnd2"],
                       capture_output=True, timeout=120)
    except Exception:
        pass
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        _BaseTk = TkinterDnD.Tk; _HAS_DND = True
    except ImportError:
        _BaseTk = tk.Tk; _HAS_DND = False; DND_FILES = None

_base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base_dir)
sys.path.insert(0, os.path.dirname(_base_dir))
sys.path.insert(0, os.path.join(_base_dir, "..", "plugins"))
from stalker_fs import (FORMATS, pack_db, unpack_db, extract_file, auto_detect,
                         sqfs_check, sqfs_list, sqfs_extract, sqfs_pack, load_db)
from toolkit import log_section, color, T, CanvasTree, LogBox, dir_row, count_label, apply_theme as _apply_theme
import toolkit

ALL_FMTS = {**FORMATS, "SquashFS": {"name": "sq_base", "key": "sq", "scrambler": None, "pack": False}}
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



class App:
    def __init__(self, master=None):
        self.root = master or _BaseTk()
        if master is None:
            self.root.title("STALKER X-Ray FS Tool")
            self.root.geometry("1100x800"); self.root.minsize(900, 600)
        self.root.configure(bg=color("bg"))
        _apply_theme()
        self.fmt_var = tk.StringVar(value="auto")
        self.input_var = tk.StringVar(); self.output_var = tk.StringVar()
        self.db_files = []; self.files_data = []
        self.loaded = {}; self.raws = {}; self.merged = None
        self.running = False
        self._build_ui()
        self.input_var.trace_add("write", self._on_input_change)

    # ═══ Theme ═══
    def _setup_theme(self):
        """统一配色模板: 全部由 toolkit.apply_theme 提供."""
        toolkit.apply_theme()
    # ═══ UI ═══
    def _build_ui(self):
        P = 14
        ttk.Label(self.root, text="STALKER X-Ray FS Tool", style="Title.TLabel").pack(anchor="w", padx=P, pady=(P,2))
        top = ttk.Frame(self.root); top.pack(fill="x", padx=P, pady=(0,4))
        ttk.Label(top, text="格式", width=4).pack(side="left")
        cb = tk.OptionMenu(top, self.fmt_var, *FMT_KEYS)
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

        pan = ttk.Frame(self.root); pan.pack(fill="both", expand=True, padx=P, pady=(4,2))
        self._build_db_panel(pan)
        self._build_file_panel(pan)
        self._build_pack_panel()
        pg = ttk.Frame(self.root); pg.pack(fill="x", padx=P, pady=(0,2))
        self.progress = ttk.Progressbar(pg, mode="indeterminate")
        self.status_lbl = ttk.Label(pg, text="就绪", style="Dim.TLabel", font=color("font_sm")); self.status_lbl.pack(anchor="w")
        self.log_lf, self.log = log_section(self.root, "日志", height=4)

    def _build_db_panel(self, pan):
        left = ttk.LabelFrame(pan, text="DB 文件列表", padding=4); left.pack(side="left", fill="both", expand=True)
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

    def _build_file_panel(self, pan):
        right = ttk.LabelFrame(pan, text="包内文件", padding=4); right.pack(side="right", fill="both", expand=True)
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

    def _build_pack_panel(self):
        pf = ttk.LabelFrame(self.root, text="封包 (独立面板)", padding=4); pf.pack(fill="x", padx=14, pady=(0,2))
        # Row 1: format + output + pack button
        row1 = ttk.Frame(pf); row1.pack(fill="x", pady=(0,2))
        ttk.Label(row1, text="格式", width=4).pack(side="left")
        self.pack_fmt_var = tk.StringVar(value="xdb")
        pk = tk.OptionMenu(row1, self.pack_fmt_var, *[k for k in FMT_KEYS if k != "auto"])
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
        root = Node("", "", True)
        for e in entries:
            parts = e["path"].replace("\\", "/").split("/")
            n = root
            for i, part in enumerate(parts):
                is_dir = (i < len(parts) - 1) or e["is_dir"]
                if part not in n.children:
                    n.add(Node(part, "/".join(parts[:i + 1]), is_dir,
                               0 if is_dir else e["size_real"],
                               0 if is_dir else e["offset"]))
                n = n.children[part]
            if not n.is_dir:
                n.source = src; n.offset = e["offset"]; n.size = e["size_real"]
        return root

    def _rebuild_merged(self):
        self.merged = Node("", "", True)
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
        root = Node("", "", True)
        for f in self.db_files:
            n = Node(os.path.basename(f), f, False)
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
        """NLC 加密 sq_base: 用 nlc_sqfs 插件解密到临时文件, 按普通 SquashFS 浏览.
        raws[path] = b'DEC:' + temp_path 供解包时复用."""
        try:
            import nlc_sqfs
            dec = nlc_sqfs.decrypt_sq(path)
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
        except ImportError:
            self._log("  NLC 解密需要 nlc_sqfs.py 插件 (同目录)", "warn")
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
                    self._log(f"  SquashFS: {len(entries)} 条, {nf} 文件", "ok")
                else:
                    self._log("  SquashFS 解析失败 (缺 rdsquashfs?) ", "err")
            elif kind == "nlc":
                self._load_nlc(path)
            else:
                self._log("  无法识别的 .sq 文件", "warn")
            return
        raw = load_db(path)
        if fmt == "auto": fmt = auto_detect(raw)
        if not fmt or fmt == "SquashFS": self._log("  无法自动检测格式", "warn"); return
        entries = unpack_db(raw, fmt)
        self.raws[path] = raw
        self.loaded[path] = self._build_model(entries, path)
        nf = sum(1 for e in entries if not e["is_dir"])
        self._log(f"  {fmt}: {len(entries)} 条, {nf} 文件", "ok")

    def _check_all(self):
        if self.merged: self.merged.toggle(True); self._render(); self._refresh_db_list()
    def _check_none(self):
        if self.merged: self.merged.toggle(False); self._render(); self._refresh_db_list()

    # ═══ Input events ═══
    def _on_fmt_change(self, *a):
        fmt = self.fmt_var.get()
        self.fmt_desc.configure(text="自动检测" if fmt == "auto" else ALL_FMTS.get(fmt, {}).get("name", ""))

    def _on_input_change(self, *a):
        p = self.input_var.get().strip()
        if p and os.path.isfile(p) and (_is_db(p) or _is_sq(p)):
            self._add_db(p); self._load_all_checked()

    def _on_drop_input(self, e):
        paths = self.root.tk.splitlist(e.data)
        if not paths: return
        # set input var only for a single FILE (trace auto-loads it);
        # multi-drop is fully handled here to avoid double loading
        if len(paths) == 1 and os.path.isfile(paths[0]):
            self.input_var.set(paths[0])
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

    # ═══ Pack ═══
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
        root = Node("", "", True)
        for rel, data, _ in self.files_data:
            parts = rel.split("/")
            n = root
            for i, part in enumerate(parts):
                is_dir = i < len(parts) - 1
                if part not in n.children:
                    n.add(Node(part, "/".join(parts[:i+1]), is_dir,
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
        ext = ".sqfs" if fmt == "SquashFS" else f".{fmt}.db"
        if not out:
            out = filedialog.asksaveasfilename(title="保存", defaultextension=ext)
            if not out: return; self.pack_out_var.set(out)
        else:
            out = os.path.join(out, f"packed{ext}")
        self.running = True; self._log(f"封包 ({fmt})...", "hdr"); self.progress.start(10)
        self.status_lbl.configure(text="封包中...")
        def work():
            try:
                if fmt == "SquashFS":
                    ok = sqfs_pack(self.files_data, out)
                    if not ok: raise RuntimeError("SquashFS 封包失败 (缺 tar2sqfs?)")
                    self._log(f"完成: SquashFS → {out}", "ok")
                else:
                    db = pack_db(self.files_data, fmt)
                    with open(out, "wb") as f: f.write(db)
                    self._log(f"完成: {len(db)} 字节 → {out}", "ok")
                self.root.after(0, lambda: self.status_lbl.configure(text="完成", foreground=color("green")))
            except Exception as e: self._log(f"错误: {e}", "err")
            self.root.after(0, self._done)
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
                    else:
                        raw = self.raws.get(n.source)
                        if raw:
                            data = extract_file(raw, {"offset": n.offset, "size_real": n.size, "is_dir": False})
                            if data:
                                os.makedirs(os.path.dirname(p), exist_ok=True)
                                with open(p, "wb") as f: f.write(data)
                    self.root.after(0, lambda v=i+1: self.progress.configure(value=v))
                self._log(f"完成: {len(nodes)} 项", "ok")
                self.root.after(0, lambda: self.status_lbl.configure(text=f"完成: {len(nodes)} 项", foreground=color("green")))
            except Exception as e: self._log(f"错误: {e}", "err")
            self.root.after(0, self._done)
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
                self.root.after(0, lambda i=idx: self.status_lbl.configure(text=f"[{i+1}/{len(self.loaded)}] {os.path.basename(db_path)}"))
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
                    for n in files:
                        data = extract_file(raw, {"offset": n.offset, "size_real": n.size, "is_dir": False})
                        if data:
                            p = os.path.join(out, pkg, n.path.replace("/", os.sep)); os.makedirs(os.path.dirname(p), exist_ok=True)
                            with open(p, "wb") as f: f.write(data)
                    ok += 1; tf += len(files)
                    self._log(f"  {os.path.basename(db_path)} → {pkg}/: {len(files)} 文件", "dim")
                except Exception as ex: self._log(f"  {os.path.basename(db_path)}: 错误 {ex}", "err")
                self.root.after(0, lambda v=idx+1: self.progress.configure(value=v))
            self._log(f"完成: {ok}/{len(self.loaded)} 个包, 共 {tf} 文件", "ok")
            self.root.after(0, lambda: self.status_lbl.configure(text=f"完成: {tf} 文件", foreground=color("green")))
            self.root.after(0, self._done)
        threading.Thread(target=work, daemon=True).start()

    # ═══ Util ═══
    @staticmethod
    def _fmt_size(sz):
        if sz >= 1048576: return f"{sz/1048576:.1f} MB"
        if sz >= 1024: return f"{sz/1024:.1f} KB"
        return f"{sz} B"

    def _log(self, msg, tag="info"):
        self.root.after(0, lambda: self.log.add(msg, tag))
    def _done(self): self.running = False; self.progress.stop(); self.progress.configure(mode="indeterminate")
    def run(self):
        try:
            self.root.mainloop()
        finally:
            try:
                from stalker_fs import cleanup_sqfs_tools
                cleanup_sqfs_tools()
            except Exception:
                pass

if __name__ == "__main__": App().run()
