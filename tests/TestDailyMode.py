"""Check that Daily closes the Lobby's popups, claims attendance and all mail, opens Dream Park and stops on the Lobby, pressing nothing else.

The screens are the boxes OCR read off the Global client's Lobby, its entry banner and Notice board, the open menu, the
Mail screen before and after Claim All, and Items Obtained, as the bot sees them once the catalog has mapped them, with
the player's name left out. What Daily must never do: press a delete, the Shop, a purchase, Crystals, a price, Rescue or
the game's quit button; press anything on a screen it does not know; run beside another mode. The park visit itself is
checked in `TestDreamPark`.
"""

import ast
import importlib
import re
import sys
import textwrap
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
import utils_chaos  # noqa: E402,F401
import utils_sortie  # noqa: E402,F401
import utils_story  # noqa: E402,F401
from ok import TriggerTask  # noqa: E402
from ok.device.interaction_methods.post_message import PostMessageInteraction  # noqa: E402

from src.en import daily, handlers, skip_tutorial, spend_guard, story, stuck_stop  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

START = 1_000.0
INSTALLS = 3

# 219, the Lobby with its menu closed.
LOBBY = (
    ("N", 0.136, 0.032), ("m", 0.839, 0.031), ("`", 0.919, 0.023), ("等级", 0.054, 0.049), ("06", 0.055, 0.091), ("240/240+", 0.698, 0.049),
    ("★", 0.777, 0.054), ("E", 0.834, 0.049), ("N", 0.972, 0.03), ("53%", 0.106, 0.084), ("Act 1-Chapter 1, Episode 7", 0.824, 0.194),
    ("故事", 0.884, 0.156), ("Clear Battle Mission Chapt", 0.154, 0.233), ("0/1", 0.064, 0.262), ("Sortie", 0.884, 0.267), ("CAC>", 0.898, 0.292),
    ("O11d Oh", 0.05, 0.333), ("Reach Captain Level 10", 0.104, 0.388), ("θ Simulation", 0.867, 0.354), ("日 Chaos", 0.883, 0.44),
    ("方舟城市", 0.875, 0.528), ("Combatants", 0.867, 0.617), ("EVENT", 0.822, 0.704), ("营救", 0.887, 0.705), ("32d0h", 0.935, 0.832),
    ("CORONOMICON", 0.142, 0.887), ("GIFT", 0.166, 0.921), ("Uponthe SnW", 0.889, 0.925), ("APromrse", 0.894, 0.887),
)
# 265, the Lobby with its menu open.
MENU = (
    ("N", 0.137, 0.032), ("06", 0.057, 0.091), ("53%", 0.105, 0.084), ("Act 1 - Chapter 1, Episode 7", 0.521, 0.130), ("故事", 0.581, 0.091),
    ("⭐", 0.736, 0.091), ("Event", 0.783, 0.087), ("X", 0.961, 0.049), ("Arkhianon Supply", 0.825, 0.160), ("日", 0.904, 0.159),
    ("Mission Chapter 1. B3", 0.118, 0.233), ("θ Sortie", 0.581, 0.200), ("0/1", 0.064, 0.263), ("Activity", 0.789, 0.231),
    ("Simulation", 0.564, 0.288), ("10d23h", 0.056, 0.332), ("Unigram", 0.796, 0.302), ("日", 0.836, 0.302), ("Reach Captain Level10", 0.105, 0.392),
    ("θ Chaos", 0.579, 0.375), ("Partners", 0.791, 0.375), ("方舟城市", 0.571, 0.463), ("Storage", 0.790, 0.451), ("Combatants", 0.565, 0.552),
    ("Achievement", 0.808, 0.520), ("Archive", 0.790, 0.594), ("EVENT", 0.519, 0.639), ("营救", 0.584, 0.639), ("Shop", 0.781, 0.666),
    ("N", 0.816, 0.666), ("?", 0.963, 0.706), ("10d 23h", 0.056, 0.870), ("31d 23h", 0.618, 0.832), ("Reach Captain Level 10", 0.104, 0.925),
    ("Upon theSnW", 0.586, 0.925), ("APromrse=", 0.593, 0.885),
)
# 273, the open menu with its key labels on: `End` under the power button.
MENU_KEYS = MENU + (("ESC", 0.962, 0.076), ("M", 0.962, 0.310), ("O", 0.962, 0.815), ("End", 0.964, 0.951))
# 218, the Notice board over the Lobby.
NOTICE = (
    ("Notice", 0.216, 0.119), ("Update", 0.403, 0.119), ("of being my partner for tonight Captain.", 0.325, 0.26), ("I shall allow you the honor", 0.324, 0.215),
    ("Distress Signal", 0.692, 0.267), ("Amplified", 0.662, 0.211), ("Blazebell", 0.66, 0.323), ("Distress Signal:", 0.692, 0.473), ("Amplified", 0.663, 0.419),
    ("Vivian", 0.642, 0.534), ("NightmarexCarnival", 0.716, 0.656), ("Attire & Card Skin Release!", 0.327, 0.736),
    ("Visit the Official Website", 0.717, 0.725), ("Go Now", 0.325, 0.826), ("Ongoing", 0.652, 0.854),
)
# 217, the entry banner: no text that stays from one banner to the next.
BANNER = (("Seasonal", 0.132, 0.766), ("Rossweisse", 0.184, 0.827), ("Seasonal Combatant Rescue Rate-Up", 0.234, 0.906), ("11d 0h", 0.48, 0.905))
# 274, the Mail screen with three mails to claim.
MAIL = (
    ("√", 0.068, 0.089), ("Mail", 0.107, 0.090), ("003 / 100", 0.844, 0.090), ("1st Anniversary Login Rewards hav..", 0.265, 0.183),
    ("From. Chaos Zero Nightmare", 0.217, 0.244), ("区 6d 23h", 0.410, 0.244), ("1st Anniversary Login Rewards have arrived!", 0.698, 0.215),
    ("From. Chaos Zero Nightmare", 0.611, 0.257), ("2026-10-2807:00", 0.884, 0.260), ("N", 0.047, 0.298), ("+", 0.929, 0.288),
    ("1st Anniversary Surprise Growth S..", 0.262, 0.329), ("From. Chaos Zero Nightmare", 0.216, 0.392), ("区 6d 23h", 0.409, 0.391),
    ("We've prepared a special gift to celebrate our 1st Anniversary", 0.716, 0.378), ("N", 0.047, 0.446), ("together with our Protos.", 0.599, 0.411),
    ("Make sure to claim it now!", 0.603, 0.441), ("1st Anniversary Login Rewards hav...", 0.264, 0.478), ("From. Chaos Zero Nightmare", 0.217, 0.541),
    ("区 6d 23h", 0.410, 0.541), ("①", 0.061, 0.902), ("Claim All", 0.194, 0.904), ("Delete read mail", 0.380, 0.905), ("Claim", 0.850, 0.867),
)
# 276, the same mail after Claim All: OCR read `Claim AIl`, and the open mail's Claim has turned into Delete.
MAIL_AFTER = tuple(box for box in MAIL if box[0] not in ("√", "①", "Claim All", "Claim", "N")) + (
    ("静", 0.099, 0.242), ("Claim AIl", 0.194, 0.905), ("Delete", 0.851, 0.868),
)
# 522, the empty mailbox's popup on a live run: it reads as 276, Claim All greyed. A press on it shows the toast here.
MAIL_EMPTY = MAIL_AFTER
MAIL_TOAST = MAIL_AFTER + (("All items in the mail have been received.", 0.500, 0.275),)
# 275, Items Obtained over the Mail screen.
ITEMS = (
    ("Items Obtained", 0.502, 0.377), ("365,000", 0.287, 0.568), ("2,000", 0.384, 0.568), ("5", 0.487, 0.566), ("365", 0.566, 0.568),
    ("V", 0.499, 0.885), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.978),
)
# The daily attendance popup on day 4, opened as the Mail popup closed: days 1 to 3 stamped, today's Claim Reward, the
# X drawn but not read. Then Items Obtained over it, and the popup again with day 4 stamped and its X read.
ATTENDANCE = (
    ("Invitation to a New Journey", 0.690, 0.169), ("Permanent", 0.833, 0.229), ("02", 0.541, 0.308), ("1", 0.629, 0.318), ("03", 0.653, 0.307),
    ("07", 0.778, 0.325), ("04", 0.431, 0.611), ("05", 0.542, 0.612), ("06", 0.653, 0.611), ("Claim Reward", 0.459, 0.830),
    ("Awaiting Attendance", 0.571, 0.831), ("Awaiting Attendance", 0.683, 0.831), ("Awaiting Attendance", 0.817, 0.828),
)
ATTENDANCE_ITEMS = (("Items Obtained", 0.502, 0.377), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.977))
ATTENDANCE_STAMPED = (
    ("Invitation to a New Journey", 0.690, 0.169), ("X", 0.933, 0.127), ("Permanent", 0.833, 0.229), ("02", 0.541, 0.309), ("03", 0.653, 0.307),
    ("07", 0.778, 0.326), ("天", 0.568, 0.450), ("04", 0.428, 0.612), ("05", 0.542, 0.612), ("06", 0.653, 0.611),
    ("Awaiting Attendance", 0.571, 0.831), ("Awaiting Attendance", 0.683, 0.831), ("Awaiting Attendance", 0.817, 0.828),
)
# 264, the Lobby a few idle seconds later, its UI faded out: OCR reads nothing.
FADED = ()
# Where the faded-scene crops sit: x 0-441 and y 21-302 of a 1080p capture.
SCENE_REGION = (0.0, 0.02, 0.23, 0.28)
# Claim All's crops, from 274 (orange) and the live run's empty popup (greyed): x 57-480 and y 928-1026.
CLAIM_ALL_CROP = (0.03, 0.86, 0.25, 0.95)
# 222, the Selective Rescue screen, and 253, a paid Rescue's Crystal dialog.
RESCUE = (
    ("√", 0.041, 0.043), ("营救", 0.116, 0.048), ("235", 0.71, 0.048), ("Skip Tutorial", 0.88, 0.054), ("Special Signal Selective Rescue", 0.386, 0.255),
    ("Shop", 0.109, 0.922), ("Rescue Info", 0.253, 0.926), ("Selective Rescue 10 time(s)", 0.849, 0.912), ("免费", 0.95, 0.912),
)
PAID_RESCUE = (
    ("营救", 0.115, 0.047), ("235", 0.709, 0.048), ("10 Signal Amplification Anchor required.", 0.502, 0.423),
    ("Spend 1600 Crystals to make the purchase?", 0.500, 0.463), ("取消", 0.347, 0.631), ("确认", 0.667, 0.631), ("Rescue 10 time(s)", 0.848, 0.913),
)
# The Event list as the menu's Event opens it, on its first event rather than Dream Park; and the same list without Dream Park.
EVENT_LIST = (
    ("√", 0.041, 0.046), ("Event", 0.109, 0.048), ("N", 0.973, 0.030), ("↓ Recommended Events", 0.091, 0.138), ("N", 0.215, 0.111),
    ("Invitation to a New Journey", 0.774, 0.136), ("Event Description", 0.784, 0.201), ("Permanent", 0.918, 0.201),
    ("tation to a New Journey", 0.114, 0.270), ("02", 0.626, 0.335), ("03", 0.738, 0.336), ("kie Captain Mission", 0.101, 0.395),
    ("07", 0.861, 0.353), ("le Path of a Captain", 0.102, 0.519), ("N", 0.179, 0.576), ("htmare Dream Park", 0.100, 0.644), ("04", 0.512, 0.636),
    ("05", 0.625, 0.636), ("06", 0.737, 0.636), ("nise Upon the Snow", 0.101, 0.771), ("Awaiting Attendance", 0.543, 0.854),
    ("Awaiting Attendance", 0.656, 0.854), ("Awaiting Attendance", 0.768, 0.855), ("Awaiting Attendance", 0.901, 0.854),
    ("Poised Against the(", 0.103, 0.894),
)
EVENT_LIST_WITHOUT_PARK = tuple(box for box in EVENT_LIST if "Dream Park" not in box[0])
# 266, the Graphic Settings page, a screen Daily has no business on.
SETTINGS = (
    ("Graphic Settings", 0.184, 0.091), (":X", 0.932, 0.091), ("Graphics", 0.138, 0.172), ("Image Quality", 0.161, 0.233), ("High", 0.797, 0.234),
    ("Game Resolution", 0.173, 0.307), ("1920×1080", 0.808, 0.304), ("Screen Mode", 0.161, 0.378), ("Full Screen", 0.796, 0.376),
    ("Reset", 0.680, 0.892), ("Apply", 0.917, 0.894),
)

