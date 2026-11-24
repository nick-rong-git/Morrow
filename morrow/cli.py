"""Morrow 命令行入口与学习流程。"""

import asyncio
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict

from rich.console import Console
from rich.text import Text

from .audio import audio_engine
from .client import MorrowClient
from .config import Config
from .terminal import terminal_session
from .ui.viewport import CardViewport
from .ui import (
    EXAMPLE_KEYS,
    get_study_examples,
    render_banner,
    render_disguise_answer_panel,
    render_disguise_recall_panel,
    render_study_answer_card,
    render_study_recall_card,
    show_advance_review_modal,
    show_completion_screen,
    show_dictionary_modal,
    show_settings_modal,
    show_token_wizard,
    trigger_boss,
)

JUDGMENTS = {
    "1": ("FAMILIAR", "known"), "j": ("FAMILIAR", "known"),
    "2": ("VAGUE", "fuzzy"), "k": ("VAGUE", "fuzzy"),
    "3": ("FORGET", "forgot"), "l": ("FORGET", "forgot"),
    "0": ("WELL_FAMILIAR", "mastered"), "z": ("WELL_FAMILIAR", "mastered"),
}
WINDOWS_SCROLL_KEYS = {"H": "up", "P": "down", "I": "page_up", "Q": "page_down"}
ANSI_SCROLL_KEYS = {
    b"[A": "up", b"[B": "down", b"OA": "up", b"OB": "down",
    b"[5~": "page_up", b"[6~": "page_down",
}


class StudyError(Exception):
    """当前学习会话无法继续。"""


async def async_read_key() -> str:
    if not sys.stdin.isatty():
        key = await asyncio.to_thread(sys.stdin.read, 1)
        if not key:
            raise EOFError
        return key

    if sys.platform == "win32":
        import msvcrt

        while True:
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in ("\x00", "\xe0"):
                    scroll_key = WINDOWS_SCROLL_KEYS.get(msvcrt.getwch())
                    if scroll_key:
                        return scroll_key
                elif key == "\x03":
                    raise KeyboardInterrupt
                else:
                    return key
            await asyncio.sleep(0.025)

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            if select.select([fd], [], [], 0)[0]:
                key = os.read(fd, 1)
                if not key or key == b"\x04":
                    raise EOFError
                if key != b"\x1b" or not select.select([fd], [], [], 0.025)[0]:
                    return key.decode("ascii", errors="replace")
                sequence = os.read(fd, 1)
                if sequence in (b"[", b"O"):
                    while select.select([fd], [], [], 0.025)[0]:
                        part = os.read(fd, 1)
                        sequence += part
                        if not part or b"@" <= part <= b"~":
                            break
                if sequence in ANSI_SCROLL_KEYS:
                    return ANSI_SCROLL_KEYS[sequence]
            await asyncio.sleep(0.025)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


async def _read_command(console: Console) -> str:
    key = (await async_read_key()).lower()
    if key in ("\x1b", "b"):
        audio_engine.stop()
        trigger_boss(console)
        await async_read_key()
        return ""
    return key


def word_audio_url(word: Dict[str, Any], accent: str) -> str:
    speeches = word.get("speeches", {})
    return speeches.get(accent) or word.get(f"audio_{accent.lower()}") or word.get("audio_us") or word.get("audio_uk") or ""


def play_word_sound(word: Dict[str, Any], accent: str, *, example: str = "") -> None:
    audio_engine.play_word(word_audio_url(word, accent), fallback_text=word.get("spelling", ""), accent=accent, example=example)


async def _get_word(client: MorrowClient) -> Dict[str, Any]:
    word = await client.get_word()
    if word is None:
        raise StudyError(client.last_error or "无法取词")
    return word


