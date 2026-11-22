"""Run the daily chores from the Lobby: close its entry popups, claim all mail, visit Nightmare Dream Park, and stop on a clean Lobby.

The Lobby, its menu and the Mail screen sit next to buttons that delete mail, open the Shop, refill Aether with Crystals,
open Rescue or quit the game. So Daily presses only the fixed targets in `TARGETS`, each on the one screen it belongs to,
every press goes through `press`, which refuses a box that reads as any of those, and each target has a per-run limit.
A screen Daily does not know for 30 seconds, and the tutorial, stop it with nothing pressed.

The park spends only its own profit, a free counter that refills while the player is away. Its rows are read by
`dream_park`, and one is pressed only when its price reads as a plain park number.

Imported by ok-script before `ok_tasks/` is on `sys.path`, so upstream is reached only through `handlers.loaded`.
"""

import re
import time
from collections import Counter, namedtuple
from pathlib import Path

import numpy as np
from ok import Logger, TriggerTask

from src.en import dream_park
from src.en.handlers import loaded
from src.en.notify import announce
from src.en.screen import centre_of, colour_share, frame_of, in_region, patch_of, text_in_region
from src.en.spend_guard import ACCOUNT, DELETION, MONEY, PURCHASE, RESCUE_HEADER, RESCUE_PHRASES, cleaned, folded, handle_rescue_screen, marker_in
from src.en.story import find_icon, grey, tap

logger = Logger.get_logger(__name__)

# The modes Daily may never run beside. Their own `enable`s know nothing of Daily, so `apply` teaches them.
OTHER_MODES = ("ChaosMode", "SortieMode", "StoryMode")

# What Daily presses, by name. A point is fixed by the screen's layout; None is a text button, pressed on the box OCR read.
BANNER_CLOSE = "the entry banner's X"
NOTICE_CLOSE = "the Notice board's X"
MENU = "the Lobby's Menu"
ENVELOPE = "the menu's Mail"
MENU_CLOSE = "the menu's X"
CLAIM_ALL = "Claim All"
ITEMS_CLOSE = "the Items Obtained caption"
MAIL_CLOSE = "the Mail popup's X"
WAKE = "the faded Lobby's sky"
EVENT = "the menu's Event"
DREAM_PARK = "the Event list's Dream Park"
EVENT_LEAVE = "the Event list's back arrow"
ENTER_PARK = "Enter Amusement Park"
PARK_ACHIEVEMENTS = "the event page's Achievements"
PAGE_LEAVE = "the event page's back arrow"
PARK_MANAGE = "the park's Manage"
PARK_OPERATE = "the park's Operate"
PANEL_CLOSE = "the park panel's back arrow"
PARK_LEAVE = "the park's back arrow"
PARK_RANK = "Amusement Park Rank"
RANK_UP = "Rank Up"
RANK_CLOSE = "the Rank screen's X"
RANK_RESULT_CLOSE = "the Rank result's caption"
UPGRADE = "a ride's Upgrade"
BUILD = "a ride's Build"
CLAIM = "an achievement's claim ring"
MANAGEMENT_TAB = "the Achievements' Management tab"
ACHIEVEMENTS_LEAVE = "the Achievements' back arrow"
RULES_CANCEL = "the Rules of Good Order's 取消"
# Every Dream Park screen draws its back arrow at the same place, and each press of it takes one screen back.
BACK = (0.041, 0.046)
TARGETS = {
    BANNER_CLOSE: (0.968, 0.049),
    NOTICE_CLOSE: (0.911, 0.120),
    MENU: (0.959, 0.046),
    ENVELOPE: (0.962, 0.280),
    MENU_CLOSE: (0.961, 0.049),
    MAIL_CLOSE: (0.936, 0.093),
    WAKE: (0.300, 0.420),
    CLAIM_ALL: None,
    ITEMS_CLOSE: None,
    EVENT: (0.783, 0.088),
    DREAM_PARK: None,
    EVENT_LEAVE: BACK,
    ENTER_PARK: None,
    PARK_ACHIEVEMENTS: None,
    PAGE_LEAVE: BACK,
    PARK_MANAGE: (0.087, 0.294),
    PARK_OPERATE: (0.087, 0.473),
    PANEL_CLOSE: BACK,
    PARK_LEAVE: BACK,
    PARK_RANK: (0.804, 0.906),
    RANK_UP: None,
    RANK_CLOSE: (0.977, 0.137),
    RANK_RESULT_CLOSE: None,
    UPGRADE: None,
    BUILD: None,
    CLAIM: None,
    MANAGEMENT_TAB: (0.100, 0.270),
    ACHIEVEMENTS_LEAVE: BACK,
    RULES_CANCEL: None,
}
# How many upgrades one park visit may press, one level each, so the cap only bounds a loop that has gone wrong, and how
# many achievement claims: the event has 23 achievements.
UPGRADE_CAP = 200
CLAIM_CAP = 30
# How often each target may be pressed in one run. Claim All, the wake tap and Rank Up get one retry for a tap the game
# ignored; the rest allow two retries for a screen slow to change. A target leading to another screen counts only until
# that screen shows (`ARRIVALS`), so a later step, or the next round of the park, may press it again.
TAP_LIMITS = {BANNER_CLOSE: 3, NOTICE_CLOSE: 3, MENU: 3, ENVELOPE: 3, MENU_CLOSE: 3, MAIL_CLOSE: 3, WAKE: 2, CLAIM_ALL: 2, ITEMS_CLOSE: 3,
              EVENT: 3, DREAM_PARK: 3, EVENT_LEAVE: 3, ENTER_PARK: 3, PARK_ACHIEVEMENTS: 3, PAGE_LEAVE: 3, PARK_MANAGE: 3, PARK_OPERATE: 3,
              PANEL_CLOSE: 3, PARK_LEAVE: 3, PARK_RANK: 3, RANK_UP: 2, RANK_CLOSE: 3, RANK_RESULT_CLOSE: 3, UPGRADE: UPGRADE_CAP, BUILD: 3,
              CLAIM: CLAIM_CAP, MANAGEMENT_TAB: 3, ACHIEVEMENTS_LEAVE: 3, RULES_CANCEL: 3}
