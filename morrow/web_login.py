"""交互式墨墨网页登录，在独立窗口中完成 Morrow 的背词配置。"""

import asyncio
from urllib.parse import unquote, urlsplit

from .client import WS_URL

WEB_STUDY_URL = "https://www.maimemo.com/home/web_study"
OPEN_API_TOKEN_URL = "https://open.maimemo.com/open/api/v1/tokens/openapi"
_STUDY_LOCATIONS = {
    ("www.maimemo.com", "/home/web_study"),
    ("tc-apis.maimemo.com", "/webstudy"),
}
_SOCKET_ENDPOINT = urlsplit(WS_URL)


class WebLoginError(Exception):
    """浏览器登录流程未能完成。"""


def token_from_study_url(value: str) -> str:
    try:
        url = urlsplit(value)
    except ValueError:
        return ""
    endpoint = (url.scheme, url.netloc.lower(), url.path)
    if endpoint != (_SOCKET_ENDPOINT.scheme, _SOCKET_ENDPOINT.netloc, _SOCKET_ENDPOINT.path) or url.fragment:
        return ""

    # 保留查询参数原样。客户端连接时会统一解码并编码一次。
    tokens = []
    for parameter in url.query.split("&"):
        name, separator, value = parameter.partition("=")
        if name == "token" and separator:
            tokens.append(value)
    if len(tokens) == 1 and tokens[0] and not any(char.isspace() for char in unquote(tokens[0])):
        return tokens[0]
    return ""


def _is_study_page(url: str) -> bool:
    location = urlsplit(url)
    return location.scheme == "https" and (location.netloc, location.path.rstrip("/")) in _STUDY_LOCATIONS


async def _wait_for_study_connection(browser, timeout: float) -> str:
    token = asyncio.get_running_loop().create_future()
    context = await browser.new_context(no_viewport=True)

    def disconnected(*_):
        if not token.done():
            token.set_result("")

    def tab_closed(*_):
        if not context.pages:
            disconnected()

    def watch(page):
        def opened(socket):
            if not token.done() and _is_study_page(page.url):
                value = token_from_study_url(socket.url)
                if value:
                    token.set_result(value)

        page.on("websocket", opened)
        page.on("close", tab_closed)

    browser.on("disconnected", disconnected)
    context.on("close", disconnected)
    context.on("page", watch)
    page = await context.new_page()
    await page.goto(WEB_STUDY_URL, wait_until="commit", timeout=25_000)

    try:
        value = await asyncio.wait_for(token, timeout)
    except asyncio.TimeoutError:
        raise WebLoginError("等待墨墨网页登录超时。") from None
    if not value:
        raise WebLoginError("登录窗口已关闭。")
    return value


async def sign_in_via_browser(timeout: float = 300) -> str:
    try:
        from playwright.async_api import Error, async_playwright
    except ImportError:
        raise WebLoginError("网页登录组件未安装。可安装项目依赖，或手动粘贴。") from None

    try:
        async with async_playwright() as playwright:
            for channel in ("msedge", "chrome"):
                try:
                    browser = await playwright.chromium.launch(channel=channel, headless=False, timeout=12_000)
                except Error:
                    continue
                break
            else:
                raise WebLoginError("无法启动 Edge 或 Chrome。可使用手动粘贴。")

            try:
                return await _wait_for_study_connection(browser, timeout)
            finally:
                if browser.is_connected():
                    await browser.close()
    except (Error, OSError, NotImplementedError):
        raise WebLoginError("网页登录已中断，或墨墨网页暂时无法打开。") from None
