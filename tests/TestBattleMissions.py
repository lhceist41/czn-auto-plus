"""Check that Story plays a chapter's open Battle Missions left to right and stops, pressing nothing, at anything else.

The screens are the boxes OCR read off the Story hub, the Battle Missions list, a mission's detail, formation, fight and
result, a lock popup and the growth tutorial, as the bot sees them once the catalog has mapped them, over the pixels cut
from the same captures. What Story must never do: tap a card it cannot name, start a mission a third time, act on a list
still settling, press through a lock or the tutorial, or press Next Mission.
"""

import sys
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
import utils_story  # noqa: E402

from src.en import battle_missions, story  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

IMAGES = REPO_ROOT / "tests" / "images"
INSTALLS = 3
START = 1_000.0

# The Story hub.
HUB = (("故事", 0.106, 0.048), ("N", 0.973, 0.031), ("故事", 0.331, 0.773), ("N", 0.452, 0.732),
       ("Act 1- Chapter 1, Episode 7", 0.269, 0.816), ("Battle Missions", 0.713, 0.773), ("Chapter 1 B2", 0.661, 0.816))
# The list on the tutorial's first visit, dimmed by its hint, with OCR reading B1's arrow as a trailing I.
LIST_TUTORIAL = (
    ("Battle Missions", 0.151, 0.046), ("Chapter1", 0.603, 0.04), ("N", 0.648, 0.023), ("Skip Tutorial", 0.88, 0.055),
    ("Safe trip, Captain. Don't worry too much", 0.249, 0.188), ("Black Rose", 0.165, 0.459), ("Batte Missions", 0.465, 0.437),
    ("N", 0.593, 0.461), ("Battle Missions", 0.73, 0.436), ("B1I", 0.563, 0.503), ("B2", 0.806, 0.503),
    ("0/18", 0.359, 0.932), ("NORMAL", 0.522, 0.933), ("HARD", 0.703, 0.932), ("ABYSS", 0.883, 0.932),
)
# The list after B1: B1 keeps its stars, the arrow has moved to B2, B3 is locked.
LIST_B2 = (
    ("Battle Missions", 0.151, 0.046), ("Chapter 1", 0.571, 0.040), ("N", 0.615, 0.023), ("Battle Missions", 0.200, 0.437),
    ("Battle Missions", 0.466, 0.438), ("N", 0.593, 0.462), ("Battle Missions", 0.731, 0.437), ("triggers", 0.029, 0.549),
    ("🌟🌟🌟", 0.174, 0.522), ("B1", 0.307, 0.504), ("🌟🌟🌟", 0.441, 0.522), ("B2", 0.566, 0.504), ("B3", 0.807, 0.504),
    ("3/18", 0.359, 0.932), ("NORMAL", 0.522, 0.933), ("HARD", 0.703, 0.932), ("ABYSS", 0.883, 0.932),
)
# The list after B3, scrolled by itself: B3 cleared, B4 and B5 locked until the story moves on.
LIST_CLEARED = (
    ("Battle Missions", 0.151, 0.046), ("Chapter 1", 0.470, 0.040), ("Battle Missions", 0.465, 0.437),
    ("Battle Missions", 0.730, 0.437), ("Battle", 0.967, 0.437), ("B3", 0.041, 0.503), ("B4", 0.541, 0.503),
    ("B5", 0.806, 0.505), ("9/18", 0.358, 0.932), ("NORMAL", 0.522, 0.933), ("HARD", 0.703, 0.932), ("ABYSS", 0.883, 0.932),
)
# B2's detail, open over the list, which still shows B2's arrow.
DETAIL_B2 = (
    ("Battle Missions", 0.151, 0.045), ("Chapter 1", 0.557, 0.039), ("Client information", 0.748, 0.144),
    ("Battle Missions", 0.082, 0.437), ("Battle Missions", 0.349, 0.435), ("Win the battle", 0.719, 0.441),
    ("B1", 0.191, 0.503), ("B2", 0.449, 0.505), ("Reward", 0.665, 0.733), ("3/18", 0.358, 0.932), ("NORMAL", 0.523, 0.932),
    ("进入", 0.817, 0.931),
)
# B2's formation: all three level labels read, Enter bottom right.
FORMATION_B2 = (
    ("主战员配置", 0.155, 0.045), ("Chapter 1. Black Rose", 0.765, 0.140), ("#B2 Battle Missions", 0.778, 0.188),
    ("推荐", 0.740, 0.253), ("LV.1", 0.909, 0.254), ("Monsters That Appear", 0.762, 0.313), ("Win the battle", 0.761, 0.493),
    ("等级", 0.058, 0.606), ("等级", 0.272, 0.606), ("等级", 0.485, 0.606), ("01", 0.485, 0.640),
    ("First Achievement Reward", 0.776, 0.706), ("15000 TB", 0.167, 0.806), ("24900 TB", 0.378, 0.806),
    ("15000TB", 0.596, 0.806), ("Preset", 0.143, 0.919), ("进入", 0.930, 0.913),
)
# B1's formation under the tutorial's dimming: one level label read of three.
FORMATION_B1 = (
    ("主战员配置", 0.156, 0.047), ("Chapter 1. Black Rose", 0.765, 0.141), ("#B1 Battle Missions", 0.778, 0.189), ("推荐", 0.74, 0.254),
    ("Monsters That Appear", 0.763, 0.314), ("Win the battle", 0.761, 0.494), ("等级", 0.271, 0.606),
    ("First Achievement Reward", 0.776, 0.705), ("15000 TB", 0.167, 0.807), ("15000 TB", 0.382, 0.808), ("15000 TB", 0.596, 0.807),
    ("Preset", 0.142, 0.919), ("进入", 0.93, 0.912),
)
# B3's formation with the forced growth tutorial over it.
FORMATION_GROWTH = (
    ("主战员配置", 0.155, 0.046), ("Skip Tutorial", 0.879, 0.055), ("#B3 Battle Missions", 0.778, 0.189),
    ("等级", 0.058, 0.606), ("等级", 0.272, 0.606), ("等级", 0.486, 0.606),
    ("Some Combatants do not meet the", 0.231, 0.748), ("Please go to the Agent details screen to", 0.247, 0.816),
    ("recommended level for this mission.", 0.235, 0.783), ("15000 TB", 0.597, 0.807), ("proceed with their growth.", 0.201, 0.850),
    ("Preset", 0.142, 0.919), ("进入", 0.930, 0.912),
)
# B4's lock popup.
LOCKED_B4 = (("Content locked", 0.502, 0.401), ("Clear Chapter 1, B3 Battle Missions", 0.347, 0.514),
             ("Clear Story Act 1 - Chapter 1 #09 [Faded Memories]", 0.411, 0.602), ("点击屏幕关闭窗口", 0.501, 0.935))
