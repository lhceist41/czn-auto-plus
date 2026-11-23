"""Check that no tap the bot did not choose spends account currency, deletes or retreats.

Upstream's stuck handler taps blind and its centred Confirm presses whatever dialog is up, so an Aether refill, a
pack offer or a save deletion nobody asked for would go through on either. The guard has to stop those and still
leave every in-run Credits confirm, and upstream's own asked-for deletion and retreat, alone.
"""

import contextlib
import inspect
import re
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
import utils_chaos  # noqa: E402
import utils_sortie  # noqa: E402
import utils_story  # noqa: E402

from src.en import dialog_ticks, enter, handlers, notify, reason, spend_guard  # noqa: E402
from src.en.handlers import WRAPS  # noqa: E402
from src.en.stuck import CLOCK  # noqa: E402
from tests.TestChaosEntry import DETAIL, FORMATION  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

CONFIRM_AT = (0.6, 0.77)
CANCEL_AT = (0.4, 0.77)
INSTALLS = 3


class FakeTask:
    """A mode looking at one screen, recording every input and stop."""

    def __init__(self, texts=(), icon=False, node_status=None, frozen_for=0):
        """Put boxes on the screen.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
            icon: Whether the shop's price icon is on screen.
            node_status: The run status, or None for a task without one, as in Story.
            frozen_for: How long the picture has looked the same, in seconds.
        """
        self.name = "自动卡厄思模式"
        self.width, self.height = WIDTH, HEIGHT
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.icon = icon
        if node_status is not None:
            self.node_status = node_status
        self._last_change_time = time.time() - frozen_for
        self.searched = []
        self.clicked = []
        self.clicked_at = []
        self.logged = []
        self.notifications = []
        self.disabled = False

    def find_one(self, feature_name, box=None, threshold=None):
        self.searched.append((feature_name, box))
        return object() if self.icon and feature_name == spend_guard.PRICE_ICON else None

    def box_of_screen(self, *region):
        return region

    def click_box(self, box):
        self.clicked.append(box.name)
        self.clicked_at.append(((box.x + box.width / 2) / self.width, (box.y + box.height / 2) / self.height))

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled = True

    def sleep(self, seconds):
        pass


class StoryMode(FakeTask):
    """Story, where `src/en/enter.py` leaves upstream's Enter as it is."""


def dialog(*lines, cancel="取消", **kwargs):
    """Build a task showing a centred dialog with a Confirm, as the catalog hands it over.

    Args:
        *lines: The dialog's text, one box per line.
        cancel: The Cancel button's text, or None for a dialog without one.
        **kwargs: Passed on to `FakeTask`.

    Returns:
        The task.
    """
    texts = [(line, 0.5, 0.3 + 0.06 * index) for index, line in enumerate(lines)]
    texts.append(("确认", *CONFIRM_AT))
    if cancel:
        texts.append((cancel, *CANCEL_AT))
    return FakeTask(texts, **kwargs)


def upstream_confirm(task):
    """Stand in for upstream's centred Confirm, which presses it.

    Args:
        task: The running task.

    Returns:
        True, as upstream does once it pressed.
    """
    task.clicked.append("确认")
    return True


def confirm(task):
    """Run the guarded Confirm on a task.

    Args:
        task: The running task.

    Returns:
        The guarded handler's answer.
    """
    return spend_guard.guarding_confirm(upstream_confirm)(task)


def fake_utils(stuck_log=None):
    """Build a stand-in for `utils` carrying both guarded handlers and the stuck detector.

    Args:
        stuck_log: The stuck handler to carry, or None for one that records being reached.

    Returns:
        A namespace.
    """
    def handle_stuck_log(task):
        task.clicked.append("blind tap")
        return False

    def handle_center_confirm(task):
        return upstream_confirm(task)

    def is_frame_stuck(task, stuck_threshold_seconds):
        return time.time() - task._last_change_time >= stuck_threshold_seconds

    return types.SimpleNamespace(handle_stuck_log=stuck_log or handle_stuck_log, handle_center_confirm=handle_center_confirm,
                                 is_frame_stuck=is_frame_stuck)


def every_marker():
    """List every marker word with its group.

    Returns:
        `(group, word)` pairs.
    """
    return [(group, word) for table in (spend_guard.MARKERS, spend_guard.UNCAPTURED) for group, words in table.items() for word in words]


# Rescue screens and dialogs as OCR read them off the Global client.
RESCUE_SCREENS = {
    "Selective Rescue results": [("Skip Tutorial", 0.88, 0.055), ("Confirm Rescue", 0.912, 0.702), ("Selective Rescue up to 20 times.", 0.622, 0.795),
                                 ("Save Log", 0.912, 0.81), ("Remaining Multis:", 0.723, 0.917), ("19", 0.819, 0.916), ("Re-Rescue", 0.911, 0.912)],
    "Save Rescue Records": [("Save Rescue Records", 0.501, 0.101), ("This is your current Rescue Record.", 0.519, 0.519),
                            ("No saved files available.", 0.528, 0.721), ("取消", 0.349, 0.89), ("Save", 0.664, 0.89)],
    "Rescue Records Loss": [("Rescue Records Loss", 0.502, 0.339), ("Your current Rescue Records are not saved.", 0.501, 0.448),
                            ("Unsaved records will be lost and cannot be recovered.", 0.502, 0.487),
                            ("Do you Want to proceed with Re-Rescue?", 0.501, 0.526), ("取消", 0.346, 0.654), ("确认", 0.667, 0.657)],
    "Change Saved Rescue Records": [("Change Saved Rescue Records", 0.503, 0.339), ("Re-Rescue will erase your current Rescue Records.", 0.5, 0.45),
                                    ("Unsaved Rescue Records cannot be recovered.", 0.501, 0.486),
                                    ("Do you Want to proceed with Re-Rescue?", 0.501, 0.526), ("取消", 0.347, 0.656), ("确认", 0.667, 0.656)],
    "ticket banner": [("营救", 0.116, 0.047), ("235", 0.709, 0.049), ("Shop", 0.109, 0.923), ("Agent Info", 0.389, 0.928),
                      ("Rescue 1 time(s)", 0.633, 0.913), ("Rescue 10 time(s)", 0.848, 0.914), ("10", 0.96, 0.914)],
    "Selective Rescue banner": [("营救", 0.116, 0.048), ("Special Signal Selective Rescue", 0.386, 0.255),
                                ("Ends when a Rescue record is", 0.33, 0.521), ("Remaining Rescue Count: 20", 0.883, 0.837),
                                ("Selective Rescue 10 time(s)", 0.849, 0.912), ("免费", 0.95, 0.912)],
    "event banner": [("营救", 0.116, 0.046), ("Free Rescue Count 0 / 20", 0.299, 0.646), ("Rescue Merit", 0.791, 0.751),
                     ("Rescue 1 time(s)", 0.634, 0.911), ("免费", 0.732, 0.914), ("Rescue 10 time(s)", 0.85, 0.912), ("免费", 0.949, 0.912)],
}
# The Lobby's own Rescue button, and a Chaos result whose mission is named for a rescue.
LOBBY = [("Sortie", 0.885, 0.267), ("θ Chaos", 0.883, 0.441), ("Combatants", 0.868, 0.617), ("EVENT", 0.823, 0.704), ("营救", 0.886, 0.705)]
CHAOS_RESULT = [("The Blue Pot", 0.681, 0.239), ("Chaos Size | Small", 0.693, 0.274), ("Rescue Renoa", 0.663, 0.358), ("Reward", 0.607, 0.627),
                ("确认", 0.918, 0.918)]
