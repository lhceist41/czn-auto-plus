"""Draw the Tasks page's Info rows in reading order, plain wording, and only the rows worth a look.

ok-script draws one row per `task.info` entry in insertion order, and upstream writes fifteen of them every tick: a
version and language that never change, three boss flags, and a team and its gear on two rows you have to zip by eye.
`present` turns each upstream write into the rows actually drawn.
"""

import time

from ok import Logger

from src.en.framework import import_ui
from src.en.log_strings import MESSAGES, TEMPLATES
from src.en.notify import score_of
from src.en.overrides import FARMED_COMBATANT, NO_COMBATANT

logger = Logger.get_logger(__name__)

# The placeholder row for the team, drawn until a run reads the Combatants screen and replaced then by one row per combatant.
COMBATANTS = "Combatants"
# What a row holds until the run has read it. The row is drawn either way, because one that appears partway through a
# run reads as the table rearranging itself.
UNREAD = "-"
# The framework's own row for the last logged line.
LOG = "Log"
# How long the last run took, drawn above Log once it ends. The header shows the live clock while a run is going.
ELAPSED = "Time Elapsed"
# Upstream's equipment row, and where the run keeps the reading that fills the team rows instead. Upstream fills its
# row from a ledger of what the run installed, so `src/en/equipment.py` reads the screens that show the whole team and
# leaves a line like `Legend/Rare/Mythic, -/Rare/Legend` here, one column per combatant.
GEAR = MESSAGES["装备信息"]
TEAM_GEAR = "_en_team_gear"
# Where `rewards.show_team` keeps the team's names once read, in the order the gear columns follow.
TEAM_NAMES = "_en_team_names"
# How one gear slot reads in a team row, keyed on the tier `src/en/equipment.py` writes.
SLOT_WORDS = {"-": "empty", "?": "unknown"}
# Upstream's win rate row, replaced by the run count against the stop limit.
WIN_RATE = MESSAGES["当前胜率"]
RUNS = "Runs"
STOP_AFTER = "几轮后停止(0为不停止)"
# Upstream's floor row, which also carries the boss and escape flags once a run reaches them.
FLOOR = MESSAGES["所处层数，节点，类型"]
FLOOR_ROW = "Floor"
# The tail the floor row is left with while the run's node type is still blank.
UNTYPED = ", "
# Upstream's one-way flags folded into the floor row, as `(node_status key, how the floor row says it)`. First match wins.
BOSS_FLAGS = (("is_escaped", "escaped"), ("final_boss_battle", "boss fight"), ("reach_final_boss", "boss node"))
# Upstream's two card counts, drawn as one row.
CARD_COUNTS = {MESSAGES["本局已移除卡牌"], MESSAGES["本局已获得中立牌"]}
DECK = "Deck this run"
# Rows upstream writes that are never drawn. Version and language never change during a run, and the boss flags are on the floor row.
HIDDEN = {MESSAGES["版本号"], MESSAGES["游戏语言"], MESSAGES["是否到达关底boss"], MESSAGES["是否进入关底boss战斗"], MESSAGES["是否已逃脱"]}
# The Target rows, each drawn only while the setting that gives it meaning is on.
TARGET_EPIPHANY = MESSAGES["是否已获得特定闪光"]
TARGET_PORTRAIT = MESSAGES["获取刷存档主战员头像"]
FARM_EPIPHANY = "首层刷特定闪光"
# How upstream writes its yes/no rows, as strings or as bools, and how they read instead.
YES_NO = {"True": "Yes", "False": "No", True: "Yes", False: "No"}
# What every meditation row's key starts with once translated. One row per card, so they rank as a group.
MEDITATING = TEMPLATES["冥想：{}"].split("{0}")[0]
# Top to bottom: what moves during a run, then the Target flags. The team's rows rank where `COMBATANTS` does.
ORDER = (ELAPSED, LOG, FLOOR_ROW, MESSAGES["当前信用点"], RUNS, COMBATANTS, DECK, MEDITATING, TARGET_EPIPHANY, TARGET_PORTRAIT)
# The rows every Chaos or Sortie run fills, seeded blank at the start. The Target rows depend on settings and the
# meditation rows are one per configured card, so those arrive with the first status report.
STARTED = tuple(key for key in ORDER if key not in (ELAPSED, MEDITATING, TARGET_EPIPHANY, TARGET_PORTRAIT))
# Each ranked row's position in `ORDER`.
RANKS = {key: position for position, key in enumerate(ORDER)}