TOWARD_MAIL = (MENU, ENVELOPE)

# What `press` refuses whatever it was asked to press: mail deletion, the Shop, a purchase, Crystals or any account
# currency, a real price, and Rescue. Read off the box under the point, folded as the spend guard folds it.
REFUSED_GROUPS = (ACCOUNT, PURCHASE, DELETION, MONEY)
SHOP = ("shop", "商店")

# Each screen as `(left, top, right, bottom)` screen fractions around where its captions read on the Global client.
# The Lobby: Story where upstream's own Lobby stop reads it, at (0.884, 0.156), and Combatants at (0.867, 0.617). The open
# menu slides that column left, Story to (0.581, 0.091), so the Lobby never reads as itself under the menu.
LOBBY_STORY = ("故事", (0.85, 0.12, 0.92, 0.20))
LOBBY_COMBATANTS = ("Combatants", (0.82, 0.58, 0.92, 0.66))
# The open menu: Achievement at (0.808, 0.520) and Arkhianon Supply at (0.825, 0.160).
MENU_ACHIEVEMENT = ("Achievement", (0.76, 0.49, 0.86, 0.55))
MENU_SUPPLY = ("Arkhianon Supply", (0.77, 0.13, 0.88, 0.19))
# The Notice board's two tabs, at (0.216, 0.119) and (0.403, 0.119).
NOTICE_TAB = ("Notice", (0.15, 0.08, 0.30, 0.16))
UPDATE_TAB = ("Update", (0.33, 0.08, 0.47, 0.16))
# The Mail popup's title at (0.107, 0.090) and its `003 / 100` count at (0.844, 0.090). Its X sits 0.024 right of a
# column of three dots, and the envelope beside the title, which OCR reads as `√`, is no back arrow.
MAIL_TITLE = ("Mail", (0.06, 0.06, 0.16, 0.12))
MAIL_COUNT_REGION = (0.78, 0.06, 0.90, 0.12)
MAIL_COUNT = re.compile(r"\d{3}/100")
# Claim All, read at (0.194, 0.904). `Delete read mail` reads 0.19 to its right, so the band stops short of it.
CLAIM_ALL_REGION = (0.12, 0.86, 0.28, 0.95)
# Claim All's face between its icon and its caption: orange while there is mail to claim, a flat grey (195, 195, 195) once
# there is none. A press on the grey button opens nothing and only shows `All items in the mail have been received.`,
# centred at (0.500, 0.275).
CLAIM_ALL_FACE = (0.085, 0.880, 0.150, 0.925)
GREYED_LOW = np.array((0, 0, 150))
GREYED_HIGH = np.array((180, 30, 230))
GREYED_SHARE = 0.9
MAIL_EMPTY = ("All items in the mail have been received", (0.30, 0.22, 0.70, 0.33))
# Items Obtained's title at (0.502, 0.377) and its close caption at (0.501, 0.935), above the `进入` at (0.500, 0.978).
ITEMS_TITLE = ("Items Obtained", (0.40, 0.33, 0.60, 0.42))
ITEMS_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.965))
# The tutorial's Skip Tutorial pill, read at (0.879, 0.055) wherever it shows. Its outline spans x 0.818-0.992 and
# y 0.020-0.091, over the Lobby's Menu, the banner's X and the menu's X, and a tap on it skips the tutorial.
SKIP_TUTORIAL = ("Skip Tutorial", (0.0, 0.0, 1.0, 1.0))

# The entry banner shows no stable text, so it is told by its X with the three dots beside it, cut from a 1080p capture.
# The X scored 1.00 on the banner it was cut from; the plain X of a node or mission detail, at the same place, at most 0.835
# over 439 captures, and the Lobby and the open menu 0.21 at most.
BANNER_CLOSE_IMAGE = Path(__file__).with_name("images") / "lobby_banner_close.png"

# The Event list: its title at (0.109, 0.048) and the column heading at (0.091, 0.138). It opens on its first event, not
# the last one viewed. Dream Park's page: its title at (0.814, 0.167), Enter Amusement Park at (0.775, 0.901) and
# Achievements at (0.551, 0.900); the `New Event! [Rules of Good Order]` banner at (0.803, 0.803) is never pressed.
EVENT_TITLE = ("Event", (0.06, 0.02, 0.16, 0.08))
EVENT_HEADING = ("Recommended Events", (0.0, 0.10, 0.20, 0.17))
PARK_TITLE = ("Nightmare Dream Park", (0.70, 0.13, 0.93, 0.20))
PARK_ENTER = ("Enter Amusement Park", (0.68, 0.87, 0.87, 0.93))
PARK_ACHIEVEMENTS_BUTTON = ("Achievements", (0.48, 0.87, 0.62, 0.93))
# The park's left column, Manage at (0.087, 0.294) and Operate at (0.087, 0.473), drawn on the park view and beside each panel.
PARK_MANAGE_TAB = ("Manage", (0.03, 0.26, 0.14, 0.32))
PARK_OPERATE_TAB = ("Operate", (0.03, 0.44, 0.14, 0.50))
# The Manage panel: Visitor Emotions at (0.705, 0.633), Amusement Park Rank at (0.804, 0.906), and its title naming the
# Rank, `The Amusement Park All the Buzz Is About Rank 5` at (0.804, 0.313).
MANAGE_EMOTIONS = ("Visitor Emotions", (0.62, 0.60, 0.80, 0.66))
MANAGE_RANK = ("Amusement Park Rank", (0.72, 0.88, 0.89, 0.93))
MANAGE_TITLE_REGION = (0.65, 0.29, 0.97, 0.34)
RANK_NUMBER = re.compile(r"rank\s*(\d+)\s*$", re.I)
# The Facilities list: its title at (0.803, 0.274) and the hint under it at (0.802, 0.930).
FACILITIES_TITLE = ("Facilities", (0.75, 0.25, 0.86, 0.30))
FACILITIES_HINT = ("Press and hold", (0.70, 0.90, 0.90, 0.96))
# The Amusement Park Rank screen's title at (0.501, 0.137), and the result over it: `Rank 6 Achieved` at (0.500, 0.521)
# with its close caption at (0.500, 0.938).
RANK_TITLE = ("Amusement Park Rank", (0.40, 0.10, 0.60, 0.17))
RANK_ACHIEVED = re.compile(r"rank\s*\d+\s*achieved", re.I)
RANK_ACHIEVED_REGION = (0.35, 0.47, 0.65, 0.57)
RANK_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.97))
# The event's achievements: `Event Special Rewards` at (0.184, 0.045); its second tab lists the ride-level rewards as
# `Reach [Merry-Go-Round] Level 50`.
ACHIEVEMENTS_TITLE = ("Event Special Rewards", (0.08, 0.0, 0.30, 0.09))
# The dialog a tap on the park's Rules of Good Order raises, a timed game Daily never plays: its line at (0.502, 0.423)
# and its 取消 at (0.347, 0.631), with 确认 at (0.667, 0.631).
RULES_LINE = ("This event takes place after reaching the highest Rank", (0.25, 0.38, 0.75, 0.48))
RULES_BUTTONS = (("取消", (0.28, 0.60, 0.42, 0.66)), ("Cancel", (0.28, 0.60, 0.42, 0.66)))
BANNER_CORNER = (0.90, 0.0, 1.0, 0.12)
BANNER_MATCH = 0.92

