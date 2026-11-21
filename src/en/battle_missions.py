"""Play a chapter's open Battle Missions from Story, left to right on the game's Auto, and stop at anything else.

Story already presses Enter on a mission's detail and formation and Confirm on its result, but nothing took it from
the Story hub to the list, and on the list it tapped whatever play arrow it saw first, the Promotion Mission's included.
The game moves the arrow to the next open card after a clear and scrolls it into view, so the arrow alone says which
mission is next. Each mission is started at most twice a run, so a lost fight is tried once more and never forever. A
list or a mission's detail on any tab but NORMAL, a card Story cannot name, a lock, the growth tutorial and a list with
nothing open stop the run with nothing pressed.
"""

import re
import time
from pathlib import Path

import numpy as np
from ok import Logger

from src.en.handlers import insert_before, register
from src.en.notify import announce
from src.en.screen import centre_of, frame_of, in_region, text_in_region
from src.en.story import find_icon, grey, tap

logger = Logger.get_logger(__name__)

# The Story hub: its title top left, read at (0.106, 0.048), and the Battle Missions card's caption at (0.713, 0.773).
HUB_TITLE = "故事"
HUB_TITLE_REGION = (0.0, 0.0, 0.25, 0.09)
HUB_CARD = "Battle Missions"
HUB_CARD_REGION = (0.55, 0.72, 0.95, 0.84)
# The list: its title top left, read at (0.151, 0.046), and the difficulty tab at (0.522, 0.933). A mission's detail opens
# over the list and keeps both, with its Enter read at (0.817, 0.931); Enter belongs to `handle_enter`.
LIST_TITLE = "Battle Missions"
LIST_TITLE_REGION = (0.05, 0.0, 0.30, 0.09)
LIST_TAB = "NORMAL"
LIST_TAB_REGION = (0.45, 0.90, 0.60, 0.97)
# Every tab's caption shows on every tab, so which one is selected comes from its pill: the selected pill is drawn
# lighter than its caption, the others darker. The difference survives the tutorial's dimming, where the selected pill
# is only as bright as an unselected caption. Each pill is read as `(median - 5th percentile) - (95th - median)` of its
# brightness: 47 to 160 on the selected NORMAL pill, -28 to -118 on the unselected ones, near 0 where no caption shows.
TAB_BAND = (0.915, 0.950)
TAB_PILLS = (("NORMAL", 0.44, 0.60), ("HARD", 0.64, 0.76), ("ABYSS", 0.82, 0.94))
TAB_LIT = 20
TAB_UNLIT = -10
DETAIL_ENTER = "进入"
DETAIL_ENTER_REGION = (0.60, 0.85, 1.0, 1.0)
# Where `handle_enter` presses any "进入" on Story's screens.
ENTER_REGION = (0.017, 0.771, 0.996, 0.992)
# Each tab's caption, read in its pill's span of the tab row.
TAB_CAPTIONS = tuple((name, (left, LIST_TAB_REGION[1], right, LIST_TAB_REGION[3])) for name, left, right in TAB_PILLS)
# The gold play arrow on the next open card, cut from a capture of the list, and the row of cards it sits on. It scored
# 0.999-1.000 on the open card of the two lists captured with one, and 0.84 at most on lists with no card open.
ARROW_IMAGE = Path(__file__).with_name("images") / "mission_arrow.png"
CARD_ROW = (0.0, 0.47, 1.0, 0.54)
ARROW_MATCH = 0.95
# The list's title, cut from a capture of the list. A detail's panel never covers it, and it is matched on brightness
# alone, so it holds through the tutorial's dimming: 0.99-1.00 on every list and detail captured, 0.74 on one dimmed to
# 3%, and 0.39 at most on any other capture, the Story hub's and chapter map's "故事" in the same corner included.
TITLE_IMAGE = Path(__file__).with_name("images") / "mission_title.png"
TITLE_MATCH = 0.7
# The card's label sits just left of the arrow: `B2` read at x 0.566 with the arrow at 0.578. OCR reads the arrow as a
# trailing `I` or `1` now and then, as in `B1I`.
LABEL_LEFT = 0.08
LABEL_RIGHT = 0.02
LABEL = re.compile(r"B([1-6])[|IL1!>]?")
# The popup a locked card or tab raises: `Content locked` at (0.502, 0.401) and what unlocks it below, from y 0.514.
LOCKED = "Content locked"
LOCKED_REGION = (0.2, 0.3, 0.8, 0.46)
UNLOCK_REGION = (0.05, 0.46, 0.95, 0.85)
# Where a window over the list writes its title and buttons, such as `A Promise Renewed` and `Proceed with Tutorial`.
POPUP_REGION = (0.25, 0.30, 0.75, 0.80)
# The forced growth tutorial a mission's formation raises when the team is under the recommended level.
GROWTH = "Some Combatants do not meet the"
SCREEN = (0.0, 0.0, 1.0, 1.0)
# A lost fight leaves its card open, so a second start is the one retry.
MAX_STARTS = 2
HUB_TAPS = 3
# How long one reading of the list has to hold before Story acts on it, so a list still scrolling to the next card or
# fading in is never tapped or stopped on. Readings further apart than `GAP` start over.
SETTLE = 2.0
GAP = 5.0

