"""Never tap the tutorial's Skip Tutorial button, in any mode.

While the tutorial runs, a button reading Skip Tutorial covers the top right corner, over the Lobby's Menu, the
banner's X, the bar's Auto and Fast-Forward and most pages' close X, and a tap on it skips the tutorial for good. No
handler aims at it, but several tap fixed points under it on other cues. Every tap, press and drag end in that corner
is now checked against the button first: while it shows, the input is refused, announced and the run stopped. Without
the button, and anywhere else on the screen, input goes exactly as before.
"""

import contextlib
import threading

import cv2

from ok import Logger
from ok.feature.Box import Box
from ok.task.exceptions import TaskDisabledException

from src.en.handlers import WRAPS
from src.en.notify import announce
from src.en.screen import text_in_region

logger = Logger.get_logger(__name__)

CAPTION = ("Skip Tutorial", (0.0, 0.0, 1.0, 1.0))
# The button's outline, measured on every capture that shows it.
OUTLINE = (0.818, 0.020, 0.992, 0.091)
# The outline widened by 0.01 on each side, for the spread a click is given and the outline's own edge.
GUARDED = (0.808, 0.010, 1.0, 0.101)
# The outline is drawn bright enough to stand apart from every screen it sits on. The detector was measured on 1080p
# captures, so a frame of another size is scaled to that first.
REFERENCE = (1920, 1080)
RING_CROP = (1400, 0, 1920, 170)
RING_MIN_VALUE = 170
RING_TOLERANCE = 0.006

STOP_MESSAGE = "Stopped before a tap on Skip Tutorial, which would skip the tutorial for good. Play past this screen yourself, then press Start again."
TAG = "no input on Skip Tutorial"
# Set on a task this refused, so input the stopped run still tries before it unwinds is refused too.
STOPPED = "_en_skip_tutorial_stopped"

_patched = False
_operator = threading.local()


@contextlib.contextmanager
def operating():
    """Mark input as the operator's for the length of a block: it is logged when it lands on the button, never refused."""
    _operator.depth = getattr(_operator, "depth", 0) + 1
    try:
        yield
    finally:
        _operator.depth -= 1


def guarded(task, x, y):
    """Say whether a frame point lies in the corner the button covers.

    Args:
        task: The running task, for the frame size.
        x: The frame x in pixels.
        y: The frame y in pixels.

    Returns:
        True inside the widened outline.
    """
    left, top, right, bottom = GUARDED
    return left <= x / task.width <= right and top <= y / task.height <= bottom


def ring_shown(frame):
    """Find the button's bright outline on a frame.

    Args:
        frame: A BGR or BGRA frame.

    Returns:
        True when a bright shape matches the outline's box.
    """
    height, width = frame.shape[:2]
    if (width, height) != REFERENCE:
        frame = cv2.resize(frame, REFERENCE)
    x0, y0, x1, y1 = RING_CROP
    crop = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY if crop.ndim == 3 and crop.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    count, _, stats, _ = cv2.connectedComponentsWithStats((gray > RING_MIN_VALUE).astype("uint8"), 8)
    ref_width, ref_height = REFERENCE
    for index in range(1, count):
        left, top, w, h, _ = stats[index]
        box = ((x0 + left) / ref_width, (y0 + top) / ref_height, (x0 + left + w) / ref_width, (y0 + top + h) / ref_height)
        if all(abs(found - outline) <= RING_TOLERANCE for found, outline in zip(box, OUTLINE)):
            return True
    return False


def caption_read(task):
    """Say whether the current OCR pass reads the button.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when Skip Tutorial is read anywhere on the frame.
    """
    return text_in_region(task, *CAPTION) is not None


