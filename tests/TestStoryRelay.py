"""Check that Story hands a chapter's Chaos stage to Chaos mode and gets the chapter back, and that the run spends nothing.

The screens are the boxes OCR read off the tutorial's own Chaos stage, Battle Missions, chapter map and lobby, as the
bot sees them once the catalog has mapped them. What the relay must never do: hand over on a battle or a short team,
hand a run the player started to Story, leave two modes running, or let a relayed run read a setting that spends.
"""

import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

import utils  # noqa: E402
from ok.task.TaskExecutor import TaskExecutor  # noqa: E402

from src.en import handlers, loot_cards, reobserve, shell, story, story_relay, stuck, stuck_stop, zero_system  # noqa: E402
from src.en.runs import forgetting  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

INSTALLS = 3
START = 1_000_000.0

# The Chaos stage's Team Formation (Eye of the Storm #05): OCR read the level label under two of the three filled cards.
CHAOS_FORMATION = (
    ("主战员配置", 0.155, 0.047), ("Chaos Missions", 0.741, 0.139), ("The Blue Pot", 0.744, 0.189), ("Rescue Renoa", 0.757, 0.253),
    ("推荐", 0.74, 0.577), ("等级", 0.906, 0.579), ("First Achievement Reward", 0.776, 0.636), ("Deep Trauma", 0.085, 0.722),
    ("等级", 0.056, 0.766), ("等级", 0.271, 0.766), ("存储数据保存上限", 0.789, 0.815), ("110pt 0", 0.946, 0.813),
    ("Preset", 0.143, 0.919), ("进入", 0.93, 0.912),
)
# Battle Missions B1's Team Formation: a full team, one label read, and no Chaos captions.
BATTLE_FORMATION = (
    ("主战员配置", 0.156, 0.047), ("Chapter 1. Black Rose", 0.765, 0.141), ("#B1 Battle Missions", 0.778, 0.189), ("推荐", 0.74, 0.254),
    ("Monsters That Appear", 0.763, 0.314), ("Win the battle", 0.761, 0.494), ("等级", 0.271, 0.606),
    ("First Achievement Reward", 0.776, 0.705), ("15000 TB", 0.167, 0.807), ("15000 TB", 0.382, 0.808), ("15000 TB", 0.596, 0.807),
    ("Preset", 0.142, 0.919), ("进入", 0.93, 0.912),
)
# Another Chaos stage's Team Formation: the same Chaos with another mission.
OTHER_CHAOS_FORMATION = tuple(("Find the Signal", x, y) if name == "Rescue Renoa" else (name, x, y) for name, x, y in CHAOS_FORMATION)
# The chapter map the Chaos run returned to, and the one Story started on.
MAP_AFTER_CHAOS = (
    ("Chapter 1", 0.467, 0.04), ("Return", 0.967, 0.436), ("Eye of the Storm", 0.562, 0.494), ("#05", 0.659, 0.494),
    ("The Blue Pot", 0.371, 0.631), ("Chaos Observation Results", 0.39, 0.683),
)
MAP_AT_START = (
    ("Chapter 1", 0.47, 0.04), ("A Promise Unkept", 0.472, 0.436), ("01", 0.024, 0.503), ("#02", 0.271, 0.502), ("#03", 0.535, 0.503),
)
# Battle Missions' list carries the chapter title in the same place, with B1 and B2 for nodes.
BATTLE_MISSIONS = (("Chapter1", 0.603, 0.04), ("B1", 0.25, 0.5), ("B2", 0.5, 0.5))
# The lobby, whose Story button upstream's stop reads.
LOBBY = (("等级", 0.054, 0.049), ("故事", 0.884, 0.156), ("Act 1-Chapter 1, Episode 7", 0.824, 0.194))

