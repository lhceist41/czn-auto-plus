"""Serve a debug run's frame, OCR and settings on localhost, and take clicks between its frames.

`main_debug.py` answers a few JSON commands for `scripts/czn_mcp.py`, so a screen can be read and a button pressed with
nobody at the desk. Clicks queue for a handler at the top of every mode's list, so they land on the bot's own thread
between frames and never race its handlers. Release runs never start it.
"""

import base64
import concurrent.futures
import http.server
import json
import os
import queue
import threading
import time

import cv2
from PySide6.QtCore import QTimer

from ok import Logger
from ok.device.interaction_methods.post_message import PostMessageInteraction
from ok.ui.qt.events import install_qt_event_dispatcher
from ok.util.process import start_exit_watchdog

from src.en import frame_log, skip_tutorial
from src.en.framework import import_ui
from src.en.handlers import each_list, register
from src.en.screen import centre_of

logger = Logger.get_logger(__name__)

# Loopback only, so nothing off this machine can reach it. `scripts/czn_mcp.py` carries the same address.
HOST = "127.0.0.1"
PORT = 47821
# Seconds an action waits for the bot's page loop. A battle keeps the loop for its whole length.
ACTION_TIMEOUT = 15
# Seconds a caller waits on for an action the bot's thread had already started when `ACTION_TIMEOUT` ran out. A drag
# takes about 1.5 s.
RUNNING_TIMEOUT = 10
# Seconds the bot waits after a remote click, drag or key before reading the next frame.
AFTER_INPUT = 1
# Seconds handed to ok-script's swipe for a drag. It moves in one step per 100 ms of this, 10 ms apart, and lets go at
# its last step, one step short of the end: 2 s makes 20 steps, so the release lands 95% of the way along.
DRAG_DURATION = 2
# JPEG quality for frames sent out. A 1080p frame comes to ~0.3 MB.
QUALITY = 90
# The task a settings command reads when none is named.
DEFAULT_TASK = "ChaosMode"
# The functions below a request may name, so a path can never reach anything else in the module.
COMMANDS = ("status", "screenshot", "texts", "click", "drag", "press_key", "hold", "settings", "set_setting", "set_running", "quit")
# Seconds since the last request before the title bar stops saying the MCP bridge is connected.
STALE = 15
# How often, in milliseconds, the title bar is brought up to date.
TITLE_CHECK = 2000
# Seconds between replying to a quit and starting it, so the reply reaches the caller before the port closes.
QUIT_DELAY = 0.25
# Seconds the app gets to shut down after a quit before ok-script's watchdog ends the process anyway.
QUIT_GRACE = 5

# Actions waiting for the bot's thread, as `(action, future)` pairs.
_actions = queue.Queue()
# Set while the bot is held, so every frame goes to the remote handler and nothing else acts on it.
_held = threading.Event()
# `time.monotonic()` of the last request, from the MCP bridge's pings or a tool call.
_last_contact = None
_patched = False
# The reply to the first accepted quit, so a repeated one gets the same answer and schedules nothing new.
_quit_reply = None
_quit_lock = threading.Lock()


class Remote(http.server.BaseHTTPRequestHandler):
    """Answer `POST /<command>` with a JSON body of keyword arguments, replying `{"ok", "result" | "error"}`."""

    def do_POST(self):
        """Run one command and reply with its result, or with the error it raised. A request a web page could have sent
        is refused before anything runs."""
        global _last_contact
        refusal = self.refusal()
        if refusal is not None:
            status, message = refusal
            self.reply(status, message.encode("utf-8"), "text/plain; charset=utf-8")
            return
        _last_contact = time.monotonic()
        name = self.path.strip("/")
        try:
            if name not in COMMANDS:
                raise KeyError(f"unknown command {name!r}, expected one of {', '.join(COMMANDS)}")
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            reply = {"ok": True, "result": globals()[name](**json.loads(body or b"{}"))}
        except Exception as error:
            reply = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        self.reply(200, json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def refusal(self):
        """Return `(status, message)` for a request that did not come from a tool on this machine, or None to serve it.

        Loopback alone still lets any web page open here POST to the port. A browser sends an `Origin` with every
        cross-site POST, can send JSON only after a CORS preflight this server never answers, and keeps the page's own
        name in `Host` when DNS rebinding points that name at 127.0.0.1.
        """
        port = self.server.server_port
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"{HOST}:{port}", f"localhost:{port}"):
            return 403, f"refused: Host {host!r} is not {HOST}:{port} or localhost:{port}"
        if "Origin" in self.headers:
            return 403, "refused: the request came from a web page"
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return 415, "refused: send the body as Content-Type application/json"
        return None

    def reply(self, status, data, content_type):
        """Send one complete response.

        Args:
            status: The HTTP status code.
            data: The body, already encoded.
            content_type: The body's Content-Type header.
        """
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        """Keep each request out of the console."""


