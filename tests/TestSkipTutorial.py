"""Check that no tap, press or drag end lands on the tutorial's Skip Tutorial button while it shows, in any mode.

The guard sits on ok-script's real `ExecutorOperation`, so each mode is driven through its real class and upstream's real
`click`, `click_box`, `click_relative`, `swipe_relative` and `mouse_down`. Only the executor below them is a stand-in,
which records what reached the game. Frames are drawn here: a bright outline where the button is, and the bar's
icons and a close X in the same corner for the frames without it.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

from ok.feature.Box import Box  # noqa: E402
from ok.task.exceptions import TaskDisabledException  # noqa: E402
from ok.task.task import ExecutorOperation  # noqa: E402

from src.en import humanize, remote, skip_tutorial  # noqa: E402
from src.en.daily import DailyMode  # noqa: E402
from src.en.handlers import WRAPS  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

from ChaosMode import ChaosMode  # noqa: E402
from SortieMode import SortieMode  # noqa: E402
from StoryMode import StoryMode  # noqa: E402

MODES = (StoryMode, ChaosMode, SortieMode, DailyMode)
# Targets that share the button's corner and are pressed whenever it is absent.
MENU = (0.959, 0.046)
BANNER_CLOSE = (0.968, 0.049)
BAR_AUTO = (0.830, 0.053)
FAST_FORWARD = (0.895, 0.053)
PAGE_CLOSE = (0.960, 0.054)
BATTLE_AUTO = (0.880, 0.056)
CORNER_TARGETS = (MENU, BANNER_CLOSE, BAR_AUTO, FAST_FORWARD, PAGE_CLOSE, BATTLE_AUTO)
# Story's taps on the tutorial's own screens, all outside the corner.
SAVE_DATA_CLOSE = (0.883, 0.156)
BAR_SKIP = (0.767, 0.053)
NOTICE_CLOSE = (0.911, 0.120)
MISSION_CARD = (0.300, 0.500)
OUTSIDE_TARGETS = (SAVE_DATA_CLOSE, BAR_SKIP, NOTICE_CLOSE, MISSION_CARD)


def pixels(point, width=WIDTH, height=HEIGHT):
    """Turn a frame fraction into the pixel point `click` receives."""
    return int(point[0] * width), int(point[1] * height)


def dark_frame(width=WIDTH, height=HEIGHT):
    """A plain dark frame."""
    return np.full((height, width, 3), 30, np.uint8)


def pill_frame(width=WIDTH, height=HEIGHT):
    """A frame with the button's bright outline where the client draws it."""
    frame = dark_frame(width, height)
    left, top, right, bottom = skip_tutorial.OUTLINE
    cv2.rectangle(frame, (round(left * width), round(top * height)), (round(right * width), round(bottom * height)), (235, 235, 235), 2)
    return frame


def bar_frame():
    """A frame with bright icons and a close X in the corner, as the bar and a page draw them, and no button."""
    frame = dark_frame()
    for point in (BAR_AUTO, FAST_FORWARD, MENU):
        cv2.circle(frame, pixels(point), 22, (240, 240, 240), 3)
    x, y = pixels(PAGE_CLOSE)
    cv2.line(frame, (x - 20, y - 20), (x + 20, y + 20), (250, 250, 250), 4)
    cv2.line(frame, (x - 20, y + 20), (x + 20, y - 20), (250, 250, 250), 4)
    return frame


class Interaction:
    """Records what reached the game."""

    def __init__(self):
        self.sent = []

    def click(self, x, y, **kwargs):
        self.sent.append(("tap", x, y))

    def mouse_down(self, x, y, **kwargs):
        self.sent.append(("press", x, y))

    def swipe(self, from_x, from_y, to_x, to_y, duration, settle_time=0):
        self.sent.append(("drag", from_x, from_y, to_x, to_y))


