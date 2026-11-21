"""Check which screens the bot taps to advance, and which it leaves alone.

Two failure modes are worth pinning: missing a narration screen leaves the run stalled until someone stops it,
and matching something else means a stray click on a screen the bot has not learned yet. The event option
screen is the one that must never match - its text sits in the same band, centred the same, and only its width
tells the two apart.
"""

import sys
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en.dialogue import (BETWEEN_TAPS, BUBBLE_AFTER_STUCK, MAX_TAPS, MAX_TEXT_BOXES, MEMORY_REGION, TAP_AREA,  # noqa: E402
                            TOGGLE_RETRY, TOGGLED, advance_arrow_showing, handle_dialogue, narration_line, speech_line)
from src.en.story import (AFTER_HOVER, AFTER_TAP, FAST_FORWARD_RETRY, FAST_FORWARD_TAPPED, filled_slots, handle_auto_chat, handle_fast_forward, handle_skip_story,  # noqa: E402
                          handle_team_formation, turning_auto_on)
from src.en.stuck import CLOCK  # noqa: E402

WIDTH, HEIGHT = 1920, 1080

# Where the corner crops in `tests/images/` were cut from, as the pixel at their top left.
ARROW_CORNER = (1749, 900)
# Where the Story dialogue bar crops were cut from, and the centres of its Skip and Auto icons, as screen fractions.
STORY_BAR_CORNER = (1344, 0)
SKIP_CENTRE = (0.767, 0.053)
AUTO_CENTRE = (0.830, 0.053)
FAST_FORWARD_CENTRE = (0.895, 0.053)

# Where the Team Formation slot bands were cut from, as the pixel row at their top: the Chaos stage's taller cards, and a
# battle's with Save Data under them. Both span x 0-1114 and were dimmed by a tutorial hint.
TEAM_BANDS = {"team_chaos_dimmed": 798, "team_battle_dimmed": 625}
# Each slot's column in those bands, as pixel x ranges.
TEAM_COLUMNS = ((0, 307), (326, 710), (730, 1114))

# The line the run stalled on, and the two-line screen the mushroom event showed.
SOLDIER = "The Soldier's eyes are fixed on the group. The Weapon in their hand is trembling."
MUSHROOM_FIRST = "The group examines the surface of the mushroom."
MUSHROOM_SECOND = "Blue, red, yellow, green. The spores come in a variety of colors."
# The speech bubble a Chaos run sat on for 38 seconds, drawn over the scene to the right of the party.
BUBBLE_FIRST = "The important thing is that just scraping this"
BUBBLE_SECOND = "together will make us rich!"


class FakeBox:
    """An OCR box positioned by its centre and its share of the screen width."""

    def __init__(self, name, center_x, center_y, width):
        self.name = name
        self.width = width * WIDTH
        self.height = 40
        self.x = center_x * WIDTH - self.width / 2
        self.y = center_y * HEIGHT - self.height / 2


class FakeTask:
    """A task holding one OCR pass and one capture, recording where the handler tapped.

    `later` holds the OCR passes the screen reads as after each tap, in order, and it reads as blank once they run out.
    """

    width, height = WIDTH, HEIGHT
    name = "StoryMode"

    def __init__(self, boxes, frame=None, later=()):
        self.all_texts = boxes
        self.frame = frame
        self.later = list(later)
        self.taps = []
        self.moved = None
        self.slept = 0
        self.notified = None
        self.disabled = False

    def ocr(self):
        return self.later.pop(0) if self.later else []

    def click(self, x, y, after_sleep=0):
        self.taps.append((x, y))
        self.slept += after_sleep

    def move_relative(self, x, y):
        self.moved = (x, y)

    def sleep(self, seconds):
        self.slept += seconds

    def log_info(self, message):
        pass

    def notification(self, message, title=None, tray=False):
        self.notified = message

    def disable(self):
        self.disabled = True


