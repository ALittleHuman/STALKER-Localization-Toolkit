# -*- coding: utf-8 -*-
"""把 Qt 试点打成**可复现**的冻结包，并在产物里当场验证。

## 为什么要有这个脚本

试点第一版那个 68.7 MB 的包是**临时手敲 PyInstaller 命令**打出来的：命令没留下、
产物也没留（`builds/` 是发行计数器的地盘，不该塞试点包）。结果是两条结论
（"净增 +42 MB"、"冻结包能跑"）**只有当时的输出作证据，谁也没法复跑**。
试点到这里，最该补的就是"把验证做成可复跑的"。

## 它做的七件事

1. 前置检查（PyInstaller / PySide6 / 业务引擎 / `qt_pilot.py`）；
2. PyInstaller onedir 构建，并**显式 `--exclude-module tkinter/_tkinter/tkinterdnd2`** ——
   这一步把"Qt 侧不依赖 Tk"从一句声明变成**构建期约束**：真有人偷偷把 Tk 接回来，
   这里会直接编不出来（或编出来跑不起来，下一步就会红）；
3. 报构建后体积（文件数 / 字节）；
4. 按清单裁剪（每项打印命中的路径与释放的字节 —— 数字是**量出来的**，不是抄的）；
5. 扫冻结树里有没有 Tcl/Tk 产物（`find_tcl_tk()`，探针共用同一份实现）；
6. 跑冻结 exe 的 `--selftest`（真实往返 8 条）与 `--themecheck`（主题映射/持久化）；
7. 打印体积表。**只有失败才非零退出。**

## 用法

    python build_qt_pilot.py                  # 构建 + 裁剪 + 自检（默认）
    python build_qt_pilot.py --keep           # 不裁剪（对照体积用）
    python build_qt_pilot.py --no-selftest    # 只构建（探针自己会跑自检）
    python build_qt_pilot.py --out DIR        # 换输出目录

输出目录默认 `qt_pilot_dist/`（已加进 `.gitignore`：它是构建产物，不是源码）。
"""
import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULT_OUT = os.path.join(HERE, "qt_pilot_dist")
APP_NAME = "QtPilot"
ENTRY = "qt_pilot.py"

# 构建期就断掉 Tk：`--exclude-module` 让"Qt 侧不依赖 Tk"成为**约束**而不是声明。
EXCLUDES = ("tkinter", "_tkinter", "tkinterdnd2", "PIL")

# 业务包的打包方式**照抄 build.py 的既有约定**（不要自己发明）：
#   * `--paths`   ：让 PyInstaller 在**分析期**能 import 到（否则 hidden import 报缺）；
#   * `--add-data`：让**运行期**也能 import 到 —— `qt_pilot.py` 是
#                   `sys.path.insert(0, BASE/"file_system")` 之后再 import 的，
#                   onedir 下这条路径必须真实存在（第一版只加了 --paths，
#                   冻结包当场报 `No module named 'stalker_fs'`）。
PATHS = ("file_system",)
DATAS = (("file_system", "file_system"),)

# 裁剪清单：**模式匹配**而不是写死路径（PyInstaller 的目录布局换版本就会挪位置）。
# 每一项都写了"为什么可以删"。被删掉的字节数在运行时打印 —— 那份数字才是可引用的。
PRUNE = (
    ("**/opengl32sw.dll",
     "Qt 的软件 OpenGL 兜底实现（~20 MB）；试点只画控件，不用 OpenGL"),
    ("**/PySide6/translations",
     "Qt 自带翻译（~8 MB）；界面文案是我们自己的中文，用不到 Qt 语言包"),
    ("**/libcrypto-3*.dll",
     "OpenSSL；试点不联网（唯一用户是 QtNetwork，未被引入）"),
    ("**/libssl-3*.dll",
     "同上"),
)

# Tcl/Tk 产物的**精确**判据（不能用"名字里有 tk"那种松判据：toolkit / task 都会误命中）。
TCL_TK_DIRS = {"tcl", "tk", "tcl8", "tk8", "tcl8.6", "tk8.6", "tkdnd",
               "_tcl_data", "_tk_data"}
TCL_TK_SUFFIX = (".dll", ".pyd", ".so", ".dylib")