def showing(task):
    """Say whether the button shows, by its caption or, on a fresh frame, by its outline.

    The fresh frame catches a caption the OCR pass missed or was narrowed away from, and a button that came up after
    the handler read the screen.

    Args:
        task: The running task.

    Returns:
        True when the button shows, and also when no frame can be had to check, since the tap would be blind.
    """
    if caption_read(task):
        return True
    held = task.executor.nullable_frame()
    fresh = task.next_frame()
    frame = fresh if fresh is not None else held
    if frame is None:
        logger.warning("no frame to check for Skip Tutorial before a tap in its corner")
        return True
    return ring_shown(frame)


def check(task, points, what):
    """Refuse input that would land on the button while it shows.

    Args:
        task: The running task.
        points: The frame points in pixels the input presses or lets go at.
        what: What the input is, for the log.

    Raises:
        TaskDisabledException: The input was refused and the run stopped, or the run was already stopped here.
    """
    inside = [point for point in points if guarded(task, *point)]
    if getattr(_operator, "depth", 0):
        held = task.executor.nullable_frame() if inside else None
        if inside and (caption_read(task) or (held is not None and ring_shown(held))):
            logger.warning(f"operator {what} at {inside[0]} lands on Skip Tutorial, sent as asked")
        return
    if getattr(task, STOPPED, False):
        if not task.enabled:
            raise TaskDisabledException()
        setattr(task, STOPPED, False)
    if not inside or not showing(task):
        return
    x, y = inside[0]
    task.log_info(f"refusing a {what} at ({x / task.width:.3f}, {y / task.height:.3f}): Skip Tutorial shows there")
    announce(task, STOP_MESSAGE)
    setattr(task, STOPPED, True)
    task.disable()
    raise TaskDisabledException()


def guarding_click(original):
    """Wrap `click`, which every tap reaches with frame pixels, through `click_box` and `click_relative` alike.

    Args:
        original: The class's `click`.

    Returns:
        The wrapped method.
    """
    def click(self, x=-1, y=-1, *args, **kwargs):
        # A box or a fraction comes back through here as pixels, which is when it is checked.
        if not (isinstance(x, (Box, list)) or 0 < x < 1 or 0 < y < 1):
            check(self, [(x, y)], "tap")
        return original(self, x, y, *args, **kwargs)

    return click


def guarding_swipe(original):
    """Wrap `swipe`, which `swipe_relative` reaches with frame pixels, at both ends.

    Args:
        original: The class's `swipe`.

    Returns:
        The wrapped method.
    """
    def swipe(self, from_x, from_y, to_x, to_y, *args, **kwargs):
        check(self, [(from_x, from_y), (to_x, to_y)], "drag")
        return original(self, from_x, from_y, to_x, to_y, *args, **kwargs)

    return swipe


def guarding_press(original):
    """Wrap `mouse_down`, the start of a long press.

    Args:
        original: The class's `mouse_down`.

    Returns:
        The wrapped method.
    """
    def mouse_down(self, x=-1, y=-1, *args, **kwargs):
        check(self, [(x, y)], "press")
        return original(self, x, y, *args, **kwargs)

    return mouse_down


GUARDS = {"click": guarding_click, "swipe": guarding_swipe, "mouse_down": guarding_press}


def install(operations):
    """Wrap the input primitives every task inherits, once however often this runs.

    Args:
        operations: ok-script's `ExecutorOperation`, where every mode's taps, drags and presses are defined.
    """
    for name, factory in GUARDS.items():
        current = getattr(operations, name)
        if TAG in getattr(current, WRAPS, ()):
            continue
        wrapped = factory(current)
        wrapped.__name__ = current.__name__
        setattr(wrapped, WRAPS, (*getattr(current, WRAPS, ()), TAG))
        setattr(operations, name, wrapped)


def apply():
    """Refuse every tap, press and drag end on Skip Tutorial while it shows, and stop the run."""
    global _patched
    if _patched:
        return
    from ok.task.task import ExecutorOperation

    install(ExecutorOperation)
    _patched = True
    logger.info("taps, presses and drags on Skip Tutorial are refused while it shows")
