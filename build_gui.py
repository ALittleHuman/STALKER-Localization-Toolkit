# -*- coding: utf-8 -*-
"""构建器界面（build GUI）。

设计目标：
    * **不重写构建逻辑** —— 只是 `build.py` 的界面外壳，构建仍走同一函数，
      因此命令行与界面产出的东西完全一致。
    * **复用现成控件** —— 主题、按钮、输入框、日志框、分栏、标签全部取自 toolkit，
      不在界面里手写配色（否则会被 toolkit_guard 拦下）。
    * 版本号支持 **ALPHA / BETA / RC** 等自定义标记；基础版本写回
      `toolkit_base.APP_VERSION`（与命令行 `--version` 同一实现）。
    * 预发布标记的**序号自动 +1**（`VER.next_prerelease()`，按 (完整版本串, 标记名)
      各自计数）。界面上**手改过**标记就切换成"手动优先、计数不动"，这条规则
      写在「当前」框的"下次标记"那一栏里，不做隐藏规则。

运行: python build_gui.py
"""
import os
import queue
import subprocess
import sys
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from toolkit import (
    color, apply_theme, apply_tk_defaults, apply_titlebar, load_user_theme,
    set_app_icon, APP_NAME, px, sync_tk_scaling,
    tool_header, tool_text, tool_label, tool_button, themed_entry,
    LogBox, status_style, SplitPane, open_in_explorer,
)
from toolkit_platform import hidden_kwargs
import toolkit_version as VER

CHANNELS = ["无", "ALPHA", "BETA", "RC"]


