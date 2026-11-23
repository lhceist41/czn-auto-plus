"""Read what the battle screen says about the moment a card is being chosen in.

`SortieMode.run` pays for one full-frame OCR a second and every handler reads the result for free, so
everything here comes out of that pass or out of raw pixels. The one exception is `enemies`, which reads each enemy's numbers off a
zoomed crop because the full-frame pass drops too many of them.
"""

import re
from collections import namedtuple
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from ok import Logger

from src.en.game_battle import ATTRIBUTES
from src.en.screen import centre_of, colour_share, frame_of, hsv_of, in_region, patch_of, white_mask

logger = Logger.get_logger(__name__)

# The Action Point readout, as a relative box. Read from colour because OCR finds the digit only on a padded crop, and seldom a 1
# (`battle.points_left` reads the rest). The game draws it bright blue with a glow while there are points to spend and a thin grey
# outline once there are none. Deliberately tight on the digit: the hand counter below it and the decorative line through its middle
# both sit outside, so neither can be counted as a lit reading.
ACTION_POINTS = (0.488, 0.898, 0.528, 0.948)
# How bright a pixel has to be to count as part of the digit rather than the scene behind it. 200 rather than
# the obvious 170 because one frame's background sits at exactly 170 across a large flat area, which would
# have read an empty turn as a full one.
LIT = 200
# The share of the readout that has to be lit before it is read as "points remain". Across 30 real frames, 25
# empty and 5 with points, the lit share came out at most 0.031 empty and at least 0.130 full - four times
# over - and it holds from 1280x720 to 2560x1440. `tests/TestBoard.py` pins the tightest pair, so anything
# narrowing the gap fails there first.
LIT_ENOUGH = 0.08

# The three Ego slots, in the order the panel shows them.
EGO_KEYS = ("F1", "F2", "F3")
# Where each slot's cost badge sits. The three are evenly spaced down the panel, and the figures come from the
# OCR pass, which does read the bottom slot's badge and both of the outer labels even though it misses the
# Action Point digit entirely.
EGO_BADGE_X = 0.065
EGO_BADGE_Y = {"F1": 0.7140, "F2": 0.8050, "F3": 0.8960}
EGO_BADGE_HALF = (0.0090, 0.0150)
# The game tints an affordable badge, pale blue or the yellow-green of a reduced cost, and draws one it cannot pay for in grey.
BADGE_LIT = 120
TINT_SATURATION = 30
# How much of a badge's lit pixels have to be tinted before the Ego behind it is treated as one that can be fired. Measured: 1.0 on a
# blue badge, 0.995 on a reduced one and under 0.01 on a grey one.
EGO_READY = 0.5
# A slot draws its cost badge only while it holds an Ego, and a fired partner leaves an empty frame behind. Measured on 171 frames of a run:
# an empty slot at most 0.08 bright, even under a skill's flash, and a badge at least 0.55, while it is the selected slot's Cancel button.
EGO_PRESENT = 0.3
# The EP bar left of the Ego panel: seven segments down from the top, lit pale blue for each point banked and pale yellow for the
# points a previewed Ego would spend. Upstream's full-bar pixel at 0.947 is the seventh. A segment still filling is lit to about 203.
EP_SEGMENT_X = (0.020, 0.044)
EP_SEGMENT_TOP = 0.7806
EP_SEGMENT_PITCH = 0.0278
EP_SEGMENT_HALF = 0.0050
EP_MAX = 7
EP_LIT = 230
EP_LIT_ENOUGH = 0.6

# The team HP bar along the top, row 36 to 46 at 1080p. Its green stops where the enemy's next hit would leave the team, and the
# stretch from there to the HP the readout states flashes red. The readout's digits are drawn over the middle of the bar, so a
# column counts as green when `GREEN_ROWS` of its rows are.
TEAM_BAR = (0.0234, 0.0333, 0.4000, 0.0426)
GREEN_HUE = (40, 85)
GREEN_SATURATION = 100
GREEN_VALUE = 120
GREEN_ROWS = 2

# A hand card's cost digit, as offsets from the left edge of its name box and the middle of its height.
COST_OFFSET = (-0.026, -0.030, 0.002, 0.040)
# The game draws a cost an effect has lowered in lit green, and any other cost in white. Green card art sits behind some white digits, so
# only bright green counts: 0.059 to 0.097 of five lowered digits against at most 0.032 of 17 white ones.
LOWERED_LOW = np.array([40, 80, 200])
LOWERED_HIGH = np.array([85, 255, 255])
LOWERED_ENOUGH = 0.045

