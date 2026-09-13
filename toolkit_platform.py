# -*- coding: utf-8 -*-
"""STALKER 汉化工具集 — 平台与外部程序（能力 4）

把原先散在各 App 里的"平台相关"样板收拢到一处：
    * 用户设置文件 user.ltx 的读写（`load_user_value` / `save_user_values`）
    * 应用配置文件读写（app_dir() 下的 <name>.cfg.json）
    * 外部程序定位（配置 → 应用目录 → 常见安装位置 → PATH）
    * 隐藏窗口地运行外部程序（Windows CREATE_NO_WINDOW）

设计约束：
    * 只依赖 toolkit_paths.app_dir（**Tk 无关**：本模块的 user.ltx / 配置读写要被
      非 Tk 后端复用（Qt 试点读主题设置），所以不能经 toolkit_base 把 tkinter 拉进来）。
      与日志/主题/组件方向相反，无人依赖本模块的 UI。
    * 查找函数**不写盘**（纯函数）；要记住结果由调用方显式调用 save_app_config。
      这一点是刻意的：库函数不应有"读一下配置就改了用户磁盘"的隐藏副作用。
    * 设置统一放 user.ltx 的各自段落里，**不要**再给每个工具新开一个
      <tool>.cfg.json —— 散落的配置文件正是 user.ltx 要收拢的东西。
"""
import json
import os
import subprocess
import sys

# 模块级名字（不是"转发函数"）：既有探针用 `toolkit_platform.app_dir = lambda: 临时目录`
# 把落盘重定向到临时目录，本模块内部各处也走这个全局名。
from toolkit_paths import app_dir


def app_config_path(name):
    """应用配置文件路径：app_dir()/<name>.cfg.json"""
    return os.path.join(app_dir(), f"{name}.cfg.json")


def load_app_config(name, default=None):
    """读应用配置；文件缺失/损坏时返回 default（默认 {}），不抛异常。"""
    path = app_config_path(name)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {} if default is None else default