# Upstream's lists, by the names the guard cares about: Story presses a centred Confirm first, Chaos and Sortie after the stuck fallback.
STORY_ORDER = ("handle_center_confirm", "handle_stuck_log")
CHAOS_ORDER = ("handle_stuck_log", "handle_center_confirm")


def rescue_utils():
    """Build a stand-in for `utils` whose centred Confirm presses only a Confirm upstream would find.

    Returns:
        A namespace.
    """
    stand_in = fake_utils()

    def handle_center_confirm(task):
        if spend_guard.centred_confirm(task) is None:
            return False
        return upstream_confirm(task)

    stand_in.handle_center_confirm = handle_center_confirm
    return stand_in


@contextlib.contextmanager
def stand_in_mode(order):
    """Install the guard on a stand-in mode, and leave every handler list as it was afterwards.

    The install edits every list holding the anchors, the real modes' among them.

    Args:
        order: The stand-in's handler names, in upstream's order.

    Yields:
        The installed list.
    """
    saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
    mode = types.ModuleType("fake_mode_for_rescue_stop_test")
    stand_in = rescue_utils()
    mode.PAGE_HANDLERS = [getattr(stand_in, name) for name in order]
    sys.modules[mode.__name__] = mode
    try:
        spend_guard.install(stand_in)
        yield mode.PAGE_HANDLERS
    finally:
        sys.modules.pop(mode.__name__, None)
        for entries, before in saved:
            entries[:] = before


def run_screen(texts, order=STORY_ORDER, frozen_for=0):
    """Put a screen in front of an installed stand-in mode and let its list run.

    Args:
        texts: `(name, x, y)` triples.
        order: The stand-in's handler names.
        frozen_for: How long the picture has looked the same, in seconds.

    Returns:
        The task, and the name of the handler that claimed the frame or None.
    """
    task = FakeTask(texts, frozen_for=frozen_for)
    with stand_in_mode(order) as entries:
        claimed = next((handler.__name__ for handler in entries if handler(task)), None)
    return task, claimed


class TestConfirmGuard(unittest.TestCase):
    """The centred Confirm on a dialog that would spend outside the run, delete or retreat."""

    def assertStopped(self, task, answer, pressed):
        self.assertIs(True, answer)
        self.assertTrue(task.disabled)
        self.assertEqual(pressed, task.clicked)
        self.assertEqual(1, len(task.notifications))
        self.assertTrue(task.notifications[0].startswith("Stopped: a dialog would "))

    def assertConfirmed(self, task, answer):
        self.assertIs(True, answer)
        self.assertFalse(task.disabled)
        self.assertEqual(["确认"], task.clicked)
        self.assertEqual([], task.notifications)

    def test_an_aether_refill_is_cancelled_and_the_run_stopped(self):
        """Sortie's own Aether handler matches a Chinese title the catalog never produces, so this dialog reaches the Confirm."""
        task = dialog("Aether Supply", "Not enough Aether. Refill now?")
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.ACCOUNT, task.notifications[0])

    def test_each_account_marker_stops_in_both_languages(self):
        words = [word for group, word in every_marker() if group == spend_guard.ACCOUNT]
        self.assertTrue(any(re.search("[一-鿿]", word) for word in words))
        self.assertTrue(any(word.isascii() for word in words))
        for word in words:
            for shown in (f"Use 1 {word}?", f"Use 1 {word.upper()}?", f"Use 1 {word.replace(' ', '')}?"):
                with self.subTest(shown=shown):
                    task = dialog(shown)
                    self.assertStopped(task, confirm(task), ["取消"])

    def test_a_real_money_price_stops_the_run(self):
        for price in ("US$4.99", "$ 9.99", "€4,99", "£3.49", "₩ 5,500", "KRW 5500", "4.99 USD 4.99", "1.200 USD", "600 JPY", "CNY 30"):
            with self.subTest(price=price):
                task = dialog("Starter Pack", price, cancel="Cancel")
                self.assertStopped(task, confirm(task), ["Cancel"])
                self.assertIn(spend_guard.MONEY, task.notifications[0])

    def test_a_hyphenated_give_up_stops_the_run(self):
        task = dialog("Give-Up this run?", node_status={})
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.RETREAT, task.notifications[0])

    def test_charge_reason_split_over_two_lines_stops_the_run(self):
        task = dialog("Charge", "Reason?")
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.ACCOUNT, task.notifications[0])

    def test_rescue_anchor_split_over_two_lines_stops_the_run(self):
        """OCR hands the boxes back in no promised order, so the lines are joined top to bottom."""
        task = dialog("Use 1 Rescue", "Anchor?")
        task.all_texts.reverse()
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.ACCOUNT, task.notifications[0])

    def test_a_euro_price_after_the_number_stops_the_run(self):
        task = dialog("Daily Pack", "4,99 €")
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.MONEY, task.notifications[0])

    def test_a_won_price_after_the_number_stops_the_run(self):
        task = dialog("Daily Pack", "1,200 KRW")
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.MONEY, task.notifications[0])

    def test_a_yen_price_stops_the_run(self):
        task = dialog("Daily Pack", "¥600")
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.MONEY, task.notifications[0])

    def test_harmless_lines_that_join_into_no_marker_still_pass(self):
        task = dialog("Take the", "alternative", "reward instead?", "75 Credits", node_status={})
        self.assertConfirmed(task, confirm(task))

    def test_a_purchase_priced_in_run_credits_is_confirmed(self):
        task = dialog("购买", "Purchase this card?", icon=True)
        self.assertConfirmed(task, confirm(task))
        self.assertEqual([(spend_guard.PRICE_ICON, spend_guard.CONFIRM_REGION)], task.searched)

    def test_a_purchase_without_a_price_icon_stops_the_run(self):
        task = dialog("Buy", "Purchase this package?")
        self.assertStopped(task, confirm(task), ["取消"])
        self.assertIn(spend_guard.PURCHASE, task.notifications[0])

    def test_a_save_deletion_the_run_asked_for_is_confirmed(self):
        task = dialog("Delete this Save Data?", node_status={spend_guard.DELETE_ASKED: time.time()})
        self.assertConfirmed(task, confirm(task))

    def test_a_save_deletion_nobody_asked_for_stops_the_run(self):
        for status in ({}, {spend_guard.RETREAT_ASKED: True}, None):
            with self.subTest(status=status):
                task = dialog("Delete this Save Data?", node_status=status)
                self.assertStopped(task, confirm(task), ["取消"])
                self.assertIn(spend_guard.DELETION, task.notifications[0])

    def test_a_retreat_after_escape_is_confirmed(self):
        for line in ("逃脱", "Retreat from this run?"):
            with self.subTest(line=line):
                task = dialog(line, node_status={spend_guard.RETREAT_ASKED: True})
                self.assertConfirmed(task, confirm(task))

    def test_an_unasked_retreat_stops_the_run(self):
        for status in ({}, {spend_guard.DELETE_ASKED: time.time()}, None):
            with self.subTest(status=status):
                task = dialog("Retreat from this run?", node_status=status)
                self.assertStopped(task, confirm(task), ["取消"])
                self.assertIn(spend_guard.RETREAT, task.notifications[0])

    def test_harmless_confirms_still_pass(self):
        """The in-run Credits flows are what a Chaos run is made of, so stopping on one would stop most runs."""
        for name, lines in (
            ("Skip", ("Skip this story?",)),
            ("end of turn", ("End your turn?", "Some cards can still be used.")),
            ("Extract", ("Extract this equipment?", "Receive 30 Credits.")),
            ("shop removal", ("Remove this card?", "75 Credits")),
            ("substitute reward", ("This reward cannot be received.", "Take the alternative instead?")),
            ("Meditation", ("Meditate for 50 Credits?",)),
        ):
            with self.subTest(dialog=name):
                task = dialog(*lines, node_status={})
                self.assertConfirmed(task, confirm(task))

    def test_no_centred_confirm_means_no_scan(self):
        for name, texts in (
            ("no Confirm", [("Buy", 0.5, 0.4), ("Aether", 0.5, 0.5)]),
            ("Confirm below the band", [("Buy", 0.5, 0.4), ("Aether", 0.5, 0.5), ("确认", 0.5, 0.95)]),
            ("Confirm inside other text", [("Buy", 0.5, 0.4), ("Aether", 0.5, 0.5), ("确认购买", 0.5, 0.77)]),
        ):
            with self.subTest(screen=name):
                task = FakeTask(texts)
                self.assertIsNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task), "upstream's own answer")
                self.assertEqual([], task.searched)
                self.assertFalse(task.disabled)

    def test_a_dialog_without_cancel_stops_without_input(self):
        task = dialog("Aether Supply", cancel=None)
        self.assertStopped(task, confirm(task), [])

    def test_a_cancel_outside_the_dialog_buttons_is_not_pressed(self):
        task = dialog("Aether Supply", cancel=None)
        task.all_texts.append(FakeBox("取消", 0.5, 0.3))
        self.assertStopped(task, confirm(task), [])

    def test_a_counter_in_the_top_bar_is_ignored(self):
        """The mode screens count Aether in the top bar, which sits outside upstream's band."""
        task = dialog("Skip this story?", node_status={})
        task.all_texts.append(FakeBox("Aether 1,200", 0.8, 0.04))
        task.all_texts.append(FakeBox("$12", 0.9, 0.04))
        self.assertConfirmed(task, confirm(task))

    def test_a_back_out_ahead_still_claims_its_dialog(self):
        """`src/en/reason.py` declines the Charge Reason dialog ahead of the Confirm, which the guard must leave to it."""
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        mode = types.ModuleType("fake_sortie_for_spend_guard_test")
        mode.PAGE_HANDLERS = [lambda task: False]
        mode.PAGE_HANDLERS[0].__name__ = "handle_close_page"
        stand_in = fake_utils()
        mode.PAGE_HANDLERS.append(stand_in.handle_center_confirm)
        sys.modules[mode.__name__] = mode
        clicks = []
        sortie = types.SimpleNamespace(_move_and_click=lambda task, x, y: clicks.append((x, y)))
        try:
            spend_guard.install(stand_in)
            handlers.insert_before("handle_center_confirm", reason.charge_reason_handler(sortie))
            task = FakeTask([("补充理性", 0.5, 0.17), ("确认", *CONFIRM_AT), ("取消", *CANCEL_AT)], node_status={})
            task.sleep = lambda seconds: None
            claimed_by = next(handler.__name__ for handler in mode.PAGE_HANDLERS if handler(task))
        finally:
            sys.modules.pop(mode.__name__, None)
            for entries, before in saved:
                entries[:] = before
        self.assertEqual("handle_charge_reason", claimed_by)
        self.assertEqual([reason.DECLINE_POINT], clicks)
        self.assertFalse(task.disabled)
        self.assertEqual([], task.clicked)
        unguarded = FakeTask([("补充理性", 0.5, 0.17), ("确认", *CONFIRM_AT)])
        confirm(unguarded)
        self.assertTrue(unguarded.disabled, "without the back-out the guard stops the run")

    def test_the_flags_the_guard_trusts_are_still_set_upstream(self):
        """Read from the module source, since another test in the same run may stand a wrapper in for either handler."""
        for module, flag in ((utils_chaos, spend_guard.DELETE_ASKED), (utils, spend_guard.RETREAT_ASKED)):
            with self.subTest(flag=flag):
                self.assertRegex(inspect.getsource(module), rf"node_status\[['\"]{flag}['\"]\]\s*=")

    def test_the_confirm_band_is_still_upstreams(self):
        self.assertIn(f"confirm_region = {spend_guard.CONFIRM_REGION}", inspect.getsource(utils))


