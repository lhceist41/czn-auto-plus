"""Read the Combatant screens Daily's invest step works on, decide what may be spent, and write what each goal unit is short of.

Nothing here presses anything: Daily's invest handlers read a screen through these functions and press through Daily's
own guard. Every spend panel draws one button in its bottom-right corner, and the game writes on it whether the spend
can go ahead: `Promotions`, `Level Up` or `Activate` when it can, and something else (`Obtain by Merging`, `Replenish
Materials`, `Obtain through dismantling`, `Promotion required`, `Clear the Promotion Mission [...]`) when it cannot. So a
spend is allowed only when that caption equals the go word, read on the same pass as the counter, the cost and the Units
in the header, and every other caption, known or not, counts as short.

A screen is known only by its whole signature: each caption in its own region and every number parsed. Anything less is
no screen at all, and Daily presses nothing on it.

Positions are screen fractions read off the Global client's captures at 1920x1080.
"""

import json
import os
import re
from collections import namedtuple

from src.en.game_battle import COMBATANT_ATTRIBUTE
from src.en.game_quality import COMBATANT_CLASS
from src.en.screen import centre_of, in_region
from src.en.spend_guard import folded

# What each goal unit is still short of, written whole at the end of every invest step with a goal list. `data/` is in `.gitignore`.
GOALS_FILE = os.path.join("data", "farm_goals.json")

# Every Details, panel and node screen writes what it is at the top left: `Details`, `Growth` over a Partner's panels and
# `Potential` over a node panel, OCR adding a stray `i`, `?` or `C` after it.
HEADER_REGION = (0.06, 0.02, 0.22, 0.07)
# The Units the account holds, `2370K`, or `888,680` under a million, at (0.831-0.840, 0.048-0.049) on every spend panel.
# `62` and `□` sit left of it.
UNITS_REGION = (0.80, 0.03, 0.88, 0.07)
UNITS = re.compile(r"(\d+)[kK]|\d{1,3}(?:,\d{3})+|\d+")
# A panel's title at (0.851-0.853, 0.119-0.122), and its button at (0.859-0.860, 0.919-0.922).
TITLE_REGION = (0.78, 0.09, 0.93, 0.15)
CORNER_REGION = (0.78, 0.89, 0.94, 0.95)
# Promotion and node panels: the material counter `have/need` at (0.757-0.759, 0.791) and the Units cost at (0.944-0.950, 0.842).
COUNTER_REGION = (0.72, 0.77, 0.80, 0.81)
COST_REGION = (0.90, 0.82, 0.99, 0.86)
# A Promotion panel's level now and after, `Lv.20/20` at (0.785, 0.259) and `Lv.20/30` at (0.922, 0.259).
LEVEL_NOW_REGION = (0.74, 0.24, 0.83, 0.28)
LEVEL_NEXT_REGION = (0.88, 0.24, 0.96, 0.28)
# A Level Up panel: the preview `Lv.20` or `Lv.20+10` at (0.750-0.768, 0.206), the three Combat Memory or Support Data
# counters at y 0.718, the cost at (0.948-0.967, 0.768) and Auto Register at (0.852, 0.835).
PREVIEW_REGION = (0.72, 0.19, 0.80, 0.23)
MEMORY_REGION = (0.72, 0.70, 0.90, 0.74)
LEVEL_COST_REGION = (0.90, 0.75, 0.99, 0.79)
AUTO_REGISTER_REGION = (0.80, 0.81, 0.90, 0.86)
# A Partner's panels draw their own tabs down the left: `View Details` at (0.078, 0.257).
VIEW_DETAILS_REGION = (0.03, 0.24, 0.13, 0.28)
# The Stats tab: the combatant's name at (0.767, 0.164), `Lv.20/20` at (0.768, 0.260), the `Stats` heading at (0.753, 0.332).
NAME_REGION = (0.70, 0.14, 0.84, 0.19)
STATS_LEVEL_REGION = (0.72, 0.24, 0.82, 0.28)
STATS_HEADING_REGION = (0.72, 0.31, 0.79, 0.35)
# The Details tabs down the left, the same on every tab: Stats (0.121, 0.258), Partners (0.133, 0.444), Potential (0.134, 0.631).
STATS_TAB_REGION = (0.08, 0.23, 0.17, 0.28)
PARTNERS_TAB_REGION = (0.08, 0.42, 0.18, 0.47)
POTENTIAL_TAB_REGION = (0.08, 0.61, 0.18, 0.65)
# The Partners tab: the Partner's name at (0.798-0.807, 0.117-0.119), `Lv.10/10` at (0.767, 0.216), `Partner Passives` at
# (0.822, 0.540) and `强化` at (0.804, 0.924), with `Change` beside it at (0.938, 0.925).
PARTNER_NAME_REGION = (0.74, 0.10, 0.88, 0.14)
PARTNER_LEVEL_REGION = (0.72, 0.20, 0.82, 0.235)
PASSIVES_REGION = (0.77, 0.52, 0.88, 0.56)
UPGRADE_REGION = (0.77, 0.90, 0.84, 0.95)
# A Combatant with no Partner shows only `Assign Partner` on that tab, at (0.557, 0.550).
ASSIGN_PARTNER_REGION = (0.45, 0.52, 0.66, 0.58)
# The Potential map: node 02's counter at (0.440-0.442, 0.887); node 01 draws none.
NODE_02_COUNTER_REGION = (0.40, 0.86, 0.48, 0.91)
# A node panel: its node's name at (0.853, 0.354) and, for a node with levels, `Lv.N` at (0.853, 0.296).
NODE_NAME_REGION = (0.78, 0.33, 0.93, 0.38)
NODE_LEVEL_REGION = (0.80, 0.28, 0.90, 0.31)
# Its description under the name, at (0.799-0.838, 0.417-0.482).
NODE_TEXT_REGION = (0.74, 0.39, 0.95, 0.50)
# The Combatant List: its header at (0.164, 0.044), `Preset` at (0.936, 0.938), the names along y 0.483-0.487.
LIST_HEADER_REGION = (0.10, 0.02, 0.24, 0.07)
PRESET_REGION = (0.88, 0.91, 0.98, 0.96)
LIST_NAMES_REGION = (0.10, 0.46, 1.0, 0.51)
# A name reads 0.03-0.05 right of its card's middle, so the tap goes a little left of it, on the portrait above.
CARD_LEFT_OF_NAME = 0.03
CARD_Y = 0.33
# A result card: its title at (0.561-0.576, 0.347-0.350) or `Return item` at (0.501, 0.378), and the close caption at y 0.935-0.938.
CARD_TITLE_REGION = (0.42, 0.32, 0.65, 0.40)
CARD_MAX_LEVEL_REGION = (0.50, 0.41, 0.65, 0.46)
CARD_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.965))

