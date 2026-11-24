"""Re-run the card picker over recorded fights and report where its decisions differ from the ones the bot made.

Every plan line `src/en/fight_log.py` wrote holds the board the picker saw. This rebuilds that board, runs the current `cards.plan` on
it, and reports each plan that comes out different, along with what the decisions did with the board: kills available and missed,
plays worth nothing, shields with no hit coming, and plays per turn.

It scores decisions, not outcomes. It cannot know what the enemies would have done or which cards would have been drawn after a
different play, so a better report says the picker uses what the screen showed better, not that the fights would have gone better.

Run `python scripts/replay_fights.py` from the repository root to read `data/fights.1.jsonl` and `data/fights.jsonl`, or name the
files to read. `--show N` lists the first N differing plans, `--json PATH` writes the whole report.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import board, cards, fight_log  # noqa: E402

DEFAULT_FILES = (REPO_ROOT / fight_log.OLDER_FILE, REPO_ROOT / fight_log.FIGHTS_FILE)
KINDS = ("plan", "play", "end")


def read_lines(paths):
    """Read the record files in order, skipping any line that is not a record.

    Args:
        paths: The files, oldest first. A missing one is passed over.

    Returns:
        The records as dicts, and how many lines were skipped as unreadable.
    """
    records, skipped = [], 0
    for path in paths:
        if not Path(path).exists():
            continue
        with open(path, encoding="utf-8", errors="replace") as file:
            for text in file:
                if not text.strip():
                    continue
                try:
                    line = json.loads(text)
                except ValueError:
                    skipped += 1
                    continue
                if readable(line):
                    records.append(line)
                else:
                    skipped += 1
    return records, skipped


def readable(line):
    """Tell whether a parsed line is a record the report can count.

    A plan line's own fields are checked when it is rebuilt; a play or end line is only counted, so its counted fields are checked here.

    Args:
        line: One parsed JSON value.

    Returns:
        Whether it is a plan, play or end line of a named fight, with an outcome or turn of a type the report can count.
    """
    if not isinstance(line, dict) or line.get("kind") not in KINDS or not isinstance(line.get("fight"), str):
        return False
    if line["kind"] == "end":
        return line.get("outcome") is None or isinstance(line["outcome"], str)
    if line["kind"] == "play":
        return line.get("turn") is None or isinstance(line["turn"], int)
    return True


def hand_of(line):
    """Rebuild the hand cards the picker was given.

    Args:
        line: A plan line.

    Returns:
        The hand card dicts, carrying a `cost` only where the screen showed one.
    """
    hand = []
    for card in line["hand"]:
        held = {"name": card["name"], "key": card.get("key")}
        if card.get("shown"):
            held["cost"] = card["cost"]
        hand.append(held)
    return hand


def foes_of(foes):
    """Rebuild the enemies as `board.enemies` read them.

    Args:
        foes: The recorded enemies.

    Returns:
        A tuple of `board.Foe`.
    """
    return tuple(board.Foe(foe["x"], foe["hp"], foe["counter"], foe["weakness"], foe["hp_source"] in ("both", "crop"),
                           foe["hp_source"] == "both") for foe in foes)


def board_of(line, points, shrugging=()):
    """Rebuild the board a plan was made against.

    Args:
        line: A plan line.
        points: The Action Points that call planned against.
        shrugging: Where each enemy stands that shrugs off hits, as the fight's earlier lines showed them.

    Returns:
        The `cards.Board`.
    """
    return cards.Board(action_points=points, weakness=line["weakness"], hand=tuple(card["name"] for card in line["hand"]),
                       played=tuple(line["played"]), last_turn=tuple(line["last_turn"]), battle=tuple(line["battle"]),
                       hand_size=line["hand_size"], kept=tuple(line["kept"]), invulnerable=line["invulnerable"], enemies=line["enemies"],
                       health=line["after_hit"], foes=foes_of(line["foes"]), team=line["team_share"], shrugging=tuple(shrugging))


@contextmanager
def as_recorded(hits, deck):
    """Put the hits and deck texts a plan was made with in place of the live ones while it is replayed.

    Args:
        hits: Combatant to hits, as the fight's lines have carried them so far.
        deck: Card name to the text of the version the deck held.

    Yields:
        Nothing; the live tables are put back afterwards.
    """
    # Built first, so tables that cannot be rebuilt raise before anything live has changed.
    recorded_hits = {who: deque(figures, maxlen=cards.HIT_MEMORY) for who, figures in hits.items() if figures}
    recorded_deck = dict(deck)
    saved_hits, saved_deck = dict(cards.HITS), dict(cards.DECK)
    cards.HITS.clear()
    cards.HITS.update(recorded_hits)
    cards.DECK.clear()
    cards.DECK.update(recorded_deck)
    # A card's figures are cached from the deck's text, so a cache left from other texts would plan with those.
    cards.parsed.cache_clear()
    try:
        yield
    finally:
        cards.HITS.clear()
        cards.HITS.update(saved_hits)
        cards.DECK.clear()
        cards.DECK.update(saved_deck)
        cards.parsed.cache_clear()


def judged(name, state):
    """Say what a choice did with the board.

    Args:
        name: The card chosen, or None for ending the turn.
        state: The board it was chosen against.

    Returns:
        Whether it was worth nothing, and whether it shielded with no hit coming.
    """
    if name is None:
        return False, False
    return cards.value(name, state) <= 0, bool(cards.features(name).shield) and not cards.hit_coming(state)


def replay(records):
    """Re-plan every recorded plan line under the current code and score the decisions.

    Args:
        records: The records, as `read_lines` gives them.

    Returns:
        The report as a dict.
    """
    hits, decks = defaultdict(dict), {}
    # Per fight, where each enemy stands that shrugs off hits and each that took one aimed hit whole, and the card its last plan line
    # chose with its kill target and board.
    shrugging, absorbed, chosen = defaultdict(tuple), defaultdict(tuple), {}
    report = {"plans": 0, "broken": 0, "calls": 0, "same": 0, "differ": [], "fights": 0, "fights_ended": 0, "outcomes": Counter(),
              "recorded": Counter(), "replayed": Counter(), "plays_per_turn": {}}
    plays = Counter()
    for line in records:
        fight = line["fight"]
        if line["kind"] == "end":
            report["fights_ended"] += 1
            report["outcomes"][line.get("outcome")] += 1
            continue
        if line["kind"] == "play":
            if line.get("result") == "played":
                plays[(fight, line.get("turn"))] += 1
            pending = chosen.pop(fight, None)
            if pending and line.get("result") == "played" and line.get("seen") == "hand" and line.get("card") == pending[0]:
                try:
                    with as_recorded(hits[fight], decks.get(fight, {})):
                        shrugging[fight], absorbed[fight] = cards.shrugging_after(*pending, foes_of(line.get("foes") or ()), absorbed[fight])
                except (KeyError, TypeError, ValueError, AttributeError):
                    # A play line cut short or edited by hand says nothing about what the card did, so the fight's memory stays as it was.
                    pass
            continue
        if fight not in decks:
            report["fights"] += 1
        try:
            deck = line.get("deck", decks.get(fight, {}))
            if not isinstance(deck, dict):
                # Kept from the fight's later lines, which would otherwise all be planned against it.
                raise TypeError(f"deck is a {type(deck).__name__}")
            hits[fight].update(line.get("hits") or {})
            decks[fight] = deck
            chosen[fight] = replan(line, hits[fight], decks[fight], report, shrugging[fight])
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            # Valid JSON that is no plan line this code can rebuild, such as one cut short or edited by hand.
            report["broken"] += 1
    if plays:
        turns = list(plays.values())
        report["plays_per_turn"] = {"turns": len(turns), "mean": round(sum(turns) / len(turns), 2), "most": max(turns),
                                    "spread": dict(sorted(Counter(turns).items()))}
    return report


def replan(line, hits, deck, report, shrugging=()):
    """Re-run every plan one plan line holds and add what it finds to the report.

    Args:
        line: The plan line.
        hits: The hits its fight's lines have carried so far.
        deck: The deck texts its fight's lines have carried so far.
        report: The report being built.
        shrugging: Where each enemy stands that shrugs off hits, as the fight's earlier lines showed them.

    Returns:
        The card the bot chose, the x of the enemy the first plan re-run aims it at as a kill, None when it aims it at none, and the
        board it was chosen against, for `cards.shrugging_after`; None when the bot chose nothing.
    """
    hand = hand_of(line)
    calls, aims = [], {}
    with as_recorded(hits, deck):
        for call in line["plans"]:
            state = board_of(line, call["ap"], shrugging)
            plan = cards.plan([hand[at] for at in call["offered"]], state)
            if not calls:
                aims = {card["name"]: card["target"] for card in reversed(plan) if card.get("kills")}
            calls.append((call, state, [card["name"] for card in plan], [at for at, card in enumerate(plan) if card.get("kills")]))
        report["plans"] += 1
        replayed = next((now[0] for _, _, now, _ in calls if now), None)
        for index, (call, state, now, now_kills) in enumerate(calls):
            report["calls"] += 1
            if now == call["plan"] and now_kills == call["kills"]:
                report["same"] += 1
            else:
                report["differ"].append({"fight": line["fight"], "turn": line["turn"], "t": line["t"], "call": index,
                                         "hand": [card["name"] for card in hand], "recorded": call["plan"], "recorded_kills": call["kills"],
                                         "now": now, "now_kills": now_kills})
        if calls:
            _, first, _, first_kills = calls[0]
            chosen = line["chosen"]
            kill = bool(first_kills)
            count(report["recorded"], chosen and chosen["name"], kill, bool(chosen and chosen["kills"]), first)
            count(report["replayed"], replayed, kill, kill, first)
            if chosen:
                return chosen["name"], aims.get(chosen["name"]), first
    return None


def count(tally, name, kill, killing, state):
    """Add one decision to a column of the report.

    Args:
        tally: The column's `Counter`.
        name: The card chosen, or None.
        kill: Whether the current picker finds a sure kill on the board.
        killing: Whether the choice is part of a sure kill.
        state: The board.
    """
    nothing, needless = judged(name, state)
    tally["decisions"] += 1
    tally["kill available"] += kill
    tally["kill missed"] += kill and not killing
    tally["worth nothing"] += nothing
    tally["shield with no hit coming"] += needless


def summary(report, skipped, show):
    """Write the report as text.

    Args:
        report: From `replay`.
        skipped: Lines skipped as unreadable.
        show: How many differing plans to list.

    Returns:
        The lines of text.
    """
    out = [f"{report['fights']} fight(s), {report['fights_ended']} ended {dict(report['outcomes'])}, {report['plans']} plan line(s), "
           f"{skipped} unreadable line(s) skipped, {report['broken']} plan line(s) that could not be rebuilt",
           f"plans re-run: {report['calls']}, same: {report['same']}, different: {len(report['differ'])}",
           "decisions (recorded / current picker's first card):"]
    for key in ("decisions", "kill available", "kill missed", "worth nothing", "shield with no hit coming"):
        out.append(f"  {key}: {report['recorded'][key]} / {report['replayed'][key]}")
    if report["plays_per_turn"]:
        out.append(f"cards played per turn: {report['plays_per_turn']}")
    for diff in report["differ"][:show]:
        out.append(f"  fight {diff['fight']} turn {diff['turn']} at {diff['t']}s, hand {diff['hand']}: "
                   f"recorded {diff['recorded']} (kills {diff['recorded_kills']}), now {diff['now']} (kills {diff['now_kills']})")
    return out


def main(argv=None):
    """Replay the record files named on the command line, or the default ones.

    Args:
        argv: The arguments, `sys.argv[1:]` when None.

    Returns:
        0, since a different decision is a finding rather than a failure.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     epilog="It scores decisions, not outcomes: it cannot know what the enemies or the draws would have done after a different play.")
    parser.add_argument("files", nargs="*", type=Path, help="record files, oldest first (default: data/fights.1.jsonl, data/fights.jsonl)")
    parser.add_argument("--show", type=int, default=10, help="how many differing plans to list")
    parser.add_argument("--json", type=Path, help="write the whole report here")
    args = parser.parse_args(argv)
    records, skipped = read_lines(args.files or DEFAULT_FILES)
    report = replay(records)
    print("\n".join(summary(report, skipped, args.show)))
    if args.json:
        args.json.write_text(json.dumps({**report, "skipped": skipped}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