def is_tcl_tk_name(name):
    """名字本身是不是 Tcl/Tk 产物（大小写不敏感）。"""
    low = name.lower()
    if low in TCL_TK_DIRS:
        return True
    if not low.endswith(TCL_TK_SUFFIX):
        return False
    stem = low.rsplit(".", 1)[0]
    if stem.startswith("_tkinter") or stem.startswith("tkinter"):
        return True
    for pre in ("tcl", "tk", "libtcl", "libtk", "tcl86", "tk86", "tcl86t", "tk86t",
                "tcl90", "tk90"):
        if stem == pre or stem.startswith(pre + "8") or stem.startswith(pre + "9"):
            return True
    return False


def find_tcl_tk(root):
    """扫出冻结树里的 Tcl/Tk 产物（返回相对路径列表，升序）。

    探针也 import 这个函数 —— 判据只有一份实现，避免"两处判据不一样"这种漂移。
    """
    hits = []
    for dp, dn, fn in os.walk(root):
        for d in list(dn):
            if is_tcl_tk_name(d):
                hits.append(os.path.relpath(os.path.join(dp, d), root))
        for f in fn:
            if is_tcl_tk_name(f):
                hits.append(os.path.relpath(os.path.join(dp, f), root))
    return sorted(hits)


def tree_size(root):
    """(文件数, 总字节)。"""
    n = 0
    total = 0
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                total += os.path.getsize(p)
                n += 1
            except OSError:
                pass
    return n, total


def mb(n):
    return n / (1024.0 * 1024.0)


def _resolve(dist, pattern):
    """把 `**/x` 这类模式解析成 dist 下的真实路径（目录或文件）。"""
    hits = []
    norm = pattern.replace("\\", "/")
    for dp, dn, fn in os.walk(dist):
        rel_dir = os.path.relpath(dp, dist).replace("\\", "/")
        for name in list(dn) + list(fn):
            rel = name if rel_dir == "." else rel_dir + "/" + name
            if fnmatch.fnmatch(rel, norm) or fnmatch.fnmatch(name, norm):
                hits.append(os.path.join(dp, name))
    return sorted(set(hits))


def prune(dist, dry=False):
    """按 PRUNE 裁剪，返回 [(模式, 路径, 释放字节)]。"""
    freed = []
    for pattern, _why in PRUNE:
        for p in _resolve(dist, pattern):
            if not os.path.exists(p):
                continue
            if os.path.isdir(p):
                _n, size = tree_size(p)
            else:
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
            if not dry:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        os.remove(p)
                    except OSError:
                        continue
            freed.append((pattern, os.path.relpath(p, dist), size))
    return freed


def build(out, work=None, quiet=False):
    """跑 PyInstaller，返回 (dist_dir, exe_path, 耗时秒)。"""
    work = work or os.path.join(HERE, "qt_pilot_build")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
           "--name", APP_NAME,
           "--distpath", out, "--workpath", work, "--specpath", work]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    for p in PATHS:
        cmd += ["--paths", os.path.join(HERE, p)]
    for src, dst in DATAS:
        cmd += ["--add-data", "%s;%s" % (os.path.join(HERE, src), dst)]
    cmd.append(ENTRY)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    dt = time.time() - t0
    if not quiet:
        tail = (proc.stdout or "").strip().splitlines()[-6:]
        for line in tail:
            print("      | %s" % line)
    dist = os.path.join(out, APP_NAME)
    exe = os.path.join(dist, APP_NAME + ".exe")
    return dist, exe, dt, proc


def run_frozen(exe, args, timeout=300):
    """跑冻结 exe。

    * 清掉 `TCL_LIBRARY` / `TK_LIBRARY` / `PYTHONHOME` / `PYTHONPATH` ——
      否则**本机装的** Tcl/Tk 或源码目录会掩盖真实问题（测的是"这台机器"而不是产物）。
    * 不强制 IO 编码：冻结 exe 的中文输出随控制台代码页，调用方只该解析 ASCII 标记行
      （`--themecheck` 会打一行 `THEMECHECK ok=.. bad=.. tkinter=..`）。
    """
    env = dict(os.environ)
    for k in ("TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH", "PYTHONHOME", "PYTHONPATH",
              "PYTHONIOENCODING", "PYTHONUTF8"):
        env.pop(k, None)
    return subprocess.run([exe] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)