def with_bar(name):
    """Put a crop of the top bar back into an otherwise black frame.

    Args:
        name: The base name of the crop in `tests/images/`, cut from a 1080p capture at `STORY_BAR_CORNER`.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    left, top = STORY_BAR_CORNER
    frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
    return frame


def with_team(name, empty=()):
    """Put a Team Formation band of level plates back into an otherwise black frame.

    Args:
        name: The base name of the crop in `tests/images/`, a key of `TEAM_BANDS`.
        empty: Indexes of slots to paint over with the formation's grey, as a card with no level plate.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    top = TEAM_BANDS[name]
    frame[top:top + patch.shape[0], :patch.shape[1]] = patch
    for slot in empty:
        left, right = TEAM_COLUMNS[slot]
        frame[top:top + patch.shape[0], left:right] = (52, 52, 52)
    return frame


def with_corner(name):
    """Put a capture's bottom right corner, where the advance arrow bobs, back into an otherwise black frame.

    Args:
        name: The base name of the crop in `tests/images/`, cut from a 1080p capture at `ARROW_CORNER`.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    left, top = ARROW_CORNER
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
    return frame


def narration_screen():
    """Build the frame the run stalled on: health, credits and one line of prose.

    Returns:
        A `FakeTask`.
    """
    return FakeTask([
        FakeBox("2489/2658", 0.21, 0.038, 0.10),
        FakeBox("287", 0.65, 0.053, 0.02),
        FakeBox(SOLDIER, 0.496, 0.838, 0.716),
    ])


def two_line_narration_screen():
    """Build the mushroom event's dialogue screen, which reads out over two lines.

    Returns:
        A `FakeTask`.
    """
    return FakeTask([
        FakeBox("2542/2583", 0.21, 0.038, 0.10),
        FakeBox(MUSHROOM_FIRST, 0.467, 0.836, 0.508),
        FakeBox(MUSHROOM_SECOND, 0.512, 0.880, 0.591),
    ])


def option_screen():
    """Build the mushroom event's option screen, which must never be tapped.

    Its three option cards put text in the same band as narration, and the middle one is centred in the same
    place. Ranking the options is `src/en/events.py`'s job and a tap here would take that decision away.

    Returns:
        A `FakeTask`.
    """
    return FakeTask([
        FakeBox("2542/2583", 0.21, 0.038, 0.10),
        FakeBox("A single Invader mushroom has taken root here.", 0.5, 0.211, 0.35),
        FakeBox("It seems to contain a variety of spores.", 0.5, 0.248, 0.28),
        FakeBox("Examine the mushroom", 0.24, 0.799, 0.15),
        FakeBox("Check information on Types of", 0.24, 0.837, 0.22),
        FakeBox("[Dexterous] Collect a piece", 0.479, 0.799, 0.17),
        FakeBox("Upon success Decrease all", 0.479, 0.900, 0.21),
        FakeBox("Provoke the mushroom", 0.76, 0.799, 0.15),
        FakeBox("Event Encounter: [Pheromone", 0.76, 0.837, 0.21),
    ])


class TapsInArea:
    """Checking where the handler tapped, mixed into the test cases that tap."""

    def assertTapsInArea(self, taps, count):
        """Check the handler tapped `count` times, every one of them inside `TAP_AREA`.

        Args:
            taps: The points the fake task recorded.
            count: How many taps there should have been.
        """
        left, top, right, bottom = TAP_AREA
        self.assertEqual(count, len(taps))
        for x, y in taps:
            self.assertTrue(left <= x <= right and top <= y <= bottom, (x, y))


class TestDialogue(TapsInArea, unittest.TestCase):

    def test_the_stalled_narration_screen_is_recognised(self):
        """The whole point: this frame held the run until it was stopped by hand."""
        line = narration_line(narration_screen())
        self.assertIsNotNone(line)
        self.assertEqual(SOLDIER, line.name)

    def test_a_short_line_of_narration_is_recognised(self):
        """Chaos runs sat on each of these one-line screens until stopped by hand. The second is under `MIN_WIDTH`,
        so the advance arrow is what passes it."""
        for text, width, frame in (
            ("The inscription on the statue reads:", 0.316, None),
            ("A sheet of paper lies on the floor.", 0.299, with_corner("advance_arrow")),
        ):
            with self.subTest(text):
                task = FakeTask([
                    FakeBox("3045/3045", 0.212, 0.040, 0.10),
                    FakeBox("373", 0.650, 0.051, 0.02),
                    FakeBox(text, 0.494, 0.836, width),
                ], frame)
                self.assertIsNotNone(narration_line(task))

    def test_a_two_line_narration_screen_is_recognised(self):
        self.assertIsNotNone(narration_line(two_line_narration_screen()))

    def test_the_option_screen_is_never_tapped(self):
        """Tapping here would take the choice away from the ranking, which is the decision that matters."""
        self.assertIsNone(narration_line(option_screen()))

    def test_a_line_that_is_not_prose_is_never_tapped(self):
        """Each row is a real screen out of the capture corpus that an earlier, looser rule wrongly matched."""
        for description, text, centre_x, centre_y, width in (
            # An option card's text is centred in the same band; only its width tells them apart.
            ("a narrow line", "Collect a piece", 0.5, 0.84, 0.17),
            # The event prompt is wide and centred too, but it sits at the top and is not a tap target.
            ("a line high on the screen", "A single Invader mushroom has taken root here.", 0.5, 0.211, 0.5),
            ("an off centre line", "something wide but off to one side", 0.78, 0.84, 0.5),
            # The Persona card picker's tip, the widest non-prose line the corpus holds in the band.
            ("a tutorial tip", "Tap and hold the card to view its details.", 0.5, 0.858, 0.283),
            # OCR hands back empty boxes, and one wide enough would otherwise be tapped as prose.
            ("a blank reading", "   ", 0.5, 0.84, 0.6),
        ):
            with self.subTest(description):
                task = FakeTask([FakeBox(text, centre_x, centre_y, width)])
                self.assertIsNone(narration_line(task))

    def test_an_empty_screen_is_not_narration(self):
        self.assertIsNone(narration_line(FakeTask([])))

    def test_a_busy_screen_is_not_narration(self):
        """A tip banner sits at narration height on a screen carrying dozens of readings. Narration dims the
        frame and takes the HUD with it, so the box count is what tells those apart."""
        boxes = [FakeBox(f"reading {index}", 0.2, 0.3, 0.05) for index in range(MAX_TEXT_BOXES)]
        boxes.append(FakeBox("When a Claim Card is used, gain 1 Claim: Desire for each stack.", 0.49, 0.872, 0.586))
        task = FakeTask(boxes)
        # Frozen too, so a bubble line cannot slip past the count either.
        setattr(task, CLOCK, time.time() - BUBBLE_AFTER_STUCK - 1)
        self.assertFalse(handle_dialogue(task))

    def test_a_line_on_the_button_row_is_not_narration(self):
        """Most of what the capture corpus wrongly matched sat at 0.908 and below, under the prose band."""
        task = FakeTask([FakeBox("You can receive Edit Data recommendations based on Build Preset info.",
                                 0.502, 0.936, 0.548)])
        self.assertIsNone(narration_line(task))

    def test_a_cutscene_line_is_narration(self):
        """The trauma centre's prose, captured in sortie_340: same shape, on a screen of its own."""
        task = FakeTask([
            FakeBox("Patient Name Mika Protocol 0, Hormones normalized.", 0.493, 0.834, 0.479),
            FakeBox("Parameters normalized.", 0.37, 0.878, 0.21),
        ])
        self.assertIsNotNone(narration_line(task))

    def test_the_handler_taps_above_the_event_options_and_claims_the_frame(self):
        """The prose shares its band with the option cards that follow it, so the tap goes higher than either."""
        task = narration_screen()
        self.assertTrue(handle_dialogue(task))
        self.assertTapsInArea(task.taps, 1)
        options_top = min(box.y for box in option_screen().all_texts if box.y > HEIGHT / 2) / HEIGHT
        self.assertLess(TAP_AREA[3], options_top)

    def test_the_handler_taps_through_the_lines_until_the_options_appear(self):
        """Reading again between taps is what saves the run loop's second per line, and the option screen that
        follows the last line must still never be tapped."""
        task = narration_screen()
        task.later = [two_line_narration_screen().all_texts, option_screen().all_texts]
        self.assertTrue(handle_dialogue(task))
        self.assertTapsInArea(task.taps, 2)
        self.assertEqual(2 * BETWEEN_TAPS, task.slept)

    def test_a_line_that_never_advances_hands_the_frame_back(self):
        """Otherwise the handler would hold the run loop for as long as the screen stayed put."""
        task = narration_screen()
        task.later = [narration_screen().all_texts for _ in range(MAX_TAPS * 2)]
        handle_dialogue(task)
        self.assertTapsInArea(task.taps, MAX_TAPS)
        # Spread over the area rather than landing on one pixel every time.
        self.assertGreater(len(set(task.taps)), 1)

    def test_the_handler_declines_a_screen_it_does_not_recognise(self):
        """Returning False is what lets the run loop carry on to whatever else might handle the frame."""
        task = option_screen()
        self.assertFalse(handle_dialogue(task))
        self.assertEqual([], task.taps)


