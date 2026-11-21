"""Stop a run once when the Game Language setting does not match the language the game shows.

With Game Language on Traditional Chinese, upstream looks for about fifty screens by the Traditional client's wording,
which an English client never draws, so those handlers miss their screens without a word and the stuck handlers tap
around instead. A Chinese client under English misses the same screens the other way round, and every English-keyed
patch with them. This reads the first frames of a run as the client draws them, and when they settle which language
the game shows and the setting disagrees, it ends the run with what to change.
"""

import re

from ok import Logger

from src.en import game_language
from src.en.handlers import HANDLER_LIST, insert_before, loaded, register, standing_in
from src.en.notify import announce

logger = Logger.get_logger(__name__)

# A word of four or more letters. Shorter ones (HP, Lv, ATK, F1) are drawn in Latin by a Chinese client too.
LATIN_WORD = re.compile(r"[A-Za-z]{4,}")
# Two or more in a row, because the OCR reads an icon on an English client as a lone character now and then.
CJK_WORD = re.compile(r"[㐀-䶿一-鿿豈-﫿]{2,}")
# Kana and Hangul. A Japanese or Korean client shares Chinese characters but none of the bot's wording, so its boxes
# must not count towards a Chinese client.
OTHER_SCRIPT = re.compile(r"[぀-ヿᄀ-ᇿ가-힯]")
# Latin words a Chinese client is likely to draw as well: the title screen's logo, notice and build line, and key
# hints. Leaving them out costs an English client nothing it needs, and keeps them from holding a Chinese verdict back.
SHARED_WORDS = frozenset({"chaos", "zero", "nightmare", "touchtostart", "start", "smilegate", "rights", "reserved",
                          "cznlive", "weglobal", "ctrl"})

# What settles the language: at least this many boxes of one script over at least this many different frames, with
# that script this many times ahead of the other. Battle frames often carry no long word at all, so one frame is never
# enough.
FRAMES = 3
WORDS = 20
LEAD = 4
# Raw reads before a run the check cannot place is left alone, so it costs a few extra reads rather than one per frame.
# A pass that reads the same as the last one is not read raw, so a screen that holds still spends none of them.
READS = 30

ENGLISH = "English"
CHINESE = "Chinese"
SIMPLIFIED = "简体中文"
TRADITIONAL = "繁体中文"
# The drop-down's choices as the English Settings page shows them.
SHOWN = {game_language.ENGLISH: "English", SIMPLIFIED: "Simplified Chinese", TRADITIONAL: "Traditional Chinese"}
MESSAGE = ("Stopped: Game Language is set to {setting}, but the game shows {client}. Set Game Language to {wanted} on "
           "the Settings page, then press Start again.")

# Parked on the task for the length of one run.
TALLY = "_en_language_check"
# Where the check goes: right behind the stuck stop, which sits behind only `remote`'s hold. Not Daily, which reads
# English captions of its own whatever the setting and presses only what it has read.
MODES = ("utils_chaos", "utils_sortie", "utils_story")
STUCK_STOP = "stop_when_stuck"
HOLD = "handle_remote"

_patched = False


class Tally:
    """What one run's raw reads have shown so far."""

    def __init__(self):
        self.reads = 0
        self.frames = 0
        self.latin = 0
        self.cjk = 0
        self.other = 0
        self.seen = set()
        # What the run's own reading showed at the last raw read.
        self.shown = None
        # Set once the check has nothing more to do this run, with or without a verdict.
        self.done = False
        self.stopped = False

    def add(self, texts):
        """Count one frame's boxes by script, unless this run has counted the same texts before.

        Args:
            texts: The text of each box, as the client draws it.
        """
        texts = [text.strip() for text in texts if text and text.strip()]
        if not texts:
            return
        # A screen that sits still is read again on every pass, and its words would soon outnumber the rest.
        screen = tuple(texts)
        if screen in self.seen:
            return
        self.seen.add(screen)
        self.frames += 1
        for text in texts:
            if OTHER_SCRIPT.search(text):
                self.other += 1
            elif CJK_WORD.search(text):
                self.cjk += 1
            elif any(word.casefold() not in SHARED_WORDS for word in LATIN_WORD.findall(text)):
                self.latin += 1

    def verdict(self):
        """Say which language the frames so far settle on.

        Returns:
            `ENGLISH`, `CHINESE`, or None while they settle nothing.
        """
        if self.frames < FRAMES:
            return None
        if self.latin >= WORDS and self.cjk * LEAD <= self.latin:
            return ENGLISH
        if self.cjk >= WORDS and (self.latin + self.other) * LEAD <= self.cjk:
            return CHINESE
        return None