def parse_themecheck(out):
    """从冻结 exe 的输出里取 `THEMECHECK ok=N bad=M tkinter=Bool`（取不到返回 None）。

    为什么不解析中文行：冻结产物的 stdout 编码随控制台代码页，中文在别的进程里
    可能是乱码；ASCII 标记行才是稳定的契约。
    """
    m = re.search(r"THEMECHECK ok=(\d+) bad=(\d+) tkinter=(\w+)", out or "")
    if not m:
        return None
    return {"ok": int(m.group(1)), "bad": int(m.group(2)),
            "tkinter": m.group(3) == "True"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="构建 Qt 试点冻结包（可复现）")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--keep", action="store_true", help="不裁剪（对照体积用）")
    ap.add_argument("--no-selftest", action="store_true", help="构建后不跑冻结包自检")
    args = ap.parse_args(argv)

    print("=" * 68)
    print("Qt 试点冻结包构建（%s）" % APP_NAME)
    print("=" * 68)

    try:
        import PyInstaller          # noqa: F401  只做可用性探测（下面用 -m PyInstaller 调）
        assert PyInstaller.__version__
    except Exception as e:
        print("  FAIL 缺 PyInstaller：%s" % (e,))
        return 2
    try:
        import PySide6              # noqa: F401  同上
        assert PySide6.__version__
    except Exception as e:
        print("  FAIL 缺 PySide6：%s" % (e,))
        return 2
    if not os.path.isfile(os.path.join(HERE, ENTRY)):
        print("  FAIL 找不到入口 %s" % ENTRY)
        return 2

    if os.path.isdir(args.out):
        shutil.rmtree(args.out, ignore_errors=True)
    os.makedirs(args.out, exist_ok=True)

    print("\n[1] PyInstaller 构建（排除 %s）" % "、".join(EXCLUDES))
    dist, exe, dt, proc = build(args.out)
    if not os.path.isfile(exe):
        print("  FAIL 没产出 %s（PyInstaller 退出码 %d）" % (exe, proc.returncode))
        print((proc.stderr or "")[-1500:])
        return 1
    n0, b0 = tree_size(dist)
    print("  OK 产出 %s" % os.path.relpath(dist, HERE))
    print("     构建 %.1f s ；未裁剪 %d 文件 / %.1f MB" % (dt, n0, mb(b0)))

    print("\n[2] 裁剪（%s）" % ("跳过 --keep" if args.keep else "按清单"))
    n1, b1 = n0, b0
    if not args.keep:
        freed = prune(dist)
        for pattern, rel, size in freed:
            print("     删除 %-46s %.2f MB" % (rel, mb(size)))
        if not freed:
            print("     [!!] 一项都没删到 —— 要么清单过时了，要么布局变了（这是要查的）")
        n1, b1 = tree_size(dist)
        print("     裁剪后 %d 文件 / %.1f MB（释放 %.1f MB）" % (n1, mb(b1), mb(b0 - b1)))

    print("\n[3] 冻结树里不得有 Tcl/Tk")
    hits = find_tcl_tk(dist)
    print("     命中：%r" % (hits,))
    ok_tcl = not hits
    print("     %s" % ("OK 一个都没有（--exclude-module 生效）" if ok_tcl
                      else "FAIL 出现了 Tcl/Tk 产物"))

    ok_self = ok_theme = True
    if not args.no_selftest:
        print("\n[4] 冻结 exe --selftest（真实 pack → 扫描 → 加载 → 解包 → 重封包）")
        p = run_frozen(exe, ["--selftest"])
        out = (p.stdout or "").strip().splitlines()
        for line in out[-3:]:
            print("      | %s" % line)
        ok_self = (p.returncode == 0 and "PASS 8  FAIL 0" in (p.stdout or ""))
        print("     %s（退出码 %d）" % ("OK" if ok_self else "FAIL", p.returncode))

        print("\n[5] 冻结 exe --themecheck（主题映射 + 持久化；off-screen 不弹窗）")
        p2 = run_frozen(exe, ["--themecheck"])
        for line in (p2.stdout or "").strip().splitlines():
            print("      | %s" % line)
        tc = parse_themecheck(p2.stdout)
        ok_theme = bool(tc) and tc["bad"] == 0 and not tc["tkinter"] and p2.returncode == 0
        print("     解析（ASCII 标记行）：%r" % (tc,))
        print("     %s（退出码 %d）" % ("OK" if ok_theme else "FAIL", p2.returncode))

    print("\n" + "=" * 68)
    total_ok = ok_tcl and ok_self and ok_theme
    print("体积：未裁剪 %.1f MB → 裁剪后 %.1f MB（%d → %d 文件）"
          % (mb(b0), mb(b1), n0, n1))
    print("冻结 exe：%s" % exe)
    print("RESULT: %s" % ("PASS" if total_ok else "FAIL"))
    print("=" * 68)
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(main())
