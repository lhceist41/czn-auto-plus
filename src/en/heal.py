"""Always heal a Mental Breakdown with Credits at the Trauma Center.

Upstream spends a Communication Pass whenever one is held, unless its Chaos-only `优先使用金币治疗` switch is on. That switch is off
the card now, so the handler runs with it read as on.
"""

from src.en.handlers import answering, loaded, register, wrap

# Upstream's switch, read by `handle_trauma_center` in `utils_chaos`. `overrides.DROPPED` takes it off the card.
PAY_CREDITS = "优先使用金币治疗"
TAG = "always heals with Credits"

_patched = False


def paying_credits(handler, utils_chaos):
    """Run upstream's Trauma Center handler with its pay-with-Credits switch read as on.

    Args:
        handler: `handle_trauma_center`, as currently installed.
        utils_chaos: Upstream's Chaos module, whose `_get_config_value` the handler reads the switch through.

    Returns:
        The wrapped handler.
    """
    def wrapped(task):
        with answering(utils_chaos, PAY_CREDITS, lambda task_, setting: True):
            return handler(task)

    return wrapped


def apply():
    """Have the Trauma Center always pay Credits."""
    global _patched
    if _patched:
        return

    def install():
        utils_chaos = loaded("utils_chaos")
        if utils_chaos is not None:
            wrap(utils_chaos, "handle_trauma_center", lambda handler: paying_credits(handler, utils_chaos), TAG)

    register(install)
    _patched = True