# Parked on Story: how often each mission was started, how often the hub was tapped since the list last showed, and the
# reading of the list waiting to settle. Any disable drops them, so every run starts afresh.
STARTS = "_en_mission_starts"
HUB_TAPPED = "_en_mission_hub_taps"
PENDING = "_en_mission_pending"
MARKS = (STARTS, HUB_TAPPED, PENDING)

GROWTH_STOP = ("Story stopped: the game wants a combatant levelled up first (Some Combatants do not meet the recommended "
               "level). Level the team up, then start Story again.")
HUB_STOP = "Story tapped Battle Missions on the Story hub {taps} times and the list did not open. Check the game, then start Story again."

_patched = False


def on_hub(task):
    """Say whether the screen is the Story hub with its Battle Missions card.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        The card's caption box, or None.
    """
    if text_in_region(task, HUB_TITLE, HUB_TITLE_REGION) is None:
        return None
    return text_in_region(task, HUB_CARD, HUB_CARD_REGION)


def on_list(task):
    """Say whether the screen is the Battle Missions list with no mission's detail open over it.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True on the bare list.
    """
    return (text_in_region(task, LIST_TITLE, LIST_TITLE_REGION) is not None
            and text_in_region(task, LIST_TAB, LIST_TAB_REGION) is not None
            and text_in_region(task, DETAIL_ENTER, DETAIL_ENTER_REGION) is None)


def selected_tab(frame):
    """Read which difficulty tab is selected on the list.

    Args:
        frame: The current capture, or None when there is none.

    Returns:
        "NORMAL", "HARD" or "ABYSS" when exactly one pill reads selected and the others unselected, else None.
    """
    if frame is None:
        return None
    height, width = frame.shape[:2]
    band = grey(frame[int(TAB_BAND[0] * height):int(TAB_BAND[1] * height)])
    lit, unlit = [], []
    for name, left, right in TAB_PILLS:
        low, mid, high = np.percentile(band[:, int(left * width):int(right * width)], (5, 50, 95))
        contrast = (mid - low) - (high - mid)
        if contrast >= TAB_LIT:
            lit.append(name)
        elif contrast <= TAB_UNLIT:
            unlit.append(name)
    return lit[0] if len(lit) == 1 and len(unlit) == len(TAB_PILLS) - 1 else None


