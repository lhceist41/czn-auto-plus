"""Stop a Chaos, Sortie, Story or Daily run once the screen has sat still for five minutes.

Upstream's stuck handler keeps trying to click its way out for as long as the screen stays frozen, and on a screen that
can spend or discard `src/en/spend_guard.py` takes even that away, so a freeze nothing can get past would loop until
someone looked. Story has no stuck handling at all, so a screen none of its handlers knows held it the same way. This
ends the run with one last notification instead.
"""

import time

from src.en.handlers import insert_before, loaded, register
from src.en.notify import announce
from src.en.stuck import CLOCK, forget

# Past notify's first toast at 60s and short of its repeat at 360s, so the stop is the one notification after it.
STOP_SECONDS = 300
# A longer gap between two passes means the loop was not looking (a pause, a break, a long read), so the time
# frozen across it says nothing about the game. Restarting the clock there can only put a stop off.
GAP_SECONDS = 30
MESSAGE = "Stopped: the screen has not changed for 5 minutes. Check the game, then press Start again."

# Ahead of upstream's own stop handler, which Chaos and Sortie run first, so a handler that claims every frame cannot
# keep this from seeing the screen. Story has no such handler, so there it goes ahead of whatever its list starts with, the hold aside.
ANCHOR = "handle_auto_stop"
MODES = ("utils_chaos", "utils_sortie")
STORY = "utils_story"
# `remote`'s handler, first in every list on a debug run. Story's stop goes behind it, as in the other modes:
# a held run gets no pass of the stop, and a hold longer than the gap restarts the clock on release.
HOLD = "handle_remote"
# Daily's list starts with `remote`'s handler, which stays first so a held bot does nothing, then the Rescue stop.
DAILY = "src.en.daily"
DAILY_ANCHOR = "handle_rescue_screen"

# Parked on the task: when this last ran, and the stuck clock's value when the stop was last announced.
LAST_PASS = "_en_stuck_stop_last_pass"
ANNOUNCED = "_en_stuck_stop_announced"

_patched = False


def stopping(utils):
    """Build the handler that stops a run frozen past the limit.

    Args:
        utils: Upstream's `utils`, for the stuck detector.

    Returns:
        The handler.
    """
    def stop_when_stuck(task):
        now = time.time()
        last = getattr(task, LAST_PASS, None)
        setattr(task, LAST_PASS, now)
        if last is None or now - last > GAP_SECONDS:
            forget(task)
        # Run here rather than read passively, so the clock keeps up even while a later handler claims every frame.
        if not utils.is_frame_stuck(task, stuck_threshold_seconds=STOP_SECONDS):
            return False
        clock = getattr(task, CLOCK, None)
        if getattr(task, ANNOUNCED, None) != clock:
            setattr(task, ANNOUNCED, clock)
            announce(task, MESSAGE)
        task.disable()
        return True

    return stop_when_stuck


def install(utils):
    """Put the stop ahead of every handler but the hold in Chaos, Sortie and Story, and ahead of the Rescue stop in Daily's.

    Args:
        utils: The loaded `utils` module, or None when it is not importable yet.
    """
    if utils is None:
        return
    insert_before(ANCHOR, stopping(utils), only=MODES)
    story = loaded(STORY)
    names = [handler.__name__ for handler in getattr(story, "PAGE_HANDLERS", None) or ()]
    first = names.index(HOLD) + 1 if HOLD in names else 0
    if first < len(names):
        insert_before(names[first], stopping(utils), only=(STORY,))
    insert_before(DAILY_ANCHOR, stopping(utils), only=(DAILY,))


def apply():
    """Stop a Chaos, Sortie, Story or Daily run whose screen has not changed for five minutes."""
    global _patched
    if _patched:
        return
    register(lambda: install(loaded("utils")))
    _patched = True