# B1's result.
RESULT_B1 = (
    ("Lv.06", 0.61, 0.114), ("+400", 0.868, 0.122), ("(800/1500)", 0.931, 0.122), ("MVP", 0.087, 0.2),
    ("Chapter 1. Black Rose", 0.713, 0.238), ("B1 Battle Missions", 0.693, 0.272), ("Win the battle", 0.662, 0.357),
    ("Win the battle within 15 turns", 0.71, 0.43), ("Win the battle within 12 turns", 0.711, 0.502), ("Reward", 0.606, 0.626),
    ("45", 0.615, 0.746), ("36,000", 0.779, 0.746), ("Next Mission", 0.693, 0.918), ("确认", 0.917, 0.917),
)
NEXT_MISSION = (0.693, 0.918)
CONFIRM = (0.917, 0.917)

# Where each crop in `tests/images/` was cut from, as `(top, left)` pixels of a 1080p capture.
CROPS = {
    "mission_list_tutorial": (500, 0), "mission_list_b2": (500, 0), "mission_list_cleared": (500, 0), "mission_detail_b2": (500, 0),
    "team_battle_clean": (625, 0), "team_battle_dimmed": (625, 0), "mission_result_buttons": (940, 1080),
    "battle_auto_off": (0, 1344), "battle_auto_on": (0, 1344), "battle_auto_off_dark": (0, 1344), "battle_auto_on_dark": (0, 1344),
    "story_bar_off": (0, 1344),
}
# Each formation slot's column in the formation bands, as pixel x ranges, for blanking one out.
SLOT_COLUMNS = ((0, 307), (326, 710), (730, 1114))
# The arrows on the two lists, read off the captures.
B1_ARROW = (0.581, 0.505)
B2_ARROW = (0.579, 0.505)
# Where Auto sits on a Battle Mission's bar.
BATTLE_AUTO = (0.830, 0.052)