# 474, the Lobby during the tutorial: its Skip Tutorial pill covers the Menu point. The player's name is left out.
TUTORIAL_LOBBY = (
    ("等级", 0.055, 0.049), ("08", 0.057, 0.090), ("N", 0.137, 0.032), ("240/240+", 0.698, 0.050), ("⭐", 0.776, 0.053), ("E1", 0.777, 0.077),
    ("Skip Tutorial", 0.879, 0.054), ("23%", 0.107, 0.085), ("Oh my. Do you need training? Great", 0.235, 0.170),
    ("Act 1-Chapter 1, Episode 8", 0.824, 0.194), ("故事", 0.884, 0.157), ("Sortie", 0.885, 0.267), ("Simulation", 0.876, 0.352),
    ("Chaos", 0.891, 0.442), ("方舟城市", 0.876, 0.530), ("Combatants", 0.868, 0.617), ("EVENT", 0.823, 0.704), ("营救", 0.886, 0.705),
)
SKIP_TUTORIAL = ("Skip Tutorial", 0.879, 0.055)
# The pill's outline on every capture of it, which a tap anywhere inside presses.
SKIP_TUTORIAL_PILL = (0.818, 0.020, 0.992, 0.091)

# Where each target sits, written out here rather than read from the module, so a point drifting there fails a test.
POINTS = {
    daily.BANNER_CLOSE: (0.968, 0.049),
    daily.NOTICE_CLOSE: (0.911, 0.120),
    daily.MENU: (0.959, 0.046),
    daily.ENVELOPE: (0.962, 0.280),
    daily.MENU_CLOSE: (0.961, 0.049),
    daily.MAIL_CLOSE: (0.936, 0.093),
    daily.WAKE: (0.300, 0.420),
    daily.CLAIM_ALL: (0.194, 0.904),
    daily.ITEMS_CLOSE: (0.501, 0.935),
    daily.EVENT: (0.783, 0.088),
    daily.DREAM_PARK: (0.100, 0.644),
    daily.EVENT_LEAVE: (0.041, 0.046),
    daily.ENTER_PARK: (0.775, 0.901),
    daily.PARK_ACHIEVEMENTS: (0.551, 0.900),
    daily.PAGE_LEAVE: (0.041, 0.046),
    daily.PARK_MANAGE: (0.087, 0.294),
    daily.PARK_OPERATE: (0.087, 0.473),
    daily.PANEL_CLOSE: (0.041, 0.046),
    daily.PARK_LEAVE: (0.041, 0.046),
    daily.PARK_RANK: (0.804, 0.906),
    daily.RANK_UP: (0.502, 0.900),
    daily.RANK_CLOSE: (0.977, 0.137),
    daily.RANK_RESULT_CLOSE: (0.500, 0.938),
    daily.UPGRADE: (0.772, 0.634),
    daily.BUILD: (0.761, 0.845),
    daily.CLAIM: (0.722, 0.166),
    daily.MANAGEMENT_TAB: (0.100, 0.270),
    daily.ACHIEVEMENTS_LEAVE: (0.041, 0.046),
    daily.RULES_CANCEL: (0.347, 0.631),
    daily.PROFIT_CLOSE: (0.500, 0.938),
    daily.STORY_SKIP: (0.767, 0.053),
    daily.SKIP_TICK: (0.392, 0.532),
    daily.SKIP_CONFIRM: (0.667, 0.631),
    daily.ATTENDANCE_CLAIM: (0.459, 0.830),
    daily.ATTENDANCE_CLOSE: (0.933, 0.127),
    daily.SKILL_TAB: (0.892, 0.185),
    daily.FACILITIES_TAB: (0.714, 0.185),
    daily.SKILL_UPGRADE: (0.772, 0.456),
}
# What Daily must never press, by where it sits. Power is the icon's centre in 265 (rows 972-1022 of 1080) and the
# `End` key label under it in 273. Skip Tutorial is a box over three targets, not a point: `TestTutorial` covers it.
NEVER = {
    "Delete read mail": (0.380, 0.905),
    "the open mail's Claim, then Delete": (0.850, 0.867),
    "the Aether +": (0.70, 0.05),
    "the Lobby's Rescue": (0.887, 0.705),
    "Go Now": (0.325, 0.826),
    "Visit the Official Website": (0.717, 0.725),
    "the banner's dots": (0.944, 0.050),
    "the Notice board's dots": (0.889, 0.119),
    "the film icon": (0.843, 0.12),
    "the menu's Shop": (0.781, 0.666),
    "the menu's Arkhianon Supply": (0.825, 0.160),
    "the menu's settings": (0.962, 0.813),
    "the menu's power": (0.962, 0.923),
    "the power's End label": (0.962, 0.949),
    "Items Obtained's 进入": (0.500, 0.978),
    "the Mail popup's dots": (0.912, 0.093),
    "the Mail popup's envelope": (0.068, 0.089),
    "a day still awaiting attendance": (0.571, 0.831),
    "the attendance popup's dots": (0.932, 0.159),
}
# How close a tap may come to a point before it counts as pressing it: about 19 px across and 11 px down at 1080p. The
# banner's dots sit 0.015 left of where the Lobby's Menu is tapped, but only on the banner, where Daily taps the X instead.
NEAR = 0.01

