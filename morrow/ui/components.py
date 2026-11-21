"""
Morrow 基础 UI 组件库 (Components)
包含高质感进度条、连续打卡徽章、快捷键导航栏及评判药丸。
"""

from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.box import ROUNDED
from .theme import (
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS,
    COLOR_WARNING, COLOR_DANGER, COLOR_MUTED, COLOR_TEXT_MAIN
)

def render_progress_bar(current: int, total: int, streak: int = 1) -> Text:
    """渲染优雅的 Unicode 渐变进度条"""
    total = max(1, total)
    current = min(total, max(0, current))
    ratio = current / total
    bar_width = 24
    filled = int(bar_width * ratio)
    
    t = Text()
    t.append(" 📖 今日进度 [", style=COLOR_MUTED)
    t.append("━" * filled, style=f"bold {COLOR_PRIMARY}")
    if filled < bar_width:
        t.append("╸", style=COLOR_PRIMARY)
        t.append(" " * (bar_width - filled - 1), style=COLOR_MUTED)
    t.append("] ", style=COLOR_MUTED)
    t.append(f"{int(ratio * 100)}% ", style=f"bold {COLOR_TEXT_MAIN}")
    t.append(f"({current}/{total} 词, 剩余 {max(0, total - current)} 词)", style=COLOR_MUTED)
    
    # 连续打卡火苗徽章
    t.append("  │  ", style=COLOR_MUTED)
    t.append("🔥 连击 ", style="bold #ff9f43")
    t.append(f"{streak} ", style="bold #feca57")
    t.append("天", style="bold #ff9f43")
    return t

def render_judge_hotkeys() -> Text:
    """判答阶段快捷键导航栏"""
    t = Text()
    t.append("  [1] ", style="bold #50fa7b")
    t.append("认识  ", style="#50fa7b")
    
    t.append("[2] ", style="bold #f1fa8c")
    t.append("模糊  ", style="#f1fa8c")
    
    t.append("[3] ", style="bold #ff5555")
    t.append("忘记  ", style="#ff5555")
    
    t.append("[0] ", style="bold #bd93f9")
    t.append("斩词/熟知  ", style="#bd93f9")
    
    t.append("│  ", style="dim #6272a4")
    t.append("[p] ", style="bold #00f0ff")
    t.append("单词发音  ", style="#00f0ff")
    
    t.append("[e] ", style="bold #8be9fd")
    t.append("读例句(4/5/6)  ", style="#8be9fd")
    
    t.append("[t] ", style="bold #f1fa8c")
    t.append("切英美  ", style="#f1fa8c")
    
    t.append("│  ", style="dim #6272a4")
    t.append("[u] ", style="bold #ff79c6")
    t.append("撤回  ", style="#ff79c6")
    
    t.append("[/] ", style="bold #50fa7b")
    t.append("查词  ", style="#50fa7b")
    
    t.append("[m] ", style="dim")
    t.append("伪装  ", style="dim")
    
    t.append("[b] ", style="dim")
    t.append("boss  ", style="dim")
    
    t.append("[q] ", style="dim")
    t.append("退出", style="dim")
    return t

def render_recall_hotkeys() -> Text:
    """看词回忆阶段快捷键导航栏"""
    t = Text()
    t.append("  [空格 / 回车] ", style="bold #50fa7b")
    t.append("看答案释义  ", style="#50fa7b")
    
    t.append("│  ", style="dim #6272a4")
    t.append("[p] ", style="bold #00f0ff")
    t.append("听发音  ", style="#00f0ff")
    
    t.append("[t] ", style="bold #f1fa8c")
    t.append("切英美音  ", style="#f1fa8c")
    
    t.append("│  ", style="dim #6272a4")
    t.append("[u] ", style="bold #ff79c6")
    t.append("撤回  ", style="#ff79c6")
    
    t.append("[/] ", style="bold #50fa7b")
    t.append("即时查词  ", style="#50fa7b")
    
    t.append("[m] ", style="dim")
    t.append("切伪装  ", style="dim")
    
    t.append("[b] ", style="dim")
    t.append("老板键  ", style="dim")
    
    t.append("[q] ", style="dim")
    t.append("退出", style="dim")
    return t