def frame_with(*crops, empty=()):
    """Put crops of a capture back into an otherwise black frame.

    Args:
        *crops: Base names of crops in `tests/images/`, keys of `CROPS`.
        empty: Indexes of formation slots to paint over with the formation's grey, as a card with no level plate.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for crop in crops:
        patch = cv2.imread(str(IMAGES / f"{crop}.png"))
        top, left = CROPS[crop]
        frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
        for slot in empty:
            start, end = SLOT_COLUMNS[slot]
            frame[top:top + patch.shape[0], start:end] = (52, 52, 52)
    return frame


def replaced(texts, old, new):
    """Swap one box's text.

    Args:
        texts: `(name, x, y)` triples.
        old: The text to replace.
        new: What to put in its place, or None to drop the box.

    Returns:
        The triples with that box changed.
    """
    return tuple((new, x, y) if name == old else (name, x, y) for name, x, y in texts if not (name == old and new is None))


class StoryMode:
    """Story mode as its handlers see it: the screen, the input it sends, and its start and stop."""

    width, height = WIDTH, HEIGHT
    name = "StoryMode"

    def __init__(self):
        self.enabled = True
        self.all_texts = []
        self.frame = None
        self.config = {}
        self.taps = []
        self.logged = []
        self.notifications = []

    def show(self, texts, frame=None):
        """Put a screen in front of Story.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
            frame: The capture, or None.

        Returns:
            Story.
        """
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        # OCR places its boxes on whole pixels, which upstream slices the frame with.
        for box in self.all_texts:
            box.x, box.y = round(box.x), round(box.y)
        self.frame = frame
        return self

    def move_relative(self, x, y):
        pass

    def sleep(self, seconds):
        pass

    def click(self, x, y, after_sleep=0):
        self.taps.append((x, y))

    def click_box(self, box):
        self.taps.append(((box.x + box.width / 2) / self.width, (box.y + box.height / 2) / self.height))

    def find_feature(self, *args, **kwargs):
        return []

    def find_one(self, *args, **kwargs):
        return None

    def box_of_screen(self, *args, **kwargs):
        return None

    def _disable(self):
        self.enabled = False

    # As `apply` wraps `BaseTask.disable` in the app.
    disable = battle_missions.forgetting_missions(_disable)

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)


class Clocked(unittest.TestCase):
    """Runs Story on a clock the test moves, a second per pass as the app's run loop does."""

    def setUp(self):
        self.now = START
        patcher = mock.patch.object(battle_missions.time, "monotonic", lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.story = StoryMode()

    def passes(self, handler, texts, frame, count):
        """Show the same screen for several passes and run one handler on each.

        Args:
            handler: The handler under test.
            texts: The screen's boxes.
            frame: The screen's pixels.
            count: How many passes.

        Returns:
            What the handler answered on each pass.
        """
        answers = []
        for _ in range(count):
            if not self.story.enabled:
                break
            answers.append(handler(self.story.show(texts, frame)))
            self.now += 1
        return answers

    def assertTappedAt(self, point):
        self.assertEqual(1, len(self.story.taps))
        self.assertAlmostEqual(point[0], self.story.taps[0][0], delta=0.01)
        self.assertAlmostEqual(point[1], self.story.taps[0][1], delta=0.01)


class TestHub(Clocked):

    def test_the_hub_opens_battle_missions(self):
        self.assertTrue(battle_missions.handle_story_hub(self.story.show(HUB)))
        self.assertTappedAt((0.713, 0.773))
        self.assertTrue(self.story.enabled)

    def test_only_the_hub_is_tapped(self):
        """Without the hub's title or its card, and on every other screen, the hub tap declines."""
        for name, texts in (("no title", replaced(HUB, "故事", None)), ("no card", replaced(HUB, "Battle Missions", None)),
                            ("list", LIST_B2), ("detail", DETAIL_B2), ("formation", FORMATION_B2), ("result", RESULT_B1),
                            ("lock", LOCKED_B4)):
            with self.subTest(screen=name):
                self.assertFalse(battle_missions.handle_story_hub(self.story.show(texts)))
        self.assertEqual([], self.story.taps)

    def test_a_hub_that_does_not_open_the_list_stops_story(self):
        taps = battle_missions.HUB_TAPS
        self.assertEqual([True] * (taps + 1), self.passes(battle_missions.handle_story_hub, HUB, None, taps + 1))
        self.assertEqual(taps, len(self.story.taps))
        self.assertFalse(self.story.enabled)
        self.assertEqual([battle_missions.HUB_STOP.format(taps=taps)], self.story.notifications)

    def test_reaching_the_list_resets_the_hub_count(self):
        for _ in range(battle_missions.HUB_TAPS):
            self.assertTrue(battle_missions.handle_story_hub(self.story.show(HUB)))
        battle_missions.handle_mission_list(self.story.show(LIST_B2, frame_with("mission_list_b2")))
        self.assertTrue(battle_missions.handle_story_hub(self.story.show(HUB)))
        self.assertTrue(self.story.enabled)
        self.assertEqual(battle_missions.HUB_TAPS + 1, len(self.story.taps))


class TestList(Clocked):

    def test_story_starts_the_card_with_the_arrow_once_the_list_has_settled(self):
        for name, texts, crop, arrow, mission in (("tutorial", LIST_TUTORIAL, "mission_list_tutorial", B1_ARROW, "B1"),
                                                  ("after B1", LIST_B2, "mission_list_b2", B2_ARROW, "B2")):
            with self.subTest(screen=name):
                self.setUp()
                answers = self.passes(battle_missions.handle_mission_list, texts, frame_with(crop), 3)
                self.assertEqual([True, True, True], answers)
                self.assertTappedAt(arrow)
                self.assertEqual({mission: 1}, vars(self.story)[battle_missions.STARTS])
                self.assertTrue(self.story.enabled)

    def test_nothing_is_tapped_before_the_list_has_held_still(self):
        """A list still scrolling to the next card reads differently from pass to pass."""
        frame = frame_with("mission_list_b2")
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 2)
        self.assertEqual([], self.story.taps)
        self.passes(battle_missions.handle_mission_list, LIST_CLEARED, frame_with("mission_list_cleared"), 2)
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 2)
        self.assertEqual([], self.story.taps)
        self.assertTrue(self.story.enabled)

    def test_a_reading_left_for_a_while_starts_over(self):
        frame = frame_with("mission_list_b2")
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 2)
        self.now += battle_missions.GAP + 1
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 1)
        self.assertEqual([], self.story.taps)

    def test_a_list_with_no_open_card_stops_story_and_names_the_cards(self):
        answers = self.passes(battle_missions.handle_mission_list, LIST_CLEARED, frame_with("mission_list_cleared"), 5)
        self.assertEqual([True, True, True], answers)
        self.assertEqual([], self.story.taps)
        self.assertFalse(self.story.enabled)
        self.assertIn("no open mission is left on the list (cards read: B3, B4, B5)", self.story.notifications[0])

    def test_a_mission_is_started_twice_at_most(self):
        """The second start is the one retry after a loss; the third stops."""
        frame = frame_with("mission_list_b2")
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 3)
        self.now += battle_missions.GAP + 1
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 3)
        self.assertEqual(2, len(self.story.taps))
        self.now += battle_missions.GAP + 1
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 5)
        self.assertEqual(2, len(self.story.taps))
        self.assertFalse(self.story.enabled)
        self.assertIn("B2 was started 2 times this run and is still open", self.story.notifications[0])

    def test_a_card_not_labelled_b1_to_b6_is_left_alone(self):
        frame = frame_with("mission_list_b2")
        for name, texts, says in (("promotion", replaced(LIST_B2, "B2", "Promotion"), "reads 'Promotion'"),
                                  ("B7", replaced(LIST_B2, "B2", "B7"), "reads 'B7'"),
                                  ("unread", replaced(LIST_B2, "B2", None), "has no label Story could read")):
            with self.subTest(card=name):
                self.setUp()
                self.passes(battle_missions.handle_mission_list, texts, frame, 5)
                self.assertEqual([], self.story.taps)
                self.assertFalse(self.story.enabled)
                self.assertIn(says, self.story.notifications[0])
                self.assertIn("may be the Promotion Mission", self.story.notifications[0])

    def test_a_detail_open_over_the_list_is_left_to_enter(self):
        """The detail keeps the list's title, tab and B2's arrow; its Enter is `handle_enter`'s."""
        answers = self.passes(battle_missions.handle_mission_list, DETAIL_B2, frame_with("mission_detail_b2"), 4)
        self.assertEqual([False] * 4, answers)
        self.assertEqual([], self.story.taps)
        self.assertTrue(self.story.enabled)

    def test_screens_that_are_not_the_list_are_declined(self):
        frame = frame_with("mission_list_b2")
        for name, texts in (("no title", replaced(LIST_B2, "Battle Missions", None)), ("no tab", replaced(LIST_B2, "NORMAL", None)),
                            ("hub", HUB), ("formation", FORMATION_B2), ("result", RESULT_B1)):
            with self.subTest(screen=name):
                self.assertEqual([False] * 3, self.passes(battle_missions.handle_mission_list, texts, frame, 3))
        self.assertEqual([], self.story.taps)
        self.assertTrue(self.story.enabled)

    def test_labels_read_with_the_arrow_or_spaces_name_their_mission(self):
        for name, mission in (("B1I", "B1"), ("B 2", "B2"), ("b6", "B6"), ("B11", "B1"), ("B0", None), ("B7", None),
                              ("Promotion", None), ("", None), ("Battle Missions", None)):
            with self.subTest(label=name):
                self.assertEqual(mission, battle_missions.mission_of(name))

    def test_a_stop_ends_the_run_and_the_next_run_counts_afresh(self):
        frame = frame_with("mission_list_b2")
        self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 3)
        self.story.disable()
        for mark in battle_missions.MARKS:
            self.assertNotIn(mark, vars(self.story))