# Daily's own handlers in the order they must run, which the shape test holds the module to.
OWN = (
    spend_guard.handle_rescue_screen,
    daily.handle_daily_tutorial,
    daily.handle_daily_overtime,
    daily.handle_daily_items_obtained,
    daily.handle_daily_attendance,
    daily.handle_daily_mail,
    daily.handle_daily_rules_dialog,
    daily.handle_daily_profit_report,
    daily.handle_daily_skip_dialog,
    daily.handle_daily_park_story,
    daily.handle_daily_rank_result,
    daily.handle_daily_rank_screen,
    daily.handle_daily_manage_panel,
    daily.handle_daily_facilities,
    daily.handle_daily_skill_tab,
    daily.handle_daily_park_view,
    daily.handle_daily_park_achievements,
    daily.handle_daily_event_page,
    daily.handle_daily_event_list,
    daily.handle_daily_notice,
    daily.handle_daily_banner,
    daily.handle_daily_lobby_menu,
    daily.handle_daily_lobby,
    daily.handle_daily_faded_lobby,
    daily.handle_daily_unknown_screen,
)
# Upstream's generic handlers: a Lobby stop that would end Daily on its first frame, blind taps and a centred Confirm.
FORBIDDEN = ("handle_non_battle_page", "handle_center_confirm", "handle_stuck_log", "handle_enter", "handle_confirm")
# Taken at import, before any test's install can reach the module's list.
PRISTINE = list(daily.PAGE_HANDLERS)


def corner(name):
    """Put a capture's top-right corner back into an otherwise black frame.

    Args:
        name: The crop's base name in `tests/images/`, cut at x 1728-1920 and y 0-130 of a 1080p capture.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    frame[:patch.shape[0], WIDTH - patch.shape[1]:] = patch
    return frame


def placed(name, region):
    """Put a crop of a capture back where it was cut, into an otherwise black frame.

    Args:
        name: The crop's base name in `tests/images/`.
        region: Where it was cut, as `(left, top, right, bottom)` fractions of a 1080p capture.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    left, top = int(region[0] * WIDTH), int(region[1] * HEIGHT)
    frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
    return frame


def faded_lobby(name="daily_faded_lobby"):
    """Give a faded Lobby's frame: 272 by default, `daily_faded_lobby_character` for 352, whose character still stands."""
    return placed(name, SCENE_REGION)


def claim_all(lit):
    """Give a Mail frame's Claim All: orange from 274 when lit, greyed from the live run's empty popup when not."""
    return placed("daily_claim_all_lit" if lit else "daily_claim_all_greyed", CLAIM_ALL_CROP)


class Clock:
    """Monotonic time the test moves by hand."""

    def __init__(self):
        self.now = START

    def monotonic(self):
        return self.now


class Executor:
    """Finds the app's modes by class name, as ok-script's executor does, and carries its PostMessage input."""

    def __init__(self, *tasks):
        self.tasks = list(tasks)
        self.interaction = mock.Mock(spec=PostMessageInteraction)

    def get_task_by_class_name(self, name):
        return next((task for task in self.tasks if type(task).__name__ == name), None)


class Task:
    """Daily looking at one screen, recording every tap, drag, announcement and stop."""

    width, height = WIDTH, HEIGHT

    def __init__(self):
        self.name = "Daily"
        self.all_texts = []
        self.frame = None
        self.enabled = True
        self.clicks = []
        self.waits = []
        self.zones = []
        self.zone_read = list
        self.swipes = []
        self.logged = []
        self.notifications = []
        self.disabled = 0
        self.executor = Executor(self)

    def show(self, texts, frame=None):
        """Put a screen in front of Daily.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
            frame: The capture, or None.

        Returns:
            The task.
        """
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.frame = frame
        return self

    def move_relative(self, x, y):
        pass

    def sleep(self, seconds):
        pass

    def click(self, x, y, after_sleep=0):
        self.clicks.append((x, y))
        self.waits.append(after_sleep)

    def ocr(self, x, y, to_x, to_y):
        """Read a zone of the screen with `zone_read`, which reads nothing unless a test says otherwise."""
        self.zones.append((x, y, to_x, to_y))
        return self.zone_read()

    def swipe_relative(self, from_x, from_y, to_x, to_y, duration=0.5, settle_time=0):
        self.swipes.append((from_x, from_y, to_x, to_y, duration))

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled += 1
        self.enabled = False
        vars(self).pop(daily.RUN, None)


def second_bottom_button(task):
    """Match Claim All loosely, as the bottom bar's second button from the left, which on the Mail screen is `Delete read mail`."""
    bottom = sorted((box for box in task.all_texts if box.y > 0.85 * HEIGHT and box.x < 0.5 * WIDTH), key=lambda box: box.x)
    return bottom[1]


def run_pass(task):
    """Run Daily's handlers once over the screen, as its run loop does.

    Returns:
        True when a handler claimed the frame.
    """
    return any(handler(task) for handler in OWN)