class TestBlindTaps(unittest.TestCase):
    """The stuck handler's random taps on a screen that can spend or discard."""

    def run_stuck(self, task, utils_module=None):
        utils_module = utils_module or fake_utils()
        return spend_guard.guarding_taps(utils_module.handle_stuck_log, utils_module)(task)

    def test_a_shop_screen_gets_no_blind_tap(self):
        task = FakeTask([("德朗商店", 0.1, 0.05), ("Ascending Strike", 0.3, 0.4)], frozen_for=15)
        for _ in range(3):
            self.assertIs(False, self.run_stuck(task))
        self.assertEqual([], task.clicked)
        self.assertEqual(1, sum("not tapping at random" in line for line in task.logged), "once per freeze")

    def test_every_marker_blocks_in_both_languages(self):
        pairs = every_marker()
        self.assertEqual({spend_guard.ACCOUNT, spend_guard.PURCHASE, spend_guard.DELETION, spend_guard.RETREAT, spend_guard.IN_RUN},
                         {group for group, _ in pairs})
        for group, word in pairs:
            with self.subTest(word=word):
                task = FakeTask([(f"x {word} x", 0.5, 0.95)], frozen_for=15)
                self.assertIs(False, self.run_stuck(task))
                self.assertEqual([], task.clicked)
        for price in ("US$4.99", "₩ 5,500"):
            with self.subTest(price=price):
                task = FakeTask([(price, 0.5, 0.5)], frozen_for=15)
                self.assertIs(False, self.run_stuck(task))
                self.assertEqual([], task.clicked)

    def test_a_marker_split_over_two_boxes_blocks_the_tap(self):
        task = FakeTask([("Communication", 0.5, 0.4), ("Pass x1", 0.5, 0.45)], frozen_for=15)
        self.assertIs(False, self.run_stuck(task))
        self.assertEqual([], task.clicked)

    def test_a_price_icon_blocks_the_tap(self):
        task = FakeTask([("Ascending Strike", 0.3, 0.4)], icon=True, frozen_for=15)
        self.assertIs(False, self.run_stuck(task))
        self.assertEqual([], task.clicked)
        self.assertEqual([(spend_guard.PRICE_ICON, None)], task.searched)

    def test_a_plain_screen_keeps_upstreams_recovery(self):
        task = FakeTask([("Ascending Strike", 0.3, 0.4)], frozen_for=15)
        self.run_stuck(task)
        self.assertEqual(["blind tap"], task.clicked)

    def test_the_guard_keeps_upstreams_answer(self):
        for answer in (True, False):
            with self.subTest(answer=answer):
                task = FakeTask([("Ascending Strike", 0.3, 0.4)])
                self.assertIs(answer, self.run_stuck(task, fake_utils(lambda task, answer=answer: answer)))

    def test_notify_still_reports_a_guarded_screen(self):
        """notify renames the list entry, so the guard has to be installed first and sit inside it."""
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        mode = types.ModuleType("fake_chaos_for_spend_guard_test")
        stand_in = fake_utils()
        mode.PAGE_HANDLERS = [stand_in.handle_stuck_log]
        sys.modules[mode.__name__] = mode
        try:
            for _ in range(INSTALLS):
                spend_guard.install(stand_in)
                # notify's own install, which wraps whatever the module carries and replaces the entry by name.
                handlers.replace("handle_stuck_log", notify.stuck(stand_in.handle_stuck_log))
            entry = mode.PAGE_HANDLERS[0]
        finally:
            sys.modules.pop(mode.__name__, None)
            for entries, before in saved:
                entries[:] = before
        task = FakeTask([("德朗商店", 0.1, 0.05)], frozen_for=notify.STUCK_SECONDS + 5)
        self.assertIs(False, entry(task))
        self.assertEqual([], task.clicked)
        self.assertEqual(1, len(task.notifications))
        self.assertIn("Stuck on the same screen", task.notifications[0])