# Where the slot bands in `tests/images/` were cut from, as the pixel row at their top. Both span x 0-1114.
BANDS = {"team_chaos_dimmed": 798, "team_battle_dimmed": 625}
# Each slot's column in those bands, as pixel x ranges, for blanking one out.
SLOT_COLUMNS = ((0, 307), (326, 710), (730, 1114))
# How a relayed run must read each setting that spends, deletes or abandons the run, written out here rather than read
# from the module under test, so dropping a key there fails a test.
RELAYED_SETTINGS = {
    "Re-observe Bad Modifiers": False,
    "存储数据保存上限大于多少": 0,
    "领取奖励(只使用验证卡)": False,
    "治疗崩溃": False,
    "Codex Merge": "Never",
    "Enter End of Memory": False,
    "保留大于多少TB的存档": 0,
    "刷空档": False,
    "刷初始卡牌": "",
    "首层刷特定闪光": False,
    "只打第一层": False,
}
# A stand-in `utils_chaos`: it binds `utils`'s reader at import, as upstream's does, and its handlers read that binding.
UTILS_CHAOS = (
    "from utils import _get_config_value\n"
    "def heals_breakdowns(task):\n"
    "    return _get_config_value(task, '治疗崩溃', False)\n"
)
# More passes than a freeze needs to reach the stop, so a run loop that never ends fails instead of hanging.
PASS_LIMIT = 1000


def frame_with(band, empty=()):
    """Put a capture's band of level plates back into an otherwise black frame.

    Args:
        band: The base name of the crop in `tests/images/`, a key of `BANDS`.
        empty: Indexes of slots to paint over with the formation's grey, as a card with no level plate.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{band}.png"))
    top = BANDS[band]
    frame[top:top + patch.shape[0], :patch.shape[1]] = patch
    for slot in empty:
        left, right = SLOT_COLUMNS[slot]
        frame[top:top + patch.shape[0], left:right] = (52, 52, 52)
    return frame


def without_label(texts, x):
    """Drop the level label OCR read under one slot.

    Args:
        texts: `(name, x, y)` triples.
        x: The slot's label column.

    Returns:
        The triples without that slot's label.
    """
    return tuple(box for box in texts if not (box[0] == "等级" and abs(box[1] - x) < 0.01))


class Executor:
    """Holds the app's modes the way ok-script's executor does once `shell.to_task` has moved them to the one-time list."""

    # ok-script's own lookup, which searches both lists.
    get_task_by_class_name = TaskExecutor.get_task_by_class_name

    def __init__(self):
        self.trigger_tasks = []
        self.onetime_tasks = []

    def reset_scene(self):
        pass


class Mode:
    """A mode of the app, recording into a shared journal when it starts and stops."""

    width, height = WIDTH, HEIGHT
    trigger_interval = 0

    def __init__(self, journal, executor, saved=None):
        """Build a stopped mode.

        Args:
            journal: The list every mode records `(event, mode name)` into, in order.
            executor: The executor, whose one-time list this mode joins.
            saved: The mode's saved settings.
        """
        self.name = type(self).__name__
        self.journal = journal
        self.executor = executor
        executor.onetime_tasks.append(self)
        self.config = dict(saved or {})
        self.default_config = {}
        self.enabled = False
        self.all_texts = []
        self.frame = None
        self.logged = []
        self.notifications = []

    def show(self, texts, frame=None):
        """Put a screen in front of the mode.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
            frame: The capture, or None.

        Returns:
            The mode.
        """
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.frame = frame
        return self

    def enable(self):
        # What `stuck.restarting` does at every start, so a carried clock has to be put back afterwards.
        stuck.forget(self)
        self.enabled = True
        self.journal.append(("enable", self.name))

    def _disable(self):
        self.enabled = False
        self.journal.append(("disable", self.name))

    # As `apply` wraps `BaseTask.disable` in the app.
    disable = forgetting(story_relay.MARKS, _disable)

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)


class StoryMode(Mode):
    pass


class ChaosMode(Mode):
    pass


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


def names(module):
    """Read a mode's handler names in order.

    Args:
        module: The stand-in mode.

    Returns:
        A list of names.
    """
    return [handler.__name__ for handler in module.PAGE_HANDLERS]


class Modules:
    """Put stand-in modules in `sys.modules` under the real modes' names, and the real ones back afterwards."""

    def __init__(self, **modules):
        self.modules = modules
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


def module(name, handler_list, **attributes):
    """Build a stand-in mode module.

    Args:
        name: The module name.
        handler_list: Its `PAGE_HANDLERS`.
        **attributes: Anything else it carries.

    Returns:
        The module.
    """
    stand_in = types.ModuleType(name)
    stand_in.PAGE_HANDLERS = handler_list
    for key, value in attributes.items():
        setattr(stand_in, key, value)
    return stand_in


