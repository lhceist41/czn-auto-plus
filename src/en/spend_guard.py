"""Never spend account currency, delete or retreat on a tap nobody chose.

Two of upstream's fallbacks act without reading the screen. `handle_stuck_log` taps a random card or an unknown page's
button once a screen has sat still for ten seconds, and `handle_center_confirm` presses any centred Confirm whatever the
dialog asks. Either can buy Aether with Crystals, pay real money, drop a stored save or abandon a run. The blind taps
now decline on any screen that can spend or discard, and a centred Confirm on a dialog that spends outside the run,
deletes or retreats unasked is cancelled once, announced, and the run stopped.

In-run Credits stay allowed: the shop, card removal, Meditation and Extract all run on them.
"""

import re

from src.en.handlers import loaded, register, wrap
from src.en.notify import announce
from src.en.screen import in_region

# Upstream's own band for the centred Confirm, copied from `handle_center_confirm`. It leaves out the top bar, where
# the mode screens count Aether and Sortie counts Reason.
CONFIRM_REGION = (0.009, 0.168, 0.977, 0.875)
# The lower half of that band, where a dialog keeps its buttons.
CANCEL_REGION = (0.1, 0.5, 0.9, 0.875)
CONFIRM = "确认"
CANCEL = ("取消", "cancel")

# Each group reads as what the dialog would do, which is how the stop is announced.
ACCOUNT = "spend account currency"
MONEY = "spend real money"
PURCHASE = "buy something not priced in Credits"
DELETION = "delete something nobody asked to delete"
RETREAT = "retreat from a run nobody asked to leave"
IN_RUN = "spend or discard within the run"

# Words `ocr.po` maps, in both forms, and upstream's own literals.
MARKERS = {
    ACCOUNT: ("补充理性", "Charge Reason"),
    PURCHASE: ("购买", "Buy"),
    DELETION: ("记忆消除",),
    RETREAT: ("逃脱", "脱逃", "Retreat"),
    IN_RUN: ("德朗商店", "Dellang Shop", "刷新", "Refresh", "提炼", "Extract", "以信用点接收", "Receive as Credits", "移除", "Remove",
             "存储数据收集完成", "Save Data collection complete"),
}
# Words taken from public item names and the dialogs' likely wording rather than from captures; they await captures.
UNCAPTURED = {
    ACCOUNT: ("以太", "Aether", "Crystal", "Rescue Anchor", "Tear of God", "Communication Pass"),
    PURCHASE: ("Purchase",),
    DELETION: ("Delete", "Recycle", "Erase", "Eliminat"),
    RETREAT: ("Abandon", "Give Up"),
    IN_RUN: ("Discard", "Dismantle"),
}
# A price in a real currency, the symbol or code on either side of the number, read off folded text.
CURRENCY = r"(?:us\$|\$|€|£|₩|¥|krw|usd|jpy|cny)"
MONEY_PRICE = re.compile(rf"{CURRENCY}\s?\d|\d\s?{CURRENCY}")
# The shop's in-run price icon, from `coco_annotations.json`.
PRICE_ICON = "credit_icon"

# Set in `node_status` by upstream when the run itself asked for the step: `handle_data_collected` after it tapped a
# save's trash icon under the user's threshold, `handle_escape` after it pressed Retreat on the escape page.
DELETE_ASKED = "storage_delete_clicked"
RETREAT_ASKED = "is_escaped"

# Upstream's stuck threshold, used only to log a declined blind tap once per freeze.
STUCK_SECONDS = 10
# Parked on the task: the stuck clock's value when a declined tap was last logged.
LOGGED = "_en_spend_screen_logged"

TAPS_TAG = "no blind tap on a spend screen"
CONFIRM_TAG = "no Confirm on an account spend"

_patched = False


def folded(text):
    """Fold a box's text for matching.

    Args:
        text: The text OCR read, or a marker.

    Returns:
        The text case-folded with its spaces and hyphens taken out, since OCR drops a space now and then and a
        hyphen stands in for one.
    """
    return text.casefold().replace(" ", "").replace("-", "")


def cleaned(text):
    """Strip a box's text down to its letters, digits and Chinese, the way upstream compares a button.

    Args:
        text: The text OCR read.

    Returns:
        The case-folded remainder.
    """
    return re.sub(r"[^一-鿿\w]", "", text).casefold()


WORDS = {group: tuple(folded(word) for word in MARKERS.get(group, ()) + UNCAPTURED.get(group, ()))
         for group in (ACCOUNT, PURCHASE, DELETION, RETREAT, IN_RUN)}


def read_texts(boxes):
    """Fold each box's text, and add the lot joined in reading order.

    A dialog's lines come back one box each, so a name like "Rescue Anchor" can arrive split over two of them.

    Args:
        boxes: OCR boxes.

    Returns:
        The folded texts, then all of them joined.
    """
    texts = [folded(box.name) for box in sorted(boxes, key=lambda box: (box.y, box.x))]
    return [*texts, "".join(texts)]


