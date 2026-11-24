"""Decide which cards to play in a Sortie battle, and in what order.

Sortie has no Auto button, so the bot picks every card itself. Upstream looks each hand card up in a list of
names the user typed and plays the first match, but that list starts empty on the Global client - its default
is Chinese card names English OCR can never match - so every turn falls through to pressing each hotkey and
hoping. This module replaces the hoping.
"""

import re
from bisect import bisect_left, bisect_right
from collections import Counter, deque, namedtuple
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import accumulate, combinations

from src.en.game_battle import CARD_CATEGORY, CARD_COST, CARD_EXHAUSTS, CARD_OWNER, CARD_TARGET, COMBATANT_ATTRIBUTE, X_COST
from src.en.game_quality import COMBATANT_ROLE
from src.en import kits
from src.en.game_text import DESCRIPTIONS
from src.en.kits.kit import (ATTACK_CATEGORY, PHASE_ATTACK, PHASE_EPIPHANY, PHASE_ESCAPE, PHASE_FREE, PHASE_OTHER, PHASE_PRIME, PHASE_SETUP,
                             PHASE_SPENDS_EVERYTHING, PHASE_UPGRADE, base_name)
from src.en.quality import fold, in_order, index, one_edit_apart, unconfused

# Action Points a turn starts with, before anything in a run changes the figure.
BASE_ACTION_POINTS = 3
# `X_COST` comes from the generated data rather than being restated here, so a card that spends everything
# left cannot come to mean one thing to the generator and another to this.
# Categories the game deals you rather than ones you choose. A Curse is someone else's doing and a Status
# Ailment is damage waiting to happen, so neither is ever part of a plan.
DEALT_TO_YOU = frozenset({"ABNORM", "CURSE"})
# One of those that does its harm only while held - "If in hand, at the end of the turn", "If this card is in hand",
# a "Retain:" line - so playing it is how to be rid of it.
HELD_HARM = re.compile(r"\b(?:if|when) (?:this card is )?in hand|if the turn ends when in hand|when this card is retained|^Retain:", re.I | re.M)
# A line of effect text that fires on some other event - "When this card is Drawn", "If in hand" - rather than when the card is played.
TRIGGERED_LINE = re.compile(r"^\s*(?:if|when)\b", re.I)
# What a dealt card can do when played that is worse than holding it: hit your side, buff the enemy, or make more of itself.
PLAYED_HARM = re.compile(r"\b(?:allies|combatants?|self|stress|create)\b|\bdecrease (?:hp|ap)\b|\b(?:morale|fortitude|immunity|evasion|shield)\b.*\benem", re.I)
# The points clearing one of those leaves for the rest of the hand, since it is only bought ahead of the hand's own cards.
CLEARING_RESERVE = 1
# The most one of those may cost to be cleared. A dearer one, as Cursed Mace at 3, tends to have a way to get cheaper as the turn goes.
CLEARING_MAX_COST = 1
# A card that gets cheaper for each card Exhausted this turn, as Brand of Annihilation does. The screen never reads it lowered.
EXHAUST_DISCOUNT = re.compile(r"When a card is Exhausted, decrease Cost of this card by (\d+)", re.I)
# Any effect a card's text can carry names a number, so a text without one - blank, or flavour - does nothing when played.
INERT_EFFECT = re.compile(r"\d")
# A card of your own that works just by being held, as Unknown: Mutant Sample's "If in hand, +40% Damage Amount".
# It shows no cost and cannot be played.
HELD_HELP = re.compile(r"^If (?:this card is )?in hand,", re.I)
# A line the generator marks as firing when the card is kept in hand at the end of the turn, which playing it never does.
RETAIN_LINE = re.compile(r"^Retain:.*\n?", re.M)
# A card that only makes other cards better, so it wants to land before them.
SETUP_CATEGORY = "POWER"
# What a card the data has never heard of is assumed to cost. One is both the commonest price and the
# forgiving guess: too low only risks a card that will not play, while too high would refuse it outright.
ASSUMED_COST = 1

# What a combatant's cards turn into on a Mental Breakdown at max Stress. They are free, playing them is how the combatant recovers, and
# Fear's unexpected result can end the fight outright, so they are tried before anything else is spent.
BREAKDOWN_CARDS = frozenset({"Confusion", "Impulse", "Guilt", "Daze", "Escapism", "Gloom", "Charm", "Trance", "Fear", "Despair"})

# Roughly what one drawn card is worth, said in damage. A card drawn is about one more card played, and the
# ordinary card costing one point does 100% damage, so that is the exchange rate the data itself suggests.
DRAW_VALUE = 100
# Shield and heal keep a combatant standing but do not end the fight, so the same number is worth less than damage.
SHIELD_WEIGHT = 0.6
# What matching the attribute an enemy is weak to is worth. The game pays a match in extra damage and in
# extra Tenacity damage both, so a matching card is worth more than the figure printed on it.
WEAKNESS_BONUS = 1.5
# What a Healer's or a Protector's damage is worth against the figure printed on it. Their stats are low, so the same 100% hits for less than
# a Core's or an Attacker's, and their attacks should not take their points.
SUPPORT_DAMAGE = 0.5
SUPPORT_ROLES = frozenset({"Healing", "Protection"})
# What a role's own specialty is worth against the figure printed on it, over damage: a Healer's heal and a Protector's shield.
SPECIALTY_WEIGHT = 1.5
# The share of the team's HP left after the enemy's next hit at which a heal has nothing to restore, so it is worth nothing.
HEALTHY = 0.9
# What a card is worth when its effect text says nothing measurable - an Immunity, a Morale, a status with no
# figure on it. Rating those zero would mean a buff never got played at all, which is worse than the guess.
# The ordinary card costing one point does 100% damage, so an unreadable effect is priced at the same rate.
UNREAD_VALUE = 100
# What an Action Point a card gains is worth: the ordinary card costing one point does 100% damage. Only while the hand holds more to pay for.
POINT_VALUE = 100
# The share of the team's HP after the enemy's next hit from which no hit is coming, so a shield has nothing to stop. The bar reads 1.0 then.
NO_HIT = 0.995
# How many turns a fight has to have left for an Upgrade to pay for its points. Below it an Upgrade is worth that share of its value.
UPGRADE_TURNS = 2
# How many hits a combatant has to have been seen landing before any estimate of their damage is trusted.
CALIBRATED = 3
# The share of a combatant's hits an estimate of a sure kill must not count on beating. Buffs, Marks and crits spread one combatant's damage
# per 100% from 63 to 154 over a night's logs, so a kill is planned on the low end, and the turns a fight has left on the middle.
SURE_HIT = 0.25
TYPICAL_HIT = 0.5
# How many of a combatant's hits are remembered, the newest, so a level gained mid-run moves the estimate.
HIT_MEMORY = 50
# How far apart two reads of one enemy can stand, as a share of the frame's width. Enemies stand 0.06 or more apart.
SAME_ENEMY = 0.03
# The most HP an enemy may lose to an aimed hit planned at `SHRUG_PLANNED` or more and be taken for one that shrugs off hits. The Aether
# Eater loses 1 a hit behind shields that lose 1 too, so a multi-hit card took 2 off it, while a real hit takes tens.
SHRUG_LOSS = 2
SHRUG_PLANNED = 20
# Where in a turn the cards that kill go: after a chance to escape or the glowing card, before everything a fight that ends never needs.
PHASE_KILL = PHASE_UPGRADE - 0.5
# How many states of the search for a sure kill's order to remember, and of its bounds. Ten attacks against four tough enemies, planned
# at 3, 6 and 10 AP, left about 1,600 of each.
SEARCHED_STATES = 1 << 16
# What `kill_search` puts for the HP left of an enemy that every hit left together cannot kill.
UNKILLABLE = float("inf")
# The data's targets for a card that hits one enemy the player picks. The game raises it on the leftmost enemy standing and a TAB moves
# it on. Every other card that hits one enemy picks a random one.
AIMED = frozenset({"TARGET_SELECTED_MONSTER", "TARGET_SELECTED_WITH_SPLASH", "TARGET_SELECTED_MONSTER_AUTO_RANDOM"})
# What a card lit up for an Epiphany is worth beyond what it does this turn. The upgrade is permanent and the
# run is long, so it comfortably outweighs one turn of anything.
EPIPHANY_BONUS = 1000