LEVEL_PAIR = re.compile(r"lv\.?(\d+)/(\d+)")
PREVIEW = re.compile(r"lv\.?(\d+)(?:\+(\d+))?")
NODE_LEVEL = re.compile(r"lv\.?(\d+)")
COUNTER = re.compile(r"(\d+)/(\d+)")
COST = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")

# The go word each spend panel's button must equal, folded.
PROMOTE_WORD = "promotions"
LEVEL_UP_WORD = "levelup"
ACTIVATE_WORD = "activate"
UPGRADE_WORD = "强化"
AUTO_REGISTER_WORD = "autoregister"
# The two nodes v1 opens, by the name their panel writes. Node 01's panel is titled `Combatant Epiphany`.
NODE_NAMES = {"01": "epiphanybonus", "02": "basiccardupgrade"}

# What no invest press may land on, beside Daily's own refusals: a box containing one of these stems, or equal to one of
# these words, folded. A backstop only: every press already needs its caption to equal the one it wants.
REFUSED_STEMS = ("merg", "obtain", "replenish", "dismant", "mission", "promotionrequired", "editdata", "recharg", "assign")
REFUSED_WORDS = ("change", "remove", "cards", "savedata", "memoryfragments", "egomanifestation", "growthguide", "viewdetails",
                 "preset", "synchronization")
# Captions that wait on something farming cannot bring, so their line names no stage.
GATE_STEMS = ("mission", "promotionrequired")

# Each Partner's class, which names the stage its certificates drop from. The game data carries no Partner table.
PARTNER_CLASS = {"marianne": "Striker", "rosaria": "Ranger", "yvonne": "Controller"}

PROMOTION, LEVEL = "promotion", "level"
PARTNER_PROMOTION, PARTNER_LEVEL = "partner promotion", "partner level"
NODE_01, NODE_02 = "potential node 01", "potential node 02"

