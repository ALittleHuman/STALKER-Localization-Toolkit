# -*- coding: utf-8 -*-
"""
汉化包生成引擎 — CN_Pack_Generator 的 Python 重写
功能: 从汉化 XML 提取字符集 → 渲染字库纹理(DDS) → 组装 gamedata 汉化包
依赖: Pillow (缺失时自动安装)
"""
import os, sys, struct, unicodedata

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

PUNCT_OFFSETS = {
    11: {33:[1, 4], 34:[1, 4], 35:[0, 4], 36:[1, 2], 37:[1, 4], 38:[1, 4], 39:[1, 4], 40:[1, 4], 41:[0, 4], 42:[0, 4], 43:[2, 7], 44:[0, 14], 45:[1, 11], 46:[1, 14], 47:[0, 4], 58:[1, 7], 59:[0, 7], 60:[2, 7], 61:[2, 9], 62:[2, 7], 63:[1, 4], 64:[1, 4], 91:[1, 4], 92:[0, 4], 93:[0, 4], 94:[2, 4], 95:[0, 19], 96:[0, 3], 123:[0, 4], 124:[1, 3], 125:[0, 4], 126:[2, 10], 171:[0, 9], 174:[1, 4], 187:[0, 9], 8211:[0, 11], 8220:[10, 4], 8221:[1, 4], 8230:[1, 14], 12290:[1, 14], 65311:[1, 4]},
    13: {33:[1, 5], 34:[1, 5], 35:[0, 5], 36:[1, 3], 37:[0, 5], 38:[0, 5], 39:[1, 5], 40:[1, 5], 41:[0, 5], 42:[0, 5], 43:[2, 8], 44:[0, 16], 45:[1, 12], 46:[1, 16], 47:[0, 5], 58:[1, 8], 59:[0, 8], 60:[2, 8], 61:[2, 10], 62:[2, 8], 63:[1, 5], 64:[1, 5], 91:[1, 5], 92:[0, 5], 93:[0, 5], 94:[2, 5], 95:[0, 21], 96:[1, 4], 123:[0, 5], 124:[1, 4], 125:[0, 5], 126:[2, 11], 171:[0, 10], 174:[1, 5], 187:[0, 10], 8211:[0, 12], 8220:[10, 5], 8221:[0, 5], 8230:[1, 16], 12290:[0, 15], 65311:[1, 5]},
    15: {33:[2, 4], 34:[2, 4], 35:[0, 4], 36:[1, 3], 37:[0, 4], 38:[1, 4], 39:[1, 4], 40:[1, 4], 41:[0, 4], 42:[0, 4], 43:[2, 8], 44:[0, 16], 45:[1, 12], 46:[0, 16], 47:[0, 4], 58:[0, 8], 59:[0, 8], 60:[2, 8], 61:[2, 10], 62:[2, 8], 63:[1, 4], 64:[1, 4], 91:[2, 4], 92:[0, 4], 93:[0, 4], 94:[2, 4], 95:[0, 22], 96:[1, 4], 123:[1, 4], 124:[1, 3], 125:[1, 4], 126:[2, 11], 171:[0, 10], 174:[1, 4], 187:[0, 10], 8211:[0, 12], 8220:[11, 4], 8221:[1, 4], 8230:[1, 16], 12290:[1, 16], 65311:[1, 4]},
    16: {33:[1, 5], 34:[1, 5], 35:[0, 5], 36:[2, 3], 37:[0, 5], 38:[1, 5], 39:[1, 5], 40:[1, 5], 41:[0, 5], 42:[1, 5], 43:[2, 9], 44:[0, 18], 45:[1, 14], 46:[1, 18], 47:[0, 5], 58:[1, 9], 59:[0, 9], 60:[3, 9], 61:[2, 11], 62:[3, 9], 63:[1, 5], 64:[2, 5], 91:[1, 5], 92:[0, 5], 93:[0, 5], 94:[2, 5], 95:[0, 24], 96:[1, 4], 123:[0, 5], 124:[2, 4], 125:[0, 5], 126:[2, 12], 171:[1, 11], 174:[2, 5], 187:[1, 11], 8211:[0, 14], 8220:[12, 5], 8221:[1, 5], 8230:[1, 18], 12290:[1, 18], 65311:[1, 5]},
    17: {33:[2, 5], 34:[2, 5], 35:[0, 5], 36:[2, 3], 37:[1, 5], 38:[1, 5], 39:[1, 5], 40:[1, 5], 41:[0, 5], 42:[0, 5], 43:[2, 9], 44:[0, 19], 45:[1, 14], 46:[1, 19], 47:[0, 5], 58:[1, 10], 59:[0, 10], 60:[2, 9], 61:[2, 12], 62:[2, 9], 63:[1, 5], 64:[2, 5], 91:[2, 5], 92:[0, 5], 93:[0, 5], 94:[2, 5], 95:[0, 25], 96:[1, 4], 123:[1, 5], 124:[1, 4], 125:[1, 5], 126:[2, 13], 171:[0, 12], 174:[2, 5], 187:[0, 12], 8211:[0, 14], 8220:[13, 5], 8221:[1, 5], 8230:[1, 19], 12290:[1, 18], 65311:[1, 5]},
    18: {33:[2, 6], 34:[2, 6], 35:[0, 6], 36:[2, 4], 37:[0, 6], 38:[1, 6], 39:[2, 6], 40:[2, 6], 41:[0, 6], 42:[0, 6], 43:[3, 11], 44:[0, 21], 45:[1, 16], 46:[1, 21], 47:[0, 6], 58:[1, 11], 59:[0, 11], 60:[3, 10], 61:[3, 13], 62:[3, 10], 63:[1, 6], 64:[1, 6], 91:[2, 6], 92:[0, 6], 93:[1, 6], 94:[3, 6], 95:[0, 28], 96:[0, 5], 123:[1, 6], 124:[2, 5], 125:[1, 6], 126:[2, 15], 171:[1, 13], 174:[1, 6], 187:[0, 13], 8211:[0, 16], 8220:[14, 6], 8221:[1, 6], 8230:[2, 21], 12290:[1, 21], 65311:[2, 6]},
    20: {33:[2, 6], 34:[2, 6], 35:[0, 6], 36:[2, 4], 37:[1, 6], 38:[1, 6], 39:[1, 6], 40:[1, 6], 41:[0, 6], 42:[1, 6], 43:[3, 11], 44:[0, 22], 45:[2, 17], 46:[1, 22], 47:[0, 6], 58:[1, 11], 59:[0, 11], 60:[3, 11], 61:[3, 14], 62:[3, 11], 63:[1, 6], 64:[2, 6], 91:[2, 6], 92:[0, 6], 93:[0, 6], 94:[3, 6], 95:[0, 30], 96:[1, 5], 123:[1, 6], 124:[2, 5], 125:[0, 6], 126:[3, 15], 171:[1, 14], 174:[1, 6], 187:[1, 14], 8211:[0, 17], 8220:[16, 6], 8221:[1, 6], 8230:[2, 22], 12290:[1, 22], 65311:[2, 6]},
    21: {33:[2, 7], 34:[2, 7], 35:[0, 7], 36:[2, 4], 37:[0, 6], 38:[1, 6], 39:[2, 7], 40:[2, 7], 41:[0, 7], 42:[1, 7], 43:[3, 12], 44:[0, 23], 45:[1, 17], 46:[1, 24], 47:[0, 7], 58:[1, 12], 59:[0, 12], 60:[3, 11], 61:[3, 14], 62:[3, 11], 63:[2, 6], 64:[2, 6], 91:[3, 7], 92:[0, 7], 93:[1, 7], 94:[3, 6], 95:[0, 31], 96:[1, 5], 123:[1, 7], 124:[2, 5], 125:[1, 7], 126:[2, 16], 171:[1, 14], 174:[2, 7], 187:[1, 14], 8211:[0, 17], 8220:[16, 6], 8221:[1, 6], 8230:[1, 24], 12290:[2, 23], 65311:[2, 6]},
    23: {33:[3, 7], 34:[2, 7], 35:[0, 7], 36:[2, 4], 37:[1, 6], 38:[2, 6], 39:[2, 7], 40:[2, 7], 41:[0, 7], 42:[1, 7], 43:[3, 12], 44:[1, 24], 45:[1, 18], 46:[2, 25], 47:[0, 7], 58:[2, 12], 59:[1, 12], 60:[4, 12], 61:[3, 15], 62:[4, 11], 63:[1, 6], 64:[2, 6], 91:[3, 7], 92:[0, 7], 93:[1, 7], 94:[3, 6], 96:[1, 5], 123:[1, 7], 124:[2, 5], 125:[1, 7], 126:[3, 17], 171:[1, 15], 174:[2, 7], 187:[1, 15], 8211:[0, 18], 8220:[17, 6], 8221:[1, 6], 8230:[2, 25], 12290:[1, 23], 65311:[2, 6]},
    25: {33:[3, 7], 34:[3, 7], 35:[0, 7], 36:[2, 4], 37:[1, 6], 38:[1, 6], 39:[2, 7], 40:[2, 7], 41:[0, 7], 42:[1, 7], 43:[3, 12], 44:[1, 25], 45:[2, 19], 46:[2, 26], 47:[0, 7], 58:[2, 13], 59:[1, 13], 60:[4, 12], 61:[3, 15], 62:[4, 12], 63:[1, 6], 64:[3, 6], 91:[3, 7], 92:[0, 7], 93:[0, 7], 94:[3, 6], 96:[1, 5], 123:[1, 7], 124:[2, 4], 125:[0, 7], 126:[3, 17], 171:[1, 15], 174:[2, 7], 187:[1, 15], 8211:[0, 19], 8220:[18, 6], 8221:[1, 6], 8230:[2, 26], 12290:[1, 25], 65311:[2, 6]},
}