# The Absolute Invincibility badge drawn among an enemy's statuses, cut from a 1080p frame and matched on its white strokes.
INVULNERABLE_IMAGE = Path(__file__).with_name("images") / "absolute_invincibility.png"
TEMPLATE_HEIGHT = 1080
# It scores 1.0 on the capture it was cut from and at most 0.49 on 846 others.
INVULNERABLE_MATCH = 0.7

# Where the enemies' counters and badges are drawn: below the top HUD, above the cards and the combatants.
ENEMY_BAND = (0.30, 0.12, 1.00, 0.60)
# The action counter's own magenta, and the shape it is drawn in. The HP bar beside it is a lighter pink and
# is far too wide to pass the squareness test, so neither can be mistaken for the other.
# `tests/images/enemy_instinct.png` pins the counter and the badge beside it against the game's own rendering.
COUNTER_HUE = (160, 178)
COUNTER_SATURATION = 170
COUNTER_VALUE = 120
COUNTER_MIN_AREA = 400
COUNTER_SQUARENESS = (0.6, 1.7)
# How tall a counter is, as a share of the frame. Every real one measures between 0.057 and 0.060, while
# the magenta flashes an attack throws up run from 0.08 to 0.38 and the smaller markers sit at 0.033, so
# this band is what keeps a hit landing on screen from being counted as another enemy. `attack_flash.png`
# holds the burst that passes every other test and fails here.
COUNTER_HEIGHT = (0.045, 0.072)
# Where the weakness badge sits relative to its counter, and how much of it to sample.
WEAKNESS_OFFSET = (0.0185, 0.0225)
WEAKNESS_HALF = (0.0085, 0.0085)
WEAKNESS_SATURATION = 150
# The boss select screen draws its badges paler. Its Order badge sits at a saturation of about 107.
BOSS_BADGE_SATURATION = 100
WEAKNESS_VALUE = 130
# How much of the sampled patch has to be strongly coloured before it is read as a badge rather than scenery.
WEAKNESS_ENOUGH = 0.20
# The hue the client draws each of its attribute colours in. The client stores attributes as colours, so
# `ATTRIBUTES` already says which is which. Measured at 15, 78 and 133 out of 180 with a spread of about three
# each, and only the orange one has been confirmed against the game, as Instinct. Red sits at 0 rather than
# 180 only because that is the same place on a hue wheel, and the nearest of these five decides which
# attribute a badge is.
ATTRIBUTE_HUES = {"RED": 0, "ORANGE": 15, "GREEN": 78, "BLUE": 110, "PURPLE": 133}
# How far a badge's hue may sit from the nearest of those before it is treated as not a badge at all.
HUE_TOLERANCE = 20

