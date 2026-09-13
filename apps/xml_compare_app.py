# -*- coding: utf-8 -*-
"""XML 校对 App (XMLCompareApp)."""
from apps._bootstrap import (
    os, re, datetime, Path, Counter,
    ET, tk, ttk, filedialog, messagebox,
)

from toolkit import (
    color,
    dir_row, tool_header,
    LogBox, SplitPane, AutoScrollbar,
    _make_pump,
    _HAS_DND,
    errbox, log_summary, log_detail,
    plugin_slot_bar, tool_panel, refresh_dropdown,
    TaskRunner, status_style,
    decode_file, dialog_window, tool_button, tool_label,
    px, T,
    HOST_XML, AREA_TOP_BAR, AREA_FILTER,
    DEFAULT_FILTERS_STATS, row_matches_filter,
    PluginManager,
)
from apps.xml_modes import (MODE_STATS,
                            FILTERS_STATS, COLUMNS_STATS, builtin_mode_specs)

_AMP_BAD = re.compile(rb'&(?!amp;|lt;|gt;|quot;|apos;|#x?[0-9a-fA-F]+;)')
_LT_BAD = re.compile(rb'<(?![!/?a-zA-Z])')
_COMMENT_BAD = re.compile(rb'<!--(-+)')


def _fix_entities(raw: bytes) -> bytes:
    """把未转义的 & 和 < 转成实体、修正 <!-- 后多余的 -，容忍原版 XML 格式缺陷。"""
    raw = _AMP_BAD.sub(b'&amp;', raw)
    raw = _LT_BAD.sub(b'&lt;', raw)
    raw = _COMMENT_BAD.sub(b'<!--', raw)
    return raw


def collect_xml_files(root: Path) -> dict[str, Path]:
    files = {}
    for f in root.rglob("*.xml"):
        files[f.relative_to(root).as_posix()] = f
    return files


# `decode_file(filepath, enc_override)` 曾经在这里**又定义了一份**：编码判定在重构时
# 已上移进 `toolkit_textio`（本文件那份 docstring 自己都这么写），但薄包装留了下来 ——
# 于是同一个功能存在两份实现，而这份还**遮蔽**了公共层那份（本文件没有从 toolkit
# 导入 decode_file，所以调用点静默解析到本地这份）。现在改为直接用公共层那一份：
# 行为完全一致（两者都只是 `read_text_bytes(...)[:2]`），但真相只有一处。


# ── 模式 1：行数/ID 统计 ──────────────────

ID_PATTERN = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def parse_file(filepath: Path, enc_override: str = "auto") -> tuple[int, Counter, str]:
    text, used_enc = decode_file(filepath, enc_override)
    # 行数统计用原始内容 (含 XML 声明), 反映实际文件行数。
    # 口径与旧版一致: len(text.splitlines()) —— 只有**真正多出一行内容**才算多一行。
    # 曾错误地对结尾换行额外 +1, 于是"A 文件有结尾换行、B 没有"这类纯格式差异
    # 会被当成行数不一致, consistent 被误判为 False（B1）。
    lines = len(text.splitlines())
    # ID 统计忽略 XML 声明 (含 BOM), 声明 encoding 差异不影响
    body = re.sub(r"^\s*\ufeff?\s*<\?xml[^>]*\?>\s*", "", text, count=1, flags=re.I | re.S)
    ids = Counter(ID_PATTERN.findall(body))
    return lines, ids, used_enc


def compare_one(rel: str, fa: Path, fb: Path,
                enc_a: str = "auto", enc_b: str = "auto") -> dict:
    la, ida, enc_used_a = parse_file(fa, enc_a)
    lb, idb, enc_used_b = parse_file(fb, enc_b)

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
        "encoding_a": enc_used_a, "encoding_b": enc_used_b,
    }


def _side_labels(na: str, nb: str) -> tuple[str, str]:
    """两侧显示名：目录名为空时退化为 A / B。

    未开始比较前 self.name_a/name_b 都是空串，明细里会渲染成
    「ID 数: =3, =3」这种没有主语、看不懂的文本。
    """
    return (na.strip() if isinstance(na, str) and na.strip() else "A",
            nb.strip() if isinstance(nb, str) and nb.strip() else "B")


def build_full_detail(r: dict, na: str, nb: str) -> str:
    """统计模式完整明细；缺键时中性显示，绝不抛异常（C2）。"""
    na, nb = _side_labels(na, nb)
    side = r.get("only_side")
    if side:
        label = na if side == "a" else nb
        return f"文件仅在一侧存在: 仅 {label} 有 {r.get('rel', '')}"

    lines = []
    lines_a, lines_b = r.get("lines_a"), r.get("lines_b")
    if isinstance(lines_a, int) and isinstance(lines_b, int) and lines_a != lines_b:
        lines.append(f"行数: {na}={lines_a}, {nb}={lines_b} (差 {abs(lines_a - lines_b)})")
    if r.get("encoding_a") or r.get("encoding_b"):
        lines.append(f"编码: {na}={r.get('encoding_a') or '-'} / {nb}={r.get('encoding_b') or '-'}")
    ida = r.get("ida") or {}
    idb = r.get("idb") or {}
    only_a = r.get("only_a") or []
    only_b = r.get("only_b") or []
    count_diff = r.get("count_diff") or []
    lines.append(f"ID 数: {na}={r.get('ids_a', '-')}, {nb}={r.get('ids_b', '-')}")

    if only_a:
        lines.append(f"\n仅 {na} 有的 id ({len(only_a)} 个):")
        for iid in only_a:
            lines.append(f'  id="{iid}" ×{ida.get(iid, "?")}')
    if only_b:
        lines.append(f"\n仅 {nb} 有的 id ({len(only_b)} 个):")
        for iid in only_b:
            lines.append(f'  id="{iid}" ×{idb.get(iid, "?")}')
    if count_diff:
        lines.append(f"\n出现次数不同的 id ({len(count_diff)} 个):")
        for item in count_diff:
            try:
                iid, ca, cb = item
            except (TypeError, ValueError):
                lines.append(f"  {item}")
                continue
            lines.append(f'  id="{iid}"  {na}:{ca} / {nb}:{cb}')
    if not any((only_a, only_b, count_diff)) and not (
            isinstance(lines_a, int) and isinstance(lines_b, int) and lines_a != lines_b):
        lines.append("(无可列出的差异)")
    return "\n".join(lines)


# ── 模式 2：ID 文本对比 ──────────────────