# 原版 FontGen (GDI) 的 cell 高表 (ini height= 值, 与 FreeType metrics 不同)
CELL_HEIGHTS = {11: 20, 13: 22, 15: 23, 16: 25, 17: 26, 18: 29, 20: 31, 21: 32, 23: 33, 25: 35}

# 当前环境原版 FontGen 的方块字符宽 (汉字/全角标点, 查表避免字体 advance 差异)
BLOCK_WIDTHS = {11: 17, 13: 18, 15: 19, 16: 21, 17: 22, 18: 24, 20: 26, 21: 27, 23: 29, 25: 31}

# FontGen 内置字符集中的生僻汉字 (原版 Char.txt 编码 bug 丢失后由内置集补充)
FONTGEN_EXTRA = set("屑懈挟衼袗袘袙袚袛袝袞袟袠袡袣袥袦袧袨袩袪褉褋褌褍褎褏褑褔褕褖褗褘褜褝褞褟褢")

# 原版 CharAdder 编码 bug 丢失的西里尔 (严格兼容模式下剔除, 保证与原版整包一致)
LOST_CYRILLIC = set("ГЙФХЦЧШЩЭЮбвгдежзийклмнопрстуфхцчшщъыьэю")

ADV_TABLES = {
    11: {32:6, 33:6, 34:8, 35:11, 36:10, 37:15, 38:15, 39:5, 40:6, 41:6, 42:8, 43:13, 44:5, 45:8, 46:5, 47:8, 48:10, 49:10, 50:10, 51:10, 52:10, 53:10, 54:10, 55:10, 56:10, 57:10, 58:5, 59:5, 60:13, 61:13, 62:13, 63:9, 64:18, 65:12, 66:11, 67:12, 68:13, 69:10, 70:9, 71:13, 72:13, 73:5, 74:7, 75:11, 76:9, 77:17, 78:14, 79:14, 80:11, 81:14, 82:11, 83:10, 84:10, 85:13, 86:12, 87:17, 88:11, 89:11, 90:11, 91:6, 92:8, 93:6, 94:13, 95:8, 96:6, 97:10, 98:11, 99:9, 100:11, 101:10, 102:6, 103:11, 104:11, 105:5, 106:5, 107:10, 108:5, 109:16, 110:11, 111:11, 112:11, 113:11, 114:7, 115:8, 116:7, 117:11, 118:9, 119:14, 120:9, 121:9, 122:9, 123:6, 124:5, 125:6, 126:13, 171:10, 173:0, 187:10, 1025:10, 1040:12, 1041:11, 1042:11, 1044:13, 1045:10, 1046:16, 1047:10, 1048:14, 1050:11, 1051:13, 1052:17, 1053:13, 1054:14, 1055:13, 1056:11, 1057:12, 1058:10, 1059:11, 1067:15, 1071:11, 1072:10, 1103:10, 1105:10, 8220:17, 8221:17, 8230:14},
    13: {32:5, 33:6, 34:8, 35:11, 36:11, 37:16, 38:16, 39:5, 40:6, 41:6, 42:8, 43:13, 44:5, 45:8, 46:5, 47:8, 48:11, 49:11, 50:11, 51:11, 52:11, 53:11, 54:11, 55:11, 56:11, 57:11, 58:5, 59:5, 60:13, 61:13, 62:13, 63:9, 64:18, 65:13, 66:11, 67:12, 68:14, 69:10, 70:10, 71:13, 72:14, 73:5, 74:7, 75:11, 76:9, 77:17, 78:15, 79:15, 80:11, 81:15, 82:12, 83:10, 84:10, 85:13, 86:12, 87:18, 88:12, 89:11, 90:11, 91:6, 92:8, 93:6, 94:13, 95:8, 96:5, 97:10, 98:11, 99:9, 100:12, 101:10, 102:6, 103:12, 104:11, 105:5, 106:5, 107:10, 108:5, 109:17, 110:11, 111:11, 112:11, 113:12, 114:7, 115:8, 116:7, 117:11, 118:10, 119:14, 120:9, 121:10, 122:9, 123:6, 124:5, 125:6, 126:13, 171:10, 173:0, 187:10, 1025:10, 1040:13, 1041:11, 1042:11, 1044:14, 1045:10, 1046:17, 1047:11, 1048:15, 1050:11, 1051:13, 1052:17, 1053:14, 1054:15, 1055:14, 1056:11, 1057:12, 1058:10, 1059:11, 1067:15, 1071:12, 1072:10, 1103:10, 1105:10, 8220:18, 8221:18, 8230:15},
    15: {32:6, 33:6, 34:8, 35:12, 36:11, 37:17, 38:16, 39:5, 40:6, 41:6, 42:9, 43:14, 44:5, 45:8, 46:5, 47:8, 48:11, 49:11, 50:11, 51:11, 52:11, 53:11, 54:11, 55:11, 56:11, 57:11, 58:5, 59:5, 60:14, 61:14, 62:14, 63:9, 64:19, 65:13, 66:12, 67:13, 68:14, 69:10, 70:10, 71:14, 72:15, 73:6, 74:8, 75:12, 76:10, 77:18, 78:15, 79:15, 80:12, 81:15, 82:12, 83:11, 84:11, 85:14, 86:13, 87:19, 88:12, 89:11, 90:12, 91:6, 92:8, 93:6, 94:14, 95:9, 96:6, 97:10, 98:12, 99:10, 100:12, 101:11, 102:7, 103:12, 104:12, 105:5, 106:5, 107:10, 108:5, 109:18, 110:12, 111:12, 112:12, 113:12, 114:7, 115:9, 116:7, 117:12, 118:10, 119:15, 120:10, 121:10, 122:9, 123:6, 124:5, 125:6, 126:14, 171:11, 173:0, 187:11, 1025:10, 1040:13, 1041:12, 1042:12, 1044:14, 1045:10, 1046:18, 1047:11, 1048:15, 1050:12, 1051:14, 1052:18, 1053:15, 1054:15, 1055:15, 1056:12, 1057:13, 1058:11, 1059:12, 1067:16, 1071:12, 1072:10, 1103:10, 1105:11, 8220:19, 8221:19, 8230:15},
    16: {32:6, 33:7, 34:9, 35:13, 36:12, 37:19, 38:18, 39:6, 40:7, 41:7, 42:10, 43:16, 44:5, 45:9, 46:5, 47:9, 48:12, 49:12, 50:12, 51:12, 52:12, 53:12, 54:12, 55:12, 56:12, 57:12, 58:5, 59:5, 60:16, 61:16, 62:16, 63:10, 64:22, 65:15, 66:13, 67:14, 68:16, 69:12, 70:11, 71:16, 72:16, 73:6, 74:8, 75:13, 76:11, 77:20, 78:17, 79:17, 80:13, 81:17, 82:14, 83:12, 84:12, 85:16, 86:14, 87:21, 88:14, 89:13, 90:13, 91:7, 92:9, 93:7, 94:16, 95:10, 96:6, 97:12, 98:13, 99:11, 100:13, 101:12, 102:7, 103:13, 104:13, 105:6, 106:6, 107:12, 108:6, 109:20, 110:13, 111:13, 112:13, 113:13, 114:8, 115:10, 116:8, 117:13, 118:11, 119:17, 120:11, 121:11, 122:10, 123:7, 124:6, 125:7, 126:16, 171:12, 173:0, 187:12, 1025:12, 1040:15, 1041:13, 1042:13, 1044:16, 1045:12, 1046:20, 1047:12, 1048:17, 1050:13, 1051:15, 1052:20, 1053:16, 1054:17, 1055:16, 1056:13, 1057:14, 1058:12, 1059:13, 1067:18, 1071:14, 1072:12, 1103:12, 1105:12, 8220:21, 8221:21, 8230:17},
    17: {32:7, 33:7, 34:10, 35:14, 36:13, 37:19, 38:19, 39:6, 40:7, 41:7, 42:10, 43:16, 44:5, 45:10, 46:5, 47:9, 48:13, 49:13, 50:13, 51:13, 52:13, 53:13, 54:13, 55:13, 56:13, 57:13, 58:5, 59:5, 60:16, 61:16, 62:16, 63:11, 64:23, 65:15, 66:14, 67:15, 68:17, 69:12, 70:12, 71:16, 72:17, 73:7, 74:9, 75:14, 76:11, 77:21, 78:18, 79:18, 80:13, 81:18, 82:14, 83:13, 84:13, 85:16, 86:15, 87:22, 88:14, 89:13, 90:14, 91:7, 92:9, 93:7, 94:16, 95:10, 96:7, 97:12, 98:14, 99:11, 100:14, 101:13, 102:8, 103:14, 104:14, 105:6, 106:6, 107:12, 108:6, 109:21, 110:14, 111:14, 112:14, 113:14, 114:9, 115:10, 116:8, 117:14, 118:12, 119:17, 120:11, 121:12, 122:11, 123:7, 124:6, 125:7, 126:16, 171:12, 173:0, 187:12, 1025:12, 1040:15, 1041:14, 1042:14, 1044:17, 1045:12, 1046:21, 1047:13, 1048:18, 1050:14, 1051:16, 1052:21, 1053:17, 1054:18, 1055:17, 1056:13, 1057:15, 1058:13, 1059:14, 1067:19, 1071:14, 1072:12, 1103:12, 1105:13, 8220:22, 8221:22, 8230:18},
    18: {32:7, 33:8, 34:11, 35:15, 36:14, 37:21, 38:21, 39:6, 40:8, 41:8, 42:11, 43:18, 44:6, 45:11, 46:6, 47:10, 48:14, 49:14, 50:14, 51:14, 52:14, 53:14, 54:14, 55:14, 56:14, 57:14, 58:6, 59:6, 60:18, 61:18, 62:18, 63:12, 64:25, 65:17, 66:15, 67:16, 68:18, 69:13, 70:13, 71:18, 72:19, 73:7, 74:10, 75:15, 76:12, 77:23, 78:20, 79:20, 80:15, 81:20, 82:16, 83:14, 84:14, 85:18, 86:16, 87:24, 88:16, 89:15, 90:15, 91:8, 92:10, 93:8, 94:18, 95:11, 96:7, 97:13, 98:15, 99:12, 100:15, 101:14, 102:9, 103:15, 104:15, 105:7, 106:7, 107:13, 108:7, 109:23, 110:15, 111:15, 112:15, 113:15, 114:9, 115:11, 116:9, 117:15, 118:13, 119:19, 120:12, 121:13, 122:12, 123:8, 124:7, 125:8, 126:18, 171:13, 173:0, 187:13, 1025:13, 1040:17, 1041:15, 1042:15, 1044:18, 1045:13, 1046:23, 1047:14, 1048:20, 1050:15, 1051:18, 1052:23, 1053:19, 1054:20, 1055:19, 1056:15, 1057:16, 1058:14, 1059:15, 1067:21, 1071:16, 1072:13, 1103:13, 1105:14, 8220:24, 8221:24, 8230:20},
    20: {32:8, 33:9, 34:12, 35:17, 36:16, 37:24, 38:23, 39:7, 40:9, 41:9, 42:12, 43:20, 44:7, 45:12, 46:7, 47:12, 48:16, 49:16, 50:16, 51:16, 52:16, 53:16, 54:16, 55:16, 56:16, 57:16, 58:7, 59:7, 60:20, 61:20, 62:20, 63:13, 64:27, 65:19, 66:17, 67:18, 68:20, 69:15, 70:14, 71:20, 72:21, 73:8, 74:11, 75:17, 76:14, 77:26, 78:22, 79:22, 80:16, 81:22, 82:17, 83:16, 84:15, 85:20, 86:18, 87:27, 88:17, 89:16, 90:17, 91:9, 92:11, 93:9, 94:20, 95:12, 96:8, 97:15, 98:17, 99:14, 100:17, 101:15, 102:10, 103:17, 104:17, 105:7, 106:8, 107:15, 108:7, 109:25, 110:17, 111:17, 112:17, 113:17, 114:10, 115:13, 116:10, 117:17, 118:14, 119:21, 120:14, 121:14, 122:13, 123:9, 124:8, 125:9, 126:20, 171:15, 173:0, 187:15, 1025:15, 1040:19, 1041:17, 1042:17, 1044:20, 1045:15, 1046:25, 1047:16, 1048:22, 1050:17, 1051:20, 1052:26, 1053:21, 1054:22, 1055:21, 1056:16, 1057:18, 1058:15, 1059:17, 1067:23, 1071:17, 1072:15, 1103:15, 1105:15, 8220:26, 8221:26, 8230:22},
    21: {32:8, 33:9, 34:12, 35:17, 36:16, 37:24, 38:24, 39:7, 40:9, 41:9, 42:13, 43:20, 44:7, 45:12, 46:7, 47:12, 48:16, 49:16, 50:16, 51:16, 52:16, 53:16, 54:16, 55:16, 56:16, 57:16, 58:7, 59:7, 60:20, 61:20, 62:20, 63:13, 64:28, 65:19, 66:17, 67:18, 68:21, 69:15, 70:15, 71:20, 72:21, 73:8, 74:11, 75:17, 76:14, 77:26, 78:22, 79:22, 80:17, 81:22, 82:18, 83:16, 84:16, 85:20, 86:18, 87:28, 88:18, 89:16, 90:17, 91:9, 92:11, 93:9, 94:20, 95:12, 96:8, 97:15, 98:17, 99:14, 100:17, 101:16, 102:10, 103:17, 104:17, 105:7, 106:7, 107:15, 108:7, 109:25, 110:17, 111:17, 112:17, 113:17, 114:11, 115:13, 116:10, 117:17, 118:14, 119:21, 120:14, 121:14, 122:13, 123:9, 124:8, 125:9, 126:20, 171:15, 173:0, 187:15, 1025:15, 1040:19, 1041:17, 1042:17, 1044:21, 1045:15, 1046:26, 1047:16, 1048:22, 1050:17, 1051:20, 1052:26, 1053:21, 1054:22, 1055:21, 1056:17, 1057:18, 1058:16, 1059:17, 1067:23, 1071:18, 1072:15, 1103:15, 1105:16, 8220:27, 8221:27, 8230:22},
    23: {32:9, 33:10, 34:13, 35:19, 36:18, 37:26, 38:26, 39:8, 40:10, 41:10, 42:14, 43:22, 44:8, 45:13, 46:8, 47:13, 48:18, 49:18, 50:18, 51:18, 52:18, 53:18, 54:18, 55:18, 56:18, 57:18, 58:8, 59:8, 60:22, 61:22, 62:22, 63:15, 64:30, 65:21, 66:19, 67:20, 68:23, 69:17, 70:16, 71:22, 72:23, 73:9, 74:12, 75:19, 76:15, 77:29, 78:24, 79:24, 80:18, 81:24, 82:19, 83:17, 84:17, 85:22, 86:20, 87:30, 88:19, 89:18, 90:19, 91:10, 92:13, 93:10, 94:22, 95:14, 96:9, 97:17, 98:19, 99:15, 100:19, 101:17, 102:11, 103:19, 104:18, 105:8, 106:8, 107:16, 108:8, 109:28, 110:18, 111:19, 112:19, 113:19, 114:12, 115:14, 116:11, 117:18, 118:16, 119:23, 120:15, 121:16, 122:15, 123:10, 124:8, 125:10, 126:22, 171:17, 173:0, 187:17, 1025:17, 1040:21, 1041:19, 1042:19, 1044:23, 1045:17, 1046:28, 1047:18, 1048:24, 1050:19, 1051:22, 1052:29, 1053:23, 1054:24, 1055:23, 1056:18, 1057:20, 1058:17, 1059:18, 1067:25, 1071:19, 1072:17, 1103:17, 1105:17, 8220:29, 8221:29, 8230:24},
    25: {32:9, 33:10, 34:14, 35:20, 36:18, 37:28, 38:27, 39:8, 40:11, 41:11, 42:14, 43:23, 44:8, 45:14, 46:8, 47:13, 48:18, 49:18, 50:18, 51:18, 52:18, 53:18, 54:18, 55:18, 56:18, 57:18, 58:8, 59:8, 60:23, 61:23, 62:23, 63:15, 64:32, 65:22, 66:20, 67:21, 68:24, 69:17, 70:17, 71:23, 72:24, 73:9, 74:12, 75:20, 76:16, 77:30, 78:25, 79:25, 80:19, 81:25, 82:20, 83:18, 84:18, 85:23, 86:21, 87:32, 88:20, 89:19, 90:19, 91:11, 92:13, 93:11, 94:23, 95:14, 96:9, 97:17, 98:20, 99:16, 100:20, 101:18, 102:11, 103:20, 104:19, 105:8, 106:8, 107:17, 108:8, 109:29, 110:19, 111:20, 112:20, 113:20, 114:12, 115:15, 116:12, 117:19, 118:16, 119:25, 120:16, 121:17, 122:15, 123:11, 124:9, 125:11, 126:23, 171:17, 173:0, 187:17, 1025:17, 1040:22, 1041:20, 1042:20, 1044:24, 1045:17, 1046:30, 1047:18, 1048:25, 1050:20, 1051:23, 1052:30, 1053:24, 1054:25, 1055:24, 1056:19, 1057:21, 1058:18, 1059:19, 1067:27, 1071:20, 1072:17, 1103:17, 1105:18, 8220:31, 8221:31, 8230:25},
}