class Daily(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        patcher = mock.patch.object(daily, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = Task()

    def tick(self, seconds=1):
        self.clock.now += seconds

    def state(self):
        return daily.run_state(self.task)

    def finish_chores(self, mail="claimed"):
        """Count every chore as done, the mail with what it found."""
        steps = self.state()["steps"]
        steps["mail"], steps["dream_park"], self.state()["mail"] = daily.DONE, daily.DONE, mail

    def assertPressed(self, *targets):
        """Check the taps were exactly these targets, in order."""
        self.assertEqual(len(targets), len(self.task.clicks), self.task.clicks)
        for (x, y), target in zip(self.task.clicks, targets):
            expected = POINTS[target]
            self.assertAlmostEqual(expected[0], x, delta=0.005, msg=target)
            self.assertAlmostEqual(expected[1], y, delta=0.005, msg=target)

    def assertNothingForbidden(self):
        for x, y in self.task.clicks:
            for name, (never_x, never_y) in NEVER.items():
                self.assertFalse(abs(x - never_x) < NEAR and abs(y - never_y) < NEAR, f"pressed {name} at ({x:.3f}, {y:.3f})")

    def assertStopped(self, message_part):
        self.assertEqual(1, self.task.disabled)
        self.assertEqual(1, len(self.task.notifications), self.task.notifications)
        self.assertIn(message_part, self.task.notifications[0])


class TestMail(Daily):

    def test_after_the_claim_nothing_reading_delete_is_pressed_and_only_the_x_once_claimed(self):
        """1: the open mail's Claim turns into Delete in place, and `Delete read mail` sits 0.19 right of Claim All."""
        self.assertTrue(run_pass(self.task.show(MAIL_AFTER)))
        self.assertPressed(daily.CLAIM_ALL)
        self.task.clicks.clear()
        self.state()["steps"]["mail"] = daily.DONE
        self.assertTrue(run_pass(self.task.show(MAIL_AFTER)))
        self.assertPressed(daily.MAIL_CLOSE)
        self.assertNothingForbidden()

    def test_claim_all_is_pressed_once_waited_on_then_retried_once_and_a_third_press_refused(self):
        """2: a second frame inside the wait presses nothing, and the press limit refuses a third."""
        self.task.show(MAIL)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.CLAIM_ALL)
        for _ in range(daily.CLAIM_WAIT - 1):
            self.tick()
            self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.CLAIM_ALL)
        self.tick()
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.CLAIM_ALL, daily.CLAIM_ALL)
        self.assertTrue(daily.press(self.task, daily.CLAIM_ALL, daily.claim_all_button(self.task)))
        self.assertPressed(daily.CLAIM_ALL, daily.CLAIM_ALL)
        self.assertStopped("Claim All was pressed 2 times")

    def test_claim_all_that_opens_nothing_twice_counts_as_no_mail_and_closes(self):
        self.task.show(MAIL)
        for _ in range(2 * daily.CLAIM_WAIT + 1):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.CLAIM_ALL, daily.CLAIM_ALL, daily.MAIL_CLOSE)
        self.assertEqual("nothing to claim", self.state()["mail"])
        self.assertEqual(0, self.task.disabled)

    def test_a_mail_screen_without_claim_all_is_waited_on_before_it_counts_as_empty(self):
        """OCR can miss a button on one frame, and that alone must not skip the claim."""
        empty = tuple(box for box in MAIL if box[0] != "Claim All")
        self.assertTrue(run_pass(self.task.show(empty)))
        self.assertEqual([], self.task.clicks)
        self.tick(daily.CLAIM_WAIT - 1)
        self.assertTrue(run_pass(self.task.show(MAIL)))
        self.assertPressed(daily.CLAIM_ALL)

    def test_items_obtained_closes_on_its_caption_never_the_enter_below(self):
        """3: Items Obtained after Claim All counts the mail as claimed."""
        self.state()["claim_pressed"] = START
        self.assertTrue(run_pass(self.task.show(ITEMS)))
        self.assertPressed(daily.ITEMS_CLOSE)
        self.assertNothingForbidden()
        self.assertEqual(daily.DONE, self.state()["steps"]["mail"])
        self.assertEqual("claimed", self.state()["mail"])

    def test_items_obtained_without_a_claim_all_is_closed_without_counting_the_mail(self):
        self.assertTrue(run_pass(self.task.show(ITEMS)))
        self.assertPressed(daily.ITEMS_CLOSE)
        self.assertEqual(daily.PENDING, self.state()["steps"]["mail"])

    def test_claim_all_is_read_through_ocr_mixing_up_capital_i_and_small_l(self):
        """274 and 276 read it `Claim AIl` and `Claim AlI` through the app's OCR settings."""
        for text in ("Claim All", "Claim AIl", "Claim AlI", "ClaimAll"):
            with self.subTest(text=text):
                screen = tuple((text, x, y) if name == "Claim All" else (name, x, y) for name, x, y in MAIL)
                self.assertEqual(text, daily.claim_all_button(self.task.show(screen)).name)
        for text in ("Claim", "Delete read mail", "Claim All Delete"):
            with self.subTest(text=text):
                screen = tuple((text, x, y) if name == "Claim All" else (name, x, y) for name, x, y in MAIL)
                self.assertIsNone(daily.claim_all_button(self.task.show(screen)))

    def test_claim_all_outside_its_band_is_not_claim_all(self):
        screen = tuple((name, 0.380, y) if name == "Claim All" else (name, x, y) for name, x, y in MAIL if name != "Delete read mail")
        self.assertIsNone(daily.claim_all_button(self.task.show(screen)))

    def test_a_greyed_claim_all_is_never_pressed_and_counts_as_no_mail_once_waited_on(self):
        """A live run pressed the greyed button twice. It is waited on as a missing one would be, since the popup may still be drawing."""
        self.task.show(MAIL_EMPTY, claim_all(lit=False))
        for _ in range(daily.CLAIM_WAIT):
            self.assertTrue(run_pass(self.task))
            self.tick()
        self.assertEqual([], self.task.clicks)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.MAIL_CLOSE)
        self.assertEqual("nothing to claim", self.state()["mail"])
        self.assertIn("Claim All is greyed out, so there is no mail to claim", self.task.logged)
        self.assertNothingForbidden()

    def test_a_claim_all_turning_orange_inside_the_wait_is_pressed(self):
        self.task.show(MAIL, claim_all(lit=False))
        self.assertTrue(run_pass(self.task))
        self.tick(daily.CLAIM_WAIT - 1)
        self.assertTrue(run_pass(self.task.show(MAIL, claim_all(lit=True))))
        self.assertPressed(daily.CLAIM_ALL)

    def test_the_orange_claim_all_is_not_greyed_and_neither_is_a_frame_with_no_capture(self):
        self.assertTrue(daily.claim_all_greyed(self.task.show(MAIL_EMPTY, claim_all(lit=False))))
        self.assertFalse(daily.claim_all_greyed(self.task.show(MAIL, claim_all(lit=True))))
        self.assertFalse(daily.claim_all_greyed(self.task.show(MAIL)))

    def test_the_game_saying_every_mail_was_received_closes_the_popup_at_once(self):
        """The toast a press on the greyed button shows, read on the frame after a press made without a capture."""
        self.assertTrue(run_pass(self.task.show(MAIL)))
        self.tick()
        self.assertTrue(run_pass(self.task.show(MAIL_TOAST)))
        self.assertPressed(daily.CLAIM_ALL, daily.MAIL_CLOSE)
        self.assertEqual("nothing to claim", self.state()["mail"])

    def test_the_toast_read_off_its_place_is_not_taken_for_it(self):
        screen = MAIL_AFTER + (("All items in the mail have been received.", 0.500, 0.700),)
        self.assertTrue(run_pass(self.task.show(screen)))
        self.assertPressed(daily.CLAIM_ALL)

    def test_a_mail_count_or_title_missing_is_not_the_mail_screen(self):
        for missing in ("Mail", "003 / 100"):
            with self.subTest(missing=missing):
                self.assertFalse(daily.on_mail(self.task.show([box for box in MAIL if box[0] != missing])))


class TestAttendance(Daily):

    def run_screens(self, screens):
        for screen in screens:
            run_pass(self.task.show(screen))
            self.tick()

    def test_todays_claim_reward_is_pressed_items_obtained_closed_then_the_popup_closed_on_its_x(self):
        """The stamped popup is left alone while the claim may still be landing, then closed on its X, with no stop."""
        self.run_screens([ATTENDANCE, ATTENDANCE_ITEMS] + [ATTENDANCE_STAMPED] * (daily.CLAIM_WAIT - 1))
        self.assertPressed(daily.ATTENDANCE_CLAIM, daily.ITEMS_CLOSE, daily.ATTENDANCE_CLOSE)
        self.assertNothingForbidden()
        self.assertEqual(0, self.task.disabled)

    def test_a_popup_already_claimed_is_given_time_to_draw_then_only_closed(self):
        """No Claim Reward: nothing on the first frame, then the X, and again only once the popup has had time to close."""
        self.task.show(ATTENDANCE_STAMPED)
        self.assertTrue(run_pass(self.task))
        self.assertEqual([], self.task.clicks)
        self.tick(daily.SETTLE)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.ATTENDANCE_CLOSE)
        for _ in range(daily.NAV_WAIT - 1):
            self.tick()
            self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.ATTENDANCE_CLOSE)
        self.tick()
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.ATTENDANCE_CLOSE, daily.ATTENDANCE_CLOSE)
        self.assertEqual(0, self.task.disabled)

    def test_a_claim_that_opens_nothing_is_retried_once_then_the_popup_is_closed(self):
        self.task.show(ATTENDANCE)
        for _ in range(2 * daily.CLAIM_WAIT + 1):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.ATTENDANCE_CLAIM, daily.ATTENDANCE_CLAIM, daily.ATTENDANCE_CLOSE)
        self.assertEqual(0, self.task.disabled)

    def test_the_popup_needs_its_title_and_its_tag_each_in_its_place(self):
        """Each also read where the Event list's page for the same event draws it, which is no popup."""
        moved = {"Invitation to a New Journey": (0.774, 0.136), "Permanent": (0.918, 0.201)}
        for text, place in moved.items():
            for case, screen in (("missing", tuple(box for box in ATTENDANCE if box[0] != text)),
                                 ("off its place", tuple((name, *place) if name == text else (name, x, y) for name, x, y in ATTENDANCE))):
                with self.subTest(text=text, case=case):
                    self.task = Task()
                    self.assertTrue(run_pass(self.task.show(screen)))
                    self.assertEqual([], self.task.clicks)

    def test_a_claim_reward_off_the_day_cards_is_not_pressed(self):
        """Over the art on the popup's left, where no card is, a Claim Reward is no claim; the popup is only closed."""
        off_cards = tuple(("Claim Reward", 0.200, 0.830) if box[0] == "Claim Reward" else box for box in ATTENDANCE)
        self.run_screens([off_cards] * (daily.SETTLE + 1))
        self.assertPressed(daily.ATTENDANCE_CLOSE)

    def test_the_event_lists_page_for_the_same_event_is_not_the_popup(self):
        """The list opened on the attendance event, today's card unclaimed: Dream Park is opened, no Claim Reward pressed."""
        self.state()["steps"]["mail"] = daily.DONE
        unclaimed = tuple(("Claim Reward", x, y) if (name, x) == ("Awaiting Attendance", 0.543) else (name, x, y) for name, x, y in EVENT_LIST)
        self.assertTrue(run_pass(self.task.show(unclaimed)))
        self.assertPressed(daily.DREAM_PARK)

    def test_a_slow_items_obtained_on_the_mail_and_on_the_claim_each_get_their_own_presses(self):
        """Each Items Obtained shows for two frames: four caption presses in the run, two per screen, and no stop."""
        self.run_screens([LOBBY, MENU, MAIL, ITEMS, ITEMS, MAIL_AFTER, ATTENDANCE, ATTENDANCE_ITEMS, ATTENDANCE_ITEMS]
                         + [ATTENDANCE_STAMPED] * (daily.CLAIM_WAIT - 2))
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.ITEMS_CLOSE, daily.MAIL_CLOSE,
                           daily.ATTENDANCE_CLAIM, daily.ITEMS_CLOSE, daily.ITEMS_CLOSE, daily.ATTENDANCE_CLOSE)
        self.assertEqual(0, self.task.disabled)

    def test_the_claims_items_obtained_still_stops_at_its_own_limit(self):
        limit = daily.TAP_LIMITS[daily.ITEMS_CLOSE]
        self.run_screens([ATTENDANCE] + [ATTENDANCE_ITEMS] * (limit + 1))
        self.assertPressed(daily.ATTENDANCE_CLAIM, *[daily.ITEMS_CLOSE] * limit)
        self.assertStopped(f"{daily.ITEMS_CLOSE} was pressed {limit} times")

    def test_the_popup_restarts_the_unknown_screen_clock(self):
        run_pass(self.task.show(SETTINGS))
        self.tick(daily.UNKNOWN_SECONDS - 1)
        run_pass(self.task.show(ATTENDANCE_STAMPED))
        self.tick()
        run_pass(self.task.show(SETTINGS))
        self.assertEqual(0, self.task.disabled)

    def test_the_popup_after_the_mail_is_claimed_and_the_run_goes_on_to_the_park(self):
        """The live order: the Mail popup's X opens the attendance popup, and its X lands on the Lobby."""
        no_park = [MENU] + [EVENT_LIST_WITHOUT_PARK] * (daily.SETTLE + 1)
        self.run_screens([LOBBY, MENU, MAIL, ITEMS, MAIL_AFTER, ATTENDANCE, ATTENDANCE_ITEMS] + [ATTENDANCE_STAMPED] * (daily.CLAIM_WAIT - 1)
                         + [LOBBY] + no_park + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, daily.ATTENDANCE_CLAIM,
                           daily.ITEMS_CLOSE, daily.ATTENDANCE_CLOSE, daily.MENU, daily.EVENT, daily.EVENT_LEAVE)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed; Dream Park is not running")


