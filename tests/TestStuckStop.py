"""Check that a Chaos, Sortie or Story run frozen for five minutes stops itself, once, and that a pause never causes it.

On a screen that can spend or discard the spend guard withholds upstream's blind taps, so nothing else ends that
freeze: the stop has to fire there too.
"""

import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import handlers, notify, spend_guard, stuck_stop  # noqa: E402
from tests.fakes import FakeBox  # noqa: E402

START = 1_000_000.0
INSTALLS = 3


class Clock:
    """Wall time the test moves by hand, standing in for `time.time` everywhere the run reads it."""

    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


class FakeTask:
    """A mode looking at one screen, recording every tap, announcement and stop."""

    def __init__(self, texts=()):
        """Put boxes on the screen.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
        """
        self.name = "自动卡厄思模式"
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.clicked = []
        self.logged = []
        self.notifications = []
        self.disabled = 0

    def find_one(self, feature_name, box=None):
        return None

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled += 1


def named(name):
    """Build a stand-in handler carrying a given name.

    Args:
        name: The `__name__` the handler should report.

    Returns:
        A function that declines every frame.
    """
    def handler(task):
        return False

    handler.__name__ = name
    return handler


def fake_utils(clock):
    """Build a stand-in for `utils` whose screen never changes.

    Args:
        clock: The test's clock.

    Returns:
        A namespace carrying the stuck detector and the handlers the patches wrap.
    """
    def handle_stuck_log(task):
        task.clicked.append("blind tap")
        return False

    def is_frame_stuck(task, stuck_threshold_seconds=30):
        # Seeds itself the way upstream does, from absence, and never sees a change after that.
        if "_last_change_time" not in vars(task):
            task._last_change_time = clock()
        return clock() - task._last_change_time >= stuck_threshold_seconds

    return types.SimpleNamespace(handle_auto_stop=named("handle_auto_stop"), handle_stuck_log=handle_stuck_log,
                                 is_frame_stuck=is_frame_stuck)


def frozen(task, clock, seconds):
    """Freeze a task's screen for a while, with the last pass of the stop a second ago.

    Args:
        task: The task.
        clock: The test's clock.
        seconds: How long the picture has looked the same.

    Returns:
        The task.
    """
    task._last_change_time = clock() - seconds
    setattr(task, stuck_stop.LAST_PASS, clock() - 1)
    return task


def names(module):
    """Read a mode's handler names in order.

    Args:
        module: The stand-in mode.

    Returns:
        A list of names.
    """
    return [handler.__name__ for handler in module.PAGE_HANDLERS]


