"""Run the daily chores from the Lobby: close its entry popups, claim all mail, and stop on a clean Lobby.

The Lobby, its menu and the Mail screen sit next to buttons that delete mail, open the Shop, refill Aether with Crystals,
open Rescue or quit the game. So Daily presses only the fixed targets in `TARGETS`, each on the one screen it belongs to,
every press goes through `press`, which refuses a box that reads as any of those, and each target has a per-run limit.
A screen Daily does not know for 30 seconds stops it with nothing pressed.

Imported by ok-script before `ok_tasks/` is on `sys.path`, so upstream is reached only through `handlers.loaded`.
"""

import re
import time
from collections import Counter, namedtuple
from pathlib import Path

from ok import Logger, TriggerTask

from src.en.handlers import loaded
from src.en.notify import announce
from src.en.screen import centre_of, frame_of, in_region, text_in_region
from src.en.spend_guard import ACCOUNT, DELETION, MONEY, PURCHASE, RESCUE_HEADER, RESCUE_PHRASES, cleaned, folded, handle_rescue_screen, marker_in
from src.en.story import find_icon, tap

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
MAIL_BACK = "the Mail screen's back arrow"
TARGETS = {
    BANNER_CLOSE: (0.968, 0.049),
    NOTICE_CLOSE: (0.911, 0.120),
    MENU: (0.959, 0.046),
    ENVELOPE: (0.962, 0.280),
    MENU_CLOSE: (0.961, 0.049),
    MAIL_BACK: (0.068, 0.089),
    CLAIM_ALL: None,
    ITEMS_CLOSE: None,
}
# How often each target may be pressed in one run. Claim All gets one retry for a tap the game ignored; the rest allow two
# retries for a screen slow to change. Menu and the menu's Mail count only until the Mail screen shows, so a later step may open the menu again.
TAP_LIMITS = {BANNER_CLOSE: 3, NOTICE_CLOSE: 3, MENU: 3, ENVELOPE: 3, MENU_CLOSE: 3, MAIL_BACK: 3, CLAIM_ALL: 2, ITEMS_CLOSE: 3}
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
# The Mail screen's title at (0.107, 0.090) and its `003 / 100` count at (0.844, 0.090).
MAIL_TITLE = ("Mail", (0.06, 0.06, 0.16, 0.12))
MAIL_COUNT_REGION = (0.78, 0.06, 0.90, 0.12)
MAIL_COUNT = re.compile(r"\d{3}/100")
# Claim All, read at (0.194, 0.904). `Delete read mail` reads 0.19 to its right, so the band stops short of it.
CLAIM_ALL_REGION = (0.12, 0.86, 0.28, 0.95)
# Items Obtained's title at (0.502, 0.377) and its close caption at (0.501, 0.935), above the `进入` at (0.500, 0.978).
ITEMS_TITLE = ("Items Obtained", (0.40, 0.33, 0.60, 0.42))
ITEMS_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.965))

# The entry banner shows no stable text, so it is told by its X with the three dots beside it, cut from a 1080p capture.
# The X scored 1.00 on the banner it was cut from; the plain X of a node or mission detail, at the same place, at most 0.835
# over 439 captures, and the Lobby and the open menu 0.21 at most.
BANNER_CLOSE_IMAGE = Path(__file__).with_name("images") / "lobby_banner_close.png"
BANNER_CORNER = (0.90, 0.0, 1.0, 0.12)
BANNER_MATCH = 0.92

# How long the screen may stay one Daily does not know before it stops, and how long a Lobby read stays good for a
# Lobby whose UI has faded out after a few idle seconds, which OCR reads as nothing but the odd low-confidence scrap:
# `rort` at 0.585 off the art on one capture, against 0.8 and up for every caption Daily reads.
UNKNOWN_SECONDS = 30
FADED_SECONDS = 20
FADED_CONFIDENCE = 0.7
# How long Claim All gets to open Items Obtained before it is pressed again, or taken as having had nothing to claim.
CLAIM_WAIT = 5
RUN_SECONDS = 600

# Parked on the task for one run: dropped by `disable`, so every start begins afresh.
RUN = "_en_daily_run"

PENDING, DONE = "pending", "done"
Step = namedtuple("Step", "name lobby_entry menu_entry")
# One entry per chore, in the order they run. Each starts from the Lobby with its entry tap and ends back on the Lobby.
STEPS = (Step("mail", MENU, ENVELOPE),)

