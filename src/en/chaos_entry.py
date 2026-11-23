"""Walk Chaos from the Lobby to The Blue Pot's Team Formation, or back into a run left open.

Upstream starts Chaos only on the Team Formation or inside a run, and stops it on the Lobby. Started on the Lobby (its UI
shown or faded), the Chaos hub, the Chaos Manifestation map or the prompt to resume an open run, Chaos now presses the one
caption each of those screens leads on with: the Lobby's Chaos, the hub's Chaos Manifestation, the map's The Blue Pot and
the prompt's Enter. The Blue Pot's detail and the Formation are pressed by `handle_enter` as before. A target pressed three
times without the screen moving on, a refused word under a press, and a map without The Blue Pot stop the run. A run Story handed over never walks.

The resume prompt also carries Escape, which abandons the open run, and Cancel. Only the Enter box read left of both is
ever pressed there.
"""

import time
from collections import Counter

from ok import Logger

from src.en import daily
from src.en.enter import BUTTON, enter_box
from src.en.handlers import insert_before, register
from src.en.runs import forgetting, stop
from src.en.screen import centre_of, frame_of, in_region, text_in_region
from src.en.spend_guard import cleaned, folded
from src.en.story import find_icon, grey, tap
from src.en.story_relay import RELAYED

logger = Logger.get_logger(__name__)

CHAOS_MODE = "ChaosMode"
CHAOS_LIST = ("utils_chaos",)
# Every walk handler goes just ahead of this one, so the auto stop, the stuck stop and the hold still see each frame first.
ANCHOR = "handle_close_page"

# What the walk presses, by name, and how often each may be pressed in one run.
LOBBY_CHAOS = "the Lobby's Chaos"
WAKE = "the faded Lobby's sky"
HUB_CARD = "the Chaos hub's Chaos Manifestation"
PLANET = "the map's The Blue Pot"
RESUME_ENTER = "the resume prompt's Enter"
TAP_LIMIT = 3

# What the catalog turns the client's captions into. `Chaos`, `The Blue Pot` and the prompt's line are read as English.
MANIFESTATION = "卡厄思显现"
CHAOS = "chaos"
BLUE_POT = "thebluepot"
# The Lobby's Chaos caption, read at (0.891, 0.442) and as `日 Chaos` at (0.883, 0.440), its icon taken for a glyph.
LOBBY_CHAOS_REGION = (0.85, 0.41, 0.93, 0.47)
# The Chaos hub: its title read at (0.112, 0.047), its Chaos Manifestation card's label at (0.244-0.245, 0.800-0.801).
# The Zero System card's label at (0.710, 0.801) is never pressed.
HUB_TITLE_REGION = (0.05, 0.02, 0.20, 0.08)
HUB_CARD_REGION = (0.15, 0.75, 0.40, 0.85)
# The Chaos Manifestation map: its title at (0.176, 0.047), `Content Introduction` at (0.881, 0.136) and The Blue Pot at
# (0.320, 0.676). The Blue Pot's detail keeps the title and names the planet at (0.760, 0.215), with no Content
# Introduction and its own Enter at (0.935, 0.899).
MAP_TITLE_REGION = (0.08, 0.02, 0.30, 0.08)
MAP_INTRODUCTION = ("Content Introduction", (0.80, 0.10, 0.95, 0.17))
PLANET_REGION = (0.20, 0.62, 0.50, 0.72)
# The prompt a Chaos run still open raises on the way in: `Do you wish to enter the stage in progress?` at (0.501, 0.828),
# Cancel at (0.369, 0.907), Enter at (0.637, 0.907) and Escape, which abandons the run, at (0.898, 0.910).
RESUME_LINE = "enterthestageinprogress"
RESUME_LINE_REGION = (0.30, 0.79, 0.70, 0.87)
RESUME_ENTER_REGION = (0.55, 0.87, 0.72, 0.95)
# Right of this the Lobby writes its captions, Story to Combatants, and the right of its top bar. A faded Lobby reads at
# most a speech bubble, read at (0.258, 0.278).
CAPTION_SIDE = 0.70

# Parked on Chaos for one run: how often each target was pressed, and when the faded Lobby was last woken.
TAPS = "_en_chaos_walk_taps"
WOKEN = "_en_chaos_walk_woken"
MARKS = (TAPS, WOKEN)

NO_PLANET = "Stopped: Chaos could not find The Blue Pot on the Chaos Manifestation map. Open it in the game, then press Start again."

_patched = False


def walking(task):
    """Say whether the walk may act for this task: Chaos only, and never a run Story handed over."""
    return type(task).__name__ == CHAOS_MODE and not getattr(task, RELAYED, False)


def box_in(task, matches, region):
    """Find the first box in a region whose text passes a test.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.
        matches: Takes a box's text and says whether it is the one wanted.
        region: A `(left, top, right, bottom)` tuple in screen fractions.

    Returns:
        The box, or None.
    """
    return next((box for box in getattr(task, "all_texts", None) or []
                 if matches(box.name) and in_region(box, region, task.width, task.height)), None)


def reads_chaos(text):
    """Say whether a box reads `Chaos` alone, or behind the one glyph OCR makes of the Lobby's icon.

    Exact rather than a substring: the map's other planets read `Unconfirmed Chaos`.
    """
    text = cleaned(text)
    return text == CHAOS or (len(text) == len(CHAOS) + 1 and text.endswith(CHAOS) and not text[0].isascii())


def reads_manifestation(text):
    """Say whether a box reads the catalog's Chaos Manifestation."""
    return cleaned(text) == MANIFESTATION


