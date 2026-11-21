"""
Morrow 模态弹窗与特色视图 (Views)
包含即时查词典、老板键伪装、提前复习加词、今日通关大捷等交互界面。
"""

import asyncio
import re
import webbrowser
from typing import Dict, Any
from rich.box import DOUBLE_EDGE
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.align import Align
from rich.prompt import Prompt

from .theme import CARD_BOX, MODAL_BOX
from ..clipboard import clipboard_sequence, read_copied_text
from ..client import MorrowClient
from ..dict import lookup_dictionary
from ..audio import audio_engine
from ..web_login import (
    OPEN_API_TOKEN_URL, WEB_STUDY_URL, WebLoginError, sign_in_via_browser, token_from_study_url,
)


async def _ask(console: Console, prompt: str, **options) -> str:
    return await asyncio.to_thread(Prompt.ask, prompt, console=console, **options)

# ============================================================================
# 老板键一键救急屏
# ============================================================================

def trigger_boss(console: Console) -> None:
    """老板键：一键全屏伪装成系统后台日志或 top 监控"""
    console.clear()
    t = Table(show_header=True, header_style="bold #6272a4", box=None)
    t.add_column("PID", width=8)
    t.add_column("USER", width=10)
    t.add_column("PR", width=4)
    t.add_column("NI", width=4)
    t.add_column("VIRT", width=10)
    t.add_column("RES", width=10)
    t.add_column("SHR", width=8)
    t.add_column("S", width=4)
    t.add_column("%CPU", width=8)
    t.add_column("%MEM", width=8)
    t.add_column("TIME+", width=10)
    t.add_column("COMMAND")

    processes = [
        ("1402", "root", "20", "0", "1254M", "312M", "48M", "S", "1.2", "4.1", "12:45.12", "/usr/bin/dockerd -H fd://"),
        ("2190", "deploy", "20", "0", "842M", "184M", "32M", "S", "0.8", "2.4", "04:12.80", "node /app/server.js"),
        ("3881", "postgres", "20", "0", "2104M", "640M", "128M", "S", "2.4", "8.0", "31:02.15", "postgres: main: db cluster"),
        ("4901", "root", "20", "0", "312M", "42M", "12M", "S", "0.0", "0.5", "01:10.02", "/usr/sbin/sshd -D"),
        ("6201", "redis", "20", "0", "410M", "92M", "18M", "S", "0.4", "1.2", "08:14.33", "redis-server *:6379"),
        ("7112", "deploy", "20", "0", "112M", "24M", "8M", "R", "0.1", "0.3", "00:04.18", "htop --delay=15"),
    ]
    for p in processes:
        t.add_row(*p)

    console.print(Text("top - 15:02:14 up 42 days, 3 users,  load average: 0.18, 0.24, 0.20", style="bold #6272a4"))
    console.print(Text("Tasks: 142 total,   1 running, 141 sleeping,   0 stopped,   0 zombie", style="dim #6272a4"))
    console.print(Text("%Cpu(s):  1.8 us,  0.6 sy,  0.0 ni, 97.4 id,  0.1 wa,  0.0 hi,  0.1 si", style="dim #6272a4"))
    console.print(Text("MiB Mem :  16024.0 total,   6124.2 free,   5420.1 used,   4479.7 buff/cache", style="dim #6272a4"))
    console.print()
    console.print(t)
    console.print()
    console.print(Text("  [任意键安全返回学习界面 ...]", style="dim italic #44475a"))


# ============================================================================
# 终端即时查词典弹窗 (/)
# ============================================================================