class TestLobbyAndMenu(Daily):

    def test_the_lobby_opens_the_menu_while_mail_is_pending_and_finishes_with_no_tap_once_done(self):
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.task.clicks.clear()
        self.state()["steps"]["mail"], self.state()["mail"] = daily.DONE, "claimed"
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.task.clicks.clear()
        self.finish_chores()
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily finished: mail claimed")

    def test_the_menu_opens_mail_then_event_while_pending_and_closes_once_done_never_shop_or_power(self):
        """5: on the plain menu and on the one with its key labels on."""
        for screen in (MENU, MENU_KEYS):
            with self.subTest(keys=screen is MENU_KEYS):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(screen)))
                self.state()["steps"]["mail"] = daily.DONE
                self.assertTrue(run_pass(self.task))
                self.finish_chores()
                self.assertTrue(run_pass(self.task))
                self.assertPressed(daily.ENVELOPE, daily.EVENT, daily.MENU_CLOSE)
                self.assertNothingForbidden()

    def test_the_lobby_is_not_read_under_the_open_menu(self):
        self.assertFalse(daily.on_lobby(self.task.show(MENU)))
        self.assertFalse(daily.on_menu(self.task.show(LOBBY)))

    def test_every_screen_needs_both_of_its_captions(self):
        """One caption alone can be a fragment read through a popup, or another screen's word."""
        cases = ((daily.on_lobby, LOBBY, ("故事", "Combatants")), (daily.on_menu, MENU, ("Achievement", "Arkhianon Supply")),
                 (daily.on_notice, NOTICE, ("Notice", "Update")), (daily.on_mail, MAIL, ("Mail", "003 / 100")))
        for check, screen, captions in cases:
            self.assertTrue(check(self.task.show(screen)), captions)
            for caption in captions:
                with self.subTest(missing=caption):
                    self.assertFalse(check(self.task.show([box for box in screen if box[0] != caption])))
        for caption in ("Items Obtained", "点击屏幕关闭窗口"):
            with self.subTest(missing=caption):
                self.assertFalse(daily.handle_daily_items_obtained(self.task.show([box for box in ITEMS if box[0] != caption])))
        self.assertEqual([], self.task.clicks)

    def test_the_notice_board_is_closed_on_its_x_and_go_now_is_never_pressed(self):
        self.assertTrue(run_pass(self.task.show(NOTICE)))
        self.assertPressed(daily.NOTICE_CLOSE)
        self.assertNothingForbidden()


class TestBanner(Daily):

    def test_the_banner_x_is_found_on_the_banner_and_pressed(self):
        self.assertTrue(run_pass(self.task.show(BANNER, corner("daily_corner_banner"))))
        self.assertPressed(daily.BANNER_CLOSE)
        self.assertNothingForbidden()

    def test_the_lobby_the_menu_and_a_plain_x_are_not_the_banner(self):
        """7: the banner's X point lands on the Lobby's Menu, so a false match there opens the menu unasked."""
        for name in ("daily_corner_lobby", "daily_corner_menu", "daily_corner_plain_x"):
            with self.subTest(corner=name):
                frame = corner(name)
                self.assertIsNone(daily.find_icon(frame, daily.BANNER_CLOSE_IMAGE, daily.BANNER_MATCH, daily.BANNER_CORNER))
                self.assertFalse(daily.handle_daily_banner(self.task.show(BANNER, frame)))
        self.assertEqual([], self.task.clicks)

    def test_the_banner_x_outside_the_corner_is_not_the_banner(self):
        """7: a banner's X elsewhere would still get the tap at the corner's fixed point.

        Each X reaches 2 px past the corner's left or bottom edge, so a corner widened by 2 px takes in the whole X.
        """
        for where, region in (("across the left edge", (0.859375, 0.0, 0.959375, 0.12)), ("across the bottom edge", (0.90, 0.0454, 1.0, 0.1654))):
            with self.subTest(where=where):
                frame = placed("daily_corner_banner", region)
                self.assertIsNotNone(daily.find_icon(frame, daily.BANNER_CLOSE_IMAGE, daily.BANNER_MATCH, (0.0, 0.0, 1.0, 1.0)))
                self.assertFalse(daily.handle_daily_banner(self.task.show(BANNER, frame)))
        self.assertEqual([], self.task.clicks)

    def test_the_banner_check_stands_down_on_a_screen_another_check_knows(self):
        frame = corner("daily_corner_banner")
        for screen in (LOBBY, MENU, NOTICE):
            with self.subTest(screen=screen[0][0]):
                self.assertFalse(daily.handle_daily_banner(self.task.show(screen, frame)))
        self.assertEqual([], self.task.clicks)


class TestFadedLobby(Daily):

    def test_a_faded_lobby_moments_after_a_lobby_read_gets_the_menu_tap(self):
        run_pass(self.task.show(LOBBY))
        self.tick(19)
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.assertPressed(daily.MENU, daily.MENU)

    def test_a_faded_lobby_gets_no_menu_tap_without_a_recent_lobby_or_a_pending_step(self):
        """Past the Lobby read's time, or with every chore done, the faded Lobby gets the wake tap instead."""
        for case, wait in (("stale Lobby read", daily.FADED_SECONDS), ("chores done", 1)):
            with self.subTest(case=case):
                self.task = Task()
                run_pass(self.task.show(LOBBY))
                self.tick(wait)
                if wait == 1:
                    self.finish_chores()
                self.assertTrue(daily.handle_daily_faded_lobby(self.task.show(FADED, faded_lobby())))
                self.assertPressed(daily.MENU, daily.WAKE)

    def test_a_frame_reading_nothing_moments_after_a_lobby_read_gets_no_tap_unless_it_is_the_faded_lobby(self):
        """A live run pressed Menu on the Mail popup still loading and inside the park after a build, both read as nothing."""
        frames = {"black": np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), "no capture": None}
        frames.update({name: placed(name, SCENE_REGION) for name in ("daily_blank_mail", "daily_blank_park", "daily_blank_cutscene")})
        for name, frame in frames.items():
            with self.subTest(frame=name):
                self.task = Task()
                run_pass(self.task.show(LOBBY))
                self.tick()
                self.assertFalse(daily.handle_daily_faded_lobby(self.task.show(FADED, frame)))
                self.assertPressed(daily.MENU)

    def test_a_screen_with_any_confident_text_is_not_a_faded_lobby(self):
        run_pass(self.task.show(LOBBY))
        self.assertFalse(daily.handle_daily_faded_lobby(self.task.show((("Loading", 0.5, 0.5),))))
        self.assertPressed(daily.MENU)

    def test_the_low_confidence_scrap_ocr_reads_off_the_faded_lobby_still_counts_as_faded(self):
        """264 read `rort` at 0.585 through the app's own OCR settings, whose floor is 0.2."""
        run_pass(self.task.show(LOBBY))
        self.task.show((("rort", 0.083, 0.531),), faded_lobby())
        self.task.all_texts[0].confidence = 0.585
        self.assertTrue(daily.handle_daily_faded_lobby(self.task))
        self.task.all_texts[0].confidence = 0.69
        self.assertTrue(daily.handle_daily_faded_lobby(self.task))
        self.task.all_texts[0].confidence = 0.7
        self.assertFalse(daily.handle_daily_faded_lobby(self.task))
        self.assertPressed(daily.MENU, daily.MENU, daily.MENU)