def marker_in(texts, group):
    """Find a group's first marker in a set of folded texts.

    Args:
        texts: Folded box texts.
        group: One of the group names above, or MONEY for the price pattern.

    Returns:
        The marker as it matched, or None.
    """
    for text in texts:
        if group == MONEY:
            price = MONEY_PRICE.search(text)
            if price:
                return price.group()
            continue
        for word in WORDS[group]:
            if word in text:
                return word
    return None


def spends_or_discards(task):
    """Say whether the screen shows anything a random tap could spend, discard, delete or retreat with.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when a marker or a price in any currency is on screen, or the shop's price icon is.
    """
    texts = read_texts(getattr(task, "all_texts", None) or [])
    if any(marker_in(texts, group) for group in (*WORDS, MONEY)):
        return True
    return bool(task.find_one(PRICE_ICON))


def guarding_taps(original, utils):
    """Wrap the stuck-screen handler so it never taps blind on a screen that can spend or discard.

    Args:
        original: `handle_stuck_log`, as currently installed.
        utils: Upstream's `utils`, for the stuck detector the original would have run.

    Returns:
        The wrapped handler.
    """
    def handle_stuck_log(task):
        if not spends_or_discards(task):
            return original(task)
        # Run in the original's place, so the stuck clock `src/en/notify.py` reads keeps up with this screen.
        if utils.is_frame_stuck(task, stuck_threshold_seconds=STUCK_SECONDS):
            clock = getattr(task, "_last_change_time", None)
            if getattr(task, LOGGED, None) != clock:
                setattr(task, LOGGED, clock)
                task.log_info("not tapping at random on a screen that can spend or discard")
        return False

    return handle_stuck_log


def centred_confirm(task):
    """Find the centred Confirm upstream's handler would press.

    Args:
        task: The running task.

    Returns:
        The box, or None.
    """
    for box in getattr(task, "all_texts", None) or []:
        if cleaned(box.name) == CONFIRM and in_region(box, CONFIRM_REGION, task.width, task.height):
            return box
    return None


def risky_confirm(task):
    """Say whether the centred Confirm would spend outside the run, delete or retreat unasked.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        A `(group, marker)` pair naming what the dialog would do and the text that gave it away, or None when there
        is no centred Confirm or the dialog is safe to confirm.
    """
    if centred_confirm(task) is None:
        return None
    texts = read_texts(box for box in task.all_texts if in_region(box, CONFIRM_REGION, task.width, task.height))
    asked = getattr(task, "node_status", None) or {}
    for group in (ACCOUNT, MONEY):
        marker = marker_in(texts, group)
        if marker:
            return group, marker
    marker = marker_in(texts, PURCHASE)
    if marker and not task.find_one(PRICE_ICON, box=task.box_of_screen(*CONFIRM_REGION)):
        return PURCHASE, marker
    for group, flag in ((DELETION, DELETE_ASKED), (RETREAT, RETREAT_ASKED)):
        marker = marker_in(texts, group)
        if marker and not asked.get(flag):
            return group, marker
    return None


def cancel_button(task):
    """Find the dialog's Cancel.

    Args:
        task: The running task.

    Returns:
        The box, or None when no Cancel can be read.
    """
    for box in task.all_texts:
        if cleaned(box.name) in CANCEL and in_region(box, CANCEL_REGION, task.width, task.height):
            return box
    return None


def guarding_confirm(original):
    """Wrap the centred Confirm so a risky dialog is cancelled once and the run stopped.

    Args:
        original: `handle_center_confirm`, as currently installed.

    Returns:
        The wrapped handler.
    """
    def handle_center_confirm(task):
        risk = risky_confirm(task)
        if risk is None:
            return original(task)
        group, marker = risk
        cancel = cancel_button(task)
        task.log_info(f"not confirming a dialog that would {group} (read {marker!r}), {'cancelling it' if cancel else 'no Cancel to press'}")
        # The dialog would only come back from the screen under it, so the one Cancel is all the input there is.
        if cancel is not None:
            task.click_box(cancel)
        announce(task, f"Stopped: a dialog would {group}. Check the game, then press Start again.")
        task.disable()
        return True

    return handle_center_confirm


def install(utils):
    """Wrap both of upstream's fallbacks wherever the run reaches them.

    Args:
        utils: The loaded `utils` module, or None when it is not importable yet.
    """
    if utils is None:
        return
    wrap(utils, "handle_stuck_log", lambda handler: guarding_taps(handler, utils), TAPS_TAG)
    wrap(utils, "handle_center_confirm", guarding_confirm, CONFIRM_TAG)


def apply():
    """Keep blind taps off spend screens and stop the run at a centred Confirm that would spend, delete or retreat."""
    global _patched
    if _patched:
        return
    register(lambda: install(loaded("utils")))
    _patched = True
