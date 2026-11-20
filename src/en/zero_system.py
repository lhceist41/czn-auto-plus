"""Pick, reroll and merge Zero System Codices until one fits the chosen Chaos, season, save limit and modifier blacklist.

Upstream rerolls a Codex for its Save Data Storage Limit alone and always pays orbs for Chaos Merge. It never reads the Chaos,
the season or the modifiers, and on Codex Obtained `handle_confirm` presses Confirm before its own card picker ever runs.
"""

import re
import time
from difflib import SequenceMatcher
from typing import NamedTuple

from ok import Logger

from src.en.game_data import CHAOS_SEASON, CODEX_CHAOS, SEASONS
from src.en.handlers import insert_before, loaded, register, replace
from src.en.quality import fold
from src.en.reobserve import DEFAULT_BLACKLIST, MODIFIER_BLACKLIST, REDRAW_SECONDS, SAVE_LIMIT, SAVE_LIMIT_KEY, modifiers_in
from src.en.screen import in_region, lines_in, text_in_region

logger = Logger.get_logger(__name__)

# This fork's settings, with English keys since upstream ships neither.
CODEX = "Codex"
CODEX_SEASON = "Codex Season"
CODEX_MERGE = "Codex Merge"
MAX_MERGES = "Max Merges per Codex"
# The first choice of `Codex` and of `Codex Season`, which takes whatever the slots offer.
ANY = "Any"
CODEX_OPTIONS = [ANY, *CODEX_CHAOS]
SEASON_OPTIONS = [ANY, *SEASONS]
NORMAL_MERGE = "Normal Merge"
CHAOS_MERGE = "Chaos Merge"
NEVER_MERGE = "Never"
MERGE_OPTIONS = [NORMAL_MERGE, CHAOS_MERGE, NEVER_MERGE]
DEFAULT_MAX_MERGES = 3

# A Chaos or season name read off the screen counts as this one at this similarity, so "Theater of llusions" still matches.
NAME_MATCH = 0.8
# The card drops "The" from a Chaos name and the UI drops "A" from "A Promise Upon the Snow".
ARTICLE = re.compile(r"^\W*(?:the|a)\s+", re.I)
# A hunt untouched this long was abandoned, so its merge count starts again.
STALE_SECONDS = 300

# Select Codex: the caption under the title, the three slots, the reroll icon, and the shown Codex's panel.
SELECT_CAPTION = "Select Codex"
SELECT_CAPTION_REGION = (0.03, 0.20, 0.25, 0.29)
SLOTS = ((0.089, 0.356), (0.089, 0.541), (0.089, 0.727))
REROLL = (0.968, 0.153)
SELECT_TITLE = (0.68, 0.15, 0.90, 0.25)
SELECT_BODY = (0.68, 0.30, 0.99, 0.86)

# Merge Codices: the title, the Chaos list, the season strip, and the chosen Chaos and season over the info panel.
MERGE_CAPTION = "Merge Codices"
MERGE_CAPTION_REGION = (0.05, 0.01, 0.30, 0.09)
BACK = (0.042, 0.046)
CHAOS_LIST = (0.01, 0.08, 0.26, 0.86)
MERGE_NAME = (0.55, 0.36, 0.95, 0.43)
MERGE_SEASON = (0.55, 0.44, 0.85, 0.49)
# The strip opens with a no-season icon, then one per season oldest first. A Chaos tied to one season shows only that icon.
SEASON_ICON_X = 0.298
SEASON_ICON_TOP = 0.289
SEASON_ICON_STEP = 0.1275
MAX_LIST_SCROLLS = 6
MAX_SEASON_TAPS = 2

# Codex Obtained: the title, each card's column, its title and body bands, and Confirm.
OBTAINED_CAPTIONS = ("Codex Obtained", "获得法典")
OBTAINED_CAPTION_REGION = (0.313, 0.010, 0.670, 0.193)
CARD_COLUMNS = ((0.055, 0.32), (0.367, 0.632), (0.68, 0.945))
CARD_TITLE = (0.22, 0.32)
CARD_BODY = (0.33, 0.85)
CONFIRM = (0.881, 0.923)

