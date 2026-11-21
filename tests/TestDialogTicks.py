"""Check that "Do not show" is ticked on the Story skip dialog and Battle Prep only, once, and on nothing else.

The Rescue dialog draws the same box at the same x as the skip dialog, and a tick there would drop the pull confirmation,
so every refusal matters as much as the tap. The screens are the Global client's, their text as OCR read it and their
box as cut from the capture.
"""

import re
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

import utils_chaos  # noqa: E402
import utils_sortie  # noqa: E402
import utils_story  # noqa: E402

from src.en import daily, dialog_ticks, handlers, spend_guard  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

SKIP_SPOT = (0.3925, 0.678)
PREP_SPOT = (0.404, 0.721)
INSTALLS = 3
# Where every crop in `tests/images/` was cut from its 1080p capture: x 691-845, y 691-821.
CROP_LEFT, CROP_TOP = 691, 691

SKIP_SYNOPSIS = [("Do you want to skip the current dialogue?", 0.5, 0.212),
                 ("Renoa collapses and loses consciousness immediately after returning to the SS Nightmare.", 0.499, 0.294),
                 ("simply the tension leaving her body, and recommends that the Captain also rest", 0.498, 0.331),
                 ("treated.", 0.501, 0.369), ("Main Characters", 0.5, 0.444), ("Do not show until next login", 0.519, 0.677),
                 ("取消", 0.348, 0.786), ("确认", 0.662, 0.786)]
# OCR misread the title's last word on this one.
SKIP_DIALOGUE = [("Do you want to skip the current dlialogue?", 0.5, 0.213),
                 ("A sudden ambush by Luscus puts the group in danger, but the Captain's Life Core has malfunctioned,", 0.498, 0.293),
                 ("and is left alone inside the Chaos.", 0.5, 0.369), ("Main Characters", 0.499, 0.444),
                 ("Do not show until next login", 0.52, 0.677), ("取消", 0.348, 0.784), ("确认", 0.667, 0.784)]
PREP = [("Battle Prep Confirmation", 0.499, 0.166), ("Recommended Lv. 02", 0.5, 0.244),
        ("Please check to see if you've met the recommended level.", 0.499, 0.3), ("Mika", 0.351, 0.404),
        ("Assign Partner", 0.771, 0.406), ("Level Up", 0.619, 0.487), ("Assign Partner", 0.772, 0.489),
        ("Level UpD", 0.636, 0.577), ("Assign Partner", 0.768, 0.577), ("Do not show again today", 0.52, 0.721),
        ("取消", 0.347, 0.83), ("进入", 0.666, 0.831)]
PREP_TICKED = [*PREP, ("√", 0.404, 0.723)]
# The growth tutorial's Battle Prep, under its dimming.
PREP_DIMMED = [("Skip Tutorial", 0.879, 0.055), ("Battle Prep Confirmation", 0.501, 0.169), ("Recommended Lv. 01", 0.5, 0.244),
               ("Assign Partner", 0.772, 0.406), ("Do not show again today i", 0.539, 0.721), ("取消", 0.348, 0.831),
               ("•", 0.53, 0.83), ("进入", 0.665, 0.83)]
RESCUE = [("营救", 0.116, 0.046), ("Normal Rescue", 0.29, 0.187), ("Proceed with Rescue", 0.5, 0.328),
          ("Would you like to proceed Rescue 10 time(s)?", 0.501, 0.451), ("Do not show until next login", 0.521, 0.558),
          ("取消", 0.348, 0.669), ("确认", 0.667, 0.669), ("Rescue Merit", 0.79, 0.751), ("Rescue 1 time(s)", 0.633, 0.911),
          ("Rescue 10 time(s)", 0.85, 0.912), ("免费", 0.949, 0.913)]
LOOT = [("Settlement", 0.59, 0.065), ("Loot", 0.539, 0.139),
        ("There is additional loot available. Continue without using Loot Certification Card?", 0.502, 0.412),
        ("Ctrl", 0.393, 0.492), ("Do not show until next login", 0.521, 0.531), ("ESC", 0.214, 0.593), ("进入", 0.535, 0.593),
        ("取消", 0.347, 0.632), ("确认", 0.667, 0.63), ("Temporary Return", 0.623, 0.916), ("继续", 0.927, 0.915)]
