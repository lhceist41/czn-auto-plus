"""Check that Chaos presses Enter on its Entry Guide and on the Exploration record notice, and on nothing that only looks like them.

Neither screen shows its Enter on the round button, so nothing pressed them, and the run tapped the scene or a false event
option for minutes. The screens are the Global client's, their text and positions as OCR read them off live captures.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

from src.en import enter, handlers  # noqa: E402
from src.en.screen import centre_of  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402
from tests.TestDialogTicks import LOOT, PREP, PREP_DIMMED, RESCUE, SKIP_DIALOGUE, SKIP_SYNOPSIS  # noqa: E402

INSTALLS = 3
ENTRY_GUIDE = [("Chaos Manifestation Entry Guide", 0.501, 0.389),
               ("A higher difficulty is unlocked. Would you like to enter at the current difficulty?", 0.501, 0.505),
               ("□", 0.390, 0.627), ("Do not show again for today.", 0.521, 0.624), ("×", 0.213, 0.745), ("取消", 0.347, 0.745),
               ("进入", 0.664, 0.745)]
# After a run's last Leave, once over a combat card reward and once over an Encouragement.
RECORD_ENCOURAGEMENT = [("09", 0.516, 0.088), ("Unlocked Exploration Records appear as rewards in Chaos.", 0.499, 0.153),
                        ("Encouragement", 0.500, 0.636), ("During the next 3 visit to", 0.499, 0.687), ("the Dellang Shop, the", 0.498, 0.718),
                        ("price of 1 random", 0.499, 0.749), ("reduced by 100%.", 0.499, 0.812), ("displayed item is", 0.499, 0.781),
                        ("进入", 0.501, 0.973)]
RECORD_CARD = [("Unlocked Exploration Records appear as rewards in Chaos.", 0.499, 0.153), ("Quick Shelling", 0.512, 0.304),
               ("X", 0.460, 0.342), ("攻击力", 0.495, 0.343), ("80% Damage", 0.504, 0.720), ("Draw", 0.501, 0.755), ("进入", 0.502, 0.973)]
# A waypoint Settlement, whose Enter key hint sits on its Additional Loot row.
SETTLEMENT = [("406/406", 0.213, 0.037), ("结算", 0.590, 0.065), ("0/4", 0.879, 0.049), ("Loot", 0.542, 0.139),
              ("Additional Loot", 0.580, 0.369), ("获得", 0.857, 0.384), ("Exploration Score", 0.626, 0.815), ("进入", 0.835, 0.877),
              ("Temporary Return", 0.623, 0.915), ("继续", 0.928, 0.915)]
# The bare key hint a Select or Confirm button carries, and the round action button.
ENTER_HINT = [("进入", 0.501, 0.973)]
ROUND_BUTTON = [("进入", 0.946, 0.923)]
OTHER_SCREENS = {"Battle Prep": PREP, "Battle Prep dimmed": PREP_DIMMED, "Story skip": SKIP_SYNOPSIS, "Story skip misread": SKIP_DIALOGUE,
                 "Rescue": RESCUE, "Loot dialog": LOOT, "Settlement": SETTLEMENT, "Enter hint": ENTER_HINT, "round button": ROUND_BUTTON}


class FakeTask:
    """Chaos looking at one screen, recording the boxes it presses."""

    def __init__(self, texts):
        self.width, self.height = WIDTH, HEIGHT
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.pressed = []
        self.logged = []

    def click_box(self, box):
        self.pressed.append((box.name, tuple(round(value, 3) for value in centre_of(box, self.width, self.height))))

    def log_info(self, message, notify=False):
        self.logged.append(message)


def without(texts, name):
    return [entry for entry in texts if entry[0] != name]


def moved(texts, name, x, y):
    return [(text, x, y) if text == name else (text, x_, y_) for text, x_, y_ in texts]


class TestEntryGuide(unittest.TestCase):
    """The dialog asking whether to enter at the current difficulty, which the run tapped past as a speech bubble."""

    def test_enter_is_pressed_on_the_box_read(self):
        task = FakeTask(ENTRY_GUIDE)
        self.assertTrue(enter.handle_entry_guide(task))
        self.assertEqual([("进入", (0.664, 0.745))], task.pressed)

    def test_each_part_of_the_dialog_is_needed(self):
        for name in ("Chaos Manifestation Entry Guide", "Do not show again for today.", "取消", "进入"):
            with self.subTest(missing=name):
                task = FakeTask(without(ENTRY_GUIDE, name))
                self.assertFalse(enter.handle_entry_guide(task))
                self.assertEqual([], task.pressed)

    def test_each_part_is_read_only_where_the_dialog_draws_it(self):
        for name, x, y in (("Chaos Manifestation Entry Guide", 0.501, 0.2), ("Do not show again for today.", 0.521, 0.8),
                           ("进入", 0.946, 0.923)):
            with self.subTest(moved=name):
                task = FakeTask(moved(ENTRY_GUIDE, name, x, y))
                self.assertFalse(enter.handle_entry_guide(task))
                self.assertEqual([], task.pressed)

    def test_no_other_screen_is_taken_for_it(self):
        for label, texts in {**OTHER_SCREENS, "record notice": RECORD_CARD}.items():
            with self.subTest(label):
                task = FakeTask(texts)
                self.assertFalse(enter.handle_entry_guide(task))
                self.assertEqual([], task.pressed)


class TestRecordNotice(unittest.TestCase):
    """The Exploration record notice after a run's last Leave, which the run took for an event option and tapped for ever."""

    def test_its_own_enter_hint_is_pressed(self):
        for label, texts, spot in (("Encouragement", RECORD_ENCOURAGEMENT, (0.501, 0.973)), ("combat card", RECORD_CARD, (0.502, 0.973))):
            with self.subTest(label):
                task = FakeTask(texts)
                self.assertTrue(enter.handle_record_notice(task))
                self.assertEqual([("进入", spot)], task.pressed)

    def test_the_line_and_the_hint_are_both_needed(self):
        for name in ("Unlocked Exploration Records appear as rewards in Chaos.", "进入"):
            with self.subTest(missing=name):
                task = FakeTask(without(RECORD_CARD, name))
                self.assertFalse(enter.handle_record_notice(task))
                self.assertEqual([], task.pressed)

    def test_each_is_read_only_where_the_notice_draws_it(self):
        for name, x, y in (("Unlocked Exploration Records appear as rewards in Chaos.", 0.499, 0.5), ("进入", 0.835, 0.877)):
            with self.subTest(moved=name):
                task = FakeTask(moved(RECORD_CARD, name, x, y))
                self.assertFalse(enter.handle_record_notice(task))
                self.assertEqual([], task.pressed)

    def test_no_other_screen_is_taken_for_it(self):
        for label, texts in {**OTHER_SCREENS, "Entry Guide": ENTRY_GUIDE}.items():
            with self.subTest(label):
                task = FakeTask(texts)
                self.assertFalse(enter.handle_record_notice(task))
                self.assertEqual([], task.pressed)