_patched = False


def rank(key, team=()):
    """Place one Info row in `ORDER`.

    Args:
        key: The row's key as stored in `task.info`.
        team: The team's names, whose rows rank together where `COMBATANTS` does.

    Returns:
        Its position, or one past the end for a row `ORDER` does not name.
    """
    if key.startswith(MEDITATING):
        return RANKS[MEDITATING]
    if key in team:
        return RANKS[COMBATANTS]
    return RANKS.get(key, len(ORDER))


def in_order(rows, team=()):
    """Sort info rows into reading order.

    Args:
        rows: The rows to draw, keyed the way `task.info` keys them.
        team: The team's names, from `TEAM_NAMES`.

    Returns:
        A new dict in `ORDER`. The sort is stable, so the team's rows keep the order they were written in.
    """
    return dict(sorted(rows.items(), key=lambda row: rank(row[0], team)))


def ordering(original):
    """Wrap `info_set` so a new row is drawn in its place in `ORDER` rather than at the bottom.

    Args:
        original: The unbound `info_set` being replaced.

    Returns:
        The replacement.
    """
    def info_set_in_order(self, key, value):
        new = key not in self.info
        result = original(self, key, value)
        if new:
            self.info = in_order(self.info, getattr(self, TEAM_NAMES, None) or ())
        return result

    return info_set_in_order


def respell(value):
    """Give one Info row's value the wording the table shows.

    Args:
        value: The value as upstream wrote it, already in English.

    Returns:
        The value to draw, with upstream's True / False said as Yes / No.
    """
    return YES_NO.get(value, value) if isinstance(value, (str, bool)) else value


def team_rows(task):
    """Build one row per combatant, naming the gear in each of their three slots.

    Args:
        task: The running task, holding the team's names and gear reading once they have been read.

    Returns:
        The rows to draw. Until the team is read that is the `COMBATANTS` placeholder alone. After, the placeholder
        maps to None, which tells `src/en/log_text.py` to drop it.
    """
    names = getattr(task, TEAM_NAMES, None)
    if not names:
        return {COMBATANTS: UNREAD}
    gear = (getattr(task, TEAM_GEAR, None) or "").split(", ")
    rows: dict = {COMBATANTS: None}
    for index, name in enumerate(names):
        tiers = gear[index].split("/") if index < len(gear) and gear[index] else []
        rows[name] = ", ".join(SLOT_WORDS.get(tier, tier) for tier in tiers) or UNREAD
    return rows


def runs(task):
    """Say how many runs have finished, against the stop limit when one is set.

    Args:
        task: The running task, whose `node_status` counts the runs and whose config holds the limit.

    Returns:
        A line like `1 of 5 done, 1 won`.
    """
    done, won, _ = score_of(task)
    limit = (getattr(task, "config", None) or {}).get(STOP_AFTER, 0)
    line = f"{done} of {limit} done" if limit else f"{done} done"
    return f"{line}, {won} won" if done else line


def shows_target(task, key):
    """Say whether a Target row means anything for this mode and its settings.

    Args:
        task: The running task, whose config says what it is chasing.
        key: `TARGET_EPIPHANY` or `TARGET_PORTRAIT`.

    Returns:
        True when the setting behind the row is on. Sortie declares neither setting, so it never shows them.
    """
    config = getattr(task, "config", None) or {}
    if key == TARGET_EPIPHANY:
        return config.get(FARM_EPIPHANY) is True
    return config.get(FARMED_COMBATANT) not in (None, "", NO_COMBATANT)


