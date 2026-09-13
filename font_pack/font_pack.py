# -*- coding: utf-8 -*-
"""
汉化包生成引擎 — CN_Pack_Generator 的 Python 重写
功能: 从汉化 XML 提取字符集 → 渲染字库纹理(DDS) → 组装 gamedata 汉化包
依赖: Pillow (缺失时自动安装)
"""
import os, sys, struct, unicodedata, math

# ─── 游戏版本配置 ───
GAMES = {
    "SoC":  {"cfg_dir": "config",  "dds": "8888"},
    "ClS": {"cfg_dir": "configs", "dds": "8888"},
    "CoP":  {"cfg_dir": "configs", "dds": "A8"},
}

# ─── 字号表: (字号, 是否超采样x2) ───
SIZES = [(11, 0), (13, 0), (15, 0), (16, 1), (17, 1), (18, 1),
         (20, 1), (21, 1), (23, 1), (25, 1)]

# 强制方块字符 (EAW 为 A 但中文语境全角, 原版按字号+1)
FORCED_FULLWIDTH = set("\u201c\u201d\u2018\u2019\u2014\u2016")  # “ ” ‘ ’ — ‖


# ─── 与原版产物的对应关系（2026-09 实测核对，勿凭印象改） ───
# CELL_HEIGHTS = 各字号槽位的 cell 高，也就是写进 .ini 的 `height=` 值（引擎用它算行高）。
#
# ⚠ 它**不是** FontGen 的 PhysicalHeight。FontGen 一行一次调用，cell 高是命令行参数
#   （Generator.bat 105-114 行）：11→15, 13→16, 15→19, 16→20, 17→22, 18→23, 20→25,
#   21→26, 23→29, 25→31；`Tools\otherTools\CN_Pack_Generator\gamedata\textures\ui\
#   ui_font_NN.ini` 的 height= 与之逐一吻合，可作旁证。
#
# 本表取自**汉化包生成工具2024**的产物 `...\Tool\汉化包生成工具2024\gamedata\
# textures\ui\ui_font_NN_chs.ini` 的 height= ——10 个尺寸全部逐一相符，这才是本工具
# 要复现的对象（本模块就是那个工具的 Python 重写）。同批核对还确认：
#   * adv_tables.json 的宽度 == 那些 ini 里 (x2-x1)，覆盖到的码位 102/102 全等；
#   * 布局公式 (x1-(cell-宽)//2) % cell == 0 对 10 个尺寸 × 3428 行**全部成立**，
#     且 y1 恒为 cell 的整数倍 → 槽位网格 + 居中（无垂直偏移）与本模块一致；
#   * 图集尺寸（2048x1024 / 2048x2048 / 4096x2048）与本模块的行列算法逐一吻合。
# 反向对照：与 CN_Pack_Generator 的原版 FontGen 产物匹配率 0/124 → 本表与 FontGen 无关。
CELL_HEIGHTS = {11: 20, 13: 22, 15: 23, 16: 25, 17: 26, 18: 29, 20: 31, 21: 32, 23: 33, 25: 35}

# 渲染字号**不在**上表时（GUI 的「尺寸 +N」就是这条路径：渲染字号 = 槽位名 + N，
# 文件名/ltx 仍用槽位名）的 cell 高比例。
#
# ⚠ 旧写法是 `CELL_HEIGHTS.get(size, size + 4)`，即兜底只有 1.0×+4px —— 实测
# （msyh/simsun/simhei × 481 字符 × 10 槽位 × 档位 0/3/5/7/9）墨迹下沿 top+gh 最高
# 达 **1.364 × 渲染字号**（rsize=22 → 30px），于是兜底下的 rsize
# 14/19/22/24/26/27/28/29/30/32/34 分别溢出 1/2/4/4/4/4/5/5/6/6/7 px：
# 越出的墨迹落进**下一行**的槽位，游戏里正是「分划把上面那个字的底部也划进去了」。
#   rsize  14 19 22 24 26 27 28 29 30 32 34
#   需要   19 25 30 32 34 35 37 38 40 42 45   （实测 max(top+gh)）
#   旧用   18 23 26 28 30 31 32 33 34 36 38   → 差 -1 -2 -4 -4 -4 -4 -5 -5 -6 -6 -7
# 取 1.40 = 本表自身的最大比例（CELL_HEIGHTS[25]/25 = 35/25），且 ≥ 实测所需的 1.364。
# 表内字号**必须**走表（那是从原版成品反推、被探针钉死的几何），只有表外才按比例。
CELL_HEIGHT_RATIO = 1.40


def cell_height_for(rsize):
    """渲染字号 → 槽位高 cell（也就是写进 .ini 的 `height=`，引擎据此算行高）。

    表内字号走 CELL_HEIGHTS；表外（「尺寸 +N」）按 CELL_HEIGHT_RATIO 放大，
    否则槽位装不下墨迹（见 CELL_HEIGHT_RATIO 上方实测）。
    """
    return CELL_HEIGHTS.get(rsize) or int(math.ceil(rsize * CELL_HEIGHT_RATIO))


# 方块字符（汉字/全角标点）的宽度：同样来自上面那批产物，查表以避免字体 advance 差异。
# ⚠ 遗留差异（已实测、待决策，勿在未确认前"顺手修正"）：原版 ui_font_11_chs 图集里
# '你' 的墨迹高 15px（同尺寸另测 'A' 12x13），对应渲染字号约 16 = FontGen 的 (16,20,20) 行；
# 而 SIZES 用的是槽位名本身（11），即按 FontSize 11 渲染进 20px 高的 cell。10 个尺寸的
# 实测墨迹高依次为 15,16,18,19,22,25,30，均≈cell-5，而本模块渲染字号为 11,13,15,16,18,21,25
# → 字形约小 30%（槽位/宽度/行高都对齐，只有墨迹偏小）。
# 修法不是改 offset（offset 会同时改 rsize 与 cell：现在走 cell_height_for(rsize)，
# 连 cell 一起变，反而破坏上面的对齐），而是需要"槽位名 → 渲染字号"两张表分离。
# 属几何变更，需先与实际成品图集 A/B 比对后再动。
BLOCK_WIDTHS = {11: 17, 13: 18, 15: 19, 16: 21, 17: 22, 18: 24, 20: 26, 21: 27, 23: 29, 25: 31}