# A damage figure is a percentage followed shortly by the word Damage. "Damage Amount" is excluded on purpose:
# that phrasing is always a modifier on some other card's damage, as in "Increases Damage Amount by 20%", and
# counting it would rate a card that does nothing by itself as though it hit hard. A hit count after it, as in
# "40% Damage x 3", or right after the percentage, as in "60% x 3 Damage", multiplies the figure. The client mostly
# writes a multiplication sign, and a few cards a plain x.
DAMAGE = re.compile(r"(\d+)%(?:\s*[×x]\s*(\d+))?[^\n]{0,24}?Damage(?!\s+Amount)(?:\s*[×x]\s*(\d+))?")
SHIELD = re.compile(r"(\d+)%[^\n]{0,20}?Shield")
DRAW = re.compile(r"\bDraw (\d+)")
# A line that gains Action Points outright, as Source of Water's "Gain 1 AP". Seven Arms' "If ..., gain 2 AP" has a condition, so it does not count.
AP_GAIN = re.compile(r"^(?:Draw \d+,? and )?gain (\d+) AP\b", re.I | re.M)
# A figure the generator left as X, as Rising Dragon Spire's "Add X Hit(s)". A card carrying one does more than its text says, by an unknown amount.
UNKNOWN_FIGURE = re.compile(r"\bX\b")
# A heal the card makes when played, as in "Heal 100%". Mid-line ones are triggers, as in "At the end of the turn, Fixed Heal 30%".
HEAL = re.compile(r"^Heal (\d+)%", re.MULTILINE)
# A line that only scales, repeats or stands in for a heal, or moves Action Points, as Blessing of Waves' "Increase Heal Amount by 30% for
# each AP" or Fresh Raw Meat's "Recover 15% of Max HP". With the heal or the points not needed, such a line has nothing else to offer.
HEAL_OR_POINTS_LINE = re.compile(r"\bHeal\b|\bRecover \d+% of Max HP\b|\bAP\b")
# A line of damage that lands on every enemy, as in Vulture Ejection's "120% Defense-Based Damage to all enemies". The data's own target
# misses some, Diagonal Slash among them. "To random enemies" spreads its hits instead, so that stays one target's worth.
ALL_ENEMIES = re.compile(r"\bto all enemies\b")
# The line of a card that hits the enemy picked and some of another, as "70% Damage to another enemy" under "140% Damage".
OTHER_ENEMY = re.compile(r"\bto another enemy\b")
# A card that makes the next attack hit harder, or the target take more - "Add 1 Hit(s) to the next Attack Card", "+X% Damage
# Amount to the next Bullet card", "2 Vulnerable". Played after the attacks, as its category alone left it, it lands on nothing.
PRIME = re.compile(r"(?:Damage Amount|Hit\(s\)|Proc)[^|\n]*?\bnext\b[^|\n]*?\b(?:Attack|Bullet|Bind) Card"
                   r"|(?:\b\d+ Vulnerable|Vulnerable \d+)(?! to (?:allies|self))|Damage Amount taken by the target", re.I)

# How many copies of each version of a card the deck holds, by canonical name: the last `piles` read, and every change `piles` saw since.
COPIES = {}
# The effect text of every card in `COPIES`, by canonical name: the Epiphany it carries, the weakest where copies differ.
# Mutated in place, never rebound, and empty until a read, so every card falls back to its base text.
DECK = {}
# How many times a battle a card comes back to hand after it is played, by canonical name, summed over its copies, from the deck read.
RETRIEVES = {}
# Damage per 100% printed that each combatant's attacks were seen doing, by combatant, newest last. Kept for the whole run, across fights.
HITS = {}

# What a card does, in the terms the ordering cares about.
Features = namedtuple("Features", [
    # Damage to one enemy, as a percentage with every hit added up.
    "damage",
    # Shield, as a percentage.
    "shield",
    # Cards drawn.
    "draw",
    # The part of `damage` that lands on every enemy rather than one.
    "spread",
    # Heal, as a percentage.
    "heal",
], defaults=[0, 0])
# What the picker knows about the moment it is choosing in.
Board = namedtuple("Board", [
    # Action Points to plan against.
    "action_points",
    # The attribute the enemies are weak to, which `board.weakness` reads off the badge beside each enemy's action counter.
    "weakness",
    # The hand card the run has lit up. Nothing reads it yet - no capture holds one to pin the region against - so it is None.
    "epiphany",
    # Every card in hand as canonical names, for the kits. Empty means `plan` fills it from the hand it is given.
    "hand",
    # Canonical names of the cards the game took this turn, oldest first, for kits that count what has been played.
    "played",
    # The same for the turn before, which is empty on a battle's first turn.
    "last_turn",
    # The same for the whole battle, this turn's last. Where a mode counts no map nodes to tell fights apart, it reaches back one turn.
    "battle",
    # The hand size the hand counter reads, which is more than `hand` when OCR missed a card. 0 when not known.
    "hand_size",
    # Canonical names of the cards still in hand when the turn before ended, so their Retain effects have fired.
    "kept",
    # Canonical card name to the text of the version the deck holds, for kits whose rule rests on one Epiphany. `DECK` itself, so it sees every read.
    "deck",
    # Whether an enemy shows Absolute Invincibility, from `board.enemy_invulnerable`, so damage is worth nothing this turn.
    "invulnerable",
    # How many enemies are on screen, the fewest any frame of the turn without a card raised showed by its counters or `board.enemies`,
    # whichever showed more, so damage to all enemies counts once for each. 1 when not known.
    "enemies",
    # The share of the team's HP left after the enemy's next hit, from `board.team_after_hit`. None when not read.
    "health",
    # Every enemy read off the screen, as `board.Foe` left to right: where it stands, its HP and how soon it acts. Empty when not read.
    "foes",
    # The share of the team's HP it has now, from the readout over the team bar. A heal cannot store HP for a hit still to come. None when not read.
    "team",
    # Where each enemy stands that shrugged off an aimed hit this fight, from `shrugging_after`. No kill is planned on one.
    "shrugging",
], defaults=[BASE_ACTION_POINTS, None, None, (), (), (), (), 0, (), DECK, False, 1, None, (), None, ()])

# How many distinct readings to remember the folding of. OCR invents new misspellings all session, so this
# is bounded rather than unlimited, and it is far larger than the ten names one frame ever asks about.
CACHED_READINGS = 1024
# Folded card name to the client's own spelling, so a reading run together or in the wrong case still lands.
CARD_INDEX = index(CARD_COST)
# Every card that gains AP outright, which a copy falls back to when nothing on the user's list is on offer.
AP_CARDS = tuple(sorted(name for name in CARD_COST if AP_GAIN.search(DESCRIPTIONS.get(name, ""))))

# The type label the game prints under every card, in both the English the Global client draws and the
# Chinese `ocr.po` rewrites some of them into. Upstream's own filter lists only Chinese, so every English
# label reached the hand as a card name - `Basic Atta` was the commonest junk reading in a Chaos recording.
# `Defense` is here because the catalog does rewrite it, to a literal upstream's exclude list never had.
# The level badge an upgraded card carries is read the same way, as "@ Lv." or as the 等级 `ocr.po` rewrites "LV" to.
TYPE_LABELS = ("basic attack", "basic skill", "status ailment", "attack", "skill", "curse", "power",
               "upgrade", "defense", "攻击力", "防御力", "状态异常", "lv", "等级")