class TestRescueStop(unittest.TestCase):
    """A Rescue screen or dialog, whose pulls and records are the user's to choose."""

    def assertStoppedWithoutInput(self, task, claimed):
        self.assertEqual("handle_rescue_screen", claimed)
        self.assertTrue(task.disabled)
        self.assertEqual([], task.clicked)
        self.assertEqual(1, len(task.notifications))
        self.assertTrue(task.notifications[0].startswith("Stopped on the Rescue screen"))

    def assertNotStopped(self, task, claimed):
        self.assertNotEqual("handle_rescue_screen", claimed)
        self.assertFalse(task.disabled)
        self.assertEqual([], task.notifications)

    def test_every_rescue_screen_stops_the_run_without_input(self):
        for order in (STORY_ORDER, CHAOS_ORDER):
            for name, texts in RESCUE_SCREENS.items():
                with self.subTest(screen=name, order=order):
                    self.assertStoppedWithoutInput(*run_screen(texts, order, frozen_for=15))

    def test_each_rescue_phrase_stops_however_ocr_spaces_it(self):
        for marker in spend_guard.RESCUE_MARKERS:
            for shown in (marker, marker.upper(), marker.replace(" ", "").replace("-", ""), marker.replace(" ", "-"), f"Use {marker}?"):
                with self.subTest(shown=shown):
                    self.assertStoppedWithoutInput(*run_screen([(shown, 0.5, 0.5)]))

    def test_the_rescue_header_stops_the_run(self):
        for header in ("营救", "Rescue"):
            with self.subTest(header=header):
                self.assertStoppedWithoutInput(*run_screen([(header, 0.116, 0.047)]))

    def test_the_lobby_rescue_button_does_not_stop_the_run(self):
        task, claimed = run_screen(LOBBY)
        self.assertNotStopped(task, claimed)
        self.assertIsNone(spend_guard.rescue_marker(task))

    def test_a_mission_named_rescue_does_not_stop_the_run(self):
        task, claimed = run_screen(CHAOS_RESULT, CHAOS_ORDER)
        self.assertNotStopped(task, claimed)
        self.assertIsNone(spend_guard.rescue_marker(task))

    def test_a_line_that_runs_a_word_into_rescue_does_not_stop_the_run(self):
        """Folded the way the other markers are, "were rescued" would read as Re-Rescue."""
        for line in ("You were rescued by Renoa.", "Hold on before rescue arrives.", "A carefree rescuer"):
            with self.subTest(line=line):
                task, claimed = run_screen([(line, 0.5, 0.8)], frozen_for=15)
                self.assertNotStopped(task, claimed)
                self.assertEqual(["blind tap"], task.clicked, "upstream's recovery stays")

    def test_a_confirm_split_from_rescue_on_the_results_grid_stops_before_it_is_pressed(self):
        """Should OCR split Confirm Rescue, the band holds nothing the Confirm guard reads, and the Confirm would end the Selective Rescue."""
        texts = [entry for entry in RESCUE_SCREENS["Selective Rescue results"] if entry[0] != "Confirm Rescue"]
        texts += [("确认", 0.895, 0.702), ("营救", 0.935, 0.702)]
        self.assertIsNone(spend_guard.risky_confirm(FakeTask(texts)))
        self.assertStoppedWithoutInput(*run_screen(texts))

    def test_a_rescue_screen_gets_no_blind_tap(self):
        stand_in = fake_utils()
        for name, texts in RESCUE_SCREENS.items():
            with self.subTest(screen=name):
                task = FakeTask(texts, frozen_for=15)
                self.assertIs(False, spend_guard.guarding_taps(stand_in.handle_stuck_log, stand_in)(task))
                self.assertEqual([], task.clicked)

    def test_the_rescue_stop_runs_ahead_of_the_centred_confirm_in_every_mode(self):
        """Chaos and Sortie stop on the Rescue header themselves, but only after the centred Confirm had its turn."""
        modes = (utils_story, utils_chaos, utils_sortie)
        # Other tests stand modules of their own in for the modes, or take them out, and the install reaches only what is loaded.
        with mock.patch.dict(sys.modules, {module.__name__: module for module in modes}), stand_in_mode(STORY_ORDER):
            names = {module.__name__: [handler.__name__ for handler in module.PAGE_HANDLERS] for module in modes}
        for module, listed in names.items():
            with self.subTest(mode=module):
                self.assertEqual(1, listed.count("handle_rescue_screen"))
                self.assertLess(listed.index("handle_rescue_screen"), listed.index("handle_center_confirm"))
        for module in (utils_chaos.__name__, utils_sortie.__name__):
            with self.subTest(mode=module):
                self.assertLess(names[module].index("handle_rescue_screen"), names[module].index("handle_non_battle_page"))


# Story's skip dialog as OCR read it off the Global client, its synopsis lines given by `skip_dialog`.
SKIP_TITLE = ("Do you want to skip the current dialogue?", 0.5, 0.212)
SKIP_SYNOPSIS_AT = (0.294, 0.331, 0.369)
SKIP_FOOT = [("Main Characters", 0.5, 0.444), ("Do not show until next login", 0.519, 0.677), ("取消", 0.348, 0.786), ("确认", 0.662, 0.786)]
SKIP_SYNOPSES = (
    ("Renoa collapses and loses consciousness immediately after returning to the SS Nightmare. Elaine says it is",
     "simply the tension leaving her body, and recommends that the Captain also rest while Renoa is being", "treated."),
    ("The group discovers Renoa lying in a mysterious space, clutching a pocket watch. They attempt to Rescue",
     "her and return, but Deforsa appears and the group faces total annihilation. At that moment, the Captain",
     "uses a mysterious power to reverse time and defeats Deforsa."),
)


def skip_dialog(*synopsis, title=SKIP_TITLE, foot=SKIP_FOOT):
    """Build a task showing Story's skip dialog.

    Args:
        *synopsis: The synopsis lines, top to bottom, at most three.
        title: The title box, or None for a dialog without it.
        foot: The boxes under the synopsis.

    Returns:
        The task.
    """
    texts = [title] if title else []
    texts += [(line, 0.5, y) for line, y in zip(synopsis, SKIP_SYNOPSIS_AT)]
    return FakeTask([*texts, *foot])


