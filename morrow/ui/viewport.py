"""Keep the word card within the visible terminal and scroll its body."""

from rich.console import Console, RenderableType
from rich.segment import SegmentLines
from rich.text import Text


class CardViewport:
    def __init__(self) -> None:
        self.top = 0
        self.page_rows = 1
        self.feedback = ""

    def scroll(self, key: str) -> None:
        delta = {"up": -1, "down": 1, "page_up": -self.page_rows, "page_down": self.page_rows}
        self.top = max(0, self.top + delta[key])


def draw_card(
    console: Console,
    body: RenderableType,
    hint: Text,
    viewport: CardViewport | None,
    *,
    soft_wrap: bool = False,
) -> None:
    console.clear()
    feedback = Text(viewport.feedback, style="bold #f1fa8c") if viewport and viewport.feedback else None
    if viewport is None or not console.is_alt_screen or console.is_dumb_terminal:
        console.print(body, soft_wrap=soft_wrap)
        console.print()
        console.print(hint)
        if feedback is not None:
            console.print(feedback)
        return

    # Leave the last terminal row free so even a full frame cannot scroll.
    height = max(1, console.size.height - 1)
    lines = console.render_lines(body, pad=False)
    footer = console.render_lines(hint, pad=False)
    if feedback is not None:
        footer = console.render_lines(feedback, pad=False) + footer
    if len(lines) + len(footer) > height:
        scroll_hint = Text("↑/↓  PgUp/PgDn", style="dim")
        footer = console.render_lines(scroll_hint, pad=False) + footer

    footer = footer[:height - 1]
    viewport.page_rows = height - len(footer)
    viewport.top = min(viewport.top, max(0, len(lines) - viewport.page_rows))
    visible = lines[viewport.top:viewport.top + viewport.page_rows]
    if len(visible) + len(footer) < height:
        visible.append([])
    console.print(SegmentLines(visible + footer, new_lines=True), end="")