# The two statuses the game marks a summoned enemy with, either or both, cut from a 1080p frame and matched on their white strokes.
SUMMONED_IMAGES = tuple(Path(__file__).with_name("images") / name for name in ("summoned_horns.png", "summoned_ghost.png"))
# Real ones scored 0.92 to 1.0. Across 197 counters in 851 captures, nothing else scored above 0.60.
SUMMONED_MATCH = 0.8
# Wider than `ENEMY_BAND` at the top, which cuts through the counter of a boss standing tall enough to put it there.
TARGET_BAND = (0.30, 0.05, 1.00, 0.60)
# An enemy that has acted shows a grey diamond with a white X where its counter was, and so does every enemy on a turn's first frame until
# the first input. Cut from a 1080p frame and matched in grey at the counter's own centre.
ACTED_IMAGE = Path(__file__).with_name("images") / "enemy_acted.png"
# Across 562 saved frames, every X beside an HP above 0 scored 0.683 or more and an X beside a dying enemy's 0 scored 0.638. Nothing else
# scored above 0.629, a card reward's Attack icon, and no magenta counter above 0.547. An X counts without a number beside it, so this
# margin alone keeps other icons out.
ACTED_MATCH = 0.65
# The row of statuses below an enemy's HP bar, as offsets from its counter's centre.
STATUS_ROW = (0.01, 0.005, 0.17, 0.07)
# Where an enemy's HP number sits, as offsets from its counter's centre. A counter with no number there is scenery in the same magenta.
HEALTH_NUMBER = (0.03, -0.05, 0.12, 0.0)
HEALTH_DIGITS = re.compile(r"^\d+$")
# Where the ring a raised attack card puts over its target can be centred. Below it, the raised card's own art can hold a ring of the same size.
RETICLE_BAND = (0.30, 0.25, 1.00, 0.60)
# The ring's radius as a share of the frame height, 74 to 77px at 1080p in both captures, white or cyan by who plays the card.
RETICLE_RADIUS = (0.059, 0.078)
# Canny's upper edge threshold and the accumulator votes a ring needs. Across 847 captures the rings found were real ones or scenery.
RETICLE_EDGES = 120
RETICLE_VOTES = 40
# The reticle's outer ring is drawn white whoever plays the card, while the scenery that passes for one (a spider's body, a crab's
# bubbles, a round rock) is not. Within this far of the ring found, as a share of the frame height, a white pixel counts for its angle.
RETICLE_STROKE = 0.004
RETICLE_WHITE_VALUE = 180
RETICLE_WHITE_SATURATION = 60
RETICLE_ANGLES = 72
# Across 416 saved frames, every ring over an enemy with a card raised was white at 0.528 or more of its angles and every scenery ring
# in a fight at 0.33 or less.
RETICLE_WHITE_ENOUGH = 0.45
# The hint the game shows bottom left while a card is raised, the ESC key over "Cancel Selection", cut from a 1080p frame and matched on its
# edges, since its white text sits on a dark outline over a light scene and a dark one alike.
CARD_RAISED_IMAGE = Path(__file__).with_name("images") / "card_raised.png"
CARD_RAISED_BAND = (0.0, 0.87, 0.16, 0.99)
# Across 131 saved battle frames, the 44 with a card raised scored 0.75 or more and the others 0.18 or less. Rings alone also fired on
# bubbles and scenery in 7 frames without a card raised.
CARD_RAISED_MATCH = 0.5
# An enemy's action counter digit, as a half-size around the counter's centre. Measured on a 1080p capture.
COUNTER_DIGIT_HALF = (0.016, 0.026)
# How much the HP number and the counter digit are enlarged, and the black border each enlarged crop gets, in pixels before enlarging.
# Across 273 enemies in 228 battle frames, the full-frame pass had a number for 237, and 21 of those disagreed with the frame: a 1 dropped
# or added, or the HP the enemy had shown a moment earlier. The enlarged crop read 271, and none of the 40 checked by hand was wrong.
HEALTH_ZOOM = 3
COUNTER_ZOOM = 4
CROP_MARGIN = 12
# The infinity a counter shows for an enemy that will not act often reads as an 8. Its glyph is about twice as wide as it is tall and the 8
# about two thirds as wide, so the white strokes in the middle of the diamond tell them apart.
GLYPH_HALF = (0.010, 0.013)
INFINITY_WIDTH = 1.2
COUNTER_DIGITS = re.compile(r"^\d{1,2}$")
# How sure OCR has to be of a counter. Of 241 counter readings in 228 battle frames, the one wrong digit, a 7 taken for a 1, scored 0.81
# and every infinity taken for an 8 under 0.85, while the 225 that scored 0.9 or more were all right.
COUNTER_SURE = 0.9
# What `enemies` knows about one enemy: its counter's x as a fraction across the frame, its current HP, how many more cards can be played
# before it acts, and the attribute it is weak to. Each of those three is None when it was not read for sure. `sure` says the zoomed crop
# read one HP and the full-frame pass read the same or nothing there, which is what a kill is planned on. `agreed` says that pass read the
# same HP, not nothing: a crop alone can read a covered 178 as 17, and a hit learnt from that would stay in the saved figures.
Foe = namedtuple("Foe", ["x", "health", "counter", "weakness", "sure", "agreed"], defaults=[False, False])


def box_around(centre_x, centre_y, half):
    """Build a relative box of a given size around a point.

    Args:
        centre_x: Where the middle of the box sits across the frame, as a fraction.
        centre_y: Where the middle of the box sits down the frame, as a fraction.
        half: The `(x, y)` half-size, in the same fractions.

    Returns:
        A `(left, top, right, bottom)` tuple.
    """
    half_x, half_y = half
    return (centre_x - half_x, centre_y - half_y, centre_x + half_x, centre_y + half_y)


def lit_fraction(patch):
    """Say how much of a patch is drawn brightly.

    Args:
        patch: The pixels to measure, in BGR.

    Returns:
        The share of pixels brighter than `LIT`, from 0 to 1, and 0 for an empty patch.
    """
    if patch is None or patch.size == 0:
        return 0.0
    grey = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return float(np.count_nonzero(grey > LIT)) / grey.size


def has_action_points(task):
    """Say whether the turn still has Action Points to spend.

    Args:
        task: The running task.

    Returns:
        True while the readout is lit - whether any points remain, not how many, which is all the planner
        needs and all the screen gives away. Also True when there is no frame to read, because ending a turn
        that had not finished costs more than trying a card that will not play.
    """
    patch = patch_of(frame_of(task), ACTION_POINTS)
    if patch is None:
        return True
    return lit_fraction(patch) >= LIT_ENOUGH


