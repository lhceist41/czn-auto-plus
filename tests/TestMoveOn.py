"""Check that a navigation tap moves on once its caption has gone, and never taps it twice or waits past upstream.

Upstream's own handlers run here over a task that clicks and sleeps the way ok-script does: `click_box` calls `click`,
a relative point goes round `click` twice, and the wait after a tap goes through `task.sleep`. Time is a fake clock,
so the waits are exact. Captions and their places are the ones the handlers read off live Chaos captures.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from ok.task.exceptions import TaskDisabledException

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

import utils  # noqa: E402

from src.en import handlers, move_on  # noqa: E402
from src.en.handlers import WRAPS  # noqa: E402
from tests.fakes import FakeBox  # noqa: E402

# What one zone read costs on the fake clock, about what a caption-sized OCR takes live.
LOOK_COST = 0.03
# Each handler's caption as the tapped frame read it, at the place the handler looks for it, and upstream's wait after the tap.
CAPTIONS = {
    "handle_confirm": (FakeBox("确认", 0.905, 0.922), 2),
    "handle_continue": (FakeBox("继续", 0.905, 0.922), 2),
    "handle_leave": (FakeBox("离开", 0.945, 0.918), 2),
    "handle_next_step": (FakeBox("下一步", 0.894, 0.921), 2),
    "handle_settlement": (FakeBox("结算", 0.941, 0.917), 1),
    "handle_close_page": (FakeBox("点击屏幕关闭窗口", 0.5, 0.935, width=300), 1),
}
# What the six never wrap: the taps that buy, remove, equip or answer a centred dialog.
LEFT_ALONE = ("handle_center_confirm", "handle_remove", "handle_equipment", "handle_rest", "handle_rest_sortie", "handle_shop")
MODES = 3


class FakeClock:
    """A clock that only moves when the task sleeps or reads."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeTask:
    """A running task whose taps, waits and zone reads follow ok-script's own call paths."""

    def __init__(self, clock, texts, looks, readable=True, failing=None):
        """Set up the tapped frame and what each later look reads.

        Args:
            clock: The fake clock the waits move.
            texts: The tapped frame's OCR boxes.
            looks: One list of boxes per look at the caption's place; the last repeats once they run out.
            readable: False when no frame can be had.
            failing: An exception OCR raises, or None.
        """
        self.clock, self.all_texts, self.looks = clock, texts, list(looks)
        self.readable, self.failing = readable, failing
        self.width, self.height = 1920, 1080
        self.node_status = {"reach_final_boss": False}
        self.taps, self.waits, self.reads = [], [], 0

    def log_info(self, message):
        pass

    def move_relative(self, x, y):
        pass

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.clock.now += seconds
        return True

    @property
    def frame(self):
        return object() if self.readable else None

    def ocr(self, x=0, y=0, to_x=1, to_y=1, frame=None, **kwargs):
        if self.failing:
            raise self.failing
        self.reads += 1
        self.clock.now += LOOK_COST
        return self.looks.pop(0) if len(self.looks) > 1 else (self.looks[0] if self.looks else [])

    def click_box(self, box=None, relative_x=0.5, relative_y=0.5, raise_if_not_found=False, move_back=False, move=True,
                  down_time=0.01, after_sleep=1):
        x, y = int(box.x + box.width * relative_x), int(box.y + box.height * relative_y)
        return self.click(x, y, name=box.name, move_back=move_back, move=move, down_time=down_time, after_sleep=after_sleep)

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1, move=True, down_time=0.02, after_sleep=0, key="left"):
        if 0 < x < 1 or 0 < y < 1:
            return self.click_relative(x, y, move_back, move=move, after_sleep=after_sleep, name=name, down_time=down_time)
        self.taps.append((x, y))
        if after_sleep > 0:
            self.sleep(after_sleep)
        return True

    def click_relative(self, x, y, move_back=False, move=True, after_sleep=0, name=None, down_time=0.02):
        self.click(int(self.width * x), int(self.height * y), move_back, name=name, move=move, down_time=down_time,
                   after_sleep=after_sleep)


