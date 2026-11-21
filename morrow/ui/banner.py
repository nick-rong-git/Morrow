"""
Morrow 品牌 ASCII 艺术 Banner 与标头
"""

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.align import Align
from .theme import COLOR_PRIMARY, COLOR_SECONDARY, COLOR_MUTED, CARD_BOX

MORROW_ASCII = r"""
 ███╗   ███╗ ██████╗ ██████╗ ██████╗  ██████╗ ██╗    ██╗
 ████╗ ████║██╔═══██╗██╔══██╗██╔══██╗██╔═══██╗██║    ██║
 ██╔████╔██║██║   ██║██████╔╝██████╔╝██║   ██║██║ █╗ ██║
 ██║╚██╔╝██║██║   ██║██╔══██╗██╔══██╗██║   ██║██║███╗██║
 ██║ ╚═╝ ██║╚██████╔╝██║  ██║██║  ██║╚██████╔╝╚███╔███╔╝
 ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ 
"""

TAGLINE = "✦ MORROW ✦ 极简终端背单词系统 · Build for Tomorrow"

def render_banner(console: Console) -> None:
    t = Text(MORROW_ASCII.strip("\n"), style=f"bold {COLOR_PRIMARY}")
    sub = Text(f"\n{TAGLINE}\n", style=f"bold {COLOR_SECONDARY}")
    panel = Panel(
        Align.center(t + sub),
        box=CARD_BOX,
        border_style=COLOR_PRIMARY,
        padding=(0, 2)
    )
    console.print(panel)

def get_mini_header() -> Text:
    t = Text()
    t.append("✦ MORROW ✦", style=f"bold {COLOR_PRIMARY}")
    t.append(" · Terminal Vocabulary", style=f"dim {COLOR_MUTED}")
    return t