def bubble_screen(frozen_for):
    """Build the speech bubble frame the run stalled on, with the HUD still drawn around it.

    Args:
        frozen_for: How many seconds ago upstream's stuck clock last saw the picture change.

    Returns:
        A `FakeTask` holding the frame's OCR pass.
    """
    task = FakeTask([
        FakeBox("2229/2229", 0.21, 0.038, 0.10),
        FakeBox("153", 0.65, 0.053, 0.02),
        FakeBox(BUBBLE_FIRST, 0.688, 0.356, 0.308),
        FakeBox(BUBBLE_SECOND, 0.625, 0.394, 0.184),
    ])
    setattr(task, CLOCK, time.time() - frozen_for)
    return task


class TestSpeechBubble(TapsInArea, unittest.TestCase):
    """An NPC's speech bubble, which sits over the scene rather than in the narration band."""

    def test_the_stalled_bubble_is_tapped_once_the_frame_has_frozen(self):
        task = bubble_screen(BUBBLE_AFTER_STUCK + 1)
        self.assertTrue(handle_dialogue(task))
        self.assertTapsInArea(task.taps, 1)

    def test_a_bubble_is_left_alone_while_the_frame_is_still_changing(self):
        """The freeze is what says no other handler wants the frame, so a live frame is never read this loosely."""
        self.assertIsNone(speech_line(bubble_screen(0)))
        self.assertIsNone(speech_line(FakeTask(bubble_screen(0).all_texts)))

    def test_a_frozen_line_that_is_not_speech_is_never_tapped(self):
        for label, name, center_x, center_y, width in (
            ("a short label", "Event Encounter", 0.5, 0.4, 0.12),
            ("a line below the scene", "Select a card to remove", 0.5, 0.75, 0.2),
        ):
            with self.subTest(label):
                task = FakeTask([FakeBox(name, center_x, center_y, width)])
                setattr(task, CLOCK, time.time() - BUBBLE_AFTER_STUCK - 1)
                self.assertIsNone(speech_line(task))