class BuildGUI:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self._q = queue.Queue()
        self._lines = 0
        # 标记是否已被用户**手动**接手：
        #   False = 自动（默认）—— 序号由 VER.next_prerelease() 递增，构建时不自增两遍；
        #   True  = 手动 —— 界面上填的值优先，并且**不推进计数**（与命令行
        #           `--prerelease` 同一条规矩：手工输入优先）。
        # 为什么用开关而不是"比较值有没有变"：用户可能就想手填回 ALPHA.2（= 已保存值），
        # 按值比较会把这种明确的手工意图误判成"自动"，于是序号被悄悄 +1。
        self.var_marker_manual = False
        # 程序化回填标记字段期间置 True：trace 回调据此区分"用户在改"与"我们在回填"
        self._syncing_marker = False

        root.title(f"{APP_NAME} — 构建器")
        set_app_icon(root)
        # 缩放必须在使用 px() 之前同步（apply_tk_defaults 里那次排在 geometry 之后）
        sync_tk_scaling(root)
        # 尺寸按当前缩放换算（geometry/minsize 是**物理像素**）：写死 980x680
        # 在 150% 屏上只有 653x453 逻辑像素，窗口会明显偏小。
        root.geometry(f"{px(980)}x{px(680)}")
        root.minsize(px(820), px(560))
        root.configure(bg=color("bg"))
        # 与 Hub 用同一套主题来源与调用顺序：apply_theme → apply_tk_defaults
        # （后者内部 sync_tk_scaling 并重刷样式）→ apply_titlebar。
        mode = load_user_theme()
        apply_theme(mode)
        apply_tk_defaults(root, mode)
        # 标题栏跟随主题：构建器有自己的根窗口，以前漏了这一句，于是在暗色主题下
        # 顶着一条亮色标题栏（Hub 有调、这里没有 —— 就是没统一的地方）。
        apply_titlebar(root, mode)

        self._build_ui()
        self._refresh_current()

    # ── 界面 ────────────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 14}

        tool_header(self.root, "构建器（PyInstaller onedir）")
        # 原先还写着"构建逻辑与 build.py 完全一致" —— 那是给维护者看的一致性说明，
        # 对使用构建器的人没有决策价值，删掉；留在本文件 docstring 里。
        tool_text(self.root, "版本号、标记与构建计数都写回 toolkit_base.py（唯一事实来源）",
                  kind="dim", padx=14, pady=(0, 6))

        # ── 当前状态 ──
        cur = ttk.LabelFrame(self.root, text=" 当前 ", padding=8)
        cur.pack(fill="x", **pad)
        self.lbl_current = tool_label(cur, "", font_role="font_mono")
        self.lbl_current.pack(anchor="w")
        self.lbl_count = tool_label(cur, "", font_role="font_mono", fg_role="text_dim")
        self.lbl_count.pack(anchor="w")
        self.lbl_state = tool_label(cur, "就绪", font_role="font_mono")
        self.lbl_state.pack(anchor="w", pady=(4, 0))

        # ── 版本输入 ──
        ver = ttk.LabelFrame(self.root, text=" 版本号 ", padding=8)
        ver.pack(fill="x", **pad, pady=(8, 0))

        r1 = ttk.Frame(ver); r1.pack(fill="x")
        ttk.Label(r1, text="版本:", width=6).pack(side="left")
        self.var_version = tk.StringVar()
        self.ent_version = themed_entry(r1, textvariable=self.var_version)
        self.ent_version.pack(side="left", fill="x", expand=True, ipady=2)
        tool_button(r1, "解析", command=self._on_parse).pack(side="left", padx=(6, 0))

        r2 = ttk.Frame(ver); r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="标记:", width=6).pack(side="left")
        self.var_channel = tk.StringVar(value="无")
        self.cb_channel = ttk.Combobox(r2, textvariable=self.var_channel, values=CHANNELS,
                                       state="readonly", width=8)
        self.cb_channel.pack(side="left")
        # 用户一旦动过标记下拉/序号，就切到"手动"：那个值优先，计数不再自增
        # （见 _marker_args 与 _refresh_count_line —— 规则必须显示在界面上）
        self.cb_channel.bind("<<ComboboxSelected>>", lambda e: self._on_marker_pick())

        ttk.Label(r2, text="序号:", width=6).pack(side="left", padx=(10, 0))
        self.var_seq = tk.StringVar(value="1")
        self.ent_seq = themed_entry(r2, textvariable=self.var_seq, width=5)
        self.ent_seq.pack(side="left")
        self.var_seq.trace_add("write", lambda *a: self._on_seq_edit())

        self.lbl_preview = tool_label(r2, "", font_role="font_mono", fg_role="green")
        self.lbl_preview.pack(side="left", padx=(16, 0))

        # 「序号」框里显示的是**本次构建将使用的序号**（用户口径 2026-09-12）：
        # 自动模式下它就是 next_prerelease() 的 peek 值（= build.py 马上要写回、
        # 并拿去命名产物的那个号），而不是"上次已经构建过的号"。
        # 手工改过标记就以你填的为准：原样构建、计数不动。
        tool_text(ver, "序号 = 本次构建将使用的序号（构建前自动保存；自动模式 = 已保存值 +1）；"
                       "手改标记 = 原样构建、计数不动；构建失败会自动回退版本号与次数",
                  kind="dim", padx=0, pady=(4, 0))

        # ── 输出目录 ──
        out = ttk.LabelFrame(self.root, text=" 输出 ", padding=8)
        out.pack(fill="x", **pad, pady=(8, 0))
        r3 = ttk.Frame(out); r3.pack(fill="x")
        ttk.Label(r3, text="目录:", width=6).pack(side="left")
        self.var_out = tk.StringVar()
        self.ent_out = themed_entry(r3, textvariable=self.var_out)
        self.ent_out.pack(side="left", fill="x", expand=True, ipady=2)
        tool_button(r3, "浏览", command=self._browse_out, width=6).pack(side="left", padx=(6, 0))
        # 原先是两行说明（"留空=…（目录名不含版本号）" + "版本号跟在应用名后面，例如…"），
        # 合成一行：两条事实都保留，示例只留版本尾串，省掉重复应用名。
        tool_text(out, "留空 = 用 builds\\build_N（目录名不含版本号）；"
                       "内侧应用名带版本号，例 1.0.0 BETA.1",
                  kind="dim", padx=0, pady=(4, 0))

        # ── 日志 ──
        paned = SplitPane(self.root, orient="vertical")
        paned.pack(fill="both", expand=True, padx=14, pady=(8, 4))
        log_lf = ttk.LabelFrame(paned, text=" 构建输出 ", padding=4)
        paned.add(log_lf, weight=1)
        self.log = LogBox(log_lf, height=16, wrap="none")
        self.log.pack(fill="both", expand=True)

        # ── 操作栏 ──
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        # 「保存版本号与标记」按钮已删除（用户口径 2026-09-12）：它是**第二条写盘路径**，
        # 与"单一事实来源"冲突，而且"先保存再构建"的顺序会让人以为构建用的是别处的值。
        # 现在版本号/标记在**每次构建开始时自动保存**（见 build.py:main），
        # 失败还会自动回退 —— 于是"保存"这件事不再需要人记住。
        self.btn_build = tool_button(bar, "开始构建", command=self._on_build)
        self.btn_build.pack(side="left")
        self.btn_open = tool_button(bar, "打开产物目录", command=self._on_open_out)
        self.btn_open.pack(side="left", padx=(8, 0))
        self.btn_stop = tool_button(bar, "停止", command=self._on_stop)
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_stop.configure(state="disabled")

    # ── 状态 ───────────────────────────────────────────────
    def _set_status(self, text, kind="idle"):
        """状态语义 → 颜色统一走 status_style（不写得字面量色值）。"""
        self.lbl_state.configure(text=text, fg=status_style(kind))

    # ── 状态与预览 ─────────────────────────────────────────
    def _build_count(self):
        """已构建次数：读 `toolkit_base.BUILD_COUNT`（唯一来源，不再有第二个文件）。

        与 `build.py` 的 `next_build_dir()` 读的是**同一个**函数，因此界面显示
        "下次默认 build_N"和实际建出来的目录必然一致（不会一个文件一个数）。
        """
        return VER.current_build_count()

    def _refresh_current(self):
        base = VER.current_base_version()
        pre = VER.current_prerelease()
        self.lbl_current.configure(
            text=f"基础版本: {base}    标记: {pre or '无'}    完整: {VER.full_version()}"
                 f"    应用: {APP_NAME}")
        if not self.var_version.get():
            self.var_version.set(base)
        # 标记同样从已保存的值预填：否则每次打开构建器标记都重置成"无"，
        # 产物名（带标记）与界面/标题会对不上。
        # 预填只在"用户还没手动接手标记"时做；**每次刷新都同步**（而不是只同步一次）
        # 是为了自动模式下构建完能跟上刚写回的序号。
        if not self.var_marker_manual:
            # 序号显示的是**本次构建将使用的**那个号（用户口径 2026-09-12），
            # 也就是 build.py 马上要写回、并拿去命名产物的值（peek，不推进计数）。
            # 之前这里显示"已保存/上次构建过的"号，与旁边那行「下次标记」自相矛盾。
            nxt = self._next_auto_marker()
            if nxt:
                name, num = VER.split_prerelease(nxt)
                self._sync_marker_fields(name or "无", str(num) if num else "1")
            else:
                self._sync_marker_fields("无", "1")
        self._refresh_count_line()
        self._refresh_preview()

    def _sync_marker_fields(self, channel, seq):
        """程序化回填标记字段（不算"用户手动改过"，否则永远切不回自动模式）。"""
        self._syncing_marker = True
        try:
            self.var_channel.set(channel)
            self.var_seq.set(seq)
        finally:
            self._syncing_marker = False

    def _on_marker_pick(self):
        """用户选了标记下拉 → 从这一刻起"手动优先"（计数不再自增）。"""
        self.var_marker_manual = True
        self._refresh_preview()
        self._refresh_count_line()

    def _on_seq_edit(self, *_a):
        """序号输入框变化；程序化回填也会触发 trace，那种不算用户意图。"""
        if not self._syncing_marker:
            self.var_marker_manual = True
        self._refresh_preview()
        self._refresh_count_line()

    def _next_auto_marker(self):
        """自动模式下本次构建会用的标记（**只读**，不推进计数）。

        与 build.py 自增时调用的是**同一个** `VER.next_prerelease()`，因此界面显示
        什么、构建出来就是什么。consume=False：只是看一眼，否则每刷新一次界面
        就白涨一个序号（那才是真正的"看不见的副作用"）。
        base 取界面里的版本号：改了版本号就是新键 → 从 .1 重新数。
        """
        try:
            raw = self.var_version.get().strip()
            base = VER.parse_full_version(raw)[0] if raw else None
            return VER.next_prerelease(base_version=base, consume=False)
        except Exception:
            return ""

    def _refresh_count_line(self):
        """「当前」框第二行：构建编号 + **下一次会用到的标记**。

        自动/手动写在这里而不是藏着：手改的标记会原样构建且**计数器不动**，
        不写出来的话，"我明明填了 BETA.5，构建完序号却跳了/没跳"就是一条隐藏规则。
        """
        n = self._build_count()
        text = f"已构建次数(BUILD_COUNT): {n}    下次默认: build_{n + 1}"
        if self.var_marker_manual:
            text += f"    下次标记: {self._current_prerelease() or '无'}（手动：计数不动）"
        else:
            text += f"    下次标记: {self._next_auto_marker() or '无'}（自动递增）"
        self.lbl_count.configure(text=text)

    def _current_prerelease(self):
        ch = self.var_channel.get()
        if ch == "无":
            return ""
        seq = (self.var_seq.get() or "1").strip()
        return f"{ch}.{seq}" if seq.isdigit() else ch

    def _refresh_preview(self):
        try:
            full = VER.full_version(self.var_version.get() or None,
                                    self._current_prerelease())
            tup = VER.version_tuple(self.var_version.get() or None,
                                    self._current_prerelease())
            self.lbl_preview.configure(
                text=f"→ {full}   (资源版本 {'%d.%d.%d.%d' % tup})")
        except Exception:
            self.lbl_preview.configure(text="→ （版本号无效）", fg=status_style("err"))

    def _on_parse(self):
        """把用户粘贴的完整版本串（如 v1.0.0-beta.2）拆成基础版本 + 标记。"""
        raw = self.var_version.get().strip()
        base, pre = VER.parse_full_version(raw)
        if not base:
            messagebox.showwarning("无法解析", f"识别不出基础版本号：{raw!r}\n"
                                              "支持 1.0.0 / v1.0.0 / 1.0.0-beta.2")
            return
        # 粘贴完整版本串是"人明确指定了标记"（连"不带标记"也是明确指定的），
        # 因此切手动：这里给的标记原样构建，且计数不被推进。
        # 必须显式置位而不是靠 trace：粘贴 "1.0.2"（无标记）时序号字段可能压根没变。
        self.var_marker_manual = True
        self.var_version.set(base)
        if pre:
            name, _dot, num = pre.partition(".")
            self.var_channel.set(name)
            self.var_seq.set(num or "1")
        else:
            self.var_channel.set("无")
        self._refresh_preview()
        self._refresh_count_line()
        self._log_line(f"[解析] {raw} → 基础 {base}，标记 {pre or '无'}"
                       f"（手动：本次构建不推进计数）")

    # ── 日志 ───────────────────────────────────────────────
    def _log_line(self, text, tag="info"):
        self._lines += 1
        self.log.add("%4d | %s" % (self._lines, text), tag)

    # ── 保存版本号 ─────────────────────────────────────────
    # 已删除「保存版本号与标记」按钮与 `_on_save`：构建开始时会自动保存（build.py:main），
    # 失败自动回退。保留"保存"入口只会多一条能与构建不一致的写盘路径。

    # ── 构建 ───────────────────────────────────────────────
    def _browse_out(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.var_out.set(os.path.normpath(d))

    def _on_open_out(self):
        d = self.var_out.get().strip()
        if d and os.path.isdir(d):
            open_in_explorer(d)
        elif os.path.isdir(os.path.join(BASE, "builds")):
            open_in_explorer(os.path.join(BASE, "builds"))
        else:
            messagebox.showinfo("提示", "还没有构建产物目录。")

    def _on_stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                if sys.platform == "win32":
                    # 只 terminate 父进程会留下 PyInstaller 的子进程继续写产物目录，
                    # 因此连整棵进程树一起结束。
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                        capture_output=True, text=True,
                        encoding="utf-8", errors="replace", **hidden_kwargs(),
                    )
                else:
                    self.proc.terminate()
                self._set_status("已请求停止构建…", "warn")
                self._log_line("[停止] 已请求终止构建进程（含子进程）", "warn")
            except Exception as e:
                self._log_line(f"[停止] 失败: {e}", "err")

    def _marker_args(self):
        """本次构建要传给 build.py 的标记参数 —— 也是"由谁推进计数"的唯一分界。

        自动模式返回 []：**不传** --prerelease，让 build.py 自己用
        `VER.next_prerelease()` 自增并写回。推进点只有这一处，界面与命令行不会
        各推一次把序号一次涨两格；界面显示用的 `_next_auto_marker()` 是同一个
        函数的只读调用，所以"显示的"就是"构建用掉的"。

        手动模式返回 ["--prerelease", 值]：显式给出即"原样使用、不动计数"。
        值可能是空串（用户选了「无」）—— 空串也**必须显式传**：不传的话
        build.py 会把已保存的标记自动 +1 用上，正好和"不要标记"相反。
        """
        if not self.var_marker_manual:
            return []
        return ["--prerelease", self._current_prerelease()]

    def _on_build(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("正在构建", "已有构建在进行中。")
            return

        version = self.var_version.get().strip()
        base, _pre = VER.parse_full_version(version)
        if not base:
            messagebox.showwarning("版本号无效", f"请填写形如 1.0.0 的版本号（当前 {version!r}）")
            return
        out = self.var_out.get().strip()

        marker_args = self._marker_args()
        # 本次实际会用的标记：手动就是界面里的值；自动是"将要被 build.py 写回的值"
        # （peek，不推进计数），用它只为了把日志写对。
        eff_pre = marker_args[1] if marker_args else self._next_auto_marker()

        cmd = [sys.executable, os.path.join(BASE, "build.py"),
               "--version", base]
        cmd += marker_args
        if out:
            cmd += ["--out", out]

        self._lines = 0
        self._log_line("命令: " + " ".join(cmd), "hdr")
        self._log_line("版本: " + VER.full_version(base, eff_pre)
                       + f"  → 基础版本将写回 toolkit_base.APP_VERSION = {base}", "hdr")
        self._log_line(
            f"标记: {eff_pre or '无'}"
            + ("（手动指定：原样使用，计数器不动）" if marker_args
               else "（自动递增：由 build.py 按 (版本, 标记) 计数 +1）"), "hdr")

        self.btn_build.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._set_status("构建中…（PyInstaller 可能需要几分钟）", "running")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except Exception as e:
            self._log_line(f"[失败] 无法启动构建: {e}", "err")
            self._set_status("无法启动构建", "err")
            self.btn_build.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            return

        threading.Thread(target=self._pump, daemon=True).start()
        self.root.after(100, self._poll)

    def _pump(self):
        """后台线程：把子进程输出塞进队列（不在工作线程碰任何控件）。"""
        try:
            for line in self.proc.stdout:
                self._q.put(line.rstrip("\n"))
        except Exception:
            pass
        finally:
            self._q.put(None)

    def _poll(self):
        """主线程：排空队列、刷新日志；进程结束后复位按钮。"""
        done = False
        while True:
            try:
                line = self._q.get_nowait()
            except queue.Empty:
                break
            if line is None:
                done = True
                break
            tag = "err" if ("error" in line.lower() or "traceback" in line.lower()) else "info"
            if line.startswith(("Build complete", "Version:", "Output:", "Exe:")):
                tag = "ok"
            # build.py 的事务收尾行：失败/回退/快照恢复都要看得见（红/黄），
            # 否则"构建失败了但版本号已经回退"这件事在界面上完全没有痕迹。
            if line.startswith(("[FAIL]", "[回退]", "注意：")):
                tag = "err"
            elif line.startswith(("[恢复]", "[OK]")):
                tag = "warn"
            self._log_line(line, tag)

        if done:
            code = self.proc.poll() if self.proc else None
            if code == 0:
                self._log_line("=== 构建成功 ===", "ok")
                self._set_status("构建成功", "ok")
            else:
                self._log_line(f"=== 构建失败，退出码 {code} ===", "err")
                self._log_line("版本号与构建次数已回退到构建前；失败现场在 builds\\FAIL",
                               "err")
                self._set_status("构建失败（已回退，现场见 builds\\FAIL）", "err")
            self.btn_build.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self._refresh_current()
            return
        self.root.after(120, self._poll)


def main():
    root = tk.Tk()
    BuildGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