SETTINGS = [("Game Settings", 0.176, 0.091), ("Customize Detailed Popups", 0.205, 0.394), ("Display Story Skip Popup", 0.202, 0.458),
            ("on", 0.797, 0.459), ("Display Rescue Progress Popup", 0.226, 0.531), ("on", 0.797, 0.529),
            ("Display Battle Prep Confirmation Popup", 0.253, 0.601), ("on", 0.797, 0.6),
            ("Display Unequipped Memory Fragment Popup", 0.275, 0.675), ("on", 0.797, 0.674)]


def crop(name):
    """Read one of the crops around the boxes.

    Args:
        name: The crop's base name in `tests/images/`.

    Returns:
        The pixels, in BGR.
    """
    return cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))


def frame(patch):
    """Put a crop back where it was cut from, in an otherwise black frame.

    Args:
        patch: The crop's pixels.

    Returns:
        A 1080p frame.
    """
    full = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    full[CROP_TOP:CROP_TOP + patch.shape[0], CROP_LEFT:CROP_LEFT + patch.shape[1]] = patch
    return full


def ticked_skip_crop():
    """Compose a ticked skip dialog's box, since no capture shows one: Battle Prep's ticked box pasted over the skip box.

    Returns:
        The skip dialog's crop with its box ticked.
    """
    patch = crop("dont_show_skip_synopsis").copy()
    ticked = crop("dont_show_prep_ticked")
    # Both boxes' centres in crop pixels: Battle Prep's at (85, 88), the skip dialog's at (63, 41).
    patch[17:65, 39:87] = ticked[64:112, 61:109]
    return patch


class FakeTask:
    """A mode looking at one screen, recording every input."""

    def __init__(self):
        self.name = "自动剧情模式"
        self.width, self.height = WIDTH, HEIGHT
        self.all_texts = []
        self.frame = None
        self.moved = []
        self.clicked = []
        self.boxes_clicked = []
        self.logged = []
        self.notifications = []
        self.disabled = False

    def show(self, texts, patch=None):
        """Put a screen in front of the task.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
            patch: The crop around the boxes, or None for no frame.

        Returns:
            The task.
        """
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.frame = None if patch is None else frame(patch)
        return self

    def move_relative(self, x, y):
        self.moved.append((x, y))

    def sleep(self, seconds):
        pass

    def click(self, x, y, after_sleep=0):
        self.clicked.append((x, y))

    def click_box(self, box):
        self.boxes_clicked.append(box.name)

    def find_one(self, feature_name, box=None):
        return None

    def box_of_screen(self, *region):
        return region

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled = True


def moved(texts, *shifts):
    """Move some of a screen's boxes.

    Args:
        texts: `(name, x, y)` triples.
        *shifts: `(name, x, y)` triples naming a box by its text and where it goes instead.

    Returns:
        The moved screen.
    """
    where = {name: (x, y) for name, x, y in shifts}
    return [(name, *where.get(name, (x, y))) for name, x, y in texts]


def without(texts, name):
    """Take a box off a screen.

    Args:
        texts: `(name, x, y)` triples.
        name: The text of the box to drop.

    Returns:
        The screen without it.
    """
    return [entry for entry in texts if entry[0] != name]


class TestBoxState(unittest.TestCase):
    """The box read off its pixels."""

    def test_each_captured_box_reads_as_drawn(self):
        for name, spot, state in (("dont_show_skip_synopsis", SKIP_SPOT, dialog_ticks.UNTICKED),
                                  ("dont_show_skip_dialogue", SKIP_SPOT, dialog_ticks.UNTICKED),
                                  ("dont_show_prep", PREP_SPOT, dialog_ticks.UNTICKED),
                                  ("dont_show_prep_ticked", PREP_SPOT, dialog_ticks.TICKED),
                                  ("dont_show_prep_dimmed", PREP_SPOT, None)):
            with self.subTest(crop=name):
                self.assertEqual(state, dialog_ticks.box_state(frame(crop(name)), spot))

    def test_the_composed_ticked_skip_box_reads_ticked(self):
        self.assertEqual(dialog_ticks.TICKED, dialog_ticks.box_state(frame(ticked_skip_crop()), SKIP_SPOT))

    def test_a_lit_box_in_another_colour_reads_as_nothing(self):
        """Only the grey box is one this module knows unticked; a tinted square as bright is some other control."""
        for bgr in ((200, 150, 100), (90, 90, 200), (120, 200, 120)):
            with self.subTest(bgr=bgr):
                full = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
                full[700:765, 730:780] = bgr
                self.assertIsNone(dialog_ticks.box_state(full, SKIP_SPOT))

    def test_no_box_reads_as_nothing(self):
        self.assertIsNone(dialog_ticks.box_state(None, SKIP_SPOT))
        self.assertIsNone(dialog_ticks.box_state(frame(crop("dont_show_skip_synopsis")), PREP_SPOT), "label background, not a box")
        self.assertIsNone(dialog_ticks.box_state(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), SKIP_SPOT))


