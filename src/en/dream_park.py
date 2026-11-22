"""Read Nightmare Dream Park's screens and choose what Daily spends the park's profit on.

Nothing here presses anything: Daily's park handlers read a screen through these functions and press through Daily's
own guard. The park's profit is a free counter that refills while the player is away, and none of its prices is in
Crystals, but the Facilities rows sit beside achievement rows that pay Crystals, so a row is pressed only when its
price reads as a plain park number.

Positions are screen fractions read off the Global client's captures at 1920x1080.
"""

import re
from collections import namedtuple

import numpy as np

from src.en.screen import centre_of, colour_share, in_region, patch_of

EMOTIONS = ("Thrill", "Comfort", "Happiness")

# A park number: `871`, `6.81K`, `385.00K`, and `1.23M` once profit passes a million, a form taken on trust rather than
# read off a capture.
NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*([KM]?)")
SCALE = {"": 1, "K": 1_000, "M": 1_000_000}

# The park view's profit counter, read at (0.956, 0.047). The floating `+180` ticks rise below it, from y 0.12.
PROFIT_REGION = (0.90, 0.0, 1.0, 0.08)

# The Operate header: current/target for Thrill, Comfort and Happiness at y 0.105, x 0.70, 0.80 and 0.93. OCR reads a
# slash as `1` now and then and runs the three together, as `26129` for 26/29 and `61/3629 /36` for 61/36 and 29/36.
# The profit ticks, `+201` at y 0.122, float up through its right end.
HEADER_REGION = (0.64, 0.085, 1.0, 0.118)

# The Manage panel's rows: each emotion's name at x 0.71 and its own current/target box at x 0.94, y 0.675 to 0.81.
MANAGE_LABEL_REGION = (0.66, 0.65, 0.78, 0.84)
MANAGE_VALUE_X = 0.85
PROFIT_STATUS = ("Profit Status", re.compile(r"(\d[\d,]*(?:\.\d+)?[KM]?)\s*/\s*s", re.I))
IDLE_TIME = "Max Idle Time"
HOURS = re.compile(r"(\d+)\s*h", re.I)
MINUTES = re.compile(r"(\d+)\s*m", re.I)
# How far down the value of a Manage row may sit from its label.
SAME_LINE = 0.02

# The Facilities list, between its title at y 0.274 and the hold hint at y 0.930. A ride's name starts with the list's
# bullet, which OCR reads as `o`, `O` or `0`; its level sits on the same line at x 0.93; its emotion line about 0.05
# lower; its button about 0.105 lower, `强化` (Upgrade, as `ocr.po` maps it) or `Build`, with the price at x 0.95.
LIST_TOP, LIST_BOTTOM = 0.30, 0.92
NAME_X = (0.72, 0.84)
NAME = re.compile(r"[oO0•·]\s*([A-Za-z].*)")
LEVEL = re.compile(r"lv\.?\s*(\d+)\s*/\s*(\d+)", re.I)
LEVEL_X = 0.88
EMOTION_LINE = re.compile(r"(thrill?|comfort|happiness)\s*\+\s*(\d+)", re.I)
EMOTION_BELOW = (0.03, 0.075)
BUTTON_X = (0.72, 0.84)
BUTTON_BELOW = (0.08, 0.13)
UPGRADE_CAPTIONS = ("强化", "upgrade")
BUILD_CAPTIONS = ("build",)
PRICE_X = 0.88
# Where the list's side of the screen starts, a little left of every name and button caption.
LIST_SIDE_X = 0.70
MAX_LEVEL = 50

UPGRADE, BUILD = "upgrade", "build"
# `price_column` holds every box right of `PRICE_X` from the name line to the button line, each checked before a press.
Ride = namedtuple("Ride", "name level emotion action button price price_box price_column", defaults=((),))

# `Rank Up` is drawn on the next Rank's card whether or not it is earned: a saturated blue pill (BGR 247, 136, 50) when it
# is, a grey lavender one (217, 184, 175) when not, and it stays on the next, grey card after a rank up. The band takes
# the blue only: 0.92 of the patch on three captures of the live button, 0 on two grey ones and 0.17 on the card beside it.
RANK_UP_BAND = (0.86, 0.94)
RANK_UP_HALF = (0.06, 0.025)
LIVE_LOW = np.array((95, 120, 150))
LIVE_HIGH = np.array((125, 255, 255))
LIVE_SHARE = 0.6