# Both merge screens carry the merge buttons on one row, their prices beside them. The "Chaos Merge" info label sits above it.
BUTTON_ROW = (0.0, 0.895, 1.0, 0.96)
# Orbs then Credits, the last two amounts in the top bar.
TOP_BAR = (0.55, 0.0, 0.95, 0.09)
AMOUNT = re.compile(r"([\d,.]+)\s*([km]?)", re.I)
# How far a cut-off modifier list is scrolled to show its last lines.
SCROLL_NOTCHES = 3

STATE = "zero_system_hunt"

_patched = False


class Codex(NamedTuple):
    """One Codex as read off the screen, and what is wrong with it."""

    chaos: str | None  # Its Chaos from `CODEX_CHAOS`, or None when the title did not read as one.
    limit: int  # Its Save Data Storage Limit, 0 when unread.
    reasons: list  # One line per check it fails, empty when it fits.


def plain(text):
    """Fold a name for comparison the way `quality.fold` does, without a leading article.

    Args:
        text: A name, from the screen or from `game_data`.

    Returns:
        The folded name.
    """
    return fold(ARTICLE.sub("", text))


def closest(text, names):
    """Match text read off the screen to the name it most likely is.

    Args:
        text: The OCR text, wrapped lines already joined.
        names: The names it could be.

    Returns:
        The best name at `NAME_MATCH` or better, or None.
    """
    folded = plain(text)
    if not folded:
        return None
    score, name = max((SequenceMatcher(None, folded, plain(name)).ratio(), name) for name in names)
    return name if score >= NAME_MATCH else None


def amount(text):
    """Read a price or a held amount, with "4780K" as 4,780,000.

    Args:
        text: The OCR text of one box.

    Returns:
        The amount, or None when the box is not one.
    """
    match = AMOUNT.fullmatch(text.strip())
    if not match or not any(char.isdigit() for char in match.group(1)):
        return None
    return int(float(match.group(1).replace(",", "")) * {"": 1, "k": 1000, "m": 1000000}[match.group(2).casefold()])


def seasons_for(chaos):
    """List the `Codex Season` choices a Chaos can come with: every season for one of the first five, otherwise only its own.

    Args:
        chaos: A Chaos from `CODEX_CHAOS`, `ANY`, or None when the screen did not read as one.

    Returns:
        `ANY`, then the seasons it can carry.
    """
    tied = CHAOS_SEASON.get(chaos)
    return [ANY, tied] if tied else SEASON_OPTIONS


def hunt_of(task):
    """Give the Codex hunt in progress, starting a fresh one when the last was finished or abandoned.

    Args:
        task: The running task, which carries the hunt between screens.

    Returns:
        A dict of `slot` (the slot last tapped), `slots` (slot to `Codex`), `merges`, `broke`, `scrolls`, `season_taps`,
        `noted` and `at` (when it was last touched).
    """
    hunt = getattr(task, STATE, None)
    if hunt is None or time.time() - hunt["at"] > STALE_SECONDS:
        hunt = {"slot": None, "slots": {}, "merges": 0, "broke": False, "scrolls": 0, "season_taps": 0, "noted": set(), "at": 0}
        setattr(task, STATE, hunt)
    hunt["at"] = time.time()
    return hunt


def end_hunt(task):
    """Forget the hunt once its Codex is entered.

    Args:
        task: The running task.
    """
    setattr(task, STATE, None)


def merge_settings(task, utils_chaos):
    """Read what a merge pays with and how many one hunt may spend.

    Args:
        task: The running task.
        utils_chaos: The loaded `utils_chaos` module, for its config reader.

    Returns:
        The `Codex Merge` choice and the `Max Merges per Codex` cap.
    """
    return utils_chaos._get_config_value(task, CODEX_MERGE, NORMAL_MERGE), int(utils_chaos._get_config_value(task, MAX_MERGES, DEFAULT_MAX_MERGES))


def merges_left(task, hunt, utils_chaos):
    """Say whether the settings still allow another merge.

    Args:
        task: The running task.
        hunt: The hunt from `hunt_of`.
        utils_chaos: The loaded `utils_chaos` module, for its config reader.

    Returns:
        True when another merge may be paid for.
    """
    mode, cap = merge_settings(task, utils_chaos)
    return mode != NEVER_MERGE and not hunt["broke"] and hunt["merges"] < cap