def handle_remote(task):
    """Run the actions queued for the bot's thread, and take the frame while the bot is held.

    Args:
        task: The running mode task.

    Returns:
        True when an action ran or the bot is held, so no other handler acts on this frame.
    """
    ran = False
    while True:
        try:
            action, future = _actions.get_nowait()
        except queue.Empty:
            return ran or _held.is_set()
        # False once the caller gave up waiting, so a late click never lands on a screen nobody is looking at.
        if not future.set_running_or_notify_cancel():
            continue
        try:
            future.set_result(action(task))
        except Exception as error:
            future.set_exception(error)
        ran = True


def install():
    """Put `handle_remote` first in every mode's list, ahead even of `handle_auto_stop`, so a held bot does nothing at all."""
    for _, handlers in each_list():
        # Matched by name: `claims.py` wraps it, and the install runs once per task load.
        if not any(getattr(handler, "__name__", None) == handle_remote.__name__ for handler in handlers):
            handlers.insert(0, handle_remote)


def on_bot_thread(action):
    """Queue an action for `handle_remote` and wait for it to run.

    Args:
        action: Takes the running mode task. Its return value is passed back.

    Returns:
        What `action` returned.

    Raises:
        TimeoutError: The page loop did not come round in `ACTION_TIMEOUT` seconds, so the action is cancelled and never
            runs; its entry stays queued until `handle_remote` skips it. Or the action started in time but had not
            finished `RUNNING_TIMEOUT` seconds later, so its input may still land.
    """
    future = concurrent.futures.Future()
    _actions.put((action, future))
    if not concurrent.futures.wait([future], ACTION_TIMEOUT).done and future.cancel():
        raise TimeoutError(f"the page loop did not come round in {ACTION_TIMEOUT}s, so nothing was sent: no mode is running, or a battle has the loop")
    # Too late to cancel once the bot's thread has started it, so its input is landing: a caller told otherwise would send it twice.
    if not concurrent.futures.wait([future], RUNNING_TIMEOUT).done:
        raise TimeoutError(f"the action started but had not finished {RUNNING_TIMEOUT}s later, so it may still land: take a screenshot before sending it again")
    return future.result()


def _executor():
    """Return ok-script's task executor.

    Raises:
        RuntimeError: The executor has not been built yet.
    """
    from ok import og

    if og.executor is None:
        raise RuntimeError("the task executor has not started")
    return og.executor


def _task(name):
    """Find a task by its class name, such as `ChaosMode`.

    Args:
        name: The class name a request gave.

    Raises:
        KeyError: No task has that name.
    """
    for task in _executor().get_all_tasks():
        if type(task).__name__ == name:
            return task
    raise KeyError(f"no task named {name!r}")


def status():
    """Report which task is running, whether the bot is held, which tasks are switched on, and the app's process id. The
    modes count as tasks here."""
    executor = _executor()
    current = executor.current_task
    return {
        "pid": os.getpid(),
        "running": type(current).__name__ if current is not None else None,
        "held": _held.is_set(),
        "pending": _actions.qsize(),
        "enabled": {type(task).__name__: task.enabled for task in executor.get_all_tasks()},
    }


def screenshot():
    """Return the frame the bot last read, as base64 JPEG.

    Raises:
        RuntimeError: Nothing has been captured yet.
    """
    frame = frame_log.latest()
    if frame is None:
        raise RuntimeError("no frame captured yet")
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
    return {"jpeg": base64.b64encode(jpeg.tobytes()).decode("ascii"), "width": frame.shape[1], "height": frame.shape[0]}