class TestAdvanceArrow(unittest.TestCase):
    """The arrow narration draws in the bottom right corner, which is what lets a short line through."""

    def test_the_arrow_is_told_apart_from_the_closest_thing_that_is_not_one(self):
        """The arrow is the lowest scoring of the captures that show it, and the other crop is the best scoring of
        the rest, a card's edge."""
        for name, showing in (("advance_arrow", True), ("advance_arrow_absent", False)):
            with self.subTest(name):
                self.assertEqual(showing, advance_arrow_showing(FakeTask([], with_corner(name))))

    def test_a_frame_the_reader_never_got_shows_no_arrow(self):
        self.assertFalse(advance_arrow_showing(FakeTask([])))


class TestAutoAdvance(TapsInArea, unittest.TestCase):
    """Reaching for the top bar's Auto before tapping the prose."""

    def test_auto_is_only_tapped_while_it_is_off(self):
        """The old ring's reader took the new bar for off even when Auto was lit, and tapped Fast-Forward instead."""
        for crop, tapped in (("story_bar_off", True), ("story_bar_on", False), (None, False)):
            with self.subTest(crop=crop):
                task = narration_screen()
                task.frame = None if crop is None else with_bar(crop)
                self.assertTrue(handle_dialogue(task))
                if tapped:
                    self.assertEqual(1, len(task.taps))
                    self.assertAlmostEqual(AUTO_CENTRE[0], task.taps[0][0], delta=0.005)
                    self.assertAlmostEqual(AUTO_CENTRE[1], task.taps[0][1], delta=0.005)
                    self.assertEqual(AFTER_HOVER + AFTER_TAP, task.slept)
                else:
                    self.assertTapsInArea(task.taps, 1)

    def test_auto_that_will_not_turn_on_gives_way_to_tapping_the_line_until_the_retry_wait_has_passed(self):
        """A live run tapped a button that never lit for over a minute and never advanced the line."""
        task = narration_screen()
        task.frame = with_bar("story_bar_off")
        handle_dialogue(task)
        task.taps.clear()
        self.assertTrue(handle_dialogue(task))
        self.assertTapsInArea(task.taps, 1)
        task.taps.clear()
        # Tapping the line reads the screen again, and the fake reads blank once its passes run out.
        task.all_texts = narration_screen().all_texts
        setattr(task, TOGGLED, getattr(task, TOGGLED) - TOGGLE_RETRY)
        handle_dialogue(task)
        self.assertEqual(1, len(task.taps))
        self.assertAlmostEqual(AUTO_CENTRE[0], task.taps[0][0], delta=0.005)

    def test_a_memory_cutscene_is_tapped_through_without_reaching_for_auto(self):
        """The 11:31 memory cutscene is drawn in grey and ignores the button, so tapping it only wasted the frame."""
        task = narration_screen()
        task.frame = with_bar("story_bar_off")
        left, top, right, bottom = MEMORY_REGION
        task.frame[int(top * HEIGHT):int(bottom * HEIGHT), int(left * WIDTH):int(right * WIDTH)] = (131, 131, 131)
        self.assertTrue(handle_dialogue(task))
        self.assertTapsInArea(task.taps, 1)

    def test_auto_is_never_tapped_off_a_narration_screen(self):
        """The bar is only read once the screen has been recognised, so nothing else can be reached for."""
        task = option_screen()
        task.frame = with_bar("story_bar_off")
        self.assertFalse(handle_dialogue(task))
        self.assertEqual([], task.taps)