Stats = namedtuple("Stats", "name level cap caption caption_box")
Panel = namedtuple("Panel", "owner level cap next have need cost units caption caption_box")
LevelPanel = namedtuple("LevelPanel", "owner level gain cost units caption caption_box register_box")
Partners = namedtuple("Partners", "name level cap upgrade_box")
NodePanel = namedtuple("NodePanel", "name level have need cost units caption caption_box")
DoneNode = namedtuple("DoneNode", "name")
Card = namedtuple("Card", "kind caption_box")
Goals = namedtuple("Goals", "units unknown")


def boxes_in(task, region):
    """Give the OCR boxes whose centre lies in a region.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        region: A `(left, top, right, bottom)` tuple in screen fractions.

    Returns:
        The boxes, in OCR order.
    """
    return [box for box in getattr(task, "all_texts", None) or [] if in_region(box, region, task.width, task.height)]


def equal_in(task, word, region):
    """Find the one box in a region whose folded text equals a word, never a box merely containing it.

    Args:
        task: The running task.
        word: The folded word.
        region: Where it must read.

    Returns:
        The box, or None.
    """
    return next((box for box in boxes_in(task, region) if folded(box.name) == word), None)


def only_match(task, pattern, region):
    """Parse the one box in a region that matches a pattern whole.

    Args:
        task: The running task.
        pattern: A compiled pattern, matched against the folded text.
        region: Where it must read.

    Returns:
        The match, or None when no box or more than one box matches.
    """
    found = [match for match in (pattern.fullmatch(folded(box.name)) for box in boxes_in(task, region)) if match]
    return found[0] if len(found) == 1 else None


def header(task):
    """Say what the top-left header calls the screen: "details", "growth", "potential", or None."""
    for box in boxes_in(task, HEADER_REGION):
        text = folded(box.name)
        for kind in ("details", "growth", "potential"):
            if text.startswith(kind):
                return kind
    return None


def units_held(task):
    """Read the Units in the header, `2370K` as 2,370,000 and `888,680` or `888680` as written; any other form is no read.

    Matched on the text as OCR read it, unfolded, so a neighbour run into the header, `62 2656K`, is no read rather
    than 622,656,000.
    """
    found = [match for match in (UNITS.fullmatch(box.name.strip()) for box in boxes_in(task, UNITS_REGION)) if match]
    if len(found) != 1:
        return None
    return int(found[0].group(1)) * 1000 if found[0].group(1) else int(found[0].group(0).replace(",", ""))


def cost_in(task, region):
    """Read a Units cost such as `70,000` or `0` in its region, or None."""
    found = only_match(task, COST, region)
    return int(found.group(0).replace(",", "")) if found else None


def counter(task):
    """Read a panel's material counter `have/need` as two ints, or None."""
    found = only_match(task, COUNTER, COUNTER_REGION)
    return (int(found.group(1)), int(found.group(2))) if found else None


def corner_box(task):
    """Give the one box read in the bottom-right button's place, or None when none or several read there."""
    found = boxes_in(task, CORNER_REGION)
    return found[0] if len(found) == 1 else None


def stats_screen(task):
    """Read the Details screen's Stats tab: header, name, level pair, `Stats` heading and the bottom-right caption.

    Returns:
        A `Stats`, or None when any part does not read.
    """
    if header(task) != "details" or equal_in(task, "stats", STATS_HEADING_REGION) is None:
        return None
    names = [box for box in boxes_in(task, NAME_REGION) if re.search(r"[a-z]", folded(box.name))]
    level = only_match(task, LEVEL_PAIR, STATS_LEVEL_REGION)
    caption = corner_box(task)
    if len(names) != 1 or level is None or caption is None:
        return None
    return Stats(names[0].name.strip(), int(level.group(1)), int(level.group(2)), folded(caption.name), caption)


def promotion_panel(task):
    """Read a Promotions panel, a combatant's under `Details` or a Partner's under `Growth`, every number parsed.

    Returns:
        A `Panel`, or None when any part does not read.
    """
    owner = panel_owner(task)
    if owner is None or equal_in(task, PROMOTE_WORD, TITLE_REGION) is None:
        return None
    now = only_match(task, LEVEL_PAIR, LEVEL_NOW_REGION)
    after = only_match(task, LEVEL_PAIR, LEVEL_NEXT_REGION)
    have_need, cost, units, caption = counter(task), cost_in(task, COST_REGION), units_held(task), corner_box(task)
    if None in (now, after, have_need, cost, units, caption):
        return None
    return Panel(owner, int(now.group(1)), int(now.group(2)), int(after.group(2)), *have_need, cost, units, folded(caption.name), caption)


