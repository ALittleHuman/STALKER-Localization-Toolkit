# -*- coding: utf-8 -*-
"""
汉化包生成工具 GUI — CN_Pack_Generator 的 Python 重写
从汉化 XML 生成 X-Ray 字库纹理 + 完整 gamedata 汉化包
依赖: Pillow (自动安装), 微软雅黑字体
"""
import os, sys, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
from font_pack import GAMES, ensure_pillow, build_package

# ─── 主题/字体: 统一取自 toolkit (单一来源) ───
from toolkit import log_section, color, T as _T, LogBox
BG, BG2, BG3 = _T["bg"], _T["surface"], _T["surface2"]
FG, FG_DIM = _T["text"], _T["text_dim"]
ACCENT, BORDER = _T["accent"], _T["border"]
GREEN, RED, YELLOW = _T["green"], _T["red"], _T["yellow"]
MONO, UI = _T["font_mono"], _T["font"]


def dpi_setup():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class App:
    def __init__(self, root):
        self.root = root
        if isinstance(root, tk.Tk):
            root.title("汉化包生成工具 (CN_Pack_Generator 重写)")
            root.geometry("860x640")
            root.minsize(760, 560)
        root.configure(bg=BG)

        self.running = False
        self._build_ui()
        self._log("就绪。选择汉化 XML 目录后点击生成。", "dim")

    # ─── UI ───
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root); top.pack(fill="x", **pad)

        # 配置行
        row1 = ttk.Frame(top); row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="游戏版本:").pack(side="left")
        self.game_var = tk.StringVar(value="SoC")
        g = ttk.OptionMenu(row1, self.game_var, "SoC", *GAMES.keys())
        g.config(width=6); g.pack(side="left", padx=(4, 16))

        # 加载语言: eng/rus/chs/自定义 (自定义才显示输入框)
        ttk.Label(row1, text="加载语言:").pack(side="left")
        lang_box = ttk.Frame(row1); lang_box.pack(side="left", padx=(4, 16))
        self.lang_sel = tk.StringVar(value="chs")
        self.lang_entry = tk.StringVar(value="chs")
        om = ttk.OptionMenu(lang_box, self.lang_sel, "chs", "eng", "rus", "chs", "自定义",
                            command=self._lang_changed)
        om.config(width=6); om.pack(side="left")
        self.lang_entry_box = tk.Entry(lang_box, textvariable=self.lang_entry, width=6,
                                       bg=_T["entry_bg"], fg=FG, insertbackground=FG,
                                       relief="flat", bd=0, highlightthickness=1,
                                       highlightbackground=BORDER, highlightcolor=ACCENT, font=UI)
        self.lang_entry_box.pack_forget()  # 默认隐藏, 切自定义才显示

        # 尺寸
        ttk.Label(row1, text="尺寸:").pack(side="left")
        self.off_var = tk.StringVar(value="标准")
        om = ttk.OptionMenu(row1, self.off_var, "标准", "标准", "+3", "+5", "+7", "+9")
        om.config(width=4); om.pack(side="left", padx=(4, 16))

        # 字体后缀: 无/_chs/自定义 (自定义才显示输入框)
        ttk.Label(row1, text="后缀:").pack(side="left")
        suf_box = ttk.Frame(row1); suf_box.pack(side="left", padx=(4, 16))
        self.suf_sel = tk.StringVar(value="无")
        self.suf_entry = tk.StringVar(value="")
        om = ttk.OptionMenu(suf_box, self.suf_sel, "无", "无", "_chs", "自定义",
                            command=self._suf_changed)
        om.config(width=6); om.pack(side="left")
        self.suf_entry_box = tk.Entry(suf_box, textvariable=self.suf_entry, width=6,
                                      bg=_T["entry_bg"], fg=FG, insertbackground=FG,
                                      relief="flat", bd=0, highlightthickness=1,
                                       highlightbackground=BORDER, highlightcolor=ACCENT, font=UI)
        self.suf_entry_box.pack_forget()  # 默认隐藏

        self.cyr_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row1, text="完整西里尔(默认关=严格兼容原版)", variable=self.cyr_var).pack(side="left")

        # 路径行 (统一 toolkit.path_row)
        from toolkit import dir_row as _dir_row
        self.xml_var = tk.StringVar()
        self.font_var = tk.StringVar()
        self.out_var = tk.StringVar()
        _dir_row(top, "XML目录:", self.xml_var, browse=self._browse_xml)
        _dir_row(top, "字体文件:", self.font_var, browse=self._browse_font)
        _dir_row(top, "输出目录:", self.out_var, browse=self._browse_out)

        # 默认字体: 工具目录 msyh.ttf, 否则系统雅黑
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "msyh.ttf")
        if os.path.exists(local):
            self.font_var.set(local)
        else:
            for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf",
                         r"C:\Windows\Fonts\msyhl.ttc"):
                if os.path.exists(cand):
                    self.font_var.set(cand); break

        # 按钮行
        row3 = ttk.Frame(top); row3.pack(fill="x", pady=(6, 0))
        self.gen_btn = ttk.Button(row3, text="生成汉化包", command=self._generate)
        self.gen_btn.pack(side="left")
        ttk.Button(row3, text="打开输出目录", command=self._open_out).pack(side="left", padx=(8, 0))
        self.status_lbl = tk.Label(row3, text="", bg=BG, fg=GREEN, font=UI)
        self.status_lbl.pack(side="right")

        # 日志 (统一 log_section)
        self.log_lf, self.log = log_section(self.root, "日志", height=12)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(0, 8))

    # ─── 逻辑 ───
    @staticmethod
    def _placeholder(entry, var, text="自定义"):
        """Entry 水印: 空时显示灰色隐字, 聚焦清空; 返回是否处于水印态."""
        st = {"ph": False}
        def show():
            st["ph"] = True
            entry.delete(0, "end")
            entry.insert(0, text)
            entry.configure(foreground=FG_DIM)
        def on_focus_in(e):
            if st["ph"]:
                entry.delete(0, "end")
                var.set("")
                entry.configure(foreground=FG)
            st["ph"] = False
        def on_focus_out(e):
            if not var.get().strip():
                show()
            else:
                st["ph"] = False
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)
        if not var.get().strip():
            show()
        return st

    def _lang_changed(self, val):
        if val == "自定义":
            self.lang_entry.set("")
            self._lang_ph = self._placeholder(self.lang_entry_box, self.lang_entry, "自定义")
            self.lang_entry_box.pack(side="left", padx=(2, 0))
        else:
            self.lang_entry.set(val)
            self.lang_entry_box.pack_forget()

    def _suf_changed(self, val):
        if val == "自定义":
            self.suf_entry.set("")
            self._suf_ph = self._placeholder(self.suf_entry_box, self.suf_entry, "自定义")
            self.suf_entry_box.pack(side="left", padx=(2, 0))
        elif val == "_chs":
            self.suf_entry.set("_chs")
            self.suf_entry_box.pack_forget()
        else:  # 无
            self.suf_entry.set("")
            self.suf_entry_box.pack_forget()

    def _log(self, msg, tag=None):
        self.root.after(0, lambda: self.log.add(msg, tag))

    def _browse_xml(self):
        d = filedialog.askdirectory(title="选择汉化 XML 目录 (xmlfiles)")
        if d: self.xml_var.set(d)

    def _browse_font(self):
        f = filedialog.askopenfilename(title="选择字体文件",
                                       filetypes=[("TrueType", "*.ttf *.ttc"), ("所有文件", "*.*")])
        if f: self.font_var.set(f)

    def _browse_out(self):
        d = filedialog.askdirectory(title="选择输出目录 (将生成 gamedata 子文件夹)")
        if d: self.out_var.set(d)

    def _open_out(self):
        d = self.out_var.get().strip()
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa
        else:
            messagebox.showwarning("提示", "输出目录无效")

    def _generate(self):
        if self.running: return
        xml_dir = self.xml_var.get().strip()
        font = self.font_var.get().strip()
        out = self.out_var.get().strip()
        # 加载语言
        if self.lang_sel.get() == "自定义":
            lang = self.lang_entry.get().strip()
            if not lang or getattr(self, "_lang_ph", {}).get("ph"):
                messagebox.showwarning("缺少语言", "自定义加载语言不能为空"); return
        else:
            lang = self.lang_sel.get()
        # 字体后缀
        if self.suf_sel.get() == "自定义":
            suffix = self.suf_entry.get().strip()
            if not suffix or getattr(self, "_suf_ph", {}).get("ph"):
                messagebox.showwarning("缺少后缀", "自定义后缀不能为空"); return
        else:
            suffix = "" if self.suf_sel.get() == "无" else self.suf_sel.get()
        if not xml_dir or not os.path.isdir(xml_dir):
            messagebox.showwarning("缺少输入", "请选择汉化 XML 目录"); return
        if not font or not os.path.exists(font):
            messagebox.showwarning("缺少字体", "请选择 TrueType 字体文件 (如 msyh.ttf)"); return
        if not out:
            messagebox.showwarning("缺少输出", "请选择输出目录"); return
        if not ensure_pillow():
            messagebox.showerror("依赖缺失", "Pillow 安装失败，无法渲染字体"); return

        self.running = True
        self.gen_btn.configure(state="disabled")
        self.progress.start(12)
        self.status_lbl.configure(text="生成中...", foreground=YELLOW)
        game = self.game_var.get()
        off_txt = self.off_var.get()
        offset = int(off_txt[1:]) if off_txt.startswith("+") else 0
        full_cyr = self.cyr_var.get()
        self._log(f"开始生成: GAME={game}, 加载语言={lang}, 后缀={suffix!r}, 尺寸=+{offset}, 完整西里尔={full_cyr}", "hdr")

        def work():
            try:
                build_package(game, lang, xml_dir, font, out, suffix=suffix,
                              offset=offset, full_cyrillic=full_cyr, log=self._log)
                self.root.after(0, lambda: self.status_lbl.configure(text="完成", foreground=GREEN))
            except Exception as e:
                self._log(f"错误: {e}", "err")
                self.root.after(0, lambda: self.status_lbl.configure(text="失败", foreground=RED))
            self.root.after(0, self._done)

        threading.Thread(target=work, daemon=True).start()

    def _done(self):
        self.running = False
        self.gen_btn.configure(state="normal")
        self.progress.stop()


def main():
    dpi_setup()
    root = tk.Tk()
    from toolkit import apply_theme
    apply_theme()

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