async def show_dictionary_modal(console: Console) -> None:
    console.print()
    word_input = (await _ask(console, "  [bold #00f0ff]🔍 请输入要查询的单词[/bold #00f0ff] (直接按回车取消)")).strip()
    if not word_input:
        return

    console.print(Text(f"  正在联网检索 \"{word_input}\" ...", style="dim #6272a4"))
    res = await asyncio.to_thread(lookup_dictionary, word_input)

    content = Table.grid(padding=(0, 1))
    content.add_column()

    title_t = Text()
    title_t.append(res["word"], style="bold #00f0ff")
    if res.get("phonetic"):
        title_t.append(f"  /{res['phonetic']}/", style="italic #bd93f9")
    content.add_row(title_t)
    content.add_row(Text(" "))

    if res.get("explains"):
        content.add_row(Text("【中文释义】", style="bold #50fa7b"))
        for exp in res["explains"]:
            content.add_row(Text(f"  • {exp}", style="#f8f8f2"))
        content.add_row(Text(" "))

    if res.get("definitions"):
        content.add_row(Text("【英英释义】", style="bold #8be9fd"))
        for d in res["definitions"][:3]:
            content.add_row(Text(f"  • {d}", style="dim #f8f8f2"))
        content.add_row(Text(" "))

    if not res.get("explains") and not res.get("definitions"):
        content.add_row(Text("  暂无释义。请检查拼写或稍后重试。", style="dim"))

    panel = Panel(
        content,
        title="[bold #00f0ff]✦ MORROW DICTIONARY ✦[/bold #00f0ff]",
        box=MODAL_BOX,
        border_style="#00f0ff",
        padding=(1, 2)
    )
    console.print()
    console.print(panel)

    # 播放查词发音
    if res.get("audio_url"):
        audio_engine.play_word(res["audio_url"], async_play=True)

    await _ask(console, "\n  [dim]按回车键返回[/dim]", default="", show_default=False)


# ============================================================================
# 提前复习与强化加词弹窗 (r)
# ============================================================================

async def show_advance_review_modal(console: Console, client) -> int:
    console.print()
    console.print(Panel(
        Align.center(Text(
            "✦ 提前复习与强化巩固 ✦\n"
            "即使今日单词已背完，也可从词本主动抽取下一批单词进行提前学习！",
            style="bold #8be9fd"
        )),
        box=CARD_BOX,
        border_style="#8be9fd"
    ))
    while True:
        ans = (await _ask(console, "  请输入要添加的复习单词数量 (推荐 5 / 10 / 20，直接回车取消)", default="", show_default=False)).strip()
        if not ans:
            return 0
        if len(ans) <= 10 and ans.isdecimal() and 0 < int(ans) <= 2**31 - 1:
            count = int(ans)
            break
        console.print(Text("  请输入有效的正整数。", style="bold #f1fa8c"))

    console.print(Text(f"  正在请求服务端追加 {count} 个单词 …", style="dim #6272a4"))
    added = await client.add_words(count)
    if added is None:
        console.print(Text(f"  加词失败。{client.last_error}", style="bold #f1fa8c"))
    elif added > 0:
        console.print(Text(f"  [成功] 已成功向今日队列追加 {added} 个复习单词！", style="bold #50fa7b"))
    else:
        console.print(Text("  当前没有可追加的复习单词。", style="bold #f1fa8c"))

    await asyncio.sleep(1.2)
    return added or 0


# ============================================================================
# 今日任务通关胜利屏
# ============================================================================

def show_completion_screen(console: Console, stats: Dict[str, Any], streak: int | None = None) -> None:
    console.clear()
    learned = stats.get("total", 0)
    known = stats.get("known", 0)
    fuzzy = stats.get("fuzzy", 0)
    forgot = stats.get("forgot", 0)
    mastered = stats.get("mastered", 0)

    judged = known + fuzzy + forgot
    accuracy = f"{known * 100 // judged}%" if judged else "暂无"

    t = Text()
    t.append("\n  🏆  CONGRATULATIONS!  🏆\n", style="bold #feca57")
    t.append("今日单词规划已全部斩获，学习大捷！\n\n", style="bold #50fa7b")

    t.append("  📊 学习数据总览：\n", style="bold #00f0ff")
    t.append(f"     • 复习/学习总轮次 : {learned}\n", style="#f8f8f2")
    t.append(f"     • 一次性直接认识  : {known}\n", style="#50fa7b")
    t.append(f"     • 遗忘与模糊强化  : {fuzzy + forgot}\n", style="#ff5555")
    t.append(f"     • 斩词/熟知永久剔除: {mastered}\n", style="#bd93f9")
    t.append(f"     • 本轮认识准确率  : {accuracy}\n\n", style="bold #f1fa8c")

    if streak is not None:
        t.append(f"  🔥 墨墨已连续打卡 {streak} 天\n", style="bold #feca57")

    panel = Panel(
        Align.center(t),
        title="[bold #50fa7b]✦ MORROW MISSION ACCOMPLISHED ✦[/bold #50fa7b]",
        box=DOUBLE_EDGE,
        border_style="#50fa7b",
        padding=(1, 3)
    )
    console.print(panel)
    console.print()
    console.print(Text("  [r] 提前复习(再来一批)   [/] 查词典   [q] 退出程序", style="bold #8be9fd"))


