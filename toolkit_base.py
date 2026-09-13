# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 底层基础（常量 / 应用目录 / 依赖兜底 / 窗口外壳）

从 toolkit.py 拆出（方案A 第 1 步）。本模块依赖 toolkit_log（日志管线）与
toolkit_paths（应用目录，**故意放在 Tk 无关的小模块里** —— 见该模块 docstring：
非 Tk 后端（Qt 试点）要读写 user.ltx，不该为此把 Tk 拉进进程），
不依赖主题 / 组件 / 插件，供上层任意消费。
"""
import os
import subprocess
import sys

import tkinter as tk
from tkinter import messagebox

import toolkit_log
from toolkit_paths import app_dir        # re-export：`toolkit_base.app_dir` 仍可用

APP_NAME = "STALKER Localization Toolkit"
# 版本号的**单一事实来源**：基础版本 + 预发布标记并列放这里。
# 为什么标记也要落盘：构建产物名带标记（`... 1.0.1 ALPHA.1.exe`），
# 界面/标题/日志也得显示同一个标记；只存基础版本的话，下次打开构建器
# 标记就重置成"无"，产物名与界面会对不上。用构建器或 `build.py --prerelease`
# 改一次就会写回这一行；清空写成 "" 即"无标记"。
APP_VERSION = "1.1.0"
APP_PRERELEASE = "ALPHA.15"

# 构建计数也放这里 —— 用户明确要求："还有 build 计数也放这里好了"。
# 为什么同一处：版本号 / 标记 / 产物编号 / 标记序号**都是同一次构建的状态**，
# 分散到三四个文件里必然出现"改了版本号忘了改计数"的对不上；放一起，翻一眼
# 就知道当前发到哪一版。下面两个常量由**构建工具写回**（build.py 自增、
# build_gui.py 只读），读写的唯一实现在 toolkit_version.py：
#   * 读取：进程内模块属性优先，文件正则兜底（与 APP_VERSION 同一策略）；
#   * 写回：同目录临时文件 + os.replace 原子替换，写失败只当计数丢了，不拦构建。
#   * BUILD_COUNT       已构建次数。`next_build_dir()` 每次构建 +1 并取
#                       `builds/build_N`（N = BUILD_COUNT）；若该目录已存在
#                       （手改过计数 / 历史产物）就往后找第一个空号，
#                       **绝不覆盖** builds/ 下有意保留的历史产物。
#   * PRERELEASE_COUNTS 预发布标记序号，键 "<完整版本串>|<标记名>" → 已用序号，
#                       如 {"1.0.1|ALPHA": 3}。{} = 还没自动数过：此时以
#                       APP_PRERELEASE 里已写着的序号为下限继续（只增不减），
#                       因此这一行清空也不会让序号倒退回已发布过的号。
BUILD_COUNT = 27
PRERELEASE_COUNTS = {"1.0.1|ALPHA": 9, "1.1.0|ALPHA": 15}


# `app_dir` 不再是本模块的定义，而是上面的 re-export（实现搬到 Tk 无关的
# toolkit_paths.py）。这样 `toolkit_base.app_dir()` / `from toolkit_base import app_dir`
# / `from toolkit import app_dir` 三种用法都继续可用，一个字不用改。


# 让日志管线与基础层共用同一目录（在 import 期即绑定，早于任何日志调用）
toolkit_log.set_log_dir(app_dir())
# 日志保留：**预发布版不清理**（测试期一次会生成大量日志，删早了没法回看现场，
# 下限人工把握），**正式版保留最近 100 个**。策略在这里定（依据就是本文件的
# APP_PRERELEASE），清理在启动时执行一次 —— 每个入口都 import 本模块，
# 所以"每次开软件"必然走到；预发布版策略为 None，一个文件都不会动。
toolkit_log.set_log_retention(toolkit_log.retention_keep(APP_PRERELEASE))
toolkit_log.cleanup_startup_logs()


def enable_hidpi():
    """把本进程设为 per-monitor DPI 感知（幂等）。返回**实际生效**的说明串。

    必须在创建任何窗口之前调用：否则 Windows 认为程序不感知 DPI，会把整个窗口
    位图按系统缩放拉伸 —— 在 2.5K/150% 屏上就是"界面发糊"。

    为什么要在这里逐个降级尝试并回报结果：
        * 旧实现只有 `SetProcessDpiAwareness(2)`，而它是**返回 HRESULT 而不是抛异常**
          的 API。一旦因为 exe 清单已锁定 DPI 设置而失败（E_ACCESSDENIED），
          旧代码照样往日志里写"DPI: 已应用"，于是没人知道界面为什么糊。
        * 现在依次尝试 per-monitor v2 → per-monitor → system，全都失败时**回报当前
          真实状态**，不谎报。
    """
    if sys.platform != "win32":
        return "非 Windows，交给 Tk 自行处理"
    try:
        import ctypes
    except Exception as e:
        return f"无法加载 ctypes: {e}"
    user32 = ctypes.windll.user32
    # ① PER_MONITOR_AWARE_V2（Win10 1703+）：DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor v2"
    except Exception:
        pass
    # ② Win8.1 起的 shcore 旧 API —— 必须检查 HRESULT
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    # ③ Vista 起最老的 system-aware
    try:
        if user32.SetProcessDPIAware():
            return "system（仅主显示器，跨屏可能被拉伸）"
    except Exception:
        pass
    # 三种都没成功：查真实状态回报，绝不谎报"已应用"
    try:
        aw = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(aw))
        names = {0: "unaware（Windows 会位图拉伸 → 界面会糊）",
                 1: "system（DPI 感知被清单锁定为 system）",
                 2: "per-monitor（DPI 感知被清单锁定为 per-monitor）"}
        return "未能修改，当前为 " + names.get(aw.value, str(aw.value))
    except Exception:
        return "未能设置，且无法查询当前状态"


# 进程级 DPI 感知：**统一在这里做一次**，任何入口（Hub / 构建器 / 探针）只要
# import 了 toolkit 就自动生效。此前只有 Hub 自己调，build_gui 之类自然漏掉。
try:
    HIDPI_STATUS = enable_hidpi()
except Exception as _e:                                    # pragma: no cover
    HIDPI_STATUS = f"设置失败: {_e}"


def ensure_package(module_name, pip_name=None, timeout=120):
    """确保第三方包可用：已安装直接返回 True，否则尝试 pip 安装。
    打包版依赖已内置，此处只对源码运行有意义。"""
    try:
        __import__(module_name)
        return True
    except ImportError:
        pass
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_name or module_name],
            capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        return False
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


# tkinterdnd2 可选 (拖拽)
if ensure_package("tkinterdnd2"):
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BaseTk = TkinterDnD.Tk; _HAS_DND = True
else:
    _BaseTk = tk.Tk; _HAS_DND = False; DND_FILES = None


def _ico_to_photoimages(ico_path, sizes=(16, 24, 32, 48, 64)):
    """Extract several sizes from an .ico as tk.PhotoImage for crisp HiDPI icons."""
    try:
        import io
        import tkinter as tk
        from PIL import Image
        img = Image.open(ico_path)
        out = []
        for s in sizes:
            try:
                im = img.resize((s, s), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                out.append(tk.PhotoImage(data=buf.getvalue()))
            except Exception:
                continue
        return out or None
    except Exception:
        return None


def set_app_icon(win):
    """Set the window/taskbar icon to app_icon.ico (works in dev and PyInstaller).

    Uses iconphoto() with 16/24/32/48/64 px images so Windows can pick a crisp
    size for title bar and taskbar on HiDPI displays. Falls back to iconbitmap().
    """
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "app_icon.ico"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "app_icon.ico"))
    for p in candidates:
        if not os.path.isfile(p):
            continue
        imgs = _ico_to_photoimages(p)
        if imgs:
            try:
                win.iconphoto(True, *imgs)
                # Keep references alive for the lifetime of the window.
                win._toolkit_icons = imgs
                return True
            except Exception:
                pass
        try:
            win.iconbitmap(default=p)
            return True
        except Exception:
            continue
    return False


def errbox(title, msg):
    """Error dialog that also writes into 本次运行的 runtime 日志（logs/runtime_<时刻>.log）。"""
    toolkit_log.log_to_file(msg, "error")
    messagebox.showerror(title, msg)
