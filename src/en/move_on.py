"""Move on from a navigation tap as soon as its caption has left the screen.

Upstream's Confirm, Continue, Leave, Next, Settlement and tap-the-screen handlers tap their caption, then wait a fixed
second or two whatever the game does: `click_box`'s one-second `after_sleep`, then most of them sleep a second more.
That wait now looks at the tapped caption on fresh frames and ends once it has gone, never later than upstream's own
wait, and never with a second tap. A caption that stays, or a place that cannot be read, gets the full wait as before.
"""

import time

from ok import Logger
from ok.task.exceptions import FinishedException, TaskDisabledException

from src.en.handlers import loaded, register, standing_in, wrap

logger = Logger.get_logger(__name__)

# Names this change in the shared record of what a function already carries, so it is applied once.
TAG = "moves on once its caption goes"
# Upstream's navigation handlers. Nothing that buys, removes or equips is here: those taps keep upstream's wait whole.
HANDLERS = ("handle_confirm", "handle_continue", "handle_leave", "handle_next_step", "handle_settlement", "handle_close_page")
# Seconds between looks at the caption's place.
LOOK_EVERY = 0.2
# Looks in a row that must find the place empty, so one frame where OCR misses a caption still shown does not end the wait.
GONE_AFTER = 2
# How far around the caption's box a look reads, in caption heights, so a caption drawn a few pixels off is still found.
MARGIN = 1.0

# The clock the wait is measured on, here so a test can run it without real time passing.
clock = time.monotonic

_patched = False


def fold(text):
    """Reduce a caption to what two reads of it share.

    Args:
        text: The text OCR read.

    Returns:
        The text lowercased, without spaces.
    """
    return "".join((text or "").split()).lower()


def centre_inside(box, outer):
    """Tell whether a box's centre lies within another box.

    Args:
        box: The OCR box read on the latest look.
        outer: The caption's box as the tapped frame read it.

    Returns:
        True when the centre falls inside.
    """
    x, y = box.x + box.width / 2, box.y + box.height / 2
    return outer.x <= x <= outer.x + outer.width and outer.y <= y <= outer.y + outer.height