# How long the screen may stay one Daily does not know before it stops, and how long a Lobby read stays good for a
# Lobby whose UI has faded out after a few idle seconds, which OCR reads as nothing but the odd low-confidence scrap:
# `rort` at 0.585 off the art on one capture, against 0.8 and up for every caption Daily reads.
UNKNOWN_SECONDS = 30
FADED_SECONDS = 20
FADED_CONFIDENCE = 0.7
# The faded Lobby without a Lobby read, as at a start on an idle Lobby, is told by its scene: the ring's left arm, cut
# from a 1080p capture, which the Lobby's level and name cover while its UI shows. It scored 0.94 to 0.96 on four
# other faded Lobby captures, the character standing or gone, and 0.46 at most over 651 other captures, black, loading,
# cut-scenes and the Lobby with its UI among them. The wake taps open sky, which brings the UI back.
FADED_SCENE_IMAGE = Path(__file__).with_name("images") / "lobby_faded_scene.png"
FADED_SCENE_REGION = (0.0, 0.02, 0.23, 0.28)
FADED_SCENE_MATCH = 0.8
# How long the UI gets to come back after the wake tap before it is tapped again.
WAKE_WAIT = 3
# How long Claim All gets to open Items Obtained before it is pressed again, or taken as having had nothing to claim.
CLAIM_WAIT = 5
# The run's chores before the park, then the park visit, each get their own time.
RUN_SECONDS = 600
PARK_SECONDS = 600
# How long a park screen gets to change after a press before the same target is pressed again: a second Operate or
# Manage on the open panel would close it. How long a screen gets to draw before what it lacks counts, how long a ride's
# level gets to rise after its press, and how long Rank Up gets to show its result.
NAV_WAIT = 3
SETTLE = 2
UPGRADE_WAIT = 2
RANK_WAIT = 5

# Parked on the task for one run: dropped by `disable`, so every start begins afresh.
RUN = "_en_daily_run"

PENDING, DONE = "pending", "done"
Step = namedtuple("Step", "name lobby_entry menu_entry")
# One entry per chore, in the order they run. Each starts from the Lobby with its entry tap and ends back on the Lobby.
STEPS = (Step("mail", MENU, ENVELOPE), Step("dream_park", MENU, EVENT))
PARK = "dream_park"
# Where the park visit stands: reading the Manage panel, upgrading in Facilities, or on its way out to the achievements.
TO_MANAGE, TO_OPERATE, TO_LEAVE = "manage", "operate", "leave"
# The targets that lead into each park screen, which count afresh once it shows. None is pressed on the screen it leads to.
ARRIVALS = {
    "event list": (MENU, EVENT),
    "event page": (MENU, EVENT, DREAM_PARK, PARK_LEAVE, ACHIEVEMENTS_LEAVE),
    "park": (ENTER_PARK, PANEL_CLOSE),
    "manage": (PARK_MANAGE, RANK_CLOSE),
    "facilities": (PARK_OPERATE,),
    "rank": (PARK_RANK, RANK_RESULT_CLOSE),
    "rank result": (RANK_UP,),
    "achievements": (PARK_ACHIEVEMENTS, ITEMS_CLOSE),
}
# A press on a point the OCR read nothing at, shaped as a box for `press`.
Spot = namedtuple("Spot", "name x y width height")

_patched = False


def run_state(task):
    """Give the run's state, starting it on first use.

    Args:
        task: The Daily task.

    Returns:
        A dict: each step's state, the presses per target, when the run started, when the Lobby was last read, when an
        unknown screen and the Mail screen were first seen, when Claim All and the wake were last pressed, what the
        mail step found, and the park visit's own state.
    """
    state = vars(task).get(RUN)
    if state is None:
        state = {"steps": {step.name: PENDING for step in STEPS}, "taps": Counter(), "started": time.monotonic(),
                 "lobby_seen": None, "unknown_since": None, "mail_seen": None, "claim_pressed": None, "woken": None, "mail": None,
                 "park": new_park()}
        setattr(task, RUN, state)
    return state