def panel_owner(task):
    """Say whose upgrade panel shows: "combatant" under `Details`, "partner" under `Growth` with its `View Details` tab, or None."""
    kind = header(task)
    partner_tab = equal_in(task, "viewdetails", VIEW_DETAILS_REGION) is not None
    if kind == "details" and not partner_tab:
        return "combatant"
    if kind == "growth" and partner_tab:
        return "partner"
    return None


def level_panel(task):
    """Read a Level Up panel. Its title reads `Level Up`; on a Partner's panel so does a tab on the left, which never counts.

    The cost is read only once Auto Register has filled the slots: before that the panel may draw none.

    Returns:
        A `LevelPanel`, its cost None while unread, or None when any other part does not read.
    """
    owner = panel_owner(task)
    if owner is None or equal_in(task, LEVEL_UP_WORD, TITLE_REGION) is None:
        return None
    preview = only_match(task, PREVIEW, PREVIEW_REGION)
    memories = [box for box in boxes_in(task, MEMORY_REGION) if COUNTER.fullmatch(folded(box.name))]
    register, caption, units = equal_in(task, AUTO_REGISTER_WORD, AUTO_REGISTER_REGION), corner_box(task), units_held(task)
    if preview is None or len(memories) != 3 or register is None or caption is None or units is None:
        return None
    gain = int(preview.group(2)) if preview.group(2) else 0
    return LevelPanel(owner, int(preview.group(1)), gain, cost_in(task, LEVEL_COST_REGION), units, folded(caption.name), caption, register)


def partners_tab(task):
    """Read the Details screen's Partners tab: the Partner's name, its level pair, `Partner Passives` and `强化`.

    Returns:
        A `Partners`, its upgrade box None when `强化` does not read alone (OCR has run it into `Change`), or None.
    """
    if header(task) != "details" or equal_in(task, "partnerpassives", PASSIVES_REGION) is None:
        return None
    names = [box for box in boxes_in(task, PARTNER_NAME_REGION) if re.search(r"[a-z]", folded(box.name))]
    level = only_match(task, LEVEL_PAIR, PARTNER_LEVEL_REGION)
    if len(names) != 1 or level is None:
        return None
    return Partners(names[0].name.strip(), int(level.group(1)), int(level.group(2)), equal_in(task, UPGRADE_WORD, UPGRADE_REGION))


def no_partner_tab(task):
    """Say whether the Details screen's Partners tab shows a Combatant with no Partner: its tab, `Assign Partner` and no Partner's captions."""
    if header(task) != "details" or equal_in(task, "partners", PARTNERS_TAB_REGION) is None:
        return False
    if equal_in(task, "assignpartner", ASSIGN_PARTNER_REGION) is None:
        return False
    return equal_in(task, "stats", STATS_HEADING_REGION) is None and equal_in(task, "partnerpassives", PASSIVES_REGION) is None


def potential_map(task):
    """Say whether the Details screen's Potential map shows: its tabs, node 02's counter, and none of Stats' or Partners' captions."""
    if header(task) != "details" or equal_in(task, "potential", POTENTIAL_TAB_REGION) is None:
        return False
    if equal_in(task, "partners", PARTNERS_TAB_REGION) is None or only_match(task, COUNTER, NODE_02_COUNTER_REGION) is None:
        return False
    return equal_in(task, "stats", STATS_HEADING_REGION) is None and equal_in(task, "partnerpassives", PASSIVES_REGION) is None


def node_02_full(task):
    """Say whether the Potential map's node 02 counter reads its last level, `10/10`."""
    found = only_match(task, COUNTER, NODE_02_COUNTER_REGION)
    return found is not None and int(found.group(1)) >= int(found.group(2)) > 0


def node_panel(task):
    """Read a Potential node panel under the `Potential` header: node name, counter, cost, Units and caption.

    Node 01 draws no level; node 02 draws `Lv.N`, read when it shows.

    Returns:
        A `NodePanel`, its level None when none reads, or None when any other part does not read.
    """
    if header(task) != "potential" or not boxes_in(task, TITLE_REGION):
        return None
    names = boxes_in(task, NODE_NAME_REGION)
    level = only_match(task, NODE_LEVEL, NODE_LEVEL_REGION)
    have_need, cost, units, caption = counter(task), cost_in(task, COST_REGION), units_held(task), corner_box(task)
    if len(names) != 1 or None in (have_need, cost, units, caption):
        return None
    return NodePanel(folded(names[0].name), int(level.group(1)) if level else None, *have_need, cost, units, folded(caption.name), caption)