def cost_digit(left, middle):
    """Build the relative box around a hand card's cost digit.

    Args:
        left: The left edge of the card's name box, as a fraction across the frame.
        middle: The middle of the name box's height, as a fraction down the frame.

    Returns:
        A `(left, top, right, bottom)` tuple.
    """
    return left + COST_OFFSET[0], middle + COST_OFFSET[1], left + COST_OFFSET[2], middle + COST_OFFSET[3]


def cost_lowered(frame, box):
    """Say whether a hand card's cost digit is drawn in the green of a lowered cost.

    Args:
        frame: The frame to read, from `frame_of`.
        box: The digit's box, from `cost_digit`.

    Returns:
        True for a lit green digit. A card the turn cannot afford is drawn dimmed and reads False, which costs nothing since it cannot be
        played either way.
    """
    return colour_share(patch_of(frame, box), LOWERED_LOW, LOWERED_HIGH) >= LOWERED_ENOUGH


def tinted_fraction(patch):
    """Say how much of a lit patch is drawn in colour rather than grey.

    Measured against the lit pixels rather than the whole patch, so a badge sitting on a dark background and
    one sitting on a bright scene are judged the same way.

    Args:
        patch: The pixels to measure, in BGR.

    Returns:
        The tinted share of the lit pixels, from 0 to 1, and 0 for an empty patch.
    """
    hsv = hsv_of(patch)
    if hsv is None:
        return 0.0
    _, saturation, value = cv2.split(hsv)
    lit = value > BADGE_LIT
    return float(np.count_nonzero(lit & (saturation > TINT_SATURATION))) / max(int(np.count_nonzero(lit)), 1)


def affordable_egos(task):
    """List the Ego skills the EP bar can currently pay for.

    Args:
        task: The running task.

    Returns:
        The keys that fire an affordable Ego, in panel order. Empty when none can be paid for, and empty when
        there is no frame to read, since firing one blind is the behaviour this exists to replace.
    """
    frame = frame_of(task)
    ready = []
    for key in EGO_KEYS:
        box = box_around(EGO_BADGE_X, EGO_BADGE_Y[key], EGO_BADGE_HALF)
        if tinted_fraction(patch_of(frame, box)) > EGO_READY:
            ready.append(key)
    return ready


def ego_in_slot(frame, key):
    """Say whether a slot holds an Ego, which the slot of a partner already fired no longer does.

    Args:
        frame: The frame to read, or None when there is none.
        key: The slot's key, one of `EGO_KEYS`.

    Returns:
        True while the slot shows its cost badge, and False when there is no frame.
    """
    patch = patch_of(frame, box_around(EGO_BADGE_X, EGO_BADGE_Y[key], EGO_BADGE_HALF))
    if patch is None or patch.size == 0:
        return False
    return float(np.count_nonzero(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) >= BADGE_LIT)) / patch.shape[0] / patch.shape[1] >= EGO_PRESENT


def banked_points(frame):
    """Count the EP the bar has banked.

    Args:
        frame: The frame to read, or None when there is none.

    Returns:
        How many segments are lit from the top, 0 to `EP_MAX`, and 0 when there is no frame.
    """
    banked = 0
    for index in range(EP_MAX):
        middle = EP_SEGMENT_TOP + index * EP_SEGMENT_PITCH
        patch = patch_of(frame, (EP_SEGMENT_X[0], middle - EP_SEGMENT_HALF, EP_SEGMENT_X[1], middle + EP_SEGMENT_HALF))
        if patch is None or patch.size == 0 or np.count_nonzero(patch.max(axis=2) > EP_LIT) < EP_LIT_ENOUGH * patch.shape[0] * patch.shape[1]:
            break
        banked += 1
    return banked


def team_after_hit(frame):
    """Say how much of the team's HP will be left once the enemy's next hit lands.

    Args:
        frame: The frame to read, or None when there is none.

    Returns:
        The share of the team's maximum HP the bar's green reaches, or None when no green is on the bar or there is no frame.
    """
    hsv = hsv_of(patch_of(frame, TEAM_BAR))
    if hsv is None:
        return None
    hue, saturation, value = cv2.split(hsv)
    green = (hue > GREEN_HUE[0]) & (hue < GREEN_HUE[1]) & (saturation > GREEN_SATURATION) & (value > GREEN_VALUE)
    columns = np.flatnonzero(np.count_nonzero(green, axis=0) >= GREEN_ROWS)
    if not columns.size:
        return None
    return float(columns[-1] + 1) / green.shape[1]


