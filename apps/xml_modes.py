# -*- coding: utf-8 -*-
"""XML 校对 — 比较模式的**贡献点**定义（内置两种模式 + 取值来源）。

这里是"贡献点"而非"挂载点"的落地：一种模式不只是往界面塞一个控件，而是给组件
增加一类能力——新增模式会同时体现在**模式下拉、表格列、筛选项、行取值与比较算法**上。

内置的两种模式（行数/ID 统计、ID 文本对比）与插件贡献的模式走**完全同一条路径**：
都注册进 `PluginManager.compare_modes`，组件侧的**列集合、筛选项、行取值**全部
由模式声明驱动，没有任何 `== MODE_TEXT` 分支。因此插件新增一种模式（例如
"归一化对比"）不需要改 app 的渲染代码。

边界要说清楚（D1，原先的说明与事实不符）：
  * app 里确实存在一处按内部键分支的地方——`_on_double_click` 曾经写
    `if r.get("mode") == "text"`，并硬取 only_a/only_b/text_diff/count_diff 等
    内置结果键；**该硬编码已删除**：完整明细现在统一走模式声明的 detail_builder，
    没有 detail_builder 时退化为通用摘要（见 xml_compare_app._full_detail）。
  * 结果里的 `mode` 字段，内置比较函数写的是内部键（"stats"/"text"），插件应写
    **注册的显示名**；列渲染不再依赖它，它只用于导出的表头等展示。
  * 因此"不改 app 一行"成立的范围是：**列、筛选项、行取值、详情渲染**都由声明驱动；
    但插件若想让详情好看，应当提供 `detail_builder`（不提供则显示通用摘要）。

模式记录的结构（见 toolkit_plugins.Api.register_compare_mode）：
    name        模式显示名（即模式下拉取值）
    columns     [(key, heading, width), ...]；key 为 "rel"/"status"/"detail" 时
                由组件通用渲染，其余按同名列取值
    compare     compare(ctx, path_a, path_b, rel) -> dict
    row_builder result -> (row_kind, differ_types)
    filters     [(标签, {row_kind}, 需要的 differ_types), ...]
    detail_builder result, name_a, name_b -> 完整明细文本（供详情栏与双击弹窗）
"""
from toolkit_plugins import (
    DEFAULT_FILTERS_STATS, DEFAULT_FILTERS_TEXT
)

# 模式名（保持与历史一致，界面下拉与既有代码引用同一份）
MODE_STATS = "行数/ID 统计"
MODE_TEXT = "ID 文本对比"

# 兼容旧引用（这些名字原先定义在 xml_compare_app 里）
MODES = [MODE_STATS, MODE_TEXT]
FILTERS_STATS = [f[0] for f in DEFAULT_FILTERS_STATS]
FILTERS_TEXT = [f[0] for f in DEFAULT_FILTERS_TEXT]

# ── 列定义：列是声明出来的，不是写死在 _build_ui 里 ──
# "detail" 是**保留列键**：组件统一渲染为单行差异摘要（模式声明的 detail_builder
# 的缩略版，见 xml_compare_app._detail_inline）。旧版就有这一列，重写时丢掉了，
# 用户因此看不到"每行的差异摘要"（A1）；宽度与旧版一致（400 / minwidth 200）。
COLUMNS_STATS = [("rel", "文件 (相对路径)", 280),
                 ("status", "状态", 60),
                 ("lines_a", "行数 A", 90),
                 ("lines_b", "行数 B", 90),
                 ("ids_a", "ID 数 A", 90),
                 ("ids_b", "ID 数 B", 90),
                 ("detail", "差异详情", 400)]

COLUMNS_TEXT = [("rel", "文件 (相对路径)", 280),
                ("status", "状态", 60),
                ("diff_count", "差异数", 90),
                ("ids_a", "ID 数 A", 90),
                ("ids_b", "ID 数 B", 90),
                ("detail", "差异详情", 400)]


# ── 行分类：把"筛选语义"显式化，从而可被声明而不是写死在 App 里 ──
def row_builder_stats(result):
    """(row_kind, differ_types)：统计模式无文本子类型。"""
    if "only_side" in result:
        return ("only_" + result["only_side"], set())
    if result.get("consistent"):
        return ("same", set())
    return ("diff", set())


def row_builder_text(result):
    """文本对比模式：区分"仅一侧有 ID"与"ID 相同但文本不同"。"""
    if "only_side" in result:
        return ("only_" + result["only_side"], set())
    if result.get("consistent"):
        return ("same", set())
    types = set()
    if result.get("only_a") or result.get("only_b"):
        types.add("only")
    if result.get("text_diff"):
        types.add("text")
    if not types:
        types.add("only")
    return ("diff", types)


# ── 比较函数：统一签名 compare(ctx, path_a, path_b, rel) ──
# 两侧显示名（name_a / name_b）**不进比较结果**：明细渲染由模式声明的
# `detail_builder(result, na, nb)` 负责（见 _detail_stats），所以这里不再
# 把名字塞给 compare_one —— 那两个形参原先收了却从不使用。
def _compare_stats(ctx, path_a, path_b, rel):
    from apps.xml_compare_app import compare_one
    return compare_one(rel, path_a, path_b,
                       enc_a=ctx.get("enc_a", "auto"), enc_b=ctx.get("enc_b", "auto"))


def _compare_text(ctx, path_a, path_b, rel):
    from apps.xml_compare_app import compare_text_content
    return compare_text_content(rel, path_a, path_b,
                                enc_a=ctx.get("enc_a", "auto"), enc_b=ctx.get("enc_b", "auto"))


def _detail_stats(result, na, nb):
    from apps.xml_compare_app import build_full_detail
    return build_full_detail(result, na, nb)


def _detail_text(result, na, nb):
    from apps.xml_compare_app import build_full_text_detail
    return build_full_text_detail(result, na, nb)


def stats_mode_spec():
    return dict(name=MODE_STATS, columns=COLUMNS_STATS, compare=_compare_stats,
                row_builder=row_builder_stats, filters=DEFAULT_FILTERS_STATS,
                detail_builder=_detail_stats, order=10, plugin="<builtin:xml>")


def text_mode_spec():
    return dict(name=MODE_TEXT, columns=COLUMNS_TEXT, compare=_compare_text,
                row_builder=row_builder_text, filters=DEFAULT_FILTERS_TEXT,
                detail_builder=_detail_text, order=20, plugin="<builtin:xml>")


def builtin_mode_specs():
    """内置模式列表（组件导入时注册一次）。"""
    return [stats_mode_spec(), text_mode_spec()]
