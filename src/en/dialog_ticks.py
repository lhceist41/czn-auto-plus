"""Tick "Do not show" on both Story skip dialogs and on Battle Prep: the skip dialogs until the next login, Battle Prep for the day.

The dialogs are still confirmed by the handlers that press them today, `handle_center_confirm` and `handle_enter`, behind
every guard those sit behind: this only taps the box first, once per appearance. The Rescue dialog draws the same box at
the large skip dialog's x and the Loot dialog at the compact one's spot, and a tick there would drop the pull
confirmation or the lost-loot warning, so a box is tapped only on these three dialogs, each told apart by its title, its
label and its button row, and only while it reads as unticked and lit.
"""

import numpy as np

from src.en.handlers import insert_before, register
from src.en.screen import colour_share, frame_of, patch_of
from src.en.spend_guard import COMPACT_SKIP_DIALOG, SKIP_DIALOG, Dialog, rescue_marker, risky_confirm, shown
from src.en.story import tap

# The title must be the whole box, since the Settings page reads "Display Battle Prep Confirmation Popup". Read off three
# captures: title at (0.499-0.501, 0.166-0.169), label at (0.520, 0.721) and as "Do not show again today i" at (0.539, 0.721)
# under the tutorial's dimming, buttons at y 0.830-0.831.
BATTLE_PREP = Dialog("Battle Prep Confirmation", "battleprepconfirmation", True, (0.30, 0.12, 0.70, 0.21),
                     "donotshowagaintoday", (0.40, 0.69, 0.66, 0.75), ("取消", "进入"), (0.25, 0.80, 0.75, 0.86))
# Each dialog with the centre of its box. These are the only points this module ever taps.
TICKS = ((SKIP_DIALOG, (0.3925, 0.678)), (BATTLE_PREP, (0.404, 0.721)), (COMPACT_SKIP_DIALOG, (0.392, 0.532)))
# Half the patch read around a box's centre, as screen fractions: 23 x 22 pixels at 1080p, inside the box's grey square.
PATCH_HALF = (0.006, 0.01)
# The tick's orange, about (240, 142, 75), as OpenCV HSV bounds. It covered 0.79 of the patch on the ticked capture, and
# nothing on the unticked, dimmed and other dialogs' captures.
TICK_LOW = np.array((5, 102, 150), dtype=np.uint8)
TICK_HIGH = np.array((25, 255, 255), dtype=np.uint8)
MIN_TICKED = 0.5
# The unticked box is a flat grey of about 195 lit, and about 59 under the tutorial's dimming. Neutral here means channels
# within `MAX_SPREAD` of each other and a brightness inside `LIT`; the lit box read 1.00 on every capture.
MAX_SPREAD = 20
LIT = (150, 220)
MIN_UNTICKED = 0.9
TICKED = "ticked"
UNTICKED = "unticked"
# Parked on the task while a dialog stays up: the name of the dialog whose box was tapped, and whether a tap that did not
# take has been logged.
TAPPED = "_en_dont_show_tapped"
NOT_TAKEN_LOGGED = "_en_dont_show_not_taken_logged"

_patched = False


def box_state(frame, spot):
    """Read a "Do not show" box off the frame.

    Args:
        frame: The current capture, or None when there is none.
        spot: The box's centre as `(x, y)` screen fractions.

    Returns:
        TICKED, UNTICKED for a lit grey box, or None for anything else: dimmed, another colour or no frame.
    """
    x, y = spot
    half_x, half_y = PATCH_HALF
    patch = patch_of(frame, (x - half_x, y - half_y, x + half_x, y + half_y))
    if patch is None or patch.size == 0:
        return None
    if colour_share(patch, TICK_LOW, TICK_HIGH) >= MIN_TICKED:
        return TICKED
    brightest = patch.max(axis=2).astype(int)
    neutral = (brightest - patch.min(axis=2) < MAX_SPREAD) & (brightest >= LIT[0]) & (brightest <= LIT[1])
    return UNTICKED if neutral.mean() >= MIN_UNTICKED else None


def shown_tick(task):
    """Find which of the three dialogs is up.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        The `(dialog, spot)` pair from `TICKS`, or None when none is on screen.
    """
    return next(((dialog, spot) for dialog, spot in TICKS if shown(task, dialog)), None)


def handle_dont_show_again(task):
    """Tap the "Do not show" box once on a Story skip dialog or Battle Prep, and leave the confirm to the handlers after.

    Args:
        task: The running task, whose `all_texts` and `frame` hold the current reading.

    Returns:
        True when the box was tapped, which claims the frame. False on every other frame, so the dialog is confirmed as before.
    """
    found = shown_tick(task)
    if found is None:
        setattr(task, TAPPED, None)
        setattr(task, NOT_TAKEN_LOGGED, False)
        return False
    dialog, spot = found
    # Both already stop the run further on; a box is never ticked on a dialog either would stop on.
    if rescue_marker(task) or risky_confirm(task):
        return False
    if box_state(frame_of(task), spot) != UNTICKED:
        return False
    if getattr(task, TAPPED, None) == dialog.name:
        # One tap per appearance: a box that ignores it is confirmed unticked, rather than tapped on every frame.
        if not getattr(task, NOT_TAKEN_LOGGED, False):
            setattr(task, NOT_TAKEN_LOGGED, True)
            task.log_info(f"the Do not show tick on the {dialog.name} did not take, confirming it unticked")
        return False
    task.log_info(f"ticking Do not show on the {dialog.name}")
    setattr(task, TAPPED, dialog.name)
    tap(task, spot)
    return True


def install():
    """Put the tick just ahead of the centred Confirm in every list holding it.

    Daily's list holds no centred Confirm, so it gets nothing.
    """
    insert_before("handle_center_confirm", handle_dont_show_again)


def apply():
    """Tick "Do not show" on both Story skip dialogs and Battle Prep before they are confirmed."""
    global _patched
    if _patched:
        return
    register(install)
    _patched = True
