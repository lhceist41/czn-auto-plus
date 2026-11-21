"""Claim Chaos's Additional Loot before the final Settlement's Leave, and keep the setting on when the cards run out.

Upstream's `handle_chaos_reward_claim` cancels the claim at 0 cards and saves the setting as off, so it stays off after the weekly reset
refills them. This backs out the same way but only skips the rest of this run's loot.

The final Settlement shows Leave where a waypoint shows Continue, and `handle_leave` ranks far above upstream's Settlement handler,
which would leave without Obtain and let the centred Confirm give the loot up. So Obtain is pressed ahead of Leave while cards are
left, and the "continue without card" dialog is cancelled in that state.

A Settlement whose own Obtain or counter misreads on a still screen would cycle Leave and Cancel, or Obtain and Cancel, without end,
and the picture changes too much each cycle for the stuck stop to see it. So a second Cancel with no claim in between stops the run.
"""

import re

from src.en.dice import parse_currency
from src.en.handlers import answering, insert_before, loaded, register, wrap
from src.en.notify import announce
from src.en.screen import in_region
from src.en.spend_guard import cancel_button, folded

# Where upstream reads the `2/3` card counter on the claim dialog, and its Cancel button.
CARD_COUNTER_POINT = (0.959, 0.281)
CANCEL_POINT = (0.352, 0.708)
CLAIM_POINT = (0.568, 0.711)
# Upstream's own counter pattern, so the claim dialog is cancelled for an unreadable counter exactly where upstream would cancel it.
UPSTREAM_COUNTER = re.compile(r"(\d+)/(\d+)")
# Set in `node_status` once the cards read 0. Upstream rebuilds `node_status` between runs, so the next run checks again.
OUT_OF_CARDS = "_en_out_of_cards"
CLAIMING = "领取奖励(只使用验证卡)"
SETTLEMENT_TAG = "skips Obtain without Loot Certification Cards"
# Kept in `node_status` beside `OUT_OF_CARDS`, so it starts again with every run: the Settlement Cancels pressed since the last claim.
CANCELS = "_en_settlement_cancels"
MAX_CANCELS = 2
STOP_MESSAGE = ("Stopped: a Chaos Settlement asked twice about its Additional Loot and cancelling did not get past it. "
                "Claim or leave it in the game, then press Start again.")
# The Settlement page, read off captures of both Settlements: upstream's title and Obtain points, the card counter top right
# (still read under the dialog), and the point `handle_leave` reads its button at.
SETTLEMENT_TITLE_POINT = (0.552, 0.067)
SETTLEMENT_COUNTER_POINT = (0.879, 0.050)
OBTAIN_POINT = (0.851, 0.389)
LEAVE_POINT = (0.945, 0.918)
# "There is additional loot available. Continue without using Loot Certification Card?", one line across the dialog, and its Cancel.
WITHOUT_CARD = ("additionallootavailable", "withoutusinglootcertification")
WITHOUT_CARD_REGION = (0.1, 0.3, 0.9, 0.5)
WITHOUT_CARD_CANCEL_POINT = (0.347, 0.632)

_patched = False


def claiming_with_cards(task, claiming):
    """Read the Additional Loot setting as off once this run has found the cards gone.

    Args:
        task: The running task, on the Settlement page.
        claiming: The setting as upstream read it.

    Returns:
        False after a 0-card claim dialog this run, otherwise the setting as it was.
    """
    return claiming and not task.node_status.get(OUT_OF_CARDS)


def cancelling(task, press):
    """Press a Settlement Cancel, and stop the run when it is the second since the last claim.

    The Cancel is still pressed, so the game is left on the Settlement with its loot claimable by hand.

    Args:
        task: The running task.
        press: Presses the Cancel.
    """
    cancels = task.node_status.get(CANCELS, 0) + 1
    task.node_status[CANCELS] = cancels
    press()
    task.sleep(1)
    if cancels >= MAX_CANCELS:
        announce(task, STOP_MESSAGE)
        task.disable()


def no_cards_handler(utils_chaos):
    """Build the handler that cancels a claim with 0 cards left without touching the setting.

    Args:
        utils_chaos: Upstream's Chaos module, for its screen and click helpers.

    Returns:
        The handler. It also takes over upstream's Cancel for an unreadable counter, so that Cancel is counted, and declines a
        claim with cards left, which upstream's own handler then makes.
    """
    def handle_claim_without_cards(task):
        claim_box = utils_chaos.find_box_at_point(task, *CLAIM_POINT)
        if not (claim_box and "获得" in claim_box.name):
            return False
        counter = utils_chaos.find_box_at_point(task, *CARD_COUNTER_POINT)
        cards = parse_currency(counter.name) if counter else None
        if cards is not None and cards[0] == 0:
            task.log_info("no Loot Certification Cards left, so leaving this run's Additional Loot and keeping the setting on")
            task.node_status[OUT_OF_CARDS] = True
            utils_chaos._move_and_click(task, *CANCEL_POINT)
            task.sleep(1)
            return True
        if not (counter and UPSTREAM_COUNTER.search(counter.name)):
            task.log_info("the Loot Certification Card counter on the claim dialog cannot be read, cancelling the claim")
            cancelling(task, lambda: utils_chaos._move_and_click(task, *CANCEL_POINT))
            return True
        task.node_status.pop(CANCELS, None)
        return False

    return handle_claim_without_cards