def stand_in(name, reached):
    """Stand in for an upstream handler under its name, recording when a frame reaches it and declining it."""
    def handler(task):
        reached.append(name)
        return False
    handler.__name__ = name
    return handler


class TestInstall(unittest.TestCase):
    """Both screens go ahead of the centred Confirm in Chaos's list, once, and in no other mode's."""

    def lists(self, reached):
        chaos = types.ModuleType("utils_chaos")
        chaos.PAGE_HANDLERS = [stand_in(name, reached) for name in ("handle_center_confirm", "handle_enter", "handle_event_task", "handle_dialogue")]
        sortie = types.ModuleType("utils_sortie")
        sortie.PAGE_HANDLERS = [stand_in("handle_center_confirm", reached), stand_in("handle_enter", reached)]
        return chaos, sortie

    def installed(self, reached):
        chaos, sortie = self.lists(reached)
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        with mock.patch.dict(sys.modules, {"utils_chaos": chaos, "utils_sortie": sortie}):
            try:
                for _ in range(INSTALLS):
                    enter.install_chaos_screens()
                return chaos.PAGE_HANDLERS[:], sortie.PAGE_HANDLERS[:]
            finally:
                for entries, before in saved:
                    entries[:] = before

    def test_only_chaos_gains_both_once_ahead_of_the_confirm(self):
        chaos, sortie = self.installed([])
        self.assertEqual(["handle_entry_guide", "handle_record_notice", "handle_center_confirm", "handle_enter", "handle_event_task", "handle_dialogue"],
                         [handler.__name__ for handler in chaos])
        self.assertEqual(["handle_center_confirm", "handle_enter"], [handler.__name__ for handler in sortie])

    def test_neither_screen_reaches_the_event_pass_or_the_speech_tap(self):
        for label, texts, handled_by in (("Entry Guide", ENTRY_GUIDE, "handle_entry_guide"), ("record notice", RECORD_ENCOURAGEMENT, "handle_record_notice")):
            with self.subTest(label):
                reached = []
                chaos, _ = self.installed(reached)
                task = FakeTask(texts)
                claimed = next((handler.__name__ for handler in chaos if handler(task)), None)
                self.assertEqual(handled_by, claimed)
                self.assertEqual([], reached)
                self.assertEqual(1, len(task.pressed))

    def test_the_screens_are_installed_on_every_task_load(self):
        registered = []
        with mock.patch.object(enter, "_patched", False), mock.patch.object(enter, "register", registered.append):
            enter.apply()
        self.assertIn(enter.install_chaos_screens, registered)


if __name__ == "__main__":
    unittest.main()