# ─── 中文标点收窄（用户要求：原版方块宽度偏宽，尾部留白尤其大）───
# 用户口径（2026-09 决定）：**逐字按实测留白、只收空白那一侧，使墨迹两侧留白尽量均衡**，
# 任何情况下不得裁到墨迹。本模块据此实现，三条实测前提：
#
# 1) **tl 与 tr 在画面上等价，且只有右留白能被收掉**：字形贴在**收窄后**的框起点上
#    （`x = col*cell + (cell-rw0)//2 + tl`，`paste(glyph, (x+left, ...))`），框起点右移
#    多少墨迹就跟着右移多少 → 墨迹在框内的偏移恒为 `left`。引擎只采样 [x1,x2)
#    （OGSR `dxFontRender.cpp:99-111`：`tu = l.x/vTS.x`、`fTCWidth = l.z/vTS.x`），
#    所以能减的只有右留白；左留白（字体的设计内缩）只能原样保留。于是"只收空白侧"
#    在本引擎里 = **只收右**，且收窄量 ≤ 实测右留白 = 永不裁墨迹（硬保证，非经验值）。
#
# 2) 每类收掉多少"实测右留白"（= PUNCT_TRIM_BLANK）：
#      * open  开括号/左引号（（）【「『《〈〔［｛“‘）：墨迹按设计靠框右，右侧留白就是与
#        **框内正文**之间的空档 → 全收（1.0），括号因此贴住被括住的字。
#        例：slot 11 的「（」，rw0=17、左留白(mb[0]) 7、墨宽 3、右留白 7 → 收 7 → 字距 10。
#      * close 闭括号/右引号（)）】」』》〉〕］｝”’）：墨迹按设计靠框左（左留白仅 1–2px，
#        已经贴着被括住的字），右侧那段留白按同一口径全收（1.0）→ 两侧留白对齐。
#        例：slot 11 的「）」，左留白 1、右留白 13 → 收 12 → 字距 5（左 1 / 右 1）。
#        想保留原版那样"括回之后的空档"，把这个 1.0 调小即可（0 = 完全不收）。
#      * single 句读（。，、；：！？）：墨迹偏左下，右留白 8–13px（slot 11 / rw0=17）；
#        全收会把标点粘到后一个字上，故默认收一半（0.5）—— 想更紧就调大、想保留原版
#        节奏就调到 0，**一个数字**即可。
#      * wide 满框符号（…·—～）：墨迹几乎铺满框（右留白 0–4px），保守起见不收（0.0）。
#    没有该字形的字体（tahoma/arial 等画 .notdef 方框）不参与定标，方框留白与标点无关。
#
# 3) 括号真正的问题不只是"宽"，还有**墨迹被锚到了框左沿**（见 render_font 的水平锚点
#    注释）：参考成品里「（」的墨迹在框内偏右 10px，我们改前恒为 0 → 游戏里就是
#    「( 丁达尔效应)」那种"（ 后面一个大空档"（用户报的「成对标点分划错误」）。
PUNCT_OPEN = set("（【「『《〈〔［｛“‘")
PUNCT_CLOSE = set("）】」』》〉〕］｝”’")
PUNCT_SINGLE = set("。，、；：！？")
PUNCT_WIDE = set("…·—～")
# 每类**墨迹两侧各留多少 px**（2026-09 依实测参照包改成对称口径）。
#
# 旧口径是 PUNCT_TRIM_BLANK（按比例只收**右**留白），实测出两个问题：
#   * 「（」的墨迹按字体设计内缩 7–10px 靠框右，只收右留白 → 框内左侧留着一大块空档，
#     游戏里就是「光束 （丁达尔」那种"标点前面一片空白"；
#   * 「·」的宽度表值是 16px（参照包实测只有 5px），而 wide 类旧比例是 0.0（完全不收）
#     → 一个中圆点占了将近一个字宽。
# 新口径：**两侧留白各自收敛到 min(原留白, PAD)** —— 墨迹在框内左右对称、永不裁墨、
# 且框宽 ≤ 原宽（恒不放大）。想更紧/更松只改这一个数。
PUNCT_PAD_PX = {"open": 3, "close": 3, "single": 3, "wide": 3}


def punct_class(ch):
    """标点类别名（'open' / 'close' / 'single' / 'wide'）；非标点返回 None。"""
    if ch in PUNCT_OPEN:
        return "open"
    if ch in PUNCT_CLOSE:
        return "close"
    if ch in PUNCT_SINGLE:
        return "single"
    if ch in PUNCT_WIDE:
        return "wide"
    return None


def punct_box_px(ch, rw0, left, gw):
    """该字符虚拟框的 (墨迹在框内的左偏移, 框宽)；非标点 / 无墨迹原样返回 (left, rw0)。

    `left` = 墨迹在字形 advance 内的设计内缩（= render_font 的墨迹锚点），`gw` = 墨迹宽，
    原右留白 = rw0 - left - gw。标点两侧留白各自收敛到 min(原留白, PAD)：
        左偏移 = min(left, PAD)、右留白 = min(rw0-left-gw, PAD)
    ⇒ 框宽 = 左偏移 + gw + 右留白 ≤ rw0（**恒不放大**），两侧对称，且墨迹永不越框
    （左偏移 ≤ left、右留白 ≤ 原右留白 是两条硬不等式，不是经验值）。
    非标点走同一公式但 PAD = ∞ 的效果：直接返回原值，行为与改动前完全一致。
    """
    cls = punct_class(ch)
    if cls is None or gw < 1:
        return left, rw0
    pad = PUNCT_PAD_PX[cls]
    # ★ **两侧取同一个数**：min(左留白, 右留白, PAD)。
    #   旧写法是两侧各自 min(原留白, PAD)，于是原始留白比 PAD 小的那一侧就压不下去，
    #   两侧不等 —— 用户报的"双引号的对称有点小问题"就是它（” 左 2 / 右 3）。
    #   取共同值后左右恒等（这是构造性保证，不是调参），代价是宽度由窄的那一侧决定，
    #   只可能更窄：m + gw + m ≤ 原宽仍成立（m ≤ 两侧留白各自的值）。
    pr0 = rw0 - left - gw
    m = max(0, min(left, pr0, pad))
    return m, max(1, m + gw + m)

# FontGen 内置字符集中的生僻汉字 (原版 Char.txt 编码 bug 丢失后由内置集补充)
FONTGEN_EXTRA = set("屑懈挟衼袗袘袙袚袛袝袞袟袠袡袣袥袦袧袨袩袪褉褋褌褍褎褏褑褔褕褖褗褘褜褝褞褟褢")

