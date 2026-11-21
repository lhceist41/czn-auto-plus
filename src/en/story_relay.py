"""Hand a chapter's Chaos stage from Story to Chaos mode, and the chapter back to Story once the run ends.

Story has no handler for a Chaos run's map, rewards or Save Data screens, and upstream tells the player to switch modes
by hand there and back afterwards. Chaos mode already plays the whole run, so Story starts it on the stage's Team
Formation and Chaos returns to Story on the chapter map. Only a run Story started goes back, and that run never spends
or deletes anything its settings would, whatever the saved Chaos settings say. A stage Story reaches again straight after
a hand-back was not cleared, so Story stops there rather than hand it over in a loop.
"""

import re

from ok import Logger

from src.en.etched_memory import ENTER_MEMORY_END
from src.en.handlers import insert_before, loaded, register, wrap
from src.en.notify import announce
from src.en.reobserve import REOBSERVE, SAVE_LIMIT_KEY
from src.en.screen import in_region, text_in_region
from src.en.story import TEAM_SLOTS, filled_slots, team_formation
from src.en.stuck import CACHE
from src.en.stuck_stop import LAST_PASS
from src.en.zero_system import CODEX_MERGE, NEVER_MERGE

logger = Logger.get_logger(__name__)

STORY_MODE = "StoryMode"
CHAOS_MODE = "ChaosMode"
# Set on the Chaos task while it plays a run Story handed it. Any disable drops it, so a run the player starts later is their own.
RELAYED = "_en_story_relay"
# The stuck clock parked on the mode taking over until its first pass: in the app the run loop starts the mode again
# after the relay has (`src/en/shell.py`), and every start clears the clock (`src/en/stuck.py`).
CARRIED = "_en_story_relay_clock"
# The stage the Chaos task was handed, and on Story the stage the last relayed run came back from.
STAGE = "_en_story_relay_stage"
RETURNED = "_en_story_relay_returned"
# What a disable drops: every mark the relay leaves on a mode, so a stop for any reason starts the next run afresh.
MARKS = (RELAYED, CARRIED, STAGE, RETURNED)
# What a Chaos stage's Team Formation shows on its right and a battle's does not, as `(left, top, right, bottom)` screen
# fractions. They read at (0.741, 0.139) and (0.789, 0.815); a Battle Missions formation shows `#B1 Battle Missions` and no limit.
CHAOS_MISSIONS = "Chaos Missions"
CHAOS_MISSIONS_REGION = (0.60, 0.08, 1.0, 0.22)
SAVE_LIMIT = "存储数据保存上限"
SAVE_LIMIT_REGION = (0.60, 0.74, 1.0, 0.88)
# Under `Chaos Missions`: the Chaos's name and the stage's mission, read at (0.744, 0.189) and (0.757, 0.253), above the
# mission's description from y 0.311. The formation shows no node number, so these two lines are what tell stages apart.
STAGE_REGION = (0.60, 0.16, 1.0, 0.28)
# The chapter map: `Chapter 1` at the top centre, read at x 0.451-0.523, and node numbers like `#05` across the middle.
# Battle Missions shows `Chapter1` there too, with `B1` nodes, and a popup over the map hides the nodes.
CHAPTER_REGION = (0.35, 0.0, 0.65, 0.09)
CHAPTER = re.compile(r"chapter\d+")
NODE_REGION = (0.0, 0.40, 1.0, 0.60)
NODE = re.compile(r"#\d{2}")
# How a relayed run reads these Chaos settings, whatever the player saved. Re-observing pays event currency, and the
# Storage Limit minimum re-observes on its own (the story Chaos offered 110 against the default 120). Additional Loot uses
# weekly Loot Certification Cards, healing a Mental Breakdown pays a Communication Pass or gold, a Zero System merge pays
# Credits or Chaos Orbs, and End of Memory's Processing uses materials. The save threshold deletes saves. The last four
# escape or leave a run early to farm, which would never clear the stage.
RELAYED_SETTINGS = {
    REOBSERVE: False,
    SAVE_LIMIT_KEY: 0,
    "领取奖励(只使用验证卡)": False,
    "治疗崩溃": False,
    CODEX_MERGE: NEVER_MERGE,
    ENTER_MEMORY_END: False,
    "保留大于多少TB的存档": 0,
    "刷空档": False,
    "刷初始卡牌": "",
    "首层刷特定闪光": False,
    "只打第一层": False,
}
# The modules whose `_get_config_value` the Chaos handlers read through, upstream's and the fork's alike.
READERS = ("utils", "utils_chaos")
TAG = "story relay settings"
NO_CHAOS = "Story reached a Chaos stage, but Chaos mode is not in the task list. Play the stage in Chaos mode, then start Story again."
NO_STORY = "The Chaos stage is cleared, but Story mode is not in the task list. Start Story to play on."
SAME_STAGE = "Story reached the same Chaos stage again after Chaos mode handed the chapter back, so the run did not clear it. Check the game, then press Start again."

_patched = False


def mode_named(task, name):
    """Find another mode in the running app by its class name.

    The app moves every mode to the executor's one-time list at launch (`src/en/shell.py`), and ok-script's lookup
    searches both lists.

    Args:
        task: The running task, whose executor holds every mode.
        name: The mode's class name, such as `CHAOS_MODE`.

    Returns:
        The mode, or None when the app has none by that name.
    """
    return task.executor.get_task_by_class_name(name)