@lru_cache(maxsize=8)
def icon_template(path, height, mask=white_mask):
    """Load a status icon cut from a 1080p frame, scaled to a frame's size.

    Args:
        path: The icon's image file, such as `INVULNERABLE_IMAGE`.
        height: The frame height in pixels.
        mask: Reduces the icon to the pixels it is matched on, the near-white ones unless the caller says otherwise.

    Returns:
        The icon's mask, or None when the image cannot be read.
    """
    image = cv2.imread(str(path))
    if image is None:
        logger.warning(f"could not read the status icon from {path}")
        return None
    scale = height / TEMPLATE_HEIGHT
    if scale != 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return mask(image)


def enemy_invulnerable(frame):
    """Say whether an enemy is showing Absolute Invincibility, which stops it losing Health for the turn.

    Args:
        frame: The frame to read, or None when there is none.

    Returns:
        True when the badge is among the enemy statuses. False when it is not, or there is no frame.
    """
    patch = patch_of(frame, ENEMY_BAND)
    if patch is None or patch.size == 0:
        return False
    return icon_match(patch, INVULNERABLE_IMAGE, frame.shape[0]) >= INVULNERABLE_MATCH


def icon_match(patch, path, height):
    """Score how well a status icon matches anywhere in a patch.

    Args:
        patch: The pixels to search, in BGR.
        path: The icon's image file.
        height: The frame height in pixels, which the icon is scaled to.

    Returns:
        The best match, from -1 to 1, or 0 when the icon cannot be read or does not fit in the patch.
    """
    template = icon_template(path, height)
    if template is None or patch is None or patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return 0.0
    return float(cv2.matchTemplate(white_mask(patch), template, cv2.TM_CCOEFF_NORMED).max())


def hue_distance(one, other):
    """Measure the gap between two hues the short way round the wheel.

    Args:
        one: A hue, 0 to 179.
        other: The hue to compare it against.

    Returns:
        The smaller of the two ways round, so red at 179 and red at 0 are neighbours rather than opposites.
    """
    gap = abs(int(one) - int(other)) % 180
    return min(gap, 180 - gap)


def attribute_of(patch, beside_counter=True, saturation_floor=WEAKNESS_SATURATION):
    """Say which attribute a badge is drawn for.

    Assumes a battle or boss select screen: swept over `captures/`, the 22 battle frames read Instinct or nothing,
    but red artwork elsewhere - a Card Epiphany screen, a full-screen portrait - throws up shapes that pass for counters and reads as Passion.

    Args:
        patch: The pixels the badge was sampled from, in BGR.
        beside_counter: Whether the badge sits beside an enemy's action counter, as it does in battle. The boss
            select screen has no counter, and its Passion badge is drawn at a hue of 176, inside the counter's band.
        saturation_floor: How saturated a pixel has to be to count as badge colour.

    Returns:
        The attribute's name, or None when the patch holds no badge worth reading.
    """
    hsv = hsv_of(patch)
    if hsv is None:
        return None
    hue, saturation, value = cv2.split(hsv)
    strong = (saturation > saturation_floor) & (value > WEAKNESS_VALUE)
    if np.count_nonzero(strong) < WEAKNESS_ENOUGH * strong.size:
        return None
    middle = int(np.median(hue[strong]))
    # The counter sitting beside the badge is magenta, which is red's neighbour on the hue wheel, so its own
    # colour would otherwise read as a confident Passion. Anything in that band is the counter, or one of the
    # effects the game draws in the same colour, rather than a badge.
    if beside_counter and COUNTER_HUE[0] < middle < COUNTER_HUE[1]:
        return None
    colour = min(ATTRIBUTE_HUES, key=lambda name: hue_distance(middle, ATTRIBUTE_HUES[name]))
    if hue_distance(middle, ATTRIBUTE_HUES[colour]) > HUE_TOLERANCE:
        return None
    return ATTRIBUTES.get(colour)