def present(task, key, value):
    """Turn one upstream row write into the rows the table actually draws.

    Called by `log_text` ahead of its unchanged-row check. Rewritten any later, a row would never equal what upstream
    wrote, so every row would be logged at INFO on every tick.

    Args:
        task: The task writing the row.
        key: The row's key, already in English.
        value: The value as upstream wrote it, already in English.

    Returns:
        A dict of row -> value to draw, empty for a row that is never drawn. A None value means drop that row.
    """
    if key in HIDDEN:
        return {}
    status = getattr(task, "node_status", None) or {}
    if key == FLOOR and isinstance(value, str):
        flag = next((words for name, words in BOSS_FLAGS if status.get(name)), None)
        return {FLOOR_ROW: f"{value.split(', ')[0]}, {flag}" if flag else value.removesuffix(UNTYPED)}
    if key == WIN_RATE:
        return {RUNS: runs(task)}
    if key == LOG and RUNS in (getattr(task, "info", None) or {}):
        # Upstream counts a finished run and can stop the task before it rewrites its win rate, so every log line refreshes Runs.
        return {LOG: value, RUNS: runs(task)}
    if key in CARD_COUNTS:
        return {DECK: f"{status.get('removed_card_count', 0)} removed, {status.get('neutral_card_count', 0)} Neutral taken"}
    if key in (TARGET_EPIPHANY, TARGET_PORTRAIT):
        return {key: respell(value) if shows_target(task, key) else None}
    if key in (COMBATANTS, GEAR):
        return team_rows(task)
    return {key: respell(value)}


def seeding_the_table(original):
    """Wrap `info_clear` so a starting run's table is its full height from the first frame.

    Written straight into the dict rather than through `info_set`, which would log every row at INFO on
    every Start and re-sort the table once per row for an order `STARTED` is already in.

    Args:
        original: The unbound `info_clear` being replaced.

    Returns:
        The replacement.
    """
    def info_clear_seeded(self):
        original(self)
        # The last run's start, so a task stopped while still queued has no time to stamp. The header reads 0 as no run too.
        self.start_time = 0
        # The last run's team, so its rows are not redrawn before this run reads its own.
        setattr(self, TEAM_NAMES, None)
        # `node_status` is built in a mode's `__init__`, so it is there to be asked long before a Start. Story
        # has none, and runs none of the handlers that would fill these rows.
        if getattr(self, "node_status", None) is None:
            return
        for key in STARTED:
            self.info[key] = UNREAD

    return info_clear_seeded


def stamping_elapsed(original, format_elapsed):
    """Wrap `disable` so a run that ends - stopped, finished or crashed - leaves its running time as the top Info row.

    The next Start clears the table, so the row is gone again while that run's clock is in the header.

    Args:
        original: The unbound `disable` being replaced.
        format_elapsed: ok-script's own clock formatter, so the row reads like the header did.

    Returns:
        The replacement.
    """
    def disable_stamped(self):
        started = getattr(self, "start_time", 0)
        if self.enabled and started:
            self.info_set(ELAPSED, format_elapsed(time.time() - started))
        return original(self)

    return disable_stamped


def headless(original):
    """Wrap `TaskDetail.__init__` to drop the table's `Info` / `Value` column titles, which say nothing the rows do not.

    Args:
        original: The unbound `__init__` being replaced.

    Returns:
        The replacement.
    """
    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.info_table.horizontalHeader().hide()

    return __init__


def apply():
    """Draw the Info rows in reading order."""
    global _patched
    if _patched:
        return

    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, the Info rows will stay in upstream's order")
    else:
        BaseTask.info_set = ordering(BaseTask.info_set)
        BaseTask.info_clear = seeding_the_table(BaseTask.info_clear)
        format_elapsed = import_ui("shell.run_bar", "format_elapsed")
        if format_elapsed is not None:
            BaseTask.disable = stamping_elapsed(BaseTask.disable, format_elapsed)

    task_detail = import_ui("tasks.tasks_page", "TaskDetail")
    if task_detail is not None:
        task_detail.__init__ = headless(task_detail.__init__)
    _patched = True
