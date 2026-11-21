"""Check the debug-run tools: one saved frame per log line a second, and the remote control's seat in the real mode lists."""

import http.client
import http.server
import importlib.util
import json
import logging
import os
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


def raw_post(port, headers, host=True):
    """POST `{}` to the status command with exactly `headers`, as a browser or another local program might.

    Args:
        port: The remote control's port.
        headers: Every header to send besides Content-Length, and Host unless `headers` names one.
        host: False to send no Host header at all.

    Returns:
        The reply's status, Content-Type and body text.
    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.putrequest("POST", "/status", skip_host=not host or "Host" in headers)
        for name, value in {**headers, "Content-Length": "2"}.items():
            connection.putheader(name, value)
        connection.endheaders(b"{}")
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type"), response.read().decode("utf-8")
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
        """Otherwise the bot acts on the screen being stepped through by hand."""
        remote._held.set()
        self.assertTrue(remote.handle_remote("task"))

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