class Modes:
    """Put stand-in modes in `sys.modules` under the given names, and the real ones back afterwards.

    `handlers.each_list` and `insert_before(only=...)` go by the name a module is imported under, so the stand-ins
    have to take the real modes' names for the length of a test.
    """

    def __init__(self, **lists):
        """Build the modes.

        Args:
            **lists: Module name to its handler list.
        """
        self.modules = {}
        for name, handler_list in lists.items():
            module = types.ModuleType(name)
            module.PAGE_HANDLERS = handler_list
            self.modules[name] = module
        self.held = {}

    def __enter__(self):
        for name, module in self.modules.items():
            self.held[name] = sys.modules.get(name)
            sys.modules[name] = module
        return self.modules

    def __exit__(self, *exc):
        for name, original in self.held.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class TestStuckStop(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        patcher = mock.patch("time.time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.handler = stuck_stop.stopping(fake_utils(self.clock))

    def tick(self, seconds=1):
        self.clock.now += seconds

    def test_a_screen_frozen_past_the_limit_stops_the_run(self):
        task = frozen(FakeTask(), self.clock, stuck_stop.STOP_SECONDS + 1)
        self.assertIs(True, self.handler(task))
        self.assertEqual(1, task.disabled)
        self.assertEqual([stuck_stop.MESSAGE], task.notifications)

    def test_the_stop_is_announced_once(self):
        """The loop can come round again before it sees the task disabled, and a toast per frame would bury the one that matters."""
        task = frozen(FakeTask(), self.clock, stuck_stop.STOP_SECONDS + 1)
        for _ in range(5):
            self.assertIs(True, self.handler(task))
            self.tick()
        self.assertEqual([stuck_stop.MESSAGE], task.notifications)

    def test_a_screen_frozen_under_the_limit_keeps_running(self):
        task = frozen(FakeTask(), self.clock, stuck_stop.STOP_SECONDS - 1)
        self.assertIs(False, self.handler(task))
        self.assertEqual(0, task.disabled)
        self.assertEqual([], task.notifications)

    def test_a_long_gap_between_passes_restarts_the_clock(self):
        """A pause or a break looks like a frozen screen to the detector, so it may delay a stop but never cause one."""
        task = frozen(FakeTask(), self.clock, stuck_stop.STOP_SECONDS + 100)
        setattr(task, stuck_stop.LAST_PASS, self.clock() - stuck_stop.GAP_SECONDS - 1)
        self.assertIs(False, self.handler(task))
        for elapsed in range(1, stuck_stop.STOP_SECONDS + 1):
            self.tick()
            self.assertIs(elapsed >= stuck_stop.STOP_SECONDS, self.handler(task), f"{elapsed}s after the gap")
        self.assertEqual(1, task.disabled)

    def test_it_runs_first_in_chaos_sortie_and_story_only(self):
        """Story has no stop handler to sit in front of, so it goes ahead of whatever Story's list starts with. Any other mode is left alone."""
        modes = Modes(
            utils_chaos=[named("handle_remote"), named("handle_auto_stop"), named("handle_save_target_member")],
            utils_sortie=[named("handle_auto_stop"), named("handle_route_selection")],
            utils_story=[named("handle_fast_forward"), named("handle_center_confirm"), named("handle_story_complete")],
            fake_other_mode_for_stuck_stop_test=[named("handle_auto_stop")],
        )
        with modes as loaded:
            stuck_stop.install(fake_utils(self.clock))
        self.assertEqual(["handle_remote", "stop_when_stuck", "handle_auto_stop", "handle_save_target_member"], names(loaded["utils_chaos"]))
        self.assertEqual(["stop_when_stuck", "handle_auto_stop", "handle_route_selection"], names(loaded["utils_sortie"]))
        self.assertEqual(["stop_when_stuck", "handle_fast_forward", "handle_center_confirm", "handle_story_complete"], names(loaded["utils_story"]))
        self.assertEqual(["handle_auto_stop"], names(loaded["fake_other_mode_for_stuck_stop_test"]))

    def test_installing_twice_inserts_once(self):
        """The install runs on every task load."""
        modes = Modes(utils_chaos=[named("handle_auto_stop")], utils_sortie=[named("handle_auto_stop")], utils_story=[named("handle_center_confirm")])
        with modes as loaded:
            for _ in range(INSTALLS):
                stuck_stop.install(fake_utils(self.clock))
        for name, anchor in (("utils_chaos", "handle_auto_stop"), ("utils_sortie", "handle_auto_stop"), ("utils_story", "handle_center_confirm")):
            with self.subTest(mode=name):
                self.assertEqual(["stop_when_stuck", anchor], names(loaded[name]))

    def test_a_frozen_story_screen_stops_story_once(self):
        """Story used to sit on a screen none of its handlers knew for as long as nobody looked."""
        stand_in = fake_utils(self.clock)
        with Modes(utils_story=[named("handle_center_confirm"), named("handle_enter_story_or_battle")]) as loaded:
            stuck_stop.install(stand_in)
        page_handlers = loaded["utils_story"].PAGE_HANDLERS
        task = FakeTask([("Chapter 1", 0.47, 0.04)])
        task.name = "半自动剧情模式"
        stopped_after = None
        for elapsed in range(1, stuck_stop.STOP_SECONDS * 2):
            self.tick()
            any(handler(task) for handler in page_handlers)
            if task.disabled and stopped_after is None:
                stopped_after = elapsed
        self.assertIsNotNone(stopped_after)
        self.assertLessEqual(stopped_after, stuck_stop.STOP_SECONDS + 1)
        self.assertEqual([stuck_stop.MESSAGE], task.notifications)

    def test_a_frozen_spend_screen_still_stops(self):
        """The spend guard withholds upstream's taps there, so the stop is the only thing that ends the freeze."""
        stand_in = fake_utils(self.clock)
        with Modes(utils_chaos=[stand_in.handle_auto_stop, stand_in.handle_stuck_log]) as loaded:
            for _ in range(INSTALLS):
                # In the order `src/globals.py` applies them, notify's install wrapping what the module carries.
                spend_guard.install(stand_in)
                handlers.replace("handle_stuck_log", notify.stuck(stand_in.handle_stuck_log))
                stuck_stop.install(stand_in)
        page_handlers = loaded["utils_chaos"].PAGE_HANDLERS
        task = FakeTask([("德朗商店", 0.1, 0.05)])
        stopped_after = None
        for elapsed in range(1, stuck_stop.STOP_SECONDS * 2):
            self.tick()
            # The run loop: the first handler to claim the frame ends it.
            any(handler(task) for handler in page_handlers)
            if task.disabled:
                stopped_after = elapsed
                break
        self.assertIn("not tapping at random on a screen that can spend or discard", task.logged)
        self.assertEqual([], task.clicked)
        self.assertIsNotNone(stopped_after)
        self.assertLessEqual(stopped_after, stuck_stop.STOP_SECONDS + 1)
        self.assertEqual(2, len(task.notifications))
        self.assertIn("Stuck on the same screen", task.notifications[0])
        self.assertEqual(stuck_stop.MESSAGE, task.notifications[1])


class TestInstall(unittest.TestCase):

    def test_it_is_installed_before_claims(self):
        """claims wraps the lists as it finds them, so a handler inserted after it can miss the wrap and go unnamed in the frame log."""
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertIn("stuck_stop", applied)
        self.assertLess(applied.index("stuck"), applied.index("stuck_stop"))
        self.assertLess(applied.index("stuck_stop"), applied.index("claims"))


if __name__ == "__main__":
    unittest.main()