class Relay(unittest.TestCase):

    def setUp(self):
        self.journal = []
        executor = Executor()
        self.story = StoryMode(self.journal, executor)
        self.chaos = ChaosMode(self.journal, executor, saved={key: True for key in RELAYED_SETTINGS})
        self.story.enabled = True

    def relayed(self):
        """Hand the tutorial's Chaos stage over, and forget the hand-over's own journal lines."""
        self.story.show(CHAOS_FORMATION, frame_with("team_chaos_dimmed"))
        self.assertTrue(story_relay.handle_story_chaos_stage(self.story))
        self.journal.clear()


class TestHandOver(Relay):

    def test_a_full_chaos_formation_goes_to_chaos_mode_with_story_stopped_first(self):
        """Two modes enabled at once take turns on one screen, and Chaos's own start leaves Story running."""
        self.story.show(CHAOS_FORMATION, frame_with("team_chaos_dimmed"))
        self.assertTrue(story_relay.handle_story_chaos_stage(self.story))
        self.assertEqual([("disable", "StoryMode"), ("enable", "ChaosMode")], self.journal)
        self.assertFalse(self.story.enabled)
        self.assertTrue(self.chaos.enabled)
        self.assertIs(True, getattr(self.chaos, story_relay.RELAYED))

    def test_the_hand_over_finds_chaos_in_the_one_time_list_where_the_app_keeps_it(self):
        """`shell.to_task` moves every mode out of the trigger list at launch."""
        self.assertEqual([], self.story.executor.trigger_tasks)
        self.story.show(CHAOS_FORMATION, frame_with("team_chaos_dimmed"))
        self.assertTrue(story_relay.handle_story_chaos_stage(self.story))
        self.assertEqual([("disable", "StoryMode"), ("enable", "ChaosMode")], self.journal)
        self.assertEqual([], self.story.notifications)

    def test_a_battle_formation_is_left_to_story(self):
        self.story.show(BATTLE_FORMATION, frame_with("team_battle_dimmed"))
        self.assertFalse(story_relay.handle_story_chaos_stage(self.story))
        self.assertEqual([], self.journal)
        self.assertFalse(hasattr(self.chaos, story_relay.RELAYED))

    def test_a_formation_missing_either_chaos_caption_is_left_to_story(self):
        for caption in ("Chaos Missions", "存储数据保存上限"):
            with self.subTest(missing=caption):
                self.story.show([box for box in CHAOS_FORMATION if box[0] != caption], frame_with("team_chaos_dimmed"))
                self.assertFalse(story_relay.handle_story_chaos_stage(self.story))
                self.assertEqual([], self.journal)

    def test_a_short_chaos_team_is_stopped_by_story_and_never_handed_over(self):
        """The short-team stop runs first, and the hand-over would decline the frame even if it did not."""
        texts = without_label(CHAOS_FORMATION, 0.271)
        self.story.show(texts, frame_with("team_chaos_dimmed", empty=(1,)))
        self.assertFalse(story_relay.handle_story_chaos_stage(self.story))
        story_list = [story.handle_team_formation, story_relay.handle_story_chaos_stage]
        self.assertTrue(any(handler(self.story) for handler in story_list))
        self.assertEqual([("disable", "StoryMode")], self.journal)
        self.assertIn("Team Formation has 2 of 3 combatants", self.story.notifications[0])
        self.assertFalse(self.chaos.enabled)

    def test_without_chaos_mode_story_stops_instead_of_entering_a_run_it_cannot_play(self):
        self.story.executor.onetime_tasks.remove(self.chaos)
        self.story.show(CHAOS_FORMATION, frame_with("team_chaos_dimmed"))
        self.assertTrue(story_relay.handle_story_chaos_stage(self.story))
        self.assertEqual([("disable", "StoryMode")], self.journal)
        self.assertEqual([story_relay.NO_CHAOS], self.story.notifications)


