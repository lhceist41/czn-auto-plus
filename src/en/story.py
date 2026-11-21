"""Press Skip and Auto on the top bar the Global client has drawn since its November 2026 update.

Upstream finds both by templates of the old bar, where Auto and Fast-Forward shared one amber button, and reads a battle's
Auto off one pixel of it. The update split them into a row of white icons - Skip, Auto, Fast-Forward, Menu - so Story
never skips and no battle has its Auto turned on.
"""

import time
from pathlib import Path

import cv2
import numpy as np

from ok import Logger

from src.en.board import icon_template
from src.en.handlers import insert_before, loaded, register, replace, wrap
from src.en.notify import announce
from src.en.screen import colour_share, frame_of, patch_of, text_in_region, white_mask

logger = Logger.get_logger(__name__)

# The Skip, Auto and Fast-Forward icons, cut from a 1080p capture with Auto and Fast-Forward off.
SKIP_IMAGE = Path(__file__).with_name("images") / "story_skip.png"
AUTO_IMAGE = Path(__file__).with_name("images") / "story_auto.png"
FAST_FORWARD_IMAGE = Path(__file__).with_name("images") / "story_fast_forward.png"
# Where the bar sits, as `(left, top, right, bottom)` screen fractions. It spans x 1405-1920 and y 24-90 at 1080p.
BAR = (0.70, 0.0, 1.0, 0.10)
# How closely each icon has to match. Both scored 0.99 or more on the bar they were cut from, and Skip 0.80-0.85 on tinted
# and dark scenes, which change how much of the icon's edge passes the white mask. Over the 847 pre-update captures in
# `captures/` Skip's best was 0.52 and Auto's 0.74. Auto still scores 0.91 when lit, which is why its colour is read as well.
# Fast-Forward scored 0.98-1.00 off, 0.58-0.71 lit and 0.42 at most on the old captures, so it shares Auto's bar.
SKIP_MATCH = 0.7
BUTTON_MATCH = 0.8
# The Auto and Fast-Forward buttons, as `(left, top, right, bottom)` screen fractions. Each glows amber while on.
AUTO_REGION = (0.814, 0.024, 0.847, 0.081)
FAST_FORWARD_REGION = (0.878, 0.024, 0.912, 0.081)
# The amber the lit button is drawn in, as OpenCV HSV bounds - the same as the old combined button's.
GLOW_LOW = np.array((10, 20, 120), dtype=np.uint8)
GLOW_HIGH = np.array((35, 255, 255), dtype=np.uint8)
# Amber share of a button's region that means it is on. Auto read 0.377 lit, Fast-Forward 0.186-0.243, and both 0.000 off.
MIN_GLOW = 0.05
# How long the button gets to notice the pointer, and then to act, before the screen is read again.
AFTER_HOVER = 0.3
AFTER_TAP = 1
# How long to leave Fast-Forward alone after tapping it, so a scene that will not let it turn on is not tapped every frame.
FAST_FORWARD_RETRY = 30
# Set on the task: when Fast-Forward was last tapped.
FAST_FORWARD_TAPPED = "_en_fast_forward_tapped"
# The Team Formation title, and the level label every filled slot shows under its combatant.
TEAM_TITLE = "主战员配置"
LEVEL_LABEL = "等级"
# Where they sit, as `(left, top, right, bottom)` screen fractions. The title read at (0.154, 0.044). Slot 1's label read at
# (0.056, 0.605) on a battle's formation and at (0.056, 0.766) on a Chaos stage's, whose cards are taller, with the other
# two slots ~0.215 further right each, so each slot spans both.
TEAM_TITLE_REGION = (0.0, 0.0, 0.35, 0.09)
TEAM_SLOTS = ((0.0, 0.55, 0.16, 0.82), (0.17, 0.55, 0.37, 0.82), (0.38, 0.55, 0.58, 0.82))
# The `LV` plate over that label, cut from a lit card. OCR missed the label on one to two of three filled cards under the
# tutorial's dimming, where the plate still scored 0.947-1.000 (dimmed and lit), and at most 0.706 in those regions on the
# 295 other captures of the tutorial run.
LEVEL_PLATE_IMAGE = Path(__file__).with_name("images") / "team_level.png"
LEVEL_PLATE_MATCH = 0.85

