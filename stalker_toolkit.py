# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 单文件整合版
主题/组件/六个工具 GUI/hub 全部集中于此文件, 杜绝多文件不一致.
运行: python stalker_toolkit.py
"""
import os, sys, re, threading, struct, shutil, subprocess, tempfile, time, json, glob
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Set, Tuple, Union, Any, Callable
import xml.etree.ElementTree as ET

# 引擎库路径注入 (stalker_fs / font_pack 在各自工具子目录)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(_BASE_DIR, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toolkit import (
    THEMES, T, color, apply_theme, apply_tk_defaults,
    dir_row, count_label, tool_header, tool_text,
    LogBox, CanvasTree, SplitPane, PluginManager,
    _make_pump, _role_of, refresh_theme, DEFAULT_ENCODINGS,
    fmt_size, read_text_file, parse_xml_texts,
    log_section, vscrollbar, drop_zone,
    load_user_theme, save_user_theme,
    _BaseTk, _HAS_DND, DND_FILES,
)
from apps.font_pack_app import FontPackApp
from apps.convert_app import ConvertApp
from apps.text_extract_app import TextExtractApp
from apps.xml_compare_app import XMLCompareApp
from apps.video_ogm_app import VideoOGMApp
from apps.fs_app import FSToolApp

# ════════════════════════════════════════════════════════════════
# 1. 主题 (亮/暗两套, 单函数切换)
# ════════════════════════════════════════════════════════════════
def install_package(package):
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        return True
    except:
        return False

required = {"chardet": "chardet", "tkinterdnd2": "tkinterdnd2"}
for imp, pkg in required.items():
    try:
        __import__(imp)
    except ImportError:
        install_package(pkg)

# ====================== 导入库（带回退） ======================
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import chardet
    def _detect_encoding(raw):
        return chardet.detect(raw)
except ImportError:
    def _detect_encoding(raw):
        for enc in ["utf-8", "cp1251", "cp1252", "gbk"]:
            try:
                raw.decode(enc)
                return {"encoding": enc, "confidence": 0.8}
            except:
                continue
        return {"encoding": "utf-8", "confidence": 0.5}


# ====================== 主程序 ======================
if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = _BaseTk()
    root.title("STALKER 汉化工具集")
    root.geometry("1280x860")
    root.minsize(1024, 700)
    root.configure(bg=T["bg"])
    apply_theme()
    apply_tk_defaults(root)

    TOOLS = [
        ("文件系统", FSToolApp),
        ("编码转换", ConvertApp),
        ("文本提取", TextExtractApp),
        ("XML校对", XMLCompareApp),
        ("视频转换", VideoOGMApp),
        ("汉化包生成", FontPackApp),
    ]

    def rebuild(nb, apps):
        for tab in nb.tabs():
            nb.forget(tab)
        apps.clear()
        for label, cls in TOOLS:
            tab = tk.Frame(nb, bg=color("bg"))
            nb.add(tab, text=label)
            try:
                apps[label] = cls(tab)
            except Exception as e:
                ttk.Label(tab, text=f"加载失败: {e}", style="Red.TLabel").pack(pady=30)
        apply_theme()

    def attach_log(apps, g_log):
        def hide(w):
            for c in w.winfo_children():
                if isinstance(c, LogBox) and getattr(c, "_log_role", False):
                    lf = c.master
                    pane = lf.master if lf is not None else None
                    panedw = pane.master if pane is not None else None
                    try:
                        if panedw is not None and panedw.winfo_class() == "TPanedwindow":
                            panedw.forget(pane)  # 移除整个日志 pane (无空背景/无用分隔条)
                        else:
                            (lf or c.master).pack_forget()
                    except Exception:
                        pass
                    return
                hide(c)
        for app in apps.values():
            if app is None:
                continue
            # 重定向到全局日志, 经 app._ui 泵保证线程安全
            if hasattr(app, "_ui") and callable(app._ui):
                if hasattr(app, "_log") and callable(app._log):
                    app._log = lambda msg, tag="info", a=app: a._ui(g_log.add, msg, tag)
                if hasattr(app, "log") and callable(app.log):
                    app.log = lambda msg, a=app: a._ui(g_log.add, msg)
            else:
                if hasattr(app, "_log") and callable(app._log):
                    app._log = lambda msg, tag="info": g_log.add(msg, tag)
                if hasattr(app, "log") and callable(app.log):
                    app.log = lambda msg: g_log.add(msg)
            hide(app.root)

    def build_hub(mode="dark"):
        """构建 hub 全部界面 (仅首次构建时销毁重建; 切主题只换色不重建)."""
        for w in root.winfo_children():
            w.destroy()
        apply_theme(mode)
        root.configure(bg=color("bg"))

        header = ttk.Frame(root)
        header.pack(fill="x", padx=14, pady=(12, 4))
        ttk.Label(header, text="STALKER 汉化工具集", style="Title.TLabel").pack(side="left")
        # 主题下拉框在右, 标签在其左侧
        theme_var = tk.StringVar(value="暗色" if mode == "dark" else "亮色")

        def on_theme(val):
            mode = "light" if val == "亮色" else "dark"
            apply_theme(mode)
            save_user_theme(mode)
            root.configure(bg=color("bg"))
            refresh_theme(root)

        om = ttk.OptionMenu(header, theme_var, theme_var.get(), "暗色", "亮色", command=on_theme)
        om.pack(side="right")
        ttk.Label(header, text="主题:", style="Dim.TLabel").pack(side="right", padx=(0, 4))

        nb_paned = SplitPane(root, orient="vertical")
        nb_paned.pack(fill="both", expand=True, padx=10, pady=(4, 2))
        nb = ttk.Notebook(nb_paned)
        nb_paned.add(nb, weight=3)
        log_lf = ttk.LabelFrame(nb_paned, text="日志", padding=4)
        nb_paned.add(log_lf, weight=1)
        log_bar = ttk.Frame(log_lf); log_bar.pack(fill="x", pady=(0, 2))

        def export_log():
            """导出日志到 程序目录/logs/ (自动创建)."""
            try:
                g_log._flush()  # 先落盘 pending 缓冲日志
                logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
                os.makedirs(logs_dir, exist_ok=True)
                fn = os.path.join(logs_dir, f"log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(g_log.get("1.0", "end"))
                g_log.add(f"日志已导出: {fn}", "ok")
            except Exception as e:
                g_log.add(f"导出失败: {e}", "err")

        ttk.Button(log_bar, text="导出", width=6, command=export_log).pack(side="right")
        ttk.Label(log_bar, text="运行日志", style="Dim.TLabel").pack(side="left")
        g_log = LogBox(log_lf, height=6)
        apps = {}
        rebuild(nb, apps)
        attach_log(apps, g_log)

    build_hub(load_user_theme())
    root.mainloop()
