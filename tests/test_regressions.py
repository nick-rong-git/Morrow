import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

from rich.console import Console

from morrow import cli, clipboard
from morrow import web_login
from morrow.audio import AudioEngine
from morrow.client import (
    EV_SYSTEM_PING,
    EV_SYSTEM_READY,
    EV_WEBSTUDY_GET_WORD,
    EV_WEBSTUDY_INIT_STUDY,
    EV_WEBSTUDY_SUBMIT_RESPONSE,
    MorrowClient,
    _dec_varint,
    _decode_message,
    _enc_bool,
    _enc_bytes,
    _enc_int32,
    _enc_string,
    encode_envelope,
    parse_envelope,
)
from morrow.config import Config
from morrow.ui import views
from morrow.ui.cards import render_study_answer_card


def word_data(word_id, finished=0):
    word = _enc_string(1, word_id) + _enc_string(3, word_id)
    phrase = _enc_string(3, f"Example for {word_id}.")
    progress = _enc_int32(1, finished) + _enc_int32(2, 2)
    return _enc_bytes(1, word) + _enc_bytes(3, phrase) + _enc_bytes(22, progress)


class StudySocket:
    def __init__(self, on_request, *, ready=True):
        self.on_request = on_request
        self.incoming = asyncio.Queue()
        self.sent = []
        if ready:
            self.incoming.put_nowait(encode_envelope("server", EV_SYSTEM_READY))

    async def send(self, frame):
        request = parse_envelope(frame)
        self.sent.append(request)
        if request["reply_id"]:
            return
        answer = self.on_request(request)
        if isinstance(answer, Exception):
            self.incoming.put_nowait(answer)
        elif answer is not None:
            success, body = answer
            self.incoming.put_nowait(
                _enc_string(2, request["id"]) + _enc_int32(3, request["event"])
                + _enc_bytes(4, body) + _enc_bool(5, success)
            )

    async def recv(self):
        incoming = await self.incoming.get()
        if isinstance(incoming, Exception):
            raise incoming
        return incoming

    async def close(self):
        pass


class AsyncRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Config(Path(tmp.name) / "config.json")
        self.config.set("auto_play_audio", False)
        self.buffer = StringIO()
        self.console = Console(file=self.buffer, width=120)

    async def connect(self, socket):
        client = MorrowClient("test+token")
        self.addAsyncCleanup(client.close)
        with patch("morrow.client.websockets.connect", new_callable=AsyncMock, return_value=socket) as connect:
            self.assertTrue(await client.connect(), client.last_error)
            self.assertIn("token=test%2Btoken", connect.call_args.args[0])
            context = connect.call_args.kwargs["ssl"]
            self.assertTrue(context.check_hostname)
        return client

    async def test_judgment_undo_reloads_card_and_updates_summary(self):
        judgments = []

        def server(request):
            event = request["event"]
            if event == EV_WEBSTUDY_INIT_STUDY:
                return True, b""
            if event == EV_WEBSTUDY_GET_WORD:
                return True, word_data("first")
            self.assertEqual(event, EV_WEBSTUDY_SUBMIT_RESPONSE)
            fields = _decode_message(request["data"])
            self.assertEqual(fields[1], [b"first"])
            self.assertNotIn(3, fields)  # English → Chinese is the default protobuf enum.
            judgments.append(fields[2][0])
            if len(judgments) == 1:
                return False, b""
            if len(judgments) == 2:
                return True, _enc_bytes(1, word_data("second", finished=1))
            return True, b""

        socket = StudySocket(server)
        client = await self.connect(socket)
        self.assertTrue(await client.initialize())
        socket.incoming.put_nowait(encode_envelope("ping", EV_SYSTEM_PING))

        keys = AsyncMock(side_effect=[" ", "1", "2", "u", " ", "4", "0", "q"])
        with (
            patch.object(cli, "async_read_key", keys),
            patch.object(cli, "audio_engine") as audio,
        ):
            await cli.run_learning_session(client, self.config, self.console)
        self.assertEqual(judgments, [1, 2, 4])
        self.assertIn("服务端拒绝 WEBSTUDY_SUBMIT_RESPONSE", self.buffer.getvalue())
        self.assertIn("复习/学习总轮次 : 1", self.buffer.getvalue())
        self.assertIn("斩词/熟知永久剔除: 1", self.buffer.getvalue())
        audio.speak_sentence.assert_called_once_with("Example for first.", accent="US")
        get_requests = [item["data"] for item in socket.sent if item["event"] == EV_WEBSTUDY_GET_WORD]
        self.assertEqual(get_requests, [b"", _enc_bool(1, True)])
        self.assertTrue(any(item["reply_id"] == "ping" for item in socket.sent))

    async def test_no_completion_on_rejected_or_malformed_get_word(self):
        for reply in [(False, b""), (True, b"\x0a\x03x")]:
            with self.subTest(reply=reply):
                client = await self.connect(StudySocket(lambda request: reply))
                with self.assertRaises(cli.StudyError):
                    await cli.run_learning_session(client, self.config, self.console)
        self.assertNotIn("CONGRATULATIONS", self.buffer.getvalue())

    async def test_disconnected_submission_is_neither_retried_nor_counted(self):
        def server(request):
            if request["event"] == EV_WEBSTUDY_GET_WORD:
                return True, word_data("first")
            return ConnectionError("test closure")

        socket = StudySocket(server)
        client = await self.connect(socket)
        with (
            patch.object(cli, "async_read_key", AsyncMock(side_effect=[" ", "1"])),
            patch.object(cli, "audio_engine"),
            self.assertRaisesRegex(cli.StudyError, "判答结果未确认"),
        ):
            await cli.run_learning_session(client, self.config, self.console)
        self.assertEqual(
            [item["event"] for item in socket.sent],
            [EV_WEBSTUDY_GET_WORD, EV_WEBSTUDY_SUBMIT_RESPONSE],
        )
        self.assertFalse(client._pending)

    async def test_close_before_ready_unblocks_connection(self):
        socket = StudySocket(lambda request: None, ready=False)
        socket.incoming.put_nowait(ConnectionError("test closure"))
        client = MorrowClient("test")
        with patch("morrow.client.websockets.connect", AsyncMock(return_value=socket)):
            self.assertFalse(await asyncio.wait_for(client.connect(), timeout=1))
        self.assertIn("ConnectionError", client.last_error)
        self.assertIsNone(client.ws)

    async def test_unconfirmed_undo_exits_current_card_for_resync(self):
        socket = StudySocket(
            lambda request: (True, b"\x0a\x03x" if request["data"] else word_data("first"))
        )
        client = await self.connect(socket)
        with (
            patch.object(cli, "async_read_key", AsyncMock(return_value="u")),
            patch.object(cli, "audio_engine"),
            self.assertRaisesRegex(cli.StudyError, "撤回结果未确认"),
        ):
            await cli.run_learning_session(client, self.config, self.console)
        self.assertEqual([item["data"] for item in socket.sent], [b"", _enc_bool(1, True)])

    async def test_request_cancellation_removes_pending_future(self):
        socket = StudySocket(lambda request: None)
        client = await self.connect(socket)
        task = asyncio.create_task(client.get_word())
        await asyncio.sleep(0)
        self.assertEqual(len(client._pending), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(client._pending)

    async def test_review_batches_keep_statistics_and_do_not_recurse(self):
        client = Mock(spec=MorrowClient)
        client.progress = {}
        client.get_word = AsyncMock(side_effect=[{}, {"id": "a"}, {"id": "b"}])
        client.submit_response = AsyncMock(return_value=True)
        client.last_next_word = {}
        with (
            patch.object(cli, "async_read_key", AsyncMock(side_effect=["r", " ", "1", "r", " ", "2", "q"])),
            patch.object(cli, "show_advance_review_modal", AsyncMock(return_value=1)),
            patch.object(cli, "show_completion_screen") as completion,
            patch.object(cli, "audio_engine"),
        ):
            snapshots = []
            completion.side_effect = lambda console, stats: snapshots.append(dict(stats))
            await cli.run_learning_session(client, self.config, self.console)
        self.assertEqual([stats["total"] for stats in snapshots], [0, 1, 2])
        self.assertEqual(client.get_word.await_count, 3)

    async def test_settings_and_bad_token_validation(self):
        with patch.object(views, "_ask", AsyncMock(side_effect=["4", ""])):
            await views.show_settings_modal(self.console, self.config)
        self.assertEqual(Config(self.config.config_path).accent, "UK")
        self.assertIn("[1]", self.buffer.getvalue())

        client = Mock(connect=AsyncMock(return_value=False), close=AsyncMock(), last_error="offline")
        ask = AsyncMock(side_effect=["2", "invalid", ""])
        with patch.object(views, "_ask", ask), patch.object(views, "MorrowClient", return_value=client):
            self.assertFalse(await views.show_token_wizard(self.console, self.config))
        self.assertTrue(ask.call_args_list[1].kwargs["password"])
        self.assertFalse(Config(self.config.config_path).ws_token)
        client.close.assert_awaited_once()

    async def test_web_sign_in_validates_and_saves_without_a_paste_prompt(self):
        ask = AsyncMock(return_value="1")
        client = Mock(connect=AsyncMock(return_value=True), initialize=AsyncMock(return_value=True), close=AsyncMock())
        browser_login = AsyncMock(return_value="browser-token")
        with (
            patch.object(views, "_ask", ask),
            patch.object(views, "sign_in_via_browser", browser_login),
            patch.object(views, "MorrowClient", return_value=client) as make_client,
        ):
            self.assertTrue(await views.show_token_wizard(self.console, self.config))
        ask.assert_awaited_once()
        make_client.assert_called_once_with("browser-token")
        self.assertEqual(Config(self.config.config_path).ws_token, "browser-token")
        self.assertNotIn("browser-token", self.buffer.getvalue())

    async def test_failed_browser_login_accepts_a_full_study_url(self):
        pasted_url = "wss://tc-apis.maimemo.com/study/ws/webstudy?token=manual%2Btoken"
        ask = AsyncMock(side_effect=["1", pasted_url])
        with (
            patch.object(views, "_ask", ask),
            patch.object(views, "sign_in_via_browser", AsyncMock(side_effect=web_login.WebLoginError("test closure"))),
            patch.object(views, "_save_ws_token", AsyncMock(return_value=True)) as save,
        ):
            self.assertTrue(await views.show_token_wizard(self.console, self.config))
        save.assert_awaited_once_with(self.console, self.config, "manual%2Btoken")
        self.assertTrue(ask.call_args.kwargs["password"])

    async def test_rest_setup_opens_official_page_and_imports_copied_token(self):
        token = "synthetic-rest-credential-001"
        client = Mock(fetch_study_progress=Mock(return_value={"finished": 0, "total": 0}))
        with (
            patch.object(views, "_ask", AsyncMock(side_effect=["2", "i", "q"])),
            patch.object(views, "clipboard_sequence", return_value=9),
            patch.object(views, "read_copied_text", return_value=f"Bearer {token}") as read,
            patch.object(views, "_open_in_browser", AsyncMock()) as open_page,
            patch.object(views, "MorrowClient", return_value=client) as make_client,
        ):
            await views.show_settings_modal(self.console, self.config)
        open_page.assert_awaited_once_with(self.console, web_login.OPEN_API_TOKEN_URL)
        read.assert_called_once_with(9)
        make_client.assert_called_once_with(ws_token="", rest_token=token)
        self.assertEqual(Config(self.config.config_path).rest_token, token)
        self.assertNotIn(token, self.buffer.getvalue())

    async def test_failed_rest_validation_keeps_saved_token(self):
        self.config.update(rest_token="old-token")
        client = Mock(fetch_study_progress=Mock(return_value={}), rest_auth_failed=True)
        with (
            patch.object(views, "clipboard_sequence", return_value=None),
            patch.object(views, "_ask", AsyncMock(side_effect=["rejected-token", ""])),
            patch.object(views, "_open_in_browser", AsyncMock()),
            patch.object(views, "MorrowClient", return_value=client),
        ):
            self.assertFalse(await views._update_rest_token(self.console, self.config))
        self.assertEqual(Config(self.config.config_path).rest_token, "old-token")
        self.assertIn("凭证已失效", self.buffer.getvalue())

    async def test_browser_observes_only_the_expected_study_page_and_socket(self):
        events = {}
        page = Mock(on=Mock(side_effect=events.__setitem__), url="https://other.invalid")
        context = Mock(pages=[page], on=Mock(side_effect=events.__setitem__))
        browser = Mock(new_context=AsyncMock(return_value=context))
        target = "wss://tc-apis.maimemo.com/study/ws/webstudy?token="

        async def new_page():
            events["page"](page)
            return page

        async def goto(*args, **kwargs):
            events["websocket"](Mock(url=target + "wrong-origin"))
            page.url = web_login.WEB_STUDY_URL
            events["websocket"](Mock(url="wss://other.invalid/study/ws/webstudy?token=wrong-host"))
            events["websocket"](Mock(url=target + "expected-token"))

        context.new_page = AsyncMock(side_effect=new_page)
        page.goto = AsyncMock(side_effect=goto)
        self.assertEqual(await web_login._wait_for_study_connection(browser, 1), "expected-token")
        browser.new_context.assert_awaited_once_with(no_viewport=True)
        page.goto.assert_awaited_once_with(web_login.WEB_STUDY_URL, wait_until="commit", timeout=25_000)

    async def test_advance_review_reprompts_for_invalid_counts(self):
        client = Mock(add_words=AsyncMock(return_value=5))
        with (
            patch.object(views, "_ask", AsyncMock(side_effect=["²", "2147483648", "0", "５"])),
            patch.object(views.asyncio, "sleep", AsyncMock()),
        ):
            self.assertEqual(await views.show_advance_review_modal(self.console, client), 5)
        client.add_words.assert_awaited_once_with(5)


class CardRegressions(unittest.TestCase):
    def test_each_part_of_speech_gets_its_own_row(self):
        definitions = "n. 柜台；计数器；筹码\r\nv. 反驳；反击\nadj.相反的\ninterj. 哎呀\n1. 保留编号"
        for fields in ({"interpretations": [definitions]}, {"interpretation": definitions}):
            with self.subTest(fields=tuple(fields)):
                output = StringIO()
                render_study_answer_card(Console(file=output, width=100), {"spelling": "counter", **fields}, 0, 1)
                card = output.getvalue()
                self.assertRegex(card, r"\[n\.\] +柜台")
                self.assertRegex(card, r"\[v\.\] +反驳")
                self.assertRegex(card, r"\[adj\.\] +相反的")
                self.assertRegex(card, r"\[interj\.\] +哎呀")
                self.assertRegex(card, r"• +1\. 保留编号")


class StorageRegressions(unittest.TestCase):
    def test_reads_clipboard_text_only_after_a_new_copy(self):
        api = Mock(
            CF_UNICODETEXT=13,
            GetClipboardSequenceNumber=Mock(return_value=9),
            IsClipboardFormatAvailable=Mock(return_value=True),
            GetClipboardData=Mock(return_value="synthetic-token"),
        )
        with patch.object(clipboard, "win32clipboard", api):
            self.assertEqual(clipboard.read_copied_text(9), "")
            api.GetClipboardData.assert_not_called()
            api.GetClipboardSequenceNumber.return_value = 10
            self.assertEqual(clipboard.read_copied_text(9), "synthetic-token")
        api.GetClipboardData.assert_called_once_with(13)
        self.assertEqual(api.CloseClipboard.call_count, 2)

    def test_progress_distinguishes_auth_failure_from_unavailability(self):
        client = MorrowClient(ws_token="", rest_token="synthetic-token")
        with patch("morrow.client.urllib.request.urlopen", side_effect=HTTPError("", 401, "", None, None)):
            self.assertEqual(client.fetch_study_progress(), {})
            self.assertTrue(client.rest_auth_failed)
        with patch("morrow.client.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(client.fetch_study_progress(), {})
            self.assertFalse(client.rest_auth_failed)

    def test_study_url_rejects_ambiguous_or_non_official_credentials(self):
        endpoint = "wss://tc-apis.maimemo.com/study/ws/webstudy"
        self.assertEqual(web_login.token_from_study_url(endpoint + "?token=valid%2Btoken"), "valid%2Btoken")
        for url in (
            endpoint + "?token=one&token=two",
            endpoint + "?token=with%0Aline",
            "https://tc-apis.maimemo.com/study/ws/webstudy?token=wrong-scheme",
            "wss://tc-apis.maimemo.com@other.invalid/study/ws/webstudy?token=wrong-host",
        ):
            with self.subTest(url=url):
                self.assertEqual(web_login.token_from_study_url(url), "")

    def test_config_atomic_update_and_invalid_defaults(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            before = {"ws_token": None, "auto_play_audio": "false", "accent": "other", "future": "preserved"}
            path.write_text(json.dumps(before), encoding="utf-8-sig")
            config = Config(path)
            self.assertEqual(config.ws_token, "")
            self.assertTrue(config.auto_play_audio)
            self.assertEqual(config.accent, "US")
            with patch("morrow.config.os.replace", side_effect=PermissionError("test lock")):
                self.assertFalse(config.update(accent="UK"))
            self.assertEqual(config.accent, "US")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8-sig")), before)
            self.assertEqual(list(path.parent.iterdir()), [path])
            self.assertTrue(config.update(accent="UK"))
            self.assertEqual(Config(path).get("future"), "preserved")

    def test_truncated_or_overflowing_varints_cannot_become_progress(self):
        for data in (b"\x80", b"\xff" * 10 + b"\x00"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                _dec_varint(data, 0)

    def test_audio_rejects_invalid_response_and_deduplicates_downloads(self):
        with TemporaryDirectory() as directory:
            audio = AudioEngine(directory)
            url = "https://example.invalid/test.mp3"
            calls = []

            def fetch(actual_url, output_path):
                calls.append(actual_url)
                data = b"<html>" if len(calls) == 1 else b"ID3" + b"x" * 400
                Path(output_path).write_bytes(data)
                return True

            with patch.object(audio, "_download", side_effect=fetch):
                self.assertIsNone(audio.download_url_if_needed(url))
                self.assertEqual(list(Path(directory).iterdir()), [])
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(audio.download_url_if_needed, [url] * 6))
            self.assertEqual(len(calls), 2)
            self.assertIsNotNone(results[0])
            self.assertEqual(results, [results[0]] * 6)
            self.assertEqual(list(Path(directory).iterdir()), [Path(results[0])])

    def test_stop_interrupts_playback(self):
        audio = AudioEngine()
        started = threading.Event()
        cancelled = audio._cancelled

        def send(command, response, *_):
            if command.startswith("play "):
                started.set()
            elif command.startswith("status "):
                response.value = "playing"
            return 0

        audio._winmm = Mock(mciSendStringW=Mock(side_effect=send))
        with ThreadPoolExecutor(max_workers=1) as pool:
            playback = pool.submit(audio._play_file_sync, "test.mp3", cancelled)
            audio_started = started.wait(timeout=1)
            audio.stop()
            self.assertTrue(audio_started)
            self.assertTrue(playback.result(timeout=1))
        self.assertTrue(audio._winmm.mciSendStringW.call_args.args[0].startswith("close "))


if __name__ == "__main__":
    unittest.main()