# ASCII + 俄语基础字符 (对应原 _ascii_char.txt)
ASCII_CHARS = (' !"#$%&\'()*+,-./0123456789:;<=>?@'
               'ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`'
               'abcdefghijklmnopqrstuvwxyz{|}~'
               'АаБбВвГгДдЕеЁёЖжЗзИиЙйКкЛлМмНнОоПпРрСсТтУуФфХхЦцЧчШшЩщъЫыьЭэЮюЯя')

TEX_W = 1024  # 字库纹理宽 (放不下自动 2048)
GAP = 3       # 字符间水平间隙 (原版 FontGen 布局规律)

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


def ensure_pillow():
    """Pillow 缺失时自动安装."""
    try:
        from PIL import Image  # noqa
        return True
    except ImportError:
        try:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "pillow"],
                           capture_output=True, timeout=180,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            from PIL import Image  # noqa
            return True
        except Exception:
            return False


def extract_chars(xml_dir, full_cyrillic=True):
    """扫描 xmlfiles 目录, 提取所有文本字符, 返回去重字符表.
    full_cyrillic=False 时剔除原版丢失的西里尔 (严格兼容原版).
    文本解析复用 toolkit.parse_xml_texts (无 toolkit 时自包含回退)."""
    import re
    try:
        import toolkit
        _parse_xml = toolkit.parse_xml_texts
    except ImportError:
        _parse_xml = _local_parse_xml_texts
    chars = set(ASCII_CHARS)
    if not os.path.isdir(xml_dir):
        return None
    for fn in sorted(os.listdir(xml_dir)):
        if not fn.lower().endswith(".xml"):
            continue
        fp = os.path.join(xml_dir, fn)
        try:
            raw = open(fp, "rb").read().decode("utf-8-sig", "ignore")
            texts = _parse_xml(raw)
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
    chars |= FONTGEN_EXTRA
    if not full_cyrillic:
        chars -= LOST_CYRILLIC
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
    宽: 1024 若行数*cell 放得下, 否则 2048. 高: 2 幂 ≥ (max_y-1)."""
    from PIL import Image, ImageFont
    S = 2 if x2 else 1
    font = ImageFont.truetype(font_path, size * S)
    cell_h = CELL_HEIGHTS.get(size, size + 4)  # 槽宽 = cell 高
    adv_table = ADV_TABLES.get(size, {})

    def widths_of(ch):
        cp = ord(ch)
        if cp in adv_table:
            return adv_table[cp]
        if unicodedata.east_asian_width(ch) in "FW" or ch in FORCED_FULLWIDTH:
            return BLOCK_WIDTHS.get(size, size + 2)
        adv = font.getlength(ch) / S
        return max(1, round(adv) + 1)

    # 先确定纹理宽: 1024 行数*cell ≤ 1024 则用, 否则 2048
    tex_w = 1024
    slots = tex_w // cell_h
    rows_n = (len(chars) + slots - 1) // slots
    if rows_n * cell_h - 1 > 1024:
        tex_w = 2048
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
    for i, ch in enumerate(chars):
        rw = widths_of(ch)
        col = i % slots
        row = i // slots
        x = col * cell_h + (cell_h - rw) // 2
        y = row * cell_h
        bbox = font.getbbox(ch)
        mask = font.getmask(ch, mode="L")
        mb = mask.getbbox()
        if mb is not None:
            gw = (mb[2] - mb[0]) // S
            gh = (mb[3] - mb[1]) // S
            if gw >= 1 and gh >= 1:
                glyph = Image.frombytes("L", mask.size, bytes(mask)).crop(mb)
                if S > 1:
                    glyph = glyph.resize((gw, gh), Image.LANCZOS)
                top = bbox[1] // S
                left = bbox[0] // S
                # 全部使用字体自然位置（与最初一致），整体略微下移，
                # 避免采样框顶部扫到上一行字形的底边。
                draw_x = x + left
                draw_y = y + top + 2
                canvas.paste(glyph, (draw_x, draw_y))
        ini.append(f"{ord(ch):05d}= {x}, {y}, {x + rw}, {y + cell_h}")

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


def build_package(game, lang, xml_dir, font_path, out_dir,
                  offset=0, suffix="", full_cyrillic=True, log=None):
    """生成完整汉化包 gamedata/.
    lang: 加载语言, 决定 config(s)/text/{lang}/ 目录与 localization.ltx language.
    suffix: 字体文件后缀 (如 _chs), 默认空 = ui_font_11.dds; 同步到 font_prefix.
    offset: 尺寸档位, 渲染字号 = 标准字号 + offset (文件名/ltx 保持标准名).
    full_cyrillic: 保留完整西里尔 (默认 False = 严格兼容原版)."""
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

    cfg_dir = GAMES[game]["cfg_dir"]
    fmt = GAMES[game]["dds"]

    # 目标目录
    out_gd = os.path.join(out_dir, "gamedata")
    tex_dir = os.path.join(out_gd, "textures", "ui")
    text_dir = os.path.join(out_gd, cfg_dir, "text", lang)
    os.makedirs(tex_dir, exist_ok=True)
    os.makedirs(text_dir, exist_ok=True)

    # 字库 (整套 10 字号)
    for size, x2 in SIZES:
        rsize = size + offset  # 实际渲染字号
        L(f"渲染字号 {rsize} ({'x2' if x2 else '原生'})...")
        data, ini, tex_w, tex_h, max_y = render_font(chars, font_path, rsize, x2, fmt)
        base = os.path.join(tex_dir, f"ui_font_{size}{suffix}")
        write_dds(base + ".dds", tex_w, tex_h, fmt, data)
        with open(base + ".ini", "w", encoding="ascii") as f:
            f.write(ini)
        L(f"  ui_font_{size}{suffix}.dds ({tex_w}x{tex_h}, 占用 {max_y}px 高)")

    # XML: 统一转为无 BOM UTF-8（汉化包内 XML 一律 utf-8）
    import re as _re
    n = 0
    for fn in sorted(os.listdir(xml_dir)):
        if fn.lower().endswith(".xml"):
            src = os.path.join(xml_dir, fn)
            dst = os.path.join(text_dir, fn)
            with open(src, "rb") as f:
                raw = f.read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("windows-1251", errors="replace")
            # 更新 XML 声明为 utf-8（无 BOM）
            text = _re.sub(r"<\?xml[^>]*\?>",
                           lambda m: _re.sub(r'(encoding\s*=\s*["\'])[^"\']*(["\'])',
                                             r"\1utf-8\2", m.group(0), flags=_re.I),
                           text, count=1, flags=_re.I)
            with open(dst, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            n += 1
    L(f"XML: 写入 {n} 个文件 → {cfg_dir}/text/{lang}/ (无 BOM UTF-8)")

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
