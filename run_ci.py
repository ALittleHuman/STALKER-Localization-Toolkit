#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local CI / regression entry.

Runs automated checks. 各档跑什么：

    * compileall / import modules / DB roundtrip —— 三档都跑（不需要外部前提）
    * 六个探针（ext / app / functional / build / hub / engine_compat）+ 静态守卫 —— 三档都跑
    * cross_validate.py（需外部 converter.exe）—— fast 档跳过，其余按档位记 SKIP 或 FAIL
    * run_ui_smoke.py（需桌面会话）—— fast 档跳过，其余按档位记 SKIP 或 FAIL
    * cleanup: __pycache__, temp/*, cross_validate_out

Usage:
    python run_ci.py            # 本地全量回归（外部前提缺失时 SKIP + 记入"未覆盖"清单）
    python run_ci.py --fast     # 公开 CI 用的快速档：跳过"需要外部前提"的两步
    python run_ci.py --release  # 发版门禁：不接受任何未覆盖项（缺桌面/缺 converter.exe 即 FAIL）

三档的区别（用户裁定 2026-09-12，方案 3「两级门禁」）：

| 档 | 交叉校验（官方 converter.exe） | UI 冒烟（需桌面） | 缺前提时 |
|---|---|---|---|
| `--fast`（公开 CI） | 跳过 | 跳过 | 记入"本次未覆盖"清单，仍绿 |
| 默认（本地全量） | 跑 | 跑 | SKIP + 记入清单，仍绿 |
| `--release`（发版） | 跑 | 跑 | **FAIL**；且清单非空即整体 FAIL |

为什么不一刀切"缺件即 FAIL"：公开 CI 跑在没有桌面、没有官方 converter.exe 的机器上，
把"环境不具备"判成失败会让 CI **永久变红**，信号从"代码坏了"退化成"这台机器不是你的电脑"。
但发版前必须真验过这两样 —— 于是把严格度做成参数，并让"跳过了什么"永远显式打印出来
（SKIP ≠ PASS：不写出来就会被读成"覆盖过了"）。

【注释重建说明】本文件曾被一次文本事故破坏（PowerShell 把源码按 ANSI 代码页读取后
以 UTF-8 重写，中文成了 cp936→UTF-8 双重编码乱码并吞掉部分换行）。修复时字符串常量
**逐字取自**损坏前编译的 `__pycache__/run_ci.cpython-314.pyc`；注释不在 .pyc 里、
无法还原，只能照仓库风格重写，故措辞非原文，请以代码与字符串常量为准。
"""

import os
import shutil
import subprocess
import sys

# temp/ 下允许 CI 清理的**测试**目录白名单（见 cleanup；不要加 "build"）
#
# ⚠ 构建器的目录**不在此列**：`temp/build/` 是 `build.py` 的 PyInstaller
# 工作目录（work/spec），归属"谁创建谁清理"——由 build.py 自己的 finally 负责。
# CI 若删它，正在进行的构建会在十几秒处夭折并报
# `FileNotFoundError: ...work\<应用名>\base_library.zip`（实测发生过一次：
# GUI 构建与 CI 同时跑）。run_build_probe 有断言锁住此表不得出现 "build"。
CLEAN_TEMP_NAMES = ("cross_validate_out",)

# 控制台编码兜底：CI 要把子进程输出（探针里大量中文）原样打到 stdout，
# 而 Windows 控制台默认可能是 GBK，直接 print 会抛 UnicodeEncodeError 打断整轮。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 外部前提 / 覆盖清单（方案 3：两级门禁）──────────────────────────────
# 官方 converter.exe 的位置。原先两处写死绝对路径（本文件与 cross_validate.py），
# 换台机器就永远 SKIP —— 于是"交叉校验"实际上只在作者本机能跑。
# 现在环境变量优先（自托管 runner / 别的机器都能真跑），默认仍是本机原路径。
CONVERTER_ENV = "STALKER_CONVERTER_EXE"
CONVERTER_DEFAULT = (r"E:\Software\Games\STALKER\Localization\Tools\Tool"
                     r"\Stalker_Unpacker_2017\converter.exe")
# run_ui_smoke 无桌面时的自我标识（它打印这行并 exit 0）。
# 这里与 run_ui_smoke.py 里的字面量必须一致，run_build_probe 有断言钉住两边不漂移。
UI_SMOKE_SKIP_MARK = "SKIP run_ui_smoke"
# Qt 试点探针缺 PySide6/桌面时的自我标识（与 run_qt_pilot_probe.py 里的字面量必须一致）。
QT_PILOT_SKIP_MARK = "SKIP run_qt_pilot_probe"
# Qt 冻结产物探针缺 PyInstaller/PySide6 时的自我标识（与 run_qt_build_probe.py 一致）。
QT_BUILD_SKIP_MARK = "SKIP run_qt_build_probe"
# 本次运行**没有覆盖**的东西（SKIP ≠ PASS：列出来才不会被读成"验过了"）
_NOT_COVERED = []


def note_uncovered(what, why):
    _NOT_COVERED.append("%s（%s）" % (what, why))


def uncovered_report():
    if not _NOT_COVERED:
        print("\n本次覆盖：全部步骤均已执行")
        return
    print("\n本次未覆盖（SKIP ≠ PASS，别读成通过）：")
    for x in _NOT_COVERED:
        print("  - " + x)


def converter_exe():
    """官方 converter.exe 路径：环境变量 STALKER_CONVERTER_EXE 优先，否则默认绝对路径。"""
    return os.environ.get(CONVERTER_ENV) or CONVERTER_DEFAULT


def mode_of(argv):
    """`--fast` / `--release` / 默认 → `"fast"` / `"release"` / `"local"`。

    两者同时给是**用法错误**：它们对"缺前提算不算失败"的判定正好相反，
    静默取其一等于让调用者以为自己拿到了另一档。
    """
    fast, release = "--fast" in argv, "--release" in argv
    if fast and release:
        raise ValueError("--fast 与 --release 不能同时使用（对缺前提的判定相反）")
    if fast:
        return "fast"
    if release:
        return "release"
    return "local"


def prereq_missing(what, why, release):
    """外部前提缺失：返回"是否仍可继续（不算失败）"。

    * `release=True`（发版门禁）→ 打印 FAIL 并返回 False；
    * 其余档 → 打印 SKIP、返回 True。

    **两档都要进"未覆盖"清单**：无论算 SKIP 还是算 FAIL，"这一步没有跑"都是事实。
    只记 SKIP 那一档的话，发版档会打印"本次覆盖：全部步骤均已执行"，而实际上这一步
    刚刚 FAIL 掉了 —— 收尾报告自己撒谎（2026-09-12 实测踩到，已修）。
    """
    note_uncovered(what, why)
    if release:
        print("  FAIL 缺少外部前提：%s（%s）—— --release 档不接受未覆盖" % (what, why))
        return False
    print("  SKIP %s（%s）" % (what, why))
    return True


def final_ok(ok, release):
    """收尾判定：**发版档只要还有未覆盖项就不通过**（否则"缺前提即 FAIL"会被绕过）。"""
    if release and _NOT_COVERED:
        print("\nRELEASE 档要求零未覆盖，但仍有 %d 项" % len(_NOT_COVERED))
        return False
    return ok


def cleanup():
    """只清理**测试自己产生的**产物；不动用户数据。

    历史行为（已修正）：这里原先会删掉 `logs/` 下除 `.gitkeep` 外的**所有**文件，
    也就是"跑一次 CI 就把 runtime 日志清空"——而它是排障依据（现在每次启动一个
    `runtime_<启动时刻>.log`，清一次就等于抹掉若干次运行的记录）。
    经核对，没有任何测试依赖 `logs/` 为空（各探针用的是自己的内存或系统临时目录），
    因此现在只清：
        * `__pycache__/`        —— Python 编译缓存
        * `cross_validate_out/` —— cross_validate 的输出目录
        * `temp/build/`、`temp/toolkit_*` 等**已知测试目录**（而不是 temp/ 全部内容）
    `logs/` 完全不碰。
    """
    shutil.rmtree(os.path.join(HERE, "cross_validate_out"), ignore_errors=True)
    # 遗留物：cross_validate 早期版本把样例写在仓库里的固定目录，现已改为
    # 每次运行独占的临时目录；这里顺手清掉历史残留。
    shutil.rmtree(os.path.join(HERE, "cross_validate_samples"), ignore_errors=True)

    # 只清活代码的缓存：builds/（历史产物）与 backup/（重构前快照）是有意保留的
    # 对照物，CI 不该顺手改动它们；deps/ 与 .git 同理。
    for dp, dn, fn in os.walk(HERE):
        dn[:] = [d for d in dn if d not in ("builds", "backup", "deps", ".git")]
        if "__pycache__" in dn:
            shutil.rmtree(os.path.join(dp, "__pycache__"), ignore_errors=True)
            dn.remove("__pycache__")

    # temp/ 下只删**测试**生成的固定子目录；其余内容视为用户数据，保留。
    # ⚠ `temp/build/` **绝不能删** —— 它不是测试目录，而是**构建器自己的
    # PyInstaller 工作目录**（`build.py:204-208` 的 `temp/build/{work,spec}`）。
    # 曾经把它列进清理名单，后果实测过：用户从 build_gui 起构建的同时跑 CI，
    # 这句 rmtree 把 `work/<应用名>/` 删掉，PyInstaller 随即在
    # create_base_library_zip 处报
    # `FileNotFoundError: ...work\<应用名>\base_library.zip` 并夭折
    # （构建在 16 秒处夭折，`builds/build_N` 只留一个空目录）。
    # 归属原则：**谁创建、谁清理**；构建器的临时目录由 build.py 自己的 finally 清。
    temp_dir = os.path.join(HERE, "temp")
    for name in CLEAN_TEMP_NAMES:
        p = os.path.join(temp_dir, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    if os.path.isdir(temp_dir):
        for name in os.listdir(temp_dir):
            if name.startswith("toolkit_") or name.startswith("dsh_"):
                p = os.path.join(temp_dir, name)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    # logs/ 有意不清理：runtime_<启动时刻>.log 是运行与排障记录。


# 把子包目录与仓库根都放进 sys.path：探针是以脚本方式启动的，不做这一步
# `import file_system.stalker_fs`、`import plugins.*` 与 `import toolkit` 都会找不到。
# 顺序有意如此：仓库根最后插入即排在**最前**，保证顶层模块优先于同名子包内模块。
def setup_paths():
    for sub in ("file_system", "font_pack", "plugins"):
        p = os.path.join(HERE, sub)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    sys.path.insert(0, HERE)


def step(name):
    print(f"\n=== {name} ===")


def main():
    mode = mode_of(sys.argv)
    release = mode == "release"
    setup_paths()
    ok = True
    print("模式：%s —— %s" % (mode, {
        "fast": "--fast：公开 CI 档（跳过需外部前提的步骤，并记入未覆盖清单）",
        "local": "默认：本地全量（缺前提记 SKIP + 未覆盖清单）",
        "release": "--release：发版门禁（任何未覆盖项 = 不通过）",
    }[mode]))

    step("compileall")
    import py_compile
    # 只编译**活代码**：builds/build_N/_internal/ 里有历史构建的源码副本，
    # backup/ 下是重构前快照（有意保留的对照物），都不该参与本仓库的编译/扫描。
    _SKIP_PARTS = ("__pycache__", "builds", "backup", "temp", ".git",
                   "cross_validate_out", "deps")
    failed = []
    for dp, dn, fn in os.walk(HERE):
        dn[:] = [d for d in dn if d not in _SKIP_PARTS]
        if any(part in dp.split(os.sep) for part in _SKIP_PARTS):
            continue
        for f in fn:
            if f.endswith(".py"):
                p = os.path.join(dp, f)
                try:
                    py_compile.compile(p, doraise=True)
                except Exception as e:
                    failed.append((p, e))
    if failed:
        for p, e in failed:
            print(f"  FAIL {p}: {e}")
        ok = False
    else:
        print("  OK")

    step("import modules")
    import importlib
    mods = [
        "toolkit",                # 库门面（re-export 层）
        "file_system.stalker_fs",  # DB 引擎（六种格式）
        "plugins.nlc_sqfs",       # 闭源插件；不在仓库里时按 SKIP 处理
        "stalker_toolkit",        # 统一入口
    ]
    for m in mods:
        try:
            importlib.import_module(m)
            print(f"  OK {m}")
        except ModuleNotFoundError as e:
            # nlc_sqfs 是闭源插件，不入库；文件不在就当 SKIP，而不是失败。
            if m == "plugins.nlc_sqfs" and not os.path.isfile(
                os.path.join(HERE, "plugins", "nlc_sqfs.py")
            ):
                print(f"  SKIP {m} (closed-source plugin not in repository)")
            else:
                print(f"  FAIL {m}: {e}")
                ok = False
        except Exception as e:
            print(f"  FAIL {m}: {e}")
            ok = False

    step("DB roundtrip all formats")
    # 每种格式都做一次 pack→unpack→extract：覆盖空文件、二进制、子目录三类边界。
    try:
        import stalker_fs
        files = [
            ("a.txt", b"hello world", False),
            ("dir/b.bin", bytes(range(256)) * 10, False),
            ("dir/empty.bin", b"", False),
        ]
        for fmt in stalker_fs.FORMATS:
            db = stalker_fs.pack_db(files, fmt)
            entries = stalker_fs.unpack_db(db, fmt)
            assert entries, f"{fmt}: no entries"
            data_map = {f[0]: f[1] for f in files}
            for e in entries:
                if e["is_dir"]:
                    continue
                data = stalker_fs.extract_file(db, e)
                if data != data_map.get(e["path"]):
                    print(f"  FAIL {fmt} {e['path']} data mismatch")
                    ok = False
                    break
            else:
                print(f"  OK {fmt}")
    except Exception as e:
        print(f"  FAIL roundtrip: {e}")
        ok = False

    if mode == "fast":
        # 快速档（公开 CI）不跑交叉校验：**显式记账** —— 跳过不等于验过。
        note_uncovered("cross_validate（官方 converter.exe 双向交叉校验）", "--fast 档跳过")
    else:
        step("cross_validate (external converter)")
        cv_py = os.path.join(HERE, "cross_validate.py")
        cv_exe = converter_exe()
        if not os.path.isfile(cv_py):
            # cross_validate.py 是仓库件，缺件=门禁没了；converter.exe 是外部第三方
            # 程序，缺它才是真正的环境性前提缺失（按档位 SKIP 或 FAIL）。
            print("  FAIL (cross_validate.py 不在仓库里：门禁被删/改名了？)")
            ok = False
        elif not os.path.isfile(cv_exe):
            ok = prereq_missing("cross_validate（官方 converter.exe 交叉校验）",
                                "未找到 %s（可用环境变量 %s 指定）"
                                % (cv_exe, CONVERTER_ENV), release) and ok
        else:
            child_env = dict(os.environ)
            # 把解析结果回传给子进程：两处各读一次环境变量迟早会不一致。
            child_env[CONVERTER_ENV] = cv_exe
            proc = subprocess.run([sys.executable, cv_py], cwd=HERE, env=child_env,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=600)
            # 回显尾部：与其它步骤一致。**成功时也要回显** —— cross_validate 的
            # 末行是 `PASS n FAIL n SKIP n`，只打一个 OK 会让"到底验了多少"看不见。
            for ln in [x for x in (proc.stdout or "").strip().splitlines() if x.strip()][-4:]:
                print("  " + ln)
            if proc.returncode == 0:
                print("  OK")
            else:
                print("  FAIL")
                if proc.stdout:
                    print(proc.stdout[-2000:])
                if proc.stderr:
                    print(proc.stderr[-2000:])
                ok = False

    # 扩展点阀门与构造级闸门：把"注册成功但无人消费"和"方法体内隐式初始化"
    # 这两类 run_ci 只 import 抓不到的缺陷变成机器可查。
    for script, title in (("run_ext_probe.py", "run_ext_probe (扩展点端到端)"),
                          ("run_app_probe.py", "run_app_probe (构造级 + 入口级)")):
        step(title)
        path = os.path.join(HERE, script)
        if not os.path.isfile(path):
            # 仓库自带的探针缺件，只可能是被删/改名/没签出。原先记 SKIP 等于
            # "把门禁文件删掉就算绿灯"——这是最坏的一种假绿（比断言空转更危险：
            # 覆盖整段消失而 RESULT 仍是 PASS）。缺件即 FAIL。
            print(f"  FAIL ({script} 不在仓库里：门禁被删/改名了？)")
            ok = False
            continue
        proc = subprocess.run([sys.executable, path], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)
        tail = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
        for ln in tail[-6:]:
            print("  " + ln)
        if proc.returncode == 0:
            print("  OK")
        else:
            print("  FAIL")
            if proc.stderr:
                print(proc.stderr[-1500:])
            ok = False

    # 静态守卫（A3）：先验证守卫自己抓得住违规，再扫真实 apps/。
    # 顺序很重要——一个从不报错的守卫等于没有守卫。
    for script, title in (("run_guard_selftest.py", "静态守卫自测 (守卫是否可信)"),
                          ("toolkit_guard.py", "静态守卫扫描 apps/")):
        step(title)
        path = os.path.join(HERE, script)
        if not os.path.isfile(path):
            # 仓库自带的探针缺件，只可能是被删/改名/没签出。原先记 SKIP 等于
            # "把门禁文件删掉就算绿灯"——这是最坏的一种假绿（比断言空转更危险：
            # 覆盖整段消失而 RESULT 仍是 PASS）。缺件即 FAIL。
            print(f"  FAIL ({script} 不在仓库里：门禁被删/改名了？)")
            ok = False
            continue
        proc = subprocess.run([sys.executable, path], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)
        for ln in [x for x in (proc.stdout or "").strip().splitlines() if x.strip()][-8:]:
            print("  " + ln)
        if proc.returncode != 0:
            print("  FAIL")
            if proc.stderr:
                print(proc.stderr[-1000:])
            ok = False

    step("pyflakes (未定义名 / 未用导入 / 重复定义)")
    try:
        # 覆盖面 = 全部**活代码**：库 + 六个 App + 插件 + 引擎 + 构建器 + 版本 + 守卫 + 探针。
        # 曾经的缺口：build.py / build_gui.py / toolkit_version.py / toolkit_guard.py
        # 与所有 run_*.py 都不在扫描列表里，于是 build_gui.py 里两个未用导入
        # 和 Hub 入口 40 个死导入长期无人拦下。
        # 补入的缺口：plugins/（nlc_sqfs.py 与 engine_utf8_patch.py 此前只靠手工跑
        # pyflakes；两文件实测零告警、整目录退出码 0，进名单零代价）。
        proc = subprocess.run([sys.executable, "-m", "pyflakes",
                               "apps", "file_system", "font_pack", "plugins",
                               "toolkit.py", "toolkit_base.py", "toolkit_log.py",
                               "toolkit_theme.py", "toolkit_textio.py",
                               "toolkit_widgets.py", "toolkit_plugins.py",
                               "toolkit_platform.py", "toolkit_constants.py",
                               "toolkit_version.py", "toolkit_guard.py",
                               "toolkit_paths.py",
                               "stalker_toolkit.py", "build.py", "build_gui.py",
                               "cross_validate.py", "download_ffmpeg.py",
                               "run_ci.py", "run_ui_smoke.py", "run_ext_probe.py",
                               "run_app_probe.py", "run_functional_probe.py",
                               "run_build_probe.py", "run_hub_probe.py",
                               "run_engine_compat_probe.py", "run_guard_selftest.py",
                               "toolkit_plugin_ui.py",
                               # Qt 试点三件（PySide6 通过与否都能静态扫；此前只靠手工跑 pyflakes）
                               "qt_pilot.py", "qt_pilot_plugins.py", "qt_pilot_theme.py",
                               "build_qt_pilot.py", "run_qt_build_probe.py",
                               "run_deadcode_audit.py", "run_gui_text_audit.py",
                               # 只**静态扫描**、不在此处执行：它会临时改写真实源文件，
                               # 属于手动验证工具（见 ARCHITECTURE §11.2）。
                               # 进这个名单是 run_app_probe 那条"不许有游离 run_*.py"的防腐锁要求的。
                               "run_inject_layout_locks.py"],
                              cwd=HERE, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        lines = [x for x in (proc.stdout or "").strip().splitlines() if x.strip()]
        err = (proc.stderr or "")
        # "没装 pyflakes"必须**显式 SKIP**，不能当成"没有告警"。
        # 原先只看 stdout：模块不存在时 stdout 为空 → 过滤器得空列表 → 打印 OK，
        # 于是 GitHub 工作流（runners 上没有 pyflakes）这一步是**假绿**。
        if "No module named pyflakes" in err or "No module named 'pyflakes'" in err:
            print("  SKIP (pyflakes 未安装: pip install pyflakes) —— 注意这一步没有真正执行")
        else:
            # 转发层豁免名单**已清空**（此前只有 toolkit.py 一项）。
            # toolkit.py 是纯 re-export 层，原先靠整文件豁免遮住"导入但文件内未使用"
            # 的告警；现在它用模块级 `__all__`（143 名）把对外契约显式写下，pyflakes
            # 视 `__all__` 中的名字为已使用，零告警，于是豁免不再需要。
            # 空着比留着更安全：豁免名单里任何一个名字都会把该文件的**全部**告警
            # （含真实的未定义名）一起吞掉——这正是 40 个死导入曾被藏住的同一机制。
            # 将来若真有必须豁免的文件，请先问"能不能用 __all__ 代替"。
            _EXEMPT = ()
            real = [x for x in lines
                    if not any(x.startswith(e) for e in _EXEMPT)]
            if real:
                print(f"  发现 {len(real)} 项：")
                for x in real[:25]:
                    print("    " + x)
                if len(real) > 25:
                    print(f"    ...（其余 {len(real) - 25} 项）")
                ok = False
            elif lines:
                # 有告警但**全部落在豁免清单里**。`_EXEMPT` 现在是空的，所以本分支
                # 实际不可达（real == lines，已被上面拦下）；保留它只为将来真的
                # 重新加入豁免时不必回来改结构。注意 pyflakes 只要报了任何一条
                # 就返回 1，所以这里不能看退出码。
                print(f"  OK（{len(lines)} 条均属转发层豁免：{', '.join(_EXEMPT)}）")
            elif proc.returncode != 0:
                # 一条告警都没有、退出码又非 0：这是 pyflakes 本身出错，同样不能算绿。
                print(f"  FAIL pyflakes 退出码 {proc.returncode}")
                print(err[-800:])
                ok = False
            else:
                print("  OK")
    except FileNotFoundError:
        print("  SKIP (pyflakes 未安装: pip install pyflakes)")

    # 功能完整性：按用户可见功能做端到端验证（临时目录内，不碰用户数据）。
    step("run_functional_probe (功能完整性端到端)")
    fp = os.path.join(HERE, "run_functional_probe.py")
    if not os.path.isfile(fp):
        print("  FAIL (run_functional_probe.py 不在仓库里：门禁被删/改名了？)")
        ok = False
    else:
        proc = subprocess.run([sys.executable, fp], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=900)
        for ln in [x for x in (proc.stdout or "").strip().splitlines() if x.strip()][-8:]:
            print("  " + ln)
        if proc.returncode != 0:
            print("  FAIL")
            if proc.stderr:
                print(proc.stderr[-1500:])
            ok = False

    # 构建器：版本号解析/组合/写回 + build.py 参数 + GUI 无头构建。
    step("run_build_probe (构建器与版本号)")
    bp = os.path.join(HERE, "run_build_probe.py")
    if not os.path.isfile(bp):
        print("  FAIL (run_build_probe.py 不在仓库里：门禁被删/改名了？)")
        ok = False
    else:
        proc = subprocess.run([sys.executable, bp], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)
        for ln in [x for x in (proc.stdout or "").strip().splitlines() if x.strip()][-5:]:
            print("  " + ln)
        if proc.returncode != 0:
            print("  FAIL")
            if proc.stderr:
                print(proc.stderr[-1000:])
            ok = False

    # Hub 级框架集成：1 Hub + 6 组件 + 插件栏目 + 插件贡献，在同一运行态里成立。
    # 这是"框架到位了吗"这一问的直接回答——单构造六个 App 不足以覆盖它。
    step("run_hub_probe (Hub 级框架集成)")
    hp = os.path.join(HERE, "run_hub_probe.py")
    if not os.path.isfile(hp):
        print("  FAIL (run_hub_probe.py 不在仓库里：门禁被删/改名了？)")
        ok = False
    else:
        proc = subprocess.run([sys.executable, hp], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)
        for ln in [x for x in (proc.stdout or "").strip().splitlines() if x.strip()][-5:]:
            print("  " + ln)
        if proc.returncode != 0:
            print("  FAIL")
            if proc.stderr:
                print(proc.stderr[-1500:])
            ok = False

    # 引擎兼容性：旧调用形状（缺 size_comp/use_lzhuf）必须仍解出正确字节。
    # 这条锁住的是"历史调用方不会因引擎演进拿到错数据"——外部审计曾推断
    # 旧散装 GUI 会因此解包乱码，实测证明引擎的兜底推断覆盖了它。
    step("run_engine_compat_probe (旧调用形状兼容)")
    ep = os.path.join(HERE, "run_engine_compat_probe.py")
    if not os.path.isfile(ep):
        print("  FAIL (run_engine_compat_probe.py 不在仓库里：门禁被删/改名了？)")
        ok = False
    else:
        proc = subprocess.run([sys.executable, ep], cwd=HERE,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)
        for ln in [x for x in (proc.stdout or "").strip().splitlines() if x.strip()][-5:]:
            print("  " + ln)
        if proc.returncode != 0:
            print("  FAIL")
            if proc.stderr:
                print(proc.stderr[-1000:])
            ok = False

    # 界面冒烟：需要桌面会话（无桌面时它自己打印 SKIP 并 exit 0）。
    # 不在 fast 档跑：它内含"ffmpeg 是否被发现"这类**环境相关**断言，在公开 CI 的
    # 裸 runner 上会以 FAIL 形式出现 —— 那不是代码缺陷，而是"这台机器没装 ffmpeg"，
    # 一刀切会让公开 CI 永久变红（同 cross_validate 的理由）。
    if mode == "fast":
        note_uncovered("run_ui_smoke（界面冒烟：Hub 装配 + 编码/XML/ffmpeg 发现）",
                       "--fast 档跳过")
    else:
        step("run_ui_smoke (界面冒烟，需要桌面与 ffmpeg)")
        us = os.path.join(HERE, "run_ui_smoke.py")
        if not os.path.isfile(us):
            print("  FAIL (run_ui_smoke.py 不在仓库里：门禁被删/改名了？)")
            ok = False
        else:
            proc = subprocess.run([sys.executable, us], cwd=HERE, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=600)
            out = proc.stdout or ""
            for ln in [x for x in out.strip().splitlines() if x.strip()][-4:]:
                print("  " + ln)
            if UI_SMOKE_SKIP_MARK in out:
                ok = prereq_missing("run_ui_smoke（界面冒烟）",
                                    "无法创建 Tk 根窗口（无桌面会话）", release) and ok
            elif proc.returncode != 0:
                print("  FAIL")
                if proc.stderr:
                    print(proc.stderr[-1500:])
                ok = False
            else:
                print("  OK")

    # Qt 试点（文件系统页）：需要 PySide6 + 桌面会话。
    # 与 cross_validate / run_ui_smoke 同一口径：公开 CI 的裸 runner 没有 PySide6，
    # 一刀切会让它永久变红，所以 fast 档跳过并记入未覆盖清单；本地/发版档按前提缺失处理。
    if mode == "fast":
        note_uncovered("run_qt_pilot_probe（Qt 试点：文件系统页 · 同引擎真实往返）",
                       "--fast 档跳过")
    else:
        step("run_qt_pilot_probe (Qt 试点，需要 PySide6 与桌面)")
        qp = os.path.join(HERE, "run_qt_pilot_probe.py")
        if not os.path.isfile(qp):
            print("  FAIL (run_qt_pilot_probe.py 不在仓库里：试点门禁被删/改名了？)")
            ok = False
        else:
            proc = subprocess.run([sys.executable, qp], cwd=HERE, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=900)
            out = proc.stdout or ""
            for ln in [x for x in out.strip().splitlines() if x.strip()][-5:]:
                print("  " + ln)
            if QT_PILOT_SKIP_MARK in out:
                ok = prereq_missing("run_qt_pilot_probe（Qt 试点）",
                                    "缺 PySide6 或无桌面会话", release) and ok
            elif proc.returncode != 0:
                print("  FAIL")
                if proc.stderr:
                    print(proc.stderr[-1500:])
                ok = False
            else:
                print("  OK")

    # Qt 试点的**冻结产物**（可复现构建 + 冻结态 Tk 解耦）：需要 PyInstaller + PySide6。
    # 它跑一次真实打包（约 1~2 分钟）并跑三次冻结 exe；`--fast` 档跳过并记入未覆盖清单。
    if mode == "fast":
        note_uncovered("run_qt_build_probe（Qt 冻结产物：0 个 Tcl/Tk · 冻结 exe 真实往返）",
                       "--fast 档跳过（要真实打包）")
    else:
        step("run_qt_build_probe (Qt 冻结产物，需要 PyInstaller 与 PySide6)")
        qb = os.path.join(HERE, "run_qt_build_probe.py")
        if not os.path.isfile(qb):
            print("  FAIL (run_qt_build_probe.py 不在仓库里：产物门禁被删/改名了？)")
            ok = False
        else:
            proc = subprocess.run([sys.executable, qb], cwd=HERE, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=3600)
            out = proc.stdout or ""
            for ln in [x for x in out.strip().splitlines() if x.strip()][-6:]:
                print("  " + ln)
            if QT_BUILD_SKIP_MARK in out:
                ok = prereq_missing("run_qt_build_probe（Qt 冻结产物）",
                                    "缺 PyInstaller/PySide6", release) and ok
            elif proc.returncode != 0:
                print("  FAIL")
                if proc.stderr:
                    print(proc.stderr[-1500:])
                ok = False
            else:
                print("  OK")

    cleanup()
    uncovered_report()
    ok = final_ok(ok, release)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
