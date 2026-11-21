"""
Morrow 核心卡片渲染引擎 (Cards Engine)
包含两套顶级视觉模式：
1. 全功能学习卡片 (Study Card Mode)：高信息密度、优雅排版、例句发音指引。
2. 摸鱼代码伪装面板 (Disguise Mode)：100% 仿真为 IDE 编译输出与微服务日志。
"""

import time
import json
from typing import Dict, Any, List
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.align import Align

from .theme import (
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_TEXT_MAIN,
    CARD_BOX, STYLE_HIGHLIGHT
)
from .components import render_progress_bar, render_judge_hotkeys, render_recall_hotkeys

PARTS_OF_SPEECH = {
    "a", "abbr", "ad", "adj", "adv", "art", "aux", "conj", "det", "int", "interj",
    "modal", "n", "num", "phr", "prep", "pron", "v", "vi", "vt",
}

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
    streak: int | None = None,
    accent: str = "US",
    hide_judge_hint: bool = False
) -> None:
    console.clear()
    
    # 顶部进度
    console.print(render_progress_bar(current, total, streak))
    console.print()

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
        
    content.append("\n\n(回忆释义后，按空格或回车查看答案)\n", style="italic dim #6272a4")

    panel = Panel(
        Align.center(content),
        title=f"[dim]✦ MORROW STUDY · #{word.get('voc_id', '')} ✦[/dim]",
        box=CARD_BOX,
        border_style=COLOR_PRIMARY,
        padding=(1, 2)
    )
    console.print(panel)
    console.print()
    if not hide_judge_hint:
        console.print(render_recall_hotkeys())
    else:
        console.print(Text("  [h] 显示提示", style="dim #44475a"))


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
    interp_table.add_column(min_width=8, no_wrap=True, style="bold #50fa7b")
    interp_table.add_column(style=f"bold {COLOR_TEXT_MAIN}")

    interpretations = word.get("interpretations") or [word.get("interpretation") or ""]
    for interpretation in interpretations:
        for raw_line in interpretation.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            prefix, dot, meaning = line.partition(".")
            prefix = prefix.rstrip()
            if dot and prefix.lower() in PARTS_OF_SPEECH:
                interp_table.add_row(Text(f"[{prefix}.]"), Text(meaning.lstrip()))
            else:
                interp_table.add_row("•", Text(line))

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
    else:
        console.print(Text("  [h] 显示提示", style="dim #44475a"))


# ============================================================================
# 摸鱼模式：伪装为标准无色 JSON API 响应 / 配置载荷
# ============================================================================

def render_disguise_recall_panel(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    hide_judge_hint: bool = False,
) -> None:
    console.clear()
    spelling = word.get("spelling", "")
    phonetic_us = word.get("phonetic_us", "")
    phonetic_uk = word.get("phonetic_uk", "")
    hyphenation = word.get("hyphenation", "")
    difficulty = word.get("difficulty", 0)

    # 构造全面真实的 JSON 载荷（未揭晓阶段，无中文释义泄漏）
    data = {
        "status": "pending_eval",
        "timestamp": int(time.time()),
        "query": {
            "symbol": spelling,
            "phonetic": {
                "us": f"/{phonetic_us}/" if phonetic_us else "",
                "uk": f"/{phonetic_uk}/" if phonetic_uk else ""
            },
            "syllables": hyphenation,
            "difficulty_level": difficulty
        },
        "payload": {
            "resolved": False,
            "message": "awaiting evaluation; press [space/enter] to fetch definition and examples"
        },
        "session": {
            "index": min(current, total) if total > 0 else current,
            "total": total,
            "remaining": max(0, total - current)
        }
    }

    # 序列化为规范 JSON 字符串
    json_text = json.dumps(data, ensure_ascii=False, indent=2)

    # 保证字体 100% 没有任何颜色（无 ANSI 转义代码，关闭所有高亮与 markup）
    console.print(json_text, markup=False, highlight=False, style="none")
    console.print()

    # 底栏提示行也保持完全单色无色
    if hide_judge_hint:
        console.print("[h] show keys", markup=False, highlight=False, style="none")
    else:
        console.print("[Space/Enter] inspect payload  [p] audio  [t] accent  [u] undo  [/] lookup  [h] hide  [m] mode  [b] boss  [q] quit", markup=False, highlight=False, style="none")


def render_disguise_answer_panel(
    console: Console,
    word: Dict[str, Any],
    current: int,
    total: int,
    hide_judge_hint: bool = False,
) -> None:
    console.clear()
    spelling = word.get("spelling", "")
    phonetic_us = word.get("phonetic_us", "")
    phonetic_uk = word.get("phonetic_uk", "")
    hyphenation = word.get("hyphenation", "")
    difficulty = word.get("difficulty", 0)

    # 提取完整词性与释义结构
    definitions = []
    interpretations = word.get("interpretations", [])
    if not interpretations and word.get("interpretation"):
        interpretations = [l.strip() for l in word["interpretation"].split("\n") if l.strip()]

    for line in interpretations:
        line = line.strip()
        if not line:
            continue
        parts = line.split(".", 1)
        if len(parts) == 2 and len(parts[0]) <= 6:
            definitions.append({
                "pos": parts[0].strip() + ".",
                "meaning": parts[1].strip()
            })
        else:
            definitions.append({
                "meaning": line
            })

    # 提取全部权威真题例句
    examples = []
    for idx, p in enumerate(word.get("phrases", [])):
        examples.append({
            "id": idx + 1,
            "en": p.get("en", ""),
            "cn": p.get("cn", ""),
            "tags": p.get("tags", [])
        })

    # 助记笔记
    notes = []
    for n in word.get("notes", []):
        t = n.get("title", "")
        c = n.get("content", "")
        if t or c:
            notes.append({
                "title": t,
                "content": c
            })

    # 构造全面详尽的 JSON 响应
    data = {
        "status": "resolved",
        "code": 200,
        "timestamp": int(time.time()),
        "query": {
            "symbol": spelling,
            "phonetic": {
                "us": f"/{phonetic_us}/" if phonetic_us else "",
                "uk": f"/{phonetic_uk}/" if phonetic_uk else ""
            },
            "syllables": hyphenation,
            "difficulty_level": difficulty
        },
        "definitions": definitions,
        "examples": examples,
        "notes": notes,
        "session": {
            "index": min(current, total) if total > 0 else current,
            "total": total,
            "remaining": max(0, total - current)
        }
    }

    # 序列化为规范 JSON 字符串
    json_text = json.dumps(data, ensure_ascii=False, indent=2)

    # 保证字体 100% 没有任何颜色（无 ANSI 转义代码，关闭所有高亮与 markup）
    console.print(json_text, markup=False, highlight=False, style="none")
    console.print()

    # 判答提示行也保持完全单色无色
    if hide_judge_hint:
        console.print("[h] show keys", markup=False, highlight=False, style="none")
    else:
        console.print("[1] pass  [2] vague  [3] fail  [0] archive  |  [p] audio  [e] sentence  [t] accent  |  [u] undo  [/] search  [h] hide  [m] mode  [b] boss  [q] quit", markup=False, highlight=False, style="none")
