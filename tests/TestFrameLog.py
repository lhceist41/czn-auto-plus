"""Check the debug-run tools: one saved frame per log line a second, and the remote control's seat in the real mode lists."""

import errno
import http.client
import http.server
import importlib.util
import json
import logging
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

import utils_chaos  # noqa: E402
import utils_sortie  # noqa: E402
import utils_story  # noqa: E402

from ok import TaskExecutor, og  # noqa: E402
from ok.device.interaction_methods.foreground_post_message import ForegroundPostMessageInteraction  # noqa: E402
from ok.device.interaction_methods.genshin import GenshinInteraction  # noqa: E402
from ok.device.interaction_methods.post_message import PostMessageInteraction  # noqa: E402
from ok.task.task import ExecutorOperation  # noqa: E402

from src.en import frame_log, remote  # noqa: E402
from src.en.handlers import standing_in  # noqa: E402

# `scripts/` is no package, so the MCP bridge is loaded from its file.
_spec = importlib.util.spec_from_file_location("czn_mcp", REPO_ROOT / "scripts" / "czn_mcp.py")
czn_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(czn_mcp)

# 00:48:52,268 local time on the day of a live run, as the log line would print it.
LOGGED_AT = time.mktime((2026, 10, 25, 0, 48, 52, 0, 0, -1)) + 0.268


def record(level, at, message="StoryMode:nothing left worth playing"):
    """Build a log record stamped at a fixed time.

    Args:
        level: The record's logging level.
        at: The epoch time the record says it was logged at.
        message: The logged text.

    Returns:
        A `logging.LogRecord`.
    """
    line = logging.LogRecord("ok", level, __file__, 0, message, None, None)
    line.created, line.msecs = at, round((at % 1) * 1000)
    return line