def done_node(task):
    """Read a node panel with nothing left to buy: under the `Potential` header its title, name and description, and no counter, cost or button.

    An active node 01 shows this, as may a node at its last level.

    Returns:
        A `DoneNode` with the node's folded name, or None.
    """
    if header(task) != "potential" or not boxes_in(task, TITLE_REGION) or not boxes_in(task, NODE_TEXT_REGION):
        return None
    names = boxes_in(task, NODE_NAME_REGION)
    if len(names) != 1 or any(boxes_in(task, region) for region in (COUNTER_REGION, COST_REGION, CORNER_REGION)):
        return None
    return DoneNode(folded(names[0].name))


def result_card(task):
    """Read a card the game puts up after a spend: `Promotions` with `Max Level`, `Level Up`, `Return item` or `Potential`.

    Returns:
        A `Card` with its kind and close caption, or None.
    """
    caption = next((box for box in boxes_in(task, CARD_CAPTION[1]) if folded(box.name) == CARD_CAPTION[0]), None)
    if caption is None or boxes_in(task, TITLE_REGION) or boxes_in(task, HEADER_REGION):
        return None
    titles = [folded(box.name) for box in boxes_in(task, CARD_TITLE_REGION)]
    if PROMOTE_WORD in titles:
        return Card(PROMOTION, caption) if boxes_in(task, CARD_MAX_LEVEL_REGION) else None
    for word, kind in ((LEVEL_UP_WORD, LEVEL), ("returnitem", "return item"), ("potential", "potential")):
        if word in titles:
            return Card(kind, caption)
    return None


def combatant_list(task):
    """Say whether the Combatant List shows: its header and `Preset`."""
    return equal_in(task, "主战员列表", LIST_HEADER_REGION) is not None and equal_in(task, "preset", PRESET_REGION) is not None


def same_name(read, unit):
    """Say whether a name read off the Stats tab is the goal unit's, whole: no prefix and no near miss counts here."""
    return folded(read) == folded(unit)


def card_point(task, unit):
    """Find where to tap a goal unit's card on the Combatant List's visible row.

    A whole-name match wins. OCR has read Rei as `Re`, so a read of at least two letters that the name starts with counts
    too, only when it is the one such read; the Stats tab's whole-name check then confirms whose card it was.

    Args:
        task: The running task.
        unit: The goal unit's name.

    Returns:
        The point as `(x, y)` screen fractions, or None when the name is not on the row.
    """
    wanted = folded(unit)
    names = [box for box in boxes_in(task, LIST_NAMES_REGION) if re.fullmatch(r"[a-z][a-z ]*", folded(box.name))]
    whole = [box for box in names if folded(box.name) == wanted]
    start = [box for box in names if len(folded(box.name)) >= 2 and wanted.startswith(folded(box.name))]
    found = whole if whole else start
    if len(found) != 1:
        return None
    x, _ = centre_of(found[0], task.width, task.height)
    return x - CARD_LEFT_OF_NAME, CARD_Y


def refused(text):
    """Say whether a box reads as a control no invest press may land on, whatever it was asked to press.

    Args:
        text: The box's text.

    Returns:
        What gave it away, or None.
    """
    word = folded(text)
    stem = next((stem for stem in REFUSED_STEMS if stem in word), None)
    if stem:
        return stem
    return word if word in REFUSED_WORDS else None


def blocked(cost, units, floor):
    """Say why the Units forbid a spend: unread, or below the floor once paid.

    Args:
        cost: The spend's Units cost.
        units: The Units held.
        floor: The Units to keep.

    Returns:
        The reason, or None when the Units allow it.
    """
    if cost is None or units is None:
        return "the Units did not read"
    if units - cost < floor:
        return f"it would leave {units - cost:,} Units, under the {floor:,} to keep"
    return None


def promotion_go(panel, floor):
    """Decide whether a Promotions panel may be pressed: its button reads `Promotions`, the counter is met and the Units allow it.

    Args:
        panel: A `Panel`.
        floor: The Units to keep.

    Returns:
        None when it may, else why not.
    """
    if panel.caption != PROMOTE_WORD:
        return f"the button reads {panel.caption_box.name.strip()!r}"
    if panel.have < panel.need:
        return f"{panel.have}/{panel.need}"
    return blocked(panel.cost, panel.units, floor)