def new_park():
    """Start the park visit's state.

    Returns:
        A dict: when the visit started, where it stands, the screen it is on and since when, when each target was last
        pressed, the last emotions read off the Manage panel and how many upgrades had been pressed then, what one
        offline stretch earns, the Rank target whose Rank Up was found grey or could not be checked, the target the
        Operate header sent the visit to the Manage panel for and every one it has sent it there for, when Rank Up was
        pressed, the press whose level rise is awaited and what it was, presses without a rise per ride, whether the
        park and its achievements were visited, when a claim ring was pressed and how many claims in a row opened
        nothing, the counts for the finish line and why the upgrades ended.
    """
    return {"started": None, "phase": TO_MANAGE, "screen": None, "screen_since": None, "pressed": {}, "emotions": None, "emotions_at": 0,
            "stretch": None, "rank_checked": None, "rank_wanted": None, "rank_sent": set(), "rank_pressed": None, "pending": None, "no_rise": Counter(),
            "visited": False, "claims_done": False, "tab_pressed": False, "claim_pressed": None, "claim_misses": 0, "ranks": [], "rank_ups": 0,
            "upgrades": 0, "builds": [], "claims": 0, "note": None, "result": None}


def pending_step(task):
    """Find the first chore not yet done.

    Args:
        task: The Daily task.

    Returns:
        The step, or None when every chore is done.
    """
    steps = run_state(task)["steps"]
    return next((step for step in STEPS if steps[step.name] == PENDING), None)


def stop(task, message):
    """Announce why Daily stops and stop it, pressing nothing more.

    Args:
        task: The Daily task.
        message: The line to show.

    Returns:
        True, which claims the frame.
    """
    announce(task, message)
    task.disable()
    return True


def recognised(task):
    """Note that Daily knows this screen, which restarts the unknown-screen clock.

    Args:
        task: The Daily task.
    """
    run_state(task)["unknown_since"] = None


def refused(text):
    """Say whether a box reads as something Daily must never press.

    Args:
        text: The box's text.

    Returns:
        What gave it away, or None.
    """
    texts = [folded(text)]
    for group in REFUSED_GROUPS:
        marker = marker_in(texts, group)
        if marker:
            return marker
    if any(word in texts[0] for word in SHOP):
        return text
    if any(phrase.search(text.casefold()) for phrase in RESCUE_PHRASES) or cleaned(text) in RESCUE_HEADER:
        return text
    return None


def boxes_at(task, point):
    """Find the OCR boxes a tap at a point would land on.

    Args:
        task: The Daily task.
        point: `(x, y)` screen fractions.

    Returns:
        The boxes containing the point.
    """
    x, y = point[0] * task.width, point[1] * task.height
    return [box for box in getattr(task, "all_texts", None) or [] if box.x <= x <= box.x + box.width and box.y <= y <= box.y + box.height]


def press(task, target, box=None):
    """Press one of Daily's targets, unless its limit is reached or what lies under it must never be pressed.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box for a text button, None for a fixed point.

    Returns:
        True, which claims the frame: the target was pressed, or Daily has stopped.
    """
    taps = run_state(task)["taps"]
    if taps[target] >= TAP_LIMITS[target]:
        return stop(task, f"Stopped: {target} was pressed {taps[target]} times and the screen did not move on. Check the game, then press Start again.")
    point = centre_of(box, task.width, task.height) if box is not None else TARGETS[target]
    under = [box] if box is not None else []
    for hit in under + boxes_at(task, point):
        marker = refused(hit.name)
        if marker:
            task.log_info(f"not pressing {target}: the box there reads {hit.name!r} ({marker!r})")
            return stop(task, f"Stopped: {target} would have pressed {hit.name!r}. Check the game, then press Start again.")
    taps[target] += 1
    task.log_info(f"pressing {target}")
    tap(task, point)
    return True


def showing(task, caption):
    """Find a caption in its region.

    Args:
        task: The Daily task.
        caption: A `(text, region)` pair from the constants above.

    Returns:
        The box, or None.
    """
    return text_in_region(task, *caption)


def on_lobby(task):
    """Say whether the screen is the Lobby with its menu closed."""
    return showing(task, LOBBY_STORY) is not None and showing(task, LOBBY_COMBATANTS) is not None


def on_menu(task):
    """Say whether the Lobby's menu is open."""
    return showing(task, MENU_ACHIEVEMENT) is not None and showing(task, MENU_SUPPLY) is not None


def on_notice(task):
    """Say whether the Notice board is open."""
    return showing(task, NOTICE_TAB) is not None and showing(task, UPDATE_TAB) is not None


def on_mail(task):
    """Say whether the Mail screen is open."""
    if showing(task, MAIL_TITLE) is None:
        return False
    return any(MAIL_COUNT.fullmatch(folded(box.name)) and in_region(box, MAIL_COUNT_REGION, task.width, task.height)
               for box in getattr(task, "all_texts", None) or [])


def claim_all_button(task):
    """Find Claim All on the Mail screen.

    OCR has read it as `Claim AIl` and `Claim AlI`, so capital I and small l count as one letter.

    Args:
        task: The Daily task.

    Returns:
        The box, or None.
    """
    wanted = folded(CLAIM_ALL).replace("i", "l")
    for box in getattr(task, "all_texts", None) or []:
        if folded(box.name).replace("i", "l") == wanted and in_region(box, CLAIM_ALL_REGION, task.width, task.height):
            return box
    return None


def claim_all_greyed(task):
    """Say whether Claim All is drawn greyed out, with nothing left to claim.

    Args:
        task: The Daily task.

    Returns:
        True when its face is grey. False when it is orange, or there is no frame to read.
    """
    return colour_share(patch_of(frame_of(task), CLAIM_ALL_FACE), GREYED_LOW, GREYED_HIGH) >= GREYED_SHARE


def reads_nothing(task):
    """Say whether OCR read no confident text, as on a Lobby whose UI has faded out."""
    return not any(box.name.strip() and getattr(box, "confidence", 1.0) >= FADED_CONFIDENCE for box in getattr(task, "all_texts", None) or [])


