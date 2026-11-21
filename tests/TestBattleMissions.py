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
# ABYSS's lock popup, with OCR reading two icons as text beside the unlock line.
LOCKED_ABYSS = (("日", 0.500, 0.330), ("Content locked", 0.502, 0.446), ("▲", 0.799, 0.481),
                ("Clear Chapter 3 Hard, B6 Battle Missions", 0.369, 0.560), ("D", 0.771, 0.559), ("点击屏幕关闭窗口", 0.501, 0.935))
# The list after B3 under the window that offers the next story's tutorial: no card label reads through it.
LIST_POPUP = (
    ("Battle Missions", 0.151, 0.046), ("Chapter1", 0.536, 0.040), ("N", 0.973, 0.030), ("A Promise Renewed", 0.501, 0.465),
    ("You can progress through a new story.", 0.499, 0.510), ("Proceed with Tutorial", 0.505, 0.636), ("9/18", 0.359, 0.931),
    ("NORMAL", 0.522, 0.932), ("HARD", 0.703, 0.933), ("日", 0.773, 0.933), ("ABYSS", 0.883, 0.933), ("日", 0.953, 0.933),
)
# B1's result.
RESULT_B1 = (
    ("Lv.06", 0.61, 0.114), ("+400", 0.868, 0.122), ("(800/1500)", 0.931, 0.122), ("MVP", 0.087, 0.2),
    ("Chapter 1. Black Rose", 0.713, 0.238), ("B1 Battle Missions", 0.693, 0.272), ("Win the battle", 0.662, 0.357),
    ("Win the battle within 15 turns", 0.71, 0.43), ("Win the battle within 12 turns", 0.711, 0.502), ("Reward", 0.606, 0.626),
    ("45", 0.615, 0.746), ("36,000", 0.779, 0.746), ("Next Mission", 0.693, 0.918), ("确认", 0.917, 0.917),
)
# A story chapter's node panel: its Enter where a mission's detail has one, and the same play arrow on its node.
CHAPTER_NODE = (
    ("故事", 0.106, 0.047), ("Chapter 1", 0.418, 0.040), ("#08", 0.697, 0.176), ("I hear Rei has come back to us.", 0.739, 0.333),
    ("The Reason We Fight", 0.365, 0.436), ("#07", 0.032, 0.504), ("#08", 0.419, 0.504), ("Reward", 0.665, 0.731),
    ("28,000", 0.907, 0.854), ("进入", 0.817, 0.931),
)
NEXT_MISSION = (0.693, 0.918)
CONFIRM = (0.917, 0.917)

# Where each crop in `tests/images/` was cut from, as `(top, left)` pixels of a 1080p capture.
CROPS = {
    "mission_list_tutorial": (500, 0), "mission_list_b2": (500, 0), "mission_list_cleared": (500, 0), "mission_detail_b2": (500, 0),
    "team_battle_clean": (625, 0), "team_battle_dimmed": (625, 0), "mission_result_buttons": (940, 1080),
    "battle_auto_off": (0, 1344), "battle_auto_on": (0, 1344), "battle_auto_off_dark": (0, 1344), "battle_auto_on_dark": (0, 1344),
    "story_bar_off": (0, 1344), "mission_tabs_normal": (960, 0), "mission_tabs_tutorial": (960, 0), "mission_tabs_popup": (960, 0),
}
# The difficulty tabs under each list crop, NORMAL selected: plain, under the tutorial's dimming, and under a window.
TAB_ROWS = {"mission_list_tutorial": "mission_tabs_tutorial", "mission_list_b2": "mission_tabs_normal",
            "mission_list_cleared": "mission_tabs_normal", "mission_detail_b2": "mission_tabs_normal"}
# Each tab's pill as pixel x ranges of equal width, centred on its caption.
PILLS = {"NORMAL": (830, 1175), "HARD": (1178, 1523), "ABYSS": (1523, 1868)}
TABS_TOP, TABS_BOTTOM = 960, 1060
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
    for crop in crops + tuple(TAB_ROWS[crop] for crop in crops if crop in TAB_ROWS):
        patch = cv2.imread(str(IMAGES / f"{crop}.png"))
        top, left = CROPS[crop]
        frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
        for slot in empty:
            start, end = SLOT_COLUMNS[slot]
            frame[top:top + patch.shape[0], start:end] = (52, 52, 52)
    return frame


