"""Keep upstream's Enter handler on the one button that means Enter on the Global client.

Upstream presses any "进入" across the bottom fifth of the screen. The Global client captions its round action button
"Enter", and since the 2026-10-01 update it also prints an "Enter" key hint on Select and Confirm buttons, which
upstream pressed before the screen's own handler had picked anything. On a Sortie event the round button attacks the
object, so it is also left alone while an option is offered. Story mode keeps upstream's handler as it is.

Upstream also takes every Enter it presses for the start of a new run and resets the run's records. Inside a Chaos run the
round button belongs to the event on screen: it is pressed only once it lights up, and the run's records carry on.

Two Chaos screens show their "Enter" away from that button, where no other handler presses it: the Entry Guide dialog
that asks whether to enter at the current difficulty, and the Exploration record notice after a run's last Leave. Each
is pressed on its own Enter only, once its own line and that button are both read.
"""

import re

import numpy as np
from ok import Logger

from src.en.handlers import insert_before, loaded, register, standing_in, wrap
from src.en.screen import centre_of, colour_share, frame_of, in_region, patch_of
from src.en.spend_guard import Dialog, cleaned, folded, shown

logger = Logger.get_logger(__name__)

# Names this change in the shared record of what a function already carries, so it is applied once.
TAG = "the Enter button only"
# What the catalog turns the client's "Enter" into.
ENTER = "进入"
# The round action button. All 72 Enter presses in a month of pre-update logs landed at x 0.937-0.946, y 0.898-0.923,
# and the key hints on other buttons sit left of 0.87 - the Select button's is at 0.844.
BUTTON = (0.90, 0.85, 1.0, 1.0)
# Upstream's event option templates, the band it reads them from and its cutoff, as `recognize_event_options` has them.
# Of 64 captures showing one, only the Sortie rally-signal event also has the button's "Enter" up.
OPTION_TEMPLATES = [f"event{number}" for number in range(1, 9)]
OPTION_BAND = (0.198, 0.840, 0.803, 1.000)
OPTION_THRESHOLD = 0.70
# The mode whose Enter is a wide bar on the chapter panel, centred at (0.817, 0.930) - among the key hints, so no region
# can tell them apart.
STORY_MODE = "StoryMode"
CHAOS_MODE = "ChaosMode"
# The team's health, read at (0.211-0.212, 0.037-0.039) on all sixteen in-run captures saved with the round button up, and on
# neither The Blue Pot's detail nor the Formation, whose Enter starts a run. One capture read it with a full-width slash.
HEALTH_POINT = (0.209, 0.040)
HEALTH = re.compile(r"\d+\s*[/／]\s*\d+")
# Inside a run the button is a ring with crossed swords over its "Enter" hint, grey until the event lets it be pressed (the
# treasure room's until all three chests are open) and glowing magenta once it can. This patch above the hint, as offsets
# from the hint's centre, was 1.3-2.0% bright and saturated on two lit captures and 0% on fourteen grey ones of four events,
# the treasure room's purple backdrop among them.
RING = (-0.03, -0.11, 0.03, -0.01)
RING_LOW = np.array([0, 120, 180])
RING_HIGH = np.array([180, 255, 255])
RING_LIT = 0.005
# Parked on the task while a grey ring is up, so it is logged once rather than on every frame.
GREY_LOGGED = "_en_grey_enter_logged"
# "Chaos Manifestation Entry Guide", read off two captures: title at (0.501, 0.389), label at (0.521, 0.624), Cancel and Enter
# at y 0.745. Its "Do not show again for today." box is the user's choice, so it is never ticked here.
ENTRY_GUIDE = Dialog("Chaos Manifestation Entry Guide", "chaosmanifestationentryguide", True, (0.30, 0.34, 0.70, 0.44),
                     "donotshowagainfortoday", (0.40, 0.59, 0.66, 0.66), ("取消", ENTER), (0.25, 0.71, 0.75, 0.78))
# The notice after a run's last Leave, read off two captures: its line at (0.499, 0.153) over a reward card, and its own
# Enter hint at (0.501-0.502, 0.973).
RECORD_LINE = "unlockedexplorationrecordsappearasrewards"
RECORD_LINE_REGION = (0.25, 0.12, 0.75, 0.19)
RECORD_ENTER_REGION = (0.45, 0.95, 0.55, 1.0)
CHAOS_LIST = ("utils_chaos",)

_patched = False


def in_a_run(task, utils):
    """Say whether the screen is inside a Chaos run, by the team's health in the top left.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        utils: Upstream's `utils` module, for `find_box_at_point`.

    Returns:
        True when the health reads as two numbers either side of a slash.
    """
    if type(task).__name__ != CHAOS_MODE:
        return False
    box = utils.find_box_at_point(task, *HEALTH_POINT)
    return box is not None and HEALTH.search(box.name) is not None


