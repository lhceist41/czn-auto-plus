"""Write down every fight the card picker plays, so its decisions can be judged afterwards and replayed against changed code.

Each fight leaves lines in `FIGHTS_FILE`, one JSON object per line: a `plan` line each time the picker decides, a `play` line once the
game has taken or refused the card, and an `end` line once the fight is over. Only what the screen showed is written, and a field it did
not give is null. `scripts/replay_fights.py` reads them back.

Nothing here may change a fight. Every hook catches its own errors and logs the first of each fight, and it only reads what the battle
frame already has.
"""

import functools
import json
import math
import os
import time
import uuid

from ok import Logger

from src.en import board, cards, ego
from src.en.quality import fold
from src.en.screen import frame_of, in_region

logger = Logger.get_logger(__name__)

# `data/` is in `.gitignore`, and deleting the file only loses the record.
FIGHTS_FILE = os.path.join("data", "fights.jsonl")
# Where a full file goes when the next fight starts, replacing the one there before.
OLDER_FILE = os.path.join("data", "fights.1.jsonl")
# A fight writes about 1.5 KB a plan and a few dozen plans, so a file holds well over a hundred fights. With the one older file kept
# that is several Chaos runs for tuning, and the two never take more than twice this.
MAX_BYTES = 8 * 1024 * 1024
# Parked on the task for the length of a fight, as a `Fight`.
RECORD = "_en_fight_record"
# Only a real mode's battles are recorded, so the tests that drive the picker with a stand-in task write nothing.
MODES = ("ChaosMode", "SortieMode", "StoryMode")
# Seconds off the battle screen after which the next plan belongs to a new fight. A hand prompt or a draw hides the hand for a frame or
# two; leaving a fight for the reward, the map and the next node takes longer.
FIGHT_GAP = 30
# Titles that only come up after a fight: the card reward after a win, and upstream's own name for a loss.
WON_TITLES = ("获得卡牌", "卡牌奖励")
LOST_TITLES = ("战斗失败",)
# The Global client's own loss line, which it shows untranslated. It is matched as a whole box, as `battle` tells a result screen, so
# longer text that holds the words ends no fight.
LOST_LINES = (fold("Battle failed"),)
# Whether an error with no fight to log it against has been logged this run.
_warned = False


class Fight:
    """What one fight has shown so far, enough to write its end line."""

    def __init__(self, task, fight):
        """Start recording a fight.

        Args:
            task: The running task, whose class names the mode.
            fight: Which fight it is, from `battle.fight_of`, None in a mode that counts no nodes.
        """
        self.id = uuid.uuid4().hex[:12]
        self.mode = type(task).__name__
        self.fight = fight
        self.rounds = rounds_of(task)
        self.status = getattr(task, "node_status", None)
        self.started = time.monotonic()
        self.last_seen = self.started
        # When the battle screen was last seen leaving, cleared when the fight turns out to go on.
        self.left_at = None
        self.closed = False
        self.turn = None
        self.turns = 0
        self.plans = 0
        self.cards_played = 0
        # The team's (HP, max HP) as first and last read.
        self.first_team = None
        self.last_team = None
        # The hits and deck texts as last written, so a plan line only carries what changed.
        self.hits = {}
        self.deck = None
        # Whether the file has been checked for size yet, which happens once, before the fight's first line.
        self.checked = False
        self.warned = False


def quietly(hook):
    """Wrap a hook so no error of its own ever reaches the battle frame.

    Args:
        hook: A function taking the task first.

    Returns:
        The hook, logging its first error of each fight and returning None instead of raising.
    """
    @functools.wraps(hook)
    def guarded(task, *args, **kwargs):
        try:
            if type(task).__name__ in MODES:
                hook(task, *args, **kwargs)
        except Exception as error:
            warn(getattr(task, RECORD, None), f"the fight record skipped {hook.__name__}: {error!r}")

    return guarded