def with_cards_only(handler, utils_chaos):
    """Run upstream's Settlement handler with the Additional Loot setting read through `claiming_with_cards`.

    Args:
        handler: `handle_chaos_reward_settlement`, as currently installed.
        utils_chaos: Upstream's Chaos module, whose `_get_config_value` the handler reads the setting through.

    Returns:
        The wrapped handler.
    """
    def wrapped(task):
        with answering(utils_chaos, CLAIMING, claiming_with_cards):
            return handler(task)

    return wrapped


def cards_left(task, utils_chaos):
    """Say whether this run should still spend a Loot Certification Card, by the setting and the Settlement's own counter.

    Args:
        task: The running task, on the Settlement page or its "continue without card" dialog.
        utils_chaos: Upstream's Chaos module, for its screen and config helpers.

    Returns:
        True only with the setting on and a counter that reads above 0. An unreadable counter reads as no, which leaves the
        page as it was handled before rather than starting a loop on a reading nobody has seen.
    """
    if not claiming_with_cards(task, utils_chaos._get_config_value(task, CLAIMING, False)):
        return False
    counter = utils_chaos.find_box_at_point(task, *SETTLEMENT_COUNTER_POINT)
    cards = parse_currency(counter.name) if counter else None
    return cards is not None and cards[0] > 0


def obtain_before_leave_handler(utils_chaos):
    """Build the handler that presses Obtain on a final Settlement before `handle_leave` can leave it.

    Args:
        utils_chaos: Upstream's Chaos module, for its screen and config helpers.

    Returns:
        The handler. It declines a waypoint Settlement, which shows Continue and is still left to upstream's handler.
    """
    def handle_obtain_before_leave(task):
        title = utils_chaos.find_box_at_point(task, *SETTLEMENT_TITLE_POINT)
        if not (title and "结算" in title.name):
            return False
        leave = utils_chaos.find_box_at_point(task, *LEAVE_POINT)
        obtain = utils_chaos.find_box_at_point(task, *OBTAIN_POINT)
        if not (leave and utils_chaos._clean_match(leave.name, "离开") and obtain and "获得" in obtain.name):
            return False
        if not cards_left(task, utils_chaos):
            return False
        task.log_info("final Settlement with Loot Certification Cards left, pressing Obtain before Leave")
        task.click_box(obtain)
        task.sleep(1)
        return True

    return handle_obtain_before_leave


def without_card_handler(utils_chaos):
    """Build the handler that cancels "continue without card" while cards are left, so the Settlement can claim instead.

    Args:
        utils_chaos: Upstream's Chaos module, for its screen, click and config helpers.

    Returns:
        The handler. It only ever presses Cancel, and stops the run on the second since the last claim; otherwise it declines and
        the dialog goes on to the centred Confirm as before.
    """
    def handle_continue_without_card(task):
        asked = any(in_region(box, WITHOUT_CARD_REGION, task.width, task.height) and any(words in folded(box.name) for words in WITHOUT_CARD)
                    for box in task.all_texts)
        if not (asked and cards_left(task, utils_chaos)):
            return False
        task.log_info("Loot Certification Cards are left, so not continuing without one: cancelling to claim the loot")
        cancel = cancel_button(task)
        if cancel is not None:
            cancelling(task, lambda: task.click_box(cancel))
        else:
            cancelling(task, lambda: utils_chaos._move_and_click(task, *WITHOUT_CARD_CANCEL_POINT))
        return True

    return handle_continue_without_card


def install(utils_chaos):
    """Put the Settlement's claim ahead of Leave and the dialog's Cancel ahead of the centred Confirm, and stand in for upstream's claim.

    Args:
        utils_chaos: The loaded `utils_chaos` module, or None when it is not importable yet.
    """
    if utils_chaos is None:
        return
    insert_before("handle_chaos_reward_claim", no_cards_handler(utils_chaos))
    wrap(utils_chaos, "handle_chaos_reward_settlement", lambda handler: with_cards_only(handler, utils_chaos), SETTLEMENT_TAG)
    # Leave and the centred Confirm are shared with the other modes; the Settlement is Chaos's alone.
    insert_before("handle_leave", obtain_before_leave_handler(utils_chaos), only=("utils_chaos",))
    insert_before("handle_center_confirm", without_card_handler(utils_chaos), only=("utils_chaos",))


def apply():
    """Claim the final Settlement's loot before Leave, keep the setting on when the cards run out, and stop a Settlement Cancel loop."""
    global _patched
    if _patched:
        return
    register(lambda: install(loaded("utils_chaos")))
    _patched = True