class TestStops(Clocked):

    def test_a_lock_popup_stops_story_with_its_unlock_text(self):
        self.assertTrue(battle_missions.handle_mission_stop(self.story.show(LOCKED_B4)))
        self.assertFalse(self.story.enabled)
        self.assertEqual(["Story stopped on a locked screen: Content locked (Clear Chapter 1, B3 Battle Missions; "
                          "Clear Story Act 1 - Chapter 1 #09 [Faded Memories])."], self.story.notifications)
        self.assertEqual([], self.story.taps)

    def test_the_growth_tutorial_stops_story_and_skip_tutorial_is_never_pressed(self):
        self.assertTrue(battle_missions.handle_mission_stop(self.story.show(FORMATION_GROWTH, frame_with("team_battle_clean"))))
        self.assertFalse(self.story.enabled)
        self.assertEqual([battle_missions.GROWTH_STOP], self.story.notifications)
        self.assertEqual([], self.story.taps)

    def test_ordinary_screens_pass_the_stops(self):
        for name, texts in (("hub", HUB), ("list", LIST_B2), ("detail", DETAIL_B2), ("formation", FORMATION_B2),
                            ("result", RESULT_B1)):
            with self.subTest(screen=name):
                self.assertFalse(battle_missions.handle_mission_stop(self.story.show(texts)))
        self.assertTrue(self.story.enabled)