class TestTick(unittest.TestCase):
    """The handler on one screen at a time."""

    def setUp(self):
        self.task = FakeTask()

    def run_handler(self, texts, patch=None):
        return dialog_ticks.handle_dont_show_again(self.task.show(texts, patch))

    def assertNoTap(self, answer):
        self.assertIs(False, answer)
        self.assertEqual([], self.task.clicked)
        self.assertEqual([], self.task.moved)
        self.assertEqual([], self.task.boxes_clicked)

    def test_the_skip_dialog_box_is_tapped_once(self):
        for texts, name in ((SKIP_SYNOPSIS, "dont_show_skip_synopsis"), (SKIP_DIALOGUE, "dont_show_skip_dialogue")):
            with self.subTest(crop=name):
                self.task = FakeTask()
                self.assertIs(True, self.run_handler(texts, crop(name)))
                self.assertEqual([SKIP_SPOT], self.task.moved)
                self.assertEqual([SKIP_SPOT], self.task.clicked)
                self.assertEqual([], self.task.boxes_clicked, "Confirm stays with the centred Confirm")
                self.assertEqual(["ticking Do not show on the Story skip dialog"], self.task.logged)

    def test_the_battle_prep_box_is_tapped_once(self):
        self.assertIs(True, self.run_handler(PREP, crop("dont_show_prep")))
        self.assertEqual([PREP_SPOT], self.task.clicked)
        self.assertEqual([], self.task.boxes_clicked, "Enter stays with handle_enter")

    def test_an_already_ticked_box_is_left_alone(self):
        for texts, patch in ((PREP_TICKED, crop("dont_show_prep_ticked")), (SKIP_SYNOPSIS, ticked_skip_crop())):
            with self.subTest(dialog=texts[0][0]):
                self.task = FakeTask()
                self.assertNoTap(self.run_handler(texts, patch))

    def test_the_ticked_box_after_the_tap_is_left_to_the_confirm(self):
        self.assertIs(True, self.run_handler(PREP, crop("dont_show_prep")))
        self.assertIs(False, self.run_handler(PREP_TICKED, crop("dont_show_prep_ticked")))
        self.assertEqual([PREP_SPOT], self.task.clicked)

    def test_a_tick_that_did_not_take_is_not_tapped_again(self):
        self.assertIs(True, self.run_handler(PREP, crop("dont_show_prep")))
        for _ in range(3):
            self.assertIs(False, self.run_handler(PREP, crop("dont_show_prep")))
        self.assertEqual([PREP_SPOT], self.task.clicked)
        self.assertEqual(1, sum("did not take" in line for line in self.task.logged), "logged once")

    def test_a_later_appearance_gets_its_one_tap_again(self):
        self.assertIs(True, self.run_handler(SKIP_SYNOPSIS, crop("dont_show_skip_synopsis")))
        self.assertIs(False, self.run_handler([("Main Characters", 0.5, 0.444)]))
        self.assertIs(True, self.run_handler(SKIP_SYNOPSIS, crop("dont_show_skip_synopsis")))
        self.assertEqual([SKIP_SPOT, SKIP_SPOT], self.task.clicked)

    def test_the_other_dialog_gets_its_own_tap(self):
        self.assertIs(True, self.run_handler(SKIP_SYNOPSIS, crop("dont_show_skip_synopsis")))
        self.assertIs(True, self.run_handler(PREP, crop("dont_show_prep")))
        self.assertEqual([SKIP_SPOT, PREP_SPOT], self.task.clicked)

    def test_a_dimmed_box_is_left_alone(self):
        """The growth tutorial frames Enter and may eat a tap anywhere else."""
        self.assertNoTap(self.run_handler(PREP_DIMMED, crop("dont_show_prep_dimmed")))

    def test_no_frame_means_no_tap(self):
        self.assertNoTap(self.run_handler(SKIP_SYNOPSIS))

    def test_the_rescue_dialog_gets_no_tap_even_over_a_lit_box(self):
        """Its box sits at the skip box's x; the lit skip box under it stands for a layout that moved it to the same spot."""
        for name in ("dont_show_skip_synopsis", "dont_show_prep"):
            with self.subTest(crop=name):
                self.task = FakeTask()
                self.assertNoTap(self.run_handler(RESCUE, crop(name)))
                self.assertIsNone(dialog_ticks.shown_tick(self.task))

    def test_a_rescue_marker_on_a_whitelisted_dialog_gets_no_tap(self):
        for texts, name in ((SKIP_SYNOPSIS, "dont_show_skip_synopsis"), (PREP, "dont_show_prep")):
            with self.subTest(dialog=texts[0][0]):
                self.task = FakeTask()
                self.assertNoTap(self.run_handler([*texts, ("Rescue 10 time(s)", 0.85, 0.912)], crop(name)))

    def test_a_risky_dialog_gets_no_tap(self):
        """Below the synopsis the skip dialog shows only portraits, so an account marker there is a dialog the guard stops on."""
        texts = [*SKIP_SYNOPSIS, ("Use 1 Aether?", 0.5, 0.55)]
        self.assertIsNotNone(spend_guard.risky_confirm(self.task.show(texts)))
        self.assertNoTap(self.run_handler(texts, crop("dont_show_skip_synopsis")))

    def test_the_loot_dialog_gets_no_tap_even_over_a_lit_box(self):
        """A tick there would hide the lost-loot warning until the next login."""
        self.assertNoTap(self.run_handler(LOOT, crop("dont_show_skip_synopsis")))
        self.assertIsNone(dialog_ticks.shown_tick(self.task))

    def test_the_settings_page_gets_no_tap(self):
        self.assertNoTap(self.run_handler(SETTINGS, crop("dont_show_prep")))
        self.assertIsNone(dialog_ticks.shown_tick(self.task))

    def test_the_settings_row_where_the_title_sits_is_still_no_title(self):
        texts = [("Display Battle Prep Confirmation Popup", 0.499, 0.166), *PREP[1:]]
        self.assertNoTap(self.run_handler(texts, crop("dont_show_prep")))

    def test_each_part_of_the_whitelist_is_needed(self):
        cases = {
            "skip title missing": (without(SKIP_SYNOPSIS, SKIP_SYNOPSIS[0][0]), "dont_show_skip_synopsis"),
            "skip title out of place": (moved(SKIP_SYNOPSIS, (SKIP_SYNOPSIS[0][0], 0.5, 0.1)), "dont_show_skip_synopsis"),
            "skip label missing": (without(SKIP_SYNOPSIS, "Do not show until next login"), "dont_show_skip_synopsis"),
            "skip label out of place": (moved(SKIP_SYNOPSIS, ("Do not show until next login", 0.519, 0.558)), "dont_show_skip_synopsis"),
            "skip Cancel missing": (without(SKIP_SYNOPSIS, "取消"), "dont_show_skip_synopsis"),
            "skip Confirm missing": (without(SKIP_SYNOPSIS, "确认"), "dont_show_skip_synopsis"),
            "skip buttons out of place": (moved(SKIP_SYNOPSIS, ("取消", 0.348, 0.669), ("确认", 0.667, 0.669)), "dont_show_skip_synopsis"),
            "skip with Enter for Confirm": ([(("进入" if name == "确认" else name), x, y) for name, x, y in SKIP_SYNOPSIS], "dont_show_skip_synopsis"),
            "prep title missing": (without(PREP, "Battle Prep Confirmation"), "dont_show_prep"),
            "prep title out of place": (moved(PREP, ("Battle Prep Confirmation", 0.499, 0.3)), "dont_show_prep"),
            "prep label missing": (without(PREP, "Do not show again today"), "dont_show_prep"),
            "prep label out of place": (moved(PREP, ("Do not show again today", 0.52, 0.8)), "dont_show_prep"),
            "prep Cancel missing": (without(PREP, "取消"), "dont_show_prep"),
            "prep Enter missing": (without(PREP, "进入"), "dont_show_prep"),
            "prep buttons out of place": (moved(PREP, ("取消", 0.347, 0.9), ("进入", 0.666, 0.9)), "dont_show_prep"),
            "prep label of the skip dialog": ([(("Do not show until next login" if name.startswith("Do not show") else name), x, y)
                                               for name, x, y in PREP], "dont_show_prep"),
        }
        for case, (texts, name) in cases.items():
            with self.subTest(case=case):
                self.task = FakeTask()
                self.assertNoTap(self.run_handler(texts, crop(name)))

    def test_only_the_two_boxes_are_ever_tapped(self):
        """Every screen above, lit box or not, in one long run: the only points pressed are the two boxes."""
        screens = [(texts, crop(name)) for texts in (SKIP_SYNOPSIS, SKIP_DIALOGUE, PREP, PREP_TICKED, PREP_DIMMED, RESCUE, LOOT, SETTINGS)
                   for name in ("dont_show_skip_synopsis", "dont_show_skip_dialogue", "dont_show_prep", "dont_show_prep_ticked",
                                "dont_show_prep_dimmed")]
        for texts, patch in screens * 2:
            self.run_handler(texts, patch)
            self.run_handler([])
        self.assertTrue(self.task.clicked)
        self.assertLessEqual(set(self.task.clicked), {SKIP_SPOT, PREP_SPOT})
        self.assertEqual(self.task.clicked, self.task.moved)
        self.assertEqual([], self.task.boxes_clicked)
        self.assertEqual({SKIP_SPOT, PREP_SPOT}, {spot for _, spot in dialog_ticks.TICKS})