_patched = False


def find_icon(frame, path, threshold, region=BAR, mask=white_mask):
    """Find one of the bar's icons in the frame.

    Args:
        frame: The current capture, or None when there is none.
        path: The icon's image file, such as `SKIP_IMAGE`.
        threshold: The lowest score that counts as the icon, such as `SKIP_MATCH`.
        region: Where to look, as `(left, top, right, bottom)` screen fractions. The whole bar unless the caller narrows it.
        mask: Reduces both the icon and the frame to the pixels they are matched on, the near-white ones by default.

    Returns:
        The icon's centre as `(x, y)` screen fractions, or None when it is not there.
    """
    patch = patch_of(frame, region)
    if patch is None:
        return None
    template = icon_template(path, frame.shape[0], mask)
    if template is None or patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return None
    _, score, _, (left, top) = cv2.minMaxLoc(cv2.matchTemplate(mask(patch), template, cv2.TM_CCOEFF_NORMED))
    if score < threshold:
        return None
    height, width = frame.shape[:2]
    return ((region[0] * width + left + template.shape[1] / 2) / width, (region[1] * height + top + template.shape[0] / 2) / height)


def button_off(frame, path, region):
    """Find one of the bar's on/off buttons while it is off.

    Args:
        frame: The current capture, or None when there is none.
        path: The button's icon file, such as `AUTO_IMAGE`.
        region: Where the button glows when on, as `(left, top, right, bottom)` screen fractions, such as `AUTO_REGION`.

    Returns:
        The button's centre as `(x, y)` screen fractions, or None when it is lit, locked or not drawn.
    """
    point = find_icon(frame, path, BUTTON_MATCH)
    if point is None or colour_share(patch_of(frame, region), GLOW_LOW, GLOW_HIGH) >= MIN_GLOW:
        return None
    return point


def auto_off(frame):
    """Find Auto on the bar while it is off.

    Args:
        frame: The current capture, or None when there is none.

    Returns:
        The button's centre as `(x, y)` screen fractions, or None when it is lit, locked or not drawn.
    """
    return button_off(frame, AUTO_IMAGE, AUTO_REGION)


def tap(task, point):
    """Hover a bar button and then tap it, as upstream taps every button.

    Args:
        task: The running task.
        point: The button's centre as `(x, y)` screen fractions, from `find_icon`.
    """
    task.move_relative(*point)
    task.sleep(AFTER_HOVER)
    task.click(*point, after_sleep=AFTER_TAP)


def handle_skip_story(task):
    """Press Skip on the dialogue bar. The confirmation it raises is left to `handle_center_confirm`.

    Args:
        task: The running task, whose `frame` holds the current capture.

    Returns:
        True when Skip was pressed, which claims the frame.
    """
    point = find_icon(frame_of(task), SKIP_IMAGE, SKIP_MATCH)
    if point is None:
        return False
    task.log_info("dialogue bar showing, pressing Skip")
    tap(task, point)
    return True


def handle_auto_chat(task):
    """Turn Auto on, for a scene that draws the bar but offers no Skip.

    Args:
        task: The running task, whose `frame` holds the current capture.

    Returns:
        True when Auto was off and has been tapped, which claims the frame.
    """
    point = auto_off(frame_of(task))
    if point is None:
        return False
    task.log_info("dialogue Auto is off, turning it on")
    tap(task, point)
    return True


