"""Always heal a Mental Breakdown with Credits at the Trauma Center, and only when healing is on.

Upstream spends a Communication Pass whenever one is held, unless its Chaos-only `优先使用金币治疗` switch is on. That switch is off
the card now, so the handler runs with it read as on. Upstream's heal switch only gates the Breakdown screen, so with it off a
run that still reaches the Trauma Center with someone to treat stops there rather than paying.
"""

from src.en.handlers import answering, loaded, register, wrap
from src.en.notify import announce

# Upstream's switch, read by `handle_trauma_center` in `utils_chaos`. `overrides.DROPPED` takes it off the card.
PAY_CREDITS = "优先使用金币治疗"
# The heal switch, the title `handle_trauma_center` recognises the Trauma Center by, where it reads it, and the line it
# leaves on, with nothing but a back tap, when nobody is in treatment.
HEALING = "治疗崩溃"
TITLE = "创伤中心"
TITLE_POINT = (0.125, 0.049)
NOBODY_RECOVERING = "没有恢复中的战员"
TAG = "always heals with Credits"

_patched = False


def at_the_trauma_center(task, utils_chaos):
    """Say whether the screen is the Trauma Center, by upstream's own check.

    Args:
        task: The running task.
        utils_chaos: Upstream's Chaos module, for its box and game text helpers.

    Returns:
        True when the title sits where upstream reads it.
    """
    box = utils_chaos.find_box_at_point(task, *TITLE_POINT)
    return bool(box and utils_chaos._get_game_text(task, TITLE) in box.name)


def someone_to_treat(task, utils_chaos):
    """Say whether upstream would go on to the treatment taps, by its own check for an empty Trauma Center.

    Args:
        task: The running task, on the Trauma Center.
        utils_chaos: Upstream's Chaos module, for its text helpers.

    Returns:
        False when the screen says nobody is recovering.
    """
    return utils_chaos.find_text(task, utils_chaos._get_game_text(task, NOBODY_RECOVERING)) is None


def paying_credits(handler, utils_chaos):
    """Run upstream's Trauma Center handler with its pay-with-Credits switch read as on, or stop the run there when healing is off.

    Args:
        handler: `handle_trauma_center`, as currently installed.
        utils_chaos: Upstream's Chaos module, whose `_get_config_value` the handler reads the switch through.

    Returns:
        The wrapped handler.
    """
    def wrapped(task):
        if not utils_chaos._get_config_value(task, HEALING, True) and at_the_trauma_center(task, utils_chaos) and someone_to_treat(task, utils_chaos):
            announce(task, "Stopped at the Epione Center: healing is off. Treat the combatant yourself, then press Start again.")
            task.disable()
            return True
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
