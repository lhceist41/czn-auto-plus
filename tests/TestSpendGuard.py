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

from src.en import handlers, notify, reason, spend_guard  # noqa: E402
from src.en.handlers import WRAPS  # noqa: E402
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
        self.logged = []
        self.notifications = []
        self.disabled = False

    def find_one(self, feature_name, box=None):
        self.searched.append((feature_name, box))
        return object() if self.icon and feature_name == spend_guard.PRICE_ICON else None

    def box_of_screen(self, *region):
        return region

    def click_box(self, box):
        self.clicked.append(box.name)

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled = True


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


class TestInstall(unittest.TestCase):

    def test_the_guard_is_applied_before_notify(self):
        """notify renames the stuck handler's list entry, after which the tap guard would find nothing to wrap, silently."""
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertIn("spend_guard", applied)
        self.assertLess(applied.index("spend_guard"), applied.index("notify"))

    def test_each_guard_is_applied_once_however_often_the_install_runs(self):
        mode = types.ModuleType("fake_mode_for_spend_guard_install_test")
        stand_in = fake_utils()
        mode.PAGE_HANDLERS = [stand_in.handle_center_confirm, stand_in.handle_stuck_log]
        sys.modules[mode.__name__] = mode
        try:
            for _ in range(INSTALLS):
                spend_guard.install(stand_in)
        finally:
            sys.modules.pop(mode.__name__, None)
        self.assertEqual([spend_guard.CONFIRM_TAG], list(getattr(stand_in.handle_center_confirm, WRAPS)))
        self.assertEqual([spend_guard.TAPS_TAG], list(getattr(stand_in.handle_stuck_log, WRAPS)))
        self.assertEqual([spend_guard.handle_rescue_screen, stand_in.handle_center_confirm, stand_in.handle_stuck_log], mode.PAGE_HANDLERS)
        self.assertEqual(["handle_rescue_screen", "handle_center_confirm", "handle_stuck_log"], [handler.__name__ for handler in mode.PAGE_HANDLERS])


if __name__ == "__main__":
    unittest.main()
