# -*- coding: utf-8 -*-
"""编码转换 App (ConvertApp)."""
from apps._bootstrap import (
    os, re, threading, shutil, datetime, tk, ttk, filedialog, messagebox
)

from toolkit import (
    dir_row, tool_header, SplitPane, _make_pump, sniff_encoding, is_multibyte_utf8,
    DND_FILES, errbox, log_summary, log_detail,
    plugin_slot_bar, plugin_entries, HOST_CONVERT, AREA_SOURCE_ENC,
    open_in_explorer, BACKUP_DIRNAME, BACKUP_SUFFIX, ENCODING_CHOICES,
    color, tool_label, ScrollPanel,
)

# ═══ 自动检测：判定链只有一份实现（toolkit_textio.sniff_encoding） ═══
# 顺序（**多/单字节检查优先级最高**）：BOM → 多字节检查 → 手动指定
#   → XML 声明（须被字节证实）→ chardet 统计探测 → windows-1251。
# 本 App **不再自带任何收尾规则**：低置信度的单字节结论一律不采信（单字节编码对
# 任意字节都"解成功"，没有信息量），多字节家族则按置信度采信（避免漏判 GBK/Big5）。
# 策略只在一处，界面文案与日志与之一致即可。
# 本正则用于两处：日志里标出"这一步是**采信了声明**"、以及判定前挑出声明内容。
_XML_DECL_ENC_RE = re.compile(
    rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', re.I | re.S)

# 进度文案：分母一律是**候选文件数**（跳过与失败同样计入"已处理"），所以不能说成
# "N 个成功"，三类任务也不该共用一个含糊的 "N / M"。
_PROGRESS_TEXTS = {
    "convert": "已处理 {done} / {total} 个候选文件",
    "restore": "已恢复 {done} / {total} 个备份文件",
    "clear": "已清理 {done} / {total} 个备份文件",
}


def _has_xml_decl_encoding(raw):
    """字节里是否存在带 encoding 属性的 XML 声明（仅用于日志措辞）。"""
    return bool(_XML_DECL_ENC_RE.search(raw[:500]))


class ConvertApp(ttk.Frame):
    """编码转换。

    统一契约：只接收宿主 Tab（parent）——不自建根窗口、不应用主题、不自建日志面板；
    日志走全局两级通道（log_summary / log_detail）。
    本类是 ttk.Frame 子类：把自己铺满宿主 Tab，控件都建在 self 上。
    """

    PANEL_PAD = 14          # 与 _build_ui 里的 PAD 同值（页面边距统一 14）

    def _panel(self, parent, title):
        """统一滚动面板的薄封装：建面板、按本页边距摆好，返回"往里建控件"的容器。

        六个页面都走这一条路（`ScrollPanel`），于是"滚动条什么时候出现"只有一个实现、
        一条规则：**面板里有东西显示不完全**（控件 + 内部内容）才出现（用户口径 2026-09-13）。
        """
        p = ScrollPanel(parent, title)
        p.pack(fill="x", padx=self.PANEL_PAD, pady=6)
        return p.body

    def __init__(self, parent):
        self.root = parent
        super().__init__(parent)
        self.pack(fill="both", expand=True)  # 铺满宿主 Tab

        # 原有变量
        self.source_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.file_exts = tk.StringVar(value=".xml")
        self.target_enc = tk.StringVar(value="utf-8")
        self.source_enc = tk.StringVar(value="auto")
        self.recursive = tk.BooleanVar(value=True)
        self.backup_files = tk.BooleanVar(value=True)

        # 新增变量
        self.exclude_pattern = tk.StringVar()

        # 进度控制（转换任务的计数；恢复/清空各自持有本地计数，不共用这两个）
        self.total = 0
        self.current = 0
        self.paused = False
        self.cancelled = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        # 线程安全 UI 泵: 统一用 toolkit 的 _make_pump（与其余五个工具一致）
        self._ui = _make_pump(self.root)

        # ═══ 任务级运行状态（转换 / 恢复备份 / 清空备份 三者互斥） ═══
        # running 只在主线程同步置位：按钮禁用是投递到主线程的（最多 30ms 才生效），
        # 单靠按钮状态挡不住连点，标志位才是真正的重入闸门。
        self.running = False
        self._busy_name = ""
        # 参数快照按线程存放：工作线程只读自己那份，绝不读运行期会被别的任务
        # 用 _ensure_snap(force=True) 改写的 self._snap。
        self._task_local = threading.local()
        self._stats_snap = None      # 产生 convert_stats 的那次任务的参数快照（供导出统计）

        # 统计信息
        self.convert_stats = {
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'start_time': None,
            'end_time': None
        }

        # 标记当前是文件还是文件夹模式
        self.is_single_file = False

        self.init_ui()
        # trace 必须在 init_ui 之后绑定：两个回调都会访问 init_ui 里才创建的控件
        # （self.recursive_check / self.out_entry 等）。提前绑定一旦被 set() 触发，
        # 异常会被静默吞掉，表现为"选项改了但界面没反应"。
        self.output_dir.trace_add("write", self.on_output_dir_change)
        self.recursive.trace_add("write", self.on_recursive_change)

    def init_ui(self):
        """界面 (统一组件: dir_row / tool_header / color 模板)."""
        PAD = 14
        # ═══ 标题 ═══
        tool_header(self, "编码转换工具")
        # 插件动作区（toolbar 槽；无插件注册时不创建任何控件）
        # context 传**可调用对象**：每次重算都重新求值，when={"is_single_file": True}
        # 之类的条件才能随"选/拖入单个文件"而出现——传构造时的 dict 会把 when
        # 冻结成恒假（这是本文件此前的真实缺陷）。状态变化处调用 _refresh_slot()。
        self._slot_bar = plugin_slot_bar(self, HOST_CONVERT, app=self,
                                         context=self._slot_context)
        # ═══ 可调分区: 上部设置区 / 下部进度区 (分隔条拖拽)；日志面板由 Hub 统一提供 ═══
        self._paned = SplitPane(self, orient="vertical")
        self._paned.pack(fill="both", expand=True, padx=PAD, pady=(2, 8))
        upper = ttk.Frame(self._paned)
        lower = ttk.Frame(self._paned)
        self._paned.add(upper, weight=3)
        self._paned.add(lower, weight=1)


        # ═══ 源目录 ═══
        # 四个面板统一走 `ScrollPanel`（用户口径 2026-09-13："有东西显示不完全就该出滚动条"、
        # "这种控件应该统一写统一调用"）：面板内部自带横/纵滚动条（自动隐藏）。
        # 用法上只改一行：面板对象照旧，但内容建在它的 `.body` 里。
        source_frame = self._panel(upper, "源文件夹 / 单个文件")
        _, self.source_entry = dir_row(source_frame, "源", self.source_dir,
                                       browse=self.select_source,
                                       add=("清除", self.clear_source))
        # 模式指示：选/拖入单个文件后必须有可见反馈（只禁用"递归"复选框时，
        # 用户看不出当前是文件夹还是单文件模式）。控件走公共 tool_label，
        # 颜色走 color("角色名")。
        self.mode_label = tool_label(source_frame, "当前模式：未选择",
                                     font_role="font", fg_role="text_dim")
        self.mode_label.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ 输出目录 ═══
        out_frame = self._panel(upper, "输出文件夹")
        _, self.out_entry = dir_row(out_frame, "输出", self.output_dir,
                                    browse=self.select_output,
                                    add=("清除", self.clear_output))

        # ═══ 转换设置 ═══
        set_frame = self._panel(upper, "转换设置")
        set_frame.columnconfigure(5, weight=1)
        # 行0: 源/目标编码
        ttk.Label(set_frame, text="源编码：").grid(row=0, column=0, padx=(10, 4), pady=8, sticky="e")
        self.source_enc_combo = ttk.Combobox(set_frame, textvariable=self.source_enc,
            values=list(ENCODING_CHOICES)
                   + plugin_entries(HOST_CONVERT, AREA_SOURCE_ENC),
            width=14, state="readonly")
        self.source_enc_combo.grid(row=0, column=1, padx=(0, 6), sticky="w")
        # 原先这里摊着整条判定链，属"给开发者看的实现说明"，用户不会读。
        # 每个文件的**定案步骤**都会逐行写进 runtime 日志（多字节/指定/声明/统计），
        # 要查时看日志即可；完整链条见 ARCHITECTURE.md §4.1。
        # 界面上只留一句结论性建议。
        ttk.Label(set_frame, text="⚠ 建议手动指定",
                  style="Dim.TLabel").grid(row=0, column=2, padx=(0, 14), sticky="w")
        ttk.Label(set_frame, text="目标编码：").grid(row=0, column=3, padx=(12, 4), pady=8, sticky="e")
        ttk.Combobox(set_frame, textvariable=self.target_enc,
            values=["utf-8", "gbk", "gb2312", "windows-1251", "ascii", "utf-16", "big5"],
            width=14).grid(row=0, column=4, padx=(0, 10), sticky="w")
        # 行1: 扩展名 + 选项
        ttk.Label(set_frame, text="扩展名：").grid(row=1, column=0, padx=(10, 4), pady=8, sticky="e")
        ttk.Entry(set_frame, textvariable=self.file_exts, width=18).grid(row=1, column=1, padx=(0, 6), sticky="w")
        self.recursive_check = tk.Checkbutton(set_frame, text="递归子目录", variable=self.recursive)
        self.recursive_check.grid(row=1, column=2, padx=8, sticky="w")
        self.backup_check = tk.Checkbutton(
            set_frame, text="备份到 源目录\\backup（仅原地转换时可用）",
            variable=self.backup_files)
        self.backup_check.grid(row=1, column=3, padx=8, sticky="w")
        # 行2: 排除模式
        ttk.Label(set_frame, text="排除模式：").grid(row=2, column=0, padx=(10, 4), pady=(0, 10), sticky="e")
        ttk.Entry(set_frame, textvariable=self.exclude_pattern, width=28).grid(row=2, column=1, columnspan=2, padx=(0, 6), sticky="w")
        ttk.Label(set_frame,
                  text="通配符用逗号分隔(如 *backup*,temp*)；匹配文件名与相对路径；留空=不排除",
                  style="Dim.TLabel").grid(row=2, column=3, columnspan=2, padx=8, sticky="w")

        # ═══ 操作按钮 ═══
        btn_frame = ttk.Frame(upper)
        btn_frame.pack(pady=(8, 2))
        self.start_btn = ttk.Button(btn_frame, text="开始转换", command=self.start_thread, width=14)
        self.start_btn.pack(side="left", padx=4)
        self.pause_btn = ttk.Button(btn_frame, text="暂停", command=self.toggle_pause, width=8, state="disabled")
        self.pause_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(btn_frame, text="取消", command=self.cancel_convert, width=8, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        # 恢复 / 清空 / 开始转换 三者互斥：任一大任务运行中，另外两个必须禁用
        self.restore_btn = ttk.Button(btn_frame, text="恢复备份",
                                      command=self.start_restore_thread, width=10)
        self.restore_btn.pack(side="left", padx=4)
        self.clear_btn = ttk.Button(btn_frame, text="清空备份",
                                    command=self.start_clear_backup_thread, width=10)
        self.clear_btn.pack(side="left", padx=4)
        ttk.Button(btn_frame, text="打开输出", command=self.open_out_dir, width=10).pack(side="left", padx=4)
        # 与 Hub 日志页的"导出"(导出日志)同名不同事，此处必须叫"导出统计"
        ttk.Button(btn_frame, text="导出统计", command=self.export_stats, width=8).pack(side="left", padx=4)

        # ═══ 转换进度 (在下区, 日志上方) ═══
        prog_frame = self._panel(lower, "转换进度")
        self.prog_var = tk.DoubleVar()
        self.prog_bar = ttk.Progressbar(prog_frame, variable=self.prog_var, maximum=100)
        self.prog_bar.pack(fill="x", padx=10, pady=(8, 2))
        self.prog_label = ttk.Label(
            prog_frame, text=_PROGRESS_TEXTS["convert"].format(done=0, total=0),
            style="Dim.TLabel")
        self.prog_label.pack(pady=(0, 6))

        # 日志面板由 Hub 统一提供，工具内不再自建

        # ═══ 拖拽 (dir_row 已注册, 绑定处理) ═══
        try:
            if hasattr(self.source_entry, "drop_target_register"):
                self.source_entry.drop_target_register(DND_FILES)
                self.source_entry.dnd_bind("<<Drop>>", self.on_drop_source)
                self.out_entry.drop_target_register(DND_FILES)
                self.out_entry.dnd_bind("<<Drop>>", self.on_drop_output)
        except Exception:
            pass

    # ====================== 任务快照 / 重入保护 / 插件槽 ======================
    def _slot_context(self):
        """插件 when 条件用的宿主状态；每次重算都重新求值（不能传构造时的快照）。"""
        return {"is_single_file": bool(self.is_single_file)}

    def _refresh_slot(self):
        """状态变化后重算 toolbar 槽位：带 when 的插件命令据此出现/消失。"""
        slot = getattr(self, "_slot_bar", None)
        if slot is not None:
            try:
                slot.refresh()
            except Exception:
                pass

    def _begin_task(self, name, already_started=False):
        """大任务入口的原子重入保护；返回本任务是否获得执行权。

        必须在**启动线程之前**在主线程调用：按钮禁用经 UI 泵投递（最多 30ms 后
        才生效），存在窗口期，连点两次会起两个线程交叉写同一批文件。
        """
        if already_started:
            return True
        if self.running:
            who = self._busy_name or "另一任务"
            log_summary(f"[拒绝] {name}：{who}正在运行", "warn")
            self._ui(messagebox.showwarning, "提示",
                     f"已有任务正在运行：{who}。\n"
                     f"请等它结束或先取消，再执行「{name}」。")
            return False
        self.running = True
        self._busy_name = name
        self._ui(self._set_busy_ui, True)
        return True

    def _end_task(self):
        """任务收尾：复位重入标志并恢复三个启动按钮。"""
        self.running = False
        self._busy_name = ""
        self._ui(self._set_busy_ui, False)

    def _set_busy_ui(self, busy):
        """忙碌时禁用"开始转换 / 恢复备份 / 清空备份"（主线程执行）。"""
        state = tk.DISABLED if busy else tk.NORMAL
        for btn in (getattr(self, "start_btn", None), getattr(self, "restore_btn", None),
                    getattr(self, "clear_btn", None)):
            if btn is None:
                continue
            try:
                btn.config(state=state)
            except Exception:
                pass

    def _start_worker(self, target, snap, name):
        """统一的线程启动：线程起不来必须复位忙碌标志，否则按钮永久卡死。"""
        try:
            threading.Thread(target=target, args=(snap, True), daemon=True).start()
        except Exception as e:
            log_summary(f"启动{name}线程失败：{str(e)}", "err")
            self._end_task()

    def _ensure_snap(self, force=False):
        """确保快照存在 (主线程直接调 get_files 等时刷新为最新值)，返回该快照。

        force=True: 无论当前线程与已有快照，一律重建（任务启动器用）。
        注意 self._snap 是**界面侧的最新值**，运行中的任务不得依赖它——
        任务用自己的那份快照（见 _task_local / _task_snap / _bind_task_snap）。
        """
        if force or threading.current_thread() is threading.main_thread() or not getattr(self, "_snap", None):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }
        return self._snap

    def _task_snap(self):
        """取**本任务**的参数快照。

        工作线程内由 run_convert / run_restore / run_clear_backup 绑定快照；
        主线程直调（脚本 / 探针 / 交互查询）时退回界面最新值。
        """
        snap = getattr(self._task_local, "snap", None)
        if snap is not None:
            return snap
        return self._ensure_snap()

    def _bind_task_snap(self, snap):
        """把本任务的快照绑到当前线程（任务结束时必须解绑，见 finally）。"""
        self._task_local.snap = snap
        return snap

    def _unbind_task_snap(self):
        self._task_local.snap = None

    @staticmethod
    def _source_root(snap):
        """快照里的源根目录：单文件模式取所在目录，否则取源目录本身。"""
        src = (snap.get('source_dir') or "").strip()
        if not src:
            return ""
        if snap.get('is_single_file'):
            return os.path.dirname(src)
        return src

    def _set_progress(self, done, total, kind="convert"):
        """更新进度条与文案（投递回主线程）。分母是候选文件数口径。"""
        self._ui(self.prog_var.set, (done / total) * 100 if total else 0)
        text = _PROGRESS_TEXTS.get(kind, _PROGRESS_TEXTS["convert"]).format(
            done=done, total=total)
        self._ui(self.prog_label.config, text=text)

    def _finish_dialog(self, what, ok, failed, total):
        """完成弹窗按**实际成功/失败数**给结论（失败只进日志而弹窗恒报"完成"是缺陷）。"""
        if failed:
            log_summary(f"{what}：成功 {ok} 个，失败 {failed} 个（候选 {total} 个）", "err")
            self._ui(errbox, f"{what}部分失败",
                     f"{what}结束，但有失败：\n"
                     f"成功 {ok} 个 | 失败 {failed} 个\n"
                     f"候选 {total} 个文件，失败明细见日志。")
        else:
            log_summary(f"{what}：成功 {ok} 个（候选 {total} 个）", "ok")
            self._ui(messagebox.showinfo, "完成",
                     f"{what}完成！\n成功 {ok} 个 / 共 {total} 个候选文件")

    def _pick_path(self, chooser, *args, **kw):
        """统一校验 filedialog 返回值：Tk 异常时可能返回元组/数字/空，直接使用会抛。

        只接受**非空字符串**；其余（取消、异常返回值）一律当作未选择，
        非文本结果额外留一条日志——绝不把非字符串喂给 os.path.join。
        """
        try:
            p = chooser(*args, **kw)
        except Exception as e:
            log_summary(f"文件对话框失败：{str(e)}", "err")
            return ""
        if isinstance(p, str):
            return p.strip()
        if p:
            log_summary(f"文件对话框返回了非文本结果({type(p).__name__})，已忽略", "warn")
        return ""

    # ====================== 更新模式 ======================
    def update_mode_label(self):
        """按当前模式同步：模式指示标签 / 递归复选框 / 插件槽 context。"""
        if self.is_single_file:
            # 单文件模式：禁用递归
            self.recursive.set(False)
            self.recursive_check.config(state=tk.DISABLED)
            name = os.path.basename(self.source_dir.get().strip()) or "?"
            text, role = f"当前模式：单个文件（{name}）", "green"
        elif self.source_dir.get().strip():
            # 文件夹模式：启用递归
            self.recursive_check.config(state=tk.NORMAL)
            if self.recursive.get():
                text, role = "当前模式：文件夹（递归处理）", "text_dim"
            else:
                text, role = "当前模式：文件夹", "text_dim"
        else:
            self.recursive_check.config(state=tk.NORMAL)
            text, role = "当前模式：未选择", "text_dim"
        try:
            self.mode_label.config(text=text, fg=color(role))
        except Exception:
            pass
        self._refresh_slot()

    def on_recursive_change(self, *args):
        """递归选项改变时更新标签"""
        if not self.is_single_file:
            self.update_mode_label()

    # ====================== 智能拖拽 ======================
    def on_drop_source(self, event):
        """智能拖拽：自动识别文件夹或文件"""
        path = event.data
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]

        if os.path.isdir(path):
            self.source_dir.set(path)
            self.is_single_file = False
            self.update_mode_label()
            log_summary(f"已拖拽源目录：{path}")
        elif os.path.isfile(path):
            self.source_dir.set(path)
            self.is_single_file = True
            self.update_mode_label()
            log_summary(f"已拖拽单个文件：{os.path.basename(path)}")
        else:
            log_summary(f"无效路径：{path}")

    def on_drop_output(self, event):
        """拖拽输出目录"""
        path = event.data
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]
        if os.path.isdir(path):
            self.output_dir.set(path)
            log_summary(f"已拖拽输出目录：{path}")

    # ------------------------------ 基础功能 ------------------------------
    def select_source(self):
        """合并的选择按钮：弹出菜单选择文件夹或文件"""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="选择文件夹", command=self._select_folder)
        menu.add_command(label="选择文件", command=self._select_file)

        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _select_folder(self):
        """选择文件夹"""
        p = self._pick_path(filedialog.askdirectory)
        if not p:
            return
        self.source_dir.set(p)
        self.is_single_file = False
        self.update_mode_label()
        log_summary(f"已选择源目录：{p}")

    def _select_file(self):
        """选择单个文件"""
        exts = self.file_exts.get().replace(',', ' ').strip()
        if exts:
            filetypes = [("目标文件", exts), ("所有文件", "*.*")]
        else:
            filetypes = [("所有文件", "*.*")]
        p = self._pick_path(filedialog.askopenfilename, filetypes=filetypes)
        if not p:
            return
        self.source_dir.set(p)
        self.is_single_file = True
        self.update_mode_label()
        log_summary(f"已选择单个文件：{os.path.basename(p)}")

    def clear_source(self):
        """清除源文件/文件夹选择"""
        if self.source_dir.get():
            self.source_dir.set("")
            self.is_single_file = False
            # 递归复选框 / 模式指示 / 插件槽 context 一起复位（原先只改复选框，
            # 模式指示与带 when 的插件命令都留在旧状态）。
            self.update_mode_label()
            log_summary("已清除源文件/文件夹选择")

    def select_output(self):
        p = self._pick_path(filedialog.askdirectory)
        if p:
            self.output_dir.set(p)

    def clear_output(self):
        """清除输出文件夹选择"""
        if self.output_dir.get():
            self.output_dir.set("")
            log_summary("已清除输出文件夹选择")

    # 日志统一走全局通道（log_summary / log_detail），不再自建 LogBox

    def open_out_dir(self):
        """打开输出目录（无输出目录时退化为源目录 / 源文件所在目录）。"""
        out = self.output_dir.get().strip()
        if out:
            d = out
        else:
            src = self.source_dir.get().strip()
            if not src:
                # 单文件模式下源框为空时 os.path.dirname("") == ""，
                # 原先会误报"目录不存在"。
                self._ui(messagebox.showwarning, "提示", "请先选择源路径或输出目录")
                return
            d = os.path.dirname(src) if self.is_single_file else src
            if not d:
                self._ui(messagebox.showwarning, "提示", "请先选择源路径或输出目录")
                return
        if os.path.isdir(d):
            open_in_explorer(d)
        else:
            self._ui(messagebox.showwarning, "提示", f"目录不存在：{d}")

    # ------------------------------ 智能备份 ------------------------------
    def on_output_dir_change(self, *args):
        if self.output_dir.get():
            self.backup_files.set(False)
            self.backup_check.config(state=tk.DISABLED)
        else:
            self.backup_check.config(state=tk.NORMAL)

    # ------------------------------ 排除模式匹配 ------------------------------
    def is_excluded(self, filepath, snap=None):
        snap = snap if snap is not None else self._task_snap()

        pattern_str = (snap['exclude_pattern'] or "").strip()
        if not pattern_str:
            return False

        patterns = [p.strip() for p in pattern_str.split(',') if p.strip()]

        if not snap['is_single_file'] and os.path.isdir(snap['source_dir'] or ""):
            src = snap['source_dir']
            try:
                if os.path.commonpath([filepath, src]) == src:
                    rel_path = os.path.relpath(filepath, src)
                else:
                    rel_path = filepath
            except ValueError:
                rel_path = filepath
        else:
            rel_path = filepath

        import fnmatch
        for pattern in patterns:
            if fnmatch.fnmatch(os.path.basename(filepath), pattern):
                return True
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if pattern.replace('*', '') in rel_path:
                return True

        return False

    # ------------------------------ 暂停/取消控制 ------------------------------
    def toggle_pause(self):
        """切换暂停状态"""
        if self.paused:
            self.paused = False
            self.pause_event.set()
            self._ui(self.pause_btn.config, text="暂停")
            log_summary("===== 继续转换 =====")
        else:
            self.paused = True
            self.pause_event.clear()
            self._ui(self.pause_btn.config, text="继续")
            log_summary("===== 暂停转换 =====")

    def cancel_convert(self):
        """取消转换"""
        if messagebox.askyesno("确认", "确定要取消当前转换任务吗？"):
            self.cancelled = True
            self.paused = False
            self.pause_event.set()
            self._ui(self.cancel_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, state=tk.DISABLED)
            log_summary("===== 用户取消转换 =====")

    # ────────────────────── 自动校验：已删除 ──────────────────────
    # （2026-09，用户决定；审计报告见交接区 `HanaAgent\01_新增\STALKER工具集\
    #  编码转换_自动校验审计报告.md`）
    #
    # 原 `verify_file()` 的判据是"用同一个 src_enc 解码两侧原始/输出字节，再逐字符
    # 比内容"。它有四处缺陷，保留就必须四处一起修：
    #   ① 校验失败仍被计入 success（日志出现 `[成功] … | 校验失败: 内容不一致`）；
    #   ② 两侧都用 errors="replace" → 非法字节在两边都变 U+FFFD → 内容相等 →
    #      **假通过**（输出其实已含替换字符）；③ 目标编码装不下时静默写 `?`，
    #      报错只说"内容不一致"，说不出根因；④ 输出 BOM 被剥掉后才比内容，
    #      所以"输出不带 BOM"这一条根本没被校验。
    #
    # 删除的依据是**字符集关系**，不是感觉：工具默认方向是"任意源 → UTF-8"，
    # 1251/1252 等单字节 → UTF-8 是**扩容**（任何字符都能表示），本来就是 UTF-8 的
    # 也只做声明/BOM 规范化 —— 两种情形都不会丢字符。缩水（UTF-8 → 单字节）只在
    # 用户手动把目标设成单字节编码时才可能，且那两个 errors="replace" 口子就在
    # 转换路径上（见 convert_file），不是校验能补救的。
    #
    # **何时需要重新考虑**：若日后引入缩水方向（反向转码、或目标语言字符集更小），
    # 不必重做整套校验，只加"替换计数 + 告警"即可。
    # **若日后要加回校验**：不要恢复"宣称内容一致"的版本，只做**确定能判准**的
    # 单项强判据 —— 输出能否用目标编码**严格**解码（不许 replace）、输出是否含
    # U+FFFD、输出首字节是否 BOM。这几条不会出现"报了通过其实坏了"。

    def export_stats(self):
        """导出统计信息（界面参数取**产生本次统计的任务快照**，不读实时界面值）"""
        try:
            default_name = f"转换统计_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = self._pick_path(
                filedialog.asksaveasfilename,
                defaultextension=".csv",
                filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
                initialfile=default_name)
            if not filepath:
                return
            # 统计属于上一次转换任务：用那次任务的快照，避免"转完后改了界面参数，
            # 导出的 CSV 却写成新参数"（与 convert_stats 口径不符）。
            snap = self._stats_snap if self._stats_snap is not None else self._ensure_snap()
            stats = self.convert_stats
            duration = ""
            if stats['start_time'] and stats['end_time']:
                delta = stats['end_time'] - stats['start_time']
                duration = str(delta).split('.')[0]

            with open(filepath, 'w', encoding='utf-8-sig') as f:
                f.write("编码转换统计报告\n")
                f.write(f"生成时间,{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"源目录/文件,{snap['source_dir']}\n")
                f.write(f"处理模式,{'单个文件' if snap['is_single_file'] else '文件夹'}\n")
                f.write(f"输出目录,{snap['output_dir'] or '原地转换'}\n")
                f.write(f"源编码,{snap['source_enc']}\n")
                f.write(f"目标编码,{snap['target_enc']}\n")
                f.write(f"候选文件数,{self.total}\n")
                f.write(f"已处理,{self.current}\n")
                f.write(f"成功转换,{stats['success']}\n")
                f.write(f"跳过文件,{stats['skipped']}\n")
                f.write(f"失败文件,{stats['failed']}\n")
                f.write(f"耗时,{duration}\n")

            log_summary(f"统计已导出到：{filepath}")
            self._ui(messagebox.showinfo, "成功", f"统计已保存到：\n{filepath}")
        except Exception as e:
            self._ui(errbox, "错误", f"导出失败：{str(e)}")

    # ------------------------------ 备份相关 (源目录/backup/*.bak) ------------------------------
    def get_backup_path(self, original_path, snap=None):
        """获取原文件对应的.bak备份路径（源目录/backup/保持原目录结构）"""
        snap = snap if snap is not None else self._task_snap()
        src_root = self._source_root(snap)
        if not src_root:
            src_root = os.path.dirname(original_path) or os.getcwd()
        backup_root = os.path.join(src_root, BACKUP_DIRNAME)
        os.makedirs(backup_root, exist_ok=True)

        try:
            rel_path = os.path.relpath(original_path, src_root)
            if rel_path.startswith(".."):
                rel_path = os.path.basename(original_path)
        except ValueError:
            rel_path = os.path.basename(original_path)
        backup_path = os.path.join(backup_root, rel_path) + BACKUP_SUFFIX
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        return backup_path

    def backup_file(self, original_path, snap=None):
        """将文件备份到源目录的backup子目录中（保持原目录结构）"""
        try:
            backup_path = self.get_backup_path(original_path, snap)
            if not os.path.exists(backup_path):
                shutil.copy2(original_path, backup_path)
                log_detail(f"[备份] {os.path.basename(original_path)} → {backup_path}")
            else:
                log_detail(f"[备份跳过] {os.path.basename(original_path)} 已存在备份文件：{backup_path}")
        except Exception as e:
            # 备份失败是用户必须知道的（可能误以为已备份），保留在 GUI 并标 err
            log_summary(f"[备份失败] {os.path.basename(original_path)} | {str(e)}", "err")

    # ------------------------------ 恢复备份 (.bak 格式) ------------------------------
    def restore_file(self, bak_path, snap=None):
        """将backup目录下的.bak备份文件恢复到原位置；返回是否成功。

        源根目录取**本任务快照**：恢复途中清空源框不能让后半程全部落进
        "原文件不存在"分支。失败一律走 log_summary（用户可见），细节走 log_detail。
        """
        try:
            snap = snap if snap is not None else self._task_snap()
            src_root = self._source_root(snap)
            if not src_root:
                log_summary(f"[恢复失败] {os.path.basename(bak_path)} | 未选择源目录")
                return False
            backup_root = os.path.join(src_root, BACKUP_DIRNAME)
            rel_path = os.path.relpath(bak_path, backup_root)[:-len(BACKUP_SUFFIX)]
            original_path = os.path.join(src_root, rel_path)

            if os.path.exists(original_path):
                shutil.copy2(bak_path, original_path)
                log_detail(f"[恢复] {os.path.basename(bak_path)} → {original_path}")
                return True
            log_summary(f"[恢复失败] {os.path.basename(bak_path)} | 原文件不存在：{original_path}")
            return False
        except Exception as e:
            log_summary(f"[恢复失败] {os.path.basename(bak_path)} | {str(e)}")
            return False

    def run_restore(self, snap=None, already_started=False):
        """执行恢复备份逻辑（适配backup目录下的.bak格式）"""
        if not already_started and not self._begin_task("恢复备份"):
            return
        if snap is None:
            snap = self._ensure_snap(force=True)
        self._bind_task_snap(snap)
        try:
            log_summary("===== 开始恢复备份 =====")
            src_root = self._source_root(snap)
            if not src_root:
                self._ui(errbox, "错误", "请选择源目录")
                return

            backup_root = os.path.join(src_root, BACKUP_DIRNAME)
            if not os.path.exists(backup_root):
                log_summary("未找到backup目录")
                self._ui(messagebox.showinfo, "提示", "未找到backup目录，无备份可恢复")
                return

            exts = [e.strip().lower() for e in snap['file_exts'].split(",") if e.strip()]
            if not exts:
                raise Exception("请输入文件扩展名，例如 .xml,.txt")

            bak_exts = [f"{e}{BACKUP_SUFFIX}" for e in exts]
            backup_files = []
            for r, _, fs in os.walk(backup_root):
                for f in fs:
                    if any(f.lower().endswith(e) for e in bak_exts):
                        backup_files.append(os.path.join(r, f))
                if not snap['recursive']:
                    break

            # 进度计数是本任务私有的局部变量：与转换任务的 total/current 解耦
            total = len(backup_files)
            self._set_progress(0, total, "restore")

            if total == 0:
                log_summary("未找到.bak备份文件")
                self._ui(messagebox.showinfo, "提示", "未找到可恢复的.bak备份文件")
                return

            ok = 0
            failed = 0
            for i, f in enumerate(backup_files, 1):
                if self.restore_file(f, snap):
                    ok += 1
                else:
                    failed += 1
                self._set_progress(i, total, "restore")

            log_summary(f"===== 恢复结束：成功 {ok} / 失败 {failed} / 候选 {total} =====")
            self._finish_dialog("恢复备份", ok, failed, total)

        except Exception as e:
            log_summary(f"恢复异常：{str(e)}")
            self._ui(errbox, "错误", str(e))
        finally:
            self._unbind_task_snap()
            self._end_task()

    def start_restore_thread(self):
        """启动恢复备份线程"""
        if not self._begin_task("恢复备份"):
            return
        if not messagebox.askyesno("确认", "恢复备份将替换当前文件，是否继续？"):
            log_summary("已取消恢复备份", "dim")
            self._end_task()
            return
        snap = self._ensure_snap(force=True)   # 任务启动时冻结当前界面参数
        self._start_worker(self.run_restore, snap, "恢复备份")

    # ------------------------------ 清空备份功能 ------------------------------
    def run_clear_backup(self, snap=None, already_started=False):
        """执行清空backup目录下的.bak备份文件逻辑"""
        if not already_started and not self._begin_task("清空备份"):
            return
        if snap is None:
            snap = self._ensure_snap(force=True)
        self._bind_task_snap(snap)
        try:
            log_summary("===== 开始清空备份 =====")
            src_root = self._source_root(snap)
            if not src_root:
                self._ui(errbox, "错误", "请选择源目录")
                return

            backup_root = os.path.join(src_root, BACKUP_DIRNAME)
            if not os.path.exists(backup_root):
                log_summary("未找到backup目录")
                self._ui(messagebox.showinfo, "提示", "未找到backup目录，无备份可清空")
                return

            exts = [e.strip().lower() for e in snap['file_exts'].split(",") if e.strip()]
            if not exts:
                raise Exception("请输入文件扩展名，例如 .xml,.txt")

            bak_exts = [f"{e}{BACKUP_SUFFIX}" for e in exts]
            backup_files = []
            for r, _, fs in os.walk(backup_root):
                for f in fs:
                    if any(f.lower().endswith(e) for e in bak_exts):
                        backup_files.append(os.path.join(r, f))
                if not snap['recursive']:
                    break

            # 进度计数按任务私有（不共用转换任务的 total/current）
            total = len(backup_files)
            self._set_progress(0, total, "clear")

            if total == 0:
                log_summary("未找到.bak备份文件")
                self._ui(messagebox.showinfo, "提示", "未找到可清空的.bak备份文件")
                return

            ok = 0
            failed = 0
            for i, f in enumerate(backup_files, 1):
                try:
                    os.remove(f)
                    log_detail(f"[删除备份] {os.path.basename(f)} → {f}")
                    ok += 1
                except Exception as e:
                    log_summary(f"[删除失败] {os.path.basename(f)} | {str(e)}")
                    failed += 1
                self._set_progress(i, total, "clear")

            log_summary(f"===== 清空结束：成功 {ok} / 失败 {failed} / 候选 {total} =====")
            self._finish_dialog("清空备份", ok, failed, total)

        except Exception as e:
            log_summary(f"清空备份异常：{str(e)}")
            self._ui(errbox, "错误", str(e))
        finally:
            self._unbind_task_snap()
            self._end_task()

    def start_clear_backup_thread(self):
        """启动清空备份线程"""
        if not self._begin_task("清空备份"):
            return
        if not messagebox.askyesno("确认", "确认要删除backup目录下所有.bak备份文件吗？此操作不可恢复！"):
            log_summary("已取消清空备份", "dim")
            self._end_task()
            return
        snap = self._ensure_snap(force=True)   # 任务启动时冻结当前界面参数
        self._start_worker(self.run_clear_backup, snap, "清空备份")

    # ------------------------------ 核心转换 ------------------------------
    def _get_source_encoding(self, raw_data, snap=None):
        """获取源编码（判定链统一由 toolkit_textio.sniff_encoding 提供）：

            手动指定 → BOM → 严格 UTF-8 → XML 声明 → 统计探测 → windows-1251

        判定与收尾策略全部在公共库里（含"低置信度西欧单字节回落 windows-1251"），
        本方法只负责把本任务的 source_enc 设置传进去，不再自带第二套规则。
        """
        snap = snap if snap is not None else self._task_snap()
        return sniff_encoding(raw_data, override=snap['source_enc'])

    def get_files(self, snap=None):
        snap = snap if snap is not None else self._task_snap()

        # 单文件模式
        if snap['is_single_file']:
            path = (snap['source_dir'] or "").strip()
            if os.path.isfile(path):
                if self.is_excluded(path, snap):
                    log_summary(f"[排除] {os.path.basename(path)}")
                    return []
                return [path]
            else:
                raise Exception("无效的文件路径")

        # 文件夹模式
        src = (snap['source_dir'] or "").strip()
        if not os.path.isdir(src):
            raise Exception("无效的源目录")
        exts = [e.strip().lower() for e in snap['file_exts'].split(",") if e.strip()]
        if not exts:
            raise Exception("请输入文件扩展名，例如 .xml,.txt")

        files = []
        for r, _, fs in os.walk(src):
            # 跳过backup目录
            if BACKUP_DIRNAME in os.path.relpath(r, src).split(os.sep):
                continue
            for f in fs:
                # 排除.bak文件
                if f.lower().endswith(BACKUP_SUFFIX):
                    continue
                if any(f.lower().endswith(e) for e in exts):
                    filepath = os.path.join(r, f)
                    if not self.is_excluded(filepath, snap):
                        files.append(filepath)
                    else:
                        log_summary(f"[排除] {os.path.basename(filepath)}")
            if not snap['recursive']:
                break
        return files

    # ────────────────────── XML 声明 ──────────────────────

    @staticmethod
    def _fix_xml_decl(content, target_enc):
        """把 XML 声明规范化：统一双引号 + encoding 值改写成目标编码，保留其它属性。

        只处理**第一条** `<?xml ... ?>`（`count=1`），且只替换**已存在**的
        encoding 属性 —— 没有该属性时不补写，转换分支与"已是目标编码"分支
        共用本函数，保证两处口径一致。
        """
        def _one(m):
            decl = m.group(0).replace("'", '"')
            decl = re.sub(r"(encoding\s*=\s*\")[^\"]*(\")",
                          lambda mm: mm.group(1) + target_enc + mm.group(2),
                          decl, flags=re.I)
            return decl
        return re.sub(r"<\?xml[^>]*\?>", _one, content, count=1, flags=re.I)

    @staticmethod
    def _needs_rewrite(raw, target_enc, had_utf8_bom=False):
        """源已是目标编码时，文件是否**仍然必须重写**。两种情况要写：

        1. **源带 UTF-8 BOM** —— 输出侧一律不带 BOM（BOM 只对 utf-8 合法，
           留在 windows-1251 文件里是脏字节）。注意 `raw` 已在 `convert_file`
           入口剥掉 BOM，所以这个事实只能由调用方用标志传进来。
        2. XML 声明的 encoding 值与**目标编码**不符 —— 否则声明会永远停在不匹配
           的值上（用户报告的"转成 utf-8 之后声明不变"）。声明写的是目标编码，
           不是硬编码 utf-8：目标设成 windows-1251 时就写 windows-1251。

        没有 encoding 属性时第 2 条为 False —— 与 `_fix_xml_decl` 的口径一致
        （不补写声明）。两条都不满足就不写盘：否则"原地转换"会对每个本来就正确的
        文件重写一遍，既无意义又会把真正改过的文件淹没。
        """
        if had_utf8_bom:
            return True
        t = (target_enc or "").strip().lower()
        m = re.search(rb"<\?xml[^>]*\?>", raw[:400], re.I | re.S)
        if not m:
            return False
        em = re.search(rb"encoding\s*=\s*[\"\']([^\"\']*)[\"\']", m.group(0), re.I)
        if not em:
            return False
        cur = em.group(1).decode("ascii", "replace").strip().lower()
        return cur != t

    def convert_file(self, path, snap=None):
        """转换单个文件（参数取本任务快照，见 _task_snap）"""
        snap = snap if snap is not None else self._task_snap()
        if self.cancelled:
            return "cancelled"

        self.pause_event.wait()

        try:
            with open(path, "rb") as f:
                raw = f.read()
            # 字节级剥离 BOM (cp1251 解码 BOM 是乱码而非 \ufeff, 必须在解码前处理)。
            # 但"剥掉"不等于"忘掉"：**源带 UTF-8 BOM** 这个事实必须留个标志，
            # 因为输出侧一律不带 BOM —— 否则"源 BOM + 声明已对 + 目标非 utf-8"
            # 会判成"已是目标编码"而整文件跳过，BOM 就留在里面了（BOM 只对
            # utf-8 合法，留在 windows-1251 文件里是脏字节）。
            had_utf8_bom = raw[:3] == b"\xef\xbb\xbf"
            if had_utf8_bom:
                raw = raw[3:]
            elif raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                raw = raw[2:]

            src_enc = self._get_source_encoding(raw, snap)
            target = snap['target_enc'].lower()

            # 日志: 如实标出**是链条的哪一步做的决定**（顺序必须与 sniff_encoding 一致，
            # 否则这一行会自相矛盾）。原先只按"有没有声明"分支、值却来自多字节检查，
            # 于是"字节是 UTF-8、声明写 windows-1251"的文件被写成 `声明(utf-8)` ——
            # 读起来像"声明说 utf-8"，而声明明明写的是 1251。这一行正是用户用来
            # 核对"这个目录到底是什么编码"的依据，不能含糊。
            override = (snap['source_enc'] or "").strip().lower()
            if is_multibyte_utf8(raw):
                enc_source = f"多字节({src_enc})"      # ① 含多字节序列 → 判为 UTF-8
            elif override and override != "auto":
                enc_source = f"指定({src_enc})"        # ② 手动指定
            elif _has_xml_decl_encoding(raw):
                enc_source = f"声明({src_enc})"        # ③ 采信（且被字节证实的）XML 声明
            else:
                enc_source = f"统计({src_enc})"        # ④ 统计探测 → 默认 windows-1251

            if snap['output_dir']:
                if snap['is_single_file']:
                    out_path = os.path.join(snap['output_dir'], os.path.basename(path))
                else:
                    src_root = snap['source_dir']
                    try:
                        rel = os.path.relpath(path, src_root) if src_root else os.path.basename(path)
                    except ValueError:
                        rel = os.path.basename(path)
                    out_path = os.path.join(snap['output_dir'], rel)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
            else:
                out_path = path

            if src_enc == target:
                # ── 源已是目标编码：内容不用重新编码，但声明/BOM 仍要对齐 ──
                # 走到这里的唯一合理情形是"多字节检查判定为 utf-8"（`sniff_encoding`
                # 第 2 步），即文件**确实含多字节 UTF-8 序列**，但声明写的却是别的
                # （例如字节是 UTF-8、声明写 windows-1251 的"声明撒谎"文件）。
                # 此时正文必须原样保留，只把声明改成目标编码。
                #
                # 注意：纯 ASCII 的英文 XML **不会**再走到这里 —— 它没有多字节证据，
                # `sniff_encoding` 会继续走手动/声明/统计，拿到 windows-1251，从而
                # 进入下面的真实转换分支、把声明一并改掉。1.0.0 的问题正是"能不能按
                # UTF-8 解码"被当成了多字节判据，纯 ASCII 也算数 → 一律判 utf-8 →
                # 撞进本分支；而旧实现在原地转换时**直接 return "skipped"、不写文件**
                # → 声明永远停在 windows-1251。现在判据修对了，本分支只剩真多字节。
                if snap['output_dir'] and target != "utf-8":
                    # 输出到新目录且目标不是 utf-8：原样复制（保持既有语义）
                    shutil.copy2(path, out_path)
                    note = "已是目标编码（原样复制）"
                elif snap['output_dir'] or self._needs_rewrite(
                        raw, snap['target_enc'], had_utf8_bom):
                    # 两条进入条件，语义不同，别合并成一条：
                    #   * output_dir 非空 —— **必须产出文件**（用户要的是新目录里有一份，
                    #     哪怕声明本来就对；漏写会让输出目录缺文件）；
                    #   * 原地 —— 只在声明不符或源带 UTF-8 BOM 时才写盘，
                    #     不无谓重写本来就没问题的文件。
                    # `raw` 已在入口剥掉 BOM，所以这里直接按 src_enc 解即可，
                    # 写出去的就是不带 BOM 的内容。
                    content = raw.decode(src_enc, errors="replace")
                    if content.startswith("\ufeff"):
                        content = content[1:]
                    content = self._fix_xml_decl(content, snap['target_enc'])
                    if not snap['output_dir'] and snap['backup_files']:
                        self.backup_file(path, snap)
                    with open(out_path, "w", encoding=snap['target_enc'],
                              errors="replace", newline="") as f:
                        f.write(content)
                    note = f"已是目标编码；已对齐声明/BOM → {snap['target_enc']}"
                else:
                    note = "已是目标编码"
                log_detail(f"[跳过] {os.path.basename(path)} | 源={enc_source}，{note}")
                self.convert_stats['skipped'] += 1
                return "skipped"

            try:
                content = raw.decode(src_enc, errors="replace")
            except Exception:
                fallback_enc = "windows-1251"
                content = raw.decode(fallback_enc, errors="replace")
                log_detail(f"[警告] {os.path.basename(path)} | {src_enc}解码失败，使用{fallback_enc}")

            # 剥离源 BOM (U+FEFF 作为字符保留会令输出以 BOM 字节开头, 触发"转换后带BOM"校验)
            if content.startswith("\ufeff"):
                content = content[1:]

            if path.lower().endswith(".xml"):
                # XML 声明: 统一双引号 + 替换 encoding 值为目标编码 (保留其他属性)
                content = self._fix_xml_decl(content, snap['target_enc'])

            if not snap['output_dir'] and snap['backup_files']:
                self.backup_file(path, snap)

            with open(out_path, "w", encoding=snap['target_enc'], errors="replace", newline="") as f:
                f.write(content)

            self.convert_stats['success'] += 1
            log_detail(f"[成功] {os.path.basename(path)} | {enc_source} → {target}")
            return "success"

        except Exception as e:
            self.convert_stats['failed'] += 1
            log_summary(f"[失败] {os.path.basename(path)} | {str(e)}")
            return "failed"

    def run_convert(self, snap=None, already_started=False):
        """执行转换。

        snap: 本次任务的参数快照（start_thread 在主线程冻结后通过参数传入）。
              直接调用（脚本 / 探针）时自行冻结一份。工作线程全程只读这一份，
              绝不读运行期会被"恢复备份"等任务用 _ensure_snap(force=True)
              改写的 self._snap。
        """
        if not already_started and not self._begin_task("开始转换"):
            return
        if snap is None:
            snap = self._ensure_snap(force=True)
        self._bind_task_snap(snap)
        self._stats_snap = snap
        try:
            self._run_convert_body(snap)
        finally:
            self._unbind_task_snap()
            self._end_task()

    def _run_convert_body(self, snap):
        """转换主流程（在持有本任务快照的线程内执行）。"""
        try:
            self.paused = False
            self.cancelled = False
            self.pause_event.set()

            self.convert_stats = {
                'success': 0, 'skipped': 0, 'failed': 0,
                'start_time': datetime.now(), 'end_time': None
            }

            self._ui(self.pause_btn.config, state=tk.NORMAL)
            self._ui(self.cancel_btn.config, state=tk.NORMAL)
            self._ui(self.pause_btn.config, text="暂停")

            log_summary("===== 开始转换 =====")

            enc_setting = (snap['source_enc'] or "").strip().lower()
            if enc_setting == "auto":
                # 这里**不再**把整条判定链摊出来：每个文件的定案步骤（多字节 / 指定 /
                # 声明 / 统计）都逐行写在下面，那才是查"为什么判成这个编码"的地方。
                # 每次运行重复一遍链条属于噪音（完整链见 ARCHITECTURE.md §4.1）。
                log_summary("源编码：自动检测")
            else:
                # 手动指定只在"多字节证据不足"时生效（多字节 UTF-8 用单字节编码解必乱码，
                # 属物理事实）。每个文件那行会标 `指定(...)` 还是 `多字节(...)`，不必在此预警。
                log_summary(f"源编码：手动指定为 {enc_setting}")

            if not (snap['source_dir'] or "").strip():
                self._ui(errbox, "错误", "请选择源目录或文件")
                return

            files = self.get_files(snap)
            self.total = len(files)
            self.current = 0
            self._set_progress(0, self.total, "convert")

            if self.total == 0:
                log_summary("未找到目标文件")
                self._ui(messagebox.showinfo, "完成", "未找到可转换文件")
                return

            for f in files:
                result = self.convert_file(f, snap)
                self.current += 1
                self._set_progress(self.current, self.total, "convert")

                if result == "cancelled":
                    break

            self.convert_stats['end_time'] = datetime.now()
            duration = str(self.convert_stats['end_time'] - self.convert_stats['start_time']).split('.')[0]

            if self.cancelled:
                log_summary("===== 转换已取消 =====")
                log_summary(f"已处理 {self.current} / {self.total} 个候选文件 | 耗时：{duration}")
            else:
                log_summary("===== 全部完成 =====")

            stats = self.convert_stats
            summary = (
                f"\n========== 转换统计 ==========\n"
                f"候选文件总数：{self.total}\n"
                f"本次已处理：{self.current}\n"
                f"成功转换：{stats['success']}\n"
                f"跳过文件：{stats['skipped']}\n"
                f"失败文件：{stats['failed']}\n"
            )
            summary += (
                f"总耗时：{duration}\n"
                f"================================"
            )
            log_summary(summary)

            # 口径与进度标签一致：分母是候选文件数，跳过/失败同样计入"已处理"，
            # "M / M" 不代表 M 个成功。
            msg = (f"处理完成！\n"
                   f"候选文件：{self.total} 个（已处理 {self.current} / {self.total}）\n"
                   f"成功：{stats['success']} | 跳过：{stats['skipped']} | 失败：{stats['failed']}\n"
                   f"注：「已处理」含跳过与失败，不等于成功数\n"
                   f"耗时：{duration}")
            self._ui(messagebox.showinfo, "完成", msg)

        except Exception as e:
            log_summary(f"异常：{str(e)}")
            self._ui(errbox, "错误", str(e))
        finally:
            self._ui(self.pause_btn.config, state=tk.DISABLED)
            self._ui(self.cancel_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, text="暂停")
            self.paused = False
            self.pause_event.set()

    def start_thread(self):
        """启动转换线程。

        与其余五个 App 不同，本 App **不**使用 toolkit 的 TaskRunner，理由：
          * 本工具是唯一带「暂停 / 继续」状态机的（pause_event + paused），
            其按钮三态（开始/暂停/取消）在 _run_convert_body 的 try/finally 里
            自洽管理；
          * run_restore / run_clear_backup 也各自持有自己的任务状态；
        强行套 TaskRunner 只会让 running 标志与按钮状态出现两份来源，
        没有收益且要重写暂停逻辑。TaskRunner 的其他能力（构造级探针、
        失败不静默）在本 App 由显式 try/except + log_summary 覆盖。
        """
        # 第一件事就是重入检查并置位：按钮禁用是异步投递的，连点两次会起两个线程
        # 交叉写同一批文件、统计双份累加。
        if not self._begin_task("开始转换"):
            return
        snap = self._ensure_snap(force=True)   # 任务启动时冻结当前界面参数
        self._start_worker(self.run_convert, snap, "转换")
