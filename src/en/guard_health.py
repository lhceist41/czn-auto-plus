"""Refuse to start a mode when one of its safety guards did not install.

The list edits run on every task load and a failed one only logs, so a mode would otherwise run on upstream behaviour:
press any centred Confirm, pay Aether for Reason, tap blind on a frozen screen. An edit can also fail without raising,
when its function or anchor is missing, and such a skip looks exactly like a mode that is not loaded yet. So the check
reads each mode's finished list when the mode starts, from `BaseTask.enable`: a handler inside the list could not do
it, because when the edits fail it is missing too.
"""

from typing import Callable, NamedTuple

from ok import Logger
from ok.task.exceptions import TaskDisabledException

from src.en import equipment, farm_restart, heal, language_check, memory_limit, reason, spend_guard, stuck_stop, zero_system
from src.en import handlers
from src.en.handlers import HANDLER_LIST, WRAPS, loaded
from src.en.notify import announce

logger = Logger.get_logger(__name__)

CHAOS = "utils_chaos"
SORTIE = "utils_sortie"
STORY = "utils_story"
DAILY = stuck_stop.DAILY
# Each mode's class name and the module holding its handler list.
MODES = {"ChaosMode": CHAOS, "SortieMode": SORTIE, "StoryMode": STORY, "DailyMode": DAILY}
MESSAGE = "Safety guard missing: {names}. Stopped before any input."
# What a plain closure over a handler calls the handler it wraps: notify's stuck notice and `rewards`' list filler.
INNER_CELLS = ("original", "handler")


class Need(NamedTuple):
    """One handler a mode's list must hold for a guard to be in place.

    `tag` is the change `handlers.wrap` records on it, `before` a handler it must come ahead of, `function` the
    fork's own function a same-named replacement must be, and `on` a module whose attribute is checked instead.
    """

    label: str
    handler: str
    tag: str = None
    before: str = None
    function: Callable = None
    on: str = None


class Guard(NamedTuple):
    """A guard whose failure stops a mode: the module that installs it, its modes, and what each mode's list must hold."""

    label: str
    # None for a guard nothing installs.
    module: str
    modes: tuple
    needs: dict
    # Takes the task and says whether the guard matters for this run. None for always.
    when: Callable = None


def tagged(handler, tag):
    """Build the need for a handler carrying one of the guard's changes.

    Args:
        handler: The handler's name.
        tag: The change it must carry.

    Returns:
        The need, labelled by both.
    """
    return Need(f"{tag} ({handler})", handler, tag=tag)


def farm_restart_on(task):
    """Say whether Farm Gaps or Farm Starting Card is on for this run, as upstream reads them.

    Args:
        task: The mode starting.

    Returns:
        True when either is on.
    """
    config = getattr(task, "config", None) or {}
    defaults = getattr(task, "default_config", None) or {}
    return any(farm_restart.is_on(config[key] if key in config else defaults.get(key, off))
               for key, off in farm_restart.OFF.items())


CONFIRM = "handle_center_confirm"
RESCUE = Need(f"Rescue stop ({spend_guard.handle_rescue_screen.__name__} ahead of {CONFIRM})",
              spend_guard.handle_rescue_screen.__name__, before=CONFIRM)
# Upstream's caption handlers each mode's list holds, of those the spend guard keeps off a run menu.
CAPTIONS = {
    CHAOS: spend_guard.RUN_MENU_HANDLERS,
    SORTIE: spend_guard.RUN_MENU_HANDLERS,
    STORY: ("handle_next_step", "handle_close_page"),
}
RUN_MENU = spend_guard.holding_run_menu(None, False).__name__
STUCK_STOP = Need(f"stuck stop ({language_check.STUCK_STOP})", language_check.STUCK_STOP)
LANGUAGE_CHECK = Need(f"Game Language check ({language_check.check_game_language.__name__})",
                      language_check.check_game_language.__name__)
FAINT_MEMORY = (
    Need(f"Faint Memory limit ({memory_limit.handle_memory_limit.__name__})", memory_limit.handle_memory_limit.__name__,
         before=memory_limit.ANCHOR),
    Need(f"Divine notice ({memory_limit.handle_divine_epiphany.__name__})", memory_limit.handle_divine_epiphany.__name__,
         before=memory_limit.ANCHOR),
)
EQUIPMENT_TAGS = (equipment.UPGRADE_TAG, equipment.PLACEMENT_TAG, equipment.RECOMMENDED_TAG, equipment.MYTHIC_TAG,
                  equipment.SLOT_TAG, equipment.PICK_TAG, equipment.SELECTED_TAG, equipment.DRAWN_TAG)