def node_go(node, floor):
    """Decide whether a node panel may be pressed: its button reads `Activate`, the counter is met and the Units allow it.

    Args:
        node: A `NodePanel`.
        floor: The Units to keep.

    Returns:
        None when it may, else why not.
    """
    if node.caption != ACTIVATE_WORD:
        return f"the button reads {node.caption_box.name.strip()!r}"
    if node.have < node.need:
        return f"{node.have}/{node.need}"
    return blocked(node.cost, node.units, floor)


def held_by_units(panel, reason):
    """Say whether a Combatant's Promotion panel was ready but for the Units: `Promotions` over a met counter, held back only by the floor or an unread header."""
    return reason is not None and panel.caption == PROMOTE_WORD and panel.have >= panel.need


def level_go(panel, floor):
    """Decide whether a Level Up panel may be pressed: Auto Register has given levels, the cost read and the Units allow it.

    Args:
        panel: A `LevelPanel`.
        floor: The Units to keep.

    Returns:
        None when it may, else why not.
    """
    if panel.caption != LEVEL_UP_WORD:
        return f"the button reads {panel.caption_box.name.strip()!r}"
    if panel.gain <= 0:
        return "Auto Register gave no levels"
    return blocked(panel.cost, panel.units, floor)


def is_gate(caption):
    """Say whether a button's caption waits on something farming cannot bring, such as a Promotion Mission."""
    return any(stem in caption for stem in GATE_STEMS) or caption.startswith("clear")


def stage_for(unit, action, partner=None, caption=""):
    """Name the Simulation stage that drops what a short action needs, or "" when none is known.

    Args:
        unit: The goal unit.
        action: One of the action names above.
        partner: The Partner's name, for a Partner action.
        caption: The folded button caption, since a gate names no stage.

    Returns:
        The stage name, as the Simulation list writes it, or "".
    """
    if is_gate(caption):
        return ""
    if action == PROMOTION and unit in COMBATANT_CLASS:
        return f"Combatant Promotion Materials - {COMBATANT_CLASS[unit].title()}"
    if action == PARTNER_PROMOTION and partner and folded(partner) in PARTNER_CLASS:
        return f"Partner Promotion Materials - {PARTNER_CLASS[folded(partner)]}"
    if action in (NODE_01, NODE_02) and unit in COMBATANT_ATTRIBUTE:
        return f"Potential Materials - {COMBATANT_ATTRIBUTE[unit]}"
    return ""


def goal_line(unit, action, have, need, units, caption, stage, read_at):
    """Shape one short action as the goal file holds it."""
    return {"unit": unit, "action": action, "have": have, "need": need, "units": units, "caption": caption, "stage": stage, "read_at": read_at}


def goal_units(setting):
    """Check the goal list against the game's combatants.

    Args:
        setting: The goal list as saved, a list of names, or anything else for none.

    Returns:
        A `Goals`: the known names in order, each once, and the names the game does not know.
    """
    units, unknown = [], []
    for name in setting if isinstance(setting, (list, tuple)) else []:
        name = str(name).strip()
        if not name:
            continue
        if name not in COMBATANT_CLASS:
            unknown.append(name)
        elif name not in units:
            units.append(name)
    return Goals(units, unknown)


def level_allowed(units, index, held):
    """Say whether a goal unit may level, which spends Combat Memories or Support Data and Units every listed unit shares.

    Only when no unit listed before it ended this run unread, below its cap (it can use the Combat Memories now), or with
    its Promotion ready but for the Units, so what the unit the player put first can use stays for it. A Promotion short
    of Manuals or waiting on a mission holds nobody: Combat Memories are no use to that unit until it promotes.

    Args:
        units: The goal units in order.
        index: This unit's place in that order.
        held: The units holding the shared materials back.

    Returns:
        True when it may.
    """
    return not any(unit in held for unit in units[:index])


def write_goals(lines, path=None):
    """Write the goal file whole, one short action per line, so a reader never meets half of it.

    The lines go to a file beside it first, which then replaces it in one step: a write that fails leaves the old file
    as it was.

    Args:
        lines: The goal lines, in goal order.
        path: Where the file lives, `GOALS_FILE` when None.
    """
    path = path or GOALS_FILE
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    partial = path + ".tmp"
    try:
        with open(partial, "w", encoding="utf-8") as file:
            file.write("[\n" + ",\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + ("\n" if lines else "") + "]\n")
        os.replace(partial, path)
    except BaseException:
        if os.path.exists(partial):
            os.remove(partial)
        raise