def carry_stuck_clock(source, target):
    """Park the stuck clock of the mode handing over on the one taking over, so a freeze across the switch counts in full.

    Starting a mode clears its clock, which would otherwise give a screen that froze before the switch five fresh minutes.

    Args:
        source: The mode handing over.
        target: The mode taking over, already enabled.
    """
    setattr(target, CARRIED, {name: vars(source)[name] for name in (*CACHE, LAST_PASS) if name in vars(source)})


def restore_stuck_clock(task):
    """Put a carried stuck clock back on the first pass of the mode that took over, just ahead of the stuck stop.

    Args:
        task: The running mode.

    Returns:
        False, so the stuck stop still sees the frame.
    """
    vars(task).update(vars(task).pop(CARRIED, {}))
    return False


def stage_shown(task):
    """Read which Chaos stage a Team Formation is for.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        The lines under `Chaos Missions`, without spaces or case, so a stage read twice compares equal.
    """
    return tuple(sorted(box.name.casefold().replace(" ", "") for box in task.all_texts if in_region(box, STAGE_REGION, task.width, task.height)))


def chaos_formation(task):
    """Say whether the screen is a Chaos stage's Team Formation.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when the title and both Chaos captions are on screen.
    """
    return (team_formation(task) and text_in_region(task, CHAOS_MISSIONS, CHAOS_MISSIONS_REGION) is not None
            and text_in_region(task, SAVE_LIMIT, SAVE_LIMIT_REGION) is not None)


def chapter_map(task):
    """Say whether the screen is a story chapter map.

    Args:
        task: The running task, whose `all_texts` holds the current OCR pass.

    Returns:
        True when the chapter title and at least one node number are on screen.
    """
    def shown(pattern, region, name):
        return any(pattern.fullmatch(name(box)) and in_region(box, region, task.width, task.height) for box in task.all_texts)

    return (shown(CHAPTER, CHAPTER_REGION, lambda box: box.name.casefold().replace(" ", ""))
            and shown(NODE, NODE_REGION, lambda box: box.name.strip()))


def handle_story_chaos_stage(task):
    """Hand a story Chaos stage to Chaos mode on its Team Formation, which Chaos then enters.

    A short team is left to `story.handle_team_formation`, which stops Story.

    Args:
        task: Story mode, whose `all_texts` and `frame` hold the current screen.

    Returns:
        True when the run has been handed over, or Story stopped instead, which claims the frame.
    """
    if not chaos_formation(task) or filled_slots(task) != len(TEAM_SLOTS):
        return False
    stage = stage_shown(task)
    if vars(task).get(RETURNED) == stage:
        announce(task, SAME_STAGE)
        task.disable()
        return True
    chaos = mode_named(task, CHAOS_MODE)
    if chaos is None:
        announce(task, NO_CHAOS)
        task.disable()
        return True
    task.log_info("Chaos stage Team Formation, handing the run to Chaos mode")
    # Story first: two modes enabled at once take turns on the same screen, and Chaos's own start leaves Story running.
    task.disable()
    chaos.enable()
    setattr(chaos, RELAYED, True)
    setattr(chaos, STAGE, stage)
    carry_stuck_clock(task, chaos)
    return True


def handle_story_chapter_map(task):
    """Hand the chapter back to Story once a run Story started has returned to the chapter map.

    Args:
        task: Chaos mode, whose `all_texts` holds the current OCR pass.

    Returns:
        True when Story has taken over, which claims the frame.
    """
    if not getattr(task, RELAYED, False) or not chapter_map(task):
        return False
    task.log_info("back on the chapter map, handing it to Story mode")
    stage = vars(task).get(STAGE)
    task.disable()
    story = mode_named(task, STORY_MODE)
    if story is None:
        announce(task, NO_STORY)
        return True
    story.enable()
    setattr(story, RETURNED, stage)
    carry_stuck_clock(task, story)
    return True


def relayed_settings(read):
    """Wrap a module's `_get_config_value` so a relayed run reads `RELAYED_SETTINGS` instead of the saved values.

    Args:
        read: The `_get_config_value` the module carries now.

    Returns:
        The wrapper. The saved config is never touched.
    """
    def _get_config_value(task, key, default):
        if getattr(task, RELAYED, False) and key in RELAYED_SETTINGS:
            return RELAYED_SETTINGS[key]
        return read(task, key, default)

    return _get_config_value


def forgetting_relay(disable):
    """Wrap `disable` so a mode stopped for any reason no longer counts as playing a relayed run.

    It also forgets the stage a run came back from, so a Story the player starts again may hand that stage over once more.

    Args:
        disable: The unbound `disable` being replaced.

    Returns:
        The replacement.
    """
    def disable_forgetting_relay(self):
        for name in MARKS:
            vars(self).pop(name, None)
        return disable(self)

    return disable_forgetting_relay


def install():
    """Put the hand-over in Story's list, the hand-back at the head of Chaos's, and the relayed settings on the readers."""
    # The stuck stop is in place by now: `stuck_stop.apply` registers its install before this one (`src/globals.py`).
    insert_before("stop_when_stuck", restore_stuck_clock, only=("utils_story", "utils_chaos"))
    insert_before("handle_enter", handle_story_chaos_stage, only=("utils_story",))
    insert_before("handle_auto_stop", handle_story_chapter_map, only=("utils_chaos",))
    for name in READERS:
        module = loaded(name)
        if module is not None:
            wrap(module, "_get_config_value", relayed_settings, TAG)


def apply():
    """Relay a chapter's Chaos stage between Story and Chaos mode."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, Story will not hand Chaos stages to Chaos mode")
        _patched = True
        return
    BaseTask.disable = forgetting_relay(BaseTask.disable)
    register(install)
    _patched = True