def handle_daily_tutorial(task):
    """Stop while the tutorial's Skip Tutorial pill shows, ahead of every handler that presses.

    OCR read the pill, white on black, on every capture that shows it, so this is Daily's own stop for it. A frame where
    OCR misses the pill falls to the handlers below, and a press of the Lobby's Menu, the banner's X or the menu's X
    there is left to the guard in `skip_tutorial`, which refuses any tap on the pill in every mode.
    """
    if showing(task, SKIP_TUTORIAL) is None:
        return False
    return stop(task, "Stopped: the tutorial is running (Skip Tutorial shows), and Daily never skips it. Finish the tutorial, then press Start again.")


def handle_daily_overtime(task):
    """Stop a run that has gone on far longer than its chores take, the park visit timed on its own from when it starts."""
    state = run_state(task)
    park = state["park"]
    now = time.monotonic()
    if park["started"] is None and park_active(task):
        park["started"] = now
    if park["started"] is None:
        if now - state["started"] < RUN_SECONDS:
            return False
        return stop(task, f"Stopped: Daily ran for {RUN_SECONDS // 60} minutes without finishing. Check the game, then press Start again.")
    if now - park["started"] < PARK_SECONDS:
        return False
    return stop(task, f"Stopped: the Dream Park visit ran for {PARK_SECONDS // 60} minutes without finishing. Check the game, then press Start again.")


def handle_daily_items_obtained(task):
    """Close Items Obtained, and count the mail as claimed when Claim All opened it, or the achievement whose ring was pressed."""
    if showing(task, ITEMS_TITLE) is None:
        return False
    caption = showing(task, ITEMS_CAPTION)
    if caption is None:
        return False
    recognised(task)
    state = run_state(task)
    if state["claim_pressed"] is not None and state["steps"]["mail"] == PENDING:
        state["steps"]["mail"], state["mail"] = DONE, "claimed"
    park = state["park"]
    if park["claim_pressed"] is not None:
        park["claim_pressed"], park["claim_misses"] = None, 0
        park["claims"] += 1
    return press(task, ITEMS_CLOSE, caption)


def nothing_to_claim(task, reason):
    """Count the mail as done with nothing claimed, and close the Mail popup.

    Args:
        task: The Daily task.
        reason: Why, for the log.

    Returns:
        True, which claims the frame.
    """
    task.log_info(f"{reason}, so there is no mail to claim")
    state = run_state(task)
    state["steps"]["mail"], state["mail"] = DONE, "nothing to claim"
    return press(task, MAIL_CLOSE)


def handle_daily_mail(task):
    """Press Claim All while the mail is pending, wait for Items Obtained, and close the popup once it is done.

    A greyed Claim All is waited on like a missing one, since the popup may still be drawing, then taken as an empty mailbox.
    """
    if not on_mail(task):
        return False
    recognised(task)
    state = run_state(task)
    now = time.monotonic()
    for target in TOWARD_MAIL:
        state["taps"][target] = 0
    if state["mail_seen"] is None:
        state["mail_seen"] = now
    if state["steps"]["mail"] != PENDING:
        return press(task, MAIL_CLOSE)
    if showing(task, MAIL_EMPTY) is not None:
        return nothing_to_claim(task, "the game says every mail has been received")
    pressed = state["claim_pressed"]
    if pressed is not None and now - pressed < CLAIM_WAIT:
        return True
    if state["taps"][CLAIM_ALL] >= TAP_LIMITS[CLAIM_ALL]:
        return nothing_to_claim(task, "Claim All opened nothing")
    button = claim_all_button(task)
    greyed = button is not None and claim_all_greyed(task)
    if (button is None or greyed) and now - state["mail_seen"] < CLAIM_WAIT:
        return True
    if greyed:
        return nothing_to_claim(task, "Claim All is greyed out")
    if button is None:
        return nothing_to_claim(task, "no Claim All on the Mail screen")
    state["claim_pressed"] = now
    return press(task, CLAIM_ALL, button)


def park_active(task):
    """Say whether the park visit is the chore under way."""
    step = pending_step(task)
    return step is not None and step.name == PARK


def park_state(task):
    """Give the park visit's state."""
    return run_state(task)["park"]


def arrive(task, screen):
    """Note that a park screen shows: restart the unknown-screen clock and count afresh the targets that lead to it.

    Args:
        task: The Daily task.
        screen: A key of `ARRIVALS`.

    Returns:
        How long, in seconds, this screen has shown without another park screen in between.
    """
    recognised(task)
    taps = run_state(task)["taps"]
    for target in ARRIVALS.get(screen, ()):
        taps[target] = 0
    park = park_state(task)
    now = time.monotonic()
    if park["screen"] != screen:
        park["screen"], park["screen_since"] = screen, now
    return now - park["screen_since"]


def press_once(task, target, box=None):
    """Press a park target, unless it was pressed moments ago and its screen may still be changing.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box for a text button, None for a fixed point.

    Returns:
        True, which claims the frame.
    """
    pressed = park_state(task)["pressed"]
    now = time.monotonic()
    if target in pressed and now - pressed[target] < NAV_WAIT:
        return True
    pressed[target] = now
    return press(task, target, box)


def end_park(task, result=None):
    """Count the park visit as done, with why it ended early when it did.

    Args:
        task: The Daily task.
        result: The finish line's words for a visit that never reached the park, or None.
    """
    state = run_state(task)
    state["steps"][PARK] = DONE
    if result is not None:
        state["park"]["result"] = result


def park_summary(park):
    """Say in a few words what the park visit did, for the finish line.

    Args:
        park: The park visit's state.

    Returns:
        The words.
    """
    if park["result"] is not None:
        return park["result"]
    parts = [f"{park['upgrades']} upgrade{'s' if park['upgrades'] != 1 else ''}"]
    if park["rank_ups"]:
        parts.append(f"ranked up to Rank {park['ranks'][-1]}" if park["ranks"] else f"ranked up {park['rank_ups']} time(s)")
    if park["builds"]:
        parts.append(f"built {', '.join(park['builds'])}")
    parts.append(f"{park['claims']} achievement claim{'s' if park['claims'] != 1 else ''}")
    summary = "Dream Park: " + ", ".join(parts)
    return summary + (f" (upgrades ended: {park['note']})" if park["note"] else "")