def pills_moved(frame, source, target, swap=True):
    """Paint one tab's pill over another's, as a list on a tab no capture shows.

    Synthetic: HARD and ABYSS are locked on the account the captures come from, so no capture has them selected.
    Swapping NORMAL's selected pill with theirs draws them the way the game draws NORMAL selected.

    Args:
        frame: A frame whose tab row came from a capture.
        source: The pill to copy, such as "NORMAL".
        target: The pill to paint over.
        swap: Whether `target`'s pill goes to `source`'s place in turn, or `source` keeps its own.

    Returns:
        A copy of the frame with the pills moved.
    """
    frame = frame.copy()
    (from_left, from_right), (to_left, to_right) = PILLS[source], PILLS[target]
    moved = frame[TABS_TOP:TABS_BOTTOM, from_left:from_right].copy()
    if swap:
        frame[TABS_TOP:TABS_BOTTOM, from_left:from_right] = frame[TABS_TOP:TABS_BOTTOM, to_left:to_right]
    frame[TABS_TOP:TABS_BOTTOM, to_left:to_right] = moved
    return frame


def without_tabs(frame, pill=None):
    """Black out a frame's tab row, or one pill of it.

    Args:
        frame: A frame with a tab row.
        pill: The one pill to black out, such as "HARD", or None for the whole row.

    Returns:
        A copy with nothing drawn there.
    """
    frame = frame.copy()
    left, right = PILLS[pill] if pill else (0, WIDTH)
    frame[TABS_TOP:TABS_BOTTOM, left:right] = 0
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

    def test_a_window_over_the_list_is_named_when_no_card_reads(self):
        answers = self.passes(battle_missions.handle_mission_list, LIST_POPUP, frame_with("mission_tabs_popup"), 5)
        self.assertEqual([True, True, True], answers)
        self.assertEqual([], self.story.taps)
        self.assertFalse(self.story.enabled)
        self.assertEqual(["Battle Missions: a window covers the list (A Promise Renewed; You can progress through a new story.; "
                          "Proceed with Tutorial), so no card could be read. Story stopped."], self.story.notifications)

    def test_a_list_that_reads_its_cards_is_not_taken_for_a_window(self):
        """A stray line read in the middle of the list leaves the stop naming the cards it read."""
        texts = LIST_CLEARED + (("Chapter 1 complete", 0.500, 0.650),)
        self.passes(battle_missions.handle_mission_list, texts, frame_with("mission_list_cleared"), 5)
        self.assertFalse(self.story.enabled)
        self.assertIn("no open mission is left on the list (cards read: B3, B4, B5)", self.story.notifications[0])

    def test_a_list_whose_labels_do_not_read_is_not_taken_for_a_window(self):
        """Its card captions, the one-letter marks and the star rows sit where a window would write."""
        texts = tuple(box for box in LIST_B2 if box[0] not in ("B1", "B2", "B3"))
        self.passes(battle_missions.handle_mission_list, texts, frame_with("mission_list_cleared"), 5)
        self.assertFalse(self.story.enabled)
        self.assertIn("no open mission is left on the list (cards read: none)", self.story.notifications[0])