def enemy_counters(frame, band=ENEMY_BAND):
    """Find the action counter of every enemy on screen.

    Args:
        frame: The frame to read, or None when there is none.
        band: Where to look, `ENEMY_BAND` unless a caller needs the top of the screen too.

    Returns:
        A list of `(x, y)` centres in fractions of the frame, left to right.
    """
    hsv = hsv_of(patch_of(frame, band))
    if hsv is None:
        return []
    height, width = frame.shape[:2]
    # One pass over the three channels rather than three. The bounds `inRange` takes are inclusive and the
    # ones named above are exclusive, hence the step in at each end.
    mask = cv2.inRange(hsv, (COUNTER_HUE[0] + 1, COUNTER_SATURATION + 1, COUNTER_VALUE + 1),
                       (COUNTER_HUE[1] - 1, 255, 255))
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask, 8)
    left, top = band[0], band[1]
    found = []
    for index in range(1, count):
        _, _, box_width, box_height, area = stats[index]
        if area < COUNTER_MIN_AREA:
            continue
        squareness = box_width / max(box_height, 1)
        if not COUNTER_SQUARENESS[0] < squareness < COUNTER_SQUARENESS[1]:
            continue
        if not COUNTER_HEIGHT[0] <= box_height / height <= COUNTER_HEIGHT[1]:
            continue
        found.append((left + centres[index][0] / width, top + centres[index][1] / height))
    return sorted(found)


def greyscale(image):
    """Reduce BGR pixels to grey, which the X diamond is matched in since it is drawn in grey and white.

    Args:
        image: The pixels, in BGR.

    Returns:
        A single-channel image.
    """
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def enemy_markers(frame):
    """Find every enemy on screen by its action counter or, once it has acted, the X diamond drawn in the counter's place.

    Args:
        frame: The frame to read, or None when there is none.

    Returns:
        A list of `(x, y, acted)`, the centre in fractions of the frame and whether it is an X diamond, left to right.
    """
    band = TARGET_BAND
    found = [(x, y, False) for x, y in enemy_counters(frame, band)]
    patch = patch_of(frame, band)
    template = icon_template(ACTED_IMAGE, frame.shape[0], greyscale) if patch is not None and patch.size else None
    if template is None or patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return found
    height, width = frame.shape[:2]
    scores = cv2.matchTemplate(greyscale(patch), template, cv2.TM_CCOEFF_NORMED)
    template_height, template_width = template.shape
    while True:
        _, best, _, (left, top) = cv2.minMaxLoc(scores)
        if best < ACTED_MATCH:
            break
        # Clear the template's own size around the peak, so one diamond is found once.
        cv2.rectangle(scores, (left - template_width, top - template_height), (left + template_width, top + template_height), -1, -1)
        found.append((band[0] + (left + template_width / 2) / width, band[1] + (top + template_height / 2) / height, True))
    return sorted(found)


def weakness(task):
    """Say which attribute the enemies are weak to.

    No preference when they disagree, because no capture yet shows a mixed fight to check a majority against.

    Args:
        task: The running task.

    Returns:
        The attribute every enemy on screen shares, or None when they differ, when none was read, or when
        there is no frame to read.
    """
    frame = frame_of(task)
    seen = set()
    for centre_x, centre_y in enemy_counters(frame):
        badge = box_around(centre_x + WEAKNESS_OFFSET[0], centre_y + WEAKNESS_OFFSET[1], WEAKNESS_HALF)
        attribute = attribute_of(patch_of(frame, badge))
        if attribute:
            seen.add(attribute)
    return seen.pop() if len(seen) == 1 else None


def boss_x(task):
    """Find where the boss stands, so attacks go to it rather than to the minions it summons again each turn.

    Args:
        task: The running task, whose `all_texts` holds each enemy's HP number.

    Returns:
        The x of the HP number of the one enemy on screen not marked as summoned, or None unless at least one is and exactly one is not.
    """
    frame = frame_of(task)
    height = frame.shape[0] if frame is not None else 0
    numbers = [box for box in getattr(task, "all_texts", None) or [] if HEALTH_DIGITS.match(box.name)]
    summoned, unsummoned = 0, []
    for centre_x, centre_y in enemy_counters(frame, TARGET_BAND):
        region = (centre_x + HEALTH_NUMBER[0], centre_y + HEALTH_NUMBER[1], centre_x + HEALTH_NUMBER[2], centre_y + HEALTH_NUMBER[3])
        number = next((box for box in numbers if in_region(box, region, task.width, task.height)), None)
        if number is None:
            continue
        row = patch_of(frame, (centre_x + STATUS_ROW[0], centre_y + STATUS_ROW[1], min(1.0, centre_x + STATUS_ROW[2]), centre_y + STATUS_ROW[3]))
        if any(icon_match(row, path, height) >= SUMMONED_MATCH for path in SUMMONED_IMAGES):
            summoned += 1
        else:
            unsummoned.append(centre_of(number, task.width, task.height)[0])
    return unsummoned[0] if summoned and len(unsummoned) == 1 else None