def handle_fast_forward(task):
    """Turn Fast-Forward on wherever the bar shows it off, in dialogue and battles alike.

    Args:
        task: The running task, whose `frame` holds the current capture.

    Returns:
        True when Fast-Forward was off and has been tapped, which claims the frame.
    """
    if time.monotonic() - getattr(task, FAST_FORWARD_TAPPED, float("-inf")) < FAST_FORWARD_RETRY:
        return False
    point = button_off(frame_of(task), FAST_FORWARD_IMAGE, FAST_FORWARD_REGION)
    if point is None:
        return False
    task.log_info("Fast-Forward is off, turning it on")
    setattr(task, FAST_FORWARD_TAPPED, time.monotonic())
    tap(task, point)
    return True


def turning_auto_on(auto_check):
    """Wrap upstream's battle Auto check so it turns on the new bar's Auto, which its pixel check no longer sees.

    Args:
        auto_check: Upstream's `handle_battle_auto_check`, shared by Chaos and Story, which still owns the battle gate,
            the Start Attack tap and the final boss flag.

    Returns:
        The wrapper, answering whatever upstream answered.
    """
    def handle_battle_auto_check(task):
        on_battle = auto_check(task)
        point = auto_off(frame_of(task)) if on_battle else None
        if point is not None:
            task.log_info("battle Auto is off, turning it on")
            tap(task, point)
        return on_battle

    return handle_battle_auto_check


def grey(patch):
    """Reduce a patch to its brightness, so the level plate matches lit and dimmed alike.

    Args:
        patch: The pixels to reduce, in BGR.

    Returns:
        A single-channel image.
    """
    return cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)


def team_formation(task):
    """Say whether the screen is Team Formation.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when the title is on screen.
    """
    return text_in_region(task, TEAM_TITLE, TEAM_TITLE_REGION) is not None


def filled_slots(task):
    """Count the Team Formation slots holding a combatant, by the level label OCR read or the plate drawn over it.

    Args:
        task: The running task, whose `all_texts` and `frame` hold the current screen.

    Returns:
        How many of the three slots are filled.
    """
    frame = frame_of(task)
    return sum(
        text_in_region(task, LEVEL_LABEL, slot) is not None or find_icon(frame, LEVEL_PLATE_IMAGE, LEVEL_PLATE_MATCH, slot, grey) is not None
        for slot in TEAM_SLOTS
    )


def handle_team_formation(task):
    """Stop Story on a Team Formation screen with an empty slot, which upstream would press Enter on forever.

    Args:
        task: The running task, whose `all_texts` and `frame` hold the current screen.

    Returns:
        True when the team is short and the task has been stopped, which claims the frame.
    """
    if not team_formation(task):
        return False
    filled = filled_slots(task)
    if filled == len(TEAM_SLOTS):
        return False
    announce(task, f"Team Formation has {filled} of {len(TEAM_SLOTS)} combatants. Fill the team, then start Story again.")
    task.disable()
    return True


def install():
    """Put the new bar's Skip and Auto in place of upstream's, turn Fast-Forward on, and stop Story on a short team or off the story."""
    # Ahead of the battle handlers, which claim every frame of a fight while the bar shows through all of it.
    insert_before("handle_center_confirm", handle_fast_forward)
    replace("handle_skip_story", handle_skip_story)
    replace("handle_auto_chat", handle_auto_chat)
    insert_before("handle_enter", handle_team_formation, only=("utils_story",))
    utils = loaded("utils")
    if utils is not None:
        # The lobby, Rescue and Ark City stop that ends Chaos and Sortie, ahead of the handlers that enter a story or a battle.
        insert_before("handle_story_complete", utils.handle_non_battle_page, only=("utils_story",))
    utils_chaos = loaded("utils_chaos")
    if utils_chaos is not None:
        wrap(utils_chaos, "handle_battle_auto_check", turning_auto_on, "new bar Auto")


def apply():
    """Have the modes press the new top bar's Skip, Auto and Fast-Forward."""
    global _patched
    if _patched:
        return
    register(install)
    _patched = True
