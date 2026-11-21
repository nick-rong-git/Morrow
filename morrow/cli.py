"""
Morrow 核心命令行控制与状态机循环 (Morrow CLI Core)
"""

import os
import sys
import time
import asyncio
from typing import Dict, Any, Optional

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

from .config import Config
from .audio import audio_engine
from .client import MorrowClient
from .ui import (
    render_banner,
    render_study_recall_card,
    render_study_answer_card,
    render_disguise_recall_panel,
    render_disguise_answer_panel,
    trigger_boss,
    show_dictionary_modal,
    show_advance_review_modal,
    show_completion_screen
)

# ============================================================================
# 异步非阻塞单键监听 (Windows Native msvcrt)
# ============================================================================

def _read_char_sync() -> str:
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()  # 过滤方向键扩展码
            return ""
        return ch
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

async def async_read_key() -> str:
    loop = asyncio.get_event_loop()
    while True:
        k = await loop.run_in_executor(None, _read_char_sync)
        if k:
            return k


def play_word_sound(word: Dict[str, Any], accent: str) -> None:
    speeches = word.get("speeches", {})
    url = speeches.get(accent.upper()) or word.get("audio_us") or word.get("audio_uk")
    if url:
        audio_engine.play_word(url, async_play=True)


# ============================================================================
# 学习循环控制器
# ============================================================================

async def run_learning_session(client: MorrowClient, config: Config, console: Console) -> None:
    streak_info = client.fetch_user_streak()
    streak = streak_info.get("streak", 1)

    # 取首词
    word = await client.get_word()
    if not word or not word.get("id"):
        # 队列已学完，直接进入通关/提前复习屏
        stats = {"total": 0, "known": 0, "fuzzy": 0, "forgot": 0, "mastered": 0}
        show_completion_screen(console, stats, streak)
        while True:
            k = await async_read_key()
            kl = k.lower()
            if kl == "q":
                return
            if kl == "r":
                added = await show_advance_review_modal(console, client)
                if added > 0:
                    word = await client.get_word()
                    if word and word.get("id"):
                        break
            if kl == "/":
                show_dictionary_modal(console)
                show_completion_screen(console, stats, streak)

    # 学习状态统计
    stats = {"total": 0, "known": 0, "fuzzy": 0, "forgot": 0, "mastered": 0}
    accent = config.accent
    ui_mode = config.ui_mode

    while word and word.get("id"):
        # 获取权威进度
        srv_finished = client.progress.get("finished", 0)
        srv_total = client.progress.get("total", 0) or 1
        current_idx = srv_finished + 1

        # 1. 播放单词真人发音
        if config.auto_play_audio:
            play_word_sound(word, accent)

        # 2. 静默预取例句的高保真神经 MP3，消除用户按键延迟
        phrases = word.get("phrases", [])
        if phrases:
            for p in phrases:
                p_en = p.get("en", "")
                if p_en:
                    audio_engine.prefetch_sentence(p_en, accent=accent)

        # ================= 第一屏：看词回忆阶段 =================
        recall_start = time.monotonic()
        skip_to_answer = False

        while True:
            if ui_mode == "study":
                render_study_recall_card(console, word, current_idx, srv_total, streak, accent)
            else:
                render_disguise_recall_panel(console, word, current_idx, srv_total)

            k = await async_read_key()
            kl = k.lower()

            if kl == "q":
                console.print(Text("\n[已安全退出学习]", style="dim #6272a4"))
                return
            if kl == "b":
                trigger_boss(console)
                await async_read_key()
                continue
            if kl == "p":
                play_word_sound(word, accent)
                continue
            if kl == "t":
                accent = "UK" if accent == "US" else "US"
                play_word_sound(word, accent)
                continue
            if kl == "m":
                ui_mode = "disguise" if ui_mode == "study" else "study"
                continue
            if kl in ("u", "\x08"):
                prev_word = await client.get_word(back=True)
                if prev_word and prev_word.get("id"):
                    word = prev_word
                    break
                continue
            if kl in ("/", "d"):
                show_dictionary_modal(console)
                recall_start = time.monotonic()
                continue

            # 任意其他键揭晓答案
            break

        recall_duration_ms = int((time.monotonic() - recall_start) * 1000)

        # ================= 第二屏：答案释义与评判阶段 =================
        judge_start = time.monotonic()
        status = ""

        # 自动朗读首条例句
        if config.auto_play_example and phrases:
            first_en = phrases[0].get("en", "")
            if first_en:
                audio_engine.speak_sentence(first_en, accent=accent)

        while True:
            if ui_mode == "study":
                render_study_answer_card(console, word, current_idx, srv_total, streak, accent, config.hide_judge_hint)
            else:
                render_disguise_answer_panel(console, word, current_idx, srv_total)

            k = await async_read_key()
            kl = k.lower()

            if kl == "q":
                console.print(Text("\n[已安全退出学习]", style="dim #6272a4"))
                return
            if kl == "b":
                trigger_boss(console)
                await async_read_key()
                judge_start = time.monotonic()
                continue
            if kl == "p":
                play_word_sound(word, accent)
                continue
            if kl == "e":
                if phrases:
                    audio_engine.speak_sentence(phrases[0].get("en", ""), accent=accent)
                continue
            if kl in ("4", "5", "6"):
                idx = int(kl) - 4
                if 0 <= idx < len(phrases):
                    audio_engine.speak_sentence(phrases[idx].get("en", ""), accent=accent)
                continue
            if kl == "t":
                accent = "UK" if accent == "US" else "US"
                play_word_sound(word, accent)
                continue
            if kl == "m":
                ui_mode = "disguise" if ui_mode == "study" else "study"
                continue
            if kl in ("u", "\x08"):
                prev_word = await client.get_word(back=True)
                if prev_word and prev_word.get("id"):
                    word = prev_word
                    break
                continue
            if kl in ("/", "d"):
                show_dictionary_modal(console)
                judge_start = time.monotonic()
                continue

            # 核心判答分支
            if kl in ("1", "j"):
                status = "RECOGNIZE"
                stats["known"] += 1
                stats["total"] += 1
                break
            elif kl in ("2", "k"):
                status = "FUZZY"
                stats["fuzzy"] += 1
                stats["total"] += 1
                break
            elif kl in ("3", "l"):
                status = "FORGET"
                stats["forgot"] += 1
                stats["total"] += 1
                break
            elif kl in ("0", "z"):
                status = "WELL_FAMILIAR"
                stats["mastered"] += 1
                stats["total"] += 1
                break

        if not status:
            continue

        study_duration_ms = int((time.monotonic() - judge_start) * 1000)

        # 提交判答结果
        ok = await client.submit_response(
            word_id=word["id"],
            result=status,
            sm_n=word.get("sm_n", 0),
            recall_duration=recall_duration_ms,
            study_duration=study_duration_ms
        )

        if ok and client.last_next_word and client.last_next_word.get("id"):
            word = client.last_next_word
        else:
            word = await client.get_word()

    # 循环完毕，通关大捷
    show_completion_screen(console, stats, streak)
    while True:
        k = await async_read_key()
        kl = k.lower()
        if kl == "q":
            return
        if kl == "r":
            added = await show_advance_review_modal(console, client)
            if added > 0:
                await run_learning_session(client, config, console)
                return
        if kl == "/":
            show_dictionary_modal(console)
            show_completion_screen(console, stats, streak)