# An achievement row's claim control sits at x 0.722, 0.036 above the row's `n/m` progress at x 0.22: an orange ring
# with a down arrow when the reward is ready (0.15 of the patch), a grey waveform otherwise and a check once claimed (0).
PROGRESS = re.compile(r"\d+\s*/\s*\d+")
PROGRESS_X = (0.18, 0.27)
CLAIM_X = 0.722
CLAIM_ABOVE = 0.036
CLAIM_HALF = (0.02, 0.03)
READY_LOW = np.array((5, 120, 150))
READY_HIGH = np.array((25, 255, 255))
READY_SHARE = 0.06

# The Event list's entries are cut at the left, `htmare Dream Park`, and their order can change.
EVENT_ENTRY = "dreampark"
EVENT_LIST_REGION = (0.0, 0.18, 0.22, 1.0)


def parse_number(text):
    """Read a park number, as the profit counter and the Facilities prices print it.

    Args:
        text: The box's text.

    Returns:
        The value, or None when the text is anything but a plain number with an optional K or M.
    """
    match = NUMBER.fullmatch(text.replace(",", "").strip())
    if match is None:
        return None
    return float(match.group(1)) * SCALE[match.group(2)]


def boxes_of(task):
    """Give the boxes OCR read this pass, as `(box, centre_x, centre_y)` with the centre in screen fractions."""
    return [(box, *centre_of(box, task.width, task.height)) for box in getattr(task, "all_texts", None) or []]


def profit(task):
    """Read the park's profit counter.

    Args:
        task: The Daily task.

    Returns:
        The profit, or None when the counter does not read as a number.
    """
    for box in getattr(task, "all_texts", None) or []:
        if in_region(box, PROFIT_REGION, task.width, task.height):
            value = parse_number(box.name)
            if value is not None:
                return value
    return None


def split_header(text):
    """Split the Operate header's run-together digits into three values and their shared target.

    All three emotions share one target per Rank. Each value is the digits before a separator, a slash or a `1` OCR
    read for one, followed by the target. The target is one of the digit runs after a slash, cut short where the next
    value runs on from it, so every such start is tried.

    Args:
        text: The header's boxes joined left to right, spaces removed.

    Returns:
        `((thrill, comfort, happiness), target)`, or None when the text splits in no way or more than one.
    """
    targets = {run[:length] for run in re.findall(r"/(\d+)", text) for length in range(1, min(len(run), 3) + 1)}
    found = set()

    def split(rest, values, target):
        if len(values) == 3:
            if not rest:
                found.add((tuple(values), int(target)))
            return
        for end in range(1, min(len(rest), 3) + 1):
            head = rest[:end]
            if not head.isdigit() or rest[end:end + 1] not in ("/", "1"):
                continue
            tail = rest[end + 1:]
            if tail.startswith(target):
                split(tail[len(target):], values + [int(head)], target)

    for target in targets:
        split(text, [], target)
    if len(found) != 1:
        return None
    return found.pop()


def header_emotions(task):
    """Read Thrill, Comfort and Happiness off the Operate header.

    Args:
        task: The Daily task.

    Returns:
        `((thrill, comfort, happiness), target)`, or None when the header does not read cleanly.
    """
    boxes = sorted((box for box, x, y in boxes_of(task) if in_region(box, HEADER_REGION, task.width, task.height) and not box.name.strip().startswith("+")),
                   key=lambda box: box.x)
    text = "".join(re.sub(r"[^\d/]", "", box.name) for box in boxes)
    return split_header(text)


def manage_emotions(task):
    """Read Thrill, Comfort and Happiness off the Manage panel, where each has its own box.

    Args:
        task: The Daily task.

    Returns:
        `((thrill, comfort, happiness), target)`, or None when a value is missing, garbled or the targets differ.
    """
    boxes = boxes_of(task)
    values, targets = [], set()
    for emotion in EMOTIONS:
        label = next(((x, y) for box, x, y in boxes if box.name.strip().casefold().startswith(emotion[:5].casefold())
                      and in_region(box, MANAGE_LABEL_REGION, task.width, task.height)), None)
        if label is None:
            return None
        value = next((re.fullmatch(r"(\d+)\s*/\s*(\d+)", box.name.strip()) for box, x, y in boxes
                      if x >= MANAGE_VALUE_X and abs(y - label[1]) <= SAME_LINE and re.fullmatch(r"(\d+)\s*/\s*(\d+)", box.name.strip())), None)
        if value is None:
            return None
        values.append(int(value.group(1)))
        targets.add(int(value.group(2)))
    if len(targets) != 1:
        return None
    return tuple(values), targets.pop()