class Executor:
    """The executor below a task: hands out frames and takes its input."""

    def __init__(self, fresh, held=None):
        self.interaction = Interaction()
        self.method = SimpleNamespace(width=WIDTH, height=HEIGHT)
        self.device_manager = SimpleNamespace(supported_ratio=16 / 9)
        self.scene = None
        self.fresh = fresh
        self.held = held
        self.captures = 0

    def nullable_frame(self):
        return self.held

    def next_frame(self):
        self.captures += 1
        return self.fresh

    def reset_scene(self):
        pass

    def sleep(self, seconds):
        pass

    def remove_onetime_task(self, task):
        pass

    def _wake_executor(self):
        pass


def mode(cls, texts=(), fresh=None, held=None):
    """Build a running mode of the real class over a stand-in executor.

    Args:
        cls: The mode's class.
        texts: What the current OCR pass read.
        fresh: The frame a capture hands out, or None when capture fails.
        held: The frame the handler read.

    Returns:
        The task, with `notes` listing what it announced.
    """
    task = cls.__new__(cls)
    task._executor = Executor(dark_frame() if fresh is None else fresh, held)
    task.logger = skip_tutorial.logger
    task.last_click_time = 0
    task.name = cls.__name__
    task.info = {}
    task.config = {"_enabled": True}
    task._enabled = True
    task.all_texts = list(texts)
    task.notes = []
    task.notification = lambda message, **kwargs: task.notes.append(message)
    return task


def pill_read():
    """An OCR pass that reads the button where the client draws it."""
    return [FakeBox("Skip Tutorial", 0.879, 0.055)]


class GuardTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        skip_tutorial.apply()

    def assertRefused(self, task, act):
        with self.assertRaises(TaskDisabledException):
            act()
        self.assertEqual(task.executor.interaction.sent, [])
        self.assertFalse(task.enabled)
        self.assertEqual(task.notes, [skip_tutorial.STOP_MESSAGE])

    def assertSent(self, task, *inputs):
        self.assertEqual(task.executor.interaction.sent, list(inputs))
        self.assertTrue(task.enabled)
        self.assertEqual(task.notes, [])


class TestRefused(GuardTest):

    def test_a_tap_in_the_corner_with_the_caption_read_is_refused_and_stops_each_mode(self):
        for cls in MODES:
            for point in CORNER_TARGETS:
                with self.subTest(mode=cls.__name__, point=point):
                    task = mode(cls, pill_read())
                    self.assertRefused(task, lambda: task.click(*point))

    def test_with_the_caption_missed_the_outline_on_a_fresh_frame_refuses_the_tap(self):
        for cls in MODES:
            with self.subTest(mode=cls.__name__):
                task = mode(cls, fresh=pill_frame())
                self.assertRefused(task, lambda: task.click(*MENU))
                self.assertEqual(task.executor.captures, 1)

    def test_the_outline_is_found_on_a_frame_of_another_size(self):
        task = mode(StoryMode, fresh=pill_frame(1280, 720))
        self.assertRefused(task, lambda: task.click(*FAST_FORWARD))

    def test_a_box_click_and_a_pixel_click_in_the_corner_are_refused_alike(self):
        task = mode(ChaosMode, pill_read())
        x, y = pixels(PAGE_CLOSE)
        self.assertRefused(task, lambda: task.click_box(Box(x - 20, y - 20, 40, 40, name="X")))
        task = mode(ChaosMode, pill_read())
        x, y = pixels(MENU)
        self.assertRefused(task, lambda: task.click(Box(x - 10, y - 10, 20, 20, name="Menu")))
        task = mode(SortieMode, pill_read())
        self.assertRefused(task, lambda: task.click(*pixels(BANNER_CLOSE)))

    def test_a_drag_ending_or_starting_in_the_corner_is_refused(self):
        for cls in MODES:
            with self.subTest(mode=cls.__name__):
                task = mode(cls, pill_read())
                self.assertRefused(task, lambda: task.swipe_relative(0.5, 0.5, *MENU))
                task = mode(cls, fresh=pill_frame())
                self.assertRefused(task, lambda: task.swipe_relative(*FAST_FORWARD, 0.5, 0.5))

    def test_a_press_in_the_corner_is_refused(self):
        task = mode(SortieMode, pill_read())
        self.assertRefused(task, lambda: task.mouse_down(*pixels(BATTLE_AUTO)))

    def test_the_rim_around_the_outline_is_guarded_and_the_next_pixel_out_is_not(self):
        # Written out rather than taken from the box, so an edit that shrinks or moves the box fails here.
        for point in ((0.812, 0.096), (0.995, 0.015), (0.900, 0.102), (0.900, 0.009)):
            with self.subTest(point=point):
                task = mode(StoryMode, pill_read())
                self.assertRefused(task, lambda: task.click(*point))
        outside = ((0.806, 0.050), (0.900, 0.104), (0.900, 0.007))
        task = mode(StoryMode, pill_read())
        for point in outside:
            task.click(*point)
        self.assertSent(task, *(("tap", *pixels(point)) for point in outside))

    def test_no_frame_to_check_refuses_a_tap_in_the_corner(self):
        task = mode(DailyMode)
        task.executor.fresh = None
        self.assertRefused(task, lambda: task.click(*MENU))

    def test_a_missed_capture_falls_back_to_the_frame_the_handler_read(self):
        task = mode(StoryMode, held=pill_frame())
        task.executor.fresh = None
        self.assertRefused(task, lambda: task.click(*MENU))
        task = mode(StoryMode, held=dark_frame())
        task.executor.fresh = None
        task.click(*MENU)
        self.assertSent(task, ("tap", *pixels(MENU)))

    def test_once_stopped_any_further_input_from_the_run_is_refused_until_it_starts_again(self):
        task = mode(StoryMode, pill_read())
        self.assertRefused(task, lambda: task.click(*MENU))
        with self.assertRaises(TaskDisabledException):
            task.click(*MISSION_CARD)
        self.assertEqual(task.executor.interaction.sent, [])
        task._enabled = True
        task.all_texts = []
        task.click(*MISSION_CARD)
        self.assertEqual(task.executor.interaction.sent, [("tap", *pixels(MISSION_CARD))])