EQUIPMENT = (*(tagged("handle_equipment", tag) for tag in EQUIPMENT_TAGS),
             Need(f"{equipment.LISTS_TAG} (_equipment_priority)", "_equipment_priority", tag=equipment.LISTS_TAG, on="utils"))
ZERO_SYSTEM = (
    *(Need(f"Zero System Codex ({name})", name) for name in (
        zero_system.select_handler(None, None).__name__,
        zero_system.merge_handler(None, None).__name__,
        zero_system.obtained_handler(None, None).__name__,
    )),
    Need(f"Zero System Codex ({zero_system.handle_discovery_select.__name__})", zero_system.handle_discovery_select.__name__,
         function=zero_system.handle_discovery_select),
)


def spend_needs(mode):
    """List what the spend guard's install leaves in one of Chaos, Sortie and Story.

    Args:
        mode: The mode's list module.

    Returns:
        A tuple of needs.
    """
    taps_and_escape = mode != STORY
    return (
        *((tagged("handle_stuck_log", spend_guard.TAPS_TAG),) if taps_and_escape else ()),
        tagged(CONFIRM, spend_guard.CONFIRM_TAG),
        tagged("handle_enter", spend_guard.ENTER_TAG),
        *(tagged(name, spend_guard.RUN_MENU_TAG) for name in CAPTIONS[mode]),
        *((tagged("handle_escape", spend_guard.ESCAPE_TAG),) if taps_and_escape else ()),
        RESCUE,
        Need(f"run-menu hold ({RUN_MENU})", RUN_MENU),
    )


GUARDS = (
    Guard("spend guard", spend_guard.__name__, (CHAOS, SORTIE, STORY),
          {mode: spend_needs(mode) for mode in (CHAOS, SORTIE, STORY)}),
    # Daily's Rescue stop is in its own list rather than installed, and Daily presses through its own guarded `press`.
    Guard("Rescue stop", None, (DAILY,), {DAILY: (Need(f"Rescue stop ({RESCUE.handler})", RESCUE.handler),)}),
    Guard("Reason only", reason.__name__, (SORTIE,), {SORTIE: (
        Need(f"Reason only ({reason.charge_reason_handler(None).__name__} ahead of {CONFIRM})",
             reason.charge_reason_handler(None).__name__, before=CONFIRM),
        tagged("handle_sortie_reward_settlement", reason.SETTLEMENT_TAG),
        tagged("handle_sortie_reward_claim", reason.CLAIM_TAG),
    )}),
    # Sortie's list holds no Trauma Center, so there only a raise counts.
    Guard("Credits-only healing", heal.__name__, (CHAOS, SORTIE), {CHAOS: (tagged("handle_trauma_center", heal.TAG),)}),
    Guard("Faint Memory limit", memory_limit.__name__, (CHAOS, SORTIE), {CHAOS: FAINT_MEMORY, SORTIE: FAINT_MEMORY}),
    Guard("equipment rules", equipment.__name__, (CHAOS, SORTIE), {CHAOS: EQUIPMENT, SORTIE: EQUIPMENT}),
    # No setting says whether a Chaos run will reach Zero System, so every Chaos start needs it.
    Guard("Zero System Codex rules", zero_system.__name__, (CHAOS,), {CHAOS: ZERO_SYSTEM}),
    Guard("farm restart off", farm_restart.__name__, (CHAOS,), {CHAOS: (
        *(tagged(name, farm_restart.TAG) for name in farm_restart.RESTART_BRANCHES),
        tagged("handle_disable_adaptation_distortion", farm_restart.TAG),
    )}, when=farm_restart_on),
    Guard("stuck stop", stuck_stop.__name__, (CHAOS, SORTIE, STORY, DAILY),
          {mode: (STUCK_STOP,) for mode in (CHAOS, SORTIE, STORY, DAILY)}),
    Guard("Game Language check", language_check.__name__, (CHAOS, SORTIE, STORY),
          {mode: (LANGUAGE_CHECK,) for mode in (CHAOS, SORTIE, STORY)}),
)

_patched = False