def reads_blue_pot(text):
    """Say whether a box reads The Blue Pot."""
    return cleaned(text) == BLUE_POT


def resume_prompt(task):
    """Say whether the prompt to enter a run still open shows its line."""
    return box_in(task, lambda text: RESUME_LINE in folded(text), RESUME_LINE_REGION) is not None


def press(task, target, point, box=None):
    """Press one walk target, unless its limit is reached or what lies under it must never be pressed.

    Args:
        task: The Chaos task.
        target: The target's name, as the stop line gives it.
        point: Where to tap, as `(x, y)` screen fractions.
        box: The OCR box pressed, None for a fixed point.

    Returns:
        True, which claims the frame: the target was pressed, or Chaos has stopped.
    """
    taps = vars(task).setdefault(TAPS, Counter())
    if taps[target] >= TAP_LIMIT:
        return stop(task, f"Stopped: Chaos pressed {target} {taps[target]} times and the screen did not move on. Check the game, then press Start again.")
    for hit in ([box] if box is not None else []) + daily.boxes_at(task, point):
        marker = daily.refused(hit.name)
        if marker:
            task.log_info(f"not pressing {target}: the box there reads {hit.name!r} ({marker!r})")
            return stop(task, f"Stopped: Chaos would have pressed {hit.name!r} for {target}. Check the game, then press Start again.")
    taps[target] += 1
    task.log_info(f"on the way into Chaos, pressing {target}")
    tap(task, point)
    return True


def press_box(task, target, box):
    """Press a walk target on the box OCR read for it."""
    return press(task, target, centre_of(box, task.width, task.height), box)


def handle_resume_prompt(task):
    """Enter the Chaos run still open, on the prompt's Enter, and on nothing else that prompt shows.

    With the line read and its Enter not, the frame is held with nothing pressed, so no handler further down taps the
    prompt; the stuck stop ends a prompt that never reads its Enter.
    """
    if not walking(task) or not resume_prompt(task):
        return False
    button = enter_box(task, RESUME_ENTER_REGION)
    if button is None:
        return True
    task.log_info("a Chaos run is still open, entering it again")
    return press_box(task, RESUME_ENTER, button)


def handle_manifestation_planet(task):
    """Open The Blue Pot from the Chaos Manifestation map, or stop on a map that does not show it."""
    if not walking(task) or box_in(task, reads_manifestation, MAP_TITLE_REGION) is None:
        return False
    if enter_box(task, BUTTON) is not None or resume_prompt(task):
        return False
    planet = box_in(task, reads_blue_pot, PLANET_REGION)
    if planet is not None:
        return press_box(task, PLANET, planet)
    # Only the map itself is a reason to stop: its title alone also shows while The Blue Pot's detail draws in.
    if text_in_region(task, *MAP_INTRODUCTION) is None:
        return False
    return stop(task, NO_PLANET)


def handle_chaos_hub(task):
    """Open Chaos Manifestation from the Chaos hub."""
    if not walking(task) or box_in(task, reads_chaos, HUB_TITLE_REGION) is None:
        return False
    card = box_in(task, reads_manifestation, HUB_CARD_REGION)
    if card is None:
        return False
    return press_box(task, HUB_CARD, card)


def handle_chaos_lobby(task):
    """Open the Chaos hub from the Lobby. Without its Chaos caption read, upstream's Lobby stop follows."""
    if not walking(task) or not daily.on_lobby(task):
        return False
    caption = box_in(task, reads_chaos, LOBBY_CHAOS_REGION)
    if caption is None:
        return False
    return press_box(task, LOBBY_CHAOS, caption)


def handle_chaos_faded_lobby(task):
    """Bring back the UI of a Lobby that has faded out, told by its scene, at most once every `daily.WAKE_WAIT` seconds.

    Daily's own wake asks for a screen reading nothing, which a speech bubble over the faded Lobby defeats. Here the scene
    decides, with one confident line allowed away from where the Lobby writes its captions.
    """
    if not walking(task) or daily.showing(task, daily.LOBBY_STORY) is not None:
        return False
    confident = [box for box in getattr(task, "all_texts", None) or []
                 if box.name.strip() and getattr(box, "confidence", 1.0) >= daily.FADED_CONFIDENCE]
    if len(confident) > 1 or any(centre_of(box, task.width, task.height)[0] >= CAPTION_SIDE for box in confident):
        return False
    if find_icon(frame_of(task), daily.FADED_SCENE_IMAGE, daily.FADED_SCENE_MATCH, daily.FADED_SCENE_REGION, grey) is None:
        return False
    now = time.monotonic()
    woken = vars(task).get(WOKEN)
    if woken is not None and now - woken < daily.WAKE_WAIT:
        return True
    vars(task)[WOKEN] = now
    return press(task, WAKE, daily.TARGETS[daily.WAKE])


# The prompt first, since it opens over the map, then each screen of the way in, last to first.
HANDLERS = (handle_resume_prompt, handle_manifestation_planet, handle_chaos_hub, handle_chaos_lobby, handle_chaos_faded_lobby)


def install():
    """Put the walk ahead of the close-page tap in Chaos's list, behind the stops and the hold."""
    for handler in HANDLERS:
        insert_before(ANCHOR, handler, only=CHAOS_LIST)


def apply():
    """Have Chaos walk from the Lobby to The Blue Pot's Team Formation."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, the walk's tap counts will carry over between runs")
    else:
        # Every start and every stop begins the walk afresh.
        BaseTask.enable = forgetting(MARKS, BaseTask.enable)
        BaseTask.disable = forgetting(MARKS, BaseTask.disable)
    register(install)
    _patched = True