def parse_file_text_by_id(filepath: Path, enc_override: str = "auto") -> tuple[dict[str, str], str]:
    """
    解析 STALKER 风格 XML，提取 id → 文本内容 映射。
    支持两种常见格式：
      <string id="xxx"><text>内容</text></string>
      <text id="xxx">内容</text>
    """
    result = {}
    text, used_enc = decode_file(filepath, enc_override)
    try:
        text = _fix_entities(text.encode("utf-8")).decode("utf-8", "ignore")
        root = None
        try:
            root = ET.fromstring(text)
        except Exception:
            # 无根节点 / 多根平铺的情况 (NLC 英文版常见): 去掉声明后包一层 root
            text_no_decl = re.sub(r"<\?xml[^>]*\?>", "", text, count=1, flags=re.I | re.S)
            root = ET.fromstring("<root>" + text_no_decl + "</root>")
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
    except Exception as e:
        # M1: 解析失败绝不能静默——此时 result 为空, 比较结论"两侧都没有 id"
        # 是假象, 用户必须知道结果不可信。
        log_summary(f"XML 解析失败（结果不可信）: {filepath} -> {type(e).__name__}: {e}",
                    "warn")
    return result, used_enc


def compare_text_content(rel: str, fa: Path, fb: Path,
                        enc_a: str = "auto", enc_b: str = "auto") -> dict:
    """
    按 ID 比较两个 XML 文件的文本内容。
    返回 only_a（A 有 B 无的 id）、only_b（B 有 A 无的 id）、
    text_diff（文本不同的 id 及两方文本）。
    """
    ida, enc_used_a = parse_file_text_by_id(fa, enc_a)
    idb, enc_used_b = parse_file_text_by_id(fb, enc_b)

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
        "encoding_a": enc_used_a, "encoding_b": enc_used_b,
    }


def _first_diff_info(a: str, b: str):
    """返回 (位置, A字符, B字符)；完全相同返回 None。"""
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            return i, ca, cb
    return None


def _char_desc(ch: str) -> str:
    """字符描述: 显示字符本身 + Unicode 码点；替换符特别标注。"""
    if ch == "\ufffd":
        return "� U+FFFD(坏字符/替换符)"
    return f"{ch!r} U+{ord(ch):04X}"


def build_full_text_detail(r: dict, na: str, nb: str) -> str:
    """文本比较模式完整差异明细（缺键时中性显示，绝不抛异常）。"""
    na, nb = _side_labels(na, nb)
    side = r.get("only_side")
    if side:
        label = na if side == "a" else nb
        return f"文件仅在一侧存在: 仅 {label} 有 {r.get('rel', '')}"

    lines = []
    if r.get("encoding_a") or r.get("encoding_b"):
        lines.append(f"编码: {na}={r.get('encoding_a') or '-'} / {nb}={r.get('encoding_b') or '-'}")
    lines.append(f"ID 数: {na}={r.get('ids_a', '-')}, {nb}={r.get('ids_b', '-')}")
    ida_text = r.get("ida_text") or {}
    idb_text = r.get("idb_text") or {}
    only_a = r.get("only_a") or []
    only_b = r.get("only_b") or []
    text_diff = r.get("text_diff") or []

    if only_a:
        lines.append(f"\n仅 {na} 有的 id ({len(only_a)} 个):")
        for iid in only_a:
            text = ida_text.get(iid, "")
            preview = text[:60] + ("…" if len(text) > 60 else "")
            lines.append(f'  id="{iid}"  →  {preview}')

    if only_b:
        lines.append(f"\n仅 {nb} 有的 id ({len(only_b)} 个):")
        for iid in only_b:
            text = idb_text.get(iid, "")
            preview = text[:60] + ("…" if len(text) > 60 else "")
            lines.append(f'  id="{iid}"  →  {preview}')

    if text_diff:
        lines.append(f"\n文本不同的 id ({len(text_diff)} 个):")
        for item in text_diff:
            try:
                iid, ta, tb = item
            except (TypeError, ValueError):
                lines.append(f"  {item}")
                continue
            lines.append(f'  id="{iid}"')
            fi = _first_diff_info(ta, tb)
            if fi is not None:
                pos, ca, cb = fi
                lines.append(f"    首个差异@{pos}: {na}={_char_desc(ca)}  vs  {nb}={_char_desc(cb)}")
            lines.append(f"    {na}: {ta}")
            lines.append(f"    {nb}: {tb}")
            lines.append("")

    if not (only_a or only_b or text_diff):
        lines.append("(无可列出的差异)")
    return "\n".join(lines)


# ═══════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════

# 模式与筛选的取值来自贡献点声明（见 apps/xml_modes.py）；
# 这里不再本地定义，避免"两份取值"再次漂移。
# D4：这里曾经声称 MODE_TEXT / MODES / FILTERS_TEXT「由顶部 import 提供」，
# 实际只导入了 MODE_STATS / FILTERS_STATS，任何引用都会 NameError。
# 现在按事实处理：只导入真正使用的两个名字（模式下拉的候选值来自
# PluginManager.compare_modes_for()、筛选项来自模式声明），注释不再撒谎。

ENCODINGS = ["auto", "utf-8", "windows-1251", "windows-1252", "gbk", "latin-1"]


