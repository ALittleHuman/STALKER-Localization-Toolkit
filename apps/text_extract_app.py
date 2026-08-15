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
)

def _does_text_look_like_id(text: str) -> bool:
    if len(RUS_LET_CPL.findall(text)) > 0:
        return False
    if "_" in text:
        return True
    return " " not in text


def _does_text_look_like_script(text: str) -> bool:
    if len(RUS_LET_CPL.findall(text)) > 0:
        return False
    if '=' in text or '@' in text:
        return True
    for blk in [r":\d", r"load\s+~+"]:
        if re.compile(blk).search(text):
            return True
    return False


def _get_config_xml_texts(text: str) -> Set[str]:
    candidates = []
    for m in CFG_TAG_PTN.findall(text):
        if m.strip():
            candidates.append(m.strip())
    for m in CFG_ATTR_PTN.findall(text):
        if len(m) > 2:
            candidates.append(m[1:-1])
    return set(candidates)


def _escape_literal_text(text: str, quote: str = '"') -> str:
    escaped = text.replace("\\", '\\\\').replace("\n", '\\n')
    if quote == '"':
        escaped = escaped.replace('"', '\\"')
    elif quote == "'":
        escaped = escaped.replace("'", "\\'")
    return escaped


def _get_script_texts(text: str) -> Set[str]:
    result = set()
    for line in text.split("\n"):
        line = re.sub(r'--[\s\S]*$', '', line).strip()
        is_open, ongoing, is_escape, quote_char = False, '', False, None
        line_matches = set()
        for i, ch in enumerate(line):
            if ch in ('"', "'"):
                if ch == quote_char or quote_char is None:
                    if not is_open:
                        ongoing, quote_char, is_open = ch, ch, True
                        continue
                    if is_escape:
                        ongoing += ch; is_escape = False
                    else:
                        ongoing += ch; is_open = False; quote_char = None
                        if (not SCRIPT_MATCH_SENSITIVE_PTN.search(ongoing)
                                and WORD_PATTERN.search(ongoing)):
                            line_matches.add(ongoing)
                    continue
            if is_open:
                if ch == '\\':
                    is_escape = not is_escape
                    if not is_escape: ongoing += '\\\\'
                    else: ongoing += '\\'
                elif ch == 'n' and is_escape:
                    ongoing += '\n'; is_escape = False
                else:
                    ongoing += ch
        sorted_lm = sorted(line_matches, key=len, reverse=True)
        sac_line = line
        for lm in sorted_lm:
            qc = lm[0]
            sac_line = sac_line.replace(
                qc + _escape_literal_text(lm[1:-1], quote=qc) + qc, "")
        norm = sac_line.lower()
        if SCRIPT_LINE_PERMIT_PTN.search(norm):
            result = set(sorted_lm + list(result))
        elif not SCRIPT_LINE_SENSITIVE_PTN.search(norm):
            result = set(sorted_lm + list(result))
    return result


def _replace_from_text(text: str, replacement: Dict[str, str]) -> str:
    for key in sorted(replacement, key=len, reverse=True):
        text = text.replace(key, replacement[key])
    return text


def _escape_xml_content(text: str) -> str:
    for a, b in [('&', '&amp;'), ('"', '&quot;'), ("'", '&apos;'), ('<', '&lt;')]:
        text = text.replace(a, b)
    text = text.strip()
    return text if text else '\xa0'