# 原版 CharAdder 编码 bug 丢失的西里尔 (仅"复刻旧包"模式下剔除)
#
# ⚠ 剔除它们极危险，**不要**当默认：引擎对缺失码位不是留空，而是
# `TCMap[i] = vFirstValid`（OGSR `xr_3da\GameFont.cpp:130`）——把整张表填成
# **同一个字形**。实测本集合含 40 个**最常用**俄文字母
# （г в е и к л н о п р с т у х ц ч ш ы ь э ю 及大写 Г Й Ф Х Ц Ч Ш Щ Э Ю 等），
# 在俄文模组（NLC 等）里几乎每个未翻译的字符串都会命中 → 满屏重复字形。
LOST_CYRILLIC = set("ГЙФХЦЧШЩЭЮбвгдежзийклмнопрстуфхцчшщъыьэю")

# 引擎 `[features] enable_ansi_aupport_for_mb_fonts`（默认开，
# `GameFont.cpp:140-167`）会把 CP1251 的这些字节映射到下列 Unicode 槽位；
# 槽位缺失同样落到 vFirstValid，所以必须随字库一起提供。
ANSI_BRIDGE = set("\u0401\u0451\u2116\u2014\u0490\u0491\u0404\u0454\u0406\u0456\u0407\u0457")

# 完整西里尔块 U+0410–U+04FF：除基础俄文字母外还含 ЂЃЄЅІЇЈЉЊЋЌЎЏ / ђѓєѕіїјљњћќўџ 等，
# 俄语、乌克兰语模组与 mod 自带串都可能出现。整个块一起收，成本只是几行槽位。
CYRILLIC_BLOCK = set(chr(c) for c in range(0x0410, 0x0500))

# 任何情况下都必须进字库的字符集 = ASCII/俄文基础 + 完整西里尔块 + ANSI 桥接目标。
# 定义放在 ASCII_CHARS 之后（它依赖 ASCII_CHARS）。可多不可少 —— 少一个即一次重复字形。

def _load_adv_tables():
    """从同目录 adv_tables.json 读取各字号的字符宽度表。"""
    import json as _json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adv_tables.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
    except Exception as e:
        raise RuntimeError(f"无法加载字体宽度表 {path}: {e}")
    return {int(size): {int(cp): w for cp, w in table.items()}
            for size, table in raw.items()}


ADV_TABLES = _load_adv_tables()


# ASCII + 俄语基础字符 (对应原 _ascii_char.txt)
ASCII_CHARS = (' !"#$%&\'()*+,-./0123456789:;<=>?@'
               'ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`'
               'abcdefghijklmnopqrstuvwxyz{|}~'
               'АаБбВвГгДдЕеЁёЖжЗзИиЙйКкЛлМмНнОоПпРрСсТтУуФфХхЦцЧчШшЩщъЫыьЭэЮюЯя')

# 字库的下限：ASCII/俄文基础 + 完整西里尔块 + ANSI 桥接目标（见上方各集合的说明）。
# 少任何一个码位 → 引擎把它画成"同一个重复字形"。故意多收，成本只是几行槽位。
REQUIRED_CHARS = (ASCII_CHARS + "".join(sorted(CYRILLIC_BLOCK))
                  + "".join(sorted(ANSI_BRIDGE)))

# ─── fonts.ltx 模板 ───
FONTS_LTX = {
"SoC": """[stat_font]
shader 			= font
texture			= ui\\ui_font_hud_01
interval		= 0.75,1

[hud_font_small]:stat_font

[hud_font_medium]
shader 			= font
texture			= ui\\ui_font_hud_02

[hud_font_di]
shader 			= font
texture			= ui\\ui_font_console_02

[ui_font_arial_14]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_13

;not used
[ui_font_arial_21]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_13
texture1600		= ui\\ui_font_17

[ui_font_graffiti19_russian]
shader			= font
texture			= ui\\ui_font_16
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_17

[ui_font_graffiti22_russian]
shader			= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_16
texture1600		= ui\\ui_font_20

[ui_font_graff_32]
shader			= font
texture			= ui\\ui_font_18
texture800		= ui\\ui_font_17
texture1600		= ui\\ui_font_21

;not used
[ui_font_graff_40]
shader			= font
texture			= ui\\ui_font_21
texture800		= ui\\ui_font_18
texture1600		= ui\\ui_font_23

[ui_font_graff_50]
shader			= font
texture			= ui\\ui_font_23
texture800		= ui\\ui_font_21
texture1600		= ui\\ui_font_25

[ui_font_letterica16_russian]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_15

[ui_font_letterica18_russian]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_16

[ui_font_letter_25]
shader			= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_20

""",
"ClS": """[stat_font]
shader 			= font
texture			= ui\\ui_font_hud_01
interval		= 0.75,1

[hud_font_small]:stat_font

[hud_font_medium]
shader 			= font
texture		= ui\\ui_font_hud_02

[hud_font_di]
shader 			= font
texture			= ui\\ui_font_console_02

[hud_font_di2]
shader 			= hud\\font2
texture			= ui\\ui_font_console_02

[ui_font_arial_14]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_13

;not used
[ui_font_arial_21]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_13
texture1600		= ui\\ui_font_17

[ui_font_graffiti19_russian]
shader			= font
texture			= ui\\ui_font_16
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_17

[ui_font_graffiti22_russian]
shader		= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_16
texture1600		= ui\\ui_font_20

[ui_font_graff_32]
shader			= font
texture			= ui\\ui_font_18
texture800		= ui\\ui_font_17
texture1600		= ui\\ui_font_21

;not used
[ui_font_graff_40]
shader			= font
texture			= ui\\ui_font_21
texture800		= ui\\ui_font_18
texture1600		= ui\\ui_font_23

[ui_font_graff_50]
shader			= font
texture			= ui\\ui_font_23
texture800		= ui\\ui_font_21
texture1600		= ui\\ui_font_25

[ui_font_letterica16_russian]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
;texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_15

[ui_font_letterica18_russian]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_16

[ui_font_letter_25]
shader			= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_20

""",
"CoP": """[stat_font]
shader 			= font
texture			= ui\\ui_font_hud_01
interval		= 0.75,1

[hud_font_small]:stat_font

[hud_font_medium]
shader 			= font
texture			= ui\\ui_font_hud_02

[hud_font_di]
shader 			= hud\\font
texture			= ui\\ui_font_console_02

[hud_font_di2]
shader 			= hud\\font2
texture			= ui\\ui_font_console_02

[ui_font_arial_14]
shader			= hud\\font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_13

;not used
[ui_font_arial_21]
shader			= hud\\font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_13
texture1600		= ui\\ui_font_17

[ui_font_graffiti19_russian]
shader			= hud\\font
texture			= ui\\ui_font_16
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_17

[ui_font_graffiti22_russian]
shader			= hud\\font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_16
texture1600		= ui\\ui_font_20

[ui_font_graff_32]
shader			= hud\\font
texture			= ui\\ui_font_18
texture800		= ui\\ui_font_17
texture1600		= ui\\ui_font_21

;not used
[ui_font_graff_40]
shader			= hud\\font
texture			= ui\\ui_font_21
texture800		= ui\\ui_font_18
texture1600		= ui\\ui_font_23

[ui_font_graff_50]
shader			= hud\\font
texture			= ui\\ui_font_23
texture800		= ui\\ui_font_21
texture1600		= ui\\ui_font_25

[ui_font_letterica16_russian]
shader			= hud\\font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_15

[ui_font_letterica18_russian]
shader			= hud\\font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_16

[ui_font_letter_25]
shader			= hud\\font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_20
""",
}

