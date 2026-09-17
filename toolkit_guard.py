# -*- coding: utf-8 -*-
"""CI 静态守卫（验收标准 A3）

拦的是"绕过主题/绕过槽位常量表"的写法——它们**能跑**，但会让主题一致性、
插件寻址的可维护性悄悄退化，属于必须靠机器守住的纪律，不能靠记性。

零命中的写法（**必须拦住**）：
    * 颜色字面量      fg="#f14c4c" / bg="#1e1e1e"
    * 字体字面量      font=("Consolas", 10)
    * 插件槽位字面量  plugin_slot_bar(self.root, "fs", ...)   ← 应写 HOST_FS
    * 手写窗口标志    creationflags=subprocess.CREATE_NO_WINDOW

**明确不拦**（否则会误伤，守卫会被绕过或长期挂红）：
    * `color("语义角色")` —— 这是主题层的正式入口，24 处全部合法；
    * `font=color("font_mono")` / `font=T["font_mono"]` —— 取自主题；
    * 非插件调用的普通字符串。

允许行内逃生舱：在触发行追加注释 `# guard: allow`（需同时说明理由），
用于确实无法走工厂的极少数场合。
"""
import os
import re

# (规则名, 正则, 说明)
RULES = [
    ("颜色字面量", re.compile(r"""\b(?:fg|bg|foreground|background|activebackground|
                                     activeforeground|selectbackground|selectforeground|
                                     insertbackground|highlightbackground|highlightcolor|
                                     disabledforeground|fieldbackground|troughcolor)\s*=\s*["']#[0-9a-fA-F]{3,8}["']""",
                              re.X),
     "颜色必须经 color(\"角色\") 或 ttk 样式取自主题"),
    ("字体字面量", re.compile(r"""\bfont\s*=\s*\(\s*["']""", re.X),
     "字体必须取自主题（color(\"font*\")\u6216 T[\"font*\"]\uff09"),
    ("手写窗口标志", re.compile(r"creationflags\s*=\s*subprocess\.CREATE_NO_WINDOW"),
     "应使用 toolkit_platform.hidden_kwargs()"),
]

# 插件调用点：这些函数的 host 参数必须是 HOST_* 常量，不能是裸字符串。
# 注意必须同时覆盖**挂载助手**与**查询方法**——只覆盖前者会漏掉
# `option_entries_for("fs", "format")` 这类查询（本仓库自测后续扩充时发现）。
PLUGIN_CALL_RE = re.compile(
    r"\b(plugin_slot_bar|attach_plugin_context_menu|tool_panel|plugin_options_area|"
    r"plugin_entries|tool_dropdown|refresh_dropdown|"
    r"menu_items_for|options_for|option_entries_for|panels_for|find_decryptor)\s*\(")


def _constants_names(prefixes):
    """从 toolkit_plugins 常量表取挂载点名（HOST_* / AREA_* / LOC_*）——**单一真相**。

    这两条正则原先**手抄**了一份点名清单。后果：往 toolkit_plugins 里加一个新挂载点
    （`HOST_X = "x"` / `AREA_X = "x"`）时守卫不会自动覆盖它 —— 于是"新位置不许硬编码"
    这条规则对新位置静默失效，而那恰恰是守卫存在的意义。现在从表里派生。

    表取不到（依赖缺失 / 单独拷贝这个文件去跑）时退回内置清单：宁可少覆盖，也必须能跑。
    """
    try:
        import toolkit_plugins as _TP
    except Exception:
        return ()
    out = set()
    for k, v in vars(_TP).items():
        if isinstance(v, str) and any(k.startswith(p) for p in prefixes):
            out.add(v)
    return tuple(sorted(out))


HOST_POINT_NAMES = _constants_names(("HOST_",)) or ("fs", "convert", "text", "xml", "video", "font")
AREA_POINT_NAMES = _constants_names(("AREA_", "LOC_")) or (
    "top_bar", "bottom", "format", "pack_format", "source_enc", "game", "lang",
    "size", "suffix", "filter", "toolbar", "context")

RAW_HOST_RE = re.compile(r"""["'](?:%s)["']"""
                         % "|".join(re.escape(n) for n in HOST_POINT_NAMES))
RAW_AREA_RE = re.compile(r"""["'](?:%s)["']"""
                         % "|".join(re.escape(n) for n in AREA_POINT_NAMES))

def _call_args_window(lines, start_idx, max_lines=6):
    """取出 start_idx 行里那次插件调用的**实参文本**（括号配平，含跨行）。

    只看实参本身，不看后续语句——否则紧随其后的 `context={"loaded": True}`
    会被误判成"硬编码槽位"（这是本仓库真实踩过的误伤）。
    """
    text = ""
    depth = 0
    seen_open = False
    for j in range(start_idx, min(len(lines), start_idx + max_lines)):
        seg = lines[j]
        if not seen_open:
            k = seg.find("(")
            if k < 0:
                continue
            seg = seg[k:]
            seen_open = True
        text += seg
        depth += seg.count("(") - seg.count(")")
        if seen_open and depth <= 0:
            break
        text += " "
    return text


ALLOW_COMMENT = "guard: allow"


def _iter_app_files(apps_dir):
    """只扫**活代码**：apps/ 下的 .py（apps/ 内一般没有历史副本，
    这里仍显式跳过 __pycache__，与其它审计脚本口径一致）。"""
    for dp, dn, fn in os.walk(apps_dir):
        dn[:] = [d for d in dn if d not in ("__pycache__", "builds", "backup", "temp")]
        for f in sorted(fn):
            if f.endswith(".py"):
                yield os.path.join(dp, f)


def check_apps(apps_dir):
    """扫描 apps/*.py，返回 [(相对路径, 行号, 规则名, 说明, 行内容), ...]。"""
    problems = []
    for path in _iter_app_files(apps_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
        rel = os.path.relpath(path, os.path.dirname(apps_dir))
        for i, raw in enumerate(lines, 1):
            line = raw.rstrip("\n")
            if ALLOW_COMMENT in line:
                continue
            for name, rx, why in RULES:
                if rx.search(line):
                    problems.append((rel, i, name, why, line.strip()))
            # 插件调用点：只检查该次调用的实参里有没有裸 host/area 字符串
            if PLUGIN_CALL_RE.search(line):
                window = _call_args_window(lines, i - 1)
                if RAW_HOST_RE.search(window) or RAW_AREA_RE.search(window):
                    problems.append((rel, i, "硬编码槽位",
                                     "host/area 必须用 HOST_*/AREA_* 常量",
                                     line.strip()))
    return problems


def format_problems(problems):
    out = []
    for rel, ln, name, why, text in problems:
        out.append(f"  {rel}:{ln}  [{name}] {why}")
        out.append(f"      {text}")
    return "\n".join(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    problems = check_apps(os.path.join(here, "apps"))
    if not problems:
        print("  OK")
        return 0
    print(f"  发现 {len(problems)} 处违反主题/槽位纪律的写法：")
    print(format_problems(problems))
    print("  （确需例外时在该行加注释 `# guard: allow` 并说明理由）")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