def mission_screen(task, frame, tab):
    """Say whether the screen is the Battle Missions list or a mission's detail, on any tab and with a line OCR missed.

    The tab reading alone is no test, since lobby, Chaos and rescue screens read as HARD or ABYSS, and neither is the
    arrow, since Story's chapter map shows the same one. So it takes the list's title or a tab's caption read by OCR, the
    title's image, or the arrow on the row of cards with HARD or ABYSS read off the pills, which no other capture shows.
    The image is what holds on a HARD or ABYSS detail, whose panel covers those pills, so the tab reads as None there.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        frame: The current capture, or None when there is none.
        tab: What `selected_tab` read off the same frame.

    Returns:
        True on the list or a mission's detail.
    """
    if text_in_region(task, LIST_TITLE, LIST_TITLE_REGION) is not None:
        return True
    if any(text_in_region(task, name, region) is not None for name, region in TAB_CAPTIONS):
        return True
    if tab != LIST_TAB and find_icon(frame, TITLE_IMAGE, TITLE_MATCH, LIST_TITLE_REGION, grey) is not None:
        return True
    return tab in ("HARD", "ABYSS") and find_icon(frame, ARROW_IMAGE, ARROW_MATCH, CARD_ROW, grey) is not None


def worded(box):
    """Say whether a box holds more than the one or two characters OCR makes of an icon, such as `▲` or `D`."""
    return len(box.name.strip()) > 2


def popup_over(task):
    """Read the lines of a window covering the list, leaving out the list's own card captions and star rows.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        The lines top to bottom, joined with "; ", or an empty string when none is read.
    """
    lines = sorted((box for box in task.all_texts
                    if in_region(box, POPUP_REGION, task.width, task.height) and worded(box)
                    and any(char.isalpha() for char in box.name) and "missions" not in box.name.casefold()),
                   key=lambda box: box.y)
    return "; ".join(box.name.strip() for box in lines)


def mission_of(name):
    """Read a card label as the mission it names.

    Args:
        name: The text OCR read off the label.

    Returns:
        The mission, such as "B2", or None when the label is not B1 to B6.
    """
    match = LABEL.fullmatch(name.strip().upper().replace(" ", ""))
    return f"B{match.group(1)}" if match else None


def label_by(task, point):
    """Find the label of the card a play arrow sits on.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        point: The arrow's centre as `(x, y)` screen fractions.

    Returns:
        The nearest box just left of the arrow on the row of cards, or None when OCR read none there.
    """
    near = [box for box in task.all_texts
            if in_region(box, CARD_ROW, task.width, task.height)
            and point[0] - LABEL_LEFT <= centre_of(box, task.width, task.height)[0] <= point[0] + LABEL_RIGHT]
    return min(near, key=lambda box: abs(centre_of(box, task.width, task.height)[0] - point[0]), default=None)


def missions_read(task):
    """List the missions whose labels OCR read on the row of cards.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        The missions left to right, such as `["B3", "B4", "B5"]`.
    """
    cards = sorted((centre_of(box, task.width, task.height)[0], mission_of(box.name)) for box in task.all_texts
                   if in_region(box, CARD_ROW, task.width, task.height) and mission_of(box.name))
    return [mission for _, mission in cards]


def stop(task, message):
    """Announce why Story stops and stop it, with nothing pressed.

    Args:
        task: Story mode.
        message: The line to show.

    Returns:
        True, which claims the frame.
    """
    announce(task, message)
    task.disable()
    return True


def stop_off_normal(task, tab):
    """Stop Story on a list or detail whose tab does not read NORMAL, with nothing pressed.

    Args:
        task: Story mode.
        tab: The tab read, or None when none could be.

    Returns:
        True, which claims the frame.
    """
    if tab is None:
        return stop(task, "Battle Missions: Story could not tell which difficulty tab is selected, so it stopped. "
                          "Select NORMAL, then start Story again.")
    return stop(task, f"Battle Missions: the {tab} tab is selected and Story plays NORMAL only, so it stopped. "
                      "Select NORMAL, then start Story again.")