def held_original(handler):
    """Read the handler a plain closure wraps under a new name, which keeps no `__wrapped__`.

    Args:
        handler: A list entry, such as notify's `handle_stuck_log_announcing`.

    Returns:
        What its first cell named in `INNER_CELLS` holds, or None.
    """
    code = getattr(handler, "__code__", None)
    for name in INNER_CELLS:
        if code is not None and name in code.co_freevars:
            try:
                return handler.__closure__[code.co_freevars.index(name)].cell_contents
            except (TypeError, ValueError):
                return None
    return None


def layers(handler):
    """Yield a list entry and every handler it wraps, outermost first.

    `claims` wraps every entry with `functools.wraps`; a wrapper from `handlers.wrap` already lists every change
    beneath it, so only a plain closure is opened, by its cell named in `INNER_CELLS`.

    Args:
        handler: A list entry.

    Returns:
        A generator of callables.
    """
    seen = []
    while callable(handler) and not any(handler is earlier for earlier in seen):
        seen.append(handler)
        yield handler
        inner = getattr(handler, "__wrapped__", None)
        if inner is None and not getattr(handler, WRAPS, None):
            inner = held_original(handler)
        handler = inner


def carried(handler):
    """Collect the changes a handler carries, through every wrapper over it.

    Args:
        handler: A list entry or module attribute.

    Returns:
        A set of tags.
    """
    return {tag for layer in layers(handler) for tag in getattr(layer, WRAPS, ())}


def find(entries, need):
    """Find the list entry a need names.

    Args:
        entries: A mode's handler list.
        need: The need.

    Returns:
        The entry's index, or None.
    """
    for index, entry in enumerate(entries):
        for layer in layers(entry):
            if need.function is not None and layer is need.function:
                return index
            if need.function is None and getattr(layer, "__name__", None) == need.handler:
                return index
    return None


def met(need, entries):
    """Say whether a mode's list satisfies a need.

    Args:
        need: The need.
        entries: The mode's handler list.

    Returns:
        True when it is in place.
    """
    if need.on is not None:
        target = getattr(loaded(need.on), need.handler, None)
        return target is not None and need.tag in carried(target)
    index = find(entries, need)
    if index is None or (need.tag is not None and need.tag not in carried(entries[index])):
        return False
    if need.before is not None:
        anchor = find(entries, Need(need.before, need.before))
        return anchor is not None and index < anchor
    return True


def missing(task):
    """Name each safety guard the starting mode lacks.

    Checked against what the lists hold, not only against what raised, which also catches an install that raised
    halfway and an edit that found nothing to change.

    Args:
        task: The mode starting.

    Returns:
        A list of guard names, empty when every guard is in place or the task is not a mode.
    """
    mode = MODES.get(type(task).__name__)
    if mode is None:
        return []
    entries = getattr(loaded(mode), HANDLER_LIST, None)
    entries = entries if isinstance(entries, list) else []
    raised = {install.__module__ for install in handlers.failed}
    names = []
    for guard in GUARDS:
        if mode not in guard.modes or (guard.when is not None and not guard.when(task)):
            continue
        if guard.module is not None and guard.module in raised:
            names.append(f"{guard.label} (its install raised)")
        names.extend(need.label for need in guard.needs.get(mode, ()) if not met(need, entries))
    return names


def check(task):
    """Stop the starting mode before any input when a safety guard is missing, else warn once of any other failed install.

    Args:
        task: The mode starting.

    Raises:
        TaskDisabledException: A guard is missing. Raised rather than returned so nothing the start would run next
            runs, the run loop included, and the executor ends the task as it does any stopped one.
    """
    names = missing(task)
    if names:
        message = MESSAGE.format(names="; ".join(names))
        logger.error(f"{type(task).__name__}: {message}")
        announce(task, message)
        task.disable()
        raise TaskDisabledException(message)
    if handlers.failed:
        listed = ", ".join(sorted(f"{install.__module__}.{install.__qualname__}" for install in handlers.failed))
        logger.warning(f"{type(task).__name__} starts with upstream behaviour where these installs failed: {listed}")


def checking(original):
    """Wrap `BaseTask.enable` so a mode starts only with its safety guards in place.

    Args:
        original: The unbound `enable` being replaced.

    Returns:
        The replacement.
    """
    def enable(self):
        check(self)
        return original(self)

    return enable


def apply():
    """Refuse to start Chaos, Sortie, Story or Daily without the guards that keep it off spends, discards and the run's Escape."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.error("could not import BaseTask, a mode will start whatever guards failed to install")
        return
    BaseTask.enable = checking(BaseTask.enable)
    _patched = True