class TestFadedStart(Daily):
    """A start on an idle Lobby: no Lobby read yet, so only the faded Lobby's own scene earns the wake tap."""

    def test_a_start_on_a_faded_lobby_is_woken_once_then_runs_on(self):
        for _ in range(daily.WAKE_WAIT):
            self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
            self.tick()
        self.assertPressed(daily.WAKE)
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.WAKE, daily.MENU)
        self.assertEqual(0, self.task.disabled)

    def test_the_faded_lobby_with_its_character_standing_is_woken_too(self):
        """352: the UI gone, the character still there."""
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby("daily_faded_lobby_character"))))
        self.assertPressed(daily.WAKE)

    def test_a_wake_the_game_ignored_is_retried_once_then_stops(self):
        self.task.show(FADED, faded_lobby())
        for _ in range(2 * daily.WAKE_WAIT):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.WAKE, daily.WAKE)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.WAKE, daily.WAKE)
        self.assertStopped("the faded Lobby's sky was pressed 2 times")

    def test_a_frame_that_reads_nothing_but_is_not_the_faded_lobby_gets_no_tap(self):
        """Black, a Rescue flash, a cut-scene and the carnival's intro read nothing too, as OCR saw them."""
        frames = {"black": np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), "no capture": None}
        frames.update({name: placed(name, SCENE_REGION) for name in ("daily_blank_cutscene", "daily_blank_rescue_flash", "daily_blank_carnival")})
        for name, frame in frames.items():
            with self.subTest(frame=name):
                self.task = Task()
                for _ in range(daily.UNKNOWN_SECONDS):
                    self.assertTrue(run_pass(self.task.show(FADED, frame)))
                    self.tick()
                self.assertTrue(run_pass(self.task))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Daily does not know this screen")

    def test_the_scene_half_covered_by_a_dialogue_is_not_the_faded_lobby(self):
        """326: the Lobby's scene under the tutorial's dialogue box came closest of every other capture, at 0.455."""
        frame = placed("daily_scene_under_dialogue", SCENE_REGION)
        self.assertIsNone(daily.find_icon(frame, daily.FADED_SCENE_IMAGE, daily.FADED_SCENE_MATCH, daily.FADED_SCENE_REGION, daily.grey))
        self.assertTrue(run_pass(self.task.show(FADED, frame)))
        self.assertEqual([], self.task.clicks)

    def test_the_faded_scene_under_confident_text_gets_no_wake(self):
        """A popup over the faded scene reads its own text, and only a screen reading nothing can be the faded Lobby."""
        self.assertFalse(daily.handle_daily_faded_lobby(self.task.show(SETTINGS, faded_lobby())))
        self.assertEqual([], self.task.clicks)

    def test_a_lobby_faded_again_after_the_chores_is_woken_and_finishes(self):
        self.finish_chores()
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.tick()
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.WAKE)
        self.assertStopped("Daily finished: mail claimed")

    def test_the_menu_tap_moments_after_a_lobby_read_still_comes_first(self):
        run_pass(self.task.show(LOBBY))
        self.tick()
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.assertPressed(daily.MENU, daily.MENU)

    def test_the_wake_point_is_open_sky_away_from_every_target(self):
        """Measured on 264, 272, 352 and a live run's woken Lobby: no button within 0.08 of it on any of them."""
        for target, point in POINTS.items():
            if target != daily.WAKE:
                self.assertGreater(max(abs(point[0] - 0.300), abs(point[1] - 0.420)), 0.08, target)
        for screen in (LOBBY, MENU, TUTORIAL_LOBBY):
            self.assertEqual([], daily.boxes_at(self.task.show(screen), POINTS[daily.WAKE]))


class TestTutorial(Daily):
    """The tutorial's Skip Tutorial pill covers the Menu point, the banner's X and the menu's X, and a tap on it skips the tutorial."""

    def test_a_tutorial_lobby_stops_daily_with_nothing_pressed(self):
        self.assertTrue(run_pass(self.task.show(TUTORIAL_LOBBY)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Skip Tutorial shows")

    def test_the_plain_lobby_still_gets_the_menu_tap(self):
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.assertEqual(0, self.task.disabled)

    def test_the_pill_stops_daily_on_every_screen_it_presses_on(self):
        for name, texts, frame in (("menu", MENU, None), ("notice", NOTICE, None), ("mail", MAIL, None), ("items", ITEMS, None),
                                   ("banner", BANNER, corner("daily_corner_banner")), ("unknown", SETTINGS, None)):
            with self.subTest(screen=name):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(texts + (SKIP_TUTORIAL,), frame)))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Skip Tutorial shows")

    def test_the_pill_is_read_anywhere_and_with_its_space_dropped(self):
        """Its text centre has sat at x 0.879-0.880, but a tap on the Menu point lands on the pill wherever its caption reads."""
        for name, box in (("left of its place", ("Skip Tutorial", 0.70, 0.06)), ("lower", ("Skip Tutorial", 0.88, 0.15)),
                          ("space dropped", ("SkipTutorial", 0.879, 0.055)), ("upper case", ("SKIP TUTORIAL", 0.879, 0.055))):
            with self.subTest(pill=name):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(LOBBY + (box,))))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Skip Tutorial shows")

    def test_a_pill_read_at_low_confidence_after_a_lobby_read_gets_no_faded_tap(self):
        """A frame reading only the pill, faintly, would otherwise count as a faded Lobby and get the Menu tap on the pill."""
        run_pass(self.task.show(LOBBY))
        self.tick()
        self.task.show((SKIP_TUTORIAL,))
        self.task.all_texts[0].confidence = 0.5
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.MENU)
        self.assertStopped("Skip Tutorial shows")

    def test_the_pill_mid_run_stops_daily_before_its_next_press(self):
        screens = [LOBBY, MENU, MAIL + (SKIP_TUTORIAL,), ITEMS]
        for texts in screens:
            if not self.task.enabled:
                break
            run_pass(self.task.show(texts))
            self.tick()
        self.assertPressed(daily.MENU, daily.ENVELOPE)
        self.assertStopped("Skip Tutorial shows")

    def test_the_targets_it_covers_are_the_ones_measured(self):
        """The Menu, the banner's X and the menu's X lie on the pill; Daily's other fixed points do not.

        The Mail popup's X lies 0.002 below the outline but inside the box the guard in `skip_tutorial` refuses.
        """
        left, top, right, bottom = SKIP_TUTORIAL_PILL
        covered = {name for name, point in POINTS.items() if left <= point[0] <= right and top <= point[1] <= bottom}
        self.assertEqual({daily.MENU, daily.BANNER_CLOSE, daily.MENU_CLOSE}, covered)
        self.assertEqual(SKIP_TUTORIAL_PILL, skip_tutorial.OUTLINE)
        left, top, right, bottom = skip_tutorial.GUARDED
        guarded = {name for name, point in POINTS.items() if left <= point[0] <= right and top <= point[1] <= bottom}
        self.assertEqual(covered | {daily.MAIL_CLOSE}, guarded)

    def test_the_pill_on_the_mail_popup_stops_daily_before_its_x(self):
        self.state()["steps"]["mail"] = daily.DONE
        self.assertTrue(run_pass(self.task.show(MAIL_AFTER + (SKIP_TUTORIAL,))))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Skip Tutorial shows")


