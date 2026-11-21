"""Keep upstream's Enter handler on the one button that means Enter on the Global client.

Upstream presses any "进入" across the bottom fifth of the screen. The Global client captions its round action button
"Enter", and since the 2026-10-01 update it also prints an "Enter" key hint on Select and Confirm buttons, which
upstream pressed before the screen's own handler had picked anything. On a Sortie event the round button attacks the
object, so it is also left alone while an option is offered. Story mode keeps upstream's handler as it is.

Two Chaos screens show their "Enter" away from that button, where no other handler presses it: the Entry Guide dialog
that asks whether to enter at the current difficulty, and the Exploration record notice after a run's last Leave. Each
is pressed on its own Enter only, once its own line and that button are both read.
"""

from ok import Logger

from src.en.handlers import insert_before, loaded, register, standing_in, wrap
from src.en.screen import in_region
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


def on_the_button(utils):
    """Build the change that keeps `handle_enter` on the round button, and off it while an event option is up.

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
                return False
            if task.find_one(feature_name=OPTION_TEMPLATES, box=task.box_of_screen(*OPTION_BAND), threshold=OPTION_THRESHOLD):
                task.log_info("an event option is on screen, so Enter is left for the option to be chosen")
                return False
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