class TestHandBack(Relay):

    def test_a_relayed_run_back_on_the_chapter_map_goes_to_story(self):
        self.relayed()
        for screen in (MAP_AFTER_CHAOS, MAP_AT_START):
            with self.subTest(screen=screen[0]):
                self.chaos.enabled, self.story.enabled = True, False
                setattr(self.chaos, story_relay.RELAYED, True)
                self.journal.clear()
                self.assertTrue(story_relay.handle_story_chapter_map(self.chaos.show(screen)))
                self.assertEqual([("disable", "ChaosMode"), ("enable", "StoryMode")], self.journal)
                self.assertFalse(hasattr(self.chaos, story_relay.RELAYED))

    def test_a_run_the_player_started_never_goes_to_story(self):
        self.chaos.enabled, self.story.enabled = True, False
        self.assertFalse(story_relay.handle_story_chapter_map(self.chaos.show(MAP_AFTER_CHAOS)))
        self.assertEqual([], self.journal)

    def test_once_a_relayed_run_stops_the_next_start_is_the_players_own(self):
        """Any stop drops the relay, so a run the player starts later neither returns to Story nor reads the relayed settings."""
        self.relayed()
        self.chaos.disable()
        self.chaos.enable()
        self.journal.clear()
        self.assertFalse(story_relay.handle_story_chapter_map(self.chaos.show(MAP_AFTER_CHAOS)))
        self.assertEqual([], self.journal)
        reader = story_relay.relayed_settings(utils._get_config_value)
        self.assertIs(True, reader(self.chaos, reobserve.REOBSERVE, True))

    def test_screens_that_are_not_the_chapter_map_keep_the_run_with_chaos(self):
        self.relayed()
        for screen in (BATTLE_MISSIONS, CHAOS_FORMATION, LOBBY, MAP_AFTER_CHAOS[:1], MAP_AFTER_CHAOS[3:4]):
            with self.subTest(screen=screen[0][0]):
                self.assertFalse(story_relay.handle_story_chapter_map(self.chaos.show(screen)))
        self.assertEqual([], self.journal)

    def test_the_lobby_during_a_relayed_run_stops_chaos_and_leaves_story_off(self):
        """Upstream's lobby stop ends the run, and with it the relay."""
        self.relayed()
        chaos_list = [story_relay.handle_story_chapter_map, utils.handle_non_battle_page]
        self.assertTrue(any(handler(self.chaos.show(LOBBY)) for handler in chaos_list))
        self.assertEqual([("disable", "ChaosMode")], self.journal)
        self.assertFalse(self.story.enabled)
        self.assertFalse(hasattr(self.chaos, story_relay.RELAYED))

    def test_without_story_mode_the_run_stops_on_the_chapter_map(self):
        self.relayed()
        self.chaos.executor.onetime_tasks.remove(self.story)
        self.assertTrue(story_relay.handle_story_chapter_map(self.chaos.show(MAP_AFTER_CHAOS)))
        self.assertEqual([("disable", "ChaosMode")], self.journal)
        self.assertEqual([story_relay.NO_STORY], self.chaos.notifications)