class TestTabs(Clocked):
    """Story plays the NORMAL tab only, and stops on any other or on a tab row it cannot read."""

    def test_the_selected_tab_is_read_off_its_pill(self):
        normal = frame_with("mission_list_b2")
        for name, frame, tab in (("NORMAL", normal, "NORMAL"), ("NORMAL dimmed", frame_with("mission_list_tutorial"), "NORMAL"),
                                 ("NORMAL under a window", frame_with("mission_tabs_popup"), "NORMAL"),
                                 ("HARD", pills_moved(normal, "NORMAL", "HARD"), "HARD"),
                                 ("ABYSS", pills_moved(normal, "NORMAL", "ABYSS"), "ABYSS"),
                                 ("HARD dimmed", pills_moved(frame_with("mission_list_tutorial"), "NORMAL", "HARD"), "HARD"),
                                 ("none selected", pills_moved(normal, "HARD", "NORMAL", swap=False), None),
                                 ("two selected", pills_moved(normal, "NORMAL", "HARD", swap=False), None),
                                 ("HARD pill blacked out", without_tabs(normal, "HARD"), None),
                                 ("tab row blacked out", without_tabs(normal), None), ("black", np.zeros_like(normal), None),
                                 ("no frame", None, None)):
            with self.subTest(tabs=name):
                self.assertEqual(tab, battle_missions.selected_tab(frame))

    def test_a_list_on_hard_or_abyss_stops_story_with_nothing_pressed(self):
        """B2's arrow and label are on the list, so only the tab keeps Story from starting it."""
        for tab in ("HARD", "ABYSS"):
            with self.subTest(tab=tab):
                self.setUp()
                frame = pills_moved(frame_with("mission_list_b2"), "NORMAL", tab)
                answers = self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 5)
                self.assertEqual([True, True, True], answers)
                self.assertEqual([], self.story.taps)
                self.assertFalse(self.story.enabled)
                self.assertEqual([f"Battle Missions: the {tab} tab is selected and Story plays NORMAL only, so it stopped. "
                                  "Select NORMAL, then start Story again."], self.story.notifications)
                self.assertNotIn(battle_missions.STARTS, vars(self.story))

    def test_a_tab_row_story_cannot_read_stops_story_with_nothing_pressed(self):
        normal = frame_with("mission_list_b2")
        for name, frame in (("none selected", pills_moved(normal, "HARD", "NORMAL", swap=False)),
                            ("two selected", pills_moved(normal, "NORMAL", "HARD", swap=False)),
                            ("tab row blacked out", without_tabs(normal))):
            with self.subTest(tabs=name):
                self.setUp()
                self.passes(battle_missions.handle_mission_list, LIST_B2, frame, 5)
                self.assertEqual([], self.story.taps)
                self.assertFalse(self.story.enabled)
                self.assertIn("could not tell which difficulty tab is selected", self.story.notifications[0])

    def test_a_tab_read_for_a_moment_does_not_stop_story(self):
        """A reading of another tab that does not hold, as on a list still fading in, never stops Story."""
        normal = frame_with("mission_list_b2")
        self.passes(battle_missions.handle_mission_list, LIST_B2, pills_moved(normal, "NORMAL", "HARD"), 2)
        self.passes(battle_missions.handle_mission_list, LIST_B2, normal, 3)
        self.assertTrue(self.story.enabled)
        self.assertTappedAt(B2_ARROW)