class TestStops(Daily):

    def test_an_unknown_screen_gets_no_press_and_stops_after_thirty_seconds(self):
        for elapsed in range(30):
            self.assertTrue(run_pass(self.task.show(SETTINGS)), elapsed)
            self.assertEqual(0, self.task.disabled, elapsed)
            self.tick()
        self.assertTrue(run_pass(self.task))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily does not know this screen")

    def test_a_known_screen_restarts_the_unknown_clock(self):
        run_pass(self.task.show(SETTINGS))
        self.tick(29)
        run_pass(self.task.show(NOTICE))
        self.tick()
        run_pass(self.task.show(SETTINGS))
        self.assertEqual(0, self.task.disabled)

    def test_a_rescue_screen_or_dialog_stops_at_once_with_nothing_pressed(self):
        for screen in (RESCUE, PAID_RESCUE):
            with self.subTest(screen=screen[0][0]):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(screen)))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Rescue screen")

    def test_a_run_past_its_time_limit_stops_with_nothing_pressed(self):
        self.state()
        self.tick(daily.RUN_SECONDS)
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily ran for 10 minutes")

    def test_every_target_stops_at_its_limit(self):
        for target, limit in daily.TAP_LIMITS.items():
            with self.subTest(target=target):
                self.task = Task()
                box = FakeBox(target, *POINTS[target]) if daily.TARGETS[target] is None else None
                for _ in range(limit + 1):
                    daily.press(self.task, target, box)
                self.assertEqual(limit, len(self.task.clicks))
                self.assertStopped(f"{target} was pressed {limit} times")

    def test_only_a_rides_upgrade_watches_its_level_instead_of_the_full_wait(self):
        for target in daily.TAP_LIMITS:
            with self.subTest(target=target):
                self.task = Task()
                box = FakeBox(target, *POINTS[target]) if daily.TARGETS[target] is None else None
                daily.press(self.task, target, box, 7)
                upgrade = target == daily.UPGRADE
                self.assertEqual([0 if upgrade else story.AFTER_TAP], self.task.waits)
                self.assertEqual(upgrade, bool(self.task.zones))

    def test_the_limits_are_as_designed(self):
        special = {daily.CLAIM_ALL: 2, daily.ATTENDANCE_CLAIM: 2, daily.WAKE: 2, daily.RANK_UP: 2, daily.UPGRADE: 200, daily.CLAIM: 30, daily.SKIP_TICK: 1,
                   daily.SKILL_UPGRADE: 30}
        self.assertEqual({target: special.get(target, 3) for target in POINTS}, daily.TAP_LIMITS)
        self.assertEqual(set(POINTS), set(daily.TARGETS))

    def test_menu_and_mail_presses_count_only_until_the_mail_screen_shows(self):
        """A later step opens the menu again, and the presses that got the mail open were not stuck ones."""
        for _ in range(daily.TAP_LIMITS[daily.MENU]):
            daily.press(self.task, daily.MENU)
        run_pass(self.task.show(MAIL))
        self.assertTrue(daily.press(self.task, daily.MENU))
        self.assertEqual(0, self.task.disabled)


class TestRefusals(Daily):

    def test_a_target_over_a_box_that_must_never_be_pressed_stops_instead(self):
        """The backstop under every press: each marker under the Menu point, on the Lobby."""
        for text in ("Delete read mail", "Delete", "Shop", "Purchase", "Buy", "Spend 1600 Crystals", "US$4.99", "₩1,200", "营救", "Aether"):
            with self.subTest(text=text):
                self.task = Task()
                self.task.show(LOBBY + ((text, *POINTS[daily.MENU]),))
                self.assertTrue(run_pass(self.task))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("would have pressed")

    def test_card_text_holding_the_currency_name_is_not_refused(self):
        """The backstop reads the spend guard's markers, so a card word is no Crystal there either."""
        for text in ("2 Crystallization", "Foggy Crystal Ball"):
            with self.subTest(text=text):
                self.assertIsNone(daily.refused(text))
        for text in ("30 Crystals", "Crystalx100", "6.37K Crystal"):
            with self.subTest(text=text):
                self.assertEqual("crystal", daily.refused(text))

    def test_a_rescue_phrase_is_refused_by_the_backstop_too(self):
        """On a whole screen the Rescue stop sees it first, so the backstop is checked on its own."""
        for text in ("Rescue 10 time(s)", "Selective Rescue", "Free Rescue", "Rescue"):
            with self.subTest(text=text):
                self.assertIsNotNone(daily.refused(text))
                self.task = Task()
                self.task.show(((text, *POINTS[daily.MENU]),))
                self.assertTrue(daily.press(self.task, daily.MENU))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("would have pressed")

    def test_a_text_button_reading_as_a_refused_word_is_not_pressed(self):
        self.assertTrue(daily.press(self.task, daily.CLAIM_ALL, FakeBox("Delete read mail", *NEVER["Delete read mail"])))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed")

    def test_the_backstop_passes_every_target_on_its_own_screen(self):
        """Nothing Daily presses reads as a refused word, the menu's Shop and Rescue lying well away from its targets."""
        for screen in (LOBBY, MENU, MENU_KEYS, NOTICE, MAIL, MAIL_AFTER, ITEMS, ATTENDANCE, ATTENDANCE_STAMPED):
            for box in screen:
                if box[0] in ("Shop", "营救", "Delete read mail", "Delete"):
                    self.assertIsNotNone(daily.refused(box[0]), box[0])
        for target, point in POINTS.items():
            for screen in (LOBBY, MENU, NOTICE, MAIL, MAIL_AFTER, ITEMS, ATTENDANCE, ATTENDANCE_STAMPED):
                hits = daily.boxes_at(self.task.show(screen), point)
                self.assertEqual([], [box.name for box in hits if daily.refused(box.name)], target)

    def test_negative_control_a_loose_claim_all_without_the_backstop_presses_delete(self):
        """12: proves test 1's check bites. With the backstop gone and Claim All matched as the bottom bar's second button, Delete is pressed."""
        with mock.patch.object(daily, "claim_all_button", second_bottom_button), mock.patch.object(daily, "refused", lambda text: None):
            run_pass(self.task.show(MAIL_AFTER))
        with self.assertRaises(AssertionError):
            self.assertNothingForbidden()

    def test_a_loose_claim_all_alone_is_stopped_by_the_backstop(self):
        with mock.patch.object(daily, "claim_all_button", second_bottom_button):
            run_pass(self.task.show(MAIL_AFTER))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed 'Delete read mail'")