class TestFrameLog(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.executor = types.SimpleNamespace(current_task=object())
        # A fresh frame per read, the way ok-script hands over each capture.
        self.enterContext(standing_in(frame_log, latest=lambda: np.full((8, 8, 3), 200, np.uint8)))
        self.handler = frame_log.FrameLog(lambda: self.executor, os.path.join(self.folder.name, "session"))
        self.log = logging.Logger("tests.frame_log", logging.DEBUG)
        self.log.addHandler(self.handler)

    def test_a_line_saves_the_frame_it_was_logged_on(self):
        self.log.handle(record(logging.INFO, LOGGED_AT))
        path, frame = self.handler.pending.get_nowait()
        self.assertEqual("00-48-52-268_StoryMode-nothing-left-worth-playing.jpg", os.path.basename(path))
        self.handler.save(path, frame)
        self.assertEqual((8, 8, 3), cv2.imread(path).shape)

    def test_only_one_info_line_a_second_saves_while_a_task_runs(self):
        # Every one of these is a frame saved for nothing, and a battle logs on every frame.
        self.log.handle(record(logging.INFO, LOGGED_AT))
        self.log.handle(record(logging.INFO, LOGGED_AT + 0.2))
        self.log.handle(record(logging.DEBUG, LOGGED_AT + 2))
        self.executor.current_task = None
        self.log.handle(record(logging.INFO, LOGGED_AT + 4))
        self.assertEqual(1, self.handler.pending.qsize())

    def test_a_full_session_drops_its_oldest_frames(self):
        paths = [os.path.join(self.folder.name, "session", f"{index}.jpg") for index in range(3)]
        frame = np.full((8, 8, 3), 200, np.uint8)
        self.handler.save(paths[0], frame)
        with standing_in(frame_log, SESSION_CAP=os.path.getsize(paths[0]) * 2):
            for path in paths[1:]:
                self.handler.save(path, frame)
        self.assertEqual([False, True, True], [os.path.exists(path) for path in paths])

    def test_only_the_newest_sessions_are_kept(self):
        for name in ("2026-10-22_10-00-00", "2026-10-23_10-00-00", "2026-10-24_10-00-00", "2026-10-25_10-00-00"):
            os.makedirs(os.path.join(self.folder.name, name))
        frame_log.prune(self.folder.name, frame_log.SESSIONS_KEPT - 1)
        self.assertEqual(["2026-10-24_10-00-00", "2026-10-25_10-00-00"], sorted(os.listdir(self.folder.name)))


def swiping_task(interaction):
    """Build a 1920x1080 task whose swipe runs ok-script's own code down to an interaction method's swipe.

    Args:
        interaction: The interaction class whose `swipe` takes the drag, such as `PostMessageInteraction`.

    Returns:
        The task, and the list each mouse event lands in as `(event, x, y)`.
    """
    events = []
    # Built without a window, so only the mouse events below stand in for the real ones.
    method = interaction.__new__(interaction)
    method.move = lambda x, y, down_btn=0: events.append(("move", x, y))
    method.mouse_down = lambda x=-1, y=-1, name=None, key="left": events.append(("down", x, y))
    method.mouse_up = lambda *args, **kwargs: events.append(("up", None, None))
    executor = types.SimpleNamespace(nullable_frame=lambda: None, reset_scene=lambda: None, interaction=method)
    task = types.SimpleNamespace(width=1920, height=1080, executor=executor, sleep=lambda seconds: None)
    task.swipe = types.MethodType(ExecutorOperation.swipe, task)
    task.swipe_relative = types.MethodType(ExecutorOperation.swipe_relative, task)
    return task, events


def drag_on(task, *points):
    """Send a drag from another thread, as the server would, and run it here, as the bot's page loop would.

    Args:
        task: What the bot's thread hands the queued action.
        *points: The drag's `x1, y1, x2, y2`.

    Returns:
        The drag's own error, or None.
    """
    errors = []

    def send():
        try:
            remote.drag(*points)
        except Exception as error:
            errors.append(error)

    with standing_in(remote, _executor=lambda: task.executor):
        sender = threading.Thread(target=send)
        sender.start()
        run_when_queued(task, sender)
    return errors[0] if errors else None


def run_when_queued(task, sender):
    """Run the page loop here until it has run the sender's action, the sender has given up, or five seconds pass.

    Args:
        task: What the bot's thread hands the queued action.
        sender: The thread that queued it.
    """
    deadline = time.monotonic() + 5
    while not remote.handle_remote(task) and sender.is_alive() and time.monotonic() < deadline:
        time.sleep(0.001)
    sender.join(5)


class PageLoop:
    """Run `handle_remote` and then `handlers` on a thread of their own, frame after frame, as ok-script's page loop does:
    the first handler to return True ends the frame."""

    def __init__(self, test, *handlers, start=True):
        """Start the loop, or with `start=False` leave it waiting until `go` is set."""
        self.handlers = (remote.handle_remote,) + handlers
        self.go = threading.Event()
        self.done = threading.Event()
        self.task = types.SimpleNamespace()
        if start:
            self.go.set()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        test.addCleanup(self.close)

    def run(self):
        self.go.wait()
        while not self.done.is_set():
            for handler in self.handlers:
                if handler(self.task):
                    break
            time.sleep(0.001)

    def close(self):
        self.go.set()
        self.done.set()
        self.thread.join(5)


def attempt(call, *args):
    """Call something and return its result, or the error it raised."""
    try:
        return call(*args)
    except Exception as error:
        return error


def idle_executor(current_task=None, tasks=(), current_job=None, job_queue=()):
    """An executor holding `tasks`, running `current_task` and `current_job`, with `job_queue` waiting."""
    return types.SimpleNamespace(current_task=current_task, current_job=current_job, _job_queue=list(job_queue),
                                 get_all_tasks=lambda: list(tasks))


class ChaosMode:
    """A mode switched on that the executor has not picked up yet."""

    enabled = True


class LateStart:
    """A start controller that, like ok-script's, only marks itself starting and switches the mode on later."""

    def __init__(self):
        self.starting = False
        self.pending = None

    def start(self, task):
        self.starting = True
        self.pending = task

    def finish(self):
        """Switch the mode on, then stop starting, in the order ok-script's `do_start` does."""
        self.pending.enabled = True
        self.starting = False


def serve_remote(test):
    """Serve the remote control on a free loopback port for one test, and return the port."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), remote.Remote)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return server.server_port


def serve_error(test, status, body=b"", content_type="text/plain; charset=utf-8", length=None, reason=None):
    """Answer every POST with one HTTP error, standing in for a port that refuses, and return its port.

    Args:
        test: The test the server lives for.
        status: The status to answer with.
        body: The bytes sent after the headers.
        content_type: The Content-Type to send.
        length: The Content-Length to send instead of the body's own size. A longer one keeps the reply open, as a
            stalled port would.
        reason: The reason phrase to send instead of the status's own, such as an empty one.
    """
    release = threading.Event()

    class Refuse(http.server.BaseHTTPRequestHandler):

        def do_POST(self):
            # Read first, so no request bytes are left to make Windows reset the connection under the reply.
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(status, reason)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body) if length is None else length))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            if length is not None:
                release.wait(10)

        def log_message(self, *args):
            """Keep each request out of the test output."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    test.addCleanup(release.set)
    return server.server_port


def serve_raw(test, answer):
    """Read each request on a free loopback port whole, then let `answer` reply on the bare socket, and return the port.

    Args:
        test: The test the server lives for.
        answer: Called with the connected socket and an event set at cleanup; whatever it sends is the reply, and the
            socket closes when it returns.
    """
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(0.1)
    done = threading.Event()

    def serve():
        while not done.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(5)
                data = b""
                # An empty read means the caller closed early: stop instead of spinning on it.
                while b"\r\n\r\n" not in data and (chunk := connection.recv(65536)):
                    data += chunk
                head, ended, body = data.partition(b"\r\n\r\n")
                length = next((int(line.split(b":")[1]) for line in head.split(b"\r\n")
                               if line.lower().startswith(b"content-length:")), 0)
                while len(body) < length and (chunk := connection.recv(65536)):
                    body += chunk
                if ended and len(body) >= length:
                    answer(connection, done)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    test.addCleanup(listener.close)
    test.addCleanup(thread.join, 5)
    test.addCleanup(done.set)
    return listener.getsockname()[1]


def reply_head(length):
    """Return the head of a 200 JSON reply promising `length` body bytes."""
    return f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n".encode("ascii")


def raw_post(port, headers, host=True, command="status", body=b"{}", length=None, late=False):
    """POST `body` to a command with exactly `headers`, as a browser or another local program might.

    Args:
        port: The remote control's port.
        headers: Every header to send besides Content-Length, and Host unless `headers` names one.
        host: False to send no Host header at all.
        command: The command the path names.
        body: The bytes sent after the headers.
        length: The Content-Length to send instead of the body's own size.
        late: True to send the body only after the port has read the headers, and to read the reply a moment after
            that, as a slow caller's packets can trail.

    Returns:
        The reply's status, Content-Type and body text.
    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.putrequest("POST", f"/{command}", skip_host=not host or "Host" in headers)
        for name, value in {**headers, "Content-Length": str(len(body) if length is None else length)}.items():
            connection.putheader(name, value)
        if late:
            connection.endheaders()
            time.sleep(0.05)
            connection.send(body)
            time.sleep(0.3)
        else:
            connection.endheaders(body)
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type"), response.read().decode("utf-8")
    finally:
        connection.close()


def trickle_post(port, headers, length, every):
    """POST to `status` and send the body one byte at a time until the port answers, as a slow or hostile caller might.

    Args:
        port: The remote control's port.
        headers: Every header to send besides Host and Content-Length.
        length: The Content-Length to send.
        every: Seconds between two body bytes.

    Returns:
        The reply's status line, empty when the connection was reset first, and the seconds until the port answered.
    """
    connection = socket.create_connection(("127.0.0.1", port), timeout=15)
    answered = threading.Event()

    def trickle():
        try:
            for _ in range(length):
                if answered.wait(every):
                    return
                connection.sendall(b" ")
        except OSError:
            pass

    head = {"Host": f"127.0.0.1:{port}", **headers, "Content-Length": str(length)}
    sender = threading.Thread(target=trickle, daemon=True)
    started = time.monotonic()
    try:
        lines = "".join(f"{name}: {value}\r\n" for name, value in head.items())
        connection.sendall(f"POST /status HTTP/1.1\r\n{lines}\r\n".encode("ascii"))
        sender.start()
        try:
            first = connection.recv(256)
        except ConnectionError:
            first = b""
        seconds = time.monotonic() - started
        answered.set()
        sender.join()
        return first.split(b"\r\n")[0].decode("ascii"), seconds
    finally:
        connection.close()


def wait_for(condition, seconds=2):
    """Poll until `condition()` holds or `seconds` pass, and return its last answer."""
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


class TestRemote(unittest.TestCase):

    def tearDown(self):
        remote._held.clear()
        remote._quit_reply = None
        while not remote._actions.empty():
            remote._actions.get_nowait()

    def test_the_remote_comes_first_in_every_mode(self):
        """Anywhere lower, a held bot still runs whatever comes before it, and a mode it misses can never be clicked in."""
        remote.install()
        remote.install()
        for module in (utils_chaos, utils_sortie, utils_story):
            with self.subTest(module.__name__):
                names = [handler.__name__ for handler in module.PAGE_HANDLERS]
                self.assertEqual((remote.handle_remote.__name__, 1), (names[0], names.count(names[0])))

    def test_an_abandoned_click_never_lands(self):
        """A click whose caller gave up would otherwise land on whatever screen the bot reaches next."""
        clicks = []
        with standing_in(remote, ACTION_TIMEOUT=0.01), self.assertRaisesRegex(TimeoutError, "nothing was sent"):
            remote.on_bot_thread(clicks.append)
        self.assertFalse(remote.handle_remote("task"))
        self.assertEqual([], clicks)

    def test_a_held_bot_gives_up_every_frame(self):
        """Otherwise the bot acts on a screen stepped through by hand, and the stuck stop counts the time held."""
        task = types.SimpleNamespace()
        self.assertFalse(remote.handle_remote(task))
        self.assertNotIn(remote.HELD, vars(task))
        remote._held.set()
        self.assertTrue(remote.handle_remote(task))
        self.assertIs(True, getattr(task, remote.HELD))

    def test_a_hold_replies_only_after_the_page_loop_comes_round(self):
        """Told the hold took while the loop has not come round, a caller clicks while the bot can still act."""
        executor = idle_executor(current_task=ChaosMode())
        loop = PageLoop(self, start=False)
        outcome = []
        with standing_in(remote, _executor=lambda: executor):
            caller = threading.Thread(target=lambda: outcome.append(attempt(remote.hold, True)))
            caller.start()
            caller.join(0.3)
            self.assertTrue(caller.is_alive())
            self.assertTrue(remote._held.is_set())
            loop.go.set()
            caller.join(5)
        self.assertEqual(1, len(outcome))
        self.assertIs(True, outcome[0]["taken"])
        self.assertNotIn("reason", outcome[0])
        self.assertIs(True, outcome[0]["held"])
        self.assertTrue(remote._actions.empty())

    def test_a_click_decided_before_the_hold_lands_before_the_reply(self):
        """A click landing after the reply goes onto the screen the caller is already stepping through by hand."""
        executor = idle_executor(current_task=ChaosMode())
        started = threading.Event()
        clicks = []
        calls = []

        def deciding(task):
            calls.append(1)
            if clicks or started.is_set():
                return False
            started.set()
            # The humanized pace delay a real handler waits before its click.
            time.sleep(0.3)
            clicks.append("decided")
            return True

        PageLoop(self, deciding)
        self.assertTrue(started.wait(5))
        with standing_in(remote, _executor=lambda: executor):
            reply = remote.hold(True)
        self.assertEqual(["decided"], clicks)
        self.assertIs(True, reply["taken"])
        frozen = len(calls)
        time.sleep(0.1)
        # Held, every frame ends at the remote handler, so nothing after it runs again.
        self.assertEqual(frozen, len(calls))

    def test_a_hold_the_loop_never_takes_says_so_and_stays_held(self):
        """A caller told the hold took would act while a battle may still play the card it had picked."""
        executor = idle_executor(current_task=ChaosMode())
        with standing_in(remote, _executor=lambda: executor, ACTION_TIMEOUT=0.05):
            started = time.monotonic()
            reply = remote.hold(True)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIs(False, reply["taken"])
        self.assertIn("did not come round", reply["reason"])
        self.assertIn("screenshot", reply["reason"])
        self.assertIs(True, reply["held"])
        self.assertTrue(remote._held.is_set())
        # The given-up wait never runs when the loop comes round late, and the bot is still held then.
        self.assertTrue(remote.handle_remote(types.SimpleNamespace()))
        self.assertTrue(remote._actions.empty())

    def test_a_hold_with_nothing_running_replies_at_once(self):
        """Holding first and then starting the mode is the usual way in, and it would cost 15 s and a false `taken`."""
        executor = idle_executor()
        with standing_in(remote, _executor=lambda: executor, ACTION_TIMEOUT=2):
            started = time.monotonic()
            reply = remote.hold(True)
        self.assertLess(time.monotonic() - started, 1)
        self.assertIs(True, reply["taken"])
        self.assertNotIn("reason", reply)
        self.assertIs(True, reply["held"])
        self.assertIsNone(reply["running"])
        self.assertTrue(remote._actions.empty())

    def test_a_hold_with_no_task_running_still_waits_while_something_can_act(self):
        """Each of these can send input with no task running, or start a task that never reaches the remote."""
        starting = types.SimpleNamespace(start_controller=types.SimpleNamespace(starting=True))
        cases = (
            ("a mode switched on but not yet picked up", idle_executor(tasks=[ChaosMode()]), None),
            ("a stopped mode still in its last pass", idle_executor(tasks=[types.SimpleNamespace(enabled=False, running=True)]), None),
            ("a mode being started", idle_executor(), starting),
            ("a queued executor job", idle_executor(job_queue=["ExecutorJob(2, run code, owner=None)"]), None),
            ("a running executor job", idle_executor(current_job="ExecutorJob(1, run code, owner=None)"), None),
        )
        for name, executor, app in cases:
            with self.subTest(name), standing_in(remote, _executor=lambda: executor, ACTION_TIMEOUT=0.05), \
                    standing_in(og, app=app):
                reply = remote.hold(True)
                self.assertIs(False, reply["taken"])
                self.assertIn("did not come round", reply["reason"])
                self.assertTrue(remote._held.is_set())
            self.tearDown()

    def test_a_mode_started_as_an_idle_hold_replies_sends_nothing(self):
        """A mode started between the look and the reply would click on a screen the caller is told is theirs."""
        executor = idle_executor()
        clicks = []

        def acting(task):
            clicks.append("clicked")
            return True

        loop = PageLoop(self, acting, start=False)
        idle = remote._idle

        def starting_in_between(seen):
            answer = idle(seen)
            # ok-script sets the running task before it calls the mode's `run`, whose pass then reaches the handlers.
            executor.current_task = ChaosMode()
            loop.go.set()
            self.assertTrue(wait_for(lambda: vars(loop.task).get(remote.HELD) or clicks))
            return answer

        with standing_in(remote, _executor=lambda: executor, _idle=starting_in_between, ACTION_TIMEOUT=2):
            reply = remote.hold(True)
        self.assertIs(True, reply["taken"])
        self.assertEqual("ChaosMode", reply["running"])
        time.sleep(0.1)
        self.assertEqual([], clicks)
        self.assertIs(True, vars(loop.task).get(remote.HELD))

    def test_a_hold_before_the_executor_is_built_answers_at_once_and_stays_held(self):
        """Nothing can click before the executor exists, so a 15 s wait there only delays the same answer."""
        with standing_in(og, executor=None), standing_in(remote, ACTION_TIMEOUT=2):
            started = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "has not started"):
                remote.hold(True)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(remote._held.is_set())

    def test_a_release_replies_at_once_with_nothing_to_wait_for(self):
        """A release that waited on the loop would leave a bot whose loop is busy held for another 15 s."""
        executor = idle_executor()
        remote._held.set()
        with standing_in(remote, _executor=lambda: executor):
            started = time.monotonic()
            reply = remote.hold(False)
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(remote._held.is_set())
        self.assertIs(False, reply["held"])
        self.assertNotIn("taken", reply)
        self.assertTrue(remote._actions.empty())

    def test_the_remote_still_acts_on_a_held_bot(self):
        """A hold that also stopped the remote's own actions would leave the caller nothing to step through the screen with."""
        executor = idle_executor()
        PageLoop(self)
        with standing_in(remote, _executor=lambda: executor):
            self.assertIs(True, remote.hold(True)["taken"])
            self.assertEqual("sent", remote.on_bot_thread(lambda task: "sent"))

    def test_the_mcp_hold_tool_passes_taken_and_its_reason_through(self):
        """Dropped on the way, a hold the loop never took would read as one that did."""
        port = serve_remote(self)
        executor = idle_executor(current_task=ChaosMode())
        with standing_in(remote, _executor=lambda: executor, ACTION_TIMEOUT=0.05), \
                standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
            reply = czn_mcp.hold(True)
        self.assertIs(False, reply["taken"])
        self.assertIn("did not come round", reply["reason"])
        self.assertIs(True, reply["held"])

    def test_a_late_action_that_starts_in_time_reports_what_it_did(self):
        """Told it timed out, a caller sends the same input again after the first one already landed."""
        def slow(task):
            time.sleep(0.3)
            return "sent"

        def refused(task):
            time.sleep(0.3)
            raise ValueError("refused")

        for action, expected in ((slow, "'sent'"), (refused, "ValueError('refused')")):
            with self.subTest(action.__name__), standing_in(remote, ACTION_TIMEOUT=0.1, RUNNING_TIMEOUT=5):
                outcome = []
                caller = threading.Thread(target=lambda: outcome.append(attempt(remote.on_bot_thread, action)))
                caller.start()
                run_when_queued("task", caller)
                self.assertEqual([expected], [repr(result) for result in outcome])

    def test_a_started_action_that_hangs_ends_in_a_bounded_error(self):
        """Without a bound, one stuck input would hold the server's thread for good."""
        release = threading.Event()
        outcome = []

        def send():
            outcome.append(attempt(remote.on_bot_thread, lambda task: release.wait(5)))
            release.set()

        with standing_in(remote, ACTION_TIMEOUT=0.05, RUNNING_TIMEOUT=0.1):
            caller = threading.Thread(target=send)
            caller.start()
            run_when_queued("task", caller)
        self.assertEqual(1, len(outcome))
        self.assertIsInstance(outcome[0], TimeoutError)
        self.assertIn("started but had not finished", str(outcome[0]))

    def test_a_drag_swipes_on_the_bot_thread(self):
        """Sent from the server's own thread, a drag would race the handlers acting on the same frame."""
        self.assertIn("drag", remote.COMMANDS)
        swipes = []
        task = types.SimpleNamespace(
            swipe_relative=lambda *points, **kwargs: swipes.append((threading.get_ident(), points, kwargs)),
            sleep=lambda seconds: None,
            executor=types.SimpleNamespace(interaction=PostMessageInteraction.__new__(PostMessageInteraction)),
        )
        self.assertIsNone(drag_on(task, 0.5, 0.8, 0.45, 0.3))
        self.assertEqual([(threading.get_ident(), (0.5, 0.8, 0.45, 0.3), {"duration": remote.DRAG_DURATION})], swipes)

    def test_a_drag_moves_in_steps_and_lets_go_near_the_end(self):
        """ok-script moves one step per 100 ms of the duration, so under 0.1 s it divides by zero before any move."""
        task, events = swiping_task(PostMessageInteraction)
        self.assertIsNone(drag_on(task, 0.5, 0.8, 0.5, 0.3))
        steps = [event for event in events[2:-1] if event[0] == "move"]
        self.assertEqual([("move", 960, 864), ("down", 960, 864)], events[:2])
        self.assertEqual("up", events[-1][0])
        self.assertGreaterEqual(len(steps), 1)
        # PostMessage lets go where its last step left the pointer, which should sit most of the way to the end.
        travelled = (864 - steps[-1][2]) / (864 - 324)
        self.assertGreaterEqual(travelled, 0.9)

    def test_a_drag_is_refused_unless_the_app_uses_post_message(self):
        """Genshin lets go at the middle of the frame, which in a battle can play the card on whatever is there."""
        for interaction in (GenshinInteraction, ForegroundPostMessageInteraction):
            with self.subTest(interaction.__name__):
                task, events = swiping_task(interaction)
                with standing_in(remote, _executor=lambda: task.executor):
                    with self.assertRaisesRegex(RuntimeError, "PostMessage"):
                        remote.drag(0.5, 0.8, 0.5, 0.3)
                self.assertEqual([], events)
                self.assertTrue(remote._actions.empty())

    def test_a_drag_off_the_frame_is_refused(self):
        """A point off the frame is a mistake in the request, and would otherwise press wherever ok-script maps it."""
        with standing_in(remote, ACTION_TIMEOUT=0.01):
            for points in ((1.2, 0.5, 0.5, 0.5), (0.5, -0.1, 0.5, 0.5), (0.5, 0.5, 2, 0.5), (0.5, 0.5, 0.5, -1)):
                with self.subTest(points), self.assertRaises(ValueError):
                    remote.drag(*points)
        self.assertTrue(remote._actions.empty())

    def test_the_mcp_drag_tool_forwards_every_point(self):
        """A point dropped or swapped on the way would drag from or to the wrong place."""
        sent = []
        with standing_in(czn_mcp, call=lambda command, **kwargs: sent.append((command, kwargs)) or "dragged"):
            self.assertEqual("dragged", czn_mcp.drag(0.1, 0.2, 0.3, 0.4))
        self.assertEqual([("drag", {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4})], sent)
        self.assertIn(sent[0][0], remote.COMMANDS)

    def test_status_reports_the_process_id(self):
        """Without it a caller restarting the app cannot tell the old process from the new one."""
        executor = idle_executor()
        with standing_in(remote, _executor=lambda: executor):
            self.assertEqual(os.getpid(), remote.status()["pid"])

    def test_a_quit_is_refused_while_a_task_runs(self):
        """A quit mid-run would cut the bot off between a tap and the screen it leads to."""
        exits = []
        executor = idle_executor(current_task=utils_chaos)
        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0):
            with self.assertRaisesRegex(RuntimeError, "set_running"):
                remote.quit()
            time.sleep(0.1)
        self.assertEqual([], exits)
        self.assertIsNone(remote._quit_reply)

    def test_a_quit_replies_first_and_exits_once(self):
        """A caller that retries, or two callers at once, must not run the app's shutdown twice."""
        exits = []
        replies = []
        executor = idle_executor()
        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0.2):
            callers = [threading.Thread(target=lambda: replies.append(remote.quit())) for _ in range(5)]
            for caller in callers:
                caller.start()
            for caller in callers:
                caller.join()
            self.assertEqual([], exits)
            # Once a quit is accepted, a task started meanwhile changes nothing: the exit is already on its way.
            executor.current_task = utils_chaos
            replies.append(remote.quit())
            self.assertTrue(wait_for(lambda: exits))
            time.sleep(0.3)
        self.assertEqual([{"state": "exiting", "pid": os.getpid()}] * 6, replies)
        self.assertEqual([1], exits)

    def test_the_exit_arms_the_watchdog_then_runs_the_app_quit_on_the_qt_thread(self):
        """A window close may only hide the app in the tray, and a wedged shutdown with no watchdog never ends."""
        calls = []
        dispatcher = types.SimpleNamespace(dispatch=lambda callback, args, kwargs: calls.append(("dispatch", callback, args, kwargs)))
        app = types.SimpleNamespace(quit=lambda: None)
        with standing_in(remote, start_exit_watchdog=lambda grace_period: calls.append(("watchdog", grace_period)),
                         install_qt_event_dispatcher=lambda: dispatcher), standing_in(og, ok=app):
            remote._exit_app()
        self.assertEqual([("watchdog", remote.QUIT_GRACE), ("dispatch", app.quit, (), {})], calls)

    def test_the_port_answers_a_quit_and_still_refuses_unknown_commands(self):
        """The reply has to arrive before the port closes, and the quit must not open the module to other names."""
        exits = []
        executor = idle_executor()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), remote.Remote)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(command):
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/{command}", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)

        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0.2,
                         _last_contact=None):
            self.assertEqual({"ok": True, "result": {"state": "exiting", "pid": os.getpid()}}, post("quit"))
            self.assertEqual([], exits)
            for command in ("exit", "shutdown", "_exit_app", "os"):
                with self.subTest(command):
                    reply = post(command)
                    self.assertFalse(reply["ok"])
                    self.assertIn("unknown command", reply["error"])
            self.assertTrue(wait_for(lambda: exits))

    def test_a_quit_is_refused_while_a_mode_is_switched_on_but_not_yet_running(self):
        """A mode switched on from the window, or queued behind another, can start inside the quit's delay and be cut mid-drag."""
        exits = []
        mode = ChaosMode()
        executor = idle_executor(tasks=[mode])
        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0):
            with self.assertRaisesRegex(RuntimeError, "ChaosMode. Stop it with set_running first"):
                remote.quit()
            time.sleep(0.1)
            self.assertEqual([], exits)
            self.assertIsNone(remote._quit_reply)
            mode.enabled = False
            self.assertEqual("exiting", remote.quit()["state"])
            self.assertTrue(wait_for(lambda: exits))

    def test_a_quit_is_refused_while_set_running_is_still_starting_a_mode(self):
        """`set_running` returns before the start controller switches the mode on, which can land inside the quit's delay."""
        exits = []
        mode = ChaosMode()
        mode.enabled = False
        controller = LateStart()
        executor = idle_executor(tasks=[mode])
        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0), \
                standing_in(og, app=types.SimpleNamespace(start_controller=controller)):
            remote.set_running("ChaosMode", True)
            self.assertEqual((True, False), (controller.starting, mode.enabled))
            with self.assertRaisesRegex(RuntimeError, "being started: stop it with set_running, or wait until status"):
                remote.quit()
            controller.finish()
            with self.assertRaisesRegex(RuntimeError, "ChaosMode. Stop it with set_running first"):
                remote.quit()
            time.sleep(0.1)
            self.assertEqual([], exits)
            self.assertIsNone(remote._quit_reply)
            mode.enabled = False
            self.assertEqual("exiting", remote.quit()["state"])
            self.assertTrue(wait_for(lambda: exits))

    def test_a_quit_is_refused_while_an_executor_job_is_queued(self):
        """A submitted job waits with no job running until the executor's thread takes it, then sends its input."""
        exits = []
        executor = idle_executor(job_queue=["ExecutorJob(2, run code, owner=None)"])
        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0):
            with self.assertRaisesRegex(RuntimeError, "an executor job is queued: wait for it to run and end"):
                remote.quit()
            time.sleep(0.1)
            self.assertEqual([], exits)
            self.assertIsNone(remote._quit_reply)
            executor._job_queue.clear()
            self.assertEqual("exiting", remote.quit()["state"])
            self.assertTrue(wait_for(lambda: exits))

    def test_a_quit_is_refused_while_an_executor_job_runs(self):
        """ok-script's code runner sends input as a job with no task running, and a drag cut mid-way leaves the button down."""
        exits = []
        executor = idle_executor(current_job="ExecutorJob(1, run code, owner=None)")
        with standing_in(remote, _executor=lambda: executor, _exit_app=lambda: exits.append(1), QUIT_DELAY=0):
            with self.assertRaisesRegex(RuntimeError, r"ExecutorJob\(1, run code, owner=None\) is running on the executor: wait"):
                remote.quit()
            time.sleep(0.1)
            self.assertEqual([], exits)
            self.assertIsNone(remote._quit_reply)
            executor.current_job = None
            self.assertEqual("exiting", remote.quit()["state"])
            self.assertTrue(wait_for(lambda: exits))

    def test_the_mcp_bridge_reaches_the_port(self):
        """The port's own guards must never shut out the one caller it is there for."""
        port = serve_remote(self)
        ran = []
        with standing_in(remote, status=lambda **kwargs: ran.append(kwargs) or "status ran", _last_contact=None), \
                standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
            self.assertEqual("status ran", czn_mcp.call("status"))
            self.assertIsNotNone(remote._last_contact)
        self.assertEqual([{}], ran)

    def test_the_mcp_bridge_shows_a_refusal_as_a_refusal(self):
        """Told nothing answers, a live lane goes off to start a debug run that is already up and refusing it."""
        port = serve_remote(self)
        ran = []
        with standing_in(remote, status=lambda **kwargs: ran.append(kwargs) or "status ran", HOST="127.0.0.2"), \
                standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
            with self.assertRaises(czn_mcp.ToolError) as raised:
                czn_mcp.call("status")
        self.assertEqual([], ran)
        self.assertEqual(f"the debug run answered status with HTTP 403 Forbidden: refused: Host '127.0.0.1:{port}' is "
                         f"not 127.0.0.2:{port} or localhost:{port}", str(raised.exception))

    def test_the_mcp_bridge_shows_the_status_of_an_error_with_no_text_to_show(self):
        """Anything but a `ToolError` reaches Claude as a bare "Error executing tool", without the status."""
        cases = {
            "an empty body": (500, b"", "text/plain; charset=utf-8", "HTTP 500 Internal Server Error"),
            "an image": (403, b"\x89PNG\r\n\x1a\n\x00\xff", "image/png", "HTTP 403 Forbidden"),
            "bytes that are not UTF-8": (400, b"refused: \xff", "text/plain; charset=utf-8",
                                         "HTTP 400 Bad Request: refused: �"),
            "an unknown charset": (400, b"refused: x", "text/plain; charset=no-such-charset", "HTTP 400 Bad Request"),
        }
        for case, (status, body, content_type, shown) in cases.items():
            with self.subTest(case):
                port = serve_error(self, status, body, content_type)
                with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
                    with self.assertRaises(czn_mcp.ToolError) as raised:
                        czn_mcp.call("status")
                self.assertEqual(f"the debug run answered status with {shown}", str(raised.exception))

    def test_the_mcp_bridge_waits_on_a_refusal_text_for_one_read_at_most(self):
        """A body promising more than comes must not hold the tool call: what came is shown, or the status alone."""
        cases = {
            "part of the text came": (b"refused: too big", ": refused: too big", 2, 0, 1),
            "none of it came": (b"", "", 0.5, 0.4, 3),
        }
        for case, (body, shown, timeout, at_least, at_most) in cases.items():
            with self.subTest(case):
                port = serve_error(self, 413, body, length=1000)
                with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}", TIMEOUT=timeout):
                    started = time.monotonic()
                    with self.assertRaises(czn_mcp.ToolError) as raised:
                        czn_mcp.call("status")
                    seconds = time.monotonic() - started
                self.assertEqual(f"the debug run answered status with HTTP 413 Request Entity Too Large{shown}",
                                 str(raised.exception))
                self.assertGreaterEqual(seconds, at_least)
                self.assertLess(seconds, at_most)

    def test_the_mcp_bridge_still_says_nothing_answers_on_a_closed_port(self):
        """Only a port with nothing on it needs a `main_debug.py` run started."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
            with self.assertRaises(czn_mcp.ToolError) as raised:
                czn_mcp.call("status")
        self.assertTrue(str(raised.exception).startswith(f"nothing answering on http://127.0.0.1:{port} - start"),
                        str(raised.exception))

    def test_the_mcp_bridge_still_says_nothing_answers_when_the_connect_times_out(self):
        """A connect timeout is still no debug run to talk to, unlike a run that accepted the request and went quiet."""
        def time_out(*args, **kwargs):
            raise TimeoutError("timed out")

        with standing_in(socket, create_connection=time_out), standing_in(czn_mcp, URL="http://127.0.0.1:47999"):
            with self.assertRaises(czn_mcp.ToolError) as raised:
                czn_mcp.call("status")
        self.assertEqual("nothing answering on http://127.0.0.1:47999 - start `python main_debug.py` first (timed out)",
                         str(raised.exception))

    def test_the_mcp_bridge_names_the_command_when_the_reply_breaks_off_or_is_garbled(self):
        """Anything but a `ToolError` reaches Claude as a bare "Error executing tool", with no reason at all."""
        def hold(connection, done):
            done.wait(5)

        def hang_up(connection, done):
            pass

        def cut_off(connection, done):
            connection.sendall(reply_head(100) + b'{"ok": tr')

        def reset(connection, done):
            connection.sendall(reply_head(100) + b'{"ok": tr')
            time.sleep(0.2)
            # A zero linger makes the close a reset instead of an orderly end.
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

        def send(data):
            return lambda connection, done: connection.sendall(data)

        # A shown text ending in "..." is only the start: the rest is the OS's or the decoder's own wording.
        hung_up = "the debug run hung up on status before its reply was complete ("
        not_json = "the debug run answered status with a reply that is not valid JSON ("
        huge = b'{"ok": true, "result": ' + b"1" * 5000 + b"}"
        deep = b"[" * 200000 + b"]" * 200000
        cases = {
            "no head in time": (hold, "the debug run accepted status but then sent nothing for 0.5 s"),
            "closed without answering": (hang_up, hung_up + "Remote end closed connection without response)"),
            "reset mid-body": (reset, hung_up + "..."),
            "body cut off": (cut_off, hung_up + "IncompleteRead(9 bytes read, 91 more expected))"),
            "not HTTP": (send(b"hello\r\n\r\n"), "the debug run answered status with something that is not HTTP "
                                                 "(BadStatusLine: hello\r\n)"),
            "not JSON": (send(reply_head(5) + b"notjs"), not_json + "Expecting value: line 1 column 1 (char 0))"),
            "not UTF-8": (send(reply_head(3) + b'"\xff"'), not_json + "..."),
            "an integer past the digit limit": (send(reply_head(len(huge)) + huge),
                                                not_json + "Exceeds the limit (4300 digits)..."),
            "nesting past the recursion limit": (send(reply_head(len(deep)) + deep),
                                                 not_json + "maximum recursion depth exceeded..."),
        }
        for case, (answer, shown) in cases.items():
            with self.subTest(case):
                port = serve_raw(self, answer)
                with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}", TIMEOUT=0.5):
                    started = time.monotonic()
                    with self.assertRaises(czn_mcp.ToolError) as raised:
                        czn_mcp.call("status")
                    seconds = time.monotonic() - started
                message = str(raised.exception)
                if shown.endswith("..."):
                    self.assertTrue(message.startswith(shown[:-3]), message)
                else:
                    self.assertEqual(shown, message)
                self.assertLess(seconds, 3)

    def test_the_mcp_bridge_names_the_command_for_json_that_is_not_a_reply(self):
        """Without `ok`, or what `ok` promises, a reply would end in a bare `KeyError` or `TypeError`."""
        cases = {
            "no ok": (b'{"result": 1}', 'JSON that is not a reply: {"result": 1}'),
            "a list": (b"[1]", "JSON that is not a reply: [1]"),
            "ok without a result": (b'{"ok": true}', 'JSON that is not a reply: {"ok": true}'),
            "a failure without an error": (b'{"ok": false}', 'JSON that is not a reply: {"ok": false}'),
        }
        for case, (body, shown) in cases.items():
            with self.subTest(case):
                answer = lambda connection, done, body=body: connection.sendall(reply_head(len(body)) + body)
                port = serve_raw(self, answer)
                with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}", TIMEOUT=2):
                    with self.assertRaises(czn_mcp.ToolError) as raised:
                        czn_mcp.call("status")
                self.assertEqual(f"the debug run answered status with {shown}", str(raised.exception))
        failed = b'{"ok": false, "error": "KeyError: \'x\'"}'
        port = serve_raw(self, lambda connection, done: connection.sendall(reply_head(len(failed)) + failed))
        with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}", TIMEOUT=2):
            with self.assertRaises(czn_mcp.ToolError) as raised:
                czn_mcp.call("status")
        self.assertEqual("KeyError: 'x'", str(raised.exception))

    def test_the_mcp_bridge_names_the_command_when_its_reply_cannot_be_read(self):
        """Any other `OSError` while reading, such as a network reset code, would otherwise reach Claude bare."""
        dropped = OSError(errno.ENETRESET, "the network dropped the connection")

        def drop(*args, **kwargs):
            raise dropped

        body = b'{"ok": true, "result": 1}'
        port = serve_raw(self, lambda connection, done: connection.sendall(reply_head(len(body)) + body))
        with standing_in(http.client.HTTPResponse, read=drop), standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
            with self.assertRaises(czn_mcp.ToolError) as raised:
                czn_mcp.call("status")
        self.assertIs(OSError, type(dropped))
        self.assertEqual(f"the debug run's reply to status could not be read ({dropped})", str(raised.exception))

    def test_the_mcp_bridge_adds_no_stray_space_for_an_empty_reason_phrase(self):
        """The port always sends a phrase, but another server on the port need not."""
        port = serve_error(self, 403, b"refused: nope", reason="")
        with standing_in(czn_mcp, URL=f"http://127.0.0.1:{port}"):
            with self.assertRaises(czn_mcp.ToolError) as raised:
                czn_mcp.call("status")
        self.assertEqual("the debug run answered status with HTTP 403: refused: nope", str(raised.exception))

    def test_a_request_a_web_page_could_send_runs_nothing(self):
        """Loopback alone lets any page open in a browser here click, start a mode or end the app through the port."""
        port = serve_remote(self)
        own_host = f"127.0.0.1:{port}"
        refused = {
            "text/plain": ({"Content-Type": "text/plain"}, True, 415),
            "no Content-Type": ({}, True, 415),
            "a form": ({"Content-Type": "application/x-www-form-urlencoded"}, True, 415),
            "a multipart form": ({"Content-Type": "multipart/form-data; boundary=x"}, True, 415),
            "JSON in another type's parameter": ({"Content-Type": "text/plain; x=application/json"}, True, 415),
            "an Origin": ({"Content-Type": "application/json", "Origin": "https://example.com"}, True, 403),
            "an Origin of null": ({"Content-Type": "application/json", "Origin": "null"}, True, 403),
            "a foreign Host": ({"Content-Type": "application/json", "Host": f"rebound.example:{port}"}, True, 403),
            "our address as a prefix": ({"Content-Type": "application/json", "Host": f"127.0.0.1.evil.example:{port}"}, True, 403),
            "another port in Host": ({"Content-Type": "application/json", "Host": f"127.0.0.1:{port + 1}"}, True, 403),
            "a Host with no port": ({"Content-Type": "application/json", "Host": "localhost"}, True, 403),
            "no Host": ({"Content-Type": "application/json"}, False, 403),
        }
        served = {
            "plain JSON": {"Content-Type": "application/json", "Host": own_host},
            "JSON with a charset": {"Content-Type": "application/json; charset=utf-8", "Host": own_host},
            "JSON in capitals": {"Content-Type": "Application/JSON", "Host": own_host},
            "localhost": {"Content-Type": "application/json", "Host": f"LocalHost:{port}"},
        }
        ran = []
        with standing_in(remote, status=lambda **kwargs: ran.append(kwargs) or "status ran", _last_contact=None):
            for case, (headers, host, status) in refused.items():
                with self.subTest(case):
                    ran.clear()
                    remote._last_contact = None
                    code, content_type, text = raw_post(port, headers, host)
                    self.assertEqual((status, "text/plain; charset=utf-8"), (code, content_type))
                    self.assertTrue(text.startswith("refused: "), text)
                    self.assertEqual([], ran)
                    self.assertIsNone(remote._last_contact)
            for case, headers in served.items():
                with self.subTest(case):
                    ran.clear()
                    code, content_type, text = raw_post(port, headers)
                    self.assertEqual((200, {"ok": True, "result": "status ran"}), (code, json.loads(text)))
                    self.assertEqual([{}], ran)

    def test_a_reply_reaches_a_caller_whose_body_trails_the_headers(self):
        """Body bytes that land after the port closes make Windows reset the connection and wipe the unread reply."""
        port = serve_remote(self)
        refused = {
            "text/plain": ({"Content-Type": "text/plain"}, 415),
            "an Origin": ({"Content-Type": "application/json", "Origin": "https://example.com"}, 403),
            "a foreign Host": ({"Content-Type": "application/json", "Host": f"rebound.example:{port}"}, 403),
        }
        ran = []
        with standing_in(remote, status=lambda **kwargs: ran.append(kwargs) or "status ran", _last_contact=None):
            for case, (headers, status) in refused.items():
                with self.subTest(case):
                    code, _, text = raw_post(port, headers, late=True)
                    self.assertEqual(status, code)
                    self.assertTrue(text.startswith("refused: "), text)
                    self.assertIsNone(remote._last_contact)
            with self.subTest("an unknown command"):
                code, _, text = raw_post(port, {"Content-Type": "application/json"}, command="exit", late=True)
                self.assertEqual(200, code)
                self.assertIn("unknown command", json.loads(text)["error"])
        self.assertEqual([], ran)

    def test_a_refused_body_that_never_comes_holds_the_refusal_back_only_briefly(self):
        """A page could send a Content-Length it never fills, and the port must not wait on it for good."""
        port = serve_remote(self)
        with standing_in(remote, DRAIN_TIMEOUT=1):
            for case, length, body, seconds in (("never filled", 10 ** 9, b"{}", 3), ("negative", -1, b"", 0.5),
                                                ("not a number", "two", b"", 0.5)):
                with self.subTest(case):
                    started = time.monotonic()
                    code, _, text = raw_post(port, {"Content-Type": "text/plain"}, body=body, length=length)
                    self.assertEqual(415, code)
                    self.assertTrue(text.startswith("refused: "), text)
                    self.assertLess(time.monotonic() - started, seconds)

    def test_a_trickled_body_holds_the_handler_for_one_deadline_in_all(self):
        """A byte at a time keeps each read inside its timeout, so only a deadline for the whole body ends it."""
        port = serve_remote(self)
        ran = []
        cases = (("refused", {"Content-Type": "text/plain"}, 415),
                 ("served", {"Content-Type": "application/json"}, 408))
        with standing_in(remote, DRAIN_TIMEOUT=1, status=lambda **kwargs: ran.append(kwargs) or "status ran",
                         _last_contact=None):
            for case, headers, status in cases:
                with self.subTest(case):
                    line, seconds = trickle_post(port, headers, length=20, every=0.3)
                    self.assertRegex(line, rf"^HTTP/1\.\d {status} ")
                    self.assertLess(seconds, 2)
                    self.assertIsNone(remote._last_contact)
        self.assertEqual([], ran)

    def test_a_served_content_length_the_port_cannot_trust_is_refused_at_once(self):
        """Taken as given, -1 waits until the caller closes, and a word or 5000 digits raise a ValueError."""
        port = serve_remote(self)
        own = {"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"}
        ran = []
        cases = (("negative", -1, b"", 400, 0.5), ("not a number", "two", b"", 400, 0.5),
                 ("over the limit", remote.DRAIN_LIMIT + 1, b"{}", 413, 2), ("5000 digits", "9" * 5000, b"{}", 413, 2),
                 ("never filled", 10, b"{}", 408, 2))
        with standing_in(remote, DRAIN_TIMEOUT=1, status=lambda **kwargs: ran.append(kwargs) or "status ran",
                         _last_contact=None):
            for case, length, body, status, seconds in cases:
                with self.subTest(case):
                    started = time.monotonic()
                    code, content_type, text = raw_post(port, own, body=body, length=length)
                    self.assertEqual((status, "text/plain; charset=utf-8"), (code, content_type))
                    self.assertTrue(text.startswith("refused: "), text)
                    self.assertLess(time.monotonic() - started, seconds)
                    self.assertIsNone(remote._last_contact)
            self.assertEqual([], ran)
            # HTTP allows leading zeros, and the count they pad is small, so it is served like the count alone.
            with self.subTest("a small count padded with 5000 zeros"):
                code, _, text = raw_post(port, own, body=b"{}", length="0" * 5000 + "2")
                self.assertEqual((200, {"ok": True, "result": "status ran"}), (code, json.loads(text)))
                self.assertEqual([{}], ran)

    def test_a_chunked_body_is_refused_and_runs_nothing(self):
        """Read as an empty body, a chunked `hold` sending `{"on": false}` would hold the bot, not release it."""
        port = serve_remote(self)
        ran = []
        for case, extra in (("no Content-Length", {}), ("a Content-Length beside it", {"Content-Length": "13"})):
            with self.subTest(case), standing_in(remote, hold=lambda **kwargs: ran.append(kwargs) or "hold ran",
                                                 _last_contact=None):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                started = time.monotonic()
                try:
                    headers = {"Content-Type": "application/json", "Transfer-Encoding": "chunked", **extra}
                    # Encoded here, since http.client stops encoding chunks once it sees a Content-Length.
                    body = b'7\r\n{"on": \r\n6\r\nfalse}\r\n0\r\n\r\n'
                    connection.request("POST", "/hold", body=body, headers=headers)
                    response = connection.getresponse()
                    code, content_type = response.status, response.getheader("Content-Type")
                    text = response.read().decode("utf-8")
                finally:
                    connection.close()
                self.assertEqual((411, "text/plain; charset=utf-8"), (code, content_type))
                self.assertTrue(text.startswith("refused: "), text)
                # Read up to the last chunk, not left on the socket to reset the reply or waited on to the deadline.
                self.assertLess(time.monotonic() - started, 1)
                self.assertIsNone(remote._last_contact)
        self.assertEqual([], ran)

    def test_the_mcp_quit_tool_sends_quit(self):
        """A tool forwarding to any other command would leave the app running while the caller waits for it to go."""
        sent = []
        with standing_in(czn_mcp, call=lambda command, **kwargs: sent.append((command, kwargs)) or {"state": "exiting"}):
            self.assertEqual({"state": "exiting"}, czn_mcp.quit())
        self.assertEqual([("quit", {})], sent)
        self.assertIn(sent[0][0], remote.COMMANDS)

    def test_a_screenshot_outlives_the_frame_ok_script_drops(self):
        """ok-script drops its frame on every sleep, so a held bot would otherwise have nothing to show."""
        self.assertIn("next_frame", vars(TaskExecutor))
        captured = np.zeros((9, 16, 3), np.uint8)
        with standing_in(TaskExecutor, next_frame=lambda executor: captured), standing_in(frame_log, _latest=None):
            frame_log.keep_frames()
            TaskExecutor.next_frame(None)
            self.assertEqual(16, remote.screenshot()["width"])


if __name__ == "__main__":
    unittest.main()
