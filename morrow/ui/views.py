"""
Morrow 模态弹窗与特色视图 (Views)
包含即时查词典、老板键伪装、提前复习加词、今日通关大捷等交互界面。
"""

import time
from typing import Dict, Any
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.align import Align
from rich.prompt import Prompt

from .theme import (
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS,
    COLOR_WARNING, COLOR_DANGER, COLOR_MUTED, COLOR_TEXT_MAIN,
    CARD_BOX, MODAL_BOX
)
from ..dict import lookup_dictionary
from ..audio import audio_engine

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

def show_dictionary_modal(console: Console) -> None:
    console.print()
    word_input = Prompt.ask("  [bold #00f0ff]🔍 请输入要查询的单词[/bold #00f0ff] (直接按回车取消)").strip()
    if not word_input:
        return

    console.print(Text(f"  正在联网检索 \"{word_input}\" ...", style="dim #6272a4"))
    res = lookup_dictionary(word_input)

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

    Prompt.ask("\n  [dim]按回车键返回单词背诵[/dim]")


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
    ans = Prompt.ask("  请输入欲添加的复习单词数量 (推荐 5 / 10 / 20，直接回车取消)", default="").strip()
    if not ans or not ans.isdigit() or int(ans) <= 0:
        return 0

    count = int(ans)
    console.print(Text(f"  正在请求服务端舀入 {count} 个单词 ...", style="dim #6272a4"))
    added = await client.add_words(count)
    if added is not None and added > 0:
        console.print(Text(f"  [成功] 已成功向今日队列追加 {added} 个复习单词！", style="bold #50fa7b"))
    else:
        console.print(Text("  [提示] 未能追加新词（可能当前词本已学完或网络超时）", style="bold #f1fa8c"))

    time.sleep(1.2)
    return added or 0


# ============================================================================
# 今日任务通关胜利屏
# ============================================================================

def show_completion_screen(console: Console, stats: Dict[str, Any], streak: int = 1) -> None:
    console.clear()
    learned = stats.get("total", 0)
    known = stats.get("known", 0)
    fuzzy = stats.get("fuzzy", 0)
    forgot = stats.get("forgot", 0)
    mastered = stats.get("mastered", 0)

    accuracy = int(known * 100 / max(1, (known + fuzzy + forgot)))

    t = Text()
    t.append("\n  🏆  CONGRATULATIONS!  🏆\n", style="bold #feca57")
    t.append("今日单词规划已全部斩获，学习大捷！\n\n", style="bold #50fa7b")

    t.append("  📊 学习数据总览：\n", style="bold #00f0ff")
    t.append(f"     • 复习/学习总轮次 : {learned}\n", style="#f8f8f2")
    t.append(f"     • 一次性直接认识  : {known}\n", style="#50fa7b")
    t.append(f"     • 遗忘与模糊强化  : {fuzzy + forgot}\n", style="#ff5555")
    t.append(f"     • 斩词/熟知永久剔除: {mastered}\n", style="#bd93f9")
    t.append(f"     • 本轮认识准确率  : {accuracy}%\n\n", style="bold #f1fa8c")

    t.append("  🔥 连续打卡荣耀：\n", style="bold #ff9f43")
    t.append(f"     墨墨连续打卡已达成 {streak} 天！明天的自己会感谢今天的坚持！\n\n", style="bold #feca57")

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