class TestSent(GuardTest):

    def test_without_the_button_every_corner_target_is_tapped_in_each_mode(self):
        for cls in MODES:
            for frame in (dark_frame(), bar_frame()):
                with self.subTest(mode=cls.__name__):
                    task = mode(cls, fresh=frame)
                    for point in CORNER_TARGETS:
                        task.click(*point)
                    self.assertSent(task, *(("tap", *pixels(point)) for point in CORNER_TARGETS))

    def test_with_the_button_read_taps_outside_the_corner_go_through_without_a_capture(self):
        for cls in MODES:
            with self.subTest(mode=cls.__name__):
                task = mode(cls, pill_read(), fresh=pill_frame())
                for point in OUTSIDE_TARGETS:
                    task.click(*point)
                task.swipe_relative(0.3, 0.6, 0.3, 0.3)
                task.mouse_down(*pixels(MISSION_CARD))
                self.assertSent(task, *(("tap", *pixels(point)) for point in OUTSIDE_TARGETS), ("drag", 576, 648, 576, 324),
                                ("press", *pixels(MISSION_CARD)))
                self.assertEqual(task.executor.captures, 0)

    def test_without_the_button_a_drag_and_a_press_in_the_corner_go_through(self):
        task = mode(ChaosMode, fresh=bar_frame())
        task.swipe_relative(0.5, 0.5, *MENU)
        task.mouse_down(*pixels(PAGE_CLOSE))
        self.assertSent(task, ("drag", 960, 540, *pixels(MENU)), ("press", *pixels(PAGE_CLOSE)))

    def test_the_caption_elsewhere_than_the_button_still_counts(self):
        task = mode(DailyMode, [FakeBox("skiptutorial", 0.5, 0.5)])
        self.assertRefused(task, lambda: task.click(*MENU))