class TestSkipSynopsis(unittest.TestCase):
    """The skip dialog retells the scene, and a scene where someone retreats or buys something is no dialog that does."""

    def test_captured_synopses_are_confirmed(self):
        for synopsis in SKIP_SYNOPSES:
            with self.subTest(synopsis=synopsis[0]):
                task = skip_dialog(*synopsis)
                self.assertIsNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task))
                self.assertEqual(["确认"], task.clicked)

    def test_a_marker_in_the_synopsis_is_confirmed(self):
        for line in ("the group must retreat before the Chaos closes in.", "They Abandon the ship and Give Up the chase.",
                     "Renoa wants to buy a pocket watch.", "a Purchase made long ago", "The records Delete themselves.",
                     "Elaine can Erase a memory."):
            for row in range(len(SKIP_SYNOPSIS_AT)):
                with self.subTest(line=line, row=row):
                    synopsis = ["A sudden ambush puts the group in danger,", "the Captain's Life Core has malfunctioned,",
                                "and is left alone inside the Chaos."]
                    synopsis[row] = line
                    task = skip_dialog(*synopsis)
                    self.assertIsNone(spend_guard.risky_confirm(task))
                    self.assertIs(True, confirm(task))
                    self.assertEqual(["确认"], task.clicked)
                    self.assertFalse(task.disabled)

    def test_the_same_line_on_any_other_dialog_still_stops(self):
        line = "the group must retreat before the Chaos closes in."
        cases = {
            "no title": skip_dialog(line, title=None),
            "another title": skip_dialog(line, title=("Leave this battle?", 0.5, 0.212)),
            "no label": skip_dialog(line, foot=[box for box in SKIP_FOOT if not box[0].startswith("Do not show")]),
            "the label where the Rescue dialog draws it": skip_dialog(
                line, foot=[(name, x, 0.558 if name.startswith("Do not show") else y) for name, x, y in SKIP_FOOT]),
            "no Cancel": skip_dialog(line, foot=[box for box in SKIP_FOOT if box[0] != "取消"]),
            "buttons where another dialog draws them": skip_dialog(
                line, foot=[(name, x, 0.669 if name in ("取消", "确认") else y) for name, x, y in SKIP_FOOT]),
        }
        for case, task in cases.items():
            with self.subTest(case=case):
                self.assertEqual(spend_guard.RETREAT, spend_guard.risky_confirm(task)[0])
                self.assertIs(True, confirm(task))
                self.assertTrue(task.disabled)

    def test_a_marker_outside_the_synopsis_still_stops(self):
        for name, extra in (("under the synopsis", ("Use 1 Aether?", 0.5, 0.55)), ("in the title", ("Retreat?", 0.5, 0.24)),
                            ("a price", ("US$4.99", 0.5, 0.6))):
            with self.subTest(where=name):
                task = skip_dialog(*SKIP_SYNOPSES[0])
                task.all_texts.append(FakeBox(*extra))
                self.assertIsNotNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task))
                self.assertTrue(task.disabled)

    def test_the_skip_dialog_is_told_apart_by_the_same_whitelist_as_its_tick(self):
        self.assertIn(spend_guard.SKIP_DIALOG, [dialog for dialog, _ in dialog_ticks.TICKS])


# The compact skip dialog as OCR read it off the Global client: an Ark City episode's ending, the same frame after its box
# was ticked, and an Excursion story. The speaker and the subtitle line under the dialog stay readable.
COMPACT_TOP = [("Do you want to skip this story?", 0.501, 0.413), ("Ctrl", 0.393, 0.492), ("Do not show until next login", 0.520, 0.530),
               ("进入", 0.537, 0.594), ("取消", 0.348, 0.631), ("确认", 0.667, 0.631)]
COMPACT_SPEAKER = ("Nono", 0.118, 0.753)
COMPACT_SUBTITLE_AT = (0.426, 0.837)
COMPACT_SCREENS = (
    [*COMPACT_TOP, COMPACT_SPEAKER, ("So, what do you think? A safer Ark City, brought to you by Nono and Elaine!", *COMPACT_SUBTITLE_AT),
     ("Space", 0.936, 0.912)],
    [("Y①", 0.801, 0.050), ("Do you want to skip this story?", 0.501, 0.412), ("Ctrl", 0.392, 0.492),
     ("Do not show until next login", 0.520, 0.530), ("ESC", 0.216, 0.593), ("取消", 0.348, 0.631), ("进入", 0.536, 0.594),
     ("确认", 0.667, 0.631), COMPACT_SPEAKER,
     ("So, what do you think? A safer Ark City, brought to you by Nono and Elaine!", *COMPACT_SUBTITLE_AT), ("Space", 0.937, 0.912)],
    [("DD=", 0.855, 0.049), ("Do you want to skip this story?", 0.501, 0.412), ("Ctrl", 0.393, 0.493),
     ("Do not show until next login", 0.520, 0.530), ("ESC", 0.216, 0.593), ("取消", 0.347, 0.631), ("进入", 0.537, 0.594),
     ("确认", 0.666, 0.631), ("Selena", 0.126, 0.753), ("Captain, if you're everin need of some plushies, please tell me.", 0.370, 0.835),
     ("Space", 0.935, 0.911)],
)
# Lines a story could well say, each holding a word the guard stops on anywhere else.
RISKY_SUBTITLES = ("We have to retreat before the Chaos closes in.", "Let's buy some snacks on Main Street.",
                   "The Aether readings are off the chart.", "Don't give up now, Captain!", "a Purchase made long ago",
                   "Elaine can Erase a memory.", "It only cost US$4.99!")
# The Loot dialog draws the same label, box and button row a little lower than the compact dialog's title.
LOOT = [("Settlement", 0.59, 0.065), ("Loot", 0.539, 0.139),
        ("There is additional loot available. Continue without using Loot Certification Card?", 0.502, 0.412),
        ("Ctrl", 0.393, 0.492), ("Do not show until next login", 0.521, 0.531), ("ESC", 0.214, 0.593), ("进入", 0.535, 0.593),
        ("取消", 0.347, 0.632), ("确认", 0.667, 0.63), ("Temporary Return", 0.623, 0.916), ("继续", 0.927, 0.915)]


def compact_dialog(subtitle, top=COMPACT_TOP):
    """Build a task showing the compact skip dialog over a line of dialogue.

    Args:
        subtitle: The dialogue line under the dialog.
        top: The dialog's own boxes.

    Returns:
        The task.
    """
    return FakeTask([*top, COMPACT_SPEAKER, (subtitle, *COMPACT_SUBTITLE_AT), ("Space", 0.936, 0.912)])


class TestCompactSkip(unittest.TestCase):
    """The compact skip dialog leaves the scene's dialogue showing under it, and a line of dialogue is no dialog that spends."""

    def test_captured_compact_dialogs_are_confirmed(self):
        for screen in COMPACT_SCREENS:
            with self.subTest(subtitle=screen[-2][0]):
                task = FakeTask(screen)
                self.assertIsNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task))
                self.assertEqual(["确认"], task.clicked)

    def test_a_marker_in_the_dialogue_under_it_is_confirmed(self):
        for line in RISKY_SUBTITLES:
            with self.subTest(line=line):
                task = compact_dialog(line)
                self.assertIsNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task))
                self.assertEqual(["确认"], task.clicked)
                self.assertFalse(task.disabled)

    def test_a_marker_in_the_speaker_name_is_confirmed(self):
        task = FakeTask([*COMPACT_TOP, ("Retreat Officer", 0.118, 0.753), ("Over here!", *COMPACT_SUBTITLE_AT)])
        self.assertIsNone(spend_guard.risky_confirm(task))

    def test_a_marker_inside_the_dialog_still_stops(self):
        for where, extra in (("under the title", ("Use 1 Aether?", 0.5, 0.45)), ("beside the title", ("Retreat?", 0.62, 0.413)),
                             ("a price by the buttons", ("US$4.99", 0.5, 0.6))):
            with self.subTest(where=where):
                task = compact_dialog(COMPACT_SCREENS[0][-2][0])
                task.all_texts.append(FakeBox(*extra))
                self.assertIsNotNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task))
                self.assertEqual(["取消"], task.clicked)
                self.assertTrue(task.disabled)

    def test_the_same_line_on_another_dialog_with_the_same_button_row_still_stops(self):
        line = RISKY_SUBTITLES[0]
        self.assertIsNone(spend_guard.risky_confirm(FakeTask(LOOT)), "the Loot dialog itself is safe to confirm")
        cases = {
            "the Loot dialog": FakeTask([*LOOT, COMPACT_SPEAKER, (line, *COMPACT_SUBTITLE_AT)]),
            "no title": compact_dialog(line, [box for box in COMPACT_TOP if not box[0].startswith("Do you want")]),
            "the large dialog's title": compact_dialog(
                line, [(("Do you want to skip the current dialogue?" if name.startswith("Do you want") else name), x, y)
                       for name, x, y in COMPACT_TOP]),
            "the title where the large dialog draws it": compact_dialog(
                line, [(name, x, 0.212 if name.startswith("Do you want") else y) for name, x, y in COMPACT_TOP]),
            "no label": compact_dialog(line, [box for box in COMPACT_TOP if not box[0].startswith("Do not show")]),
            "no Cancel": compact_dialog(line, [box for box in COMPACT_TOP if box[0] != "取消"]),
            "buttons where the large dialog draws them": compact_dialog(
                line, [(name, x, 0.786 if name in ("取消", "确认") else y) for name, x, y in COMPACT_TOP]),
        }
        for case, task in cases.items():
            with self.subTest(case=case):
                self.assertEqual(spend_guard.RETREAT, spend_guard.risky_confirm(task)[0])
                self.assertIs(True, confirm(task))
                self.assertTrue(task.disabled)

    def test_the_compact_dialog_is_told_apart_by_the_same_whitelist_as_its_tick(self):
        self.assertIn(spend_guard.COMPACT_SKIP_DIALOG, [dialog for dialog, _ in dialog_ticks.TICKS])