async def run_learning_session(
    client: MorrowClient, config: Config, console: Console,
) -> None:
    stats = {"total": 0, "known": 0, "fuzzy": 0, "forgot": 0, "mastered": 0}
    history = []
    accent = config.accent
    ui_mode = config.ui_mode
    word_audio_timing = config.word_audio_timing
    word = await _get_word(client)

    while True:
        if not word.get("id"):
            audio_engine.stop()
            show_completion_screen(console, stats)
            key = await _read_command(console)
            if key == "q":
                if not console.is_alt_screen:
                    console.print(Text("\n[已退出学习]", style="dim #6272a4"))
                return
            if key == "r" and await show_advance_review_modal(console, client):
                word = await _get_word(client)
            if key == "/":
                await show_dictionary_modal(console)
            continue

        phrases = [phrase["en"] for phrase in get_study_examples(word)]
        finished = client.progress.get("finished", 0)
        total = client.progress.get("total", 0)
        recall_start = time.monotonic()
        judge_start = None
        recall_ms = 0
        reveal_audio = False
        viewport = CardViewport()
        audio_engine.stop()
        audio_engine.prefetch_word(word_audio_url(word, accent), fallback_text=word.get("spelling", ""), accent=accent)
        if word_audio_timing == "recall":
            play_word_sound(word, accent)
        for phrase in phrases:
            audio_engine.prefetch_sentence(phrase, accent=accent)

        while True:
            answered = judge_start is not None
            if ui_mode == "study":
                render = render_study_answer_card if answered else render_study_recall_card
                render(console, word, finished, total, accent=accent,
                       hide_judge_hint=config.hide_judge_hint, viewport=viewport)
            else:
                render = render_disguise_answer_panel if answered else render_disguise_recall_panel
                render(console, word, finished + 1, total, config.hide_judge_hint, viewport=viewport)
            viewport.feedback = ""

            if reveal_audio:
                reveal_audio = False
                example = phrases[0] if config.auto_play_example and phrases else ""
                if word_audio_timing == "answer":
                    play_word_sound(word, accent, example=example)
                elif example:
                    audio_engine.speak_sentence(example, accent=accent)

            key = await _read_command(console)
            if key == "q":
                return
            elif key in ("up", "down", "page_up", "page_down"):
                viewport.scroll(key)
            elif key == "h":
                if not config.update(hide_judge_hint=not config.hide_judge_hint):
                    viewport.feedback = "无法保存提示栏设置。"
            elif key == "p":
                play_word_sound(word, accent)
            elif key == "t":
                accent = "UK" if accent == "US" else "US"
                audio_engine.prefetch_word(word_audio_url(word, accent), fallback_text=word.get("spelling", ""), accent=accent)
                if answered:
                    play_word_sound(word, accent)
                for phrase in phrases:
                    audio_engine.prefetch_sentence(phrase, accent=accent)
            elif key == "m":
                ui_mode = "disguise" if ui_mode == "study" else "study"
                viewport.top = 0
            elif key in ("u", "\x08", "\x7f"):
                previous = await client.get_word(back=True)
                if previous is None:
                    if not client.last_request_rejected:
                        raise StudyError(f"{client.last_error or '连接中断'}。撤回结果未确认，请重新进入学习并同步进度。")
                    viewport.feedback = client.last_error or "无法撤回判答"
                elif previous.get("id"):
                    if history and history[-1][0] == previous["id"]:
                        _, category = history.pop()
                        stats[category] -= 1
                        stats["total"] -= 1
                    word = previous
                    break
                else:
                    viewport.feedback = "没有可撤回的单词。"
            elif key in ("/", "d"):
                await show_dictionary_modal(console)
                if answered:
                    judge_start = time.monotonic()
                else:
                    recall_start = time.monotonic()
            elif key in (" ", "\r", "\n"):
                if answered:
                    play_word_sound(word, accent)
                else:
                    judge_start = time.monotonic()
                    recall_ms = int((judge_start - recall_start) * 1000)
                    reveal_audio = True
                    viewport.top = 0
            elif answered and (key == "e" or key in EXAMPLE_KEYS):
                index = 0 if key == "e" else EXAMPLE_KEYS.index(key)
                if index < len(phrases):
                    audio_engine.speak_sentence(phrases[index], accent=accent)
            elif answered and key in JUDGMENTS:
                response, category = JUDGMENTS[key]
                ok = await client.submit_response(
                    word_id=word["id"], response=response, study_method="STUDY_EN_CN",
                    recall_duration=recall_ms,
                    study_duration=int((time.monotonic() - judge_start) * 1000),
                )
                if not ok:
                    if client.last_request_rejected:
                        viewport.feedback = client.last_error or "判答未保存，请重试。"
                        continue
                    raise StudyError(f"{client.last_error or '连接中断'}。判答结果未确认，请重新进入学习并同步进度。")
                history.append((word["id"], category))
                stats[category] += 1
                stats["total"] += 1
                word = client.last_next_word
                if word is None:
                    word = await _get_word(client)
                break