def mismatch(client, setting):
    """Build the stop message for a setting that cannot read the client.

    Simplified Chinese on a Chinese client is left alone: it reads a Simplified client correctly, and telling that
    client from a Traditional one is beyond a script count.

    Args:
        client: `ENGLISH` or `CHINESE`.
        setting: The Game Language value.

    Returns:
        The message, or None when the setting reads the client.
    """
    if client == ENGLISH and setting == TRADITIONAL:
        wanted = game_language.ENGLISH
    elif client == CHINESE and setting == game_language.ENGLISH:
        wanted = TRADITIONAL
    else:
        return None
    return MESSAGE.format(setting=SHOWN.get(setting, setting), client=client, wanted=SHOWN[wanted])


def raw_texts(task):
    """Read the current frame as the client draws it, leaving the run's own reading alone.

    Args:
        task: The running task.

    Returns:
        The text of each box.
    """
    with standing_in(task.executor, ocr_po_translation=None):
        return [box.name for box in task.ocr()]


def check_game_language(task):
    """Stop the run, once, when the game's language and the Game Language setting disagree.

    Args:
        task: The running task.

    Returns:
        True when the run is stopped, so no later handler acts on the frame.
    """
    tally = vars(task).setdefault(TALLY, Tally())
    if tally.stopped:
        # The loop can come round again before it sees the task disabled.
        task.disable()
        return True
    if tally.done:
        return False
    shown = tuple(box.name for box in getattr(task, "all_texts", None) or ())
    if shown == tally.shown:
        return False
    tally.shown = shown
    tally.reads += 1
    try:
        tally.add(raw_texts(task))
    except Exception as error:
        logger.warning(f"could not read the game's language: {error}")
        tally.done = True
        return False
    client = tally.verdict()
    if client is None:
        if tally.reads >= READS:
            tally.done = True
            logger.info(f"could not tell the game's language from {tally.frames} frames, not checking it this run")
        return False
    tally.done = True
    setting = game_language.current()
    message = mismatch(client, setting)
    if message is None:
        logger.info(f"the game shows {client}, which Game Language {setting} reads")
        return False
    tally.stopped = True
    announce(task, message)
    task.disable()
    return True


def forgetting(enable):
    """Wrap `enable` so each run checks the language afresh.

    Args:
        enable: The unbound `enable` being replaced.

    Returns:
        The replacement.
    """
    def enable_checking_afresh(self):
        # Without asking whether the task is enabled: the Start button marks a mode enabled before the run loop calls
        # `enable`, so the run that is starting looks like one already going.
        vars(self).pop(TALLY, None)
        return enable(self)

    return enable_checking_afresh


def install():
    """Put the check behind the stuck stop in Chaos, Sortie and Story, or behind the hold where there is none."""
    for name in MODES:
        names = [getattr(handler, "__name__", None) for handler in getattr(loaded(name), HANDLER_LIST, None) or ()]
        if STUCK_STOP in names:
            index = names.index(STUCK_STOP) + 1
        else:
            index = names.index(HOLD) + 1 if HOLD in names else 0
        if index < len(names):
            insert_before(names[index], check_game_language, only=(name,))


def apply():
    """Stop a run whose Game Language setting cannot read the game's screens."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, the Game Language check will carry over between runs")
    else:
        BaseTask.enable = forgetting(BaseTask.enable)
    register(install)
    _patched = True