def save_app_config(name, cfg):
    """写应用配置。返回 True/False —— 调用方可据此提示，而不是静默丢弃。"""
    try:
        with open(app_config_path(name), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# 用户设置：app_dir()/user.ltx（每个用户一份的**唯一**设置文件）
# ─────────────────────────────────────────────────────────────
# 格式是极简 INI（沿用 STALKER 的 `user.ltx` 命名）：
#
#     [theme]
#     mode = dark
#
#     [ffmpeg]
#     path = D:\tools\ffmpeg\bin\ffmpeg.exe
#     probe = D:\tools\ffmpeg\bin\ffprobe.exe
#
# **必须保留其它段**：历史上这个文件只放主题，整文件覆盖（`"w"` 直接重写）
# 不会暴露问题；现在同一个文件还要放各工具的手动设置，覆盖就会互相抹掉。
# 所以下面的写入口一律"读 → 改一项 → 整体写回"。新增设置请复用它们，
# 不要各自再开一个 <tool>.cfg.json —— 那正是本文件要避免的散落。

def user_config_path():
    """用户设置文件路径：app_dir()/user.ltx（自动生成，不入库）。"""
    return os.path.join(app_dir(), "user.ltx")


def _parse_ltx(text):
    """`[section]` + `key = value` → {section: {key: value}}。

    无法识别的行（注释、垃圾）直接跳过，绝不因为一行坏数据丢掉整个文件。
    """
    data = {}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            data.setdefault(section, {})[key.strip()] = val.strip()
    return data


def _render_ltx(data):
    """{section: {key: value}} → 文本；段间空一行。"""
    blocks = []
    for section, items in data.items():
        lines = [f"[{section}]"]
        lines += [f"{k} = {v}" for k, v in items.items()]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def load_user_config():
    """读整个 user.ltx → {section: {key: value}}；缺失/损坏返回 {}。"""
    try:
        with open(user_config_path(), "r", encoding="utf-8") as f:
            return _parse_ltx(f.read())
    except Exception:
        return {}


def load_user_value(section, key, default=None):
    """读某一项；不存在返回 default。"""
    return load_user_config().get(section, {}).get(key, default)


def save_user_values(section, values):
    """一次写入某一段的若干项，**保留其它段**。返回 True/False。

    整段一起写而不是逐项写：`[ffmpeg]` 的 path/probe 本来就要成对更新，
    逐项写会读改写两遍，中间失败还会留下半套配置。
    """
    data = load_user_config()
    bucket = data.setdefault(section, {})
    for key, val in values.items():
        bucket[key] = str(val)
    try:
        with open(user_config_path(), "w", encoding="utf-8") as f:
            f.write(_render_ltx(data))
        return True
    except Exception:
        return False


def save_user_value(section, key, value):
    """写单项（`save_user_values` 的单键形式）。"""
    return save_user_values(section, {key: value})


def _hidden_kwargs():
    """Windows 下隐藏子进程控制台窗口；其它平台为空。"""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# 公开别名：调用方需要自己用 Popen/check_call 时取这份关键字，
# 避免各处手写 `CREATE_NO_WINDOW if sys.platform == "win32" else 0`。
hidden_kwargs = _hidden_kwargs


def run_hidden(cmd, timeout=120, cwd=None, text=True):
    """隐藏窗口运行外部程序，返回 CompletedProcess；失败抛异常由调用方处理。

    统一了原先散落各处（且容易漏写 creationflags）的 subprocess.run 调用。
    """
    return subprocess.run(
        cmd, capture_output=True, text=text, timeout=timeout, cwd=cwd,
        **_hidden_kwargs(),
    )


def locate_exe(name, extra_dirs=(), config_key=None, config_name=None):
    """按固定优先级定位外部程序，返回绝对路径或 None。

    顺序：
        1. 应用配置里的记录（给出 config_name + config_key 时）
        2. 应用目录（app_dir()/name.exe）
        3. extra_dirs（调用方给的项目相关位置）
        4. PATH（Windows 用 where，其它用 shutil.which）

    纯查找，**不写盘**。
    """
    exe = name if name.lower().endswith(".exe") else f"{name}.exe"
    plain = name[:-4] if name.lower().endswith(".exe") else name

    if config_name and config_key:
        cfg = load_app_config(config_name)
        p = cfg.get(config_key)
        if p and os.path.isfile(p):
            return p

    p = os.path.join(app_dir(), exe)
    if os.path.isfile(p):
        return p

    for d in extra_dirs:
        if not d:
            continue
        p = os.path.join(os.path.expandvars(d), exe)
        if os.path.isfile(p):
            return p

    try:
        if sys.platform == "win32":
            r = run_hidden(["where", plain], timeout=15)
            if r.returncode == 0 and (r.stdout or "").strip():
                cand = r.stdout.strip().splitlines()[0].strip()
                if os.path.isfile(cand):
                    return cand
        else:
            import shutil
            cand = shutil.which(plain)
            if cand and os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return None


def system_font_dirs():
    """系统字体目录（Windows 下为 C:\\Windows\\Fonts），跨平台返回可能存在的目录。"""
    cands = []
    if sys.platform == "win32":
        win = os.environ.get("SystemRoot", r"C:\Windows")
        cands.append(os.path.join(win, "Fonts"))
    elif sys.platform == "darwin":
        cands += ["/System/Library/Fonts", "/Library/Fonts",
                  os.path.expanduser("~/Library/Fonts")]
    else:
        cands += ["/usr/share/fonts", "/usr/local/share/fonts",
                  os.path.expanduser("~/.fonts")]
    return [d for d in cands if os.path.isdir(d)] or cands


def open_in_explorer(path):
    """在文件管理器里打开路径（仅 Windows 真正实现；其它平台返回 False）。"""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606  (Windows-only API)
            return True
        subprocess.Popen(["xdg-open", path])  # noqa: S603,S607
        return True
    except Exception:
        return False