def _render_menu(
    console: Console, config: Config, progress: Dict[str, int], message: str, *, rest_auth_failed: bool = False,
) -> None:
    console.clear()
    render_banner(console)
    if progress:
        console.print(Text(f"  墨墨今日进度 {progress['finished']}/{progress['total']} 词", style="bold #50fa7b"))
    elif rest_auth_failed:
        console.print(Text("  开放 API 凭证已失效或缺少权限。按 [s] → [2] 更新。", style="bold #f1fa8c"))
    elif config.rest_token:
        console.print(Text("  墨墨今日进度暂不可用", style="dim #6272a4"))
    console.print(Text(f"  界面模式 [{config.ui_mode}]  │  默认发音 [{config.accent}]", style="bold #50fa7b"))
    if message:
        console.print(Text(f"  {message}", style="bold #f1fa8c"))
    console.print()
    if config.hide_judge_hint:
        console.print(Text("  [y] 开始背词  [s] 设置  [h] 显示提示  [q] 退出", style="dim #6272a4"))
    else:
        console.print(Text(
            "  [y] 开始背词  [r] 提前复习  [/] 查词典  [s] 设置  [m] 切换模式  [h] 隐藏提示  [Esc/b] 老板键  [q] 退出",
            style="bold #00f0ff",
        ))


async def _connect(client: MorrowClient, console: Console) -> None:
    console.print(Text("  正在连接墨墨并同步学习进度 …", style="dim #6272a4"))
    if not await client.connect() or not await client.initialize():
        await client.close()
        raise StudyError(f"{client.last_error or '学习会话初始化失败'}。按 [y] 重试，或按 [s] 检查凭证。")
    client.progress = await asyncio.to_thread(client.fetch_study_progress)


async def _run(console: Console, config: Config) -> None:
    client = None
    message = ""
    try:
        if not config.ws_token:
            await show_token_wizard(console, config, reason="missing")
        if config.ws_token:
            client = MorrowClient(config.ws_token, config.rest_token)
            try:
                await _connect(client, console)
            except StudyError as exc:
                message = str(exc)
        else:
            message = "尚未配置 ws_token，可在设置中继续配置。"

        while True:
            _render_menu(
                console, config, client.progress if client else {}, message,
                rest_auth_failed=bool(client and client.rest_auth_failed),
            )
            message = ""
            key = await _read_command(console)
            if key == "q":
                return
            if key == "/":
                await show_dictionary_modal(console)
            elif key == "s":
                await show_settings_modal(console, config)
                if client is not None and client.ws_token != config.ws_token:
                    await client.close()
                    client = None
                    message = "背词凭证已更新，开始背词时将连接墨墨。"
                elif client is not None and client.rest_token != config.rest_token:
                    client.rest_token = config.rest_token
                    client.progress = await asyncio.to_thread(client.fetch_study_progress)
            elif key == "h":
                if not config.update(hide_judge_hint=not config.hide_judge_hint):
                    message = "无法保存提示栏设置。"
            elif key == "m":
                mode = "disguise" if config.ui_mode == "study" else "study"
                if not config.update(ui_mode=mode):
                    message = "无法保存界面模式。"
            elif key in ("y", " ", "\r", "\n", "r"):
                if not config.ws_token and not await show_token_wizard(console, config, reason="missing"):
                    continue
                try:
                    if client is None:
                        client = MorrowClient(config.ws_token, config.rest_token)
                    if not client.is_alive:
                        await _connect(client, console)
                    if key == "r" and not await show_advance_review_modal(console, client):
                        continue
                    await run_learning_session(client, config, console)
                    return
                except StudyError as exc:
                    await client.close()
                    message = str(exc)
                finally:
                    audio_engine.stop()
    finally:
        audio_engine.stop()
        if client is not None:
            await client.close()


def main() -> None:
    config = Config(Path(__file__).resolve().parent.parent / "config.json")
    audio_engine.cache_dir = config.config_path.parent / config.data_dir / "audio_cache"
    with terminal_session() as console:
        try:
            asyncio.run(_run(console, config))
        except KeyboardInterrupt:
            console.print(Text("\n[已中断退出]", style="dim #6272a4"))
        except EOFError:
            pass


if __name__ == "__main__":
    main()