def ring_lit(task, button):
    """Say whether the round button's ring above its Enter hint is lit.

    Args:
        task: The running task, whose frame holds the current screen.
        button: The Enter hint's OCR box.

    Returns:
        True when enough of the ring glows; False for a grey ring or a frame that cannot be read.
    """
    x, y = centre_of(button, task.width, task.height)
    left, top, right, bottom = RING
    patch = patch_of(frame_of(task), (x + left, y + top, x + right, y + bottom))
    return colour_share(patch, RING_LOW, RING_HIGH) >= RING_LIT


def press_in_run(task, button):
    """Press an event's Enter inside a run, the way upstream does, minus its reset of the run's records.

    Args:
        task: The running task.
        button: The Enter hint's OCR box.

    Returns:
        True when it was pressed, False while the ring is grey.
    """
    if not ring_lit(task, button):
        if not getattr(task, GREY_LOGGED, False):
            setattr(task, GREY_LOGGED, True)
            task.log_info("the event's Enter is grey, so it is left until the event lights it")
        return False
    task.log_info("pressing the event's Enter, inside the run, so the run's records carry on")
    task.click_box(button)
    task.sleep(1)
    return True


def on_the_button(utils):
    """Build the change that keeps `handle_enter` on the round button, and off it while an event option is up.

    Inside a Chaos run it presses the button itself, once lit, since upstream's press resets the run's records.

    Args:
        utils: Upstream's `utils` module, whose `_clean_match` is how `handle_enter` recognises "进入".

    Returns:
        A factory taking the handler currently installed and returning the one to run in its place.
    """
    def factory(original_handle_enter):
        def handle_enter(task):
            if type(task).__name__ == STORY_MODE:
                return original_handle_enter(task)
            button = next((box for box in task.all_texts
                           if utils._clean_match(box.name, ENTER) and in_region(box, BUTTON, task.width, task.height)), None)
            if button is None:
                setattr(task, GREY_LOGGED, False)
                return False
            if task.find_one(feature_name=OPTION_TEMPLATES, box=task.box_of_screen(*OPTION_BAND), threshold=OPTION_THRESHOLD):
                task.log_info("an event option is on screen, so Enter is left for the option to be chosen")
                return False
            if in_a_run(task, utils):
                return press_in_run(task, button)
            # Upstream reads nothing else off the screen, so showing it the button alone still lets it press it itself.
            with standing_in(task, all_texts=[button]):
                return original_handle_enter(task)

        return handle_enter

    return factory


def enter_box(task, region):
    """Find the "进入" box in a region.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        region: The region the button sits in, as screen fractions.

    Returns:
        The box, or None when it was not read there.
    """
    return next((box for box in task.all_texts if cleaned(box.name) == ENTER and in_region(box, region, task.width, task.height)), None)


def handle_entry_guide(task):
    """Press Enter on the Chaos Entry Guide, which asks whether to enter at the current difficulty.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when Enter was pressed, which claims the frame.
    """
    if not shown(task, ENTRY_GUIDE):
        return False
    task.log_info("Chaos Entry Guide, entering at the current difficulty")
    task.click_box(enter_box(task, ENTRY_GUIDE.buttons_region))
    return True


def handle_record_notice(task):
    """Close the Exploration record notice on its own Enter hint.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when Enter was pressed, which claims the frame.
    """
    if not any(RECORD_LINE in folded(box.name) and in_region(box, RECORD_LINE_REGION, task.width, task.height) for box in task.all_texts):
        return False
    button = enter_box(task, RECORD_ENTER_REGION)
    if button is None:
        return False
    task.log_info("Exploration record notice, closing it")
    task.click_box(button)
    return True


def install_chaos_screens():
    """Put both Chaos screens ahead of the centred Confirm, in Chaos's list only, since they are Chaos's own."""
    insert_before("handle_center_confirm", handle_entry_guide, only=CHAOS_LIST)
    insert_before("handle_center_confirm", handle_record_notice, only=CHAOS_LIST)


def install(utils):
    """Keep `handle_enter` on the round button wherever it is registered.

    Args:
        utils: Upstream's `utils` module, or None when it has not been imported yet.
    """
    if utils is None:
        return
    wrap(utils, "handle_enter", on_the_button(utils), TAG)


def apply():
    """Keep `handle_enter` on the round button, and press the Enter of the two Chaos screens that show it elsewhere."""
    global _patched
    if _patched:
        return
    register(lambda: install(loaded("utils")))
    register(install_chaos_screens)
    _patched = True