class MoveOnCase(unittest.TestCase):
    """Runs one upstream handler under the wrapper on the fake clock."""

    def setUp(self):
        self.clock = FakeClock()
        patches = (mock.patch.object(move_on, "clock", self.clock),
                   mock.patch.object(utils, "is_button_active", lambda task, box: True),
                   mock.patch.object(utils, "_get_game_text", lambda task, text: text))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_handler(self, name, looks, **kwargs):
        """Tap a handler's caption and report what followed.

        Args:
            name: The upstream handler.
            looks: What each look at the caption's place reads.
            **kwargs: Passed to `FakeTask`.

        Returns:
            The task, after the handler, and the seconds from its tap to the handler's return.
        """
        caption, _ = CAPTIONS[name]
        task = FakeTask(self.clock, [caption], looks, **kwargs)
        tapped = []
        task.taps = TapLog(tapped, self.clock)
        self.assertTrue(move_on.moving_on(getattr(utils, name))(task))
        self.assertEqual(1, len(tapped), "exactly one tap")
        return task, self.clock.now - tapped[0]


class TapLog(list):
    """Records the clock at each tap alongside the tap itself."""

    def __init__(self, times, clock):
        super().__init__()
        self.times, self.clock = times, clock

    def append(self, tap):
        self.times.append(self.clock.now)
        super().append(tap)


class TestCaptionStays(MoveOnCase):
    """A caption still shown keeps the whole of upstream's wait, and is never tapped again inside it."""

    def test_each_handler_waits_its_full_time_without_a_second_tap(self):
        for name, (caption, full) in CAPTIONS.items():
            with self.subTest(name=name):
                task, waited = self.run_handler(name, [[caption]])
                self.assertGreaterEqual(waited, full - 1e-9)
                # Never past upstream's wait by more than the one read that started inside it.
                self.assertLessEqual(waited, full + LOOK_COST + 1e-9)
                self.assertGreater(task.reads, 1)

    def test_a_misread_caption_over_its_place_still_holds(self):
        # OCR made something else of the same caption: it must not pass for a gone one.
        _, full = CAPTIONS["handle_confirm"]
        misread = FakeBox("Confirn", 0.905, 0.922)
        _, waited = self.run_handler("handle_confirm", [[misread]])
        self.assertGreaterEqual(waited, full - 1e-9)

    def test_one_missed_read_does_not_end_the_wait(self):
        caption, full = CAPTIONS["handle_leave"]
        _, waited = self.run_handler("handle_leave", [[caption], [], [caption]])
        self.assertGreaterEqual(waited, full - 1e-9)


class TestCaptionGoes(MoveOnCase):
    """A caption gone moves the handler on early."""

    def test_each_handler_moves_on_after_two_empty_looks(self):
        for name, (caption, full) in CAPTIONS.items():
            with self.subTest(name=name):
                task, waited = self.run_handler(name, [[caption], [], []])
                self.assertEqual(3, task.reads)
                self.assertAlmostEqual(3 * (move_on.LOOK_EVERY + LOOK_COST), waited)
                self.assertLess(waited, full)

    def test_the_wait_after_a_gone_caption_is_skipped(self):
        # handle_confirm sleeps once inside `click_box` and once more itself; once the caption has gone, the second
        # wait never starts.
        task, _ = self.run_handler("handle_confirm", [[], []])
        self.assertEqual([move_on.LOOK_EVERY] * 2, task.waits)

    def test_other_text_beside_the_caption_does_not_hold_the_wait(self):
        # The next screen's text within the margin, away from where the caption sat.
        beside = FakeBox("Tap and hold the icon to compare.", 0.905, 0.955, width=400)
        _, waited = self.run_handler("handle_confirm", [[beside]])
        self.assertLess(waited, 1)

    def test_settlement_keeps_its_hover_before_the_tap(self):
        # `_move_and_click` rests on the point for half a second before tapping; that wait is not the tap's.
        task, waited = self.run_handler("handle_settlement", [[], []])
        self.assertEqual(0.5, task.waits[0])
        self.assertLess(waited, 1)

    def test_the_task_gets_its_own_methods_back(self):
        task, _ = self.run_handler("handle_continue", [[]])
        self.assertNotIn("sleep", vars(task))
        self.assertNotIn("click", vars(task))
        self.assertNotIn("click_box", vars(task))