class TestFormation(Clocked):

    def test_battle_mission_formations_count_as_full(self):
        for name, texts, crop in (("B2", FORMATION_B2, "team_battle_clean"), ("B1 dimmed", FORMATION_B1, "team_battle_dimmed")):
            with self.subTest(formation=name):
                self.assertFalse(story.handle_team_formation(self.story.show(texts, frame_with(crop))))
                self.assertTrue(self.story.enabled)

    def test_an_empty_slot_still_stops_story(self):
        texts = tuple(box for box in FORMATION_B2 if not (box[0] == "等级" and box[1] == 0.272))
        self.assertTrue(story.handle_team_formation(self.story.show(texts, frame_with("team_battle_clean", empty=(1,)))))
        self.assertFalse(self.story.enabled)
        self.assertIn("Team Formation has 2 of 3 combatants", self.story.notifications[0])


class TestBattleAuto(Clocked):

    def test_a_battle_missions_auto_is_turned_on_only_while_off(self):
        """It is drawn as crossed swords, which the dialogue's play icon does not match."""
        for crop, taps in (("battle_auto_off", 1), ("battle_auto_on", 0), ("battle_auto_off_dark", 1), ("battle_auto_on_dark", 0)):
            with self.subTest(crop=crop):
                self.story.taps.clear()
                self.assertTrue(story.turning_auto_on(lambda _: True)(self.story.show((), frame_with(crop))))
                self.assertEqual(taps, len(self.story.taps))
                for x, y in self.story.taps:
                    self.assertAlmostEqual(BATTLE_AUTO[0], x, delta=0.01)
                    self.assertAlmostEqual(BATTLE_AUTO[1], y, delta=0.02)

    def test_the_dialogue_icon_alone_misses_the_battle_missions_auto(self):
        self.assertIsNone(story.auto_off(frame_with("battle_auto_off")))
        self.assertIsNotNone(story.battle_auto_off(frame_with("battle_auto_off")))

    def test_off_the_battle_nothing_is_tapped(self):
        self.assertFalse(story.turning_auto_on(lambda _: False)(self.story.show((), frame_with("battle_auto_off"))))
        self.assertEqual([], self.story.taps)

    def test_the_battle_icon_does_not_match_the_dialogue_bar(self):
        """The dialogue bar keeps its own Auto and its own handler."""
        self.assertIsNone(story.button_off(frame_with("story_bar_off"), story.BATTLE_AUTO_IMAGE, story.AUTO_REGION))