class TestWholeRun(Daily):

    # The park step after the mail, on a client whose Event list no longer has Dream Park.
    NO_PARK = [MENU] + [EVENT_LIST_WITHOUT_PARK] * (daily.SETTLE + 1)
    NO_PARK_PRESSES = (daily.MENU, daily.EVENT, daily.EVENT_LEAVE)

    def run_screens(self, screens):
        for screen in screens:
            texts, frame = screen if isinstance(screen, tuple) and len(screen) == 2 and isinstance(screen[1], np.ndarray) else (screen, None)
            run_pass(self.task.show(texts, frame))
            self.tick()

    def test_banner_notice_menu_mail_claim_and_the_x_back_to_a_finished_lobby(self):
        """The order the live client showed, the Mail popup's X landing on the Lobby with the menu closed."""
        self.run_screens([(BANNER, corner("daily_corner_banner")), NOTICE, LOBBY, MENU, (MAIL, claim_all(lit=True)), ITEMS,
                          (MAIL_AFTER, claim_all(lit=False)), LOBBY] + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.BANNER_CLOSE, daily.NOTICE_CLOSE, daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE,
                           daily.MAIL_CLOSE, *self.NO_PARK_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed; Dream Park is not running")

    def test_an_x_landing_on_the_open_menu_goes_on_to_the_event_list_and_finishes(self):
        self.run_screens([LOBBY, MENU, MAIL, ITEMS, MAIL_AFTER] + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, daily.EVENT, daily.EVENT_LEAVE)
        self.assertStopped("Daily finished: mail claimed")

    def test_an_empty_mailbox_presses_no_claim_all_and_ends_on_the_lobby(self):
        """The live run's order: the popup with Claim All greyed, then the Lobby the X lands on."""
        empty = (MAIL_EMPTY, claim_all(lit=False))
        self.run_screens([LOBBY, MENU] + [empty] * (daily.CLAIM_WAIT + 1) + [LOBBY] + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.MAIL_CLOSE, *self.NO_PARK_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: no mail to claim")

    def test_a_start_on_a_faded_lobby_wakes_it_claims_and_ends_on_the_lobby(self):
        self.run_screens([(FADED, faded_lobby()), LOBBY, MENU, (MAIL, claim_all(lit=True)), ITEMS, (MAIL_AFTER, claim_all(lit=False)), LOBBY]
                         + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.WAKE, daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, *self.NO_PARK_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed")


def stand_in(module):
    """Copy a module so an install edits the copy, its handler list included.

    Args:
        module: The real module.

    Returns:
        The copy, under the same name.
    """
    copy = types.ModuleType(module.__name__)
    copy.__dict__.update(vars(module))
    if isinstance(getattr(module, handlers.HANDLER_LIST, None), list):
        copy.PAGE_HANDLERS = list(PRISTINE if module is daily else module.PAGE_HANDLERS)
    return copy


def registered_installs():
    """Rebuild every handler-list edit the app registers, in the order `src/globals.py` applies the modules.

    Each `register(...)` inside a module's `apply` is evaluated in that module's own namespace, with any function `apply`
    defines for it, so the edits are the app's own without running the rest of `apply`, which patches the framework.

    Returns:
        The install callables.
    """
    source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
    installs = []
    for name in re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M):
        module = importlib.import_module(f"src.en.{name}")
        module_source = Path(module.__file__).read_text(encoding="utf-8")
        for node in ast.parse(module_source).body:
            if not (isinstance(node, ast.FunctionDef) and node.name == "apply"):
                continue
            namespace = dict(vars(module))
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef):
                    exec(textwrap.dedent(ast.get_source_segment(module_source, statement, padded=True)), namespace)  # noqa: S102
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "register" and call.args:
                    installs.append(eval(ast.get_source_segment(module_source, call.args[0]), namespace))  # noqa: S307
    return installs


class TestHandlerList(unittest.TestCase):

    def test_after_every_install_daily_runs_remote_the_stuck_stop_the_rescue_stop_then_its_own_and_nothing_generic(self):
        """10: an upstream handler inserted with no mode named would otherwise reach Daily's list."""
        self.assertEqual([handler.__name__ for handler in OWN], [handler.__name__ for handler in PRISTINE])
        real = {name: sys.modules[name] for name, _ in handlers.each_list()}
        real.update({name: sys.modules[name] for name in ("utils", "utils_chaos", "utils_sortie", "utils_story", daily.__name__)})
        copies = {name: stand_in(module) for name, module in real.items()}
        installs = registered_installs()
        self.assertGreater(len(installs), 20)
        with mock.patch.dict(sys.modules, copies):
            for _ in range(INSTALLS):
                for install in installs:
                    install()
        names = [handler.__name__ for handler in copies[daily.__name__].PAGE_HANDLERS]
        self.assertEqual(["handle_remote", "stop_when_stuck"] + [handler.__name__ for handler in OWN], names)
        for name in FORBIDDEN:
            self.assertNotIn(name, names)
        self.assertIn("handle_non_battle_page", [handler.__name__ for handler in copies["utils_story"].PAGE_HANDLERS])

    def test_after_every_install_every_mode_runs_the_hold_first_and_the_stuck_stop_next_to_its_first_own_handler(self):
        """A held run takes no pass of the stop, so a still screen while held never ends it, and unheld the stop still comes first."""
        real = {name: sys.modules[name] for name, _ in handlers.each_list()}
        real.update({name: sys.modules[name] for name in ("utils", "utils_chaos", "utils_sortie", "utils_story", daily.__name__)})
        copies = {name: stand_in(module) for name, module in real.items()}
        with mock.patch.dict(sys.modules, copies):
            for _ in range(INSTALLS):
                for install in registered_installs():
                    install()
        first_own = {"utils_chaos": "handle_auto_stop", "utils_sortie": "handle_auto_stop", "utils_story": "handle_center_confirm",
                     daily.__name__: "handle_rescue_screen"}
        for mode, anchor in first_own.items():
            with self.subTest(mode=mode):
                names = [handler.__name__ for handler in copies[mode].PAGE_HANDLERS]
                self.assertEqual("handle_remote", names[0])
                self.assertEqual(1, names.count("stop_when_stuck"))
                self.assertLess(names.index("stop_when_stuck"), names.index(anchor))

    def test_daily_is_applied_before_claims(self):
        """claims wraps the lists as it finds them, so nothing Daily's list gets later would be named in the frame log."""
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertLess(applied.index("stuck_stop"), applied.index("daily"))
        self.assertLess(applied.index("daily"), applied.index("claims"))

    def test_daily_is_built_from_the_config_as_a_trigger_task(self):
        """The shell gives every trigger task a Start button."""
        from src.config import config

        self.assertIn(["src.en.daily", "DailyMode"], config["trigger_tasks"])
        self.assertTrue(issubclass(daily.DailyMode, TriggerTask))

    def test_daily_imports_nothing_from_ok_tasks_at_import(self):
        """ok-script builds it before `ok_tasks/` is on `sys.path`."""
        tree = ast.parse((REPO_ROOT / "src" / "en" / "daily.py").read_text(encoding="utf-8"))
        tasks = {path.stem for path in (REPO_ROOT / "ok_tasks").glob("*.py")}
        for node in tree.body:
            if isinstance(node, ast.Import):
                self.assertFalse({alias.name.split(".")[0] for alias in node.names} & tasks)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], tasks)


class Mode:
    """Another mode of the app, enabled and stopped as the executor would."""

    def __init__(self, journal):
        self.journal = journal
        self.enabled = False

    def enable(self):
        self.enabled = True
        self.journal.append(("enable", type(self).__name__))

    def disable(self):
        self.enabled = False
        self.journal.append(("disable", type(self).__name__))


class ChaosMode(Mode):
    pass


class SortieMode(Mode):
    pass


class StoryMode(Mode):
    pass


class TestOneModeAtATime(unittest.TestCase):

    def setUp(self):
        self.journal = []
        self.others = [ChaosMode(self.journal), SortieMode(self.journal), StoryMode(self.journal)]
        self.daily = daily.DailyMode.__new__(daily.DailyMode)
        self.daily._enabled = False
        self.daily._executor = Executor(self.daily, *self.others)
        journal = self.journal

        def enable(task):
            task._enabled = True
            journal.append(("enable", type(task).__name__))

        def disable(task):
            task._enabled = False
            journal.append(("disable", type(task).__name__))

        for name, replacement in (("enable", enable), ("disable", disable)):
            patcher = mock.patch.object(TriggerTask, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_starting_daily_stops_whichever_mode_runs(self):
        for other in self.others:
            with self.subTest(mode=type(other).__name__):
                other.enabled = True
                self.journal.clear()
                self.daily.enable()
                self.assertEqual([("disable", type(other).__name__), ("enable", "DailyMode")], self.journal)
                self.assertFalse(other.enabled)

    def test_starting_another_mode_stops_daily(self):
        """11: through `load_config`, which the run loop and the debug port's `set_running` both start the mode after."""
        load_config = daily.teaching_modes(lambda task: None)
        for other in self.others:
            with self.subTest(mode=type(other).__name__):
                other.executor = self.daily._executor
                load_config(other)
                self.daily._enabled = True
                self.journal.clear()
                other.enable()
                self.assertEqual([("disable", "DailyMode"), ("enable", type(other).__name__)], self.journal)
                self.assertFalse(self.daily.enabled)

    def test_daily_itself_and_other_tasks_are_not_wrapped(self):
        load_config = daily.teaching_modes(lambda task: None)
        original = self.daily.enable
        load_config(self.daily)
        self.assertNotIn("enable", vars(self.daily))
        self.assertEqual(original, self.daily.enable)

    def test_a_start_begins_the_run_afresh_and_a_stop_forgets_it(self):
        state = daily.run_state(self.daily)
        state["steps"]["mail"] = daily.DONE
        self.daily.enable()
        self.assertEqual(daily.PENDING, daily.run_state(self.daily)["steps"]["mail"])
        self.daily.disable()
        self.assertNotIn(daily.RUN, vars(self.daily))


class TestStuckStopReachesDaily(unittest.TestCase):

    def test_the_stuck_stop_goes_after_remote_and_ahead_of_the_rescue_stop_once(self):
        module = types.ModuleType(daily.__name__)
        module.PAGE_HANDLERS = [types.SimpleNamespace(__name__="handle_remote")] + list(PRISTINE)
        fake_utils = types.SimpleNamespace(is_frame_stuck=lambda task, stuck_threshold_seconds=0: False)
        with mock.patch.dict(sys.modules, {daily.__name__: module}):
            for _ in range(INSTALLS):
                stuck_stop.install(fake_utils)
        self.assertEqual(["handle_remote", "stop_when_stuck", "handle_rescue_screen"], [handler.__name__ for handler in module.PAGE_HANDLERS[:3]])
        self.assertEqual(len(PRISTINE) + 2, len(module.PAGE_HANDLERS))


if __name__ == "__main__":
    unittest.main()