# ============================================================================
# 主入口
# ============================================================================

def main():
    console = Console()
    config = Config("config.json")

    if not config.ws_token:
        console.print(Panel(
            "[bold red]错误：尚未配置 ws_token！[/bold red]\n"
            "请在 [bold #00f0ff]config.json[/bold #00f0ff] 中填入您的墨墨 token 后再启动。",
            box=CARD_BOX,
            border_style="red"
        ))
        return

    render_banner(console)

    async def _async_start():
        client = MorrowClient(ws_token=config.ws_token, rest_token=config.rest_token)
        console.print(Text("  正在建立安全长连接并同步学习进度 ...", style="dim #6272a4"))
        
        ok = await client.connect()
        if not ok:
            console.print(Text(f"  [连接失败] {client.last_error}", style="bold red"))
            return

        init_ok = await client.initialize()
        if not init_ok:
            console.print(Text("  [握手失败] 无法初始化墨墨学习会话", style="bold red"))
            await client.close()
            return

        streak_info = client.fetch_user_streak()
        streak = streak_info.get("streak", 1)

        # 渲染主菜单
        console.print()
        console.print(Text(f"  🔥 墨墨已连续打卡: {streak} 天  │  界面模式: [{config.ui_mode}]  │  默认发音: [{config.accent}]", style="bold #50fa7b"))
        console.print()
        console.print(Text("  按 [y] 开始背词   [r] 提前复习   [/] 查词典   [m] 切伪装模式   [q] 退出", style="bold #00f0ff"))

        while True:
            k = await async_read_key()
            kl = k.lower()
            if kl in ("y", "\r", " "):
                await run_learning_session(client, config, console)
                break
            elif kl == "r":
                added = await show_advance_review_modal(console, client)
                if added > 0:
                    await run_learning_session(client, config, console)
                    break
            elif kl == "/":
                show_dictionary_modal(console)
                console.print(Text("\n  按 [y] 开始背词   [r] 提前复习   [/] 查词典   [q] 退出", style="bold #00f0ff"))
            elif kl == "m":
                new_mode = "disguise" if config.ui_mode == "study" else "study"
                config.set("ui_mode", new_mode)
                config.save()
                console.print(Text(f"  [设置] 已切换至: [{new_mode}] 模式", style="bold #bd93f9"))
            elif kl == "q":
                break

        await client.close()
        console.print(Text("\n✦ 感谢使用 Morrow · Build for Tomorrow ✦\n", style="bold #00f0ff"))

    try:
        asyncio.run(_async_start())
    except KeyboardInterrupt:
        console.print(Text("\n[已中断退出]", style="dim #6272a4"))

if __name__ == "__main__":
    main()