class XMLCompareApp:
    """XML 校对。

    统一契约：只接收宿主 Tab（parent）——不自建根窗口、不应用主题、不自建日志面板；
    日志走全局两级通道（log_summary / log_detail）。
    """

    def __init__(self, parent):
        self.root = parent
        self.font_mono = color("font_mono")
        self.font_ui = color("font")

        self.results: list[dict] = []
        self.name_a = ""
        self.name_b = ""
        self.tree = None
        # 注册内置比较模式：与插件贡献的模式走**同一张表**（能力 6 贡献点）
        _pm = PluginManager.shared()
        for _spec in builtin_mode_specs():
            _pm.register_compare_mode(**_spec)

        self.mode_var = tk.StringVar(value=MODE_STATS)
        self.filter_var = tk.StringVar(value="不一致")

        self._ui = _make_pump(self.root)
        self._build_ui()
        # 统一任务壳（忙碌标志 / 按钮禁用恢复 / 状态语义色 / 线程）
        self.task = TaskRunner(
            self.root, self._ui,
            on_busy=lambda busy: self.btn_compare.config(
                state="disabled" if busy else "normal",
                text="比较中..." if busy else "开始比较"),
            status_setter=lambda text, kind="idle": self.lbl_status.config(
                text=text, fg=status_style(kind)),
        )
        # 拖放：只由目录框（dir_row 的 drop）精准接收，**不注册整个窗口** ——
        # 整窗拖拽会把拖到任意位置的文件都当输入，与"目录框"的语义冲突。
        # 原先这里调了一个只含 `pass` 的 `_setup_dragdrop()` 来"留个说明"，
        # 空方法 + 空调用没有作用，说明改成本注释。

    # ── 布局 ──────────────────────────────

    def _build_ui(self):
        top = tk.Frame(self.root)
        tool_header(self.root, "XML校对")
        # 插件动作区（toolbar 槽；无插件注册时不创建任何控件）
        # context 传**可调用对象**：构造时 self.results 必为空，写死的话
        # {"has_results": ...} 条件恒为假（C3）。出结果后由 _on_done 调 refresh()。
        self._slot_bar = plugin_slot_bar(self.root, HOST_XML, app=self,
                                         context=lambda: {"has_results": bool(self.results)})
        # 插件贡献的子栏目（api.register_panel，area="top_bar"）：无注册时不创建控件
        tool_panel(self.root, HOST_XML, AREA_TOP_BAR, app=self)
        top.pack(fill="x", padx=12, pady=10)

        self.entry_a_var = tk.StringVar()
        self.entry_b_var = tk.StringVar()
        for label, key in [("文件夹 A:", "a"), ("文件夹 B:", "b")]:
            var = self.entry_a_var if key == "a" else self.entry_b_var
            _, entry = dir_row(top, label, var,
                               browse=lambda k=key: self._browse(k),
                               drop=lambda e, k=key: self._on_drop_dir(e, k), width=10)
            setattr(self, f"entry_{key}", entry)

        btn_row = tk.Frame(self.root)
        btn_row.pack(fill="x", padx=12, pady=(0, 4))

        # 编码选择：auto = 自动判定（BOM > 严格 UTF-8 > XML 声明 > 统计探测 > windows-1251）；
        # 显式指定时**手动值优先于以上全部**（toolkit_textio.sniff_encoding 的 override 分支）。
        # 实际用到的编码会在选中行的明细栏、以及导出 CSV 的「编码」行回显（D3）。
        enc_row = tk.Frame(self.root)
        enc_row.pack(fill="x", padx=12, pady=(0, 4))
        tool_label(enc_row, text="编码 A（auto=自动判定）:", font_role="font").pack(side="left", padx=(0, 4))
        self.enc_a_var = tk.StringVar(value="auto")
        self.cb_enc_a = ttk.Combobox(enc_row, textvariable=self.enc_a_var,
                                     values=ENCODINGS, state="readonly", width=14)
        self.cb_enc_a.pack(side="left", padx=(0, 12))
        tool_label(enc_row, text="编码 B（auto=自动判定）:", font_role="font").pack(side="left", padx=(0, 4))
        self.enc_b_var = tk.StringVar(value="auto")
        self.cb_enc_b = ttk.Combobox(enc_row, textvariable=self.enc_b_var,
                                     values=ENCODINGS, state="readonly", width=14)
        self.cb_enc_b.pack(side="left", padx=(0, 12))

        self.btn_compare = tool_button(btn_row, "开始比较", font_role="font",
                                   command=self._start_compare, width=12)
        self.btn_compare.pack(side="left", padx=(0, 8))

        tool_button(btn_row, "清除", font_role="font",
               command=self._clear_entries, width=6).pack(side="left", padx=(0, 12))

        # 模式选择
        tool_label(btn_row, text="比较模式:", font_role="font").pack(side="left", padx=(0, 4))
        self.cb_mode = ttk.Combobox(btn_row, textvariable=self.mode_var,
                                    values=list(PluginManager.shared().compare_modes_for()),
                                    state="readonly", width=14)
        self.cb_mode.pack(side="left", padx=(0, 12))
        self.cb_mode.bind("<<ComboboxSelected>>", self._on_mode_change)

        self.lbl_status = tool_label(btn_row, "" if _HAS_DND else "拖拽不可用，请用浏览按钮",
                                font_role="font", fg_role="text_dim")
        self.lbl_status.pack(side="left")

        self.stat_frame = tk.Frame(self.root)
        self.stat_frame.pack(fill="x", padx=12)
        self.lbl_stat = tool_label(self.stat_frame, "", font_role="font", fg_role="text_dim")
        self.lbl_stat.pack(side="left")

        filter_row = tk.Frame(self.root)
        filter_row.pack(fill="x", padx=12, pady=(4, 0))
        tool_label(filter_row, text="筛选:", font_role="font").pack(side="left")
        self.cb_filter = ttk.Combobox(filter_row, textvariable=self.filter_var,
                                      values=refresh_dropdown(None, HOST_XML, AREA_FILTER,
                                                              FILTERS_STATS),
                                      state="readonly", width=10)
        self.cb_filter.pack(side="left", padx=4)
        self.cb_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_tree())
        # 「导出为表格」放在筛选行（与筛选下拉水平）：导出的就是**当前筛选后**的表格，
        # 两者放一起才看得出"所见即所得"。原先它在上一行的按钮区，与筛选割裂。
        tool_button(filter_row, "导出为表格", font_role="font",
                    command=self._export, width=12).pack(side="left", padx=(12, 0))

        # ═══ 主区: 表格 + 内嵌详情栏 (中间可拖拽分隔) ═══
        # 日志面板由 Hub 统一提供，工具内不再自建；下面的详情栏是功能控件，保留。
        top_area = tk.Frame(self.root)
        top_area.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        inner = SplitPane(top_area, orient="vertical")
        inner.pack(fill="both", expand=True)
        self._inner = inner

        tree_frame = tk.Frame(inner)
        inner.add(tree_frame, weight=3)

        # 详情栏 (内嵌于主区, 与表格之间可拖拽分隔; 平时隐藏)
        # 上半 = 明细文本，下半 = **逐条 id + 「复制id」按钮**。
        # 「复制全部 id」已按用户要求删除：一次性把几十个 id 拼成多行塞进剪贴板，
        # 实际用起来对不上号；改为每条 id 各有一个复制按钮。
        # 该容器**统一用 grid** 管理子控件：LogBox 在 scrollbar=True 时会自己包一个
        # 滚动条并 pack，与 grid 混用会直接 TclError（cannot use geometry manager
        # grid ... already has slaves managed by pack），所以这里 scrollbar=False
        # 并自己用 grid 摆滚动条。
        self.detail_frame = tk.Frame(inner)
        self.detail_frame.grid_columnconfigure(0, weight=1)
        self.detail_frame.grid_rowconfigure(0, weight=1)
        self._detail_text = LogBox(self.detail_frame, height=8, wrap="word", scrollbar=False,
                                   tags=[("diff", "red"), ("ok", "green"),
                                         ("only", "orange")])
        detail_vsb = AutoScrollbar(self.detail_frame, orient="vertical",
                                   command=self._detail_text.yview)
        self._detail_text.configure(yscrollcommand=detail_vsb.set)
        self._detail_text.grid(row=0, column=0, sticky="nsew")
        detail_vsb.grid(row=0, column=1, sticky="ns")
        self._id_frame = ttk.LabelFrame(self.detail_frame, text=" 差异 id（逐条复制）",
                                        padding=4)
        self._id_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # 列与表头由**模式声明**构建（插件贡献的新列同样出现在这里）
        self._tree_frame = tree_frame
        self._apply_columns()
        # 表格的挂载/滚动钩子/事件绑定/tag 配色统一由 _attach_tree 负责，
        # 这样模式切换重建 Treeview 后不会「表格消失、绑定与配色全丢」（C1）。
        self._attach_tree(self.tree)

    def _attach_tree(self, tree):
        """把 Treeview 挂进 tree_frame，并接好滚动条、事件、tag 配色。

        _build_ui 与 _apply_columns 都要调用它：ttk.Treeview 的 columns 不可变，
        模式切换必须销毁重建，而重建后的控件不会自动继承 grid 位置、滚动钩子、
        事件绑定与 tag_configure —— 漏掉任何一项都表现为「切一次模式表格就废了」。
        """
        vsb = AutoScrollbar(self._tree_frame, orient="vertical", command=tree.yview)
        hsb = AutoScrollbar(self._tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._tree_frame.grid_rowconfigure(0, weight=1)
        self._tree_frame.grid_columnconfigure(0, weight=1)

        tree.bind("<Double-1>", self._on_double_click)
        tree.bind("<<TreeviewSelect>>", self._on_row_select)
        tree.tag_configure("diff", foreground=color("red"))
        tree.tag_configure("ok", foreground=color("green"))
        tree.tag_configure("only", foreground=color("orange"))
        return tree

    # ── 拖放 ──────────────────────────────
    # 拖拽只绑在目录框上（见上面 _build_ui 里的说明），这里不再有整窗注册。

    def _browse(self, key: str):
        path = filedialog.askdirectory(title=f"选择文件夹 {key.upper()}")
        if path:
            var = self.entry_a_var if key == "a" else self.entry_b_var
            var.set(path)


    def _on_drop_dir(self, event, key: str):
        """拖拽文件夹到目录框: 精准定位到 A 或 B."""
        raw = event.data
        try:
            paths = self.root.tk.splitlist(raw)
        except Exception:
            paths = [raw]
        dirs = [p for p in paths if os.path.isdir(p)]
        if not dirs:
            return
        var = self.entry_a_var if key == "a" else self.entry_b_var
        var.set(dirs[0])

    def _clear_entries(self):
        """清空两个目录栏。"""
        self.entry_a_var.set("")
        self.entry_b_var.set("")

    # 日志统一走全局通道（log_summary / log_detail），不再自建 LogBox

    def _on_mode_change(self, event=None):
        """切换比较模式：只重建列集合与筛选项，并**重渲染已有结果**（不重跑）。

        与旧版语义一致：切模式本身不产生新的 I/O —— 要在新模式重跑请点「开始比较」。
        曾经这里在 event 非空且两个路径都填了时直接 _start_compare()，等于每切一次
        模式就把整棵目录树重扫一遍（大盘目录上非常昂贵），已去掉（B2）。

        注意：切换后**必须清掉旧结果**。新模式声明的列与行取值契约可能不同
        （例如文本模式的 text_diff 在统计模式的列里没有意义），保留旧数据会让
        「列头已换、行取值还是旧口径」的错位数据留在表格里（B6）。
        """
        mode = self.mode_var.get()
        spec = PluginManager.shared().compare_mode(mode) or {}
        filters = spec.get("filters") or DEFAULT_FILTERS_STATS
        names = [f[0] for f in filters]
        # 重设筛选项必须走 refresh_dropdown：直接 config(values=...) 会丢掉插件条目
        _allowed = refresh_dropdown(self.cb_filter, HOST_XML, AREA_FILTER, list(names))
        if self.filter_var.get() not in _allowed:
            # B3：旧版按模式给默认筛选（文本=「有差异」、统计=「不一致」），
            # 而不是回落到列表第 0 项「全部」——那会让切完模式立刻显示全部行。
            self.filter_var.set(names[0] if names else "全部")
        self.results = []
        # 列集合随模式变（插件贡献的新列在此出现）
        self._apply_columns()
        self._refresh_tree()

    def _start_compare(self):
        if self.task.running:
            return
        pa = self.entry_a_var.get().strip()
        pb = self.entry_b_var.get().strip()
        if not pa or not pb:
            messagebox.showwarning("路径缺失", "请先选择两个文件夹。")
            return
        if not Path(pa).is_dir():
            errbox("路径无效", f"文件夹 A 不存在:\n{pa}")
            return
        if not Path(pb).is_dir():
            errbox("路径无效", f"文件夹 B 不存在:\n{pb}")
            return

        self.tree.delete(*self.tree.get_children())
        self.results = []
        # B6：列集合在**开始比较时**也按当前模式重建一次，保证「列头 / 行取值 /
        # 详情 / 导出表头」四者同源（_active_mode 与 _columns_for_mode 都取自
        # mode_var）。清掉表格后列头与数据若不同步，用户会看到一列都读不懂的表。
        self._apply_columns()

        mode = self.mode_var.get()
        enc_a = self.enc_a_var.get()
        enc_b = self.enc_b_var.get()
        # 按钮禁用/恢复与状态由 TaskRunner 统一处理；异常交给 _on_error
        self.task.run(lambda: self._run_compare(pa, pb, mode, enc_a, enc_b),
                      status="正在扫描...", on_error=self._on_error)

    def _run_compare(self, pa: str, pb: str, mode: str, enc_a: str = "auto", enc_b: str = "auto"):
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
            # 比较函数取自模式注册表 —— 插件贡献的模式与内置模式走同一条路径，
            # 组件不做任何 `if mode == ...` 分支（能力 6 贡献点）。
            _spec = PluginManager.shared().compare_mode(mode) or {}
            _cmp = _spec.get("compare")
            _ctx = {"name_a": self.name_a, "name_b": self.name_b,
                    "enc_a": enc_a, "enc_b": enc_b, "mode": mode}
            if _cmp is None:
                raise RuntimeError(f"未注册的比较模式: {mode!r}")

            for i, rel in enumerate(common):
                r = _cmp(_ctx, files_a[rel], files_b[rel], rel)
                if not isinstance(r, dict):
                    # 注册表只校验 compare 可调用，没校验返回值形状。非 dict 结果
                    # 一旦进了 self.results，任何一次渲染都会 AttributeError，
                    # 因此这里当场归一化 + 留痕，而不是等界面崩。
                    log_summary(f"比较模式 {mode!r} 对 {rel} 返回了非字典结果"
                                f"（{type(r).__name__}），已按“无结果”处理", "warn")
                    r = {"rel": rel, "consistent": False, "mode": mode,
                         "_invalid_result": type(r).__name__}
                else:
                    r.setdefault("mode", mode)
                results.append(r)
                # 逐文件结果写「详细日志」（只落盘）：GUI 只显示进度与最终统计。
                # D8：原先只写 一致/仅A/仅B 三个计数，文本模式下真正的差异内容
                # （text_diff 命中数与两侧文本）完全不在日志里，出问题无法从
                # runtime 日志复现结论；这里补齐差异总数与逐条明细。
                log_detail(f"  [比较] {rel} | mode={mode} | "
                           f"一致={r.get('consistent')} | "
                           f"编码 A={r.get('encoding_a')} B={r.get('encoding_b')} | "
                           f"行数 A={r.get('lines_a')} B={r.get('lines_b')} | "
                           f"ID 数 A={r.get('ids_a')} B={r.get('ids_b')} | "
                           f"仅A={len(r.get('only_a') or [])} "
                           f"仅B={len(r.get('only_b') or [])} "
                           f"次数不同={len(r.get('count_diff') or [])} "
                           f"文本不同={len(r.get('text_diff') or [])} "
                           f"差异总数={self._diff_total(r)}")
                if r.get("only_side"):
                    log_detail(f"    [仅一侧] {rel} 只存在于 {self.name_a if r['only_side'] == 'a' else self.name_b}")
                for iid, ca, cb in (r.get("count_diff") or []):
                    log_detail(f'    [次数] id="{iid}" A={ca} / B={cb}')
                for iid, ta, tb in (r.get("text_diff") or []):
                    log_detail(f'    [文本] id="{iid}"')
                    log_detail(f'      A={ta!r}')
                    log_detail(f'      B={tb!r}')
                if (i + 1) % 20 == 0 or i == total - 1:
                    self._ui(lambda c=i+1, t=total: self.lbl_status.config(
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
            self._ui(self._on_done)
        except Exception as e:
            msg = str(e)
            self._ui(lambda: self._on_error(msg))

    def _on_done(self):
        # 忙碌标志与按钮恢复由 TaskRunner 负责；这里只做业务结果回显
        cons = sum(1 for r in self.results if r.get("consistent"))
        incon = sum(1 for r in self.results
                    if not r.get("consistent") and "only_side" not in r)
        only_a = sum(1 for r in self.results if r.get("only_side") == "a")
        only_b = sum(1 for r in self.results if r.get("only_side") == "b")

        self.lbl_stat.config(
            text=f"一致 {cons}  |  不一致 {incon}  |  仅 {self.name_a} {only_a}  |  仅 {self.name_b} {only_b}")
        log_summary(f"对比完成: 一致 {cons} | 不一致 {incon} | 仅 {self.name_a} {only_a} | 仅 {self.name_b} {only_b}", "ok")
        self._refresh_tree()
        # C3：结果产生后重算插件动作区 —— context 是 lambda（读 self.results），
        # 不 refresh 的话{"has_results": True} 类条件永远不会生效。
        try:
            self._slot_bar.refresh()
        except Exception:
            pass
        self.task.set_status("比较完成", "ok")

    def _diff_total(self, r) -> int:
        """一条结果的差异条目总数（缺键视为 0，绝不抛异常，供日志/列渲染共用）。"""
        if not isinstance(r, dict):
            return 0
        return sum(len(r.get(k) or []) for k in ("only_a", "only_b", "count_diff", "text_diff"))
    def _on_error(self, e):
        msg = str(e)
        self.task.set_status("出错", "err")
        log_summary(f"比较出错: {msg}", "err")
        errbox("比较出错", msg)

    def _active_mode(self):
        """当前生效的模式记录 = 模式下拉的当前取值（mode_var）。

        D5：这里的注释原先声称"以结果数据为准"，但对内置模式永不成立——
        内置结果里的 mode 是 "stats"/"text"（见 compare_one / compare_text_content），
        而注册名是「行数/ID 统计」「ID 文本对比」，modes.get(r["mode"]) 永远取不到，
        实际总是回落到 self.mode_var.get()。注册名与内部键共用一套命名只会制造
        这种"注释说的和代码做的不一样"，因此明确以 mode_var 为准：
        用户在哪个模式下看，就用哪个模式声明渲染，列头与筛选语义因此始终自洽。
        （插件结果里的 mode 写的是注册显示名，与 mode_var 一致；导出表头用它。）
        """
        modes = PluginManager.shared().compare_modes_for()
        return modes.get(self.mode_var.get()) or next(iter(modes.values()), None)

    def _row_kind(self, r, mode):
        """行分类：由模式的 row_builder 决定；未提供时按 consistent/only_side 推断。

        row_builder 抛异常时不再静默（M1）：回落默认分类，但留一条 warning，
        否则插件的结果会被按错误语义过滤/着色而用户毫无察觉。
        """
        if not isinstance(r, dict):
            return "diff", set()
        rb = (mode or {}).get("row_builder")
        if rb is not None:
            try:
                kind, types = rb(r)
                return kind, types
            except Exception as e:
                log_summary(f"行分类失败（回落默认分类）: "
                            f"{r.get('rel', '?') if isinstance(r, dict) else '?'} -> "
                            f"{type(e).__name__}: {e}", "warn")
        if "only_side" in r:
            return "only_" + r["only_side"], set()
        if r.get("consistent"):
            return "same", set()
        return "diff", set()

    @staticmethod
    def _cell_text(value, width=0):
        """单元格值 → 文本：None/缺失给中性 "-"，长文本（详情列）折叠为单行。"""
        if value is None:
            return "-"
        text = str(value)
        if width and len(text) > width:
            return text[:width] + "…"
        return text

    def _row_values(self, r, mode, kind):
        """按模式声明的列产出 Treeview 值。

        这里**没有任何 `if mode == ...` 分支**：内置列与插件列走同一段通用渲染，
        取值一律 .get()，缺键给中性显示。因此插件只声明了自己列的 result 也能
        安全渲染，不会 KeyError（C2）。
        """
        # 列来源必须是**与表头同一份**映射结果（_columns_for_mode）：它会把
        # lines_a/lines_b 合成 "lines"、ids_a/ids_b 合成 "ids"，也负责去重。
        # 若直接用 mode["columns"] 的原始元素（元组）做 key，每个键都会落到兜底
        # 分支，整行变成一片 "-"（实测踩过）。
        if not isinstance(r, dict):
            # 结果不是字典（插件 compare 违约返回）时给它一行能看懂的占位，
            # 而不是在 Tk 事件回调里 AttributeError（C2）。
            r = {"rel": str(r), "consistent": False}
        cols = [c[0] for c in self._columns_for_mode(mode)]
        label = self.name_a if kind == "only_a" else self.name_b
        only_side = kind.startswith("only_")
        out = []
        for key in cols:
            if key == "rel":
                out.append(r.get("rel", ""))
            elif key == "status":
                out.append("仅%s" % label if only_side
                           else ("✓" if kind == "same" else "✗"))
            elif key in ("lines", "lines_a", "lines_b"):
                # B4：仅单侧存在的文件两侧都没有行数，旧版写 "-"，不再伪装成 0
                out.append("-" if only_side else "A:%s / B:%s" % (
                    self._cell_text(r.get("lines_a")), self._cell_text(r.get("lines_b"))))
            elif key in ("ids", "ids_a", "ids_b"):
                out.append("-" if only_side else "A:%s / B:%s" % (
                    self._cell_text(r.get("ids_a")), self._cell_text(r.get("ids_b"))))
            elif key == "diff_count":
                out.append("-" if only_side else str(self._diff_total(r)))
            elif key == "detail":
                # A1：保留列键 detail —— 模式声明的 detail_builder 的**单行缩略版**
                out.append(self._detail_inline(r, mode, kind))
            elif key in ("encoding_a", "encoding_b"):
                out.append(self._cell_text(r.get(key)))
            elif key in r:
                out.append(self._cell_text(r.get(key)))
            else:
                # 插件声明了列但这条结果没有该键（例如模式复用同一批结果）：
                # 中性显示，不伪装成 0，也不抛 KeyError（C2）。
                out.append("-")
        return tuple(out)

    def _detail_inline(self, r, mode, kind):
        """detail 列的单行摘要（**刻意不走 detail_builder**）。

        为什么不能复用完整明细：`detail_builder` 是给"选中一行的完整明细"用的，
        它会把两侧的 id 逐个列出来。而表格是**每行都要算一次**这个值 ——
        实测 1 万行时它让填充从 89ms 涨到 327ms（每行 ~0.02ms × 1 万）。
        这里只按**计数**拼一句摘要，代价与差异条目数无关。
        """
        if not isinstance(r, dict):
            return ""
        if kind == "same":
            return "无差异"
        na, nb = _side_labels(self.name_a, self.name_b)
        side = r.get("only_side")
        if side:
            return f"文件仅在一侧存在（仅 {na if side == 'a' else nb}）"
        parts = []
        for key, label in (("only_a", f"仅 {na} 有"), ("only_b", f"仅 {nb} 有"),
                           ("count_diff", "次数不同"), ("text_diff", "文本不同")):
            n = len(r.get(key) or [])
            if n:
                parts.append(f"{label} {n}")
        if not parts:
            return "无差异" if r.get("consistent") else "有差异"
        return "；".join(parts)

    def _columns_for_mode(self, mode):
        """模式声明的列 → Treeview 列 id 列表。

        映射规则：`lines_a`/`lines_b` 合并为一个 "lines" 列（值为 "A:x / B:y"），
        `ids_a`/`ids_b` 合并为 "ids"；`detail` 是**保留列键**，统一渲染为单行差异
        摘要（A1，取值见 _detail_inline）；其余 key 直接作为列 id（插件新增的列
        因此会自动出现，无需改组件）。
        """
        out = []
        seen = set()

        def _push(cid, heading, width=None):
            if cid in seen:
                return
            seen.add(cid)
            out.append((cid, heading, width))

        for col in (mode or {}).get("columns") or COLUMNS_STATS:
            key, heading = col[0], col[1]
            width = col[2] if len(col) > 2 else None
            if key in ("lines_a", "lines_b"):
                _push("lines", "行数 A / B", width or 120)
            elif key in ("ids_a", "ids_b"):
                _push("ids", "ID 数 A / B", width or 120)
            else:
                _push(key, heading, width)
        return out

    def _apply_columns(self):
        """按当前模式重建 Treeview 的列集合。

        模式切换时列的构成可能不同，而 ttk.Treeview 的 columns 不可变，
        因此这里销毁重建。**重建后必须重新挂载**（grid / 滚动钩子 / 事件绑定 /
        tag 配色）——这些原先只在 _build_ui 里做一次，于是切一次模式表格就消失、
        滚动条失效、行不着色、双击与选中回调全废（C1），现在统一交给 _attach_tree。
        """
        cols = self._columns_for_mode(self._active_mode())
        if getattr(self, "tree", None) is not None:
            try:
                self.tree.destroy()
            except Exception:
                pass
        self.tree = ttk.Treeview(self._tree_frame, columns=[c[0] for c in cols],
                                 show="headings", selectmode="browse")
        for cid, heading, width in cols:
            self.tree.heading(cid, text=heading)
            if cid in ("status",):
                self.tree.column(cid, width=width or 70, minwidth=50, anchor="center")
            elif cid == "rel":
                self.tree.column(cid, width=width or 280, minwidth=150)
            elif cid == "detail":
                # 详情列是长文本，左对齐、放宽（与旧版 400/200 对齐）
                self.tree.column(cid, width=width or 400, minwidth=200, anchor="w")
            else:
                self.tree.column(cid, width=width or 110, minwidth=80, anchor="center")
        self._attach_tree(self.tree)
        return cols

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._hide_detail()
        mode, visible = self._visible_rows()
        for i, r, kind in visible:
            tag = {"same": "ok", "diff": "diff"}.get(kind, "only")
            self.tree.insert("", "end", iid=str(i),
                             values=self._row_values(r, mode, kind), tags=(tag,))

    def _selected_result(self):
        """选中行 → (原始下标, result) 或 None；行号非法时返回 None 而不是抛错。"""
        try:
            sel = self.tree.selection()
        except Exception:
            return None
        if not sel:
            return None
        try:
            idx = int(sel[0])
        except (TypeError, ValueError):
            return None
        if idx < 0 or idx >= len(self.results):
            return None
        return idx, self.results[idx]

    def _show_detail_popup_for(self, r, mode, kind):
        """双击 → 弹出该行的完整明细（任何模式/任何结果形状都不抛异常）。"""
        rel = r.get("rel", "") if isinstance(r, dict) else str(r)
        self._show_detail_popup(rel, self._full_detail(r, mode, kind) or "无差异",
                                self._detail_ids(r))

    def _on_double_click(self, event):
        picked = self._selected_result()
        if picked is None:
            return
        _idx, r = picked
        mode = self._active_mode()
        kind, _types = self._row_kind(r, mode)
        self._show_detail_popup_for(r, mode, kind)

    def _on_row_select(self, event):
        """选中行 → 在详情栏显示该行明细。

        与旧版一致：面板常驻、一致行与仅单侧行也显示内容（B5）。
        明细一律经模式声明的 detail_builder 渲染（内置两种模式各自提供），
        插件没提供 detail_builder 时退化为通用摘要，绝不 KeyError（C2）。
        """
        if not self._detail_text:
            self._hide_detail()
            return
        picked = self._selected_result()
        if picked is None:
            self._hide_detail()
            return
        _idx, r = picked
        mode = self._active_mode()
        kind, _types = self._row_kind(r, mode)

        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", "end")

        # 第一行: 文件 + 状态（统计口径中性，不再硬取 r["ids_a"]）
        rel = r.get("rel", "") if isinstance(r, dict) else str(r)
        if not isinstance(r, dict):
            r = {"rel": rel, "consistent": False}
        if kind == "same":
            head = f"[ {rel} ] ✓ {self._row_status_text(r, kind)}"
        elif kind.startswith("only_"):
            head = f"[ {rel} ] {self._row_status_text(r, kind)}"
        else:
            head = (f"[ {rel} ] ✗ {self._row_status_text(r, kind)}"
                    f"  ID 数: A={self._cell_text(r.get('ids_a'))} "
                    f"B={self._cell_text(r.get('ids_b'))}")
        body = self._full_detail(r, mode, kind)
        self._detail_text.insert("1.0", head + ("\n" + body if body else "\n"))

        self._detail_text.config(state="disabled")
        # 下半部分：逐条 id + 各自的「复制id」按钮
        self._render_id_list(r)
        self._show_detail()

    def _show_detail(self):
        """显示详情栏 (加入筛选框内部 paned, 与表格之间可拖拽分隔)."""
        try:
            if str(self.detail_frame) not in self._inner.panes():
                self._inner.add(self.detail_frame, weight=2)
        except Exception:
            pass

    def _hide_detail(self):
        """隐藏详情栏."""
        try:
            if str(self.detail_frame) in self._inner.panes():
                self._inner.forget(self.detail_frame)
        except Exception:
            pass


    def _active_filter_spec(self, mode, filt):
        """当前筛选声明 (标签, row_kinds, differ_types)。

        D6：筛选下拉里可能混入**插件直接注册的下拉条目**（register_option_entry），
        它们不在模式声明的 filters 里。原先这种情况静默回落到「全部」——于是
        下拉显示「P-筛选」而表格按「全部」过滤，界面与行为不一致。
        现在回落仍保持可用（否则选了插件条目就什么都看不到），但会写一条
        warning 说明该值没有过滤语义，不再是静默行为。
        """
        specs = (mode or {}).get("filters") or DEFAULT_FILTERS_STATS
        spec = next((s for s in specs if s[0] == filt), None)
        if spec is not None:
            return spec
        fallback = specs[0] if specs else None
        if fallback is not None and filt:
            log_summary(f"筛选项 {filt!r} 不是模式 "
                        f"{(mode or {}).get('name') or ''} 声明的过滤条件，"
                        f"已按 {fallback[0]!r} 处理（无过滤语义）", "warn")
        return fallback

    def _visible_rows(self):
        """按当前模式与筛选声明挑出可见行 → [(原始下标, result, row_kind), ...]。

        `_refresh_tree` 与 `_export` **共用这一份**判定，避免历史上"表格与导出
        各写一套筛选、结果会漂移"的问题。下标显式携带，不用 list.index（同值字典
        会取错行）。
        """
        mode = self._active_mode()
        spec = self._active_filter_spec(mode, self.filter_var.get())
        out = []
        for i, r in enumerate(self.results):
            kind, types = self._row_kind(r, mode)
            if spec is not None and not row_matches_filter(kind, types, spec):
                continue
            out.append((i, r, kind))
        return mode, out

    def _row_status_text(self, r, kind):
        if kind == "only_a":
            return "仅%s" % self.name_a
        if kind == "only_b":
            return "仅%s" % self.name_b
        return "一致" if kind == "same" else "不一致"

    def _detail_ids(self, r):
        """明细里出现的 id → [(来源标签, id 文本), ...]（去重、保序）。

        汇总 only_a / only_b / text_diff / count_diff 四种差异来源，口径与旧版
        「复制全部 id」一致；区别只是现在**逐条**展示并可逐条复制。
        缺键/结构异常一律跳过，绝不抛（插件结果可能只有自己声明的键）。
        """
        if not isinstance(r, dict):
            return []
        na, nb = _side_labels(self.name_a, self.name_b)
        out, seen = [], set()

        def _add(cat, val):
            s = str(val)
            if not s or s in seen:
                return
            seen.add(s)
            out.append((cat, s))

        for key, cat in (("only_a", f"仅 {na}"), ("only_b", f"仅 {nb}")):
            for x in (r.get(key) or []):
                _add(cat, x)
        for key, cat in (("text_diff", "文本不同"), ("count_diff", "次数不同")):
            for item in (r.get(key) or []):
                try:
                    _add(cat, item[0])
                except (TypeError, IndexError, KeyError):
                    continue
        return out

    def _copy_one_id(self, id_text):
        """把单个 id 复制到剪贴板（明细里每条的「复制id」按钮）。"""
        text = str(id_text)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception as e:
            log_summary(f"复制 id 失败: {type(e).__name__}: {e}", "err")
            errbox("复制失败", f"无法写入剪贴板:\n{e}")
            return
        log_summary(f"已复制 id: {text}", "ok")

    def _build_id_list(self, parent, ids, height=140):
        """可滚动的 id 列表：每条 id 后面一个「复制id」按钮。

        两处性能设计（都是实测逼出来的）：
        1. **虚拟化**：只为视口内的行创建控件。给每条 id 建 4 个控件时，
           「换选一行」在 200 条差异下要 **1478ms**（`<<TreeviewSelect>>` 每次
           变化都重建整份列表）；虚拟化后常驻只有视口那几行。
        2. **基础设施只建一次**：Canvas/滚动条/空提示按容器缓存，换行时只更新
           数据、滚动区间与可见行。原先每次换选都 destroy 整棵子树再重建，
           容器尺寸一变就触发 SplitPane 重排 + Treeview 整块重绘（换选一次 ~71ms）。
        """
        import tkinter.font as _tkf
        ids = list(ids)
        # 换容器（内嵌面板 ↔ 弹窗）时丢弃旧基础设施；同一容器则复用
        if getattr(self, "_id_parent", None) is not parent:
            self._id_parent = parent
            self._id_canvas = None
            self._id_box = None
            self._id_empty = None
            self._id_rows = {}
            for child in parent.winfo_children():
                child.destroy()

        if self._id_canvas is None:
            self._id_row_h = max(px(22),
                                 _tkf.Font(font=T["font"]).metrics("linespace") + px(4))
            self._id_rows = {}
            self._id_box = tk.Frame(parent)
            cv = tk.Canvas(self._id_box, highlightthickness=0, bg=color("surface"),
                           height=px(height))
            sb = AutoScrollbar(self._id_box, orient="vertical", command=cv.yview)
            # 滚动条一动就重画可见区间（拖动滑块不会触发 <Configure>）
            cv.configure(yscrollcommand=lambda *a: (sb.set(*a), self._id_paint()))
            sb.pack(side="right", fill="y")
            cv.pack(side="left", fill="both", expand=True)
            self._id_canvas = cv
            self._id_empty = tool_label(parent, "（该文件没有 id 差异）",
                                        font_role="font", fg_role="text_dim")
            cv.bind("<Configure>", lambda e: self._id_paint())
            # 滚轮只在指针进入该画布时接管，避免抢走表格的滚轮
            cv.bind("<MouseWheel>", lambda e: (cv.yview_scroll(
                -1 if e.delta > 0 else 1, "units"), self._id_paint(), "break")[-1])

        cv = self._id_canvas
        self._ids = ids
        if not ids:
            self._id_box.pack_forget()
            self._id_empty.pack(anchor="w", padx=4, pady=2)
            for idx in list(self._id_rows):
                win, frame = self._id_rows.pop(idx)
                try:
                    cv.delete(win); frame.destroy()
                except Exception:
                    pass
            return None
        self._id_empty.pack_forget()
        self._id_box.pack(fill="both", expand=True)
        cv.configure(scrollregion=(0, 0, 0, self._id_row_h * len(ids)))
        cv.yview_moveto(0)
        self._id_paint()
        return self._id_box

    def _id_paint(self):
        """只保留视口内的 id 行（虚拟化核心）。"""
        cv = getattr(self, "_id_canvas", None)
        if cv is None:
            return
        h = self._id_row_h
        total = len(self._ids)
        try:
            top = cv.canvasy(0)
            view_h = cv.winfo_height() or px(140)
            width = cv.winfo_width() or px(300)
        except Exception:
            return
        first = max(0, int(top // h))
        last = min(total, int((top + view_h) // h) + 2)

        for idx in [i for i in self._id_rows if i < first or i >= last]:
            win, frame = self._id_rows.pop(idx)
            try:
                cv.delete(win)
                frame.destroy()
            except Exception:
                pass

        for idx in range(first, last):
            cat, one = self._ids[idx]
            if idx not in self._id_rows:
                frame = tk.Frame(cv, bg=color("surface"))
                tool_label(frame, text=f"[{cat}]", font_role="font",
                           fg_role="text_dim").pack(side="left", padx=(0, 4))
                tool_label(frame, text=one, font_role="font_mono").pack(side="left")
                tool_button(frame, "复制id", width=8,
                            command=lambda s=one: self._copy_one_id(s)).pack(side="right")
                win = cv.create_window(0, idx * h, window=frame, anchor="nw")
                self._id_rows[idx] = (win, frame)
            else:
                win = self._id_rows[idx][0]
            try:
                cv.coords(win, 0, idx * h)
                cv.itemconfigure(win, width=width)
            except Exception:
                pass

    def _render_id_list(self, r):
        """刷新内嵌详情栏下半部分的逐条 id 列表。"""
        if not getattr(self, "_id_frame", None):
            return
        self._build_id_list(self._id_frame, self._detail_ids(r))

    def _full_detail(self, r, mode, kind):
        """完整明细文本：优先用模式声明的 detail_builder（D1 的契约所在）。

        插件没提供 detail_builder、或它自己抛异常时，退化为通用摘要而不是空串——
        这样"只声明了自己列的插件结果"被选中/双击也有内容可看（C2）。
        """
        if not isinstance(r, dict):
            # 插件 compare 没返回 dict 时（注册表允许，只是组件不认）不能让
            # 选中/双击在 Tk 事件回调里抛异常，否则界面直接失去响应。
            return "(该模式的结果结构不是字典，无法渲染详情)"
        na, nb = self.name_a, self.name_b
        builder = (mode or {}).get("detail_builder")
        if builder is not None:
            try:
                detail = builder(r, na, nb)
            except Exception as e:
                log_summary(f"详情渲染失败（回落通用摘要）: "
                            f"{r.get('rel', '?') if isinstance(r, dict) else '?'} -> "
                            f"{type(e).__name__}: {e}", "warn")
                detail = None
            if detail:
                return str(detail)
        return self._generic_detail(r, na, nb)

    def _generic_detail(self, r, na, nb):
        """通用摘要：不认识插件模式时也能给出可读结论，缺键不抛异常。"""
        na, nb = _side_labels(na, nb)
        side = r.get("only_side")
        if side:
            return f"文件仅在一侧存在: 仅 {na if side == 'a' else nb} 有 {r.get('rel', '')}"
        parts = [f"状态: {'一致' if r.get('consistent') else '不一致'}"]
        for label, key in (("行数", "lines_a"), ("ID 数", "ids_a")):
            if key in r:
                other = key.replace("_a", "_b")
                parts.append(f"{label}: {na}={self._cell_text(r.get(key))} / "
                             f"{nb}={self._cell_text(r.get(other))}")
        total = self._diff_total(r)
        parts.append(f"差异条目: {total}")
        if not any(r.get(k) for k in ("only_a", "only_b", "count_diff", "text_diff")):
            declared = [k for k in r
                        if k not in ("rel", "mode", "consistent", "only_side",
                                     "encoding_a", "encoding_b")
                        and not isinstance(r.get(k), (dict, list))]
            for k in declared:
                parts.append(f"{k}={self._cell_text(r.get(k))}")
        return "\n".join(parts)

    def _encoding_line(self, visible):
        """实际使用的编码回显（D3）：结果算出来却无人展示，用户无从判断。

        按 (A, B) 去重；只有一种组合时是精确值，多种时列出去重后的组合列表。
        """
        pairs = []
        for _i, r, _kind in visible:
            if not isinstance(r, dict):
                continue
            a, b = r.get("encoding_a"), r.get("encoding_b")
            if not a and not b:
                continue
            pair = (a or "-", b or "-")
            if pair not in pairs:
                pairs.append(pair)
        if not pairs:
            return ""
        return " ; ".join(f"A={a} / B={b}" for a, b in pairs)

    def _export_row(self, r, mode, kind):
        """CSV 一行：只由模式声明的列产出行值（B7）。

        原先这里无条件 `cells[1] = ...` 覆盖第 2 列，假定 status 一定在第 1 位——
        插件把别的列放在第 1 位时就会替换错列。现在 status 由 _row_values 按
        列 key 自行产出，导出与表格**逐列同源**；only_* 行的「文件仅在一侧存在」
        说明由 _row_values 的 detail 列（B4）与通用明细负责，不再丢失。
        """
        return tuple(self._row_values(r, mode, kind))

    def _export(self):
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
        mode, visible = self._visible_rows()
        na, nb = _side_labels(self.name_a, self.name_b)
        rows = [self._export_row(r, mode, kind) for _i, r, kind in visible]

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

        w.writerow(["XML校对报告"])
        w.writerow([f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
        w.writerow([f"比较模式: {mode.get('name') if mode else ''}"])
        w.writerow([f"文件夹 A: {self.entry_a_var.get().strip()}"])
        w.writerow([f"文件夹 B: {self.entry_b_var.get().strip()}"])
        w.writerow([f"编码（auto=自动判定）: A={self.enc_a_var.get()} / B={self.enc_b_var.get()}"])
        enc_used = self._encoding_line(visible)
        if enc_used:
            w.writerow([f"实际使用编码: {enc_used}"])
        w.writerow([f"筛选条件: {filt}"])
        w.writerow([f"一致: {cons} | 不一致: {incon} | 仅 {na}: {oa} | 仅 {nb}: {ob}"])
        w.writerow([])
        # 表头直接来自模式声明的列（插件新增列会自动出现在导出里）；detail 是
        # 声明里的保留列键，所以不再额外追加一列"差异详情"，避免重复列。
        w.writerow([c[1] for c in ((mode or {}).get("columns") or COLUMNS_STATS)])

        for row in rows:
            w.writerow(row)

        # newline="" 是 csv 模块的硬性要求：不写的话 \r\n 会被文本层再翻译成
        # \r\r\n，Excel 打开会看到大量空行（实测导出文件里行行之间都有空行）。
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(buf.getvalue())
        log_summary(f"已导出 {len(rows)} 行到 {path}", "ok")
        messagebox.showinfo("导出完成", f"已导出 {len(rows)} 行到:\n{path}")

    def _show_detail_popup(self, filename: str, detail: str, ids=None):
        win = dialog_window(self.root, f"差异详情 — {filename}",
                            size="650x480", minsize=(420, 280))

        # 先摆底部（pack 的 side="bottom" 先入者最靠底），再用文本填满剩余空间
        tool_button(win, "关闭", command=win.destroy, width=10).pack(
            side="bottom", pady=(0, 8))
        if ids:
            lf = ttk.LabelFrame(win, text=" 差异 id（逐条复制）", padding=4)
            lf.pack(side="bottom", fill="x", padx=8, pady=(4, 4))
            self._build_id_list(lf, ids, height=150)

        text = LogBox(win, wrap="word", scrollbar=False,
                      tags=[("diff", "red"), ("ok", "green"),
                            ("only", "orange")])
        text.pack(fill="both", expand=True)
        text.insert("1.0", detail)
        text.config(state="disabled")