LOCALIZATION_LTX = {
"SoC": """[string_table]
language\t= #LANG#
font_prefix\t= _#LANG#
files = ui_st_pda, ui_st_mm_mp, ui_st_inventory, string_table_tutorial, string_table_general, string_table_includes, stable_dialog_manager, stable_dialog_manager_uni, stable_task_manager, stable_treasure_manager, string_table_level_tips, string_table_items, string_table_ui, string_table_enc_zone, string_table_outfit, stable_dialogs, stable_dialogs_escape, stable_dialogs_garbage, stable_dialogs_agroprom, stable_dialogs_deadcity, stable_dialogs_darkvalley, stable_dialogs_pripyat, stable_dialogs_labx18, stable_dialogs_bar, stable_dialogs_military, stable_dialogs_yantar, stable_dialogs_radar, stable_dialogs_aes, mp_st_speechmenu, ui_st_keybinding, ui_mp_teamdesc, ui_st_mm, stable_stories, ui_st_mapdesc, string_table_enc_social, string_table_enc_mutants, string_table_enc_weapons, string_table_enc_equipment, ui_st_mp, ui_st_other, stable_game_credits
""",
"ClS": """[string_table]
language        = #LANG#
font_prefix     = _#LANG#
""",
"CoP": """[string_table]
language        = #LANG#
font_prefix     = _#LANG#
""",
}


def _pillow_available():
    """PIL 是否可导入（只探测，不引入名字，因此无"未用导入"）。"""
    import importlib.util
    try:
        return importlib.util.find_spec("PIL.Image") is not None
    except (ImportError, ValueError):
        return False


def ensure_pillow():
    """Pillow 缺失时自动安装."""
    if _pillow_available():
        return True
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "pillow"],
                       capture_output=True, timeout=180,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        # 安装后重新探测（子进程写入 site-packages，需刷新 finder 缓存）
        import importlib
        importlib.invalidate_caches()
        return _pillow_available()
    except Exception:
        return False


def extract_chars(xml_dir, full_cyrillic=True):
    """扫描 xmlfiles 目录, 提取所有文本字符, 返回去重字符表.
    full_cyrillic=False 时剔除原版丢失的西里尔 (严格兼容原版).
    文本解析复用 toolkit.parse_xml_texts (无 toolkit 时自包含回退).

    编码**必须**走与 build_package 同一条判定链 (`_decode_xml_bytes`)。
    这里曾经写死 `raw.decode("utf-8-sig", "ignore")`：对 GBK/GB18030 源
    （中文汉化包最常见的源编码，也是原版 CharAdder 在中文 Windows 上的
    `Encoding.Default` 行为，见其帮助文本"仅支持 GB18030 与带 BOM 的
    Unicode"）会**静默丢字**——实测一个 GBK 源里的中文
    '你好世界，潜行者。测试' 11 个字全部提取不到。后果不是报错，而是
    字库里**没有这些字**，游戏内显示为空白/回退字符，且日志里毫无痕迹。
    `errors="ignore"` 还让这种丢失无法被察觉。

    注意这不是"改行为"：原版 FontGen 读 GBK(ANSI) 本来就正确、在俄文模组
    （NLC 等）下也不出乱码；本函数此前反而与它不一致。对 **UTF-8 源**，
    改前改后提取结果逐字符相同（回归无变化），只影响非 UTF-8 源。"""
    # 注意: sys.path 上可能有**同名但缺该函数**的 toolkit, 此时光是 ImportError
    # 不够——访问属性会抛 AttributeError 直接崩掉 extract_chars。用 getattr 兜底。
    try:
        import toolkit as _toolkit
    except ImportError:
        _toolkit = None
    _parse_xml = getattr(_toolkit, "parse_xml_texts", None) or _local_parse_xml_texts
    chars = set(REQUIRED_CHARS)
    if not os.path.isdir(xml_dir):
        return None
    # **递归**扫描：原版 CharAdder 用的就是 `for /r` 递归扫整个文本树
    # （Generator.bat:75）。只扫顶层会漏掉子目录里的 XML → 那些字符不进字库 →
    # 引擎把它们画成**重复的同一个字形**（见 LOST_CYRILLIC 上方注释）。
    targets = []
    for dirpath, _dirnames, filenames in os.walk(xml_dir):
        for name in sorted(filenames):
            if name.lower().endswith(".xml"):
                targets.append(os.path.join(dirpath, name))
    # 判不准的编码**聚合告警**（不逐文件刷屏）：西里尔源（NLC 等俄文模组）通常
    # 不写 XML 声明，`sniff_encoding` 会落到 windows-1251 这个终局默认值 —— 那是
    # **按设计**的判定，逐文件告警会把日志刷满，反而没人看。但也不能静默：
    # 字库里少字是看不见的故障，所以出来后汇总一条，附文件名与计数。
    guessed = []
    undecodable = []
    for fp in targets:
        fn = os.path.basename(fp)
        try:
            with open(fp, "rb") as f:
                raw = f.read()
            text, enc, trusted = _decode_xml_bytes(raw)
            if text is None:
                undecodable.append(fn)
                continue
            if not trusted:
                guessed.append((fn, enc))
            texts = _parse_xml(text)
        except Exception:
            continue
        for t in texts:
            for ch in t:
                if ch in "\r\n":
                    continue
                cp = ord(ch)
                if cp < 0x20 and ch != "\t":
                    continue
                if 0xD800 <= cp <= 0xDFFF:
                    continue
                chars.add(ch)
    if guessed:
        detail = ", ".join("%s(%s)" % (n, e) for n, e in guessed[:5])
        more = "" if len(guessed) <= 5 else " 等 %d 个" % len(guessed)
        _log_shared("字符集提取：%d 个 XML 的编码无法确定，已按探测结果解出（%s%s）。"
                    "若成品少字，请确认这些文件的原始编码" % (len(guessed), detail, more),
                    "warn")
    if undecodable:
        _log_shared("字符集提取：%d 个 XML 无法解码，已跳过（%s）"
                    % (len(undecodable), ", ".join(undecodable[:5])), "warn")
    chars |= FONTGEN_EXTRA
    if not full_cyrillic:
        # 仅"复刻旧包"模式：剔除原版 CharAdder 因编码 bug 丢掉的 40 个**常用**西里尔。
        # 引擎对缺失码位不是留空，而是 `TCMap[i] = vFirstValid`（同一个字形），
        # 所以在含未翻译俄文的目标上这等于满屏乱码 —— 必须显式告警，不许静默。
        chars -= LOST_CYRILLIC
        _log_shared(
            "字库按「复刻旧包」模式剔除了 %d 个常用西里尔字母（г в е и к л н о п р с т у 等）。"
            "引擎对缺失码位会画成**重复的同一个字形**：目标若含未翻译的俄文（NLC 等俄文模组），"
            "会出现满屏方块/重复字形 —— 请改选「完整西里尔」" % len(LOST_CYRILLIC), "warn")
    return "".join(sorted(chars))


