"""Keep Farm Gaps and Farm Starting Card from restarting a Chaos run on the Global client.

Both settings wait for a starting event offering Remove 2 Cards or a Legendary Card and tap the run's menu "to restart"
when it lacks one. No fresh Global run has shown that event, and upstream matches its Chinese wording, so the tap only
ever opened Chaos Info, where the run sat until the stuck stop. Until a real restart exists, the restart branches and
Farm Gaps' switch-off of Adaptation Distortion on the Chaos start page read both settings as off. Farm Gaps' card
removal and Farm Starting Card's place at the top of the card reward priority stay as they are.
"""

import contextlib

from src.en.handlers import answering, loaded, register, standing_in, wrap

FARM_GAPS = "刷空档"
STARTING_CARD = "刷初始卡牌"
# What upstream reads when each setting is off.
OFF = {FARM_GAPS: False, STARTING_CARD: ""}
NAMES = {FARM_GAPS: "Farm Gaps", STARTING_CARD: "Farm Starting Card"}
# Each handler holding a restart branch: the settings it reads as off, and the helpers it calls that read them as saved.
RESTART_BRANCHES = {"handle_event_task": ((STARTING_CARD, FARM_GAPS), ()),
                    "handle_card_reward": ((STARTING_CARD,), ("_get_card_reward_priority",))}
# The run whose lines are said, and the settings said in it.
LOGGED = "_en_farm_restart_logged"
TAG = "no farm restart on Global"

_patched = False


def is_on(value):
    """Say whether a read of either setting turns it on, as upstream tests them.

    Args:
        value: What `_get_config_value` read.

    Returns:
        True for Farm Gaps ticked or a starting card named.
    """
    return value is True or (isinstance(value, str) and bool(value.strip()))


def say_off(task, key):
    """Log once per run that a setting cannot restart a run on the Global client yet.

    Upstream starts every run with a new `node_status`, so that object tells one run from the next. A new floor brings
    one too, but keeps the count of bosses passed.

    Args:
        task: The running task.
        key: The setting's config key.
    """
    status = getattr(task, "node_status", None)
    logged = getattr(task, LOGGED, None)
    if logged is None or logged[0] is not status:
        same_run = logged is not None and (status or {}).get("pass_final_boss_count", 0) > 0
        logged = (status, logged[1] if same_run else set())
        setattr(task, LOGGED, logged)
    if key not in logged[1]:
        logged[1].add(key)
        task.log_info(f"{NAMES[key]} cannot restart a run on the Global client yet, so the run plays on")


def read_off(task, value, key):
    """Answer a read of a setting with its off value.

    Args:
        task: The running task.
        value: What upstream would have read.
        key: The setting's config key.

    Returns:
        The off value when the setting is on, otherwise the value read.
    """
    if not is_on(value):
        return value
    say_off(task, key)
    return OFF[key]


def as_saved(utils, helper, reader):
    """Run one of upstream's helpers over the saved settings while the handler around it reads them as off.

    Args:
        utils: Upstream's `utils`.
        helper: The helper, as currently installed.
        reader: The `_get_config_value` the module carried before the handler started.

    Returns:
        The helper to stand in for the length of the handler.
    """
    def reading_saved(*args, **kwargs):
        with standing_in(utils, _get_config_value=reader):
            return helper(*args, **kwargs)

    return reading_saved


def playing_on(utils, keys, keeping=()):
    """Build the change that runs a handler with the given settings read as off.

    Args:
        utils: Upstream's `utils`, whose `_get_config_value` the handler reads through.
        keys: The settings to read as off.
        keeping: Names of `utils` helpers the handler calls that still read the saved settings.

    Returns:
        A factory taking the handler currently installed and returning the one to run in its place.
    """
    def factory(original):
        def handler(task, *args, **kwargs):
            reader = utils._get_config_value
            with contextlib.ExitStack() as stack:
                stack.enter_context(standing_in(utils, **{name: as_saved(utils, getattr(utils, name), reader) for name in keeping}))
                for key in keys:
                    stack.enter_context(answering(utils, key, lambda task_, value, key=key: read_off(task_, value, key)))
                return original(task, *args, **kwargs)

        return handler

    return factory


def leaving_adaptation_distortion(utils_chaos):
    """Build the change that leaves the Chaos start page's Adaptation Distortion switch as it is.

    Args:
        utils_chaos: Upstream's Chaos module, for `_get_config_value`.

    Returns:
        A factory taking the handler currently installed and returning the one to run in its place.
    """
    def factory(original):
        def handler(task):
            if utils_chaos._get_config_value(task, FARM_GAPS, False) is True:
                say_off(task, FARM_GAPS)
                return False
            return original(task)

        return handler

    return factory


def install():
    """Read both settings as off in the restart branches and on the Chaos start page."""
    utils = loaded("utils")
    if utils is not None:
        for name, (keys, keeping) in RESTART_BRANCHES.items():
            wrap(utils, name, playing_on(utils, keys, keeping), TAG)
    utils_chaos = loaded("utils_chaos")
    if utils_chaos is not None:
        wrap(utils_chaos, "handle_disable_adaptation_distortion", leaving_adaptation_distortion(utils_chaos), TAG)


def apply():
    """Keep Farm Gaps and Farm Starting Card from tapping a run's menu or the start page's Adaptation Distortion switch."""
    global _patched
    if _patched:
        return
    register(install)
    _patched = True