class CaptionWatch:
    """Stands in for one handler's taps and waits, turning the wait after its tap into looks at the caption."""

    def __init__(self, task):
        """Hold what the handler would otherwise have called.

        Args:
            task: The running task.
        """
        self.task = task
        self.sleep_on = task.sleep
        self.click_on = task.click
        self.click_box_on = task.click_box
        self.aimed = None
        self.inner = 0
        self.caption = None
        self.tapped_at = None
        self.watching = True
        self.gone = False
        self.misses = 0

    def click_box(self, box=None, *args, **kwargs):
        """Remember which box the tap goes to, then tap it as upstream does.

        Args:
            box: The box, or list of boxes, upstream's `click_box` takes.
            *args: Passed through unchanged.
            **kwargs: Passed through unchanged.

        Returns:
            What upstream's `click_box` returns.
        """
        aimed = box[0] if isinstance(box, list) and box else box
        # A feature name is looked up inside ok-script, so the tapped point finds the caption then.
        self.aimed = aimed if hasattr(aimed, "height") else None
        try:
            return self.click_box_on(box, *args, **kwargs)
        finally:
            self.aimed = None

    def click(self, x=-1, y=-1, *args, after_sleep=0, **kwargs):
        """Tap as upstream does, then wait through `sleep`, which ends the wait once the caption has gone.

        ok-script's own `click` calls `click` again for a box or a relative point, so only the outermost call is the tap.

        Args:
            x: The point across, in pixels or as a fraction of the screen.
            y: The point down, in the same units.
            *args: Passed through unchanged.
            after_sleep: The wait upstream asked for after the tap.
            **kwargs: Passed through unchanged.

        Returns:
            What upstream's `click` returns.
        """
        if self.inner or self.tapped_at is not None:
            if not self.inner:
                # A handler tapping twice is upstream's own doing, so its waits stay upstream's from here on.
                self.watching = False
            return self.click_on(x, y, *args, after_sleep=after_sleep, **kwargs)
        caption = self.aimed or self.caption_at(x, y)
        self.inner += 1
        try:
            result = self.click_on(x, y, *args, after_sleep=0, **kwargs)
        finally:
            self.inner -= 1
        self.tapped_at = clock()
        self.caption = caption
        if caption is None:
            self.watching = False
        if after_sleep > 0:
            self.sleep(after_sleep)
        return result

    def caption_at(self, x, y):
        """Find the text the tap lands on, the way upstream's `find_box_at_point` does.

        Args:
            x: The point across, in pixels or as a fraction of the screen.
            y: The point down, in the same units.

        Returns:
            The smallest box on the tapped frame holding the point, or None when none does or the point is not one.
        """
        task = self.task
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        # ok-script's own test for a relative point.
        if 0 < x < 1 or 0 < y < 1:
            x, y = x * task.width, y * task.height
        hits = [box for box in task.all_texts or [] if box.x <= x <= box.x + box.width and box.y <= y <= box.y + box.height]
        return min(hits, key=lambda box: box.width * box.height) if hits else None

    def zone(self):
        """Work out where a look reads: the caption's box and a margin around it.

        Returns:
            `(left, top, right, bottom)` as fractions of the screen.
        """
        box, task = self.caption, self.task
        pad = box.height * MARGIN
        return (max(0.0, (box.x - pad) / task.width), max(0.0, (box.y - pad) / task.height),
                min(1.0, (box.x + box.width + pad) / task.width), min(1.0, (box.y + box.height + pad) / task.height))

    def shown(self):
        """Look once at the caption's place on a fresh frame.

        Anything read where the caption sat counts as the caption, whatever OCR made of it: a misread caption must
        never pass for a gone one.

        Returns:
            True while the caption, or any text over its place, still shows; False once neither does; None when
            the place cannot be read.
        """
        task = self.task
        try:
            frame = task.frame
            if frame is None:
                return None
            read = task.ocr(*self.zone(), frame=frame) or []
        except (TaskDisabledException, FinishedException):
            # A stop or a finish while paused inside the read belongs to the run, not to this wait.
            raise
        except Exception as error:
            logger.warning(f"could not read where {self.caption.name} was, so the full wait runs: {error}")
            return None
        name = fold(self.caption.name)
        return any(centre_inside(box, self.caption) or (name and name in fold(box.name)) for box in read)

    def sleep(self, seconds):
        """Wait as upstream asked, ending early once the tapped caption has gone.

        A wait before the tap, or after a tap with nothing to watch, runs whole. Each wait after the tap is cut,
        never stretched, so the handler's total stays within upstream's.

        Args:
            seconds: The wait upstream asked for.

        Returns:
            True, as `task.sleep` does.
        """
        if self.tapped_at is None or not self.watching:
            return self.sleep_on(seconds)
        if self.gone:
            return True
        deadline = clock() + seconds
        while True:
            left = deadline - clock()
            if left <= 0:
                return True
            # `task.sleep` drops the frame, so the look below reads a new one.
            step = min(LOOK_EVERY, left)
            self.sleep_on(step)
            if step >= left or clock() >= deadline:
                return True
            shown = self.shown()
            if shown is None:
                self.watching = False
                left = deadline - clock()
                if left > 0:
                    self.sleep_on(left)
                return True
            self.misses = 0 if shown else self.misses + 1
            if self.misses >= GONE_AFTER:
                self.gone = True
                logger.info(f"{self.caption.name} left the screen {clock() - self.tapped_at:.1f}s after the tap, moving on")
                return True


def moving_on(original):
    """Wrap an upstream navigation handler so the wait after its tap ends once the caption has gone.

    Args:
        original: The upstream handler, or another patch's wrapper of it.

    Returns:
        The wrapped handler.
    """
    def handler(task, *args, **kwargs):
        watch = CaptionWatch(task)
        with standing_in(task, sleep=watch.sleep, click=watch.click, click_box=watch.click_box):
            return original(task, *args, **kwargs)

    return handler


def install(utils):
    """Put the wrapper on each navigation handler, in every mode list holding it.

    Args:
        utils: The loaded `utils` module.
    """
    for name in HANDLERS:
        wrap(utils, name, moving_on, TAG)


def apply():
    """End the wait after a navigation tap once its caption has gone, in every mode that taps one."""
    global _patched
    if _patched:
        return

    def installing():
        utils = loaded("utils")
        if utils is not None:
            install(utils)

    register(installing)
    _patched = True