def stand_in_story():
    """Build a copy of Story's own handler list under its module name, with the fork's handlers that matter here installed.

    Returns:
        The stand-in module.
    """
    module = types.ModuleType("utils_story")
    module.PAGE_HANDLERS = list(utils_story.PAGE_HANDLERS)
    return module


class StoryList(Clocked):
    """Runs Story's own handler list, with the missions installed into a copy of it."""

    def setUp(self):
        super().setUp()
        self.module = stand_in_story()
        held = sys.modules.get("utils_story")
        sys.modules["utils_story"] = self.module
        self.addCleanup(sys.modules.__setitem__, "utils_story", held)
        for _ in range(INSTALLS):
            battle_missions.install()

    def names(self):
        return [handler.__name__ for handler in self.module.PAGE_HANDLERS]

    def one_pass(self, texts, frame=None):
        """Run Story's list once over a screen, as its run loop does.

        Args:
            texts: The screen's boxes.
            frame: The screen's pixels.

        Returns:
            The name of the handler that claimed the frame, or None.
        """
        self.story.show(texts, frame)
        self.now += 1
        for handler in self.module.PAGE_HANDLERS:
            if handler(self.story):
                return handler.__name__
        return None


class TestStoryList(StoryList):

    def test_each_handler_goes_in_once_where_it_must(self):
        names = self.names()
        for name in ("handle_mission_stop", "handle_story_hub", "handle_mission_list"):
            self.assertEqual(1, names.count(name))
        self.assertLess(names.index("handle_mission_stop"), names.index("handle_center_confirm"))
        self.assertLess(names.index("handle_mission_stop"), names.index("handle_close_page"))
        self.assertLess(names.index("handle_mission_list"), names.index("handle_enter_story_or_battle"))
        self.assertLess(names.index("handle_story_hub"), names.index("handle_enter_story_or_battle"))
        self.assertLess(names.index("handle_enter"), names.index("handle_mission_list"))

    def test_no_other_mode_gets_them(self):
        """Even a mode holding every handler they go in front of."""
        module = types.ModuleType("utils_sortie")
        module.PAGE_HANDLERS = [utils.handle_center_confirm, utils.handle_enter, utils_story.handle_enter_story_or_battle]
        held = sys.modules.get("utils_sortie")
        sys.modules["utils_sortie"] = module
        self.addCleanup(sys.modules.__setitem__, "utils_sortie", held)
        battle_missions.install()
        self.assertEqual(["handle_center_confirm", "handle_enter", "handle_enter_story_or_battle"],
                         [handler.__name__ for handler in module.PAGE_HANDLERS])

    def test_the_result_goes_through_confirm_and_never_next_mission(self):
        self.assertEqual("handle_confirm", self.one_pass(RESULT_B1, frame_with("mission_result_buttons")))
        self.assertTappedAt(CONFIRM)
        self.assertNotAlmostEqual(NEXT_MISSION[0], self.story.taps[0][0], delta=0.1)

    def test_the_detail_and_formation_go_through_enter(self):
        for name, texts, crop in (("detail", DETAIL_B2, "mission_detail_b2"), ("formation", FORMATION_B2, "team_battle_clean")):
            with self.subTest(screen=name):
                self.story.taps.clear()
                self.assertEqual("handle_enter", self.one_pass(texts, frame_with(crop)))
                self.assertEqual(1, len(self.story.taps))

    def test_a_lock_popup_is_never_closed_and_tapped_again(self):
        self.assertEqual("handle_mission_stop", self.one_pass(LOCKED_B4))
        self.assertEqual([], self.story.taps)

    def test_the_list_never_reaches_storys_own_arrow_tap(self):
        """Story's entrance tap would take whatever play arrow it saw, the Promotion card's included."""
        texts = replaced(LIST_B2, "B2", "Promotion")
        claimed = {self.one_pass(texts, frame_with("mission_list_b2")) for _ in range(5)}
        self.assertEqual({"handle_mission_list"}, claimed)
        self.assertEqual([], self.story.taps)
        self.assertFalse(self.story.enabled)


if __name__ == "__main__":
    unittest.main()