# The Card Reward skip dialog as OCR read it off the Global client, with the offered cards' text still readable under
# its buttons, one of them a card that builds Crystallization.
CARD_REWARD_SKIP = [
    ("543 /543", 0.211, 0.036), ("194", 0.763, 0.050), ("Q", 0.959, 0.079), ("卡牌奖励", 0.501, 0.130), ("请选择1张获得的卡牌", 0.892, 0.133),
    ("Tap and hold the card to view its details.", 0.499, 0.208), ("Rewards cannot be obtained if you choose to skip.", 0.500, 0.413),
    ("Are you sure you want to skip it?", 0.501, 0.454), ("ESC", 0.215, 0.594), ("取消", 0.348, 0.632), ("进入", 0.535, 0.593),
    ("•", 0.531, 0.631), ("确认", 0.667, 0.631), ("Damage", 0.275, 0.712), ("50% Damage× 3", 0.505, 0.708),
    ("2 Crystallization", 0.276, 0.746), ("Create2 Overload in", 0.732, 0.710), ("Draw Pile", 0.735, 0.745), ("D", 0.035, 0.890),
    ("F1", 0.652, 0.891), ("跳过", 0.747, 0.930), ("进入", 0.835, 0.892), ("Avg. Sig. Card Cost", 0.147, 0.927), ("0.7", 0.261, 0.928),
    ("确认", 0.906, 0.931),
]
# Card text holding the currency's name inside another word, from `game_text.py` and `game_data.py`.
CARD_LINES = ("2 Crystallization", "4 Crystallization", "3 Crystallization", "2Crystallization", "Crystallization", "Foggy Crystal Ball",
              "Harmonization: Foggy Crystal Ball", "Foggy CrystalBall")
# Crystals as a price or a refill, the paid Rescue dialog's line and the Lobby's top-up banner among them, and prices OCR
# runs on into the next word or count.
CRYSTAL_SPENDS = ("Spend 1600 Crystals to make the purchase?", "Not enough Aether. Refill with Crystals?", "Use 300 Crystal?",
                  "Crystal x100", "Crystalx100", "300Crystals", "Crystal Bonuses", "CRYSTALS")


class TestCardText(unittest.TestCase):
    """A card's text that only holds the currency's name is no spend, and every Crystal price still is."""

    def test_the_card_reward_skip_dialog_is_confirmed_over_a_crystallization_card(self):
        task = FakeTask(CARD_REWARD_SKIP, node_status={})
        self.assertIsNone(spend_guard.risky_confirm(task))
        self.assertIs(True, confirm(task))
        self.assertEqual(["确认"], task.clicked)
        self.assertFalse(task.disabled)
        self.assertEqual([], task.notifications)

    def test_card_text_is_no_spend_on_a_dialog_or_for_a_blind_tap(self):
        for line in CARD_LINES:
            with self.subTest(line=line):
                task = dialog("Are you sure you want to skip it?", line, node_status={})
                self.assertIsNone(spend_guard.risky_confirm(task))
                self.assertFalse(spend_guard.spends_or_discards(FakeTask([(line, 0.5, 0.5)])))

    def test_a_crystal_spend_still_stops_over_the_same_card(self):
        for line in CRYSTAL_SPENDS:
            with self.subTest(line=line):
                task = FakeTask([*CARD_REWARD_SKIP, (line, 0.5, 0.36)], node_status={})
                self.assertIs(True, confirm(task))
                self.assertTrue(task.disabled)
                self.assertEqual(["取消"], task.clicked)
                self.assertIn(spend_guard.ACCOUNT, task.notifications[0])

    def test_a_crystal_spend_blocks_the_blind_tap(self):
        for line in CRYSTAL_SPENDS:
            with self.subTest(line=line):
                self.assertTrue(spend_guard.spends_or_discards(FakeTask([("2 Crystallization", 0.3, 0.7), (line, 0.5, 0.5)])))

    def test_a_card_word_only_spares_the_marker_it_starts_with(self):
        """Crystallization in one line and a Crystal price in the next still read as a spend, joined or apart."""
        texts = spend_guard.read_texts([FakeBox("2 Crystallization", 0.3, 0.4), FakeBox("30 Crystals", 0.3, 0.5)])
        self.assertEqual("crystal", spend_guard.marker_in(texts, spend_guard.ACCOUNT))
        self.assertEqual("crystal", spend_guard.marker_in(["2crystallization30crystals"], spend_guard.ACCOUNT))


# The same dialog over Select Card Space as OCR read it, Confirm read cleanly, with a card's text showing through its
# button strip on the left.
SELECT_CARD_SPACE_SKIP = [
    ("1", 0.042, 0.048), ("请选择1张转换的卡牌", 0.213, 0.047), ("Select Card Space", 0.876, 0.030), ("View Card Info Caps", 0.868, 0.066),
    ("Strike", 0.545, 0.159), ("基础攻击", 0.567, 0.184), ("Order's Bible Page", 0.165, 0.246), ("技能", 0.125, 0.284),
    ("Rewards cannot be obtained if you choose to skip.", 0.501, 0.413), ("Are you sure you want to skip it?", 0.501, 0.454),
    ("ESC", 0.215, 0.594), ("进入", 0.536, 0.594), ("Exhaust", 0.144, 0.649), ("取消", 0.347, 0.632), ("确认", 0.664, 0.634),
    ("when this card is", 0.146, 0.689), ("Exhausted, Draw 2", 0.146, 0.720), ("Draw 2 Basic Card(s) of", 0.566, 0.784),
    ("跳过", 0.768, 0.931), ("Convert", 0.936, 0.931),
]
# Card names and text that hold a delete or retreat word, from `game_text.py`, and the Crystallization line again.
DIALOG_CARD_LINES = {"Retreat": spend_guard.RETREAT, "Elimination": spend_guard.DELETION, "Delete Commitment": spend_guard.DELETION,
                     "2 Crystallization": None}
# What the reward skip dialog's own lines would say if it ever asked for one of these, each inside its band.
DIALOG_SPENDS = {"Spend 1600 Crystals to make the purchase?": spend_guard.ACCOUNT, "Pay $4.99 to skip?": spend_guard.MONEY,
                 "Retreat from the run?": spend_guard.RETREAT, "Delete this save data?": spend_guard.DELETION}


def replaced(frame, old, new):
    """Swap one box's text in a captured frame.

    Args:
        frame: `(name, x, y)` triples.
        old: The text to replace.
        new: Its replacement.

    Returns:
        The new triples.
    """
    return [(new if name == old else name, x, y) for name, x, y in frame]