def handle_daily_rules_dialog(task):
    """Decline the Rules of Good Order, a timed game Daily never plays, with its 取消 and never its 确认."""
    if showing(task, RULES_LINE) is None:
        return False
    button = next((box for box in (showing(task, caption) for caption in RULES_BUTTONS) if box is not None), None)
    if button is None:
        return False
    recognised(task)
    return press_once(task, RULES_CANCEL, button)


def handle_daily_rank_result(task):
    """Close the Rank result, counting the rank up."""
    if not any(RANK_ACHIEVED.search(box.name) and in_region(box, RANK_ACHIEVED_REGION, task.width, task.height)
               for box in getattr(task, "all_texts", None) or []):
        return False
    caption = showing(task, RANK_CAPTION)
    if caption is None:
        return False
    arrive(task, "rank result")
    park = park_state(task)
    if park["rank_pressed"] is not None:
        park["rank_ups"] += 1
        park["rank_pressed"] = None
    return press_once(task, RANK_RESULT_CLOSE, caption)


def handle_daily_rank_screen(task):
    """Press Rank Up only on the blue pill of an earned Rank, else close the screen.

    The caption is drawn on the next Rank's card whether or not it is earned, and stays on the next, grey card after a rank
    up, so the caption alone would press it again and again.
    """
    if showing(task, RANK_TITLE) is None:
        return False
    arrive(task, "rank")
    park = park_state(task)
    now = time.monotonic()
    pressed = park["rank_pressed"]
    if pressed is not None and now - pressed < RANK_WAIT:
        return True
    button = dream_park.rank_up_button(task)
    if park_active(task) and button is not None and dream_park.rank_up_live(frame_of(task), button, task.width, task.height):
        park["rank_pressed"] = now
        return press(task, RANK_UP, button)
    if park["emotions"] is not None:
        park["rank_checked"] = park["emotions"][1]
    return press_once(task, RANK_CLOSE)


def handle_daily_manage_panel(task):
    """Read the emotions, the profit rate and the idle time, then open the Rank when every emotion has reached its target."""
    if showing(task, MANAGE_EMOTIONS) is None or showing(task, MANAGE_RANK) is None:
        return False
    shown_for = arrive(task, "manage")
    park = park_state(task)
    if not park_active(task) or park["phase"] == TO_LEAVE:
        return press_once(task, PANEL_CLOSE)
    emotions = dream_park.manage_emotions(task)
    if emotions is None and shown_for < SETTLE:
        return True
    rank = next((RANK_NUMBER.search(box.name) for box in getattr(task, "all_texts", None) or []
                 if in_region(box, MANAGE_TITLE_REGION, task.width, task.height) and RANK_NUMBER.search(box.name)), None)
    if rank is not None and (not park["ranks"] or park["ranks"][-1] != int(rank.group(1))):
        park["ranks"].append(int(rank.group(1)))
    stretch = dream_park.offline_stretch(task)
    if stretch is not None:
        park["stretch"] = stretch
    wanted, park["rank_wanted"] = park["rank_wanted"], None
    if emotions is not None:
        park["emotions"], park["emotions_at"] = emotions, park["upgrades"]
        values, target = emotions
        if all(value >= target for value in values) and park["rank_checked"] != target:
            return press_once(task, PARK_RANK)
    elif wanted is not None:
        # The header said every emotion reached this target, but the panel does not read them, so Rank Up cannot be
        # checked. Counting the target as tried stops Facilities sending the visit straight back here.
        park["rank_checked"] = wanted
    park["phase"] = TO_OPERATE
    return press_once(task, PARK_OPERATE)


def ride_risen(task, rows):
    """Check the last upgrade or build took, once its level has had time to rise.

    Args:
        task: The Daily task.
        rows: The Facilities rows now in view.

    Returns:
        None to go on, True to wait for the level, or the stop's claim of the frame after two presses without a rise.
    """
    park = park_state(task)
    pending = park["pending"]
    if pending is None:
        return None
    name, level, pressed, action = pending
    ride = next((ride for ride in rows if ride.name == name), None)
    if ride is not None and ride.level > level:
        park["pending"], park["no_rise"][name] = None, 0
        if action == dream_park.BUILD:
            park["builds"].append(name)
        return None
    if time.monotonic() - pressed < UPGRADE_WAIT:
        return True
    park["pending"] = None
    park["no_rise"][name] += 1
    if park["no_rise"][name] >= 2:
        return stop(task, f"Stopped: Dream Park did not take two presses on {name} (its level did not rise). Check the game, then press Start again.")
    return None


def leave_facilities(task, note):
    """Stop upgrading for this visit and close the Facilities list."""
    park = park_state(task)
    park["phase"], park["note"], park["visited"] = TO_LEAVE, note, True
    return press_once(task, PANEL_CLOSE)