FOLDED_LABELS = tuple(fold(label) for label in TYPE_LABELS)
# The label under every Mental Breakdown card, matched only on a run of 7 of its letters. The rules for the short labels would eat real
# cards cut short: "Accent" is Mute Accent and one edit from "Ment", and "Down" is Downward Cut. No card name holds any of these runs.
BREAKDOWN_PIECES = frozenset(fold("Mental Breakdown")[start:start + 7] for start in range(len(fold("Mental Breakdown")) - 6))
# The type icon shares the label's OCR box and is read as a stray letter or two in front of it, which is why
# `XBasic A` occurs. `src/en/ocr_text.py` trims the same way for the same reason.
LABEL_PREFIX = 2
# The shortest piece from inside a label, rather than its start, taken for that label - "tack", "grade" and "pgrad" are real readings.
LABEL_PIECE = 4
# How much of a name has to survive before a truncated reading is worth repairing. Below this a stub matches
# too many cards to mean anything - four would rescue only two more readings out of 1,662 and risk far more.
MIN_STUB = 5
# How many letters at the end of a name cut short may be wrong. The reader mangles the letter it cut at, as in "Quantun",
# "Barrier Der" and "Fairy's Prc", so a stub that fits nothing is retried with up to this many dropped.
GARBLED_TAIL = 2
# How much of a name a reading checked against the deck has to keep, as a share of its letters. Live, Annihilation came back as
# "DarkMistSecretAil", 17 of 29, far past what the whole roster can risk but the only Dark Mist card those letters fit in that deck.
DECK_SHARE = 0.5
# Tiphera's three Archetype cards differ only by a glyph the reader seldom keeps - "Archetype:O", "Archetyp", "rchetype:".
# Matched on folded text, on a piece of the word, with a real glyph or the O, C or 0 the reader takes the circle for at the end.
ARCHETYPE_READ = re.compile(r"(?:rchet|het[yv]p)[a-z]*?([○△□oc0]?)$|^arche$")
ARCHETYPES = {"△": "Archetype: △", "□": "Archetype: □"}
# All three cost nothing, so which one a reading that lost its glyph is taken for changes how it ranks, never whether it is played.
ARCHETYPE_UNREAD = "Archetype: ○"
# The keyword tags a card's tooltip lists, like "[Unique / Bullet]", which the reader picks up when the tooltip covers the hand.
# No card name holds a bracket or a slash.
KEYWORD_TAG = re.compile(r"[\[\]/]")


def looks_like_label(folded):
    """Say whether a reading is a type label, read whole, cut short or a letter wrong.

    Args:
        folded: The reading, already folded, maybe with the type icon read as a letter or two in front.

    Returns:
        True when it is a label, the start of one or a piece from inside one, give or take one letter.
    """
    if any(piece in folded for piece in BREAKDOWN_PIECES):
        return True
    for trimmed in (folded[cut:] for cut in range(LABEL_PREFIX + 1)):
        if not trimmed:
            continue
        for label in FOLDED_LABELS:
            start = label[:len(trimmed)]
            if trimmed == start or one_edit_apart(trimmed, start) or one_edit_apart(trimmed, label) or (len(trimmed) >= LABEL_PIECE and trimmed in label):
                return True
    return False


def owner(name):
    """Name the combatant a card belongs to.

    Args:
        name: A card name the data knows, in any Epiphany.

    Returns:
        The combatant, or None for a card no combatant owns.
    """
    return CARD_OWNER.get(base_name(name))


def stub_card(stub, party=frozenset()):
    """Find the one card a name cut short can be.

    The reader cuts from either end - "Knife Tos" and "rrier Der" are both real readings - so a stub is tried as the start
    of a name and then as a piece of one. Two cards that fit means the reading cannot say which, and a shorter stub only fits more.
    A reading that looks like a label only gets the first try, so "Quant" is still Quantum Seed but "XAttacl" finds no card.
    Since we know who is in the party, a fit owned by any other combatant cannot be in hand, which narrows the lookup to the cards
    this party can hold - "ord Slas" fits Rossweisse's Sword Slash and Yuki's Longsword Slash, and only one of them is in a party.

    Args:
        stub: A folded reading the index has no spelling for.
        party: The combatants known to be in the party. Empty when none are known yet, which leaves every card in play.

    Returns:
        The card, or None when nothing or more than one card fits. A card and its Epiphanies count as one card, the plainest of them, as do
        names that only add to it at the same cost.
    """
    tries = [(cut, fits) for cut in range(GARBLED_TAIL + 1) for fits in (str.startswith, str.__contains__)]
    for cut, fits in tries[:1] if looks_like_label(stub) else tries:
        piece = stub[:len(stub) - cut]
        if len(piece) < MIN_STUB:
            return None
        # Over the exact spellings only: the fallback spellings in the index rearrange or rewrite letters, so a piece of one means nothing.
        matches = [real for folded, real in CARD_INDEX.exact.items() if fits(folded, piece)]
        # Kept whole when no fit is the party's, so a member whose cards have not been read yet still gets the old answer.
        if party:
            matches = [real for real in matches if owner(real) in (None, *party)] or matches
        if matches:
            plainest = min(matches, key=len)
            # A longer name built on the plainest at its price is played the same: "Inferno" fits Inferno Rhapsody and Inferno Rhapsody: Heaven.
            alike = all(fold(real).startswith(fold(plainest)) and cost(real) == cost(plainest) for real in matches)
            return plainest if alike or len({base_name(real) for real in matches}) == 1 else None
    return None


@lru_cache(maxsize=CACHED_READINGS)
def canonical(name, party=frozenset(), deck=frozenset()):
    """Turn a name as read off the screen into the one the data is keyed by.

    Args:
        name: The card name the reader produced.
        party: The combatants known to be in the party, which settles a name cut short that fits cards of several combatants.
        deck: The canonical names of the cards the deck holds, from `DECK`, for a hand card too garbled for the whole roster.

    Returns:
        The client's spelling, or the name unchanged when nothing matches it.
    """
    # The hotkey sits just above the card name, close enough that the reader sometimes returns the two as one
    # box - a real hand came back as "1=Soul Riff". No card in the data is named starting with a digit, so a
    # leading one is the key rather than part of the name. It comes off before anything else, because the
    # looser spellings read a 1 as a letter and would land "1Homing Laser" on "Homing Laser L".
    stub = fold(name).lstrip("0123456789")
    known = CARD_INDEX.look_up(stub)
    if known and deck and known not in deck and stub not in CARD_INDEX.exact:
        # The index guesses at a reading it cannot spell, and a deck card the reading sits inside beats that guess. Live, "sidual Herb"
        # went to Residual Herb with Harmonization: Residual Herb in the deck.
        held = [real for real in deck if stub in fold(real)]
        known = held[0] if len(held) == 1 else known
    if known:
        return known
    # The reader also cuts a name short while the hand animates, so "Knife Tos" arrives for "Knife Toss".
    # Only an unambiguous stub is repaired: two cards start "Attac", and guessing between them would be
    # worse than leaving the reading alone for the label test to deal with.
    known = stub_card(stub, party) or deck_card(stub, deck)
    if known:
        return known
    archetype = ARCHETYPE_READ.search(stub)
    if archetype:
        return ARCHETYPES.get(archetype.group(1) or "", ARCHETYPE_UNREAD)
    return name


def described(name, description):
    """Tell apart cards whose names differ only by the glyph after a colon, by the effect text read under the name.

    Args:
        name: The card name the reader produced.
        description: The effect text the reader produced, from upstream's `recognize_cards`.

    Returns:
        The card of that family whose text the description is closest to, else the canonical name.
    """
    named = canonical(name)
    family, colon, _ = named.partition(":")
    kin = [card for card in DESCRIPTIONS if card.startswith(family + ":")] if colon and description else []
    read = fold(description)
    return max(kin, key=lambda card: SequenceMatcher(None, fold(text_of(card)), read).ratio(), default=named)


def deck_card(stub, deck):
    """Find the one card the deck holds whose letters a garbled reading keeps in order.

    Args:
        stub: A folded reading neither the index nor `stub_card` could place.
        deck: The canonical names of the cards the deck holds. Empty before the piles are read, which finds nothing.

    Returns:
        The card, or None when no card or more than one fits, or the reading keeps less than `DECK_SHARE` of the name.
    """
    if len(stub) < MIN_STUB or looks_like_label(stub):
        return None
    # Lookalikes folded on both sides, since "Mutation:Forbidden AIgorthm" keeps every letter in order but one capital I. One wrong letter
    # is let through too, which the roster refuses a name this short: live, Joker came back as "Jokel" and "lokel" 14 times in 116.
    reading = unconfused(stub)
    matches = [real for real in deck if len(stub) >= len(fold(real)) * DECK_SHARE
               and (in_order(reading, unconfused(fold(real))) or one_edit_apart(reading, unconfused(fold(real))))]
    return min(matches, key=len) if matches and len({base_name(real) for real in matches}) == 1 else None