class TestRewardSkipDialog(unittest.TestCase):
    """The reward skip dialog is judged by its own lines, never by the cards it is drawn over."""

    def test_card_text_under_the_card_reward_skip_dialog_is_confirmed(self):
        for line in DIALOG_CARD_LINES:
            with self.subTest(line=line):
                task = FakeTask(replaced(CARD_REWARD_SKIP, "2 Crystallization", line), node_status={})
                self.assertTrue(spend_guard.shown(task, spend_guard.REWARD_SKIP_DIALOG))
                self.assertIsNone(spend_guard.risky_confirm(task))
                self.assertIs(True, confirm(task))
                self.assertEqual(["确认"], task.clicked)
                self.assertFalse(task.disabled)

    def test_card_text_through_the_button_strip_is_confirmed(self):
        for line in DIALOG_CARD_LINES:
            with self.subTest(line=line):
                task = FakeTask(replaced(SELECT_CARD_SPACE_SKIP, "Exhaust", line), node_status={})
                self.assertIsNone(spend_guard.risky_confirm(task))

    def test_the_same_card_text_still_stops_where_the_dialog_is_not_recognised(self):
        """Without either of the dialog's lines or its Cancel, or on another dialog, everything is read as before."""
        for line, group in DIALOG_CARD_LINES.items():
            if group is None:
                continue
            frame = replaced(CARD_REWARD_SKIP, "2 Crystallization", line)
            tasks = {
                "first line missing": FakeTask([box for box in frame if not box[0].startswith("Rewards cannot")], node_status={}),
                "second line missing": FakeTask([box for box in frame if not box[0].startswith("Are you sure")], node_status={}),
                "Cancel missing": FakeTask([box for box in frame if box[0] != "取消"], node_status={}),
                "lines elsewhere": dialog("Rewards cannot be obtained if you choose to skip.", "Are you sure you want to skip it?", line,
                                          node_status={}),
                "plain dialog": dialog("Are you sure?", line, node_status={}),
            }
            for case, task in tasks.items():
                with self.subTest(line=line, case=case):
                    self.assertFalse(spend_guard.shown(task, spend_guard.REWARD_SKIP_DIALOG))
                    self.assertEqual(group, spend_guard.risky_confirm(task)[0])

    def test_a_spend_delete_or_retreat_in_the_dialogs_own_lines_still_stops(self):
        for frame_name, frame in (("Card Reward", CARD_REWARD_SKIP), ("Select Card Space", SELECT_CARD_SPACE_SKIP)):
            for line, group in DIALOG_SPENDS.items():
                for y in (0.36, 0.50):
                    with self.subTest(frame=frame_name, line=line, y=y):
                        task = FakeTask([*frame, (line, 0.5, y)], node_status={})
                        self.assertTrue(spend_guard.shown(task, spend_guard.REWARD_SKIP_DIALOG))
                        self.assertIs(True, confirm(task))
                        self.assertTrue(task.disabled)
                        self.assertEqual(["取消"], task.clicked)
                        self.assertIn(group, task.notifications[0])


# The prompt a Chaos run still open raises on the way in, as OCR read it through the catalog.
# Escape abandons the run.
RESUME_LINE = ("Do you wish'to enter the stage in progress?", 0.501, 0.828)
RESUME = [("53%", 0.501, 0.508), ("9/17", 0.500, 0.563), ("卡厄思显现", 0.501, 0.677), ("The Blue Pot", 0.502, 0.728), RESUME_LINE,
          ("取消", 0.369, 0.907), ("进入", 0.637, 0.907), ("Escape", 0.898, 0.910)]
ESCAPE = (0.898, 0.910)
# Chaos Info, the battle menu Q opens, as OCR read it. Its Escape abandons the run.
CHAOS_INFO = [("© Chaos Info", 0.168, 0.051), ("Q Outskirts", 0.640, 0.050), ("16/17", 0.778, 0.051), ("275", 0.879, 0.050),
              ("Loot", 0.668, 0.164), ("The Blue Pot", 0.258, 0.262), ("Chaos Sizel Small", 0.267, 0.300), ("600", 0.693, 0.301),
              ("Difficulty", 0.217, 0.382), ("Phase 1", 0.537, 0.382), ("• Save Data Storage Limit 10Opt", 0.251, 0.466),
              ("The loot you have acquired can be taken back to the ship upon return.", 0.811, 0.818), ("End", 0.820, 0.890),
              ("Escape", 0.936, 0.928)]
# Sortie's Stage Info, which Esc opens in battle, as a live run read it. Its Escape leaves the stage.
STAGE_INFO = [("© Stage Info", 0.165, 0.050), ("X", 0.959, 0.050), ("Loot", 0.669, 0.164), ("0", 0.934, 0.163),
              ("Combatant Promotion Materials", 0.331, 0.261), ("- Ranger", 0.489, 0.264), ("Combatants", 0.245, 0.300),
              ("Difficulty", 0.217, 0.382), ("Stage 2", 0.536, 0.383), ("Current turn count", 0.252, 0.450), ("4", 0.536, 0.449),
              ("No loot acquired.", 0.810, 0.547), ("?", 0.049, 0.806),
              ("The loot you have acquired can be taken back to the ship upon return.", 0.812, 0.818), ("End", 0.842, 0.890),
              ("Escape", 0.935, 0.929)]
# Battle Prep's confirmation, whose Enter sits beside its Cancel, away from the round button.
BATTLE_PREP = [("Battle Prep Confirmation", 0.501, 0.169), ("Recommended Lv.10", 0.500, 0.244),
               ("Please check to see if you've met the recommended level.", 0.500, 0.302),
               ("Please check if you've included Partners in your formation.", 0.501, 0.334), ("LV.10", 0.293, 0.405), ("Tressa", 0.362, 0.406),
               ("Assign Partner|", 0.773, 0.406), ("LV.10", 0.293, 0.489), ("Owen", 0.355, 0.492), ("Assign Partner", 0.772, 0.491),
               ("D", 0.847, 0.490), ("Do not show again today", 0.521, 0.721), ("X", 0.210, 0.830), ("取消", 0.347, 0.830), ("进入", 0.666, 0.831)]


def changed(texts, drop=(), add=()):
    """Copy a screen with some boxes left unread and others read in.

    Args:
        texts: `(name, x, y)` triples.
        drop: Names of boxes OCR missed.
        add: `(name, x, y)` triples OCR read as well.

    Returns:
        The new triples.
    """
    return [box for box in texts if box[0] not in drop] + list(add)


@contextlib.contextmanager
def guarded_enter():
    """Put `src/en/enter.py`'s change and the guard over upstream's own Enter, as the app applies them, three times over.

    A copy of `utils` carries the wrappers, so the real module keeps its handler.

    Yields:
        The installed `handle_enter`.
    """
    saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
    copy = types.ModuleType(utils.__name__)
    copy.__dict__.update(vars(utils))
    mode = types.ModuleType("fake_mode_for_escape_enter_test")
    mode.PAGE_HANDLERS = [copy.handle_enter]
    sys.modules[mode.__name__] = mode
    try:
        for _ in range(INSTALLS):
            enter.install(copy)
            spend_guard.install(copy)
        yield mode.PAGE_HANDLERS[0]
    finally:
        sys.modules.pop(mode.__name__, None)
        for entries, before in saved:
            entries[:] = before


def run_enter(task):
    """Show a screen to the installed Enter.

    Args:
        task: The running task.

    Returns:
        The handler's answer.
    """
    with guarded_enter() as handle_enter:
        return handle_enter(task)


def pressed_at(task):
    """Give where each pressed box sits.

    Args:
        task: The running task, with `clicked_at` recorded.

    Returns:
        `(x, y)` screen fractions, rounded to three places.
    """
    return [(round(x, 3), round(y, 3)) for x, y in task.clicked_at]