def judge(task, chaos, season, limit, modifiers, hunt, utils_chaos):
    """Check one Codex against the settings.

    Args:
        task: The running task.
        chaos: Its Chaos from `closest`, or None.
        season: Its season from `closest`, or None when it carries none.
        limit: Its Save Data Storage Limit, 0 when unread.
        modifiers: Its modifier families from `modifiers_in`.
        hunt: The hunt from `hunt_of`, which notes a season check dropped for a Chaos so it is logged once.
        utils_chaos: The loaded `utils_chaos` module.

    Returns:
        The `Codex`.
    """
    reasons = []
    wanted = utils_chaos._get_config_value(task, CODEX, ANY)
    if wanted != ANY and chaos != wanted:
        reasons.append(f"{chaos or 'an unread Chaos'} is not {wanted}")
    wanted_season = utils_chaos._get_config_value(task, CODEX_SEASON, ANY)
    if wanted_season != ANY and season != wanted_season:
        if wanted_season in seasons_for(chaos):
            reasons.append(f"season {season or 'none'} is not {wanted_season}")
        elif chaos not in hunt["noted"]:
            hunt["noted"].add(chaos)
            task.log_info(f"{chaos} only comes with {CHAOS_SEASON[chaos]}, so {CODEX_SEASON} {wanted_season} is not asked of it")
    required = int(utils_chaos._get_config_value(task, SAVE_LIMIT_KEY, 120))
    if limit < required:
        reasons.append(f"Save Data Storage Limit {limit or 'unread'} is below {required}")
    blacklist = utils_chaos._get_config_value(task, MODIFIER_BLACKLIST, DEFAULT_BLACKLIST)
    banned = [name for name in modifiers if name in blacklist]
    if banned:
        reasons.append(f"blacklisted {', '.join(banned)}")
    return Codex(chaos, limit, reasons)


def read_codex(task, title, body, hunt, utils_chaos, utils):
    """Read and check the Codex on one panel or card, scrolling its modifier list once when everything else fits.

    The panel and the cards cut their modifier list off, so a Codex is only passed once its hidden lines are read too.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        title: The `(left, top, right, bottom)` region of its name, which may wrap over two lines.
        body: The region of its season, save limit and modifiers.
        hunt: The hunt from `hunt_of`.
        utils_chaos: The loaded `utils_chaos` module.
        utils: The loaded `utils` module, for its scroll helper.

    Returns:
        The `Codex`.
    """
    names = [box.name for box in task.all_texts if in_region(box, body, task.width, task.height)]
    chaos = closest(lines_in(task, title), CODEX_CHAOS)
    season = next(filter(None, (closest(name, SEASONS) for name in names)), None)
    limit = SAVE_LIMIT.search(lines_in(task, body))
    limit = int(limit.group(1)) if limit else 0
    modifiers = modifiers_in(names)
    codex = judge(task, chaos, season, limit, modifiers, hunt, utils_chaos)
    if codex.reasons:
        return codex
    utils._scroll_card_page(task, (body[0] + body[2]) / 2, (body[1] + body[3]) / 2, -SCROLL_NOTCHES, "Zero System")
    hidden = modifiers_in(box.name for box in task.ocr() if in_region(box, body, task.width, task.height))
    return judge(task, chaos, season, limit, modifiers + hidden, hunt, utils_chaos)


def rank(codex):
    """Order a Codex by how badly it fits: fewer failed checks first, then a higher save limit.

    Args:
        codex: The `Codex`.

    Returns:
        A sort key, lowest for the best fit.
    """
    return len(codex.reasons), -codex.limit


def best(codices):
    """Pick the key of the best-fitting Codex by `rank`.

    Args:
        codices: A dict of key to `Codex`.

    Returns:
        The best key.
    """
    return min(codices, key=lambda key: rank(codices[key]))


def describe(codex):
    """Name a Codex and what is wrong with it, for the log.

    Args:
        codex: The `Codex`.
    """
    return f"{codex.chaos or 'unread Chaos'} at {codex.limit or 'unread'}pt ({'; '.join(codex.reasons) or 'fits'})"


