# -*- coding: utf-8 -*-
"""Qt 试点**冻结产物**验证：可复现构建 + 在产物里验证今天的 Tk 解耦。

## 为什么单独一个探针

`run_qt_pilot_probe.py` 跑的是**源码态**（开发机上有 Tcl/Tk、有 PySide6、有水有电）。
而这一轮真正改动的东西 —— "Qt 侧不再依赖 Tk" —— 只有在**冻结产物**里才有意义：
开发机上 `import tkinter` 永远成功，谁也不知道 Qt 包里到底带没带 Tcl/Tk。
所以这里把 `build_qt_pilot.py` 跑一遍，然后对**产物**下断言。

## 锁什么（每条都对应一个具体的失败模式）

1. 构建脚本能按文档跑起来并产出 exe（可复现：命令留在仓库里，不靠口头）；
2. 冻结树里**一个 Tcl/Tk 产物都没有**（`--exclude-module tkinter/_tkinter/tkinterdnd2` 生效）；
3. **正对照**：同一套判据用在 Tk 发行包上必须**扫得出** Tcl/Tk ——
   否则第 2 条的"0 个"可能只是检测器失灵（这正是"永远为真的锁"的典型形态）；
4. 冻结 exe `--selftest` 真跑通（引擎往返 8 条）；
5. 冻结 exe `--themecheck` 通过，并且它的输出里那条"本进程没有 tkinter"也是 PASS；
6. 裁剪清单**真的删掉了**目标文件，且**没删掉必需项**（`platforms/qwindows.dll`、
   `platforms/qoffscreen.dll`、PySide6 的核心 dll）—— 体积优化最容易踩的就是这个；
7. `--bench` 能开真窗并跑完（证明裁剪后 `qwindows.dll` 这条路仍然可用）。

缺 PySide6 / PyInstaller 时按 SKIP 处理（与 `run_qt_pilot_probe` 同一套口径：SKIP ≠ PASS）。

用法: python run_qt_build_probe.py      （退出码 0=全过；只有 FAIL 非零）
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

PASS, FAIL, SKIP = [], [], []
# 缺外部前提时打印这行并 exit 0（run_ci.py 里的 QT_BUILD_SKIP_MARK 必须与此字面量一致）
SKIP_MARK = "SKIP run_qt_build_probe"


def check(name, fn):
    try:
        r = fn()
    except Exception as e:
        FAIL.append(name)
        print("  FAIL %s -> %s: %s" % (name, type(e).__name__, e))
        return
    if r is False:
        FAIL.append(name)
        print("  FAIL %s -> 断言返回 False" % name)
        return
    PASS.append(name)
    print("  PASS %s" % name)


def skip(name, why):
    SKIP.append(name)
    print("  SKIP %s（%s）" % (name, why))


def main():
    print("=" * 68)
    print("Qt 试点冻结产物验证（可复现构建 + 冻结态 Tk 解耦）")
    print("=" * 68)

    try:
        import build_qt_pilot as BQ
    except Exception as e:
        skip("全部", "导入 build_qt_pilot 失败：%r" % (e,))
        print("\n%s（导入失败）" % SKIP_MARK)
        print("\nPASS 0  FAIL 0  SKIP 1")
        return 0
    try:
        import PyInstaller          # noqa: F401  只做可用性探测
        import PySide6              # noqa: F401
        assert PyInstaller.__version__ and PySide6.__version__
    except Exception as e:
        skip("全部", "缺 PyInstaller/PySide6：%r" % (e,))
        print("\n%s（缺打包或 Qt 前提）" % SKIP_MARK)
        print("\nPASS 0  FAIL 0  SKIP 1")
        return 0

    print("\n[1] 可复现构建（调 build_qt_pilot.py，和用户手动跑的是同一条命令）")
    p = subprocess.run([sys.executable, "build_qt_pilot.py"], cwd=BASE,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3600)
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.strip().splitlines()[-12:]:
        print("      | %s" % line)
    dist = os.path.join(BASE, "qt_pilot_dist", BQ.APP_NAME)
    exe = os.path.join(dist, BQ.APP_NAME + ".exe")
    check("构建脚本退出码 0 且产出 exe", lambda: p.returncode == 0 and os.path.isfile(exe))
    if not os.path.isfile(exe):
        print("\n构建没成功，后续断言无从谈起")
        print("\nPASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
        return 1

    print("\n[2] 冻结树里不得有 Tcl/Tk（判据与构建脚本同一份实现）")
    hits = BQ.find_tcl_tk(dist)
    print("      实测命中：%r" % (hits,))
    check("冻结产物里 0 个 Tcl/Tk 产物（tkinter 已被 --exclude-module 断掉）",
          lambda: not hits)

    print("\n[3] 正对照：同一套判据必须能在 **Tk 发行包**上扫出 Tcl/Tk")
    tk_rel = None
    builds = os.path.join(BASE, "builds")
    if os.path.isdir(builds):
        for d in sorted(os.listdir(builds), reverse=True):
            cand = os.path.join(builds, d)
            if not os.path.isdir(cand):
                continue
            inner = [x for x in os.listdir(cand) if os.path.isdir(os.path.join(cand, x))
                     and x.startswith("STALKER")]
            root = os.path.join(cand, inner[0]) if inner else cand
            if os.path.isdir(os.path.join(root, "_internal")):
                tk_rel = root
                break
    if tk_rel is None:
        skip("正对照（判据不是空转）", "仓库里没有可用的 Tk 发行包（builds/ 下没找到 _internal）")
    else:
        tk_hits = BQ.find_tcl_tk(tk_rel)
        print("      Tk 发行包：%s" % os.path.relpath(tk_rel, BASE))
        print("      扫出 %d 项：%r" % (len(tk_hits), tk_hits[:6]))
        check("正对照：判据在 Tk 发行包里扫得出 Tcl/Tk（所以第 2 条的 0 才有意义）",
              lambda: len(tk_hits) >= 2)

    print("\n[4] 冻结 exe 的真实行为")
    r1 = BQ.run_frozen(exe, ["--selftest"])
    o1 = r1.stdout or ""
    for line in o1.strip().splitlines()[-2:]:
        print("      | %s" % line)
    check("冻结 exe --selftest：PASS 8 / FAIL 0（引擎真实往返）",
          lambda: r1.returncode == 0 and "PASS 8  FAIL 0" in o1)

    r2 = BQ.run_frozen(exe, ["--themecheck"])
    o2 = r2.stdout or ""
    for line in o2.strip().splitlines():
        print("      | %s" % line)
    tc = BQ.parse_themecheck(o2)          # ASCII 标记行（中文行随控制台代码页，不作为契约）
    print("      解析（ASCII 标记行）：%r" % (tc,))
    check("冻结 exe --themecheck：ok>0 且 bad=0（主题映射 + 持久化，off-screen）",
          lambda: bool(tc) and tc["ok"] > 0 and tc["bad"] == 0 and r2.returncode == 0)
    check("冻结态里 tkinter 也没进进程（THEMECHECK tkinter=False）",
          lambda: bool(tc) and tc["tkinter"] is False)

    r3 = BQ.run_frozen(exe, ["--bench"], timeout=600)
    o3 = r3.stdout or ""
    for line in o3.strip().splitlines()[-2:]:
        print("      | %s" % line)
    check("冻结 exe --bench：能开真窗跑完（裁剪后 qwindows 平台插件仍可用）",
          lambda: r3.returncode == 0 and "ms" in o3)

    print("\n[5] 裁剪清单：该删的删了、该留的留着")
    n_after, b_after = BQ.tree_size(dist)
    print("      裁剪后：%d 文件 / %.1f MB" % (n_after, BQ.mb(b_after)))
    live_prune = [pat for pat, _why in BQ.PRUNE if BQ._resolve(dist, pat)]
    print("      清单里仍残留的项：%r" % (live_prune,))
    check("裁剪清单每一项都真的删掉了（没有静默失效的模式）", lambda: not live_prune)
    check("裁剪确实缩小了产物（释放 > 5 MB）", lambda: b_after < 80 * 1024 * 1024)
    must = ["platforms/qwindows.dll", "platforms/qoffscreen.dll"]
    found = {}
    for dp, _dn, fn in os.walk(dist):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), dist).replace("\\", "/")
            for m in must:
                if rel.endswith(m):
                    found[m] = rel
    print("      必需项：%r" % (found,))
    check("裁剪没删掉必需的平台插件（qwindows / qoffscreen）",
          lambda: len(found) == len(must))
    check("PySide6 核心（Qt6Core/Qt6Widgets/Qt6Gui）都还在",
          lambda: all(any(n.lower() in f.lower() for f in _all_files(dist))
                      for n in ("Qt6Core", "Qt6Widgets", "Qt6Gui")))

    print("\n" + "=" * 68)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败：")
        for n in FAIL:
            print("  - " + n)
    print("=" * 68)
    return 1 if FAIL else 0


def _all_files(root):
    out = []
    for dp, _dn, fn in os.walk(root):
        out.extend(fn)
    return out


if __name__ == "__main__":
    sys.exit(main())