_patched = False


def run_state(task):
    """Give the run's state, starting it on first use.

    Args:
        task: The Daily task.

    Returns:
        A dict: each step's state, the presses per target, when the run started, when the Lobby was last read, when an
        unknown screen and the Mail screen were first seen, when Claim All was last pressed, and what the mail step found.
    """
    state = vars(task).get(RUN)
    if state is None:
        state = {"steps": {step.name: PENDING for step in STEPS}, "taps": Counter(), "started": time.monotonic(),
                 "lobby_seen": None, "unknown_since": None, "mail_seen": None, "claim_pressed": None, "mail": None}
        setattr(task, RUN, state)
    return state


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


def handle_daily_overtime(task):
    """Stop a run that has gone on far longer than its chores take."""
    if time.monotonic() - run_state(task)["started"] < RUN_SECONDS:
        return False
    return stop(task, f"Stopped: Daily ran for {RUN_SECONDS // 60} minutes without finishing. Check the game, then press Start again.")


def handle_daily_items_obtained(task):
    """Close Items Obtained, and count the mail as claimed when Claim All opened it."""
    if showing(task, ITEMS_TITLE) is None:
        return False
    caption = showing(task, ITEMS_CAPTION)
    if caption is None:
        return False
    recognised(task)
    state = run_state(task)
    if state["claim_pressed"] is not None and state["steps"]["mail"] == PENDING:
        state["steps"]["mail"], state["mail"] = DONE, "claimed"
    return press(task, ITEMS_CLOSE, caption)


def handle_daily_mail(task):
    """Press Claim All while the mail is pending, wait for Items Obtained, and go back once it is done."""
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
        return press(task, MAIL_BACK)
    pressed = state["claim_pressed"]
    if pressed is not None and now - pressed < CLAIM_WAIT:
        return True
    if state["taps"][CLAIM_ALL] >= TAP_LIMITS[CLAIM_ALL]:
        # Pressed and retried with no Items Obtained: the mailbox had nothing to claim.
        task.log_info("Claim All opened nothing, so there was no mail to claim")
        state["steps"]["mail"], state["mail"] = DONE, "nothing to claim"
        return press(task, MAIL_BACK)
    button = claim_all_button(task)
    if button is None and now - state["mail_seen"] < CLAIM_WAIT:
        return True
    if button is None:
        task.log_info("no Claim All on the Mail screen, so there is no mail to claim")
        state["steps"]["mail"], state["mail"] = DONE, "nothing to claim"
        return press(task, MAIL_BACK)
    state["claim_pressed"] = now
    return press(task, CLAIM_ALL, button)


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
    return stop(task, f"Daily finished: {'mail claimed' if state['mail'] == 'claimed' else 'no mail to claim'}.")


def handle_daily_faded_lobby(task):
    """Tap Menu on a Lobby whose UI has faded out, the same tap the Lobby would get, which brings the UI back or opens the menu.

    Only while a chore is pending and the Lobby was read moments ago: a screen that reads nothing could be anything else.
    """
    if any(box.name.strip() and getattr(box, "confidence", 1.0) >= FADED_CONFIDENCE for box in getattr(task, "all_texts", None) or []):
        return False
    state = run_state(task)
    seen = state["lobby_seen"]
    step = pending_step(task)
    if seen is None or time.monotonic() - seen >= FADED_SECONDS or step is None:
        return False
    recognised(task)
    return press(task, step.lobby_entry)


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
# last of the known screens, so a popup is never taken for a clean Lobby. None of upstream's generic handlers is here:
# its Lobby stop would end Daily on its first frame, and its blind taps and centred Confirm press what Daily never reads.
PAGE_HANDLERS = [
    handle_rescue_screen,
    handle_daily_overtime,
    handle_daily_items_obtained,
    handle_daily_mail,
    handle_daily_notice,
    handle_daily_banner,
    handle_daily_lobby_menu,
    handle_daily_lobby,
    handle_daily_faded_lobby,
    handle_daily_unknown_screen,
]


class DailyMode(TriggerTask):
    """Claims the day's free rewards from the Lobby and stops there."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Daily"
        self.description = "Start on the Lobby. Closes the entry popups, claims all mail and stops on the Lobby. Presses nothing else."
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
