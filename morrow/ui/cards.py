"""
Morrow 核心卡片渲染引擎 (Cards Engine)
包含两套顶级视觉模式：
1. 全功能学习卡片 (Study Card Mode)：高信息密度、优雅排版、例句发音指引。
2. 代码伪装模式 (Disguise Mode)：用单色 JSON 显示当前单词。
"""

import json
from typing import Any, Dict, Iterator, List
from rich.console import Console, Group
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.align import Align

from .theme import (
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_TEXT_MAIN,
    CARD_BOX, STYLE_HIGHLIGHT
)
from .components import render_progress_bar, render_judge_hotkeys, render_recall_hotkeys
from .viewport import CardViewport, draw_card

PARTS_OF_SPEECH = {
    "a", "abbr", "ad", "adj", "adv", "art", "aux", "conj", "det", "int", "interj",
    "modal", "n", "num", "phr", "prep", "pron", "v", "vi", "vt",
}
EXAMPLE_KEYS = ("4", "5", "6")


def _definition_rows(word: Dict[str, Any]) -> Iterator[tuple[str, str]]:
    interpretations = word.get("interpretations") or [word.get("interpretation") or ""]
    for interpretation in interpretations:
        for raw_line in interpretation.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            prefix, dot, meaning = line.partition(".")
            prefix = prefix.rstrip()
            if dot and prefix.lower() in PARTS_OF_SPEECH:
                yield f"[{prefix}.]", meaning.lstrip()
            else:
                yield "", line


def get_study_examples(word: Dict[str, Any]) -> List[Dict[str, Any]]:
    phrases = word.get("phrases") or []
    return [phrase for phrase in phrases if phrase.get("en", "").strip()][:len(EXAMPLE_KEYS)]

# ============================================================================
# 全功能模式：看词回忆阶段卡片
# ============================================================================

def render_study_recall_card(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    streak: int | None = None,
    accent: str = "US",
    hide_judge_hint: bool = False,
    *,
    viewport: CardViewport | None = None,
) -> None:
    # 主词卡
    spelling = word.get("spelling", "")
    phonetic_accent = accent if word.get(f"phonetic_{accent.lower()}") else ("US" if word.get("phonetic_us") else "UK")
    phonetic = word.get(f"phonetic_{phonetic_accent.lower()}", "")
    hyphenation = word.get("hyphenation", "")
    difficulty = word.get("difficulty", 0)

    content = Text()
    content.append(f"\n{spelling}\n", style=f"bold {COLOR_PRIMARY}")
    
    if phonetic:
        content.append(f"/{phonetic}/ ", style=f"bold {COLOR_SECONDARY}")
        content.append(f"[{phonetic_accent} 🔊]  ", style="dim #8be9fd")
        
    if hyphenation and hyphenation != spelling:
        content.append(f" ·  音节: {hyphenation}  ", style="dim #6272a4")
        
    if difficulty:
        content.append(" " + "★" * min(5, difficulty), style="#f1fa8c")
        
    content.append("\n\n(先回忆读音和释义，再按空格或回车查看答案)\n", style="italic dim #6272a4")

    panel = Panel(
        Align.center(content),
        title=f"[dim]✦ MORROW STUDY · #{word.get('voc_id', '')} ✦[/dim]",
        box=CARD_BOX,
        border_style=COLOR_PRIMARY,
        padding=(1, 2)
    )
    hint = Text("  [h] 显示提示", style="dim #44475a") if hide_judge_hint else render_recall_hotkeys()
    draw_card(console, Group(render_progress_bar(current, total, streak), Text(), panel), hint, viewport)


# ============================================================================
# 全功能模式：答案释义与例句阶段卡片
# ============================================================================