def settled(task, reading):
    """Say whether the list has read the same way for `SETTLE` seconds.

    Args:
        task: Story mode.
        reading: What the list says this pass, such as `("start", "B2")`.

    Returns:
        True once the reading has held, which also forgets it so the next action waits afresh.
    """
    now = time.monotonic()
    pending = vars(task).get(PENDING)
    if pending is None or pending[0] != reading or now - pending[2] > GAP:
        setattr(task, PENDING, (reading, now, now))
        return False
    if now - pending[1] < SETTLE:
        setattr(task, PENDING, (reading, pending[1], now))
        return False
    vars(task).pop(PENDING, None)
    return True


def handle_mission_stop(task):
    """Stop Story on a lock popup or the growth tutorial, which upstream would close or press through.

    Args:
        task: Story mode, whose `all_texts` holds the current OCR pass.

    Returns:
        True when Story has been stopped, which claims the frame.
    """
    if text_in_region(task, LOCKED, LOCKED_REGION) is not None:
        lines = sorted((box for box in task.all_texts
                        if in_region(box, UNLOCK_REGION, task.width, task.height) and worded(box)),
                       key=lambda box: box.y)
        unlock = "; ".join(box.name.strip() for box in lines) or "no unlock condition read"
        return stop(task, f"Story stopped on a locked screen: Content locked ({unlock}).")
    if text_in_region(task, GROWTH, SCREEN) is not None:
        return stop(task, GROWTH_STOP)
    return False


def handle_story_hub(task):
    """Tap the Battle Missions card on the Story hub, where Story finds nothing of its own to enter.

    Args:
        task: Story mode, whose `all_texts` holds the current OCR pass.

    Returns:
        True when the card was tapped or Story stopped, which claims the frame.
    """
    card = on_hub(task)
    if card is None:
        return False
    taps = vars(task).get(HUB_TAPPED, 0)
    if taps >= HUB_TAPS:
        return stop(task, HUB_STOP.format(taps=taps))
    setattr(task, HUB_TAPPED, taps + 1)
    task.log_info("Story hub, opening Battle Missions")
    tap(task, centre_of(card, task.width, task.height))
    return True


def handle_mission_list(task):
    """Start the open Battle Mission on the list, or stop when none is left or the open card is not one Story plays.

    Args:
        task: Story mode, whose `all_texts` and `frame` hold the current screen.

    Returns:
        True on the list, which claims the frame whether Story tapped, waited for the list to settle or stopped.
    """
    if not on_list(task):
        return False
    vars(task).pop(HUB_TAPPED, None)
    frame = frame_of(task)
    tab = selected_tab(frame)
    point = find_icon(frame, ARROW_IMAGE, ARROW_MATCH, CARD_ROW, grey)
    label = label_by(task, point) if point is not None else None
    mission = mission_of(label.name) if label is not None else None
    starts = vars(task).get(STARTS, {}).get(mission, 0)
    # Only what decides the action, so a card label OCR reads on one pass and misses on the next cannot hold off the stop.
    if tab != LIST_TAB:
        reading = ("tab", tab)
    elif point is None:
        reading = ("none",)
    elif mission is None:
        reading = ("unknown",)
    elif starts >= MAX_STARTS:
        reading = ("retried", mission)
    else:
        reading = ("start", mission)
    if not settled(task, reading):
        return True
    if reading[0] == "tab":
        return stop_off_normal(task, tab)
    if reading[0] == "none":
        cards = ", ".join(missions_read(task))
        popup = popup_over(task) if not cards else ""
        if popup:
            return stop(task, f"Battle Missions: a window covers the list ({popup}), so no card could be read. Story stopped.")
        return stop(task, f"Battle Missions: no open mission is left on the list (cards read: {cards or 'none'}). The rest "
                          "are cleared or locked. Story stopped.")
    if reading[0] == "unknown":
        name = f"reads '{label.name.strip()}'" if label is not None else "has no label Story could read"
        return stop(task, f"Battle Missions: the next open card {name}, not B1 to B6, so it may be the Promotion Mission. "
                          "Story leaves it to you and stopped.")
    if reading[0] == "retried":
        return stop(task, f"Battle Missions: {mission} was started {starts} times this run and is still open, so the fight "
                          "was likely lost. Strengthen the team, then start Story again.")
    count = vars(task).setdefault(STARTS, {})
    count[mission] = starts + 1
    task.log_info(f"Battle Missions: starting {mission} (attempt {starts + 1} of {MAX_STARTS})")
    tap(task, point)
    return True


