"""Leave the Additional Loot setting on when the Loot Certification Cards run out.

Upstream's `handle_chaos_reward_claim` cancels the claim at 0 cards and saves the setting as off, so it stays off after the weekly reset
refills them. This backs out the same way but only skips the rest of this run's loot.
"""

from src.en.dice import parse_currency
from src.en.handlers import answering, insert_before, loaded, register, wrap

# Where upstream reads the `2/3` card counter on the claim dialog, and its Cancel button.
CARD_COUNTER_POINT = (0.959, 0.281)
CANCEL_POINT = (0.352, 0.708)
CLAIM_POINT = (0.568, 0.711)
# Set in `node_status` once the cards read 0. Upstream rebuilds `node_status` between runs, so the next run checks again.
OUT_OF_CARDS = "_en_out_of_cards"
CLAIMING = "领取奖励(只使用验证卡)"
SETTLEMENT_TAG = "skips Obtain without Loot Certification Cards"

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


def no_cards_handler(utils_chaos):
    """Build the handler that cancels a claim with 0 cards left without touching the setting.

    Args:
        utils_chaos: Upstream's Chaos module, for its screen and click helpers.

    Returns:
        The handler. It declines any other claim dialog, which upstream's own handler then takes.
    """
    def handle_claim_without_cards(task):
        claim_box = utils_chaos.find_box_at_point(task, *CLAIM_POINT)
        if not (claim_box and "获得" in claim_box.name):
            return False
        counter = utils_chaos.find_box_at_point(task, *CARD_COUNTER_POINT)
        cards = parse_currency(counter.name) if counter else None
        if cards is None or cards[0] > 0:
            return False
        task.log_info("no Loot Certification Cards left, so leaving this run's Additional Loot and keeping the setting on")
        task.node_status[OUT_OF_CARDS] = True
        utils_chaos._move_and_click(task, *CANCEL_POINT)
        task.sleep(1)
        return True

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


def apply():
    """Cancel a 0-card claim ahead of upstream, and skip Obtain for the rest of that run."""
    global _patched
    if _patched:
        return

    def install():
        utils_chaos = loaded("utils_chaos")
        if utils_chaos is None:
            return
        insert_before("handle_chaos_reward_claim", no_cards_handler(utils_chaos))
        wrap(utils_chaos, "handle_chaos_reward_settlement", lambda handler: with_cards_only(handler, utils_chaos), SETTLEMENT_TAG)

    register(install)
    _patched = True