def is_card_name(reading):
    """Say whether a reading off the hand names a card, or is the type label printed under one.

    A name the data knows always wins, because several real cards are named after a label - `Attack!`,
    `Curse of the Fairy`, `Defense System`, `Power Anchor`. Testing the label first would delete all of them.
    A reading the data does not know is kept unless it looks like a label, so a card released after the dump
    is still played rather than silently dropped.

    Args:
        reading: The text the reader returned for one hand card.

    Returns:
        True when it should be treated as a card.
    """
    folded = fold(reading)
    if not folded or KEYWORD_TAG.search(reading):
        return False
    # Two real cards are named exactly after a label, `Attack!` and `Curse`. `ocr.po` already ruled on both:
    # the label appears under every card of that type while the card is one of 794, so the label wins. Curse
    # cards are never played voluntarily anyway, which leaves `Attack!` as the whole cost of the rule.
    if folded in FOLDED_LABELS:
        return False
    known = canonical(reading)
    # A label misread by one letter lands on `Attack!` too, so the same ruling covers it. Live, "Attacl" under
    # Cobalt Light was played as `Attack!` and pressed Cobalt Light's key in its place.
    if fold(known) in FOLDED_LABELS:
        return False
    return known in CARD_COST or not looks_like_label(folded)


def features(name):
    """Read what a card does out of its own effect text.

    The text is the client's, written for a player rather than for a parser, so this reads the parts that are
    stated plainly and ignores the rest. A card whose effect is conditional reads as zero, which costs it
    position within its phase but never keeps it out of a plan.

    Args:
        name: The card name, in any spelling.

    Returns:
        The `Features` the text states, all zero for a card with no description.
    """
    return parsed(canonical(name))


@lru_cache(maxsize=None)
def parsed(name):
    """Pull the figures out of one card's effect text.

    Cached on the client's own spelling rather than on what was read off the screen, so the cache is bounded
    by the catalog instead of by however many ways OCR has misread a name over a long session.

    Args:
        name: The canonical card name.

    Returns:
        The `Features` the text states.
    """
    return figures(text_of(name))


def damage_in(text):
    """Add up the damage figures in an effect text, every hit counted.

    Args:
        text: The effect text, or one line of it.

    Returns:
        The total, as a percentage.
    """
    return sum(int(share) * int(before or after or 1) for share, before, after in DAMAGE.findall(text))


def figures(text):
    """Pull the damage, shield and draw figures out of what an effect text does when played.

    Args:
        text: The effect text, as the generated data writes it.

    Returns:
        The `Features` the text states, leaving out its "Retain:" lines.
    """
    text = RETAIN_LINE.sub("", text)
    return Features(
        damage=damage_in(text),
        shield=sum(int(found) for found in SHIELD.findall(text)),
        draw=sum(int(found) for found in DRAW.findall(text)),
        spread=sum(damage_in(line) for line in text.splitlines() if ALL_ENEMIES.search(line)),
        heal=sum(int(found) for found in HEAL.findall(text)),
    )


def cost(name):
    """Say what a card costs to play.

    Args:
        name: The card name, in any spelling.

    Returns:
        The Action Point cost, `X_COST` when it spends everything left, or `ASSUMED_COST` for a card the data
        does not carry.
    """
    return CARD_COST.get(canonical(name), ASSUMED_COST)


def price(card):
    """Say what a hand card costs to play, as it shows on screen when an effect has lowered it.

    Args:
        card: A hand card, carrying a `cost` only when `battle.py` read a lowered one off it.

    Returns:
        The Action Point cost, from the card when it carries one and from `cost` otherwise.
    """
    return card.get("cost", cost(card["name"]))


def discounted(card, board):
    """Take off a card's price what this turn's Exhausts have lowered it by, when the screen did not read it lowered.

    Args:
        card: A hand card, as `_hand_cards` reads it.
        board: The `Board` it would be played into, whose `played` holds this turn's cards.

    Returns:
        The card, carrying its lowered `cost` when an Exhaust took some off.
    """
    found = EXHAUST_DISCOUNT.search(description(card["name"]))
    exhausted = sum(name in CARD_EXHAUSTS for name in board.played)
    if not found or not exhausted or "cost" in card or cost(card["name"]) == X_COST:
        return card
    return {**card, "cost": max(0, cost(card["name"]) - int(found.group(1)) * exhausted)}


def attribute_of(name):
    """Say which attribute a card attacks with.

    A card has no attribute of its own. It carries whichever the combatant holding it has, which is why this
    goes through the owner rather than reading something off the card.

    Args:
        name: The card name, in any spelling.

    Returns:
        The attribute name, or None when the card has no known owner.
    """
    return COMBATANT_ATTRIBUTE.get(owner(canonical(name)))


def category(name):
    """Say what kind of card this is.

    Args:
        name: The card name, in any spelling.

    Returns:
        The category, or None for a card the data does not carry.
    """
    return CARD_CATEGORY.get(canonical(name))


def description(name):
    """Give a card's effect text as the client writes it.

    Args:
        name: The card name, in any spelling.

    Returns:
        The text, or an empty string for a card the data does not carry.
    """
    return text_of(canonical(name))


def text_of(name):
    """Give a card's effect text, as the version of it the deck holds when the deck has been read.

    Args:
        name: The canonical card name.

    Returns:
        The deck's text, else the base text, or an empty string for a card the data does not carry.
    """
    return DECK.get(name) or DESCRIPTIONS.get(name) or ""


def on_play(name):
    """Give the part of a card's effect text that happens when it is played.

    Args:
        name: The card name, in any spelling.

    Returns:
        The text without its "Retain:" lines.
    """
    return RETAIN_LINE.sub("", description(name))


def settle_deck():
    """Value every card by the version of it `COPIES` holds, the weakest where its copies differ."""
    DECK.clear()
    DECK.update({name: min(texts, key=lambda text: strength(figures(text))) for name, texts in COPIES.items()})
    parsed.cache_clear()


def use_deck(copies, retrieves=None):
    """Take a fresh read of the deck in place of everything known about it.

    Args:
        copies: Canonical card name to the effect texts its copies were matched to, from `piles`. A `Counter` of copies per text, or
            any collection of texts, each then counted once.
        retrieves: Canonical card name to the Retrieve counts its copies showed, summed, from `piles`. None when no card showed one.
    """
    COPIES.clear()
    COPIES.update({name: Counter(texts) for name, texts in copies.items()})
    RETRIEVES.clear()
    RETRIEVES.update(retrieves or {})
    settle_deck()


def change_deck(name, text, by):
    """Add or take away one copy of a card, in one version.

    Args:
        name: The canonical card name.
        text: The version's effect text, from `piles.version_of`.
        by: 1 for a copy gained, -1 for one removed.
    """
    held = COPIES.setdefault(name, Counter())
    held[text] += by
    if held[text] <= 0:
        del held[text]
    if not held:
        del COPIES[name]
    settle_deck()


def harmless_to_play(name):
    """Say whether a card's played effect does nothing against you, leaving out lines that fire on some other event.

    Args:
        name: The card name, in any spelling.

    Returns:
        True when no played line matches `PLAYED_HARM`.
    """
    return not any(PLAYED_HARM.search(line) for line in description(name).splitlines() if not TRIGGERED_LINE.match(line))


def worth_clearing(name):
    """Say whether a card dealt to you is better played than held, once nothing better is left to play.

    Args:
        name: The card name, in any spelling.

    Returns:
        True for any Curse with a fixed cost, since a Curse left in hand only clogs it. A Status Ailment counts when it only hurts
        while it sits in hand, when its text does nothing on play, or when it Exhausts once played and does no harm doing it.
    """
    kind, text = category(name), description(name)
    if kind not in DEALT_TO_YOU or cost(name) == X_COST:
        return False
    return kind == "CURSE" or bool(HELD_HARM.search(text)) or not INERT_EFFECT.search(text) or canonical(name) in CARD_EXHAUSTS and harmless_to_play(name)