def texts():
    """Return the text the running mode read on its last page-loop frame, with centres as fractions of the frame.

    Raises:
        RuntimeError: The running task keeps no OCR pass, which also covers no task running.
    """
    task = _executor().current_task
    boxes = getattr(task, "all_texts", None)
    if boxes is None:
        raise RuntimeError("the running task keeps no OCR pass")
    centres = [centre_of(box, task.width, task.height) for box in boxes]
    return [{"text": box.name, "x": round(x, 3), "y": round(y, 3)} for box, (x, y) in zip(boxes, centres)]


def _send(label, act):
    """Log one input and run it on the bot's thread.

    Args:
        label: What the log line calls the input.
        act: Takes the running mode task and sends the input.
    """
    def sending(task):
        logger.info(f"remote {label}")
        # The operator's to send, even onto Skip Tutorial: the guard only logs it.
        with skip_tutorial.operating():
            act(task)

    on_bot_thread(sending)
    return label


def click(x, y):
    """Click a point on the bot's thread, between two frames.

    Args:
        x: Horizontal position as a fraction of the frame, 0 to 1.
        y: Vertical position as a fraction of the frame, 0 to 1.
    """
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError("x and y are fractions of the frame, from 0 to 1")
    return _send(f"click at ({x:.3f}, {y:.3f})", lambda task: task.click(x, y, after_sleep=AFTER_INPUT))


def drag(x1, y1, x2, y2):
    """Press at one point, move to another and let go, on the bot's thread between two frames.

    Args:
        x1: Horizontal start as a fraction of the frame, 0 to 1.
        y1: Vertical start as a fraction of the frame, 0 to 1.
        x2: Horizontal end as a fraction of the frame, 0 to 1.
        y2: Vertical end as a fraction of the frame, 0 to 1.

    Raises:
        ValueError: A point is off the frame.
        RuntimeError: The app is set to an interaction other than PostMessage.
    """
    if not all(0 <= value <= 1 for value in (x1, y1, x2, y2)):
        raise ValueError("x1, y1, x2 and y2 are fractions of the frame, from 0 to 1")
    interaction = _executor().interaction
    # Genshin's swipe lets go at the middle of the frame instead of the end, which in a battle can play the card on whatever is there.
    if not isinstance(interaction, PostMessageInteraction):
        raise RuntimeError(f"a drag needs the PostMessage interaction, not {type(interaction).__name__}: switch it in the app's settings")

    def dragging(task):
        task.swipe_relative(x1, y1, x2, y2, duration=DRAG_DURATION)
        task.sleep(AFTER_INPUT)

    return _send(f"drag from ({x1:.3f}, {y1:.3f}) to ({x2:.3f}, {y2:.3f})", dragging)


def press_key(key):
    """Press a key on the bot's thread, between two frames.

    Args:
        key: The key name ok-script sends, such as `esc`.
    """
    return _send(f"key {key}", lambda task: task.send_key(key, after_sleep=AFTER_INPUT))


def hold(on=True):
    """Stop the bot acting on frames, or let it carry on. A held bot still reads every frame, so `texts` stays current.

    Args:
        on: True to hold the bot, False to release it.
    """
    if on:
        _held.set()
    else:
        _held.clear()
    logger.info(f"remote {'hold' if on else 'release'}")
    return status()


def settings(task=DEFAULT_TASK):
    """Return every setting a task carries, by its config key.

    Args:
        task: The task's class name.
    """
    return dict(_task(task).config)


def set_setting(key, value, task=DEFAULT_TASK):
    """Change one setting on a task, saved to its config file as the settings card would.

    Args:
        key: The config key, which for upstream's settings is the Chinese one.
        value: The new value, of the type the setting already holds.
        task: The task's class name.

    Raises:
        KeyError: The task has no such setting.
        ValueError: ok-script's validation refused the value.
    """
    config = _task(task).config
    if key not in config:
        raise KeyError(f"{task} has no setting {key!r}")
    config[key] = value
    if config[key] != value:
        raise ValueError(f"{task} refused {value!r} for {key!r}")
    logger.info(f"remote set {task} {key} = {value!r}")
    return config[key]


