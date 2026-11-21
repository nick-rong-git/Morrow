"""
Morrow 终端 UI 主题与视觉规范 (Theme & Palette)
采用极简深色极客风（Electric Cyan + Cyber Violet + Emerald Green + Golden Amber）。
"""

from rich.style import Style
from rich.box import ROUNDED, HEAVY, SIMPLE

# 调色盘规范
COLOR_PRIMARY = "#00f0ff"      # 电光青（主品牌色、焦点、当前单词）
COLOR_SECONDARY = "#bd93f9"    # 幻影紫（音标、辅助元数据）
COLOR_SUCCESS = "#50fa7b"      # 翡翠绿（认识、已掌握、完成）
COLOR_WARNING = "#f1fa8c"      # 黄金琥珀（模糊、例句高亮、提醒）
COLOR_DANGER = "#ff5555"       # 珊瑚红（忘记、错误、强提醒）
COLOR_MUTED = "#6272a4"        # 暗岩蓝（低调注释、底栏快捷键提示）
COLOR_TEXT_MAIN = "#f8f8f2"    # 亮白（正文主体）
COLOR_BORDER = "#44475a"       # 边框深灰

# 边框定义
CARD_BOX = ROUNDED
MODAL_BOX = HEAVY

# 风格常量
STYLE_BANNER = "bold #00f0ff"
STYLE_WORD_TITLE = "bold #00f0ff"
STYLE_PHONETIC = "italic #bd93f9"
STYLE_SYLLABLE = "#8be9fd"
STYLE_EXPLAIN_TEXT = "bold #f8f8f2"
STYLE_EXAMPLE_EN = "#f8f8f2"
STYLE_EXAMPLE_CN = "#8be9fd"
STYLE_HIGHLIGHT = "bold #f1fa8c on #282a36"
STYLE_KEY_HINT = "dim #6272a4"