class TestOffNormal(Clocked):
    """A list or detail on another tab is held and stopped even on a pass where OCR misses the list's title or caption."""

    def off_normal(self, crop, tab):
        frame = frame_with(crop)
        return without_tabs(frame) if tab is None else pills_moved(frame, "NORMAL", tab)

    def assertStoppedOn(self, tab, answers):
        self.assertTrue(all(answers))
        self.assertEqual([], self.story.taps)
        self.assertFalse(self.story.enabled)
        if tab is None:
            self.assertIn("could not tell which difficulty tab is selected", self.story.notifications[0])
        else:
            self.assertEqual([f"Battle Missions: the {tab} tab is selected and Story plays NORMAL only, so it stopped. "
                              "Select NORMAL, then start Story again."], self.story.notifications)

    def test_a_list_pass_ocr_did_not_fully_read_is_held_and_stopped_off_normal(self):
        for tab in ("HARD", "ABYSS", None):
            for name, texts in (("title missed", replaced(LIST_B2, "Battle Missions", None)),
                                ("NORMAL caption missed", replaced(LIST_B2, "NORMAL", None)),
                                ("only HARD read", (("HARD", 0.703, 0.932),)), ("only ABYSS read", (("ABYSS", 0.883, 0.932),))):
                with self.subTest(tab=tab, texts=name):
                    self.setUp()
                    answers = self.passes(battle_missions.handle_list_off_normal, texts, self.off_normal("mission_list_b2", tab), 5)
                    self.assertStoppedOn(tab, answers)

    def test_a_list_on_hard_or_abyss_with_no_line_read_is_known_by_its_arrow(self):
        for tab in ("HARD", "ABYSS"):
            with self.subTest(tab=tab):
                self.setUp()
                answers = self.passes(battle_missions.handle_list_off_normal, (), self.off_normal("mission_list_b2", tab), 5)
                self.assertStoppedOn(tab, answers)

    def test_a_detail_off_normal_is_held_and_stopped_before_enter(self):
        for tab in ("HARD", "ABYSS", None):
            for name, texts in (("read", DETAIL_B2), ("title missed", replaced(DETAIL_B2, "Battle Missions", None)),
                                ("NORMAL caption missed", replaced(DETAIL_B2, "NORMAL", None))):
                with self.subTest(tab=tab, texts=name):
                    self.setUp()
                    answers = self.passes(battle_missions.handle_detail_off_normal, texts,
                                          self.off_normal("mission_detail_b2", tab), 5)
                    self.assertStoppedOn(tab, answers)

    def test_a_detail_on_hard_with_only_enter_read_is_known_by_its_arrow(self):
        answers = self.passes(battle_missions.handle_detail_off_normal, (("进入", 0.817, 0.931),),
                              self.off_normal("mission_detail_b2", "HARD"), 5)
        self.assertStoppedOn("HARD", answers)

    def test_normal_is_left_as_it_was(self):
        for name, handler, texts, crop in (
                ("list, title missed", battle_missions.handle_list_off_normal, replaced(LIST_B2, "Battle Missions", None),
                 "mission_list_b2"),
                ("list, caption missed", battle_missions.handle_list_off_normal, replaced(LIST_B2, "NORMAL", None), "mission_list_b2"),
                ("list, dimmed", battle_missions.handle_list_off_normal, replaced(LIST_TUTORIAL, "NORMAL", None),
                 "mission_list_tutorial"),
                ("detail", battle_missions.handle_detail_off_normal, DETAIL_B2, "mission_detail_b2")):
            with self.subTest(screen=name):
                self.assertEqual([False] * 3, self.passes(handler, texts, frame_with(crop), 3))
        self.assertEqual([], self.story.taps)
        self.assertTrue(self.story.enabled)

    def test_screens_that_are_not_battle_missions_are_declined(self):
        """A chapter node shows the same arrow and Enter, and lobby, Chaos and rescue screens read as HARD or ABYSS."""
        unreadable = without_tabs(frame_with("mission_list_b2"))
        hard_row = pills_moved(frame_with("mission_tabs_normal"), "NORMAL", "HARD")
        for name, texts, frame in (("chapter node", CHAPTER_NODE, unreadable), ("HARD read, no arrow", HUB, hard_row),
                                   ("formation", FORMATION_B2, hard_row), ("result", RESULT_B1, hard_row)):
            for handler in (battle_missions.handle_list_off_normal, battle_missions.handle_detail_off_normal):
                with self.subTest(screen=name, handler=handler.__name__):
                    self.assertEqual([False] * 3, self.passes(handler, texts, frame, 3))
        self.assertEqual([], self.story.taps)
        self.assertTrue(self.story.enabled)

    def test_a_detail_without_enter_is_left_to_the_list(self):
        texts = replaced(DETAIL_B2, "进入", None)
        frame = self.off_normal("mission_detail_b2", "HARD")
        self.assertEqual([False] * 3, self.passes(battle_missions.handle_detail_off_normal, texts, frame, 3))

    def test_a_reading_that_gives_way_to_normal_counts_afresh(self):
        """A detail still fading in reads no tab for a moment; once NORMAL reads, a later moment like it starts over."""
        normal = frame_with("mission_detail_b2")
        self.passes(battle_missions.handle_detail_off_normal, DETAIL_B2, without_tabs(normal), 2)
        self.passes(battle_missions.handle_detail_off_normal, DETAIL_B2, normal, 1)
        self.assertEqual([True], self.passes(battle_missions.handle_detail_off_normal, DETAIL_B2, without_tabs(normal), 1))
        self.assertTrue(self.story.enabled)
        self.assertEqual([], self.story.taps)