def set_running(task, running):
    """Start or stop a mode, as its Start and Stop buttons would.

    Args:
        task: The mode's class name, such as `ChaosMode`.
        running: True to start it, False to stop it.
    """
    from ok import og

    target = _task(task)
    if running:
        # Posted to the controller's own thread, which finds the game window first as the button does.
        og.app.start_controller.start(target)
    else:
        target.disable()
        target.unpause()
    logger.info(f"remote {'start' if running else 'stop'} {task}")
    return status()


def quit():
    """End the whole app after replying, as its own quit would. A closed window may only hide in the tray, so it is not used.

    Returns:
        `{"state": "exiting", "pid": ...}`: the process is gone when that pid is.

    Raises:
        RuntimeError: A task is running, being started or switched on, or an executor job is queued or running, so a
            quit could cut input mid-action. Stop the task with `set_running` first, or wait for the job to end.
    """
    from ok import og

    global _quit_reply
    with _quit_lock:
        if _quit_reply is None:
            executor = _executor()
            current = executor.current_task
            if current is not None:
                raise RuntimeError(f"{type(current).__name__} is running: stop it with set_running first, so the quit never cuts it mid-action")
            # `set_running` only asks the start controller, which finds the game window and switches the mode on later,
            # on its own thread. It switches the mode on before it stops starting, so reading this first leaves no gap.
            if getattr(getattr(getattr(og, "app", None), "start_controller", None), "starting", False):
                raise RuntimeError("a mode is being started: stop it with set_running, or wait until status shows it running")
            # Covers a mode switched on from the window or queued behind another, and a trigger task that is on.
            enabled = [type(task).__name__ for task in executor.get_all_tasks() if task.enabled]
            if enabled:
                raise RuntimeError(f"switched on and may start any moment: {', '.join(enabled)}. Stop it with set_running first")
            # ok-script's code runner sends input as a job, with no task running, and the exit could cut a drag mid-way.
            # A submitted job waits in the queue until the executor's thread takes it.
            if getattr(executor, "_job_queue", None):
                raise RuntimeError("an executor job is queued: wait for it to run and end, then quit")
            job = executor.current_job
            if job is not None:
                raise RuntimeError(f"{job} is running on the executor: wait for it to end, then quit")
            _quit_reply = {"state": "exiting", "pid": os.getpid()}
            logger.info("remote quit")
            timer = threading.Timer(QUIT_DELAY, _exit_app)
            timer.daemon = True
            timer.start()
        return dict(_quit_reply)


def _exit_app():
    """Run ok-script's quit on the Qt thread, with its watchdog armed first so a wedged shutdown still ends the process."""
    from ok import og

    start_exit_watchdog(grace_period=QUIT_GRACE)
    # Hands back the dispatcher the app installed at start, which posts the call to the Qt thread.
    install_qt_event_dispatcher().dispatch(og.ok.quit, (), {})


def show_connection():
    """Add "MCP connected" to the main window's title bar while the MCP bridge is pinging."""
    main_window = import_ui("MainWindow", "MainWindow")
    if main_window is None:
        return
    original_init = main_window.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        title = self.title_bar.title_label.text()

        def update():
            connected = _last_contact is not None and time.monotonic() - _last_contact < STALE
            # Not `setWindowTitle`, which writes the version into the bar as well, right beside the badge that already shows it.
            self.title_bar.set_title(f"{title}  MCP connected" if connected else title)

        # Parented to the window, so it stops when the window goes.
        timer = QTimer(self)
        timer.timeout.connect(update)
        timer.start(TITLE_CHECK)

    main_window.__init__ = patched_init


def apply():
    """Serve the remote control, on a debug run only."""
    global _patched
    if _patched:
        return
    _patched = True
    from ok import og

    if not (og.config or {}).get("debug"):
        return
    register(install)
    show_connection()
    try:
        server = http.server.ThreadingHTTPServer((HOST, PORT), Remote)
    except OSError as error:
        logger.warning(f"remote control could not listen on {HOST}:{PORT}: {error}")
        return
    threading.Thread(target=server.serve_forever, name="remote", daemon=True).start()
    logger.info(f"debug run, remote control listening on http://{HOST}:{PORT}")