def value_beside(task, label):
    """Find the box on the same line as a Manage panel label, to the right of it.

    Args:
        task: The Daily task.
        label: The label's text.

    Returns:
        The value's text, or None.
    """
    boxes = boxes_of(task)
    wanted = label.casefold().replace(" ", "")
    line = next((y for box, x, y in boxes if wanted in box.name.casefold().replace(" ", "") and x < MANAGE_VALUE_X), None)
    if line is None:
        return None
    return next((box.name.strip() for box, x, y in boxes if x >= MANAGE_VALUE_X and abs(y - line) <= SAME_LINE), None)


def offline_stretch(task):
    """Work out what one full offline stretch earns: the Manage panel's Profit Status times its Max Idle Time.

    Args:
        task: The Daily task.

    Returns:
        The profit, or None when either does not read.
    """
    rate_text, idle_text = value_beside(task, PROFIT_STATUS[0]), value_beside(task, IDLE_TIME)
    if rate_text is None or idle_text is None:
        return None
    rate = PROFIT_STATUS[1].fullmatch(rate_text)
    rate = parse_number(rate.group(1)) if rate else None
    hours, minutes = HOURS.search(idle_text), MINUTES.search(idle_text)
    if rate is None or (hours is None and minutes is None):
        return None
    seconds = 3600 * int(hours.group(1) if hours else 0) + 60 * int(minutes.group(1) if minutes else 0)
    return rate * seconds


def facility_rows(task):
    """Read the Facilities rows whose button shows.

    A row is found by its name. A button with no name above it, cut off at the top of the list, is no row; a locked
    ride shows `Reach Amusement Park Rank N` where its button would be, and a ride whose button is cut off at the bottom
    has none, so neither is a row either.

    Args:
        task: The Daily task.

    Returns:
        The rows top to bottom, each a `Ride`: its level (0 before it is built), its emotion, `UPGRADE` or `BUILD`, the
        button's box, the price (None when it does not read as a park number), the price's box (None when absent) and
        every box in the row's price column, the price line's and those above it up to the name line.
    """
    boxes = [(box, x, y) for box, x, y in boxes_of(task) if LIST_TOP <= y <= LIST_BOTTOM]
    rows = []
    for box, x, y in sorted(boxes, key=lambda item: item[2]):
        name = NAME.fullmatch(box.name.strip())
        if name is None or not NAME_X[0] <= x <= NAME_X[1]:
            continue
        level = next((LEVEL.search(other.name) for other, ox, oy in boxes if ox >= LEVEL_X and abs(oy - y) <= SAME_LINE
                      and LEVEL.search(other.name)), None)
        emotion = next((EMOTION_LINE.search(other.name) for other, ox, oy in boxes if NAME_X[0] <= ox <= PRICE_X
                        and EMOTION_BELOW[0] <= oy - y <= EMOTION_BELOW[1] and EMOTION_LINE.search(other.name)), None)
        button = next(((other, oy) for other, ox, oy in boxes if BUTTON_X[0] <= ox <= BUTTON_X[1] and BUTTON_BELOW[0] <= oy - y <= BUTTON_BELOW[1]
                       and other.name.strip().casefold() in UPGRADE_CAPTIONS + BUILD_CAPTIONS), None)
        if button is None or emotion is None:
            continue
        button_box, button_y = button
        action = BUILD if button_box.name.strip().casefold() in BUILD_CAPTIONS else UPGRADE
        if action == UPGRADE and level is None:
            continue
        price_box = next((other for other, ox, oy in boxes if ox >= PRICE_X and abs(oy - button_y) <= SAME_LINE), None)
        price = parse_number(price_box.name) if price_box is not None else None
        column = tuple(other for other, ox, oy in boxes if ox >= PRICE_X and y - SAME_LINE <= oy <= button_y + SAME_LINE)
        rows.append(Ride(name.group(1).strip(), int(level.group(1)) if level else 0, emotion_of(emotion.group(1)), action, button_box, price,
                         price_box, column))
    return rows


def list_side(task):
    """Give every box on the Facilities list's side of the screen, in rows or between them, from its top to its bottom."""
    return [box for box, x, y in boxes_of(task) if x >= LIST_SIDE_X and LIST_TOP <= y <= LIST_BOTTOM]


def emotion_of(text):
    """Name the emotion an emotion line starts with, OCR's `Thril` included."""
    return next(emotion for emotion in EMOTIONS if text.casefold().startswith(emotion[:5].casefold()))