def hurts_held(name):
    """Say whether a card dealt to you does its harm while it sits in hand, and so is cleared ahead of the hand's own cards.

    Args:
        name: The card name, in any spelling.

    Returns:
        True for a Curse or Status Ailment with a fixed cost whose text says it acts from the hand, as Shackles does.
    """
    return category(name) in DEALT_TO_YOU and cost(name) != X_COST and bool(HELD_HARM.search(description(name)))


def clearing_order(name):
    """Order the cards worth clearing: the ones that deal damage first, then the cheapest.

    Args:
        name: The card name, in any spelling.

    Returns:
        A sort key, smallest first.
    """
    return "damage" not in description(name).lower(), cost(name)


def worth_playing(name):
    """Say whether a card is one the player would ever choose to play.

    Args:
        name: The card name, in any spelling.

    Returns:
        False for a Curse, a Status Ailment or a card that helps by being held, True for anything else, including a card not in the data.
    """
    return category(name) not in DEALT_TO_YOU and not helps_held(name)


def helps_held(name):
    """Say whether a card does its good while it sits in hand, and so is worth keeping rather than playing.

    Args:
        name: The card name, in any spelling.

    Returns:
        True for a card of your own whose text opens with "If in hand".
    """
    return category(name) not in DEALT_TO_YOU and bool(HELD_HELP.match(description(name)))


def value(name, board):
    """Say what a card is worth here, in damage terms, once the kits in play have had their say.

    Args:
        name: The card name, in any spelling.
        board: The `Board` it would be played into.

    Returns:
        The generic `rated` figure, adjusted by every kit the hand switches on.
    """
    return kits.worth(canonical(name), board, rated(name, board), lambda other: rated(other, board))


def rated(name, board):
    """Say what a card is worth by its own text alone.

    Args:
        name: The card name, in any spelling.
        board: The `Board` it would be played into.

    Returns:
        A single figure combining the damage, shield, heal, draw and Action Points the card states, with damage raised when the
        card's attribute is the one the enemies are weak to. A heal with nothing to restore, now or after the next hit, a shield
        with no hit coming and points with nothing to pay for count for nothing, and an Upgrade is cut while the fight has under
        `UPGRADE_TURNS` turns left.
    """
    doing = features(name)
    matched = board.weakness is not None and attribute_of(name) == board.weakness
    if wasted(name, board):
        return 0
    # Damage on an enemy that shrugs off hits is worth nothing, so damage to all enemies counts once for each of the others.
    hit = doing.damage + doing.spread * (max(1, board.enemies - sum(shrugs(foe, board) for foe in board.foes)) - 1)
    full = board.team is not None and board.team >= 1
    heal = 0 if full or board.health is not None and board.health >= HEALTHY else doing.heal
    shield = doing.shield if hit_coming(board) else 0
    worth = strength(doing._replace(damage=0 if board.invulnerable else hit * (WEAKNESS_BONUS if matched else 1), heal=heal, shield=shield),
                     COMBATANT_ROLE.get(owner(name)))
    gained = points_gained(name)
    if gained and points_wanted(name, board):
        worth += POINT_VALUE * gained
    # A heal, a shield or points judged not needed are why such a card is worth nothing, not a text the parser could not read. Such a card
    # with a line nothing here reads, as Tactical Maneuver's Tenacity Damage or Shadow Reload's dagger, still has that line to offer.
    needless = (doing.heal or gained) and not unread_line(name, HEAL_OR_POINTS_LINE) or doing.shield and not unread_line(name)
    if not worth and not needless:
        worth = UNREAD_VALUE * max(cost(name), 1)
    if category(name) == SETUP_CATEGORY:
        turns = fight_turns(board)
        if turns is not None and turns < UPGRADE_TURNS:
            worth *= turns / UPGRADE_TURNS
    if lit_up(name, board):
        worth += EPIPHANY_BONUS
    return worth


def points_gained(name):
    """Say how many Action Points a card gains outright when played.

    Args:
        name: The card name, in any spelling.

    Returns:
        The points, 0 for a card that gains none or only under a condition.
    """
    return sum(int(found) for found in AP_GAIN.findall(on_play(name)))


def points_wanted(name, board):
    """Say whether the rest of the hand has a use for more Action Points than the turn has left.

    Args:
        name: The card that would gain them, left out of the hand once.
        board: The `Board` it would be played into, whose `hand` holds every card in hand.

    Returns:
        True when the other cards worth playing cost more than the points left, or one of them spends every point there is.
    """
    others = list(board.hand)
    if canonical(name) in others:
        others.remove(canonical(name))
    prices = [cost(other) for other in others if worth_playing(other)]
    return X_COST in prices or sum(prices) > board.action_points


def unread_line(name, passed=None):
    """Say whether a card's played text has a line none of the figures here read, as "2 Tenacity Damage" or "3 Vulnerable to all enemies".

    Args:
        name: The card name, in any spelling.
        passed: A pattern for lines to pass over as offering nothing more, or None to count every line.

    Returns:
        True when some line of what happens on play states no damage, shield, draw, heal or Action Points, and `passed` does not match it.
    """
    return any(not any(figures(line)) and not AP_GAIN.search(line) and not (passed and passed.search(line))
               for line in on_play(name).splitlines() if line.strip())


def plays_within(board):
    """Count the most cards the hand could still play this turn, cheapest first, which is how many times every action counter could tick.

    Args:
        board: The `Board`, whose `hand` and `action_points` bound the count.

    Returns:
        The number of cards.
    """
    left, count = board.action_points, 0
    prices = sorted(0 if price == X_COST else price for price in (cost(name) for name in board.hand if worth_playing(name)))
    for price in prices:
        if price > left:
            break
        left -= price
        count += 1
    return count


def hit_coming(board):
    """Say whether the team is to be hit before the turn ends, so a shield has something to stop.

    Args:
        board: The `Board`, with the team bar's prediction in `health` and each enemy's action counter in `foes`.

    Returns:
        True when the bar shows a hit coming or did not read, or when an enemy's counter runs out within the cards the hand could
        still play: every card played takes one off every counter, and an enemy acts at 0. A counter that did not read counts as no hit.
    """
    if board.health is None or board.health < NO_HIT:
        return True
    reach = plays_within(board)
    return any(foe.counter is not None and foe.counter <= reach for foe in board.foes)


def paired(before, after):
    """Match each enemy read before a card was played to its read after, by where it stands.

    Args:
        before: The `board.Foe` reads the card was chosen against.
        after: The reads of the frame that showed it played.

    Returns:
        Pairs of reads of one enemy, for each enemy before with an HP read and exactly one read after with one.
    """
    pairs = []
    for foe in before:
        later = [other for other in after if abs(other.x - foe.x) <= SAME_ENEMY]
        if foe.health is not None and len(later) == 1 and later[0].health is not None:
            pairs.append((foe, later[0]))
    return pairs


def shrugs(foe, board):
    """Say whether an enemy has shrugged off an aimed hit this fight.

    Args:
        foe: The `board.Foe`.
        board: The `Board`, whose `shrugging` says where such enemies stand.

    Returns:
        True when it stands where one did.
    """
    return any(abs(foe.x - x) <= SAME_ENEMY for x in board.shrugging)