class TestUnreadable(MoveOnCase):
    """A place that cannot be read gets upstream's whole wait."""

    def test_no_frame_waits_the_full_time(self):
        for name, (_, full) in CAPTIONS.items():
            with self.subTest(name=name):
                _, waited = self.run_handler(name, [[]], readable=False)
                self.assertAlmostEqual(full, waited)

    def test_ocr_failing_waits_the_full_time(self):
        _, full = CAPTIONS["handle_next_step"]
        _, waited = self.run_handler("handle_next_step", [[]], failing=RuntimeError("onnx_ocr"))
        self.assertAlmostEqual(full, waited)

    def test_a_stop_during_a_look_still_stops_the_run(self):
        caption, _ = CAPTIONS["handle_continue"]
        task = FakeTask(self.clock, [caption], [[]], failing=TaskDisabledException())
        with self.assertRaises(TaskDisabledException):
            move_on.moving_on(utils.handle_continue)(task)
        self.assertEqual(1, len(task.taps))
        self.assertNotIn("sleep", vars(task))

    def test_a_tap_on_no_text_waits_the_full_time(self):
        # Nothing on the frame holds the tapped point, so there is no caption to watch.
        task = FakeTask(self.clock, [], [[]])
        watch = move_on.CaptionWatch(task)
        with mock.patch.object(task, "click", watch.click), mock.patch.object(task, "sleep", watch.sleep):
            task.click(0.5, 0.5, after_sleep=1)
        self.assertEqual([1], task.waits)
        self.assertEqual(0, task.reads)


class TestSecondTap(MoveOnCase):
    """A handler that taps twice gets upstream's waits from its second tap on, whatever its first caption did."""

    def test_a_second_tap_after_the_first_caption_went_waits_the_full_time(self):
        # No upstream handler taps twice today; one that starts to must not inherit a wait its first caption ended.
        first, _ = CAPTIONS["handle_confirm"]
        second = FakeBox("继续", 0.5, 0.5)

        def handler(task):
            task.click_box(first)
            task.click_box(second)
            task.sleep(1)
            return True

        task = FakeTask(self.clock, [first, second], [[], []])
        tapped = []
        task.taps = TapLog(tapped, self.clock)
        self.assertTrue(move_on.moving_on(handler)(task))
        self.assertEqual(2, len(tapped), "exactly two taps")
        self.assertLess(tapped[1] - tapped[0], 1, "the first caption went before the second tap")
        self.assertAlmostEqual(2, self.clock.now - tapped[1])
        self.assertEqual(2, task.reads, "no look after the second tap")


class TestWhichHandlers(unittest.TestCase):
    """Only the navigation handlers carry the change, once each, wherever a mode lists them."""

    def setUp(self):
        self.utils = types.SimpleNamespace(**{name: named(name) for name in (*CAPTIONS, *LEFT_ALONE)})
        self.originals = dict(vars(self.utils))
        self.mode = types.ModuleType("fake_mode_for_move_on_test")
        self.mode.PAGE_HANDLERS = list(self.originals.values())
        # Only this list: the real modes other tests imported carry the same names, and a stand-in must not land in them.
        lists = mock.patch.object(handlers, "each_list", lambda: iter([(self.mode.__name__, self.mode.PAGE_HANDLERS)]))
        lists.start()
        self.addCleanup(lists.stop)

    def test_the_six_are_wrapped_once_and_listed_in_place(self):
        for _ in range(MODES):
            move_on.install(self.utils)
        for index, name in enumerate(self.originals):
            if name not in CAPTIONS:
                continue
            with self.subTest(name=name):
                current = getattr(self.utils, name)
                self.assertEqual([move_on.TAG], list(getattr(current, WRAPS)))
                self.assertIs(current, self.mode.PAGE_HANDLERS[index])
                self.assertEqual(name, current.__name__)

    def test_buying_removing_equipping_and_centred_confirms_are_left_alone(self):
        move_on.install(self.utils)
        for name in LEFT_ALONE:
            with self.subTest(name=name):
                self.assertIs(self.originals[name], getattr(self.utils, name))
                self.assertIn(self.originals[name], self.mode.PAGE_HANDLERS)
                self.assertNotIn(move_on.TAG, getattr(self.originals[name], WRAPS, ()))
        self.assertTrue(set(LEFT_ALONE).isdisjoint(move_on.HANDLERS))

    def test_every_wrapped_name_is_upstreams(self):
        # A rename upstream would otherwise leave the wrapper silently installed nowhere.
        for name in move_on.HANDLERS:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(utils, name, None)))


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


if __name__ == "__main__":
    unittest.main()