# ============================================================================
# 智能 Token 引导与配置向导
# ============================================================================

async def _open_in_browser(console: Console, url: str) -> None:
    try:
        opened = await asyncio.to_thread(webbrowser.open, url)
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        console.print(Text(f"  无法打开浏览器，请手动打开 {url}", style="bold #f1fa8c"))


async def _save_ws_token(console: Console, config, token: str) -> bool:
    console.print(Text("  正在验证 ws_token …", style="dim #6272a4"))
    client = MorrowClient(token)
    try:
        if not await client.connect() or not await client.initialize():
            console.print(Text(f"  验证失败。{client.last_error}", style="bold #ff5555"))
            return False
    finally:
        await client.close()
    if config.update(ws_token=token):
        console.print(Text("  ws_token 已验证并保存。", style="bold #50fa7b"))
        return True
    return False


async def _paste_ws_token(console: Console, config) -> bool:
    console.print(Text(
        "  手动配置时，在墨墨学习网页的 F12 → 网络 → WS 中复制 webstudy 请求的完整 URL。"
        "\n  也可以直接粘贴 ws_token。",
        style="dim #8be9fd",
    ))
    while True:
        value = (await _ask(console, "  粘贴学习连接地址或 ws_token（回车返回）", password=True)).strip()
        if not value:
            return False
        token = value
        if "://" in value or value.lower().startswith(("ws:", "wss:", "http:", "https:")):
            token = token_from_study_url(value)
            if not token:
                console.print(Text("  请粘贴墨墨 webstudy 的 WebSocket 请求地址。", style="bold #f1fa8c"))
                continue
        if await _save_ws_token(console, config, token):
            return True


async def show_token_wizard(console: Console, config, reason: str = "missing") -> bool:
    console.clear()
    guide = Text()
    if reason == "missing":
        guide.append("尚未配置背词凭证。\n\n", style="bold #f1fa8c")
    guide.append("1  在 Edge 或 Chrome 中登录墨墨，Morrow 自动验证并保存背词凭证。\n")
    guide.append("2  手动粘贴学习连接地址或 ws_token。\n")
    console.print(Panel(guide, title="MORROW · 背词登录", box=MODAL_BOX, border_style="#00f0ff"))
    choice = await _ask(console, "  选择登录方式，q 返回", choices=["1", "2", "q"], default="1")
    if choice == "q":
        return False
    if choice == "1":
        console.print(Text("  正在打开独立浏览器窗口。请在墨墨网页完成登录并进入学习页。", style="dim #8be9fd"))
        try:
            token = await sign_in_via_browser()
        except WebLoginError as exc:
            console.print(Text(f"  {exc}", style="bold #f1fa8c"))
        else:
            if await _save_ws_token(console, config, token):
                return True
    return await _paste_ws_token(console, config)