class TestStoryBar(unittest.TestCase):

    def test_skip_is_pressed_and_auto_only_turned_on(self):
        """Story pressed nothing once the bar was redrawn, and a lit Auto tapped again would switch itself back off.

        The tinted and dark crops are scenes a run played through without skipping, where Skip scored 0.85 and 0.80.
        """
        cases = (
            ("story_bar_off", handle_skip_story, SKIP_CENTRE),
            ("story_bar_on", handle_skip_story, SKIP_CENTRE),
            ("story_bar_tinted", handle_skip_story, SKIP_CENTRE),
            ("story_bar_dark", handle_skip_story, SKIP_CENTRE),
            ("story_bar_off", handle_auto_chat, AUTO_CENTRE),
            ("story_bar_on", handle_auto_chat, None),
            (None, handle_skip_story, None),
            (None, handle_auto_chat, None),
        )
        for crop, handler, centre in cases:
            with self.subTest(crop=crop, handler=handler.__name__):
                task = FakeTask([], None if crop is None else with_bar(crop))
                self.assertEqual(centre is not None, handler(task))
                self.assertEqual(0 if centre is None else 1, len(task.taps))
                for x, y in task.taps:
                    self.assertAlmostEqual(centre[0], x, delta=0.005)
                    self.assertAlmostEqual(centre[1], y, delta=0.005)

    def test_a_battle_only_has_auto_turned_on_when_it_is_off(self):
        # Upstream reads Auto off a pixel the new bar leaves black, so no battle had Auto turned on.
        for crop, on_battle, taps in (("story_bar_off", True, [AUTO_CENTRE]), ("story_bar_on", True, []), ("story_bar_off", False, [])):
            with self.subTest(crop=crop, on_battle=on_battle):
                task = FakeTask([], with_bar(crop))
                self.assertEqual(on_battle, turning_auto_on(lambda _: on_battle)(task))
                self.assertEqual(len(taps), len(task.taps))
                for (x, y), (centre_x, centre_y) in zip(task.taps, taps):
                    self.assertAlmostEqual(centre_x, x, delta=0.005)
                    self.assertAlmostEqual(centre_y, y, delta=0.005)

    def test_story_stops_on_a_team_formation_screen_with_an_empty_slot(self):
        # Upstream pressed Enter on a team of one forever. The boxes sit where the live screen read them.
        title = FakeBox("主战员配置", 0.154, 0.044, 0.08)
        levels = [FakeBox("等级", x, 0.605, 0.02) for x in (0.056, 0.271, 0.486)]
        for filled, stops in ((1, True), (2, True), (3, False)):
            with self.subTest(filled=filled):
                task = FakeTask([title, *levels[:filled]])
                self.assertEqual(stops, handle_team_formation(task))
                self.assertEqual(stops, task.disabled)
                self.assertEqual(stops, task.notified is not None)
        self.assertFalse(handle_team_formation(FakeTask(levels[:1])))

    def test_a_full_team_counts_as_full_on_both_formation_layouts(self):
        """OCR read the level label under two of three filled cards on the Chaos stage and one of three on Battle Missions.

        Both stopped Story with a full team. The Chaos stage's labels sit at y 0.766, below where a battle's do.
        """
        title = FakeBox("主战员配置", 0.155, 0.047, 0.08)
        read = {"team_chaos_dimmed": [FakeBox("等级", x, 0.766, 0.02) for x in (0.056, 0.271)],
                "team_battle_dimmed": [FakeBox("等级", 0.271, 0.606, 0.02)]}
        for band, labels in read.items():
            with self.subTest(band=band):
                task = FakeTask([title, *labels], with_team(band))
                self.assertFalse(handle_team_formation(task))
                self.assertFalse(task.disabled)
                self.assertEqual(3, filled_slots(task))

    def test_an_empty_slot_still_stops_story_on_both_formation_layouts(self):
        title = FakeBox("主战员配置", 0.155, 0.047, 0.08)
        for band in TEAM_BANDS:
            for empty in range(3):
                with self.subTest(band=band, empty=empty):
                    task = FakeTask([title], with_team(band, empty=(empty,)))
                    self.assertTrue(handle_team_formation(task))
                    self.assertTrue(task.disabled)
                    self.assertIn("2 of 3", task.notified)
        task = FakeTask([title], np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8))
        self.assertTrue(handle_team_formation(task))
        self.assertIn("0 of 3", task.notified)

    def test_fast_forward_is_turned_on_once_and_then_left_alone_for_the_retry_wait(self):
        # The dark crop has it lit already, and a second tap on a lit button would switch it back off.
        for crop, taps in (("story_bar_off", [FAST_FORWARD_CENTRE]), ("story_bar_tinted", [FAST_FORWARD_CENTRE]), ("story_bar_dark", []), (None, [])):
            with self.subTest(crop=crop):
                task = FakeTask([], None if crop is None else with_bar(crop))
                self.assertEqual(bool(taps), handle_fast_forward(task))
                self.assertEqual(len(taps), len(task.taps))
                for (x, y), (centre_x, centre_y) in zip(task.taps, taps):
                    self.assertAlmostEqual(centre_x, x, delta=0.005)
                    self.assertAlmostEqual(centre_y, y, delta=0.005)
        task = FakeTask([], with_bar("story_bar_off"))
        handle_fast_forward(task)
        self.assertFalse(handle_fast_forward(task))
        setattr(task, FAST_FORWARD_TAPPED, getattr(task, FAST_FORWARD_TAPPED) - FAST_FORWARD_RETRY)
        self.assertTrue(handle_fast_forward(task))


if __name__ == "__main__":
    unittest.main()