def stand_in_utils():
    """Build a stand-in for `utils` carrying the two handlers the spend guard wraps.

    Returns:
        A namespace.
    """
    def handle_stuck_log(task):
        return False

    def handle_center_confirm(task):
        return False

    return types.SimpleNamespace(handle_stuck_log=handle_stuck_log, handle_center_confirm=handle_center_confirm,
                                 is_frame_stuck=lambda task, stuck_threshold_seconds: False)


class TestInstall(unittest.TestCase):
    """Where the tick sits in each mode's list."""

    def installed_names(self):
        """Install the spend guard and the tick on the real modes, read their lists, and put every list back.

        Returns:
            Each mode's handler names, by module name.
        """
        modes = (utils_story, utils_chaos, utils_sortie, daily)
        stand_in = stand_in_utils()
        # Other tests stand modules of their own in for the modes, or take them out, and the install reaches only what is loaded.
        with mock.patch.dict(sys.modules, {module.__name__: module for module in modes}):
            saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
            try:
                for _ in range(INSTALLS):
                    spend_guard.install(stand_in)
                    dialog_ticks.install()
                return {module.__name__: [getattr(handler, "__name__", None) for handler in module.PAGE_HANDLERS] for module in modes}
            finally:
                for entries, before in saved:
                    entries[:] = before

    def test_the_tick_sits_after_the_rescue_stop_and_before_both_confirms_once(self):
        """Another test in the same run may leave a handler of its own ahead of the centred Confirm, so only the order is asserted here."""
        names = self.installed_names()
        for module in (utils_story, utils_chaos, utils_sortie):
            listed = names[module.__name__]
            with self.subTest(mode=module.__name__):
                self.assertEqual(1, listed.count("handle_dont_show_again"))
                self.assertEqual(1, listed.count("handle_rescue_screen"))
                tick = listed.index("handle_dont_show_again")
                self.assertLess(listed.index("handle_rescue_screen"), tick)
                self.assertLess(tick, listed.index("handle_center_confirm"))
                self.assertLess(tick, listed.index("handle_enter"), "Battle Prep's Enter is pressed by handle_enter")

    def test_the_tick_goes_straight_after_the_rescue_stop(self):
        mode = types.ModuleType("fake_mode_for_dialog_ticks_test")
        stand_in = stand_in_utils()
        mode.PAGE_HANDLERS = [stand_in.handle_center_confirm, stand_in.handle_stuck_log]
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        sys.modules[mode.__name__] = mode
        try:
            for _ in range(INSTALLS):
                spend_guard.install(stand_in)
                dialog_ticks.install()
            listed = [handler.__name__ for handler in mode.PAGE_HANDLERS]
        finally:
            sys.modules.pop(mode.__name__, None)
            for entries, before in saved:
                entries[:] = before
        self.assertEqual(["handle_rescue_screen", "handle_dont_show_again", "handle_center_confirm", "handle_stuck_log"], listed)

    def test_daily_gets_no_tick(self):
        """Daily keeps its reviewed press set, which holds no centred Confirm."""
        listed = self.installed_names()[daily.__name__]
        self.assertNotIn("handle_center_confirm", listed)
        self.assertNotIn("handle_dont_show_again", listed)

    def test_the_tick_is_applied_after_the_spend_guard(self):
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertEqual(1, applied.count("dialog_ticks"))
        self.assertLess(applied.index("spend_guard"), applied.index("dialog_ticks"))
        self.assertLess(applied.index("dialog_ticks"), applied.index("claims"))


if __name__ == "__main__":
    unittest.main()