def handle_daily_facilities(task):
    """Build or upgrade one ride per pass with the park's profit, re-reading the list after every press.

    Any box reading as Crystals, a currency or a purchase in a row's price column, or anywhere on the list's right side,
    stops Daily, and a row whose price does not read is never pressed. When every emotion has reached its target and its
    Rank Up has not been tried at that target, the visit goes to the Manage panel first, at most once for each target in
    a visit, however the targets the header reads come and go.
    """
    if showing(task, FACILITIES_TITLE) is None or showing(task, FACILITIES_HINT) is None:
        return False
    shown_for = arrive(task, "facilities")
    park = park_state(task)
    if not park_active(task) or park["phase"] == TO_LEAVE:
        return press_once(task, PANEL_CLOSE)
    if park["phase"] == TO_MANAGE:
        return press_once(task, PARK_MANAGE)
    rows = dream_park.facility_rows(task)
    for ride in rows:
        hit = next((box for box in ride.price_column if refused(box.name)), None)
        if hit is not None:
            return stop(task, f"Stopped: a Dream Park price reads {hit.name!r}, and Daily spends only the park's profit. Check the game, then press Start again.")
    hit = next((box for box in dream_park.list_side(task) if refused(box.name)), None)
    if hit is not None:
        return stop(task, f"Stopped: the Dream Park list reads {hit.name!r}, and Daily spends only the park's profit. Check the game, then press Start again.")
    waiting = ride_risen(task, rows)
    if waiting is not None:
        return waiting
    emotions = dream_park.header_emotions(task)
    if emotions is None and park["emotions_at"] == park["upgrades"]:
        emotions = park["emotions"]
    if (emotions is not None and all(value >= emotions[1] for value in emotions[0]) and park["rank_checked"] != emotions[1]
            and emotions[1] not in park["rank_sent"]):
        # At most one trip for each target in a visit: when the Manage panel reads an emotion below the target the
        # header shows, or does not read at all, another trip for that target would read the same and send the visit
        # back here, round and round until the visit runs out of time, also when the header reads two targets by turns.
        park["phase"], park["rank_wanted"] = TO_MANAGE, emotions[1]
        park["rank_sent"].add(emotions[1])
        return press_once(task, PARK_MANAGE)
    if park["upgrades"] >= UPGRADE_CAP:
        return leave_facilities(task, f"the visit's {UPGRADE_CAP} upgrades are used")
    ride, reason = dream_park.choose(rows, emotions, dream_park.profit(task), park["stretch"])
    if ride is None:
        if shown_for < SETTLE:
            return True
        return leave_facilities(task, reason)
    park["pending"] = (ride.name, ride.level, time.monotonic(), ride.action)
    if ride.action == dream_park.BUILD:
        return press(task, BUILD, ride.button)
    park["upgrades"] += 1
    return press(task, UPGRADE, ride.button)


def handle_daily_park_view(task):
    """Open the panel the visit needs next from the park view, or leave the park."""
    if showing(task, PARK_MANAGE_TAB) is None or showing(task, PARK_OPERATE_TAB) is None:
        return False
    arrive(task, "park")
    park = park_state(task)
    if not park_active(task) or park["phase"] == TO_LEAVE:
        return press_once(task, PARK_LEAVE)
    return press_once(task, PARK_MANAGE if park["phase"] == TO_MANAGE else PARK_OPERATE)


def handle_daily_park_achievements(task):
    """Press every orange claim ring on both tabs of the event's achievements, then go back to the event page."""
    if showing(task, ACHIEVEMENTS_TITLE) is None:
        return False
    shown_for = arrive(task, "achievements")
    park = park_state(task)
    if not park_active(task) or park["claims_done"]:
        return press_once(task, ACHIEVEMENTS_LEAVE)
    now = time.monotonic()
    if park["claim_pressed"] is not None:
        if now - park["claim_pressed"] < CLAIM_WAIT:
            return True
        park["claim_pressed"] = None
        park["claim_misses"] += 1
        if park["claim_misses"] >= 2:
            return stop(task, "Stopped: two Dream Park achievement claims opened nothing. Check the game, then press Start again.")
    if shown_for < SETTLE or (park["tab_pressed"] and now - park["pressed"][MANAGEMENT_TAB] < NAV_WAIT):
        return True
    ready = dream_park.ready_claims(task, frame_of(task))
    if ready:
        x, y = ready[0][0] * task.width, ready[0][1] * task.height
        park["claim_pressed"] = now
        return press(task, CLAIM, Spot("claim ring", x - 1, y - 1, 2, 2))
    if not park["tab_pressed"]:
        park["tab_pressed"] = True
        return press_once(task, MANAGEMENT_TAB)
    park["claims_done"] = True
    return press_once(task, ACHIEVEMENTS_LEAVE)


def handle_daily_event_page(task):
    """Enter the park, then open its achievements, then go back to the Lobby; end the step quietly when it cannot be entered."""
    if showing(task, PARK_TITLE) is None or showing(task, EVENT_TITLE) is None:
        return False
    shown_for = arrive(task, "event page")
    park = park_state(task)
    if not park_active(task):
        return press_once(task, PAGE_LEAVE)
    enter = showing(task, PARK_ENTER)
    if enter is None:
        if shown_for < SETTLE:
            return True
        end_park(task, "Dream Park is not running")
        return press_once(task, PAGE_LEAVE)
    if not park["visited"]:
        return press_once(task, ENTER_PARK, enter)
    achievements = showing(task, PARK_ACHIEVEMENTS_BUTTON)
    if not park["claims_done"] and achievements is not None:
        return press_once(task, PARK_ACHIEVEMENTS, achievements)
    end_park(task)
    return press_once(task, PAGE_LEAVE)


def handle_daily_event_list(task):
    """Open Dream Park from the Event list, which opens on another event, or end the step quietly when it is not listed."""
    if showing(task, EVENT_TITLE) is None or showing(task, EVENT_HEADING) is None:
        return False
    shown_for = arrive(task, "event list")
    if not park_active(task):
        return press_once(task, EVENT_LEAVE)
    entry = dream_park.event_entry(task)
    if entry is not None:
        return press_once(task, DREAM_PARK, entry)
    if shown_for < SETTLE:
        return True
    end_park(task, "Dream Park is not running")
    return press_once(task, EVENT_LEAVE)


def handle_daily_notice(task):
    """Close the Notice board."""
    if not on_notice(task):
        return False
    recognised(task)
    return press(task, NOTICE_CLOSE)


def handle_daily_banner(task):
    """Close the entry banner, told by its X and dots on a screen that is none of the others Daily knows."""
    if on_lobby(task) or on_menu(task) or on_notice(task):
        return False
    if find_icon(frame_of(task), BANNER_CLOSE_IMAGE, BANNER_MATCH, BANNER_CORNER) is None:
        return False
    recognised(task)
    return press(task, BANNER_CLOSE)


