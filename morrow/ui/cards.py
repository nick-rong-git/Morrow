"""
Morrow 核心卡片渲染引擎 (Cards Engine)
包含两套顶级视觉模式：
1. 全功能学习卡片 (Study Card Mode)：高信息密度、优雅排版、例句发音指引。
2. 摸鱼代码伪装面板 (Disguise Mode)：100% 仿真为 IDE 编译输出与微服务日志。
"""

import time
import random
from typing import Dict, Any, List
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.align import Align
from rich.box import ROUNDED, SIMPLE, DOUBLE_EDGE

from .theme import (
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS,
    COLOR_WARNING, COLOR_DANGER, COLOR_MUTED, COLOR_TEXT_MAIN,
    CARD_BOX, STYLE_HIGHLIGHT
)
from .components import render_progress_bar, render_judge_hotkeys, render_recall_hotkeys

def _now_str() -> str:
    return time.strftime("%H:%M:%S")

# ============================================================================
# 全功能模式：看词回忆阶段卡片
# ============================================================================

def render_study_recall_card(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    streak: int = 1,
    accent: str = "US"
) -> None:
    console.clear()
    
    # 顶部进度
    console.print(render_progress_bar(current, total, streak))
    console.print()

    # 主词卡
    spelling = word.get("spelling", "")
    phonetic = word.get(f"phonetic_{accent.lower()}") or word.get("phonetic_us") or word.get("phonetic_uk") or ""
    hyphenation = word.get("hyphenation", "")
    difficulty = word.get("difficulty", 0)

    content = Text()
    content.append(f"\n{spelling}\n", style=f"bold {COLOR_PRIMARY}")
    
    if phonetic:
        content.append(f"/{phonetic}/ ", style=f"bold {COLOR_SECONDARY}")
        content.append(f"[{accent.upper()} 🔊]  ", style="dim #8be9fd")
        
    if hyphenation and hyphenation != spelling:
        content.append(f" ·  音节: {hyphenation}  ", style="dim #6272a4")
        
    if difficulty:
        content.append(" " + "★" * min(5, difficulty), style="#f1fa8c")
        
    content.append("\n\n(请在心中回忆释义与拼写，按任意键揭晓答案)\n", style="italic dim #6272a4")

    panel = Panel(
        Align.center(content),
        title=f"[dim]✦ MORROW STUDY · #{word.get('voc_id', '')} ✦[/dim]",
        box=CARD_BOX,
        border_style=COLOR_PRIMARY,
        padding=(1, 2)
    )
    console.print(panel)
    console.print()
    console.print(render_recall_hotkeys())


# ============================================================================
# 全功能模式：答案释义与例句阶段卡片
# ============================================================================

def render_study_answer_card(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    streak: int = 1,
    accent: str = "US",
    hide_judge_hint: bool = False
) -> None:
    console.clear()
    
    # 顶部进度
    console.print(render_progress_bar(current, total, streak))
    console.print()

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
    interp_table.add_column(width=8, style="bold #50fa7b")
    interp_table.add_column(style=f"bold {COLOR_TEXT_MAIN}")

    interpretations = word.get("interpretations", [])
    if not interpretations and word.get("interpretation"):
        interpretations = [l.strip() for l in word["interpretation"].split("\n") if l.strip()]

    for line in interpretations:
        line = line.strip()
        if not line:
            continue
        parts = line.split(".", 1)
        if len(parts) == 2 and len(parts[0]) <= 6:
            pos = parts[0].strip() + "."
            meaning = parts[1].strip()
            interp_table.add_row(f"[{pos}]", meaning)
        else:
            interp_table.add_row("•", line)

    # 3. 精选例句与短语
    phrases = word.get("phrases", [])
    phrase_elements: List[Text] = []
    for idx, p in enumerate(phrases[:3]):
        en = p.get("en", "")
        cn = p.get("cn", "")
        hl = p.get("highlight")
        tags = p.get("tags", [])

        pt = Text()
        pt.append(f"[{idx + 4}] ", style="bold #8be9fd")
        
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
    console.print(panel)
    console.print()

    if not hide_judge_hint:
        console.print(render_judge_hotkeys())


# ============================================================================
# 摸鱼模式：伪装为开发环境代码日志
# ============================================================================

def render_disguise_recall_panel(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int
) -> None:
    console.clear()
    spelling = word.get("spelling", "")
    
    console.print(Text(f"[{_now_str()}] [INFO]  [worker-pool] task_id=7410 ready: payload_len={len(spelling)*14}", style="dim #6272a4"))
    console.print(Text(f"[{_now_str()}] [DEBUG] [cache::redis] GET key=\"module_cache:{spelling}\" -> miss (0.24ms)", style="dim #6272a4"))
    
    # 单词伪装为待编译变量名
    line = Text()
    line.append(f"[{_now_str()}] [TRACE] ", style="dim #6272a4")
    line.append("resolving symbol ", style="#8be9fd")
    line.append(f'"{spelling}"', style=f"bold {COLOR_PRIMARY}")
    line.append(f" (idx: {current}/{total}) ...", style="dim #6272a4")
    console.print(line)
    
    console.print()
    console.print(Text("  ^ [Space/Enter] inspect struct  [p] audio  [u] undo  [/] search  [m] switch mode  [b] boss", style="dim #6272a4"))


def render_disguise_answer_panel(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int
) -> None:
    console.clear()
    spelling = word.get("spelling", "")
    interpretation = word.get("interpretation", "").replace("\n", " ; ")
    
    console.print(Text(f"[{_now_str()}] [INFO]  [compiler] parsed AST for symbol \"{spelling}\"", style="dim #6272a4"))
    
    # 释义伪装为文档注释
    line = Text()
    line.append(f"[{_now_str()}] [DOC]   ", style="dim #50fa7b")
    line.append(f"/** {interpretation} */", style=f"bold {COLOR_TEXT_MAIN}")
    console.print(line)

    phrases = word.get("phrases", [])
    if phrases:
        p_en = phrases[0].get("en", "")
        p_cn = phrases[0].get("cn", "")
        console.print(Text(f"[{_now_str()}] [TEST]  example: \"{p_en}\" // {p_cn}", style="dim #8be9fd"))

    console.print()
    console.print(Text("  [1] pass(认识)  [2] retry(模糊)  [3] fail(忘记)  [0] archive(斩词)  |  [p] audio  [e] sentence  |  [u] undo  [m] mode", style="dim #6272a4"))