async def _update_rest_token(console: Console, config) -> bool:
    sequence = clipboard_sequence()
    await _open_in_browser(console, OPEN_API_TOKEN_URL)
    console.print(Text("  在墨墨官网登录并复制开放 API 凭证。", style="dim #8be9fd"))
    while True:
        copied = False
        if sequence is not None:
            action = await _ask(
                console, "  回车导入刚复制的凭证，m 手动粘贴，q 返回",
                choices=["i", "m", "q"], default="i", show_choices=False, show_default=False,
            )
            if action == "q":
                return False
            copied = action == "i"

        if copied:
            value = (await asyncio.to_thread(read_copied_text, sequence)).strip()
            if not value:
                console.print(Text("  未读取到新复制的文本。请在官网复制凭证，或选择手动粘贴。", style="bold #f1fa8c"))
                continue
        else:
            value = (await _ask(console, "  粘贴开放 API 凭证（回车返回）", password=True)).strip()
            if not value:
                return False

        token = value[7:].strip() if value.lower().startswith("bearer ") else value
        if token_from_study_url(token):
            console.print(Text("  这是背词凭证地址，可用设置 1 或 7 配置。", style="bold #f1fa8c"))
            continue
        if (copied and len(token) < 24) or not re.fullmatch(r"[A-Za-z0-9._~+/\-]+=*", token):
            console.print(Text("  凭证格式无效。请复制官网显示的 Token，或选择手动粘贴。", style="bold #f1fa8c"))
            continue

        console.print(Text("  正在用墨墨开放 API 验证凭证…", style="dim #6272a4"))
        client = MorrowClient(ws_token="", rest_token=token)
        if await asyncio.to_thread(client.fetch_study_progress):
            return config.update(rest_token=token)
        message = (
            "  凭证已失效或缺少学习数据权限。请重新领取后再试。"
            if client.rest_auth_failed else "  墨墨今日进度接口暂时无法验证凭证。请稍后再试。"
        )
        console.print(Text(message, style="bold #f1fa8c"))


async def show_settings_modal(console: Console, config) -> None:
    message = ""
    while True:
        console.clear()
        t = Table(show_header=False, box=CARD_BOX, border_style="#00f0ff", padding=(0, 2))
        t.add_column("选项", style="bold #00f0ff", width=6)
        t.add_column("设置项", style="bold #f8f8f2", width=26)
        t.add_column("当前状态/值", style="#50fa7b")

        t.add_row(Text("[1]"), "网页登录 / 更新背词凭证", "已设置" if config.ws_token else "未设置")
        t.add_row(Text("[2]"), "打开官网并更新开放 API 凭证", "已设置" if config.rest_token else "未设置")
        t.add_row(Text("[3]"), "打开墨墨学习网页", WEB_STUDY_URL)
        t.add_row(Text("[4]"), "发音偏好 (美音 / 英音)", config.accent)
        t.add_row(Text("[5]"), "单词自动发音", "开启" if config.auto_play_audio else "关闭")
        t.add_row(Text("[6]"), "例句自动朗读", "开启" if config.auto_play_example else "关闭")
        t.add_row(Text("[7]"), "手动更新背词凭证", "粘贴 WebSocket 地址或 ws_token")

        console.print(Panel(t, title="MORROW · 系统与凭证设置", box=CARD_BOX, border_style="#00f0ff"))
        if message:
            console.print(Text(message, style="bold #f1fa8c"))
            message = ""

        choice = (await _ask(console, "  输入选项 [1-7]（回车返回）", default="", show_default=False)).strip().lower()
        if not choice or choice in ("q", "quit", "exit"):
            return
        if choice == "7":
            if await _paste_ws_token(console, config):
                message = "背词凭证已更新。"
            continue
        if choice == "1":
            if await show_token_wizard(console, config, reason="manual"):
                message = "背词凭证已更新。"
            continue
        if choice == "3":
            await _open_in_browser(console, WEB_STUDY_URL)
            continue

        if choice == "2":
            if await _update_rest_token(console, config):
                message = "开放 API 凭证已验证并保存。"
            continue
        elif choice == "4":
            saved = config.update(accent="UK" if config.accent == "US" else "US")
        elif choice == "5":
            saved = config.update(auto_play_audio=not config.auto_play_audio)
        elif choice == "6":
            saved = config.update(auto_play_example=not config.auto_play_example)
        else:
            message = "请输入 1 到 7。"
            continue
        message = "设置已保存。" if saved else "无法保存设置。"
