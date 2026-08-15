# -*- coding: utf-8 -*-
"""Auto-split app module."""
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

class ConvertApp(ttk.Frame):
    def __init__(self, master=None):
        self.root = master or _BaseTk()
        super().__init__(self.root)
        self.pack(fill="both", expand=True)  # 铺满宿主 (tab/独立窗口)
        # 统一主题 (toolkit 单一来源)
        apply_theme()
        apply_tk_defaults(self.root)
        if master is None:
            self.root.title("编码转换工具")
            self.root.geometry("950x880")
            self.root.resizable(True, True)

        # 原有变量
        self.source_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.file_exts = tk.StringVar(value=".xml")
        self.target_enc = tk.StringVar(value="utf-8")
        self.source_enc = tk.StringVar(value="auto")
        self.recursive = tk.BooleanVar(value=True)
        self.backup_files = tk.BooleanVar(value=True)

        # 新增变量
        self.auto_verify = tk.BooleanVar(value=True)
        self.exclude_pattern = tk.StringVar()

        # 进度控制
        self.total = 0
        self.current = 0
        self.paused = False
        self.cancelled = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        import queue as _q
        self._ui_q = _q.Queue()
        try:
            self.root.after(30, self._ui_pump)
        except Exception:
            pass

        # 统计信息
        self.convert_stats = {
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'verified_ok': 0,
            'verified_fail': 0,
            'start_time': None,
            'end_time': None
        }

        # 标记当前是文件还是文件夹模式
        self.is_single_file = False

        self.output_dir.trace_add("write", self.on_output_dir_change)
        self.recursive.trace_add("write", self.on_recursive_change)
        self.init_ui()

    def init_ui(self):
        """界面 (统一组件: dir_row/log_section/color 模板)."""
        PAD = 14
        # ═══ 标题 ═══
        tool_header(self, "编码转换工具")
        # ═══ 可调分区: 上部设置区 / 下部日志区 (分隔条拖拽) ═══
        self._paned = SplitPane(self, orient="vertical")
        self._paned.pack(fill="both", expand=True, padx=PAD, pady=(2, 8))
        upper = ttk.Frame(self._paned)
        lower = ttk.Frame(self._paned)
        self._paned.add(upper, weight=3)
        self._paned.add(lower, weight=1)


        # ═══ 源目录 ═══
        source_frame = ttk.LabelFrame(upper, text="源文件夹 / 单个文件")
        source_frame.pack(fill="x", padx=PAD, pady=6)
        _, self.source_entry = dir_row(source_frame, "源", self.source_dir,
                                       browse=self.select_source,
                                       add=("清除", self.clear_source))

        # ═══ 输出目录 ═══
        out_frame = ttk.LabelFrame(upper, text="输出文件夹")
        out_frame.pack(fill="x", padx=PAD, pady=6)
        _, self.out_entry = dir_row(out_frame, "输出", self.output_dir,
                                    browse=self.select_output,
                                    add=("清除", self.clear_output))

        # ═══ 转换设置 ═══
        set_frame = ttk.LabelFrame(upper, text="转换设置")
        set_frame.pack(fill="x", padx=PAD, pady=6)
        set_frame.columnconfigure(5, weight=1)
        # 行0: 源/目标编码
        ttk.Label(set_frame, text="源编码：").grid(row=0, column=0, padx=(10, 4), pady=8, sticky="e")
        self.source_enc_combo = ttk.Combobox(set_frame, textvariable=self.source_enc,
            values=["auto", "utf-8", "gbk", "gb2312", "big5", "shift_jis", "euc-kr",
                    "windows-1251", "windows-1252", "iso-8859-1", "ascii", "utf-16"],
            width=14, state="readonly")
        self.source_enc_combo.grid(row=0, column=1, padx=(0, 6), sticky="w")
        ttk.Label(set_frame, text="自动检测可能不准确", style="Dim.TLabel").grid(row=0, column=2, padx=(0, 14), sticky="w")
        ttk.Label(set_frame, text="目标编码：").grid(row=0, column=3, padx=(12, 4), pady=8, sticky="e")
        ttk.Combobox(set_frame, textvariable=self.target_enc,
            values=["utf-8", "gbk", "gb2312", "windows-1251", "ascii", "utf-16", "big5"],
            width=14).grid(row=0, column=4, padx=(0, 10), sticky="w")
        # 行1: 扩展名 + 选项
        ttk.Label(set_frame, text="扩展名：").grid(row=1, column=0, padx=(10, 4), pady=8, sticky="e")
        ttk.Entry(set_frame, textvariable=self.file_exts, width=18).grid(row=1, column=1, padx=(0, 6), sticky="w")
        self.recursive_check = tk.Checkbutton(set_frame, text="递归子目录", variable=self.recursive)
        self.recursive_check.grid(row=1, column=2, padx=8, sticky="w")
        self.backup_check = tk.Checkbutton(set_frame, text="备份为.bak", variable=self.backup_files)
        self.backup_check.grid(row=1, column=3, padx=8, sticky="w")
        tk.Checkbutton(set_frame, text="自动校验", variable=self.auto_verify).grid(row=1, column=4, padx=8, sticky="w")
        # 行2: 排除模式
        ttk.Label(set_frame, text="排除模式：").grid(row=2, column=0, padx=(10, 4), pady=(0, 10), sticky="e")
        ttk.Entry(set_frame, textvariable=self.exclude_pattern, width=28).grid(row=2, column=1, columnspan=2, padx=(0, 6), sticky="w")
        ttk.Label(set_frame, text="通配符逗号分隔, 如 *backup*,temp*", style="Dim.TLabel").grid(row=2, column=3, columnspan=2, padx=8, sticky="w")

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
        ttk.Button(btn_frame, text="恢复备份", command=self.start_restore_thread, width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="清空备份", command=self.start_clear_backup_thread, width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="打开输出", command=self.open_out_dir, width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="导出", command=self.export_stats, width=8).pack(side="left", padx=4)

        # ═══ 转换进度 (在下区, 日志上方) ═══
        prog_frame = ttk.LabelFrame(lower, text="转换进度")
        prog_frame.pack(fill="x", padx=PAD, pady=6)
        self.prog_var = tk.DoubleVar()
        self.prog_bar = ttk.Progressbar(prog_frame, variable=self.prog_var, maximum=100)
        self.prog_bar.pack(fill="x", padx=10, pady=(8, 2))
        self.prog_label = ttk.Label(prog_frame, text="0 / 0 文件", style="Dim.TLabel")
        self.prog_label.pack(pady=(0, 6))

        # ═══ 日志 (统一 log_section, hub 集成时隐藏) ═══
        self.log_lf, self.log_box = log_section(lower, "运行日志", height=10, clear=False)
        self.log_box._timestamp = True

        # ═══ 拖拽 (dir_row 已注册, 绑定处理) ═══
        try:
            if hasattr(self.source_entry, "drop_target_register"):
                self.source_entry.drop_target_register(DND_FILES)
                self.source_entry.dnd_bind("<<Drop>>", self.on_drop_source)
                self.out_entry.drop_target_register(DND_FILES)
                self.out_entry.dnd_bind("<<Drop>>", self.on_drop_output)
        except Exception:
            pass

    # ====================== 更新模式 ======================
    def update_mode_label(self):
        """根据当前模式更新递归复选框状态"""
        if self.is_single_file:
            # 单文件模式：禁用递归
            self.recursive.set(False)
            self.recursive_check.config(state=tk.DISABLED)
        else:
            # 文件夹模式：启用递归
            self.recursive_check.config(state=tk.NORMAL)

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
            self.log(f"已拖拽源目录：{path}")
        elif os.path.isfile(path):
            self.source_dir.set(path)
            self.is_single_file = True
            self.update_mode_label()
            self.log(f"已拖拽单个文件：{os.path.basename(path)}")
        else:
            self.log(f"无效路径：{path}")

    def on_drop_output(self, event):
        """拖拽输出目录"""
        path = event.data
        if path.startswith('{') and path.endswith('}'):
            path = path[1:-1]
        if os.path.isdir(path):
            self.output_dir.set(path)
            self.log(f"已拖拽输出目录：{path}")

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
        p = filedialog.askdirectory()
        if p:
            self.source_dir.set(p)
            self.is_single_file = False
            self.update_mode_label()
            self.log(f"已选择源目录：{p}")

    def _select_file(self):
        """选择单个文件"""
        exts = self.file_exts.get().replace(',', ' ').strip()
        if exts:
            filetypes = [("目标文件", exts), ("所有文件", "*.*")]
        else:
            filetypes = [("所有文件", "*.*")]
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            self.source_dir.set(p)
            self.is_single_file = True
            self.update_mode_label()
            self.log(f"已选择单个文件：{os.path.basename(p)}")

    def clear_source(self):
        """清除源文件/文件夹选择"""
        if self.source_dir.get():
            self.source_dir.set("")
            self.is_single_file = False
            self.recursive_check.config(state=tk.NORMAL)
            self.log("已清除源文件/文件夹选择")

    def select_output(self):
        p = filedialog.askdirectory()
        if p:
            self.output_dir.set(p)

    def clear_output(self):
        """清除输出文件夹选择"""
        if self.output_dir.get():
            self.output_dir.set("")
            self.log("已清除输出文件夹选择")

    def _ui(self, fn, *args, **kwargs):
        """从工作线程安全调度 UI 调用到主线程 (queue 队列, 主线程轮询泵)."""
        self._ui_q.put((fn, args, kwargs))

    def _ui_pump(self):
        """主线程轮询泵: 每 30ms 处理 UI 队列."""
        try:
            while True:
                fn, a, k = self._ui_q.get_nowait()
                try:
                    fn(*a, **k)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.after(30, self._ui_pump)
        except Exception:
            pass

    def _ensure_snap(self):
        """确保快照存在 (主线程直接调 get_files 等时刷新为最新值)."""
        if threading.current_thread() is threading.main_thread() or not getattr(self, "_snap", None):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'auto_verify': self.auto_verify.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }

    def log(self, msg):
        self._ui(self.log_box.add, msg)
    def clear_log(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete(1.0, tk.END)
        self.log_box.config(state=tk.DISABLED)

    def open_out_dir(self):
        d = self.output_dir.get() or (self.source_dir.get() if not self.is_single_file else os.path.dirname(self.source_dir.get()))
        if os.path.isdir(d):
            os.startfile(d)
        else:
            self._ui(messagebox.showwarning, "提示", "目录不存在")

    # ------------------------------ 智能备份 ------------------------------
    def on_output_dir_change(self, *args):
        if self.output_dir.get():
            self.backup_files.set(False)
            self.backup_check.config(state=tk.DISABLED)
        else:
            self.backup_check.config(state=tk.NORMAL)

    # ------------------------------ 排除模式匹配 ------------------------------
    def is_excluded(self, filepath):
        self._ensure_snap()

        pattern_str = self._snap['exclude_pattern'].strip()
        if not pattern_str:
            return False

        patterns = [p.strip() for p in pattern_str.split(',') if p.strip()]
        
        if not self.is_single_file and os.path.isdir(self._snap['source_dir']):
            src = self._snap['source_dir']
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
            self.log("===== 继续转换 =====")
        else:
            self.paused = True
            self.pause_event.clear()
            self._ui(self.pause_btn.config, text="继续")
            self.log("===== 暂停转换 =====")

    def cancel_convert(self):
        """取消转换"""
        if messagebox.askyesno("确认", "确定要取消当前转换任务吗？"):
            self.cancelled = True
            self.paused = False
            self.pause_event.set()
            self._ui(self.cancel_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, state=tk.DISABLED)
            self.log("===== 用户取消转换 =====")

    # ------------------------------ 自动校验 ------------------------------
    def verify_file(self, original_path, converted_path):
        """校验转换后的文件完整性"""
        try:
            if not os.path.exists(converted_path):
                return False, "文件不存在"

            orig_size = os.path.getsize(original_path)
            conv_size = os.path.getsize(converted_path)
            
            if orig_size == 0:
                if conv_size > 10:
                    return False, f"空文件转换后大小异常({conv_size}字节)"
                return True, "通过"

            target_enc = self._snap['target_enc'].lower()
            with open(converted_path, 'rb') as f:
                conv_raw = f.read()

            # 解码前剥离 BOM 字节 (输出带 BOM 也能正常校验, BOM 归入声明归一化比较)
            if conv_raw[:3] == b"\xef\xbb\xbf":
                conv_raw = conv_raw[3:]
            elif conv_raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                conv_raw = conv_raw[2:]

            try:
                conv_content = conv_raw.decode(target_enc)
            except:
                return False, f"无法用目标编码({target_enc})解码"

            with open(original_path, 'rb') as f:
                orig_raw = f.read()
            # 字节级剥离 BOM (与 convert_file 一致)
            if orig_raw[:3] == b"\xef\xbb\xbf":
                orig_raw = orig_raw[3:]
            elif orig_raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                orig_raw = orig_raw[2:]

            src_enc = self._get_source_encoding(orig_raw)

            try:
                orig_content = orig_raw.decode(src_enc, errors='replace')
            except:
                orig_content = orig_raw.decode("windows-1251", errors='replace')
            # 源 BOM 剥离 (与 convert_file 一致, 转换输出不带 BOM)
            if orig_content.startswith("\ufeff"):
                orig_content = orig_content[1:]
            if conv_content.startswith("\ufeff"):
                conv_content = conv_content[1:]  # 兼容: 转换侧已剥离, 此处双保险

            # XML 校验两条路:
            #  1) 无声明: 字符级严格相等
            #  2) 有声明: 声明除 encoding 外完全一致 + 转换后不带 BOM + 正文严格相等
            def _split_xml_decl(s):
                m = re.match(r"^\s*<\?xml[^>]*\?>", s, re.S)
                return (s[m.start():m.end()], s[m.end():]) if m else (None, s)

            orig_decl, orig_body = _split_xml_decl(orig_content)
            conv_decl, conv_body = _split_xml_decl(conv_content)

            if orig_decl is None:
                # 路 1: 无声明, 字符级严格相等
                if orig_content != conv_content:
                    return False, "内容不一致(无XML声明须完全一致)"
            else:
                # 路 2: 有声明
                if conv_decl is None:
                    return False, "XML声明缺失"
                # 声明归一化: BOM + 引号 + encoding 值一起归并比较
                def _norm_decl(decl):
                    d = decl.lstrip("\ufeff")
                    d = d.replace("'", '"')
                    d = re.sub(r'encoding\s*=\s*"[^"]*"', '', d, flags=re.I)
                    return d.strip()
                if _norm_decl(orig_decl) != _norm_decl(conv_decl):
                    return False, "XML声明不一致(除编码/引号/BOM外)"
                # 正文: 字符级严格相等
                if orig_body != conv_body:
                    return False, "内容不一致"

            return True, "通过"

        except Exception as e:
            return False, f"校验异常: {str(e)}"

    # ------------------------------ 日志导出 ------------------------------
    def export_log(self):
        """导出运行日志"""
        try:
            default_name = f"转换日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                initialfile=default_name
            )
            if filepath:
                log_content = self.log_box.get(1.0, tk.END)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                self.log(f"日志已导出到：{filepath}")
                self._ui(messagebox.showinfo, "成功", f"日志已保存到：\n{filepath}")
        except Exception as e:
            self._ui(errbox, "错误", f"导出失败：{str(e)}")

    def export_stats(self):
        """导出统计信息"""
        try:
            default_name = f"转换统计_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
                initialfile=default_name
            )
            if filepath:
                stats = self.convert_stats
                duration = ""
                if stats['start_time'] and stats['end_time']:
                    delta = stats['end_time'] - stats['start_time']
                    duration = str(delta).split('.')[0]

                with open(filepath, 'w', encoding='utf-8-sig') as f:
                    f.write("编码转换统计报告\n")
                    f.write(f"生成时间,{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"源目录/文件,{self.source_dir.get()}\n")
                    f.write(f"处理模式,{'单个文件' if self.is_single_file else '文件夹'}\n")
                    f.write(f"输出目录,{self.output_dir.get() or '原地转换'}\n")
                    f.write(f"源编码,{self.source_enc.get()}\n")
                    f.write(f"目标编码,{self.target_enc.get()}\n")
                    f.write(f"文件总数,{self.total}\n")
                    f.write(f"成功转换,{stats['success']}\n")
                    f.write(f"跳过文件,{stats['skipped']}\n")
                    f.write(f"失败文件,{stats['failed']}\n")
                    f.write(f"校验通过,{stats['verified_ok']}\n")
                    f.write(f"校验失败,{stats['verified_fail']}\n")
                    f.write(f"耗时,{duration}\n")

                self.log(f"统计已导出到：{filepath}")
                self._ui(messagebox.showinfo, "成功", f"统计已保存到：\n{filepath}")
        except Exception as e:
            self._ui(errbox, "错误", f"导出失败：{str(e)}")

    # ------------------------------ 备份相关 (.bak 格式) ------------------------------
    def get_backup_path(self, original_path):
        """获取原文件对应的.bak备份路径（源目录/backup/保持原目录结构）"""
        src_root = self.source_dir.get() if not self.is_single_file else os.path.dirname(self.source_dir.get())
        if not src_root:
            src_root = os.path.dirname(original_path) or os.getcwd()
        backup_root = os.path.join(src_root, "backup")
        os.makedirs(backup_root, exist_ok=True)

        try:
            rel_path = os.path.relpath(original_path, src_root)
            if rel_path.startswith(".."):
                rel_path = os.path.basename(original_path)
        except ValueError:
            rel_path = os.path.basename(original_path)
        backup_path = os.path.join(backup_root, rel_path) + ".bak"
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        return backup_path

    def backup_file(self, original_path):
        """将文件备份到源目录的backup子目录中（保持原目录结构）"""
        try:
            backup_path = self.get_backup_path(original_path)
            if not os.path.exists(backup_path):
                shutil.copy2(original_path, backup_path)
                self.log(f"[备份] {os.path.basename(original_path)} → {backup_path}")
            else:
                self.log(f"[备份跳过] {os.path.basename(original_path)} 已存在备份文件：{backup_path}")
        except Exception as e:
            self.log(f"[备份失败] {os.path.basename(original_path)} | {str(e)}")

    # ------------------------------ 恢复备份 (.bak 格式) ------------------------------
    def restore_file(self, bak_path):
        """将backup目录下的.bak备份文件恢复到原位置"""
        try:
            src_root = self.source_dir.get() if not self.is_single_file else os.path.dirname(self.source_dir.get())
            backup_root = os.path.join(src_root, "backup")
            rel_path = os.path.relpath(bak_path, backup_root)[:-4]
            original_path = os.path.join(src_root, rel_path)
            
            if os.path.exists(original_path):
                shutil.copy2(bak_path, original_path)
                self.log(f"[恢复] {os.path.basename(bak_path)} → {original_path}")
            else:
                self.log(f"[恢复失败] {os.path.basename(bak_path)} | 原文件不存在：{original_path}")
        except Exception as e:
            self.log(f"[恢复失败] {os.path.basename(bak_path)} | {str(e)}")

    def run_restore(self):
        """执行恢复备份逻辑（适配backup目录下的.bak格式）"""
        try:
            self.log("===== 开始恢复备份 =====")
            if not self._snap['source_dir']:
                self._ui(errbox, "错误", "请选择源目录")
                return

            src_root = self._snap['source_dir'] if not self.is_single_file else os.path.dirname(self._snap['source_dir'])
            backup_root = os.path.join(src_root, "backup")
            if not os.path.exists(backup_root):
                self.log("未找到backup目录")
                self._ui(messagebox.showinfo, "提示", "未找到backup目录，无备份可恢复")
                return

            exts = [e.strip().lower() for e in self._snap['file_exts'].split(",") if e.strip()]
            if not exts:
                raise Exception("请输入文件扩展名，例如 .xml,.txt")

            bak_exts = [f"{e}.bak" for e in exts]
            backup_files = []
            for r, _, fs in os.walk(backup_root):
                for f in fs:
                    if any(f.lower().endswith(e) for e in bak_exts):
                        backup_files.append(os.path.join(r, f))
                if not self._snap['recursive']:
                    break

            self.total = len(backup_files)
            self.current = 0
            self._ui(self.prog_var.set, 0)
            self._ui(self.prog_label.config, text=f"0 / {self.total}")

            if self.total == 0:
                self.log("未找到.bak备份文件")
                self._ui(messagebox.showinfo, "提示", "未找到可恢复的.bak备份文件")
                return

            for f in backup_files:
                self.restore_file(f)
                self.current += 1
                self._ui(self.prog_var.set, (self.current / self.total) * 100)
                self._ui(self.prog_label.config, text=f"{self.current} / {self.total}")

            self.log("===== 恢复完成 =====")
            self._ui(messagebox.showinfo, "完成", f"恢复完成！\n总计：{self.total} 个.bak文件")

        except Exception as e:
            self.log(f"恢复异常：{str(e)}")
            self._ui(errbox, "错误", str(e))

    def start_restore_thread(self):
        """启动恢复备份线程"""
        if messagebox.askyesno("确认", "恢复备份将替换当前文件，是否继续？"):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'auto_verify': self.auto_verify.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }
            threading.Thread(target=self.run_restore, daemon=True).start()

    # ------------------------------ 清空备份功能 ------------------------------
    def run_clear_backup(self):
        """执行清空backup目录下的.bak备份文件逻辑"""
        try:
            self.log("===== 开始清空备份 =====")
            if not self._snap['source_dir']:
                self._ui(errbox, "错误", "请选择源目录")
                return

            src_root = self._snap['source_dir'] if not self.is_single_file else os.path.dirname(self._snap['source_dir'])
            backup_root = os.path.join(src_root, "backup")
            if not os.path.exists(backup_root):
                self.log("未找到backup目录")
                self._ui(messagebox.showinfo, "提示", "未找到backup目录，无备份可清空")
                return

            exts = [e.strip().lower() for e in self._snap['file_exts'].split(",") if e.strip()]
            if not exts:
                raise Exception("请输入文件扩展名，例如 .xml,.txt")

            bak_exts = [f"{e}.bak" for e in exts]
            backup_files = []
            for r, _, fs in os.walk(backup_root):
                for f in fs:
                    if any(f.lower().endswith(e) for e in bak_exts):
                        backup_files.append(os.path.join(r, f))
                if not self._snap['recursive']:
                    break

            self.total = len(backup_files)
            self.current = 0
            self._ui(self.prog_var.set, 0)
            self._ui(self.prog_label.config, text=f"0 / {self.total}")

            if self.total == 0:
                self.log("未找到.bak备份文件")
                self._ui(messagebox.showinfo, "提示", "未找到可清空的.bak备份文件")
                return

            for f in backup_files:
                try:
                    os.remove(f)
                    self.log(f"[删除备份] {os.path.basename(f)} → {f}")
                except Exception as e:
                    self.log(f"[删除失败] {os.path.basename(f)} | {str(e)}")
                self.current += 1
                self._ui(self.prog_var.set, (self.current / self.total) * 100)
                self._ui(self.prog_label.config, text=f"{self.current} / {self.total}")

            self.log("===== 清空备份完成 =====")
            self._ui(messagebox.showinfo, "完成", f"清空备份完成！\n总计处理：{self.total} 个文件")

        except Exception as e:
            self.log(f"清空备份异常：{str(e)}")
            self._ui(errbox, "错误", str(e))

    def start_clear_backup_thread(self):
        """启动清空备份线程"""
        if messagebox.askyesno("确认", "确认要删除backup目录下所有.bak备份文件吗？此操作不可恢复！"):
            self._snap = {
                'source_dir': self.source_dir.get(),
                'output_dir': self.output_dir.get(),
                'file_exts': self.file_exts.get(),
                'target_enc': self.target_enc.get(),
                'source_enc': self.source_enc.get(),
                'recursive': self.recursive.get(),
                'backup_files': self.backup_files.get(),
                'auto_verify': self.auto_verify.get(),
                'exclude_pattern': self.exclude_pattern.get(),
                'is_single_file': self.is_single_file,
            }
            threading.Thread(target=self.run_clear_backup, daemon=True).start()

    # ------------------------------ 核心转换 ------------------------------
    def _get_source_encoding(self, raw_data):
        """获取源编码 (确定性优先):
        1. XML 声明 (权威) → 2. 严格 utf-8 解码测试 (确定性区分 utf-8/单字节)
        → 3. 手动指定 (非 utf-8 文件) → 4. cp1251 兜底."""
        # 1. XML 声明优先
        m = re.search(rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']',
                      raw_data[:500], re.I | re.S)
        if m:
            decl_enc = m.group(1).decode("ascii", "replace").strip().lower()
            if decl_enc in ("utf-8", "utf8"):
                return "utf-8"
            if decl_enc in ("windows-1251", "windows1251", "cp1251", "cp-1251"):
                return "windows-1251"
            if decl_enc:
                return decl_enc
        # 2. 严格 utf-8 解码测试 (确定性, 区分 utf-8 vs 单字节编码)
        try:
            raw_data.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        # 3. 手动指定 (对无声明且非 utf-8 的文件生效)
        specified_enc = self._snap['source_enc'].strip().lower()
        if specified_enc and specified_enc != "auto":
            return specified_enc
        # 4. cp1251 兜底 (STALKER 俄语场景)
        return "windows-1251"

    def get_files(self):
        self._ensure_snap()

        # 单文件模式
        if self.is_single_file:
            path = self._snap['source_dir'].strip()
            if os.path.isfile(path):
                if self.is_excluded(path):
                    self.log(f"[排除] {os.path.basename(path)}")
                    return []
                return [path]
            else:
                raise Exception("无效的文件路径")

        # 文件夹模式
        src = self._snap['source_dir'].strip()
        if not os.path.isdir(src):
            raise Exception("无效的源目录")
        exts = [e.strip().lower() for e in self._snap['file_exts'].split(",") if e.strip()]
        if not exts:
            raise Exception("请输入文件扩展名，例如 .xml,.txt")
        
        files = []
        for r, _, fs in os.walk(src):
            # 跳过backup目录
            if "backup" in os.path.relpath(r, src).split(os.sep):
                continue
            for f in fs:
                # 排除.bak文件
                if f.lower().endswith(".bak"):
                    continue
                if any(f.lower().endswith(e) for e in exts):
                    filepath = os.path.join(r, f)
                    if not self.is_excluded(filepath):
                        files.append(filepath)
                    else:
                        self.log(f"[排除] {os.path.basename(filepath)}")
            if not self._snap['recursive']:
                break
        return files

    def convert_file(self, path):
        """转换单个文件"""
        self._ensure_snap()
        if self.cancelled:
            return "cancelled"

        self.pause_event.wait()

        try:
            with open(path, "rb") as f:
                raw = f.read()
            # 字节级剥离 BOM (cp1251 解码 BOM 是乱码而非 \ufeff, 必须在解码前处理)
            if raw[:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
            elif raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                raw = raw[2:]
            
            src_enc = self._get_source_encoding(raw)
            target = self._snap['target_enc'].lower()

            # 日志: 准确反映编码来源
            decl_m = re.search(rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', raw[:500], re.I | re.S)
            if decl_m:
                enc_source = f"声明({src_enc})"
            elif self._snap['source_enc'].strip().lower() == "auto":
                enc_source = f"自动({src_enc})"
            else:
                enc_source = f"指定({src_enc})"

            if self._snap['output_dir']:
                if self.is_single_file:
                    out_path = os.path.join(self._snap['output_dir'], os.path.basename(path))
                else:
                    src_root = self._snap['source_dir']
                    try:
                        rel = os.path.relpath(path, src_root) if src_root else os.path.basename(path)
                    except ValueError:
                        rel = os.path.basename(path)
                    out_path = os.path.join(self._snap['output_dir'], rel)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
            else:
                out_path = path

            if src_enc == target:
                if self._snap['output_dir']:
                    if target == "utf-8":
                        # 源已是 UTF-8，但可能带 BOM；统一写成无 BOM UTF-8
                        content = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8",
                                            errors="replace")
                        content = re.sub(r"<\?xml[^>]*\?>",
                                         lambda m: re.sub(r"(encoding\s*=\s*[\"'])[^\"']*([\"'])",
                                                         r"\1utf-8\2", m.group(0), flags=re.I),
                                         content, count=1, flags=re.I)
                        with open(out_path, "w", encoding="utf-8", errors="replace", newline="") as f:
                            f.write(content)
                    else:
                        shutil.copy2(path, out_path)
                self.log(f"[跳过] {os.path.basename(path)} | 源={enc_source}，已是目标编码")
                self.convert_stats['skipped'] += 1
                return "skipped"

            try:
                content = raw.decode(src_enc, errors="replace")
            except:
                fallback_enc = "windows-1251"
                content = raw.decode(fallback_enc, errors="replace")
                self.log(f"[警告] {os.path.basename(path)} | {src_enc}解码失败，使用{fallback_enc}")

            # 剥离源 BOM (U+FEFF 作为字符保留会令输出以 BOM 字节开头, 触发"转换后带BOM"校验)
            if content.startswith("\ufeff"):
                content = content[1:]

            if path.lower().endswith(".xml"):
                # XML 声明: 统一双引号 + 替换 encoding 值为目标编码 (保留其他属性)
                def _fix_xml_decl(m):
                    decl = m.group(0).replace("'", '"')
                    decl = re.sub(r"(encoding\s*=\s*\")[^\"]*(\")",
                                  lambda mm: mm.group(1) + self._snap['target_enc'] + mm.group(2),
                                  decl, flags=re.I)
                    return decl
                content = re.sub(r"<\?xml[^>]*\?>", _fix_xml_decl, content, count=1, flags=re.I)

            if not self._snap['output_dir'] and self._snap['backup_files']:
                self.backup_file(path)

            with open(out_path, "w", encoding=self._snap['target_enc'], errors="replace", newline="") as f:
                f.write(content)

            verify_result = ""
            if self._snap['auto_verify']:
                success, msg = self.verify_file(path, out_path)
                if success:
                    self.convert_stats['verified_ok'] += 1
                    verify_result = " | 校验通过"
                else:
                    self.convert_stats['verified_fail'] += 1
                    verify_result = f" | 校验失败: {msg}"

            self.convert_stats['success'] += 1
            self.log(f"[成功] {os.path.basename(path)} | {enc_source} → {target}{verify_result}")
            return "success"

        except Exception as e:
            self.convert_stats['failed'] += 1
            self.log(f"[失败] {os.path.basename(path)} | {str(e)}")
            return "failed"

    def run_convert(self):
        """执行转换"""
        try:
            self.paused = False
            self.cancelled = False
            self.pause_event.set()

            self.convert_stats = {
                'success': 0, 'skipped': 0, 'failed': 0,
                'verified_ok': 0, 'verified_fail': 0,
                'start_time': datetime.now(), 'end_time': None
            }

            self._ui(self.start_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, state=tk.NORMAL)
            self._ui(self.cancel_btn.config, state=tk.NORMAL)
            self._ui(self.pause_btn.config, text="暂停")

            self.log("===== 开始转换 =====")
            
            enc_setting = self._snap['source_enc'].strip().lower()
            if enc_setting == "auto":
                self.log("源编码：自动检测（chardet）")
            else:
                self.log(f"源编码：手动指定为 {enc_setting}")

            if not self._snap['source_dir']:
                self._ui(errbox, "错误", "请选择源目录或文件")
                return

            files = self.get_files()
            self.total = len(files)
            self.current = 0
            self._ui(self.prog_var.set, 0)
            self._ui(self.prog_label.config, text=f"0 / {self.total}")

            if self.total == 0:
                self.log("未找到目标文件")
                self._ui(messagebox.showinfo, "完成", "未找到可转换文件")
                return

            for f in files:
                result = self.convert_file(f)
                self.current += 1
                self._ui(self.prog_var.set, (self.current / self.total) * 100)
                self._ui(self.prog_label.config, text=f"{self.current} / {self.total}")

                if result == "cancelled":
                    break

            self.convert_stats['end_time'] = datetime.now()
            duration = str(self.convert_stats['end_time'] - self.convert_stats['start_time']).split('.')[0]

            if self.cancelled:
                self.log(f"===== 转换已取消 =====")
                self.log(f"已处理：{self.current}/{self.total} 文件 | 耗时：{duration}")
            else:
                self.log("===== 全部完成 =====")

            stats = self.convert_stats
            summary = (
                f"\n========== 转换统计 ==========\n"
                f"总文件数：{self.total}\n"
                f"成功转换：{stats['success']}\n"
                f"跳过文件：{stats['skipped']}\n"
                f"失败文件：{stats['failed']}\n"
            )
            if self._snap['auto_verify']:
                summary += (
                    f"校验通过：{stats['verified_ok']}\n"
                    f"校验失败：{stats['verified_fail']}\n"
                )
            summary += (
                f"总耗时：{duration}\n"
                f"================================"
            )
            self.log(summary)

            msg = f"处理完成！\n总计：{self.total} 个文件\n"
            msg += f"成功：{stats['success']} | 跳过：{stats['skipped']} | 失败：{stats['failed']}\n"
            msg += f"耗时：{duration}"
            self._ui(messagebox.showinfo, "完成", msg)

        except Exception as e:
            self.log(f"异常：{str(e)}")
            self._ui(errbox, "错误", str(e))
        finally:
            self._ui(self.start_btn.config, state=tk.NORMAL)
            self._ui(self.pause_btn.config, state=tk.DISABLED)
            self._ui(self.cancel_btn.config, state=tk.DISABLED)
            self._ui(self.pause_btn.config, text="暂停")
            self.paused = False
            self.pause_event.set()

    def start_thread(self):
        self._snap = {
            'source_dir': self.source_dir.get(),
            'output_dir': self.output_dir.get(),
            'file_exts': self.file_exts.get(),
            'target_enc': self.target_enc.get(),
            'source_enc': self.source_enc.get(),
            'recursive': self.recursive.get(),
            'backup_files': self.backup_files.get(),
            'auto_verify': self.auto_verify.get(),
            'exclude_pattern': self.exclude_pattern.get(),
            'is_single_file': self.is_single_file,
        }
        threading.Thread(target=self.run_convert, daemon=True).start()

# ═══ 零散文本提取 ═══
RUS_LETTERS = "".join(chr(c) for c in range(0x0410, 0x0450)) + "\u0401\u0451"
RUS_LET_CPL = re.compile("[" + RUS_LETTERS + "]")
WORD_PATTERN = re.compile("[" + RUS_LETTERS + "a-zA-Z]")
SCRIPT_LINE_PERMIT_PTN = re.compile(
    r"([Mm]essage|[Tt]ext(?!ure)|(?<![a-z])[Nn]ews(?![a-z]))")
SCRIPT_LINE_SENSITIVE_PTN = re.compile(
    r"(exec|write|parse_names|load|(?<!de)script(?!ion)|call|"
    r"set(?![Tt]ext)|open|sound|effect|abort|print|console|cmd|return)")
SCRIPT_MATCH_SENSITIVE_PTN = re.compile(r'("[\s]*return)')
CFG_TAG_PTN = re.compile(
    r"<(?:text|bio|title|name)(?:| [ \S]*?[^/]) *?>([^<>]*?)</(?:text|bio|title|name)>")
CFG_ATTR_PTN = re.compile(r'(?:hint|name)\s*=\s*((?:"[^"]*")|' + r"(?:'[^']*'))")
SCRIPT_TRANSLATE_FUNC = "game.translate_string"