def choose(rides, emotions, money, stretch=None):
    """Choose the next press in the Facilities list, or why there is none.

    Build a newly unlocked ride first when its price is within the profit; when one costs more than the profit but no
    more than one full offline stretch, save for it and upgrade nothing. Otherwise upgrade the cheapest ride of the
    emotion furthest below the Rank target; once all three are at the target, the cheapest ride of all, which counts
    toward the ride-level achievements. A row whose price did not read is never chosen.

    Args:
        rides: The rows, from `facility_rows`.
        emotions: `((thrill, comfort, happiness), target)`, or None when unread.
        money: The profit, or None when unread.
        stretch: What one full offline stretch earns, or None when unknown, which turns the saving rule off.

    Returns:
        `(ride, None)` for the row to press, or `(None, reason)`.
    """
    if money is None:
        return None, "the profit did not read"
    builds = sorted((ride for ride in rides if ride.action == BUILD and ride.price is not None), key=lambda ride: ride.price)
    for ride in builds:
        if ride.price <= money:
            return ride, None
    for ride in builds:
        if stretch is not None and ride.price <= stretch:
            return None, f"saving for {ride.name} ({ride.price:,.0f})"
    if emotions is None:
        return None, "the emotions did not read"
    values, target = emotions
    upgrades = [ride for ride in rides if ride.action == UPGRADE and ride.price is not None and ride.level < MAX_LEVEL]
    shortfall = {emotion: target - value for emotion, value in zip(EMOTIONS, values) if value < target}
    if shortfall:
        worst = max(shortfall.values())
        lagging = [emotion for emotion, short in shortfall.items() if short == worst]
        upgrades = [ride for ride in upgrades if ride.emotion in lagging]
        if not upgrades:
            return None, f"no {' or '.join(lagging)} ride with a readable price in view"
    if not upgrades:
        return None, "no ride with a readable price in view"
    cheapest = min(upgrades, key=lambda ride: ride.price)
    if cheapest.price > money:
        return None, f"the next upgrade, {cheapest.name}, costs more than the profit"
    return cheapest, None


def rank_up_button(task):
    """Find the `Rank Up` caption on the Amusement Park Rank screen, on whichever card it is drawn.

    Args:
        task: The Daily task.

    Returns:
        The box, or None.
    """
    for box, x, y in boxes_of(task):
        if box.name.strip().casefold().replace(" ", "") == "rankup" and RANK_UP_BAND[0] <= y <= RANK_UP_BAND[1]:
            return box
    return None


def rank_up_live(frame, box, width, height):
    """Say whether a `Rank Up` caption sits on the blue pill of an earned Rank.

    Args:
        frame: The capture, or None.
        box: The caption's box.
        width: Screen width in pixels.
        height: Screen height in pixels.

    Returns:
        True when the pill around it is blue. False when it is grey, or there is no frame to read.
    """
    x, y = centre_of(box, width, height)
    half_x, half_y = RANK_UP_HALF
    return colour_share(patch_of(frame, (x - half_x, y - half_y, x + half_x, y + half_y)), LIVE_LOW, LIVE_HIGH) >= LIVE_SHARE


def ready_claims(task, frame):
    """Find the achievement rows whose reward is ready, told by the orange claim ring.

    Args:
        task: The Daily task.
        frame: The capture, or None.

    Returns:
        The claim points as `(x, y)` screen fractions, top to bottom.
    """
    points = []
    for box, x, y in sorted(boxes_of(task), key=lambda item: item[2]):
        if not (PROGRESS_X[0] <= x <= PROGRESS_X[1] and PROGRESS.fullmatch(box.name.strip())):
            continue
        point = (CLAIM_X, y - CLAIM_ABOVE)
        half_x, half_y = CLAIM_HALF
        patch = patch_of(frame, (point[0] - half_x, point[1] - half_y, point[0] + half_x, point[1] + half_y))
        if colour_share(patch, READY_LOW, READY_HIGH) >= READY_SHARE:
            points.append(point)
    return points


def event_entry(task):
    """Find Nightmare Dream Park in the Event list's left column.

    Args:
        task: The Daily task.

    Returns:
        The box, or None when the event is not listed.
    """
    for box in getattr(task, "all_texts", None) or []:
        if EVENT_ENTRY in box.name.casefold().replace(" ", "") and in_region(box, EVENT_LIST_REGION, task.width, task.height):
            return box
    return None