def handle_daily_lobby_menu(task):
    """Open the next chore from the menu, or close the menu once no chore in it is left."""
    if not on_menu(task):
        return False
    recognised(task)
    step = pending_step(task)
    return press(task, step.menu_entry if step is not None else MENU_CLOSE)


def handle_daily_lobby(task):
    """Start the next chore from the Lobby, or finish once every chore is done."""
    if not on_lobby(task):
        return False
    recognised(task)
    state = run_state(task)
    state["lobby_seen"] = time.monotonic()
    step = pending_step(task)
    if step is not None:
        return press(task, step.lobby_entry)
    return stop(task, f"Daily finished: {'mail claimed' if state['mail'] == 'claimed' else 'no mail to claim'}; {park_summary(state['park'])}.")


def handle_daily_faded_lobby(task):
    """Bring back the UI of a Lobby that has faded out.

    Moments after a Lobby read, with a chore pending, it gets the Menu tap the Lobby would get, which brings the UI back
    or opens the menu. Without that read, as at a start on an idle Lobby, it gets the wake tap on open sky, but only on
    the faded Lobby's own scene: a screen that reads nothing could be anything else.
    """
    if not reads_nothing(task):
        return False
    state = run_state(task)
    now = time.monotonic()
    seen = state["lobby_seen"]
    step = pending_step(task)
    if seen is not None and now - seen < FADED_SECONDS and step is not None:
        recognised(task)
        return press(task, step.lobby_entry)
    if find_icon(frame_of(task), FADED_SCENE_IMAGE, FADED_SCENE_MATCH, FADED_SCENE_REGION, grey) is None:
        return False
    recognised(task)
    woken = state["woken"]
    if woken is not None and now - woken < WAKE_WAIT:
        return True
    state["woken"] = now
    return press(task, WAKE)


def handle_daily_unknown_screen(task):
    """Take every frame no handler above knows, press nothing, and stop once that has lasted `UNKNOWN_SECONDS`."""
    state = run_state(task)
    now = time.monotonic()
    if state["unknown_since"] is None:
        state["unknown_since"] = now
    if now - state["unknown_since"] < UNKNOWN_SECONDS:
        return True
    return stop(task, f"Stopped: Daily does not know this screen and pressed nothing for {UNKNOWN_SECONDS}s. Go back to the Lobby, then press Start again.")


# The run loop takes the first handler returning True. `remote` puts its handler first and `stuck_stop` its stop ahead
# of the Rescue stop. Overlays come before what they cover, the banner's weak check after every text check, and the Lobby
# last of the known screens, so a popup is never taken for a clean Lobby. The park's dialogs come before the panels under
# them, its panels before the park view drawn beside them, and Dream Park's page before the Event list it sits in. None
# of upstream's generic handlers is here: its Lobby stop would end Daily on its first frame, and its blind taps and
# centred Confirm press what Daily never reads.
PAGE_HANDLERS = [
    handle_rescue_screen,
    handle_daily_tutorial,
    handle_daily_overtime,
    handle_daily_items_obtained,
    handle_daily_mail,
    handle_daily_rules_dialog,
    handle_daily_rank_result,
    handle_daily_rank_screen,
    handle_daily_manage_panel,
    handle_daily_facilities,
    handle_daily_park_view,
    handle_daily_park_achievements,
    handle_daily_event_page,
    handle_daily_event_list,
    handle_daily_notice,
    handle_daily_banner,
    handle_daily_lobby_menu,
    handle_daily_lobby,
    handle_daily_faded_lobby,
    handle_daily_unknown_screen,
]


class DailyMode(TriggerTask):
    """Claims the day's free rewards from the Lobby, visits Dream Park, and stops on the Lobby."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Daily"
        self.description = ("Start on the Lobby. Closes the entry popups, claims all mail, then visits Nightmare Dream Park while it runs: ranks it "
                            "up, builds and upgrades rides with the park's own profit and claims its achievements. Stops on the Lobby. Presses nothing else.")
        self.trigger_interval = 1
        self.all_texts = []
        self.default_config['_enabled'] = False

    def enable(self):
        """Stop any other mode, and start the run afresh."""
        stop_others(self, OTHER_MODES)
        vars(self).pop(RUN, None)
        run_state(self)
        super().enable()

    def disable(self):
        """Stop, forgetting the run."""
        vars(self).pop(RUN, None)
        super().disable()

    def run(self):
        """Read the screen once and hand it to the first handler that knows it."""
        utils = loaded("utils")
        texts = self.ocr()
        self.all_texts = utils._simplify_texts(texts) if utils is not None else texts
        for handle_page in PAGE_HANDLERS:
            if handle_page(self):
                return


def stop_others(task, class_names):
    """Stop the named modes if they are running.

    Args:
        task: The mode about to start, for its executor.
        class_names: The class names of the modes to stop.
    """
    for name in class_names:
        other = task.executor.get_task_by_class_name(name)
        if other is not None and other is not task and other.enabled:
            other.disable()


def stopping_daily(original_enable, task):
    """Wrap another mode's `enable` so starting it stops Daily first.

    Args:
        original_enable: The mode's own `enable`.
        task: The mode being wrapped.

    Returns:
        The replacement `enable`.
    """
    def enable():
        stop_others(task, (DailyMode.__name__,))
        original_enable()

    return enable


def teaching_modes(original_load_config):
    """Wrap `BaseTask.load_config` so the other modes stop Daily when they start.

    Wrapping here puts it ahead of the run loop and the debug port, which both take their reference to `enable` later.

    Args:
        original_load_config: The unbound `load_config` being replaced.

    Returns:
        The replacement.
    """
    def load_config(self):
        if type(self).__name__ in OTHER_MODES:
            self.enable = stopping_daily(self.enable, self)
        original_load_config(self)

    return load_config


def apply():
    """Have Chaos, Sortie and Story stop Daily when they start."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, starting another mode will not stop Daily")
        _patched = True
        return
    BaseTask.load_config = teaching_modes(BaseTask.load_config)
    _patched = True