class TestOperator(GuardTest):

    def test_the_debug_port_click_onto_the_button_is_sent_and_logged(self):
        for texts, held in ((pill_read(), None), ((), pill_frame())):
            task = mode(StoryMode, texts, held=held)
            with mock.patch.object(remote, "on_bot_thread", lambda action: action(task)), mock.patch.object(skip_tutorial, "logger") as logger:
                remote.click(*MENU)
            self.assertEqual(task.executor.interaction.sent, [("tap", *pixels(MENU))])
            self.assertTrue(task.enabled)
            self.assertIn("Skip Tutorial", logger.warning.call_args.args[0])
            self.assertEqual(task.executor.captures, 0)

    def test_the_debug_port_click_off_the_button_logs_nothing(self):
        task = mode(StoryMode, held=dark_frame())
        with mock.patch.object(remote, "on_bot_thread", lambda action: action(task)), mock.patch.object(skip_tutorial, "logger") as logger:
            remote.click(*MENU)
        self.assertEqual(task.executor.interaction.sent, [("tap", *pixels(MENU))])
        logger.warning.assert_not_called()

    def test_operator_input_ends_with_its_block(self):
        task = mode(StoryMode, pill_read())
        with skip_tutorial.operating():
            task.click(*MENU)
        with self.assertRaises(TaskDisabledException):
            task.click(*MENU)
        self.assertEqual(task.executor.interaction.sent, [("tap", *pixels(MENU))])


class TestInstall(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        skip_tutorial.apply()

    def test_installed_once_however_often_it_runs(self):
        skip_tutorial.apply()
        before = {name: getattr(ExecutorOperation, name) for name in skip_tutorial.GUARDS}
        skip_tutorial.install(ExecutorOperation)
        skip_tutorial.install(ExecutorOperation)
        skip_tutorial._patched = False
        skip_tutorial.apply()
        for name, wrapped in before.items():
            with self.subTest(name=name):
                self.assertIs(getattr(ExecutorOperation, name), wrapped)
                self.assertEqual(getattr(wrapped, WRAPS).count(skip_tutorial.TAG), 1)
                self.assertEqual(wrapped.__name__, name)

    def test_every_mode_inherits_the_guarded_input(self):
        for cls in MODES:
            for name in skip_tutorial.GUARDS:
                with self.subTest(mode=cls.__name__, name=name):
                    self.assertIn(skip_tutorial.TAG, getattr(getattr(cls, name), WRAPS, ()))


class TestDrift(unittest.TestCase):

    def test_a_fixed_tap_just_outside_the_box_stays_off_the_outline_at_the_largest_spread(self):
        # The guard checks the aimed point, and humanize drifts a fixed tap afterwards, so the box must reach further
        # out from the outline than the largest drift Input Variance allows.
        spread = humanize.human_input_option.config_type[humanize.SPREAD_PX]["max"]
        reach = spread * HEIGHT / humanize.REFERENCE_HEIGHT
        task = SimpleNamespace(width=WIDTH, height=HEIGHT)
        x, y = pixels((0.900, 0.050))
        above = next(row for row in range(y, -1, -1) if not skip_tutorial.guarded(task, x, row))
        below = next(row for row in range(y, HEIGHT) if not skip_tutorial.guarded(task, x, row))
        left = next(column for column in range(x, -1, -1) if not skip_tutorial.guarded(task, column, y))
        outline_left, outline_top, _, outline_bottom = skip_tutorial.OUTLINE
        self.assertLess(round(above + reach) / HEIGHT, outline_top)
        self.assertGreater(round(below - reach) / HEIGHT, outline_bottom)
        self.assertLess(round(left + reach) / WIDTH, outline_left)


class TestOutline(unittest.TestCase):

    def test_the_outline_is_found_only_where_the_button_is(self):
        self.assertTrue(skip_tutorial.ring_shown(pill_frame()))
        self.assertTrue(skip_tutorial.ring_shown(cv2.cvtColor(pill_frame(), cv2.COLOR_BGR2BGRA)))
        self.assertFalse(skip_tutorial.ring_shown(dark_frame()))
        self.assertFalse(skip_tutorial.ring_shown(bar_frame()))
        moved = np.roll(pill_frame(), 40, axis=1)
        self.assertFalse(skip_tutorial.ring_shown(moved))


if __name__ == "__main__":
    unittest.main()