def shrugging_after(name, target, board, after, absorbed=()):
    """Work out which enemies shrug off hits, as the Aether Eater does, from what a card the game took did to them.

    A card aimed at one enemy, planned at `SURE_HIT` to take `SHRUG_PLANNED` HP or more off it, counts only while every other enemy
    kept its HP and stayed. The enemy shrugs off hits once such a card took 1 to `SHRUG_LOSS` HP off it, or a second one took none: a
    Shield can take one hit whole, and so can a card an Epiphany turned into one with no damage while it was played. An enemy that
    then loses `SHRUG_PLANNED` or more at once, on reads the zoomed crop and the full-frame pass agree on, shrugs off nothing after
    all: one that loses a point a hit drops a few at most to a card of several hits. Nothing is learnt on an invulnerable turn, which
    the badge already covers.

    Args:
        name: The card the game took.
        target: The x of the enemy a planned kill aimed it at, None otherwise.
        board: The `Board` the card was chosen against.
        after: The reads of the frame that showed it played.
        absorbed: Where each enemy stands that took one such card whole, from the last call.

    Returns:
        Where each enemy stands that shrugs off hits, as `Board.shrugging` holds them, and the new `absorbed`.
    """
    pairs = paired(board.foes, after)
    landed = [foe.x for foe, later in pairs if foe.agreed and later.agreed and foe.health - later.health >= SHRUG_PLANNED]
    marked = [x for x in board.shrugging if not any(abs(x - other) <= SAME_ENEMY for other in landed)]
    absorbed = [x for x in absorbed if not any(abs(x - other) <= SAME_ENEMY for other in landed)]
    if not aimed(name) or board.invulnerable:
        return tuple(marked), tuple(absorbed)
    if target is None and len(board.foes) == 1 and board.enemies <= 1:
        # Alone, an enemy is where any aimed card goes.
        target = board.foes[0].x
    estimate = expected_damage(name, SURE_HIT)
    if target is None or estimate is None or estimate[0] * on_target(name) + estimate[1] < SHRUG_PLANNED:
        return tuple(marked), tuple(absorbed)
    hit = [(foe, later) for foe, later in pairs if abs(foe.x - target) <= SAME_ENEMY]
    others = [(foe, later) for foe, later in pairs if abs(foe.x - target) > SAME_ENEMY]
    # An enemy gone or hurt besides the target says the card may have landed elsewhere, as when a Taunt holds the reticle.
    if not hit or len(pairs) != len(board.foes) or any(later.health != foe.health for foe, later in others):
        return tuple(marked), tuple(absorbed)
    foe, later = hit[0]
    loss = foe.health - later.health
    if not (foe.sure and later.sure and 0 <= loss <= SHRUG_LOSS) or any(abs(foe.x - x) <= SAME_ENEMY for x in marked):
        return tuple(marked), tuple(absorbed)
    seen = [x for x in absorbed if abs(foe.x - x) <= SAME_ENEMY]
    if loss or seen:
        return (*marked, foe.x), tuple(x for x in absorbed if x not in seen)
    return tuple(marked), (*absorbed, foe.x)


def note_hit(name, before, after, shrugging=()):
    """Learn what one of a combatant's attacks did, from the enemies read before it was played and after.

    Only a plain hit on one enemy teaches anything: an attack with damage to all enemies, with a figure the text leaves as X or with
    no owner is skipped, and so is any pair of reads where an enemy read before is gone after, not exactly one enemy lost HP, any
    enemy gained some, the one that lost it shrugs off hits, or its HP was not read the same by the zoomed crop and the full-frame pass
    both times. A hit that kills leaves no HP to compare, and whatever else lost HP on that frame may have lost it to something else.

    Args:
        name: The card the game took.
        before: The `board.Foe` reads the card was chosen against.
        after: The reads of the frame that showed it played.
        shrugging: Where each enemy stands that shrugs off hits, as `Board.shrugging` holds them.

    Returns:
        The damage per 100% printed it did, now remembered for its owner, or None when it taught nothing.
    """
    doing = features(name)
    who = owner(canonical(name))
    if who is None or not doing.damage or doing.spread or UNKNOWN_FIGURE.search(on_play(name)):
        return None
    if any(not any(abs(other.x - foe.x) <= SAME_ENEMY for other in after) for foe in before):
        return None
    pairs = paired(before, after)
    dropped = [(foe, later) for foe, later in pairs if later.health < foe.health]
    if len(dropped) != 1 or any(later.health > foe.health for foe, later in pairs):
        return None
    foe, later = dropped[0]
    if not (foe.agreed and later.agreed) or any(abs(foe.x - x) <= SAME_ENEMY for x in shrugging):
        return None
    figure = (foe.health - later.health) * 100 / doing.damage
    HITS.setdefault(who, deque(maxlen=HIT_MEMORY)).append(figure)
    return figure


def per_hundred(who, share):
    """Say what a combatant's attacks do per 100% printed, at a given point of the hits seen.

    Args:
        who: The combatant.
        share: Which point of their hits, from 0 for the weakest to 1 for the strongest: `SURE_HIT` or `TYPICAL_HIT`.

    Returns:
        The damage, or None until `CALIBRATED` hits have been seen.
    """
    seen = sorted(HITS.get(who, ()))
    if len(seen) < CALIBRATED:
        return None
    # Linear between the two hits either side of the point, as the inclusive quantiles count it.
    place = share * (len(seen) - 1)
    low = int(place)
    return seen[low] + (seen[min(low + 1, len(seen) - 1)] - seen[low]) * (place - low)


def expected_damage(name, share):
    """Estimate a card's damage in HP from what its owner's hits have done, split into the part on one enemy and the part on all.

    Args:
        name: The card name, in any spelling.
        share: Which point of the owner's hits to plan on, as `per_hundred` takes it.

    Returns:
        A pair of HP figures, to the one enemy hit and to every enemy, or None when the owner has too few hits seen.
    """
    figure = per_hundred(owner(canonical(name)), share)
    if figure is None:
        return None
    doing = features(name)
    return (doing.damage - doing.spread) * figure / 100, doing.spread * figure / 100


def fight_turns(board):
    """Estimate how many turns the fight has left: the enemies' HP over what a turn's worth of the hand's attacks typically does.

    Args:
        board: The `Board`, with each enemy's HP in `foes`.

    Returns:
        The turns, or None when an enemy's HP is unknown, too few hits have been seen to put a figure on any attack, or the turn can
        do no damage.
    """
    count = max(len(board.foes), board.enemies)
    if not board.foes or count > len(board.foes) or any(foe.health is None for foe in board.foes) or board.invulnerable:
        return None
    attacks = []
    for name in board.hand:
        price, estimate = cost(name), expected_damage(name, TYPICAL_HIT)
        if estimate and price != X_COST and worth_playing(name) and features(name).damage:
            attacks.append((price, estimate[0] + estimate[1] * count))
    budget = max(board.action_points, BASE_ACTION_POINTS)
    most = max((sum(damage for _, damage in picked) for size in range(1, len(attacks) + 1) for picked in combinations(attacks, size)
                if sum(price for price, _ in picked) <= budget), default=0)
    return sum(foe.health for foe in board.foes) / most if most else None


def aimed(name):
    """Say whether a card hits one enemy the player picks, so the bot can move it onto the enemy it means to kill.

    Args:
        name: The card name, in any spelling.

    Returns:
        True for a card whose target is in `AIMED`.
    """
    return CARD_TARGET.get(base_name(canonical(name))) in AIMED


def on_target(name):
    """Say what share of a card's damage to one enemy lands on the enemy it hits, the rest going "to another enemy".

    The game picks that other enemy, so no kill is planned on that part.

    Args:
        name: The card name, in any spelling.

    Returns:
        The share, 1 for a card with no such line.
    """
    doing = features(name)
    single = doing.damage - doing.spread
    text = RETAIN_LINE.sub("", text_of(canonical(name)))
    other = sum(damage_in(line) for line in text.splitlines() if OTHER_ENEMY.search(line))
    return max(0, single - other) / single if single > 0 else 1