def _local_parse_xml_texts(text):
    """自包含回退: ET 优先, 正则回退 (与 toolkit.parse_xml_texts 相同)."""
    import re as _re
    import xml.etree.ElementTree as ET
    try:
        return list(ET.fromstring(text).itertext())
    except Exception:
        strip = _re.compile(r"<[^>]+>")
        out = []
        for m in _re.finditer(r"<text[^>]*>(.*?)</text>", text, _re.S):
            out.append(strip.sub("", m.group(1)))
        for m in _re.finditer(r"<string[^>]*>(.*?)</string>", text, _re.S):
            out.append(strip.sub("", m.group(1)))
        return out


def write_dds(path, w, h, fmt, data):
    """写 DDS. fmt: '8888' = 32bpp BGRA, 'A8' = 8bpp alpha."""
    if fmt == "8888":
        pitch = w * 4
        pf = struct.pack("<8I", 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
        flags = 0x1007
    else:
        pitch = w
        pf = struct.pack("<8I", 32, 0x2, 0, 8, 0, 0, 0, 0xFF)
        flags = 0x1007
    hdr = (b"DDS " + struct.pack("<7I", 124, flags, h, w, pitch, 0, 0) +
           b"\0" * 44 + pf + struct.pack("<I", 0x1000) + b"\0" * 16)
    with open(path, "wb") as f:
        f.write(hdr + data)


def render_font(chars, font_path, size, x2, fmt):
    """渲染一个字库: 返回 (dds_bytes, ini_text, tex_w, tex_h, max_y).
    布局 = 原版 FontGen 网格: 槽宽=cell高, 每行槽数=tex_w//槽宽,
    字符在槽内水平居中 (x1 = col*槽宽 + (槽宽-字符宽)//2).
    宽: 1024 若行数*cell 放得下, 否则自动放大 2048 → 4096.
    高: 2 幂 ≥ (max_y-1)."""
    from PIL import Image, ImageFont
    S = 2 if x2 else 1
    font = ImageFont.truetype(font_path, size * S)
    cell_h = cell_height_for(size)  # 槽宽 = cell 高；表外字号按比例（见 CELL_HEIGHT_RATIO）
    # 垂直锚点：把字体 em 盒的**底部**对齐行带底部（= 参照包实测规则：降部贴带底、
    # 基线上方恰好留 descent）。旧实现把墨迹钉在行带顶部（top = bbox[1]），实测比参照包
    # 整体高 3–9px，且「。」这类句读被画到行中部而不是贴基线 —— 用户报的"没对称"。
    _asc, _desc = font.getmetrics()
    vshift = max(0, cell_h - (_asc + _desc) // S)
    adv_table = ADV_TABLES.get(size, {})

    def widths_of(ch):
        cp = ord(ch)
        if cp in adv_table:
            return adv_table[cp]
        if unicodedata.east_asian_width(ch) in "FW" or ch in FORCED_FULLWIDTH:
            return BLOCK_WIDTHS.get(size, size + 2)
        adv = font.getlength(ch) / S
        return max(1, round(adv) + 1)

    # 先确定画布宽: 1024 → 2048 → 4096，保证大字号/大字符集放得下
    tex_w = 1024
    slots = tex_w // cell_h
    rows_n = (len(chars) + slots - 1) // slots
    for candidate in (2048, 4096):
        if rows_n * cell_h - 1 <= tex_w:
            break
        tex_w = candidate
        slots = tex_w // cell_h
        rows_n = (len(chars) + slots - 1) // slots
    if rows_n * cell_h - 1 > tex_w:
        raise RuntimeError(f"字库 {tex_w} 宽放不下 {len(chars)} 字符")

    # 布局 + 渲染
    max_y = rows_n * cell_h
    need = max(1, max_y - 1)
    tex_h = 16
    while tex_h < need:
        tex_h *= 2
    canvas = Image.new("L", (tex_w, tex_h), 0)
    ini = []
    clipped = 0
    for i, ch in enumerate(chars):
        rw0 = widths_of(ch)
        col = i % slots
        row = i // slots
        y = row * cell_h
        bbox = font.getbbox(ch)
        mask = font.getmask(ch, mode="L")
        mb = mask.getbbox()
        gw = gh = 0
        if mb is not None:
            gw = (mb[2] - mb[0]) // S
            gh = (mb[3] - mb[1]) // S
        # 标点收窄要**实测墨迹**（设计内缩 left、墨宽 gw）才能算两侧留白，
        # 所以这一句放在量完 mask 之后（见 punct_box_px / PUNCT_PAD_PX）。
        left0 = (mb[0] // S) if mb is not None else 0
        pl, rw = punct_box_px(ch, rw0, left0, gw)
        # ★ 框不得比墨迹窄（宽度表个别码位偏窄：U+0483–86 表值 1px 而墨迹 4–9px、
        #   U+00AD 表值 0）。判据在 clamp_box_to_ink 里，探针调用同一个函数。
        rw = clamp_box_to_ink(pl, rw, gw)
        # 框起点**左移 pl**：墨迹在图集中的绝对位置保持不变，改变的只是"从哪儿开始采样"。
        # 引擎只按 [x1,x2) 取样再画到笔位，所以墨迹在屏上的偏移就等于 pl —— 于是
        # "标点两侧留白对称"这件事完全由 pl 决定（旧实现只动 x2，左侧那圈设计留白动不了）。
        x = col * cell_h + (cell_h - rw0) // 2 + left0 - pl
        if mb is not None:
            if gw >= 1 and gh >= 1:
                glyph = Image.frombytes("L", mask.size, bytes(mask)).crop(mb)
                if S > 1:
                    glyph = glyph.resize((gw, gh), Image.LANCZOS)
                top = bbox[1] // S + vshift
                # 装不下就**整体上移**，绝不从底部裁墨 —— 旧实现的 clip_bot 会啃掉字的
                # 底边，那正是"所有字的底部一丢丢边被吞"的机制。上移到顶仍装不下才裁顶。
                if top + gh > cell_h:
                    top -= (top + gh - cell_h)
                # ★ 水平锚点 = 墨迹在字形 advance 内的**设计内缩**（mask.bbox[0]），不是
                #   `getbbox()[0]`：getbbox 的水平范围是**布局**范围（左边距→advance），对
                #   全角标点恒为 0，拿它当左偏移会把墨迹锚到框左沿、丢掉字体的设计内缩。
                #   参考成品（`汉化包生成工具2024` 的 ui_font_11_chs.dds/ini —— 本模块要复现
                #   的对象）实测框内墨迹偏移：（=10 ）=1 “=10 ”=1 。=1 ，=2 、=1 ？=1 一/丁/A=0。
                #   这个内缩现在由 punct_box_px 统一裁决：标点收敛到 min(内缩, PAD)（对称），
                #   非标点原样保留；框起点随之左移 pl（见上面 x 的算法）。
                #
                # 纵向：**不是**"按字体自然位置落槽"（那种写法把墨迹钉在行带顶部）。实测参照包
                #   （同槽位、同 DDS 口径）的墨迹是"em 盒底贴行带底"：降部到带底、基线上方留
                #   descent、汉字上 3–4px / 下 2px。我们旧写法是汉字上 0–1px / 下 9px、句读被画
                #   到行中部（参照贴基线），用户一眼看出"没对称"。故统一加 vshift（见函数开头）。
                # 上面那句"max(top+gh) <= cell_h 对所有字体/字号成立"只在**表内字号**
                # 成立；「尺寸 +N」走 cell_height_for 的比例兜底（已实测修好，见其注释），
                # 而 Latin 字体在表内字号仍可能有 top<0（consola 的 '|' 在 25 号实测 -5px）。
                # 下面把墨迹裁进自己的行带 = 契约兜底：行带 [y, y+cell_h) 正是引擎**唯一
                # 采样**的垂直区间（OGSR `dxFontRender.cpp:104-111` 由 ini 的 y1 与
                # height= 算出 tv/fTCHeight，**忽略 y2**）。带外的墨迹在游戏里本来就看不见，
                # 留着只会落进邻格的采样框 —— 本行底部越进下一行（用户报的「分划把上面
                # 那个字的底部也划进去了」）或本行顶部越进上一行。裁掉的是不可见像素，
                # 正常字体/字号下不会触发（count=0）。若真触发，日志会说明。
                clip_top = max(0, -top)
                clip_bot = max(0, top + gh - cell_h)
                if clip_top or clip_bot:
                    keep = gh - clip_top - clip_bot
                    if keep >= 1:
                        glyph = glyph.crop((0, clip_top, gw, clip_top + keep))
                        top += clip_top
                        gh = keep
                    else:
                        glyph = None
                    clipped += 1
                if glyph is not None and gw >= 1 and gh >= 1:
                    draw_x = x + pl
                    draw_y = y + top
                    canvas.paste(glyph, (draw_x, draw_y))
        ini.append(f"{ord(ch):05d}= {x}, {y}, {x + rw}, {y + cell_h}")

    if clipped:
        # 不静默：这说明该字体在该字号的墨迹比槽位高（换字体或换小一号的尺寸档位），
        # 字库本身仍然自洽（墨迹不会越进邻格），但用户有权知道。
        _log_shared("字号 %d: %d 个字符的墨迹超出槽位高 %d，已裁进行带内。"
                    "该字体在此字号的墨迹过高（引擎只采样 [y1, y1+height)），"
                    "建议换字体或改用更小的尺寸档位" % (size, clipped, cell_h), "warn")

    # 转像素
    px = canvas.tobytes()  # L 8bit
    if fmt == "8888":
        out = bytearray()
        for v in px:
            out += bytes((v, v, v, v))
        data = bytes(out)
    else:
        data = px
    ini = "[mb_symbol_coords]\nheight={}\n".format(cell_h) + "\n".join(ini) + "\n"
    return data, ini, tex_w, tex_h, max_y


# ─── XML 编码判定（绝不静默 errors="replace"） ───
def _shared_module(name):
    """导入仓库根目录的公共模块。

    引擎也能作为独立 CLI 运行（`python font_pack/font_pack.py ...`），此时仓库根
    不在 sys.path 上；导入失败返回 None，由调用方走自包含回退。
    """
    try:
        return __import__(name)
    except ImportError:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isdir(root) and root not in sys.path:
            sys.path.insert(0, root)
        try:
            return __import__(name)
        except ImportError:
            return None


def _log_shared(msg, tag="info"):
    """写**用户可见**告警：优先 toolkit_log.summary（落盘 + GUI 日志栏）。

    build_package(log=...) 的回调只用来写逐条目细节（App 传的是 log_detail，
    只落盘），告警不能依赖它——否则编码问题依旧"无人看见"。toolkit_log 不可用
    （引擎独立 CLI 运行）时退回 stderr。
    """
    lg = _shared_module("toolkit_log")
    fn = getattr(lg, "summary", None) if lg is not None else None
    if callable(fn):
        try:
            fn(msg, tag)
            return
        except Exception:
            pass
    try:
        print(f"[{tag}] {msg}", file=sys.stderr)
    except Exception:
        pass


_XML_DECL_ENC_RE = None


def _declared_encoding(raw):
    """XML 声明里的 encoding（小写）；没有声明返回 None。"""
    global _XML_DECL_ENC_RE
    import re as _re
    if _XML_DECL_ENC_RE is None:
        _XML_DECL_ENC_RE = _re.compile(
            rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', _re.I | _re.S)
    m = _XML_DECL_ENC_RE.search(raw[:500])
    if not m:
        return None
    try:
        return m.group(1).decode("ascii", "replace").strip().lower()
    except Exception:
        return None


def _encoding_trusted(enc, declared):
    """编码是否可信：windows-1251 只有 XML 声明**明确写了**才算可信。

    windows-1251 是 toolkit_textio.sniff_encoding 的终局默认值，对任意字节都能
    解码成功——不区分"声明为 cp1251"与"什么都没判定出来"，就又会回到静默乱码。
    """
    if enc in ("windows-1251", "cp1251"):
        return declared in ("windows-1251", "cp1251")
    return True


def _decode_xml_bytes(raw):
    """XML 字节 → (text, 编码名, 可信)。

    可信=False 表示编码只是猜的，**调用方必须告警**（不再"保留原始字节"：
    按用户决策，包内 XML 一律 UTF-8，判不准也要转出来并留痕）。
    旧实现是 `raw.decode("windows-1251", errors="replace")`，对任何字节都"成功"，
    于是 GBK/GB18030/UTF-16 源文件会**静默**变成替换字符/错字写进汉化包。
    判定走 toolkit_textio（手动/BOM/严格 UTF-8/XML 声明/统计探测/默认），
    不可用时退回自包含严格链。
    """
    tio = _shared_module("toolkit_textio")
    declared = _declared_encoding(raw)
    if tio is not None:
        # 判定必须在**含 BOM 的原始字节**上做（decode_bytes 会先剥 BOM 再判定，
        # 而 UTF-16/UTF-32 的 BOM 正是唯一判定依据）；解码交给 codec 自己消费 BOM。
        enc = tio.sniff_encoding(raw)
        body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        try:
            return body.decode(enc), enc, _encoding_trusted(enc, declared)
        except (UnicodeDecodeError, UnicodeError, LookupError):
            pass
        try:
            text, enc2, forced = tio.decode_bytes(raw)
            return text, enc2, (not forced) and _encoding_trusted(enc2, declared)
        except Exception:
            return None, None, False
    for enc in ("utf-8-sig", "utf-8", "gb18030", "windows-1251", "windows-1252"):
        try:
            return raw.decode(enc), enc, _encoding_trusted(enc, declared)
        except (UnicodeDecodeError, UnicodeError, LookupError):
            continue
    return None, None, False


def clamp_box_to_ink(pl, rw, gw):
    """框不得比墨迹窄 —— 返回修正后的框宽。

    `pl` = 墨迹在框内的左偏移、`gw` = 墨宽。引擎只按 [x1,x2) 采样，框窄了就**静默右裁墨**。
    宽度表（adv_tables.json）是标定值，个别码位比墨迹还窄（实测 U+0483–U+0486 表值 1px
    而墨迹 4–9px；U+00AD 表值 0），所以必须有这条下限。
    对已收窄的标点它是**无操作**（punct_box_px 保证 rw ≥ pl+gw），不会动标定宽度。
    render_font 与探针共用这一处判据，避免两边各算一遍而漂移。
    """
    if gw >= 1 and rw < pl + gw:
        return pl + gw
    return rw


def font_missing_chars(font_path, chars):
    """返回所选字体**画不出**的抽样字符（空列表 = 覆盖正常）。

    为什么需要：字体缺字形时 PIL 会画 `.notdef` 方框，于是**整套图集全是同一个方框**
    而工具照样报"完成" —— 用户拿到十张废图集却没有任何提示。
    判据：与私用区码位 `\\ue000` 的位图逐字节比较（实测 tahoma 下 '中' 与私用区
    位图完全相同：size (24,18) / bytes=432）。
    **按类别成组抽样**，并且**整组都是 .notdef 才算该类别缺失** —— 原因是：
      * 只抽一个字符会被"拉丁字体恰好也有的全角标点"（`—`、`“`）蒙过去；
      * 反过来，个别生僻字缺字形是正常的，不该因此否决整个包。
    只要求"字库真正需要的类别"：纯俄文模组配纯西文字体不会被误拒。
    """
    from PIL import ImageFont
    f = ImageFont.truetype(font_path, 24)
    ref = bytes(f.getmask("\ue000", mode="L"))

    def _notdef(ch):
        try:
            return bytes(f.getmask(ch, mode="L")) == ref
        except Exception:
            return True

    groups = []
    # ★ 优先取**真·CJK 表意字符**：只按 east_asian_width 取前几个会抓到全角标点
    #   （`—` `“` `”`），而拉丁字体恰好有这些 → "整组都是 notdef"不成立 → 判据空转
    #   （实测：字符集含 `切` 却返回"覆盖正常"）。
    cjk = [c for c in chars if 0x4E00 <= ord(c) <= 0x9FFF][:3]
    if not cjk:
        cjk = [c for c in chars if 0x3400 <= ord(c) <= 0x4DBF][:3]      # 扩展 A
    if not cjk:
        cjk = [c for c in chars if 0x3000 <= ord(c) <= 0x30FF][:3]      # 假名/日式标点
    if not cjk:
        cjk = [c for c in chars
               if unicodedata.east_asian_width(c) in "FW" or c in FORCED_FULLWIDTH][:3]
    cyr = [c for c in chars if 0x0400 <= ord(c) <= 0x04FF][:3]
    if cjk:
        groups.append(cjk)
    if cyr:
        groups.append(cyr)
    if "A" in chars:
        groups.append(["A"])
    if not groups:
        groups.append(list(chars[:3]))
    miss = []
    for group in groups:
        if group and all(_notdef(c) for c in group):
            miss.extend(group)
    return miss


def build_package(game, lang, xml_dir, font_path, out_dir,
                  offset=0, suffix="", full_cyrillic=True, log=None):
    """生成完整汉化包 gamedata/.
    lang: 加载语言, 决定 config(s)/text/{lang}/ 目录与 localization.ltx language.
    suffix: 字体文件后缀 (如 _chs), 默认空 = ui_font_11.dds; 同步到 font_prefix.
    offset: 尺寸档位, 渲染字号 = 标准字号 + offset (文件名/ltx 保持标准名).
    full_cyrillic: 保留完整西里尔 (默认 True = 保留; False = 剔除 LOST_CYRILLIC,
                   严格兼容原版)。"""
    def L(msg):
        if log: log(msg)

    if game not in GAMES:
        raise RuntimeError(f"未知游戏版本: {game}")
    if not ensure_pillow():
        raise RuntimeError("Pillow 安装失败, 无法渲染字体")
    chars = extract_chars(xml_dir, full_cyrillic=full_cyrillic)
    if not chars:
        raise RuntimeError("xmlfiles 目录为空或没有 XML 文件")
    L(f"字符集: {len(chars)} 字符 (含 ASCII/俄语基础)" + ("" if full_cyrillic else ", 严格兼容原版"))

    # ★ 字体覆盖检查（**在创建任何目录之前**）：字体画不出汉字/西里尔时，整套图集会是
    #   同一个 .notdef 方框却照样报"完成"。这里直接拒绝，且不留半成品 gamedata。
    _miss = font_missing_chars(font_path, chars)
    if _miss:
        raise RuntimeError(
            "所选字体画不出这些字符（图集会全部变成同一个方框）: %s —— "
            "请改用 msyh / simsun / simhei 等含中日韩字形的字体（当前: %s）"
            % (" ".join(_miss), os.path.basename(font_path)))

    cfg_dir = GAMES[game]["cfg_dir"]
    fmt = GAMES[game]["dds"]

    # 目标目录
    out_gd = os.path.join(out_dir, "gamedata")
    tex_dir = os.path.join(out_gd, "textures", "ui")
    text_dir = os.path.join(out_gd, cfg_dir, "text", lang)
    os.makedirs(tex_dir, exist_ok=True)
    os.makedirs(text_dir, exist_ok=True)

    # 字库 (整套 10 字号)
    # 失败时**清掉已经写出的 gamedata**：否则用户在输出目录里看到 gamedata 就以为
    # 生成成功了，把半成品（部分字号是新图集、部分是旧图集）拷进游戏。
    try:
        for size, x2 in SIZES:
            rsize = size + offset  # 实际渲染字号
            L(f"渲染字号 {rsize} ({'x2' if x2 else '原生'})...")
            data, ini, tex_w, tex_h, max_y = render_font(chars, font_path, rsize, x2, fmt)
            base = os.path.join(tex_dir, f"ui_font_{size}{suffix}")
            write_dds(base + ".dds", tex_w, tex_h, fmt, data)
            with open(base + ".ini", "w", encoding="ascii") as f:
                f.write(ini)
            L(f"  ui_font_{size}{suffix}.dds ({tex_w}x{tex_h}, 占用 {max_y}px 高)")
    except Exception:
        import shutil as _shutil
        _shutil.rmtree(out_gd, ignore_errors=True)
        raise

    # XML: 一律转为无 BOM UTF-8（汉化包内 XML 统一 utf-8 —— 用户决策）
    # 注：**不再**对"编码判不准"的文件走「原样字节 + 另存 .orig」路线。那条路线
    # 虽然保数据不失真，但会让包内编码不统一；既定按 UTF-8，就统一按 UTF-8 产出，
    # 判不准时在日志里明确告警（而不是静默），而不是把原始字节原样塞进包。
    import re as _re
    n = 0
    n_guess = 0
    for fn in sorted(os.listdir(xml_dir)):
        if not fn.lower().endswith(".xml"):
            continue
        src = os.path.join(xml_dir, fn)
        dst = os.path.join(text_dir, fn)
        with open(src, "rb") as f:
            raw = f.read()
        text, enc, trusted = _decode_xml_bytes(raw)
        if text is None:
            # decode_bytes 的兜底是 latin-1（永不失败），这里基本不可达；
            # 真到了这一步也仍然按 UTF-8 落盘，绝不跳过文件。
            text = raw.decode("windows-1251", errors="replace")
            enc, trusted = "windows-1251(errors=replace)", False
        if not trusted:
            n_guess += 1
            _log_shared(f"XML 编码无法确定，已按 {enc or '未知'} 解出后转 UTF-8: {fn}"
                        f"（若成品有乱码，请手工确认该文件的原始编码）", "warn")
        # 更新 XML 声明为 utf-8（无 BOM）
        text = _re.sub(r"<\?xml[^>]*\?>",
                       lambda m: _re.sub(r'(encoding\s*=\s*["\'])[^"\']*(["\'])',
                                         r"\1utf-8\2", m.group(0), flags=_re.I),
                       text, count=1, flags=_re.I)
        with open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        n += 1
        L(f"  XML {fn}: {enc} → utf-8")
    L(f"XML: 写入 {n} 个文件 → {cfg_dir}/text/{lang}/ (无 BOM UTF-8)"
      + (f"; 其中 {n_guess} 个原编码无法确定，已按探测结果转换并在日志告警" if n_guess else ""))

    # fonts.ltx + localization.ltx
    with open(os.path.join(out_gd, cfg_dir, "fonts.ltx"), "w", encoding="utf-8") as f:
        f.write(FONTS_LTX[game])
    loc = (LOCALIZATION_LTX[game]
           .replace("_#LANG#", suffix)   # font_prefix ← 字体后缀 (可为空)
           .replace("#LANG#", lang))      # language ← 加载语言
    with open(os.path.join(out_gd, cfg_dir, "localization.ltx"), "w", encoding="utf-8") as f:
        f.write(loc)
    L("fonts.ltx + localization.ltx 已生成")
    L(f"完成: {out_gd}")
    return out_gd


if __name__ == "__main__":
    # CLI: python font_pack.py <xml_dir> <font.ttf> <out_dir> [game] [lang] [suffix]
    a = sys.argv
    if len(a) < 4:
        print("用法: python font_pack.py <xml目录> <字体文件> <输出目录> [GAME=SoC] [LANG=chs] [后缀=_chs]")
        sys.exit(1)
    game = a[4] if len(a) > 4 else "SoC"
    lang = a[5] if len(a) > 5 else "chs"
    suffix = a[6] if len(a) > 6 else ""
    build_package(game, lang, a[1], a[2], a[3], suffix=suffix, log=print)