class TestStops(Clocked):

    def test_a_lock_popup_stops_story_with_its_unlock_text(self):
        self.assertTrue(battle_missions.handle_mission_stop(self.story.show(LOCKED_B4)))
        self.assertFalse(self.story.enabled)
        self.assertEqual(["Story stopped on a locked screen: Content locked (Clear Chapter 1, B3 Battle Missions; "
                          "Clear Story Act 1 - Chapter 1 #09 [Faded Memories])."], self.story.notifications)
        self.assertEqual([], self.story.taps)

    def test_the_lock_message_leaves_out_icons_read_as_text(self):
        self.assertTrue(battle_missions.handle_mission_stop(self.story.show(LOCKED_ABYSS)))
        self.assertEqual(["Story stopped on a locked screen: Content locked (Clear Chapter 3 Hard, B6 Battle Missions)."],
                         self.story.notifications)

    def test_content_locked_outside_the_popup_band_is_no_lock(self):
        """The popup's caption reads at y 0.401 and 0.446; the same words elsewhere, as on a tile, stop nothing."""
        for name, point in (("below", (0.502, 0.48)), ("above", (0.502, 0.28)), ("left", (0.15, 0.40)), ("right", (0.85, 0.40))):
            with self.subTest(place=name):
                self.assertFalse(battle_missions.handle_mission_stop(self.story.show((("Content locked",) + point,) + LIST_B2)))
        self.assertTrue(self.story.enabled)
        self.assertEqual([], self.story.notifications)

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

    def with_arrow_feature(self, point):
        """Have upstream's `enterbattle` template find a play arrow, as it does on the list at 0.99.

        Args:
            point: The arrow's centre as screen fractions.
        """
        arrow = FakeBox("enterbattle", *point, width=30, height=37)
        arrow.confidence = 0.99
        self.story.find_feature = lambda feature_name=None, **kwargs: [arrow] if feature_name == "enterbattle" else []

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
        self.assertEqual(1, names.count("handle_list_off_normal"))
        self.assertEqual(1, names.count("handle_detail_off_normal"))
        self.assertEqual(names.index("handle_mission_list") + 1, names.index("handle_list_off_normal"))
        self.assertEqual(names.index("handle_list_off_normal") + 1, names.index("handle_enter_story_or_battle"))
        self.assertEqual(names.index("handle_detail_off_normal") + 1, names.index("handle_enter"))

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

    def test_a_list_on_hard_never_reaches_storys_own_arrow_tap(self):
        frame = pills_moved(frame_with("mission_list_b2"), "NORMAL", "HARD")
        claimed = {self.one_pass(LIST_B2, frame) for _ in range(5)}
        self.assertEqual({"handle_mission_list"}, claimed)
        self.assertEqual([], self.story.taps)
        self.assertFalse(self.story.enabled)

    def test_a_list_off_normal_that_ocr_did_not_fully_read_never_reaches_storys_own_arrow_tap(self):
        self.with_arrow_feature(B2_ARROW)
        for tab in ("HARD", "ABYSS"):
            for name, texts in (("title missed", replaced(LIST_B2, "Battle Missions", None)),
                                ("NORMAL caption missed", replaced(LIST_B2, "NORMAL", None))):
                with self.subTest(tab=tab, texts=name):
                    self.story.enabled, self.story.taps = True, []
                    frame = pills_moved(frame_with("mission_list_b2"), "NORMAL", tab)
                    claimed = {self.one_pass(texts, frame) for _ in range(5)}
                    self.assertEqual({"handle_list_off_normal"}, claimed)
                    self.assertEqual([], self.story.taps)
                    self.assertFalse(self.story.enabled)

    def test_a_normal_list_ocr_did_not_fully_read_still_reaches_storys_own_arrow_tap(self):
        self.with_arrow_feature(B2_ARROW)
        texts = replaced(LIST_B2, "Battle Missions", None)
        self.assertEqual("handle_enter_story_or_battle", self.one_pass(texts, frame_with("mission_list_b2")))
        self.assertTappedAt(B2_ARROW)

    def test_a_detail_off_normal_never_reaches_enter(self):
        for tab in ("HARD", "ABYSS"):
            with self.subTest(tab=tab):
                self.story.enabled, self.story.taps = True, []
                frame = pills_moved(frame_with("mission_detail_b2"), "NORMAL", tab)
                claimed = {self.one_pass(DETAIL_B2, frame) for _ in range(5)}
                self.assertEqual({"handle_detail_off_normal"}, claimed)
                self.assertEqual([], self.story.taps)
                self.assertFalse(self.story.enabled)

    def test_a_chapter_node_still_goes_through_enter(self):
        self.assertEqual("handle_enter", self.one_pass(CHAPTER_NODE, without_tabs(frame_with("mission_list_b2"))))
        self.assertEqual(1, len(self.story.taps))

    def test_the_list_never_reaches_storys_own_arrow_tap(self):
        """Story's entrance tap would take whatever play arrow it saw, the Promotion card's included."""
        texts = replaced(LIST_B2, "B2", "Promotion")
        claimed = {self.one_pass(texts, frame_with("mission_list_b2")) for _ in range(5)}
        self.assertEqual({"handle_mission_list"}, claimed)
        self.assertEqual([], self.story.taps)
        self.assertFalse(self.story.enabled)


if __name__ == "__main__":
    unittest.main()