def kill_plan(picked, board):
    """Work out the order and the enemies that let a set of attacks kill the most enemies for sure.

    Damage to all enemies is counted first, since the set plays it first, and so is the part on one enemy of a card that also hits all.
    An aimed hit goes to the enemy the plan picks, which costs a TAB at play time unless it is the leftmost one standing, where the game
    raises the card. Any other hit on one enemy lands on a random one, so it only counts once one enemy is left. Two hits can finish one
    enemy, and a hit that kills the leftmost enemy moves the next aimed hit's start along.

    Args:
        picked: Per attack, its HP figures to one enemy and to all, as `expected_damage` gives them at `SURE_HIT`, and whether it is aimed.
        board: The `Board`, whose enemies with a sure HP read can be killed. An enemy without one, one that shrugs off hits, or one
            not read at all, still stands and still draws a random hit.

    Returns:
        The enemies killed, how many aimed hits need moving off the leftmost enemy, and per attack in `picked` that hits only one
        enemy, in the order to play them, its index and the x of the enemy it is aimed at, None when it is not aimed at one.
    """
    spread = sum(every for _, every, _ in picked)
    lefts = [foe.health - spread if foe.sure and foe.health is not None and not shrugs(foe, board) else None for foe in board.foes]
    standing = [foe for foe, left in zip(board.foes, lefts) if left is None or left > 0]
    killed = len(board.foes) - len(standing)
    lefts = [left for left in lefts if left is None or left > 0]
    # Enemies counted but not read stand somewhere unknown, so they only ever take a random hit.
    unread = max(0, board.enemies - len(board.foes))
    for one, every, _ in picked:
        alive = [index for index, left in enumerate(lefts) if left is None or left > 0]
        if every and one and alive and len(alive) + unread == 1 and lefts[alive[0]] is not None:
            lefts[alive[0]] -= one
            killed += lefts[alive[0]] <= 0
    single = [index for index, (one, every, _) in enumerate(picked) if one and not every]
    count, moved, order = kill_search(tuple(picked[index][0::2] for index in single), tuple(lefts), unread)
    # Back from what each hit does to the cards, each value to the first card left that does it, so cards that tie keep their order.
    unplaced = list(single)
    placed = []
    for hit, target in order:
        index = next(index for index in unplaced if picked[index][0::2] == hit)
        unplaced.remove(index)
        placed.append((index, None if target is None else standing[target].x))
    return killed + count, -moved, placed


def kill_search(hits, lefts, unread):
    """Find the order and the enemies for hits on one enemy that kill the most, then need the fewest moved off the leftmost enemy.

    Searched by what each hit does rather than which card does it, so two Strikes left are one state however they came about, and the
    sets `lethal` tries share their states.

    Args:
        hits: Per hit still to play, its HP figure and whether it is aimed, in the order to prefer where nothing else decides.
        lefts: Per enemy standing, left to right, the HP it has left, None when not known, 0 or less once killed.
        unread: How many more enemies stand somewhere unknown.

    Returns:
        The enemies killed, how many hits are moved as a negative, and per hit in the order to play it, the hit and the index in
        `lefts` of the enemy it is aimed at, None when it is not aimed at one.
    """
    return searched(hits, settled(hits, lefts), unread)


def settled(hits, lefts):
    """Put one figure for every HP left that makes no difference to what some hits can do, so `searched` holds those states once.

    Args:
        hits: As `kill_search` takes them.
        lefts: As `kill_search` takes them.

    Returns:
        The HP left per enemy, 0 for any enemy killed and `UNKILLABLE` for any with more than every hit together does.
    """
    reach = sum(one for one, _ in hits)
    return tuple(left if left is None or 0 < left <= reach else 0 if left <= 0 else UNKILLABLE for left in lefts)


@lru_cache(maxsize=SEARCHED_STATES)
def searched(hits, lefts, unread):
    """Search `kill_search`'s orders, with every enemy's HP left as it gives them.

    Args:
        hits: As `kill_search` takes them.
        lefts: As `kill_search` takes them, 0 once killed and `UNKILLABLE` above what every hit left could do.
        unread: As `kill_search` takes it.

    Returns:
        What `kill_search` returns.
    """
    alive = [index for index, left in enumerate(lefts) if left is None or left > 0]
    best = at_best(hits, lefts, unread)
    outcome = (0, 0, tuple((hit, None) for hit in hits))
    for place, hit in enumerate(hits):
        if best[0] == 0 or outcome[:2] == best:
            break
        if hit in hits[:place]:
            continue
        one, aims = hit
        rest = hits[:place] + hits[place + 1:]
        if aims:
            targets = [target for target in alive if lefts[target] is not None]
            # A hit on an enemy that every hit left together cannot kill does no better than the same hit on the first enemy tried,
            # which is never moved further, so only that one is kept.
            reach = one + sum(other for other, _ in rest)
            targets = targets[:1] + [target for target in targets[1:] if lefts[target] <= reach]
        else:
            targets = alive if len(alive) + unread == 1 and lefts[alive[0]] is not None else []
        for target in targets or [None]:
            after = settled(rest, lefts if target is None else lefts[:target] + (lefts[target] - one,) + lefts[target + 1:])
            kills_now = target is not None and after[target] <= 0
            # With an enemy not read, the card may be raised on it, so no aimed hit lands where it is raised for sure.
            moved_now = aims and target is not None and (unread > 0 or target != alive[0])
            # Only a result above the best so far replaces it, so a branch that cannot beat it even at its best is skipped.
            most, fewest = at_best(rest, after, unread)
            if (kills_now + most, fewest - moved_now) <= outcome[:2]:
                continue
            kills_after, moved, order = searched(rest, after, unread)
            result = (kills_now + kills_after, moved - moved_now, ((hit, target if aims else None), *order))
            if result[:2] > outcome[:2]:
                outcome = result
    return outcome


@lru_cache(maxsize=SEARCHED_STATES)
def at_best(hits, lefts, unread):
    """Bound what `kill_search` can find, so a branch that cannot beat the best so far is skipped.

    Args:
        hits: As `kill_search` takes them.
        lefts: As `kill_search` takes them.
        unread: As `kill_search` takes it.

    Returns:
        A pair no order of the hits beats: the most enemies they could kill between them, each needing at least what it has left, the
        ones with least left first; and, as a negative, the fewest hits moved off the leftmost enemy in killing that many. An enemy
        killed while one to its left still stands is never the leftmost, so every hit on it is moved.
    """
    total = sum(one for one, _ in hits)
    standing = [left for left in lefts if left is None or left > 0]
    most = bisect_right(list(accumulate(sorted(left for left in standing if left is not None))), total)
    budget, free = total, 0
    for left in standing if unread == 0 else []:
        if left is None or budget < left or free == most:
            break
        budget -= left
        free += 1
    # Each of the others killed takes as many moved hits as the fewest aimed hits that finish it. The leftmost is never one of them.
    reaches = list(accumulate(sorted((one for one, aims in hits if aims), reverse=True)))
    needs = sorted(bisect_left(reaches, left) + 1 for left in standing[1 if unread == 0 else 0:] if left is not None)
    return most, -sum(needs[:most - free])


def kills(picked, board):
    """Count the enemies a set of attacks kills for sure, as `kill_plan` aims them.

    Args:
        picked: Per attack, its HP figures to one enemy and to all and whether it is aimed, as `kill_plan` takes them.
        board: The `Board` they would be played into.

    Returns:
        The number of enemies.
    """
    return kill_plan(picked, board)[0]


def lethal(fixed, board):
    """Find the cheapest set of affordable attacks that kills the most enemies for sure, to play before anything else.

    A kill is only planned on HP the zoomed crop read as one number that the full-frame pass read the same or not at all, and on the
    low end of the damage the attacker's own hits have done, `SURE_HIT`, once `CALIBRATED` of them have been seen. Live, the bot
    buffed three cards deep into a turn whose first attack would have finished the fight.

    Args:
        fixed: The playable hand cards with a fixed price.
        board: The `Board` they would be played into.

    Returns:
        Pairs of a card and the x of the enemy it is aimed at, None for a card not aimed at one, in the order to play them: damage to
        all enemies first while several are left, then the hits on one enemy in the order `kill_plan` lands them, the turn's usual
        order where that makes no difference. Empty when no set kills anything.
    """
    if board.invulnerable or not any(foe.sure for foe in board.foes):
        return []
    attacks = [(card, expected_damage(card["name"], SURE_HIT)) for card in fixed if features(card["name"]).damage]
    attacks = [(card, (estimate[0] * on_target(card["name"]), estimate[1], aimed(card["name"]))) for card, estimate in attacks if estimate]
    best, best_key, best_order = (), (0,), []
    healths = list(accumulate(sorted(foe.health for foe in board.foes if foe.sure and foe.health is not None and not shrugs(foe, board))))
    for size in range(1, len(attacks) + 1):
        for picked in combinations(attacks, size):
            spent = sum(price(card) for card, _ in picked)
            if spent > board.action_points:
                continue
            # A set that could not beat the best so far even killing every enemy its damage could reach is not searched.
            most = bisect_right(healths, sum(one + every * len(board.foes) for _, (one, every, _) in picked))
            if not most or (most, -spent, -size, 0) <= best_key:
                continue
            picked = sorted(picked, key=lambda pair: phase(pair[0]["name"], board))
            killed, moved, order = kill_plan([estimate for _, estimate in picked], board)
            # A kill that needs no TAB is preferred to one that does, since a Taunt or an unread reticle leaves a card where it was raised.
            key = (killed, -spent, -size, -moved)
            if key[0] and key > best_key:
                best, best_key, best_order = picked, key, order
    if max(len(board.foes), board.enemies) <= 1:
        return [(card, None) for card, _ in best]
    first = [(card, None) for card, (_, every, _) in best if every]
    return first + [(best[index][0], target) for index, target in best_order]