class TestEscape(unittest.TestCase):
    """The Global client's Escape, which abandons a run: on the resume prompt, on Chaos Info and on Sortie's Stage Info."""

    def run_stuck(self, task):
        stand_in = fake_utils()
        return spend_guard.guarding_taps(stand_in.handle_stuck_log, stand_in)(task)

    def test_a_screen_carrying_escape_gets_no_blind_tap(self):
        for name, texts in (("resume prompt", RESUME), ("Chaos Info", CHAOS_INFO), ("Stage Info", STAGE_INFO)):
            with self.subTest(screen=name):
                task = FakeTask(texts, frozen_for=15)
                self.assertIs(False, self.run_stuck(task))
                self.assertEqual([], task.clicked)

    def test_a_dialog_that_would_escape_is_cancelled_unless_the_run_asked(self):
        task = dialog("Escape", "Do you want to escape from this run?", node_status={})
        self.assertIs(True, confirm(task))
        self.assertTrue(task.disabled)
        self.assertEqual(["取消"], task.clicked)
        self.assertIn(spend_guard.RETREAT, task.notifications[0])
        asked = dialog("Escape", node_status={spend_guard.RETREAT_ASKED: True})
        self.assertIs(True, confirm(asked))
        self.assertEqual(["确认"], asked.clicked)
        self.assertFalse(asked.disabled)

    def test_words_that_only_look_like_escape_stay_harmless(self):
        """Escapism is a card a hand can hold, and Esc a key hint the battle overlays print beside their Cancel."""
        for name, texts in (("Escapism card", [("Escapism", 0.5, 0.75), ("Has a low chance for unexpected results to occur on use.", 0.5, 0.8)]),
                            ("Esc key hint", [("Esc", 0.05, 0.316), ("取消", 0.084, 0.316)])):
            with self.subTest(screen=name):
                task = FakeTask(texts, frozen_for=15)
                self.run_stuck(task)
                self.assertEqual(["blind tap"], task.clicked)
        task = dialog("End your turn?", "Escapism", node_status={})
        self.assertIs(True, confirm(task))
        self.assertEqual(["确认"], task.clicked)

    def test_the_prompt_as_read_leaves_its_enter_alone(self):
        """The prompt's own Enter is the one press that resumes the run."""
        self.assertIsNone(spend_guard.escape_at_enter(FakeTask(RESUME)))
        task = StoryMode(RESUME)
        self.assertIs(True, run_enter(task))
        self.assertEqual([(0.637, 0.907)], pressed_at(task))

    def test_an_escape_read_as_enter_without_the_line_is_never_pressed(self):
        """A pass that misses the prompt's line leaves only upstream's Enter, which presses an Enter in the round button's corner.

        At the measured x 0.898 the Enter change already leaves it, outside Story.
        """
        for x in (0.902, ESCAPE[0]):
            misread = [("进入", x, ESCAPE[1])]
            for name, texts in (
                    ("read as Enter", changed(RESUME, drop=(RESUME_LINE[0], "Escape"), add=misread)),
                    ("read as Enter over the Escape box", changed(RESUME, drop=(RESUME_LINE[0],), add=misread)),
                    ("read as Enter, the real Enter missed", changed(RESUME, drop=(RESUME_LINE[0], "Escape", "进入"), add=misread)),
                    ("read as Enter, Cancel missed", changed(RESUME, drop=(RESUME_LINE[0], "Escape", "取消"), add=misread))):
                for mode in (FakeTask, StoryMode):
                    if mode is StoryMode and x < spend_guard.ROUND_BUTTON[0] and name != "read as Enter over the Escape box":
                        continue
                    with self.subTest(x=x, variant=name, mode=mode.__name__):
                        task = mode(texts)
                        self.assertIs(False, run_enter(task))
                        self.assertEqual([], task.clicked)
                        declined = x >= spend_guard.ROUND_BUTTON[0] or name == "read as Enter over the Escape box"
                        self.assertEqual(int(declined), sum("may be the run's Escape" in line for line in task.logged))

    def test_the_round_button_is_still_pressed(self):
        for name, texts, spot in (("Blue Pot detail", DETAIL, (0.935, 0.899)), ("Formation", FORMATION, (0.945, 0.913))):
            with self.subTest(screen=name):
                task = FakeTask(texts)
                self.assertIs(True, run_enter(task))
                self.assertEqual([spot], pressed_at(task))
                self.assertEqual([], [line for line in task.logged if "Escape" in line])

    def test_an_enter_beside_its_cancel_away_from_the_round_button_is_still_pressed_in_story(self):
        task = StoryMode(BATTLE_PREP)
        self.assertIs(True, run_enter(task))
        self.assertEqual([(0.666, 0.831)], pressed_at(task))

    def test_a_declined_enter_is_logged_once_per_freeze(self):
        task = FakeTask(changed(RESUME, drop=(RESUME_LINE[0], "Escape"), add=[("进入", 0.902, ESCAPE[1])]))
        with guarded_enter() as handle_enter:
            for clock in (1, 1, 1, 2):
                setattr(task, CLOCK, clock)
                self.assertIs(False, handle_enter(task))
        self.assertEqual(2, sum("may be the run's Escape" in line for line in task.logged))
        self.assertEqual([], task.clicked)

    def test_the_round_button_corner_is_still_the_enter_changes(self):
        self.assertEqual(enter.BUTTON, spend_guard.ROUND_BUTTON)
        self.assertEqual(enter.ENTER, spend_guard.ENTER)


class TestInstall(unittest.TestCase):

    def test_the_enter_guard_sits_over_the_enter_change_once(self):
        """`src/en/enter.py` shows upstream the round button's box alone, so a guard inside it would never read the Escape box."""
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertLess(applied.index("enter"), applied.index("spend_guard"))
        with guarded_enter() as handle_enter:
            tags = list(getattr(handle_enter, WRAPS))
        self.assertEqual(1, tags.count(spend_guard.ENTER_TAG))
        self.assertEqual(1, tags.count(enter.TAG))
        self.assertLess(tags.index(enter.TAG), tags.index(spend_guard.ENTER_TAG))
        self.assertEqual("handle_enter", handle_enter.__name__)

    def test_the_guard_is_applied_before_notify(self):
        """notify renames the stuck handler's list entry, after which the tap guard would find nothing to wrap, silently."""
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertIn("spend_guard", applied)
        self.assertLess(applied.index("spend_guard"), applied.index("notify"))

    def test_each_guard_is_applied_once_however_often_the_install_runs(self):
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        mode = types.ModuleType("fake_mode_for_spend_guard_install_test")
        stand_in = fake_utils()
        mode.PAGE_HANDLERS = [stand_in.handle_center_confirm, stand_in.handle_stuck_log]
        sys.modules[mode.__name__] = mode
        try:
            for _ in range(INSTALLS):
                spend_guard.install(stand_in)
        finally:
            sys.modules.pop(mode.__name__, None)
            for entries, before in saved:
                entries[:] = before
        self.assertEqual([spend_guard.CONFIRM_TAG], list(getattr(stand_in.handle_center_confirm, WRAPS)))
        self.assertEqual([spend_guard.TAPS_TAG], list(getattr(stand_in.handle_stuck_log, WRAPS)))
        self.assertEqual([spend_guard.handle_rescue_screen, stand_in.handle_center_confirm, stand_in.handle_stuck_log], mode.PAGE_HANDLERS)
        self.assertEqual(["handle_rescue_screen", "handle_center_confirm", "handle_stuck_log"], [handler.__name__ for handler in mode.PAGE_HANDLERS])


if __name__ == "__main__":
    unittest.main()
