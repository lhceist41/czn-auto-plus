"""Check that a run speaks up when it starts, when it finishes, and when it is stuck."""

import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

import utils  # noqa: E402

from src.en import handlers, notify  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

INSTALLS = 3
# The Lobby as OCR read it off a live capture: the Story button where upstream reads it, and the other mode buttons below.
LOBBY = [("等级", 0.054, 0.047), ("104/240+", 0.700, 0.049), ("故事", 0.884, 0.156), ("Chapter 2, Episode 2", 0.845, 0.194),
         ("Sortie", 0.884, 0.266), ("Simulation", 0.874, 0.353), ("Chaos", 0.891, 0.442), ("方舟城市", 0.883, 0.521),
         ("Combatants", 0.868, 0.615), ("营救", 0.887, 0.705)]
# The Rescue and Ark City headers, top left, from their own captures.
RESCUE = [("营救", 0.116, 0.046), ("Normal Rescue", 0.29, 0.187)]
ARK_CITY = [("方舟城市", 0.118, 0.046)]


class FakeTask:
    """A mode, recording what it was asked to announce."""

    def __init__(self, rounds=0, wins=0, bosses=0):
        self.name = "自动卡厄思模式"
        self.node_status = {
            notify.ROUNDS: rounds,
            notify.WINS: wins,
            notify.BOSSES: bosses,
        }
        self.logged = []
        self.notifications = []
        self.enables = 0

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append({"message": message, "title": title, "tray": tray})

    def enable(self):
        self.enables += 1


def finishes(task, wins_it=True):
    """Stand in for upstream's expedition result page, which scores the run and clears its status.

    Args:
        task: The task being scored.
        wins_it: Whether the run counted as a success.

    Returns:
        The wrapped handler's own return value.
    """
    def handle_expedition_result(task):
        task.node_status[notify.ROUNDS] += 1
        if wins_it:
            task.node_status[notify.WINS] += 1
        # Upstream clears the per-run status before it returns, which is what takes the floor with it.
        task.node_status[notify.BOSSES] = 0
        return False

    return notify.finishing(handle_expedition_result)(task)


class TestNotify(unittest.TestCase):

    def test_starting_a_run_announces_it(self):
        task = FakeTask()
        task.enable = notify.starting(task.enable, task)
        task.enable()
        self.assertEqual(1, task.enables)
        self.assertEqual(["Run started."], [note["message"] for note in task.notifications])

    def test_the_notification_is_titled_with_the_mode(self):
        """The title is run through the app catalog on the way out, which puts it in English."""
        task = FakeTask()
        notify.starting(task.enable, task)()
        self.assertEqual("自动卡厄思模式", task.notifications[0]["title"])

    def test_every_notification_reaches_windows(self):
        """Without `tray`, it only shows inside the app, which defeats the point of notifying."""
        task = FakeTask()
        notify.starting(task.enable, task)()
        self.assertTrue(task.notifications[0]["tray"])

    def test_a_finished_run_reports_the_floor_it_reached(self):
        """The floor has to be read before the handler runs, because the handler clears it."""
        task = FakeTask(rounds=2, wins=1, bosses=3)
        finishes(task)
        self.assertEqual(["Run finished on floor 4. 2 of 3 runs have succeeded."],
                         [note["message"] for note in task.notifications])

    def test_a_lost_run_is_reported_too(self):
        task = FakeTask(rounds=0, wins=0, bosses=0)
        finishes(task, wins_it=False)
        self.assertEqual(["Run finished on floor 1. 0 of 1 runs have succeeded."],
                         [note["message"] for note in task.notifications])

    def test_a_page_that_scored_nothing_says_nothing(self):
        """The handler runs on every frame that shows the page, and only one of them counts a round."""
        task = FakeTask(rounds=1)
        notify.finishing(lambda task: False)(task)
        self.assertEqual([], task.notifications)

    def test_a_screen_stuck_past_the_threshold_is_reported(self):
        task = FakeTask()
        task._last_change_time = time.time() - (notify.STUCK_SECONDS + 5)
        notify.stuck(lambda task: False)(task)
        self.assertEqual(1, len(task.notifications))
        self.assertIn("Stuck on the same screen", task.notifications[0]["message"])

    def test_a_screen_stuck_briefly_is_left_to_upstream(self):
        """Upstream already clicks its way out from ten seconds, so a short spell is not worth a toast."""
        task = FakeTask()
        task._last_change_time = time.time() - 15
        notify.stuck(lambda task: False)(task)
        self.assertEqual([], task.notifications)

    def test_one_stuck_screen_only_reports_once(self):
        """The handler runs every frame, so without this it would notify several times a second."""
        task = FakeTask()
        task._last_change_time = time.time() - (notify.STUCK_SECONDS + 5)
        handler = notify.stuck(lambda task: False)
        for _ in range(5):
            handler(task)
        self.assertEqual(1, len(task.notifications))

    def test_a_screen_that_starts_moving_again_can_report_next_time(self):
        task = FakeTask()
        handler = notify.stuck(lambda task: False)
        task._last_change_time = time.time() - (notify.STUCK_SECONDS + 5)
        handler(task)
        task._last_change_time = time.time()
        handler(task)
        task._last_change_time = time.time() - (notify.STUCK_SECONDS + 5)
        handler(task)
        self.assertEqual(2, len(task.notifications))

    def test_a_task_with_no_stuck_detection_is_left_alone(self):
        task = FakeTask()
        notify.stuck(lambda task: False)(task)
        self.assertEqual([], task.notifications)

    def test_the_wrapped_handler_keeps_its_answer(self):
        """Position in the handler list is the priority scheme, so the return value decides what runs next."""
        self.assertTrue(notify.stuck(lambda task: True)(FakeTask()))
        self.assertFalse(notify.stuck(lambda task: False)(FakeTask()))

    def test_the_replacement_is_named_apart_from_the_original(self):
        """`handlers.replace` matches by name, so a wrapper named after the original would wrap itself."""
        self.assertEqual("handle_stuck_log_announcing", notify.stuck(lambda task: False).__name__)
        self.assertEqual("handle_expedition_result_announcing", notify.finishing(lambda task: False).__name__)