def wasted(name, board):
    """Say whether a card would do nothing, being all damage while an enemy cannot lose Health.

    Args:
        name: The card name, in any spelling.
        board: The `Board` it would be played into.

    Returns:
        True for a card with damage and nothing else on an invulnerable turn.
    """
    doing = features(name)
    return board.invulnerable and doing.damage > 0 and not strength(doing._replace(damage=0))


def strength(doing, role=None):
    """Say what a card's figures are worth together, in damage terms.

    Args:
        doing: The card's `Features`.
        role: The owner's role from `COMBATANT_ROLE`, which weighs a Healer's or Protector's damage down and their specialty up.

    Returns:
        The damage, plus the shield, heal and draw at their exchange rates.
    """
    damage = doing.damage * (SUPPORT_DAMAGE if role in SUPPORT_ROLES else 1)
    shield = doing.shield * (SPECIALTY_WEIGHT if role == "Protection" else SHIELD_WEIGHT)
    heal = doing.heal * (SPECIALTY_WEIGHT if role == "Healing" else SHIELD_WEIGHT)
    return damage + shield + heal + DRAW_VALUE * doing.draw


def lit_up(name, board):
    """Say whether this is the card the run has lit up for an Epiphany.

    Args:
        name: The card name, in any spelling.
        board: The `Board` it would be played into.

    Returns:
        True when the glow read off the screen belongs to this card.
    """
    return board.epiphany is not None and canonical(board.epiphany) == canonical(name)


def phase(name, board):
    """Say when in a turn a card belongs.

    Args:
        name: The card name, in any spelling.
        board: The `Board` it would be played into.

    Returns:
        One of the `PHASE_` values, or a kit's place between two of them, lowest being earliest in the turn.
    """
    if canonical(name) in BREAKDOWN_CARDS:
        return PHASE_ESCAPE
    if lit_up(name, board):
        return PHASE_EPIPHANY
    return kits.phase(canonical(name), board, generic_phase(name))


def generic_phase(name):
    """Say when in a turn a card belongs by its cost and text alone.

    Args:
        name: The card name, in any spelling.

    Returns:
        One of the `PHASE_` values from `PHASE_UPGRADE` on.
    """
    price = cost(name)
    if price == X_COST:
        return PHASE_SPENDS_EVERYTHING
    kind = category(name)
    if kind == SETUP_CATEGORY:
        return PHASE_UPGRADE
    if price == 0:
        return PHASE_FREE
    if features(name).draw:
        return PHASE_SETUP
    if kind not in DEALT_TO_YOU and PRIME.search(on_play(name)):
        return PHASE_PRIME
    if kind == ATTACK_CATEGORY:
        return PHASE_ATTACK
    return PHASE_OTHER


def buying_order(card, board):
    """Build the sort key that decides which cards a turn can afford.

    Value per Action Point, rather than value alone, because the question is what to spend a limited budget
    on. A card with no fixed price sorts last however good it looks, since it takes everything that is left
    and so can only ever be the turn's final play.

    Args:
        card: The hand card, as `_hand_cards` reads it.
        board: The `Board` it would be played into.

    Returns:
        A sort key putting the best buy first.
    """
    points = price(card)
    return points == X_COST, -value(card["name"], board) / max(points, 1)


def best_buy(ranked, budget, board):
    """Pick the cards with a fixed price that are worth the most together within the turn's Action Points.

    Buying the best value per point first can strand points: a 1-point Basic attack bought ahead of a 3-point attack leaves 2 points and
    nothing to spend them on.

    Args:
        ranked: The playable hand cards with a fixed price, best buy first.
        budget: The Action Points to spend.
        board: The `Board` they would be played into.

    Returns:
        The cards to buy, best buy first. A tie goes to the set spending more points, then to the set of more cards. A card whose text
        does nothing here is never bought, while one a kit rates at nothing is still bought on points nothing else wants.
    """
    ranked = [card for card in ranked if rated(card["name"], board) > 0 or value(card["name"], board) > 0]
    worth = [value(card["name"], board) for card in ranked]
    prices = [price(card) for card in ranked]
    best, best_key = (), (0, 0, 0)
    for size in range(1, len(ranked) + 1):
        for picked in combinations(range(len(ranked)), size):
            spent = sum(prices[index] for index in picked)
            key = (sum(worth[index] for index in picked), spent, size)
            if spent <= budget and key > best_key:
                best, best_key = picked, key
    return [ranked[index] for index in best]


def plan(hand, board):
    """Choose the cards to play this turn, in the order to play them.

    Two questions, answered in order, because answering them together gets both wrong. What the budget buys is
    settled on the most value the points can buy, so a cheap card cannot crowd out a dear one that wins the fight. Only then are the survivors put into phase order, and
    cards that tie keep the order the hand had. Attacks that kill an enemy for sure are bought before both, and played before
    everything but a chance to escape and the glowing card.

    Args:
        hand: Hand cards as `_hand_cards` reads them, each a dict with at least a `name`.
        board: The `Board` this is being decided against.

    Returns:
        The hand cards to play, in order, costing no more than the Action Points available. A card that is part of a sure kill
        carries `kills`, and `target`, the x of the enemy it is aimed at or None.
    """
    if not board.hand:
        board = board._replace(hand=tuple(canonical(card["name"]) for card in hand))
    hand = [discounted(card, board) for card in hand]
    playable = (card for card in hand if worth_playing(card["name"]) and not kits.held(canonical(card["name"]), board)
                and not wasted(card["name"], board))
    budget = board.action_points
    ranked = sorted(playable, key=lambda held: buying_order(held, board))
    kill = lethal([card for card in ranked if price(card) != X_COST], board)
    ranked = [card for card in ranked if not any(card is killing for killing, _ in kill)]
    budget -= sum(price(card) for card, _ in kill)
    kill = [{**card, "kills": True, "target": target} for card, target in kill]
    fixed = [card for card in ranked if price(card) != X_COST]
    # An Upgrade pays off every turn left in the battle, so its first copy is bought first and the rest of the hand shares what is left,
    # unless the fight looks to be over before it could pay.
    turns = fight_turns(board)
    lasting = turns is None or turns >= UPGRADE_TURNS
    first = [lasting and category(card["name"]) == SETUP_CATEGORY and canonical(card["name"]) not in board.battle for card in fixed]
    upgrades = best_buy([card for card, new in zip(fixed, first) if new], budget, board)
    left = budget - sum(price(card) for card in upgrades)
    # A cheap card that hurts while held goes next, as long as a point stays for the rest of the hand.
    cleared = []
    for card in sorted((card for card in hand if hurts_held(card["name"])), key=lambda held: clearing_order(held["name"])):
        if price(card) <= CLEARING_MAX_COST and left - price(card) >= CLEARING_RESERVE:
            cleared.append(card)
            left -= price(card)
    chosen = upgrades + cleared + best_buy([card for card, new in zip(fixed, first) if not new], left, board)
    spenders = [card for card in ranked if price(card) == X_COST and rated(card["name"], board) > 0]
    if spenders and sum(price(card) for card in chosen) < budget:
        # It takes the rest of the turn's points, so it is worth playing only while some remain, and nothing can follow it.
        chosen.append(spenders[0])
    return sorted(kill + chosen, key=lambda held: PHASE_KILL if held.get("kills") else phase(held["name"], board))