def _split_text_at_length(text: str, n: int) -> List[str]:
    if not text: return [""]
    return [text[i*n:(i+1)*n] for i in range(len(text)//n)] + [text[(len(text)//n)*n:]]


def _normalize_xml_string(xml_str: str, need_fix_st: bool = True,
                          delete_header: bool = True) -> str:
    if need_fix_st: delete_header = True
    if "</" in xml_str:
        while xml_str and not xml_str.startswith("<"):
            xml_str = xml_str[1:]
    xml_str = re.sub(r'&[\s]+amp;', '&amp;', xml_str)
    xml_str = re.sub(r'&[\s]+lt;', '&lt;', xml_str)
    xml_str = re.sub(
        '&(?!ensp;|emsp;|nbsp;|lt;|gt;|amp;|quot;|copy;|reg;|trade;|times;|divide;)',
        '&amp;', xml_str)
    xml_str = re.sub(r'<!--[\s\S]*?-->', '', xml_str)
    if delete_header:
        xml_str = re.sub(r'<\?[^>]+\?>', '', xml_str)
    tc = (r'A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF'
          r'\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F'
          r'\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD')
    xml_str = re.sub(r'<(?![%s/])' % tc, '&lt;', xml_str).strip()
    if xml_str.startswith("&lt;?xml"): xml_str = "<" + xml_str[4:]
    if need_fix_st:
        if not xml_str.strip().startswith("<string_table>"):
            xml_str = "<string_table>" + xml_str + "</string_table>"
        xml_str = re.sub(r"</string_table>[\s\S]+", "</string_table>", xml_str)
    return xml_str


def _generate_text_xml(filepath: str, texts: Dict[str, str]):
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<string_table>']
    for tid, tcontent in texts.items():
        safe_id = _escape_xml_content(tid)
        safe_text = '\n'.join(
            _split_text_at_length(_escape_xml_content(tcontent), 1000))
        lines.append(f'\t<string id="{safe_id}">')
        lines.append(f'\t\t<text>{safe_text}</text>')
        lines.append('\t</string>')
    lines.append('</string_table>')
    with open(filepath, "w", encoding="utf-8") as f:
        f.write('\n'.join(lines) + '\n')


def _generate_output_file(filepath: str, text: str, encoding: str = "utf-8",
                          add_xml_header: bool = False):
    if add_xml_header and not text.strip().startswith("<?xml"):
        text = '<?xml version="1.0" encoding="utf-8"?>\n' + text.strip()
    with open(filepath, "w", encoding=encoding) as f:
        f.write(text)


def _parse_cfgxml(filepath: str, quiet: bool = False) -> Tuple[str, Set[str], str]:
    whole_text, success_enc = read_text_file(filepath)
    whole_text = _normalize_xml_string(whole_text, need_fix_st=False, delete_header=False)
    return (whole_text, _get_config_xml_texts(whole_text), success_enc)


def _local_read_text_file(path):
    """自包含回退 (与 toolkit.read_text_file 相同)."""
    for i, enc in enumerate(DEFAULT_ENCODINGS):
        try:
            with open(path, "r", encoding=enc,
                      errors="ignore" if i == len(DEFAULT_ENCODINGS) - 1 else "strict") as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def _parse_script(filepath: str, quiet: bool = False) -> Tuple[str, Set[str]]:
    whole_text = None
    for i, enc in enumerate(DEFAULT_ENCODINGS):
        try:
            flag = (i == len(DEFAULT_ENCODINGS) - 1)
            with open(filepath, "r", encoding=enc,
                      errors="ignore" if flag else "strict") as f:
                whole_text = f.read()
            if not quiet:
                print(f"  [{'FORCED ' if flag else ''}{enc}] {filepath}")
            break
        except UnicodeDecodeError:
            if not quiet: print(f"  [NOT {enc}] {filepath}")
    if whole_text is None:
        raise ValueError(f"Cannot decode {filepath}")
    return (whole_text, _get_script_texts(whole_text))


# ============================================================================
#  提取核心
# ============================================================================

def _extract_gameplay(src: str, dst: str, id_prefix: str, verbose: bool = True) -> dict:
    extracted, counter, fc, cc = {}, 0, 0, 0
    sp, tp = Path(src), Path(dst)
    for f in sorted(sp.rglob("*.xml")):
        rel = f.relative_to(sp)
        if any(p.startswith("translated_") or p == "text" for p in rel.parts):
            continue
        try:
            wt, cands, enc = _parse_cfgxml(str(f), quiet=not verbose)
        except Exception as e:
            if verbose: print(f"  SKIP {rel}: {e}")
            continue
        fc += 1; repls = {}
        for c in cands:
            if not c.strip() or _does_text_look_like_id(c): continue
            eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
            extracted[eid] = c; repls[c] = eid
            if verbose: print(".", end="", flush=True)
        out = tp / rel; out.parent.mkdir(parents=True, exist_ok=True)
        _generate_output_file(str(out),
                              _replace_from_text(wt, repls) if repls else wt,
                              encoding=enc)
        if verbose and not repls: print(f"  [0] {rel}")
    if verbose: print(f"\n  gameplay: {fc} files, {counter} strings, {cc} chars")
    return extracted


def _extract_scripts(src: str, dst: str, id_prefix: str, verbose: bool = True) -> dict:
    extracted, counter, fc, cc = {}, 0, 0, 0
    sp, tp = Path(src), Path(dst)
    for f in sorted(sp.rglob("*.script")):
        rel = f.relative_to(sp)
        if any(p.startswith("translated_") for p in rel.parts): continue
        try:
            wt, cands = _parse_script(str(f), quiet=not verbose)
        except Exception as e:
            if verbose: print(f"  SKIP {rel}: {e}")
            continue
        fc += 1; repls = {}
        for cq in cands:
            qc = cq[0]; c = cq[1:-1]
            if _does_text_look_like_id(c) or _does_text_look_like_script(c): continue
            eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
            extracted[eid] = c
            old = qc + _escape_literal_text(c, quote=qc) + qc
            repls[old] = f'{SCRIPT_TRANSLATE_FUNC}("{eid}")'
            if verbose: print(".", end="", flush=True)
        out = tp / rel; out.parent.mkdir(parents=True, exist_ok=True)
        _generate_output_file(str(out),
                              _replace_from_text(wt, repls) if repls else wt)
        if verbose and not repls: print(f"  [0] {rel}")
    if verbose: print(f"\n  scripts: {fc} files, {counter} strings, {cc} chars")
    return extracted


def run_extraction(source: str, target: str = "", prefix: str = "mod",
                   clean: bool = False, log_callback=None) -> dict:
    """提取文本. 一次性仅处理 gameplay 或 scripts 其中之一.
    target 为空 = 原地: 新文件写回源子目录, 提取 xml 放源根.
    target 有值 = 输出目录: 新建 gameplay/scripts 放新文件, xml 直接放输出根."""
    def log(msg):
        if log_callback: log_callback(msg)

    source = os.path.abspath(source)
    if not os.path.isdir(source):
        raise FileNotFoundError(f"Source not found: {source}")

    # 识别类型: 源目录本身是 gameplay/scripts, 或父目录含其一 (两者都有则拒绝)
    base = os.path.basename(source).lower()
    if base in ("gameplay", "scripts"):
        ftype = base
        src_sub = source
    else:
        subs = [s for s in ("gameplay", "scripts") if os.path.isdir(os.path.join(source, s))]
        if not subs:
            raise ValueError("源目录中未找到 gameplay 或 scripts 子目录")
        if len(subs) > 1:
            raise ValueError("仅支持一次性处理 gameplay 或 scripts 其中之一")
        ftype = subs[0]
        src_sub = os.path.join(source, ftype)

    # 输出布局
    if not target:
        out_root = source          # xml 放源根
        dst_sub = src_sub          # 新文件原地替换
        log("未指定输出目录: 原地替换, xml 输出到源目录")
    else:
        target = os.path.abspath(target)
        out_root = target          # xml 放输出根
        dst_sub = os.path.join(target, ftype)
        os.makedirs(dst_sub, exist_ok=True)
        log(f"输出: {dst_sub}/ 新文件 + {prefix}_{ftype}_texts.xml → {out_root}")

    ts = int(time.time())
    id_pre = f"sgtat_{prefix}_{ftype[:2]}_{ts}"
    log(f"ID 前缀: {id_pre}")

    stats = {"gp_files": 0, "gp_strings": 0, "gp_chars": 0,
             "sc_files": 0, "sc_strings": 0, "sc_chars": 0}
    if ftype == "gameplay":
        log("提取 gameplay 配置文本...")
        gp = _extract_gameplay(src_sub, dst_sub, id_pre, verbose=False)
        if gp:
            _generate_text_xml(os.path.join(out_root, f"{prefix}_gameplay_texts.xml"), gp)
            log(f"  gameplay: {len(gp)} 条 → {prefix}_gameplay_texts.xml")
        stats["gp_strings"] = len(gp)
        stats["gp_chars"] = sum(len(v) for v in gp.values())
        stats["gp_files"] = sum(1 for _ in Path(dst_sub).rglob("*.xml"))
    else:
        log("提取 scripts 脚本文本...")
        sc = _extract_scripts(src_sub, dst_sub, id_pre, verbose=False)
        if sc:
            _generate_text_xml(os.path.join(out_root, f"{prefix}_scripts_texts.xml"), sc)
            log(f"  scripts: {len(sc)} 条 → {prefix}_scripts_texts.xml")
        stats["sc_strings"] = len(sc)
        stats["sc_chars"] = sum(len(v) for v in sc.values())
        stats["sc_files"] = sum(1 for _ in Path(dst_sub).rglob("*.script"))

    stats["total"] = stats["gp_strings"] + stats["sc_strings"]
    stats["total_chars"] = stats["gp_chars"] + stats["sc_chars"]
    stats["target"] = out_root
    log(f"完成。总计 {stats['total']} 条文本（{stats['total_chars']:,} 字符）。")
    return stats


# ============================================================================
#  GUI — VS Code Dark+ 风格
# ============================================================================



class TextExtractApp:
    def __init__(self, root):
        self.root = root
        if isinstance(root, tk.Tk):
            self.root.title("STALKER 文本提取器")
            self.root.geometry("780x620")
            self.root.minsize(680, 520)
        self.root.configure(bg=color("bg"))
        self.source_path = tk.StringVar()
        self.target_path = tk.StringVar()
        self.prefix_var = tk.StringVar(value="gs")
        self.clean_var = tk.BooleanVar(value=True)  # 兼容: 旧属性 (已无 UI, 提取默认不清理)
        self.running = False
        apply_theme()
        self._build_ui()
        self._ui = _make_pump(self.root)
        self._setup_drag_drop()

    def _apply_theme(self):
        """统一配色模板: 全部由 toolkit.apply_theme 提供."""
        apply_theme()
    def _setup_drag_drop(self):
        try:
            import tkinterDnD
            if hasattr(self.root, "drop_target_register"):
                self.root.drop_target_register("DND_Files")
                self.root.dnd_bind("<<Drop>>", self._on_drop)
        except ImportError:
            pass

    def _on_drop(self, event):
        data = event.data
        paths = data.strip().split() if isinstance(data, str) else [data]
        for p in paths:
            p = p.strip("{}")
            if os.path.isdir(p):
                if not self.source_path.get():
                    self.source_path.set(os.path.normpath(p))
                elif not self.target_path.get():
                    self.target_path.set(os.path.normpath(p))
                break

    def _on_drop_source(self, event):
        """拖拽文件夹到源目录框."""
        path = event.data.strip("{}").strip()
        if os.path.isdir(path):
            self.source_path.set(os.path.normpath(path))

    def _on_drop_target(self, event):
        """拖拽文件夹到输出目录框."""
        path = event.data.strip("{}").strip()
        if os.path.isdir(path):
            self.target_path.set(os.path.normpath(path))

    def _build_dir_row(self, parent, label_text, var, browse_cmd, drop_cmd=None):
        """统一目录行 (toolkit.dir_row): 标签 + 输入框(边框) + 浏览 + 拖拽."""
        ttk.Label(parent, text=label_text).pack(anchor=tk.W)
        dir_row(parent, "", var, browse=browse_cmd, width=0, drop=drop_cmd)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        # ═══ 可调分区: 上部操作区 / 下部日志统计区 ═══
        self._paned = SplitPane(main, orient=tk.VERTICAL)
        self._paned.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        upper = ttk.Frame(self._paned)
        lower = ttk.Frame(self._paned)
        self._paned.add(upper, weight=3)
        self._paned.add(lower, weight=1)

        tr = ttk.Frame(upper); tr.pack(fill=tk.X, pady=(0, 10))
        tool_header(tr, "STALKER 文本提取", side=tk.LEFT, padx=0, pady=0)
        ttk.Label(tr, text="cfgxml + scriptE  ·  纯提取",
                  style="Dim.TLabel").pack(side=tk.RIGHT)

        self._build_dir_row(upper, "源目录",
                            self.source_path, lambda: self._browse(self.source_path),
                            self._on_drop_source)
        self._build_dir_row(upper, "输出目录",
                            self.target_path, lambda: self._browse(self.target_path),
                            self._on_drop_target)

        or_ = ttk.Frame(upper); or_.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(or_, text="前缀").pack(side=tk.LEFT)
        ttk.Entry(or_, textvariable=self.prefix_var, width=8).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(or_, text="  输出: {prefix}_gameplay_texts.xml + {prefix}_scripts_texts.xml",
                  style="Dim.TLabel").pack(side=tk.LEFT, padx=(16, 0))

        br = ttk.Frame(upper); br.pack(fill=tk.X, pady=(0, 4))
        self.extract_btn = ttk.Button(br, text="▶  提取文本", style="Accent.TButton",
                                       command=self._start)
        self.extract_btn.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(upper, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 8))

        ttk.Separator(lower, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        self.log_lf, self.log = log_section(lower, "日志", height=4)
        self._tag_map = {"success": "ok", "error": "err"}

        self.stats_frame = ttk.LabelFrame(lower, text=" 统计 ", padding=12)
        self.stats_frame.pack(fill=tk.X, pady=(8, 0))
        inner = ttk.Frame(self.stats_frame); inner.pack(fill=tk.X)
        labels = [("gameplay", "gp_stat", "gp_detail"),
                  ("scripts", "sc_stat", "sc_detail"),
                  ("总计", "total_stat", "total_detail")]
        for i, (title, stat_attr, detail_attr) in enumerate(labels):
            if i > 0:
                ttk.Separator(inner, orient=tk.VERTICAL).pack(
                    side=tk.LEFT, fill=tk.Y, padx=20)
            col = ttk.Frame(inner); col.pack(side=tk.LEFT, expand=True)
            ttk.Label(col, text=title, style="Dim.TLabel").pack()
            lbl = ttk.Label(col, text="—", style="Stats.TLabel"); lbl.pack()
            setattr(self, stat_attr, lbl)
            det = ttk.Label(col, text="", style="Dim.TLabel"); det.pack()
            setattr(self, detail_attr, det)

        st = ttk.Frame(main); st.pack(fill=tk.X, pady=(6, 0))
        self.status_lbl = ttk.Label(st, text="就绪", style="Green.TLabel")
        self.status_lbl.pack(side=tk.LEFT)
        ttk.Label(st, text="提取后可拖入 Hana 翻译", style="Dim.TLabel").pack(side=tk.RIGHT)

    def _browse(self, var):
        p = filedialog.askdirectory()
        if p: var.set(os.path.normpath(p))

    def _log(self, msg, tag="info"):
        self.log.add(msg, self._tag_map.get(tag, tag))

    def _clear_log(self):
        self.log.clear()

    def _start(self):
        src = self.source_path.get().strip()
        dst = self.target_path.get().strip()
        pfx = self.prefix_var.get().strip() or "mod"
        if not src: messagebox.showwarning("提示", "请指定源目录"); return
        if not os.path.isdir(src):
            messagebox.showerror("错误", f"源目录不存在：\n{src}"); return
        # 类型预检: 源目录本身是 gameplay/scripts, 或父目录含其一 (两者都有则拒绝)
        base = os.path.basename(src).lower()
        if base not in ("gameplay", "scripts"):
            subs = [s for s in ("gameplay", "scripts") if os.path.isdir(os.path.join(src, s))]
            if not subs:
                messagebox.showwarning("提示", "源目录中未找到 gameplay 或 scripts 子目录。"); return
            if len(subs) > 1:
                messagebox.showwarning("提示", "仅支持一次性处理 gameplay 或 scripts 其中之一。"); return
        if self.running: return
        self.running = True
        self.extract_btn.config(state=tk.DISABLED, text="提取中...")
        self.progress.start(10)
        self.status_lbl.config(text="正在提取...", style="Yellow.TLabel")
        for attr in ["gp_stat", "sc_stat", "total_stat", "gp_detail", "sc_detail", "total_detail"]:
            getattr(self, attr).config(text="..." if "stat" in attr else "")
        self._clear_log()
        self._log("═══ 开始提取 ═══", "dim")
        self._log(f"源: {src}")
        self._log(f"输出: {dst or '(未指定, 原地替换)'}")
        self._log(f"前缀: {pfx}"); self._log("")

        def worker():
            try:
                sts = run_extraction(src, dst, pfx, False,
                                     log_callback=lambda m: self._ui(self._log, m))
                self._ui(self._on_done, sts, None)
            except Exception as e:
                self._ui(self._on_done, None, str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, stats, error):
        self.running = False; self.progress.stop()
        self.extract_btn.config(state=tk.NORMAL, text="▶  提取文本")
        if error:
            self._log(f"✕ 错误: {error}", "error")
            self.status_lbl.config(text="提取失败", style="Red.TLabel"); return
        self._log("", "dim"); self._log("═══ 完成 ═══", "success")
        self.gp_stat.config(text=str(stats["gp_strings"]))
        self.gp_detail.config(text=f"{stats['gp_files']} 文件 · {stats['gp_chars']:,} 字符")
        self.sc_stat.config(text=str(stats["sc_strings"]))
        self.sc_detail.config(text=f"{stats['sc_files']} 文件 · {stats['sc_chars']:,} 字符")
        self.total_stat.config(text=str(stats["total"]))
        self.total_detail.config(text=f"{stats['total_chars']:,} 字符")
        pfx = self.prefix_var.get().strip() or "mod"
        self._log(f"产物: {stats['target']}", "success")
        self._log(f"  {pfx}_gameplay_texts.xml", "success")
        self._log(f"  {pfx}_scripts_texts.xml", "success")
        self.status_lbl.config(text=f"完成 · {stats['total']} 条文本", style="Green.TLabel")


# ============================================================================
#  CLI
# ============================================================================

# ═══ XML 校对 ═══
ID_PATTERN = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

# 原版 XML 常见格式缺陷: 未转义的 &、<，以及 <!-- 后多余的 -
_AMP_BAD = re.compile(rb'&(?!amp;|lt;|gt;|quot;|apos;|#x?[0-9a-fA-F]+;)')
_LT_BAD = re.compile(rb'<(?![!/?a-zA-Z])')
_COMMENT_BAD = re.compile(rb'<!--(-+)')