def merge(task, hunt, utils_chaos):
    """Press the configured merge button and count it, unless its price is more than is held.

    Args:
        task: The running task, on Merge Codices or Codex Obtained.
        hunt: The hunt from `hunt_of`.
        utils_chaos: The loaded `utils_chaos` module.

    Returns:
        True when the button was pressed.
    """
    mode, cap = merge_settings(task, utils_chaos)
    row = [box for box in task.all_texts if in_region(box, BUTTON_ROW, task.width, task.height)]
    button = next((box for box in row if plain(box.name) == plain(mode)), None)
    if button is None:
        return False
    # (x, amount) pairs, so the price is the nearest amount right of the button and the top bar reads left to right.
    prices = sorted((box.x, value) for box in row if box.x > button.x and (value := amount(box.name)) is not None)
    held = sorted((box.x, value) for box in task.all_texts if in_region(box, TOP_BAR, task.width, task.height) and (value := amount(box.name)) is not None)
    price = prices[0][1] if prices else None
    have = held[-1 if mode == NORMAL_MERGE else -2][1] if len(held) >= 2 else None
    if price is not None and have is not None and have < price:
        task.log_info(f"{mode} costs {price} but only {have} is held, so no more merges")
        hunt["broke"] = True
        return False
    hunt["merges"] += 1
    task.log_info(f"{mode} {hunt['merges']} of {cap} for {price}")
    task.click_box(button)
    task.sleep(REDRAW_SECONDS)
    return True


def pick_chaos(task, wanted, hunt, utils):
    """Tap the wanted Chaos in the Merge Codices list, or scroll the list toward it.

    Args:
        task: The running task, on Merge Codices.
        wanted: The Chaos to merge, from `CODEX_CHAOS`.
        hunt: The hunt from `hunt_of`, which counts the scrolls.
        utils: The loaded `utils` module, for its scroll helper.
    """
    rows = [(box, name) for box in task.all_texts if in_region(box, CHAOS_LIST, task.width, task.height) and (name := closest(box.name, CODEX_CHAOS))]
    row = next((box for box, name in rows if name == wanted), None)
    if row is not None:
        task.log_info(f"Choosing {wanted} to merge")
        task.click_box(row)
        return
    # Up when every row on screen comes after the wanted one in the list.
    position = CODEX_CHAOS.index(wanted)
    up = rows and all(CODEX_CHAOS.index(name) > position for _, name in rows)
    hunt["scrolls"] += 1
    task.log_info(f"Scrolling the Chaos list {'up' if up else 'down'} for {wanted}")
    utils._scroll_card_page(task, 0.13, 0.5, SCROLL_NOTCHES if up else -SCROLL_NOTCHES, MERGE_CAPTION)


def select_handler(utils_chaos, utils):
    """Build the Select Codex handler, which checks every slot, rerolls the worst, and settles for the best at the cap.

    Declining leaves the page to `handle_enter`, which enters the shown Codex.

    Args:
        utils_chaos: The loaded `utils_chaos` module.
        utils: The loaded `utils` module.

    Returns:
        The handler.
    """
    def handle_select_codex(task):
        if text_in_region(task, SELECT_CAPTION, SELECT_CAPTION_REGION) is None:
            return False
        hunt = hunt_of(task)
        shown = read_codex(task, SELECT_TITLE, SELECT_BODY, hunt, utils_chaos, utils)
        if not shown.reasons:
            task.log_info(f"Entering {describe(shown)}")
            end_hunt(task)
            return False
        slots = hunt["slots"]
        if hunt["slot"] is not None:
            slots[hunt["slot"]] = shown
        unchecked = [slot for slot in range(len(SLOTS)) if slot not in slots]
        merging = merges_left(task, hunt, utils_chaos)
        if unchecked:
            target = unchecked[0]
        elif merging:
            target = max(slots, key=lambda slot: rank(slots[slot]))
        else:
            target = best(slots)
        # Only an already checked slot can be the one on screen, so these two run once every slot is read.
        if target == hunt["slot"] and merging:
            task.log_info(f"Remerging slot {target + 1}: {describe(shown)}")
            del slots[target]
            hunt["scrolls"] = hunt["season_taps"] = 0
            utils_chaos._move_and_click(task, *REROLL)
            task.sleep(REDRAW_SECONDS)
            return True
        if target == hunt["slot"]:
            task.log_info(f"Out of merges, entering the best Codex: {describe(shown)}")
            end_hunt(task)
            return False
        hunt["slot"] = target
        utils_chaos._move_and_click(task, *SLOTS[target])
        task.sleep(REDRAW_SECONDS)
        return True

    return handle_select_codex