def render_study_answer_card(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    streak: int | None = None,
    accent: str = "US",
    hide_judge_hint: bool = False,
    *,
    viewport: CardViewport | None = None,
) -> None:
    # 1. 词头与发音信息
    spelling = word.get("spelling", "")
    phonetic_us = word.get("phonetic_us", "")
    phonetic_uk = word.get("phonetic_uk", "")
    hyphenation = word.get("hyphenation", "")
    difficulty = word.get("difficulty", 0)

    header_table = Table.grid(padding=(0, 2))
    header_table.add_column()
    header_table.add_column()

    word_t = Text()
    word_t.append(spelling, style=f"bold {COLOR_PRIMARY}")
    if hyphenation and hyphenation != spelling:
        word_t.append(f"  [{hyphenation}]", style="dim #6272a4")
    if difficulty:
        word_t.append(f"  {'★' * min(5, difficulty)}", style="#f1fa8c")

    ph_t = Text()
    if phonetic_us:
        ph_t.append(f"US /{phonetic_us}/ ", style="bold #bd93f9")
    if phonetic_uk:
        ph_t.append(f"UK /{phonetic_uk}/ ", style="#8be9fd")
    ph_t.append(f" (当前: {accent.upper()} 🔊)", style="dim #50fa7b")

    header_table.add_row(word_t, ph_t)

    # 2. 词义解析 (分词性药丸高亮)
    interp_table = Table(show_header=False, box=None, padding=(0, 1), collapse_padding=True)
    interp_table.add_column(min_width=8, no_wrap=True, style="bold #50fa7b")
    interp_table.add_column(style=f"bold {COLOR_TEXT_MAIN}")

    for label, meaning in _definition_rows(word):
        interp_table.add_row(Text(label or "•"), Text(meaning))

    # 3. 精选例句与短语
    phrase_elements: List[Text] = []
    for key, p in zip(EXAMPLE_KEYS, get_study_examples(word)):
        en = p.get("en", "")
        cn = p.get("cn", "")
        hl = p.get("highlight")
        tags = p.get("tags", [])

        pt = Text()
        pt.append(f"[{key}] ", style="bold #8be9fd")
        
        # 关键词高亮
        if hl and len(hl) == 2 and 0 <= hl[0] < hl[1] <= len(en):
            pt.append(en[:hl[0]], style=COLOR_TEXT_MAIN)
            pt.append(en[hl[0]:hl[1]], style=STYLE_HIGHLIGHT)
            pt.append(en[hl[1]:], style=COLOR_TEXT_MAIN)
        else:
            pt.append(en, style=COLOR_TEXT_MAIN)

        pt.append("  [🔊]", style="bold #00f0ff")
        
        if tags:
            for tg in tags:
                pt.append(f" #{tg}", style="dim #bd93f9")

        pt.append(f"\n     {cn}\n", style="dim #8be9fd")
        phrase_elements.append(pt)

    # 4. 助记与记忆法
    notes = word.get("notes", [])
    note_elements: List[Text] = []
    for n in notes[:2]:
        title = n.get("title", "")
        content = n.get("content", "")
        if title or content:
            nt = Text()
            nt.append("💡 ", style="bold #f1fa8c")
            if title:
                nt.append(f"[{title}] ", style="bold #f1fa8c")
            nt.append(content, style="italic #f8f8f2")
            note_elements.append(nt)

    # 组装面板
    main_grid = Table.grid(padding=(1, 0))
    main_grid.add_column()
    main_grid.add_row(header_table)
    main_grid.add_row(interp_table)

    if phrase_elements:
        p_box = Table.grid(padding=(0, 0))
        p_box.add_column()
        p_box.add_row(Text("—— 权威真题与例句 (按 [4/5/6] 听真声朗读) ——", style="dim #6272a4"))
        for pe in phrase_elements:
            p_box.add_row(pe)
        main_grid.add_row(p_box)

    if note_elements:
        n_box = Table.grid(padding=(0, 0))
        n_box.add_column()
        for ne in note_elements:
            n_box.add_row(ne)
        main_grid.add_row(n_box)

    panel = Panel(
        main_grid,
        title=f"[bold {COLOR_PRIMARY}]✦ MORROW ANSWER ✦[/bold {COLOR_PRIMARY}]",
        box=CARD_BOX,
        border_style=COLOR_PRIMARY,
        padding=(1, 2)
    )
    hint = Text("  [h] 显示提示", style="dim #44475a") if hide_judge_hint else render_judge_hotkeys()
    draw_card(console, Group(render_progress_bar(current, total, streak), Text(), panel), hint, viewport)


# ============================================================================
# 代码伪装模式：单色 JSON
# ============================================================================

def _clean_phonetic(ph: str) -> str:
    if not ph:
        return ""
    p = ph.strip().strip("/").strip("[").strip("]").strip()
    return f"/{p}/" if p else ""


def render_disguise_recall_panel(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    hide_judge_hint: bool = False,
    *,
    viewport: CardViewport | None = None,
) -> None:
    spelling = word.get("spelling", "")
    ph = word.get("phonetic_us") or word.get("phonetic_uk") or ""

    # 极简实用 JSON（看词回忆阶段：仅保留词、音标与进度）
    data = {
        "word": spelling,
        "phonetic": _clean_phonetic(ph),
        "progress": f"{min(current, total)}/{total}" if total > 0 else str(current)
    }

    hint = "[h] show keys" if hide_judge_hint else (
        "[Enter/Space] view  [p] audio  [t] accent  [u] undo  [/] lookup  [h] hide  [m] mode  [Esc/b] boss  [q] quit"
    )
    draw_card(console, Text(json.dumps(data, ensure_ascii=False, indent=2)), Text(hint), viewport)


def render_disguise_answer_panel(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    hide_judge_hint: bool = False,
    *,
    viewport: CardViewport | None = None,
) -> None:
    spelling = word.get("spelling", "")
    ph = word.get("phonetic_us") or word.get("phonetic_uk") or ""

    definitions = [f"{label} {meaning}" if label else meaning for label, meaning in _definition_rows(word)]
    examples = []
    for phrase in get_study_examples(word):
        en = phrase["en"].strip()
        cn = phrase.get("cn", "").strip()
        examples.append(f"{en} // {cn}" if cn else en)

    data = {
        "word": spelling,
        "phonetic": _clean_phonetic(ph),
        "trans": definitions,
        "examples": examples,
        "progress": f"{min(current, total)}/{total}" if total > 0 else str(current)
    }

    # 助记笔记（如有则紧凑保留）
    notes = word.get("notes", [])
    if notes:
        n0 = notes[0]
        c = n0.get("content", "").strip()
        t = n0.get("title", "").strip()
        if c:
            data["note"] = f"[{t}] {c}" if t else c

    if hide_judge_hint:
        hint = "[h] show keys"
    else:
        keys = "/".join(EXAMPLE_KEYS[:len(examples)])
        example_hint = f"  [e] first  [{keys}] examples" if keys else ""
        hint = (
            f"[1] pass  [2] vague  [3] fail  [0] kill  |  [Enter/Space/p] replay word{example_hint}  [t] accent  |  "
            "[u] undo  [/] search  [h] hide  [m] mode  [Esc/b] boss  [q] quit"
        )
    draw_card(console, Text(json.dumps(data, ensure_ascii=False, indent=2)), Text(hint), viewport, soft_wrap=True)