def enlarged(zoom):
    """Build the frame processor that enlarges an enemy's crop and pads it with black, so OCR finds every digit in it.

    Args:
        zoom: How many times to enlarge the crop.

    Returns:
        A function from the cut-out pixels to the enlarged ones inside a black border.
    """
    def enlarge(image):
        margin = CROP_MARGIN * zoom
        image = cv2.resize(image, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(image, margin, margin, margin, margin, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    return enlarge


def numbers_in(task, frame, region, zoom, pattern, threshold=0):
    """Read the numbers on an enlarged crop of the frame.

    Args:
        task: The running task, for its OCR.
        frame: The frame to read, from `frame_of`.
        region: Where to read, as a relative box, cut back to the frame where it runs off it.
        zoom: How many times to enlarge the crop.
        pattern: What a reading has to look like to count.
        threshold: How sure OCR has to be of a reading, or 0 for its own default.

    Returns:
        Every reading that matches, as text.
    """
    left, top, right, bottom = max(0.0, region[0]), max(0.0, region[1]), min(1.0, region[2]), min(1.0, region[3])
    if left >= right or top >= bottom:
        return []
    read = [box.name.strip() for box in task.ocr(left, top, right, bottom, frame=frame, threshold=threshold, frame_processor=enlarged(zoom)) or []]
    return [text for text in read if pattern.match(text)]


def counter_glyph_wide(frame, centre_x, centre_y):
    """Say whether the white figure inside an action counter is drawn wider than it is tall, as the infinity is and no digit is.

    Args:
        frame: The frame to read.
        centre_x: The counter's centre across the frame, as a fraction.
        centre_y: The counter's centre down the frame, as a fraction.

    Returns:
        True when the largest white shape in the middle of the diamond is wide. False when it is not, or nothing white is there.
    """
    patch = patch_of(frame, box_around(centre_x, centre_y, GLYPH_HALF))
    if patch is None or patch.size == 0:
        return False
    # The largest shape rather than every white pixel, so a sliver of bright scenery at a corner cannot stretch the figure.
    count, _, stats, _ = cv2.connectedComponentsWithStats(white_mask(patch), 8)
    if count < 2:
        return False
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return bool(stats[largest, cv2.CC_STAT_WIDTH] > INFINITY_WIDTH * stats[largest, cv2.CC_STAT_HEIGHT])


def enemies(task):
    """Read every enemy on screen: where it stands, its HP, how soon it acts and what it is weak to.

    Args:
        task: The running task, whose `all_texts` holds the full-frame OCR pass and whose OCR reads the zoomed crops.

    Returns:
        A tuple of `Foe`, left to right. The HP is the zoomed crop's number, or a full-frame number of three digits or more when the
        crop reads none, since that pass drops a leading 1 and can hold a number from an earlier frame. The counter is the crop's
        number, and None for the infinity of an enemy that will not act or the X of one that has acted. A counter with neither number
        is left out: card art in the same magenta passes for one. An X is kept with no HP when its number does not read, so the enemy
        still counts and no single hit is taken to kill the others for sure. An enemy at 0 HP is dying and left out. The HP is sure
        when the crop read one number and the full-frame pass read the same or none, since that pass drops small numbers rather than
        misreading them, and agreed when that pass read the same.
    """
    frame = frame_of(task)
    numbers = [box for box in getattr(task, "all_texts", None) or [] if HEALTH_DIGITS.match(box.name)]
    found = []
    for centre_x, centre_y, acted in enemy_markers(frame):
        region = (centre_x + HEALTH_NUMBER[0], centre_y + HEALTH_NUMBER[1], centre_x + HEALTH_NUMBER[2], centre_y + HEALTH_NUMBER[3])
        full = next((box.name for box in numbers if in_region(box, region, task.width, task.height)), None)
        zoomed = set(numbers_in(task, frame, region, HEALTH_ZOOM, HEALTH_DIGITS))
        sure = len(zoomed) == 1 and (full is None or full in zoomed)
        if len(zoomed) == 1:
            health = int(zoomed.pop())
        elif full is not None and (full in zoomed or not zoomed and len(full) >= 3):
            health = int(full)
        else:
            health = None
        counter = None
        if not acted:
            counted = set(numbers_in(task, frame, box_around(centre_x, centre_y, COUNTER_DIGIT_HALF), COUNTER_ZOOM, COUNTER_DIGITS,
                                     COUNTER_SURE))
            counter = int(counted.pop()) if len(counted) == 1 else None
            if counter == 8 and counter_glyph_wide(frame, centre_x, centre_y):
                counter = None
        if health is None and counter is None and not acted or health == 0:
            continue
        badge = box_around(centre_x + WEAKNESS_OFFSET[0], centre_y + WEAKNESS_OFFSET[1], WEAKNESS_HALF)
        found.append(Foe(round(centre_x, 3), health, counter, attribute_of(patch_of(frame, badge)), sure, sure and full is not None))
    return tuple(found)


def edges(image):
    """Reduce BGR pixels to how sharply their brightness changes.

    Args:
        image: The pixels, in BGR.

    Returns:
        A single-channel float image, high along every edge whichever side of it is the brighter.
    """
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return cv2.magnitude(cv2.Sobel(grey, cv2.CV_32F, 1, 0), cv2.Sobel(grey, cv2.CV_32F, 0, 1))


def card_raised(frame):
    """Say whether a hand card is raised, waiting for Enter or ESC, by the hint the game shows for those keys.

    A raised attack card dims the counters of the enemies it is not aimed at and shows the HP it would leave on the ones it is, so the
    enemies read on such a frame are not the ones on the field.

    Args:
        frame: The frame to read, or None when there is none.

    Returns:
        True while the hint is shown. False when it is not, or there is no frame.
    """
    patch = patch_of(frame, CARD_RAISED_BAND)
    template = icon_template(CARD_RAISED_IMAGE, frame.shape[0], edges) if patch is not None and patch.size else None
    if template is None or patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return False
    return float(cv2.matchTemplate(edges(patch), template, cv2.TM_CCOEFF_NORMED).max()) >= CARD_RAISED_MATCH


def reticle_x(frame):
    """Find which enemy a raised attack card is aimed at, by the ring it puts over that enemy's body.

    Args:
        frame: The frame to read, taken after the card's key was pressed.

    Returns:
        The ring's x, which lines up with its enemy's HP number. None for no white ring, or several, as an all-enemy card draws.
    """
    patch = patch_of(frame, RETICLE_BAND)
    if patch is None or patch.size == 0:
        return None
    height, width = frame.shape[:2]
    grey = cv2.medianBlur(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 3)
    rings = cv2.HoughCircles(grey, cv2.HOUGH_GRADIENT, dp=1, minDist=height * RETICLE_RADIUS[1], param1=RETICLE_EDGES, param2=RETICLE_VOTES,
                             minRadius=round(height * RETICLE_RADIUS[0]), maxRadius=round(height * RETICLE_RADIUS[1]))
    stroke = max(1, round(height * RETICLE_STROKE))
    rings = [] if rings is None else [ring for ring in rings[0] if drawn_white(patch, ring, stroke)]
    if len(rings) != 1:
        return None
    return RETICLE_BAND[0] + float(rings[0][0]) / width


def aimed_at(reticle, xs):
    """Say which enemy a reticle sits over, by the HP number it lines up with.

    The number stands within `HEALTH_NUMBER` right of the enemy's marker: measured about 0.07 for most enemies and 0.10 for a boss's
    wider bar.

    Args:
        reticle: The ring's x, from `reticle_x`.
        xs: Where each enemy's marker stands, as `Foe.x` holds it.

    Returns:
        The x of that enemy, the nearest when two would do, or None when the ring is over none of them.
    """
    middle = (HEALTH_NUMBER[0] + HEALTH_NUMBER[2]) / 2
    under = [x for x in xs if x + HEALTH_NUMBER[0] <= reticle <= x + HEALTH_NUMBER[2]]
    return min(under, key=lambda x: abs(reticle - x - middle), default=None)


def drawn_white(patch, ring, stroke):
    """Say whether a ring Hough found is drawn in white along most of its length, as the reticle's outer ring is.

    Args:
        patch: The pixels it was found in, in BGR.
        ring: Its centre across and down the patch and its radius, in pixels.
        stroke: How far from the ring a white pixel still counts, in pixels.

    Returns:
        True when enough of its angles have a white pixel that close.
    """
    centre_x, centre_y, radius = ring
    hsv = hsv_of(patch)
    white = (hsv[..., 2] >= RETICLE_WHITE_VALUE) & (hsv[..., 1] <= RETICLE_WHITE_SATURATION)
    height, width = white.shape
    angles = np.linspace(0, 2 * np.pi, RETICLE_ANGLES, endpoint=False)[:, None]
    reach = radius + np.arange(-stroke, stroke + 1)[None, :]
    columns = np.clip(np.round(centre_x + reach * np.cos(angles)).astype(int), 0, width - 1)
    rows = np.clip(np.round(centre_y + reach * np.sin(angles)).astype(int), 0, height - 1)
    return float(white[rows, columns].any(axis=1).mean()) >= RETICLE_WHITE_ENOUGH