def merge_handler(utils_chaos, utils):
    """Build the Merge Codices handler, which picks the `Codex` and the `Codex Season`, then merges.

    Args:
        utils_chaos: The loaded `utils_chaos` module.
        utils: The loaded `utils` module.

    Returns:
        The handler.
    """
    def handle_merge_codices(task):
        if text_in_region(task, MERGE_CAPTION, MERGE_CAPTION_REGION) is None:
            return False
        hunt = hunt_of(task)
        if not merges_left(task, hunt, utils_chaos):
            task.log_info("No merges left, back to Select Codex")
            utils_chaos._move_and_click(task, *BACK)
            task.sleep(REDRAW_SECONDS)
            return True
        wanted = utils_chaos._get_config_value(task, CODEX, ANY)
        shown = closest(lines_in(task, MERGE_NAME), CODEX_CHAOS)
        if wanted != ANY and shown != wanted and hunt["scrolls"] <= MAX_LIST_SCROLLS:
            pick_chaos(task, wanted, hunt, utils)
            task.sleep(REDRAW_SECONDS)
            return True
        season = utils_chaos._get_config_value(task, CODEX_SEASON, ANY)
        if season != ANY and shown not in CHAOS_SEASON and hunt["season_taps"] < MAX_SEASON_TAPS:
            if closest(lines_in(task, MERGE_SEASON), SEASONS) != season:
                hunt["season_taps"] += 1
                task.log_info(f"Choosing {season} to merge")
                utils_chaos._move_and_click(task, SEASON_ICON_X, SEASON_ICON_TOP + SEASON_ICON_STEP * SEASONS.index(season))
                task.sleep(REDRAW_SECONDS)
                return True
        # Declining an unread button waits for the next frame. Running short sends the next frame back to Select Codex.
        return merge(task, hunt, utils_chaos)

    return handle_merge_codices


def obtained_handler(utils_chaos, utils):
    """Build the Codex Obtained handler, which takes a fitting card, merges again, or settles for the best card.

    Args:
        utils_chaos: The loaded `utils_chaos` module.
        utils: The loaded `utils` module.

    Returns:
        The handler.
    """
    def handle_codex_obtained(task):
        if not any(text_in_region(task, caption, OBTAINED_CAPTION_REGION) for caption in OBTAINED_CAPTIONS):
            return False
        hunt = hunt_of(task)
        cards = {}
        for index, (left, right) in enumerate(CARD_COLUMNS):
            cards[index] = read_codex(task, (left, CARD_TITLE[0], right, CARD_TITLE[1]), (left, CARD_BODY[0], right, CARD_BODY[1]),
                                      hunt, utils_chaos, utils)
            if not cards[index].reasons:
                break
        pick = best(cards)
        if cards[pick].reasons and merges_left(task, hunt, utils_chaos):
            # Never declined while merges are left: `handle_confirm` comes next and would confirm whichever card is highlighted.
            if merge(task, hunt, utils_chaos) or not hunt["broke"]:
                return True
        task.log_info(f"Taking Codex {pick + 1}: {describe(cards[pick])}")
        left, right = CARD_COLUMNS[pick]
        utils_chaos._move_and_click(task, (left + right) / 2, (CARD_BODY[0] + CARD_BODY[1]) / 2)
        task.sleep(1)
        utils_chaos._move_and_click(task, *CONFIRM)
        task.sleep(REDRAW_SECONDS)
        return True

    return handle_codex_obtained


def handle_discovery_select(task):
    """Stand in for upstream's Codex Obtained picker, which `handle_codex_obtained` replaces from ahead of `handle_confirm`.

    Args:
        task: The running task.

    Returns:
        False, always.
    """
    return False


def install(utils_chaos, utils):
    """Swap upstream's Zero System handlers for these.

    Args:
        utils_chaos: The loaded `utils_chaos` module, or None when it is not importable yet.
        utils: The loaded `utils` module, or None.
    """
    if utils_chaos is None or utils is None:
        return
    replace("handle_zero_system_initial_page", select_handler(utils_chaos, utils))
    replace("handle_chaos_craft", merge_handler(utils_chaos, utils))
    replace("handle_discovery_select", handle_discovery_select)
    insert_before("handle_confirm", obtained_handler(utils_chaos, utils), only=("utils_chaos",))


def apply():
    """Hunt Zero System Codices by Chaos, season, save limit and modifiers."""
    global _patched
    if _patched:
        return
    register(lambda: install(loaded("utils_chaos"), loaded("utils")))
    _patched = True