class TestStuckClockAcrossTheSwitch(Relay):
    """A freeze that spans the switch stops within five minutes in total, with each mode started by the app's own run loop."""

    def setUp(self):
        super().setUp()
        self.now = START
        patcher = mock.patch("time.time", lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

        def is_frame_stuck(task, stuck_threshold_seconds=30):
            # Seeds itself from absence as upstream does, and never sees the picture change.
            if "_last_change_time" not in vars(task):
                task._last_change_time = time.time()
            return time.time() - task._last_change_time >= stuck_threshold_seconds

        stop = stuck_stop.stopping(types.SimpleNamespace(is_frame_stuck=is_frame_stuck))
        modules = Modules(
            utils_story=module("utils_story", [stop, named("handle_team_formation"), named("handle_enter")]),
            utils_chaos=module("utils_chaos", [stop, named("handle_auto_stop"), named("handle_enter")]),
            utils=module("utils", [], _get_config_value=utils._get_config_value),
        )
        self.loaded = modules.__enter__()
        self.addCleanup(modules.__exit__, None, None, None)
        for _ in range(INSTALLS):
            story_relay.install()
        self.formation = frame_with("team_chaos_dimmed")
        self.passes = 0

    def run_loop(self, mode, screen):
        """Start a mode as the app does: through the run loop `shell.to_task` gives it, which starts the mode again first.

        Args:
            mode: The mode, already enabled as the relay leaves it.
            screen: Takes how many passes the test has run and returns the `(texts, frame)` on screen.
        """
        handler_list = self.loaded["utils_story" if mode is self.story else "utils_chaos"].PAGE_HANDLERS

        def one_pass():
            self.passes += 1
            self.assertLess(self.passes, PASS_LIMIT)
            mode.show(*screen(self.passes))
            for handler in handler_list:
                if handler(mode):
                    break
            self.now += 1

        mode.run = one_pass
        shell.looping(mode)()

    def test_a_freeze_that_spans_the_hand_over_stops_within_five_minutes_in_total(self):
        """Chaos's clock is cleared twice in the app, by the relay's start and the run loop's, and must still count Story's frozen time."""
        self.run_loop(self.story, lambda passes: (CHAOS_FORMATION, self.formation) if passes > 200 else ((), None))
        self.assertTrue(self.chaos.enabled)
        self.run_loop(self.chaos, lambda passes: (CHAOS_FORMATION, self.formation))
        self.assertFalse(self.chaos.enabled)
        self.assertEqual([stuck_stop.MESSAGE], self.chaos.notifications)
        self.assertLessEqual(self.now - START, stuck_stop.STOP_SECONDS + 1)

    def test_a_freeze_that_spans_the_hand_back_stops_within_five_minutes_in_total(self):
        self.relayed()
        self.run_loop(self.chaos, lambda passes: (MAP_AFTER_CHAOS, None) if passes > 200 else ((), None))
        self.assertTrue(self.story.enabled)
        self.run_loop(self.story, lambda passes: (MAP_AFTER_CHAOS, None))
        self.assertFalse(self.story.enabled)
        self.assertEqual([stuck_stop.MESSAGE], self.story.notifications)
        self.assertLessEqual(self.now - START, stuck_stop.STOP_SECONDS + 1)


class TestSameStageAgain(Relay):
    """A run that ends on the chapter map without clearing its stage would send Story back into the same stage forever."""

    def handed_back(self):
        """Hand the tutorial's Chaos stage over and back, and forget both hand-overs' journal lines."""
        self.relayed()
        self.assertTrue(story_relay.handle_story_chapter_map(self.chaos.show(MAP_AFTER_CHAOS)))
        self.journal.clear()

    def test_the_same_stage_after_a_hand_back_stops_story_without_handing_it_over(self):
        respaced = tuple(("TheBlue Pot", x, y) if name == "The Blue Pot" else (name, x, y) for name, x, y in CHAOS_FORMATION)
        for screen in (CHAOS_FORMATION, respaced):
            with self.subTest(name=screen[2][0]):
                self.story.enabled = True
                self.handed_back()
                self.assertTrue(story_relay.handle_story_chaos_stage(self.story.show(screen, frame_with("team_chaos_dimmed"))))
                self.assertEqual([("disable", "StoryMode")], self.journal)
                self.assertEqual([story_relay.SAME_STAGE], self.story.notifications[-1:])
                self.assertFalse(self.chaos.enabled)
                self.assertFalse(hasattr(self.chaos, story_relay.RELAYED))

    def test_another_stage_after_a_hand_back_goes_to_chaos_mode(self):
        self.handed_back()
        self.assertTrue(story_relay.handle_story_chaos_stage(self.story.show(OTHER_CHAOS_FORMATION, frame_with("team_chaos_dimmed"))))
        self.assertEqual([("disable", "StoryMode"), ("enable", "ChaosMode")], self.journal)
        self.assertEqual([], self.story.notifications)

    def test_a_story_the_player_starts_again_hands_the_same_stage_over_once_more(self):
        """Any stop forgets the stage, so pressing Start is how the player asks for another try."""
        self.handed_back()
        self.story.disable()
        self.story.enable()
        self.journal.clear()
        self.assertTrue(story_relay.handle_story_chaos_stage(self.story.show(CHAOS_FORMATION, frame_with("team_chaos_dimmed"))))
        self.assertEqual([("disable", "StoryMode"), ("enable", "ChaosMode")], self.journal)


class TestRelayedSettings(unittest.TestCase):
    """A relayed run reads every setting that spends, deletes or abandons the run as off, and the saved file never changes."""

    def setUp(self):
        self.task = ChaosMode([], Executor(), saved={
            reobserve.REOBSERVE: True, reobserve.SAVE_LIMIT_KEY: 120, loot_cards.CLAIMING: True, "治疗崩溃": True,
            zero_system.CODEX_MERGE: zero_system.CHAOS_MERGE, zero_system.MAX_MERGES: 3, "Enter End of Memory": True,
            "保留大于多少TB的存档": 62000, "刷空档": True, "刷初始卡牌": "Sword", "首层刷特定闪光": True, "只打第一层": True,
            reobserve.MODIFIER_BLACKLIST: ["Plague"], "游戏语言": "English",
        })
        self.saved = dict(self.task.config)
        self.reader = story_relay.relayed_settings(utils._get_config_value)
        self.chaos_module = types.SimpleNamespace(_get_config_value=self.reader)

    def test_every_relayed_setting_reads_off_and_nothing_else_changes(self):
        self.assertEqual(RELAYED_SETTINGS, story_relay.RELAYED_SETTINGS)
        setattr(self.task, story_relay.RELAYED, True)
        for key, value in RELAYED_SETTINGS.items():
            with self.subTest(key=key):
                self.assertEqual(value, self.reader(self.task, key, True))
        self.assertEqual(["Plague"], self.reader(self.task, reobserve.MODIFIER_BLACKLIST, []))
        self.assertEqual("English", self.reader(self.task, "游戏语言", ""))
        self.assertEqual(self.saved, self.task.config)

    def test_a_run_story_did_not_start_reads_the_saved_settings(self):
        for key in RELAYED_SETTINGS:
            with self.subTest(key=key):
                self.assertEqual(self.saved[key], self.reader(self.task, key, None))

    def test_a_relayed_run_never_re_observes_for_event_currency(self):
        """The story Chaos offered a Storage Limit of 110 against the default minimum of 120, which re-observes on its own."""
        self.task.show((("Season Info Chaos", 0.19, 0.05), ("Save Data Storage Limit 110", 0.83, 0.40), ("[Plague 1] Decrease Max HP", 0.83, 0.45)))
        self.assertEqual(2, len(reobserve.reasons_to_reobserve(self.task, self.chaos_module)))
        setattr(self.task, story_relay.RELAYED, True)
        self.assertEqual([], reobserve.reasons_to_reobserve(self.task, self.chaos_module))

    def test_a_relayed_run_never_spends_a_loot_certification_card(self):
        """The Settlement only opens the claim dialog when the setting reads on, and no card is spent without the dialog."""
        seen = []
        chaos_module = types.ModuleType("utils_chaos")
        chaos_module._get_config_value = self.reader
        chaos_module.find_box_at_point = lambda task, x, y: None

        def settlement(task):
            seen.append(chaos_module._get_config_value(task, loot_cards.CLAIMING, False))
            return False

        self.task.node_status = {}
        wrapped = loot_cards.with_cards_only(settlement, chaos_module)
        wrapped(self.task)
        setattr(self.task, story_relay.RELAYED, True)
        wrapped(self.task)
        self.assertEqual([True, False], seen)

    def test_a_relayed_run_never_pays_for_a_zero_system_merge(self):
        hunt = {"broke": False, "merges": 0}
        self.assertTrue(zero_system.merges_left(self.task, hunt, self.chaos_module))
        setattr(self.task, story_relay.RELAYED, True)
        self.assertFalse(zero_system.merges_left(self.task, hunt, self.chaos_module))


class TestStoryStopsOffTheStory(Relay):

    def test_story_runs_the_lobby_stop_ahead_of_every_handler_that_taps(self):
        """A relay that ends in the lobby, or a Story started there, stops rather than tapping templates on it."""
        lobby_stop = named("handle_non_battle_page")
        modules = Modules(
            utils_story=module("utils_story", [named("handle_center_confirm"), named("handle_story_complete"), named("handle_enter_story_or_battle"), named("handle_enter")]),
            utils_chaos=module("utils_chaos", [named("handle_center_confirm"), named("handle_next_step"), lobby_stop]),
            utils=module("utils", [], handle_non_battle_page=lobby_stop),
            utils_sortie=module("utils_sortie", [named("handle_center_confirm"), lobby_stop]),
        )
        with modules as loaded:
            for _ in range(INSTALLS):
                story.install()
        self.assertEqual(["handle_fast_forward", "handle_center_confirm", "handle_non_battle_page", "handle_story_complete", "handle_enter_story_or_battle",
                          "handle_team_formation", "handle_enter"], names(loaded["utils_story"]))
        self.assertEqual(["handle_fast_forward", "handle_center_confirm", "handle_next_step", "handle_non_battle_page"], names(loaded["utils_chaos"]))

    def test_story_stops_in_the_lobby(self):
        self.assertTrue(utils.handle_non_battle_page(self.story.show(LOBBY)))
        self.assertEqual([("disable", "StoryMode")], self.journal)
        self.assertFalse(utils.handle_non_battle_page(self.story.show(MAP_AT_START)))


class TestInstall(unittest.TestCase):

    def lists(self):
        story_list = [named("stop_when_stuck"), named("handle_center_confirm"), named("handle_story_complete"), named("handle_team_formation"), named("handle_enter")]
        chaos_list = [named("handle_remote"), named("stop_when_stuck"), named("handle_auto_stop"), named("handle_save_target_member"), named("handle_enter")]
        reader = utils._get_config_value
        return Modules(
            utils_story=module("utils_story", story_list),
            utils_chaos=module("utils_chaos", chaos_list, _get_config_value=reader),
            utils=module("utils", [named("handle_center_confirm")], _get_config_value=reader),
            utils_sortie=module("utils_sortie", [named("handle_auto_stop"), named("handle_enter")], _get_config_value=reader),
        )

    def test_the_hand_over_follows_the_short_team_stop_and_the_hand_back_follows_the_stuck_stop(self):
        with self.lists() as loaded:
            for _ in range(INSTALLS):
                story_relay.install()
        self.assertEqual(["restore_stuck_clock", "stop_when_stuck", "handle_center_confirm", "handle_story_complete", "handle_team_formation",
                          "handle_story_chaos_stage", "handle_enter"], names(loaded["utils_story"]))
        self.assertEqual(["handle_remote", "restore_stuck_clock", "stop_when_stuck", "handle_story_chapter_map", "handle_auto_stop", "handle_save_target_member",
                          "handle_enter"], names(loaded["utils_chaos"]))
        self.assertEqual(["handle_auto_stop", "handle_enter"], names(loaded["utils_sortie"]))

    def test_the_readers_chaos_reaches_carry_the_relayed_settings_once(self):
        with self.lists() as loaded:
            for _ in range(INSTALLS):
                story_relay.install()
        for name in ("utils", "utils_chaos"):
            with self.subTest(module=name):
                reader = loaded[name]._get_config_value
                self.assertEqual((story_relay.TAG,), getattr(reader, handlers.WRAPS))
                task = ChaosMode([], Executor(), saved={reobserve.REOBSERVE: True})
                self.assertIs(True, reader(task, reobserve.REOBSERVE, True))
                setattr(task, story_relay.RELAYED, True)
                self.assertIs(False, reader(task, reobserve.REOBSERVE, True))
        self.assertIs(utils._get_config_value, loaded["utils_sortie"]._get_config_value)

    def test_a_chaos_handler_reads_the_relayed_settings_through_its_own_import(self):
        """Upstream's `utils_chaos` binds `utils`'s reader at import, before any install runs, so wrapping `utils` alone would miss it."""
        with self.lists() as loaded:
            chaos_module = loaded["utils_chaos"]
            exec(UTILS_CHAOS, vars(chaos_module))
            for _ in range(INSTALLS):
                story_relay.install()
            task = ChaosMode([], Executor(), saved={"治疗崩溃": True})
            self.assertIs(True, chaos_module.heals_breakdowns(task))
            setattr(task, story_relay.RELAYED, True)
            self.assertIs(False, chaos_module.heals_breakdowns(task))

    def test_every_stop_drops_the_relay(self):
        """Wrapped on `BaseTask.disable`, the one call every way a run ends goes through."""
        from ok.task.task import BaseTask

        original = BaseTask.disable
        stopped = []
        try:
            BaseTask.disable = lambda task: stopped.append(task)
            with mock.patch.object(story_relay, "_patched", False), mock.patch.object(story_relay, "register") as register:
                story_relay.apply()
            marks = (story_relay.RELAYED, story_relay.CARRIED, story_relay.STAGE, story_relay.RETURNED)
            task = types.SimpleNamespace(**{name: True for name in marks})
            BaseTask.disable(task)
        finally:
            BaseTask.disable = original
        self.assertEqual([task], stopped)
        self.assertEqual({}, vars(task))
        register.assert_called_once_with(story_relay.install)


if __name__ == "__main__":
    unittest.main()