class ModeOnScreen:
    """A mode looking at one screen, recording its notices and whether it was stopped."""

    def __init__(self, texts):
        self.name = "自动卡厄思模式"
        self.width, self.height = WIDTH, HEIGHT
        self.all_texts = [FakeBox(text, x, y) for text, x, y in texts]
        self.logged = []
        self.notifications = []
        self.stops = 0

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.stops += 1


def mode(class_name, texts):
    """Put a mode of the given class name in front of a screen, since the notice is chosen by the mode's class.

    Args:
        class_name: The mode's class name, such as `ChaosMode`.
        texts: `(text, x, y)` triples, placed as fractions of the screen.

    Returns:
        The task.
    """
    return type(class_name, (ModeOnScreen,), {})(texts)


class TestLobbyStop(unittest.TestCase):
    """Chaos and Sortie stop on the Lobby, as upstream designed, and now say in English what to do instead."""

    def handler(self):
        return notify.lobby_stop(utils)(utils.handle_non_battle_page)

    def test_chaos_and_sortie_each_say_where_they_start(self):
        for class_name in ("ChaosMode", "SortieMode"):
            with self.subTest(class_name):
                task = mode(class_name, LOBBY)
                self.assertTrue(self.handler()(task))
                self.assertEqual(1, task.stops)
                self.assertEqual([notify.LOBBY_STOPS[class_name]], task.notifications)
                self.assertIn(notify.LOBBY_STOPS[class_name], task.logged)

    def test_the_words_are_english_and_name_what_to_open(self):
        self.assertIn("Open Chaos Manifestation in the game", notify.LOBBY_STOPS["ChaosMode"])
        self.assertIn("Open Sortie in the game", notify.LOBBY_STOPS["SortieMode"])
        for message in notify.LOBBY_STOPS.values():
            self.assertTrue(message.isascii())

    def test_story_keeps_its_silent_stop(self):
        task = mode("StoryMode", LOBBY)
        self.assertTrue(self.handler()(task))
        self.assertEqual(1, task.stops)
        self.assertEqual([], task.notifications)

    def test_the_rescue_and_ark_city_stops_stay_as_they_were(self):
        for label, texts in (("Rescue", RESCUE), ("Ark City", ARK_CITY)):
            with self.subTest(label):
                task = mode("ChaosMode", texts)
                self.assertTrue(self.handler()(task))
                self.assertEqual(1, task.stops)
                self.assertEqual([], task.notifications)

    def test_no_notice_unless_upstream_stops(self):
        """The notice follows upstream's stop rather than reading the screen for itself."""
        task = mode("ChaosMode", LOBBY)
        self.assertFalse(notify.lobby_stop(utils)(lambda task_: False)(task))
        self.assertEqual([], task.notifications)

    def test_only_the_story_button_brings_the_notice(self):
        # Another stop with some other box where the Story button sits, here the button's own English before the catalog.
        task = mode("ChaosMode", [("Story", 0.884, 0.156) if text == "故事" else (text, x, y) for text, x, y in LOBBY])
        self.assertTrue(notify.lobby_stop(utils)(lambda task_: True)(task))
        self.assertEqual([], task.notifications)

    def test_any_other_screen_is_left_alone(self):
        task = mode("ChaosMode", [entry for entry in LOBBY if entry[0] != "故事"])
        self.assertFalse(self.handler()(task))
        self.assertEqual(0, task.stops)
        self.assertEqual([], task.notifications)

    def test_every_mode_carrying_the_stop_gets_the_notice_once(self):
        stand_in = types.ModuleType("utils")
        stand_in.find_box_at_point = utils.find_box_at_point

        def handle_non_battle_page(task):
            return False
        stand_in.handle_non_battle_page = handle_non_battle_page
        modes = {}
        for name in ("utils_chaos", "utils_sortie", "utils_story"):
            modes[name] = types.ModuleType(name)
            modes[name].PAGE_HANDLERS = [handle_non_battle_page]
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        with mock.patch.dict(sys.modules, {"utils": stand_in, **modes}):
            try:
                for _ in range(INSTALLS):
                    notify.install_lobby_stop()
                installed = {name: module.PAGE_HANDLERS[0] for name, module in modes.items()}
            finally:
                for entries, before in saved:
                    entries[:] = before
        for name, handler in installed.items():
            with self.subTest(name):
                self.assertIs(stand_in.handle_non_battle_page, handler)
                self.assertEqual("handle_non_battle_page", handler.__name__)
                self.assertEqual(1, getattr(handler, handlers.WRAPS).count(notify.LOBBY_TAG))

    def test_the_notice_is_installed_on_every_task_load(self):
        registered = []
        with (mock.patch.object(notify, "_patched", False), mock.patch.object(notify, "register", registered.append),
              mock.patch.dict(sys.modules, {"ok.task.task": None})):
            notify.apply()
        self.assertIn(notify.install_lobby_stop, registered)


if __name__ == "__main__":
    unittest.main()