def held_off_normal(task):
    """Hold Story on the list or a mission's detail whose tab does not read NORMAL, and stop it once that reading holds.

    Args:
        task: Story mode, whose `all_texts` and `frame` hold the current screen.

    Returns:
        True when Story was held or stopped, which claims the frame, or False on NORMAL and on any other screen.
    """
    frame = frame_of(task)
    tab = selected_tab(frame)
    if tab == LIST_TAB:
        # A reading of another tab that did not hold, as on a screen still fading in, must not count towards a later stop.
        pending = vars(task).get(PENDING)
        if pending is not None and pending[0][0] == "tab":
            vars(task).pop(PENDING)
        return False
    if not mission_screen(task, frame, tab):
        return False
    if not settled(task, ("tab", tab)):
        return True
    return stop_off_normal(task, tab)


def handle_list_off_normal(task):
    """Keep Story's own arrow tap off the list unless its NORMAL tab is selected.

    `handle_mission_list` takes only a pass where OCR reads the list's title and NORMAL caption. Any other pass reaches
    `handle_enter_story_or_battle`, whose template matches the arrow even on a list still fading in, and it taps at once.

    Args:
        task: Story mode, whose `all_texts` and `frame` hold the current screen.

    Returns:
        True when Story was held or stopped, which claims the frame.
    """
    return held_off_normal(task)


def handle_detail_off_normal(task):
    """Keep Story's Enter off a mission's detail unless its NORMAL tab is selected, since Enter starts the mission.

    Args:
        task: Story mode, whose `all_texts` and `frame` hold the current screen.

    Returns:
        True when Story was held or stopped, which claims the frame.
    """
    if text_in_region(task, DETAIL_ENTER, ENTER_REGION) is None:
        return False
    return held_off_normal(task)


def forgetting_missions(disable):
    """Wrap `disable` so a Story stopped for any reason starts its next run with no mission counted.

    Args:
        disable: The unbound `disable` being replaced.

    Returns:
        The replacement.
    """
    def disable_forgetting_missions(self):
        for name in MARKS:
            vars(self).pop(name, None)
        return disable(self)

    return disable_forgetting_missions


def install():
    """Put the stops ahead of every Story handler that could press past them, and the hub and list ahead of Story's entrance tap."""
    # Ahead of the centred Confirm and the close-page tap, which would press a lock popup or the tutorial away.
    insert_before("handle_center_confirm", handle_mission_stop, only=("utils_story",))
    # Ahead of `handle_enter_story_or_battle`, which taps the leftmost play arrow on any screen, the Promotion card's too.
    insert_before("handle_enter_story_or_battle", handle_story_hub, only=("utils_story",))
    insert_before("handle_enter_story_or_battle", handle_mission_list, only=("utils_story",))
    # A list or detail on another tab is kept from Story's entrance tap and its Enter, either of which starts the mission.
    insert_before("handle_enter_story_or_battle", handle_list_off_normal, only=("utils_story",))
    insert_before("handle_enter", handle_detail_off_normal, only=("utils_story",))


def apply():
    """Have Story play a chapter's open Battle Missions."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, Story will not play Battle Missions")
        _patched = True
        return
    BaseTask.disable = forgetting_missions(BaseTask.disable)
    register(install)
    _patched = True