def warn(record, message):
    """Log a problem with the record once per fight, or once a run when there is no fight to log it against.

    Args:
        record: The `Fight` it happened in, or None.
        message: What went wrong.
    """
    global _warned
    if record is None:
        if _warned:
            return
        _warned = True
    elif record.warned:
        return
    else:
        record.warned = True
    logger.warning(message)


def finite(value):
    """Make a value safe for strict JSON, turning NaN and the infinities into null wherever they sit.

    Args:
        value: Anything `json.dumps` takes.

    Returns:
        The same value with every non-finite float replaced by None.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(item) for item in value]
    return value


def write(record, line):
    """Append one line to `FIGHTS_FILE`, moving a full file aside before a fight's first line.

    Args:
        record: The `Fight` the line belongs to.
        line: The dict to write.
    """
    try:
        os.makedirs(os.path.dirname(FIGHTS_FILE), exist_ok=True)
        if not record.checked:
            record.checked = True
            if os.path.exists(FIGHTS_FILE) and os.path.getsize(FIGHTS_FILE) >= MAX_BYTES:
                os.replace(FIGHTS_FILE, OLDER_FILE)
        text = json.dumps(finite(line), ensure_ascii=False, allow_nan=False)
        with open(FIGHTS_FILE, "a", encoding="utf-8") as file:
            file.write(text + "\n")
    except Exception as error:
        warn(record, f"could not write the fight record to {FIGHTS_FILE}: {error!r}")


def team_read(task):
    """Read the team's HP, max HP and shield off the readout along the top.

    Args:
        task: The running task, whose `all_texts` holds this frame's OCR pass.

    Returns:
        HP, max HP and shield, each None when it did not read. The shield only counts when the HP read beside it.
    """
    hp = most = None
    for box in getattr(task, "all_texts", None) or []:
        read = ego.TEAM_HP.search(box.name) if in_region(box, ego.TEAM_READOUT, task.width, task.height) else None
        if read:
            hp, most = int(read.group(1)), int(read.group(2))
            break
    readout = ego.team_readout(task) if hp is not None else None
    return hp, most, None if readout is None else readout[1]


def foe_line(foe):
    """Write down one enemy as `board.enemies` read it.

    Args:
        foe: A `board.Foe`.

    Returns:
        A dict. `hp_source` is "both" when the zoomed crop and the full-frame pass read the same HP, "crop" when the crop read one
        number and that pass read none, "one" when only one of them gave it otherwise, and null with no HP. A kill is planned on
        "both" and "crop", a hit only learnt from "both". `summoned` says its statuses showed a summoned enemy's mark.
    """
    source = "both" if foe.agreed else "crop" if foe.sure else "one"
    return {"x": foe.x, "hp": foe.health, "hp_source": None if foe.health is None else source,
            "counter": foe.counter, "weakness": foe.weakness, "summoned": foe.summoned}


def card_line(card):
    """Write down one hand card as the picker was given it.

    Args:
        card: A hand card dict.

    Returns:
        Its name, hotkey and cost, with `shown` true when the cost is one read off the card rather than the data's.
    """
    return {"name": card["name"], "key": card.get("key"), "cost": cards.price(card), "shown": "cost" in card}


def changed_hits(record):
    """Find each combatant whose hits differ from what the fight's lines already carry.

    Args:
        record: The `Fight`, whose `hits` holds what was written.

    Returns:
        Combatant to every hit now remembered, only for those that changed, or None when none did.
    """
    now = {who: list(figures) for who, figures in cards.HITS.items()}
    changed = {who: figures for who, figures in now.items() if record.hits.get(who) != figures}
    record.hits = now
    return changed or None


def rounds_of(task):
    """Count the runs the task has finished, which tells one run from the next.

    Upstream keeps one start time for every run of a task and puts the floor and node back to 0 for each, so only this count rises
    between runs.

    Args:
        task: The running task, whose `node_status` Sortie and Chaos keep.

    Returns:
        The runs finished, or None in a mode that does not count them.
    """
    status = getattr(task, "node_status", None)
    return status.get("total_rounds") if isinstance(status, dict) else None


def fight_for(task, turn, now):
    """Find the fight a plan belongs to, ending the one before when this is a new one.

    Args:
        task: The running task, which the record is parked on.
        turn: The `battle.Turn` in progress.
        now: The monotonic time.

    Returns:
        The `Fight`.
    """
    record = getattr(task, RECORD, None)
    if record is not None and not record.closed:
        gone = record.left_at is not None and now - record.left_at > FIGHT_GAP
        # The status parts a run whose result page went unread from the next, which keeps the count and can repeat the place.
        replaced = record.status is not getattr(task, "node_status", None)
        if record.fight == turn.fight and record.rounds == rounds_of(task) and not replaced and not gone:
            record.left_at = None
            return record
        end(task, record, *after(record, turn.fight, rounds_of(task), replaced))
    record = Fight(task, turn.fight)
    setattr(task, RECORD, record)
    return record


def after(record, fight, rounds, replaced=False):
    """Say how a fight that was never seen ending went, from the fight that came next.

    A run ends at a lost fight, so a fight on a later floor or node of the same run means this one was won. The run count tells runs
    apart, since every run of a task keeps one start time. A run whose result page went unread finishes without the count rising, but
    upstream still builds the next run a new status and starts it again from the first node.

    Args:
        record: The `Fight` being ended.
        fight: The next fight, from `battle.fight_of`.
        rounds: The runs finished when the next fight came, from `rounds_of`.
        replaced: Whether the task's `node_status` is no longer the one the fight began under.

    Returns:
        The outcome and what it was told from.
    """
    if record.last_team is not None and record.last_team[0] == 0:
        return "lost", "team HP read 0"
    if later_in_run(record.fight, record.rounds, fight, rounds, replaced):
        return "won", "next fight of the same run"
    return "unknown", "no title seen"


def later_in_run(fight, rounds, following, following_rounds, replaced=False):
    """Tell whether a fight comes after another in the same run.

    Args:
        fight: The earlier fight, from `battle.fight_of`.
        rounds: The runs finished when it began.
        following: The fight after it.
        following_rounds: The runs finished when that one began.
        replaced: Whether upstream built a new `node_status` between the two.

    Returns:
        True only when both are known, in the same task and run, the first sits on a counted node and the second on a later floor or
        node, on a higher floor when the status was replaced.
    """
    if fight is None or following is None or rounds is None or rounds != following_rounds or fight[0] != following[0]:
        return False
    place, later = fight[1:], following[1:]
    if not all(isinstance(number, int) for number in place + later):
        return False
    # Upstream builds a new status for a run and for a floor won, so a new one with the floor not higher means the next run.
    if replaced and later[0] <= place[0]:
        return False
    # Node 0 is a fight before any route page the task counted, such as one the bot was started in, so it says nothing of the run.
    return place[1] >= 1 and later > place


@quietly
def planned(task, turn, state, hand, made, card, unread):
    """Write the plan line for one decision.

    Args:
        task: The running task.
        turn: The `battle.Turn` in progress.
        state: The `cards.Board` the decision was made against.
        hand: The hand cards the picker was given, in order.
        made: What each `battle.choose` call this frame was offered and chose, as (playable, action points, plan) triples.
        card: The card chosen, or None when the turn is being ended.
        unread: Whether the Action Point count did not read.
    """
    if not hand:
        # Upstream ends an empty hand itself, so there was no decision to write down.
        return
    now = time.monotonic()
    record = fight_for(task, turn, now)
    if turn is not record.turn:
        record.turn = turn
        record.turns += 1
    record.plans += 1
    record.last_seen = now
    hp, most, shield = team_read(task)
    if hp is not None:
        record.first_team = record.first_team or (hp, most)
        record.last_team = (hp, most)
    frame = frame_of(task)
    deck = dict(cards.DECK)
    line = {
        "kind": "plan", "fight": record.id, "mode": record.mode, "turn": record.turns, "t": round(now - record.started, 2),
        "ap": state.action_points, "ap_read": not unread, "hand": [card_line(held) for held in hand], "hand_size": state.hand_size,
        "played": list(state.played), "last_turn": list(state.last_turn), "battle": list(state.battle), "kept": list(state.kept),
        "refused": sorted(turn.refused), "weakness": state.weakness, "invulnerable": state.invulnerable, "enemies": state.enemies,
        "devours": state.devours,
        "foes": [foe_line(foe) for foe in state.foes], "team_hp": hp, "team_max": most, "team_share": state.team,
        "after_hit": state.health, "shield": shield, "ep": None if frame is None else board.banked_points(frame),
        "plans": [{"ap": points, "offered": [index for index, held in enumerate(hand) if any(held is one for one in playable)],
                   "plan": [chosen["name"] for chosen in plan], "kills": [index for index, chosen in enumerate(plan) if chosen.get("kills")]}
                  for playable, points, plan in made],
        "chosen": None if card is None else {"name": card["name"], "key": card.get("key"), "worth": cards.value(card["name"], state),
                                             "kills": bool(card.get("kills"))},
    }
    hits = changed_hits(record)
    if hits is not None:
        line["hits"] = hits
    if deck != record.deck:
        record.deck = deck
        line["deck"] = deck
    write(record, line)


@quietly
def resolved(task, name, result, seen, foes=None, hit=None):
    """Write the play line for a card the game has taken or refused.

    Args:
        task: The running task.
        name: The card.
        result: "played" or "refused".
        seen: What showed it: "hand" (gone from it, or still in it), "retrieve", "toast", "end turn" or "deal".
        foes: The enemies read on the frame that showed it, as `board.Foe`, or None when that frame read none.
        hit: The damage per 100% printed it was learnt to do, or None.
    """
    record = getattr(task, RECORD, None)
    if record is None or record.closed:
        return
    now = time.monotonic()
    record.last_seen = now
    if result == "played":
        record.cards_played += 1
    write(record, {"kind": "play", "fight": record.id, "turn": record.turns, "t": round(now - record.started, 2), "card": name,
                   "result": result, "seen": seen, "foes": None if foes is None else [foe_line(foe) for foe in foes], "hit": hit})


def end(task, record, outcome, why):
    """Write the end line of a fight not yet ended.

    Args:
        task: The running task.
        record: The `Fight`.
        outcome: "won", "lost" or "unknown".
        why: What the outcome was told from.
    """
    record.closed = True
    lost = None
    if record.first_team is not None and record.last_team is not None:
        lost = record.first_team[0] - record.last_team[0]
    finished = record.left_at if record.left_at is not None else record.last_seen
    write(record, {"kind": "end", "fight": record.id, "mode": record.mode, "outcome": outcome, "why": why, "turns": record.turns,
                   "plans": record.plans, "team_hp_lost": lost, "seconds": round(finished - record.started, 1),
                   "cards_played": record.cards_played})


@quietly
def left(task):
    """Note that the battle screen has gone, and end the fight if this frame says how it went. Called on every frame off it.

    Args:
        task: The running task.
    """
    record = getattr(task, RECORD, None)
    if record is None or record.closed:
        return
    if record.left_at is None:
        record.left_at = time.monotonic()
    settle(task, record)


def settle(task, record):
    """End a fight that has left the battle screen when this frame shows a title that says how it went.

    The team readout is not read here: off the battle screen other "N/M" text can sit in its region.

    Args:
        task: The running task.
        record: The `Fight`.
    """
    texts = [box.name for box in getattr(task, "all_texts", None) or []]
    if any(title in text for text in texts for title in WON_TITLES):
        end(task, record, "won", "reward title")
    elif any(title in text for text in texts for title in LOST_TITLES) or any(fold(text) in LOST_LINES for text in texts):
        end(task, record, "lost", "defeat title")
