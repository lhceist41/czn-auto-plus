"""Check that the picker decides with the fight in view: a sure kill first, nothing bought that does nothing, and Upgrades, shields and
heals only when the fight needs them.

The hands are ones the bot held in logged Chaos turns. What a combatant's attacks do is learnt from the fight itself, so each test sets
the hits it plans on.
"""

import json
import sys
import tempfile
import unittest
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import battle, board, cards  # noqa: E402
from tests.TestBattlePlay import hand, upstream  # noqa: E402
from tests.TestEnemyRead import CropTask, health_box  # noqa: E402

Foe = board.Foe
# Damage per 100% printed. Selena's spread like one night's logs, so the low end a kill is planned on is 72 and the middle 78.
SELENA_HITS = [63, 72, 78, 80, 95]
MEI_LIN_HITS = [90, 100, 105, 110, 120]
CALIBRATED = {"Selena": SELENA_HITS, "Mei Lin": MEI_LIN_HITS}
# The hand of the turn the bot buffed three cards deep into while one attack would have finished the fight.
BUFFED_INTO_A_KILL = ("Source of Water", "Emergency Shielding", "High-Power Scope", "Target Spotted", "Unity of Attack and Defense")
# The hand of a turn against an enemy on 8 HP, where three buffs went before the kill.
BUFFS_AT_8_HP = ("Source of Water", "Blessing of Waves", "High-Power Scope", "Tactical Maneuver", "Target Spotted", "Unity of Attack and Defense")
JEWEL = "Flame Dragon's Jewel"
# Heal cards with a line no figure reads that does something besides the heal: a dagger, Credits at full HP, Decibel.
HEALS_WITH_MORE = ("Shadow Reload", "Financial Therapy", "Distortion: Financial Therapy", "Soul Riff")
# Heal and point cards whose other line only raises or repeats the heal, restores HP or costs points.
NOTHING_MORE = ("Blessing of Waves", "Blue Flame", "Mutation: Hand Enthralled by Light", "Fresh Raw Meat", "Odyssey Recovery Kit",
                "Unknown: Elixir of Mutation")
# A hits file as a hand edit could leave it: a null, NaN, both infinities, a negative, a zero, a string and a boolean among Selena's
# hits, and values that are no list at all.
EDITED_HITS = ('{"Selena": [72, null, NaN, Infinity, -Infinity, -5, 0, "78", true, 80, 95], "Mei Lin": "78", "Tressa": 5, "Nia": {"x": 1},'
               ' "Orlea": [null, NaN]}')


def one(health, sure=True, counter=None):
    """Build the read of a single enemy.

    Args:
        health: Its HP.
        sure: Whether both reads of the HP agreed.
        counter: Its action counter, None when not read.

    Returns:
        The enemies, as `Board.foes` holds them.
    """
    return (Foe(0.566, health, counter, None, sure, sure),)


def played(chosen):
    """Reduce a plan to the names it plays, in order.

    Args:
        chosen: The plan.

    Returns:
        The card names.
    """
    return [card["name"] for card in chosen]


@contextmanager
def hits(by_combatant):
    """Plan with a given set of hits seen, and put back the ones there were.

    Args:
        by_combatant: Combatant to damage per 100% printed.
    """
    saved = dict(cards.HITS)
    cards.HITS.clear()
    cards.HITS.update({who: deque(figures, maxlen=cards.HIT_MEMORY) for who, figures in by_combatant.items()})
    try:
        yield
    finally:
        cards.HITS.clear()
        cards.HITS.update(saved)


class TestKillFirst(unittest.TestCase):
    """An attack that kills goes before anything a fight that ends never needs."""

    def test_the_kill_goes_before_the_buffs(self):
        for name, held, health in (("75 HP", BUFFED_INTO_A_KILL, 75), ("8 HP", BUFFS_AT_8_HP, 8)):
            with self.subTest(name), hits(CALIBRATED):
                chosen = cards.plan(hand(*held), cards.Board(foes=one(health, counter=8), health=0.957, team=1.0))
                self.assertEqual("Target Spotted", chosen[0]["name"])
                self.assertTrue(chosen[0].get("kills"))

    def test_without_the_kill_the_buffs_still_go_first(self):
        # 150% at Selena's low end is 108, short of 120, so the turn is planned as before.
        with hits(CALIBRATED):
            chosen = cards.plan(hand(*BUFFED_INTO_A_KILL), cards.Board(foes=one(120, counter=8), health=0.957, team=1.0))
            self.assertNotEqual("Target Spotted", chosen[0]["name"])
            self.assertFalse(any(card.get("kills") for card in chosen))

    def test_two_attacks_that_kill_together_are_played_first_and_the_rest_of_the_points_are_spent(self):
        # Strike's 100 and Engagement Fire's 72 make 172, past 150 HP. The third point still buys something.
        with hits(CALIBRATED):
            chosen = cards.plan(hand("High-Power Scope", "Strike", "Engagement Fire"), cards.Board(foes=one(150)))
            self.assertEqual({"Strike", "Engagement Fire"}, set(played(chosen[:2])))
            self.assertTrue(all(card.get("kills") for card in chosen[:2]))
            self.assertEqual(["High-Power Scope"], played(chosen[2:]))

    def test_no_kill_is_planned_on_too_few_hits(self):
        for seen in (SELENA_HITS[:1], SELENA_HITS[:2]):
            with self.subTest(seen=len(seen)), hits({"Selena": seen}):
                chosen = cards.plan(hand(*BUFFED_INTO_A_KILL), cards.Board(foes=one(75), health=0.957, team=1.0))
                self.assertFalse(any(card.get("kills") for card in chosen))
        with hits({"Selena": SELENA_HITS[:3]}):
            self.assertTrue(cards.plan(hand(*BUFFED_INTO_A_KILL), cards.Board(foes=one(75), health=0.957, team=1.0))[0].get("kills"))

    def test_no_kill_is_planned_on_an_unsure_read(self):
        with hits(CALIBRATED):
            for foes in (one(8, sure=False), one(None, sure=False), ()):
                with self.subTest(foes=foes):
                    chosen = cards.plan(hand(*BUFFS_AT_8_HP), cards.Board(foes=foes, health=0.957, team=1.0))
                    self.assertFalse(any(card.get("kills") for card in chosen))

    def test_no_kill_is_planned_while_damage_does_nothing(self):
        with hits(CALIBRATED):
            chosen = cards.plan(hand(*BUFFS_AT_8_HP), cards.Board(foes=one(8), invulnerable=True))
            self.assertFalse(any(card.get("kills") for card in chosen))

    def test_a_hit_on_one_enemy_only_counts_where_the_game_could_aim_it(self):
        # Strike kills the enemy on 30 only if the game aims it there, so it plans no kill. Drone Bombing hits both, and does.
        two = (Foe(0.55, 30, None, None, True), Foe(0.75, 300, None, None, True))
        with hits(CALIBRATED):
            self.assertFalse(any(card.get("kills") for card in cards.plan(hand("High-Power Scope", "Strike"), cards.Board(foes=two, enemies=2))))
            chosen = cards.plan(hand("High-Power Scope", "Strike", "Drone Bombing"), cards.Board(foes=two, enemies=2))
            self.assertEqual("Drone Bombing", chosen[0]["name"])
            self.assertTrue(chosen[0].get("kills"))

    def test_an_enemy_one_reader_missed_keeps_a_hit_on_one_enemy_from_counting(self):
        # The counter count says two enemies and only one was read: Strike could go to the one not read.
        with hits(CALIBRATED):
            chosen = cards.plan(hand("High-Power Scope", "Strike"), cards.Board(foes=one(30), enemies=2))
            self.assertFalse(any(card.get("kills") for card in chosen))

    def test_once_one_enemy_is_left_every_hit_lands_on_it(self):
        # Drone Bombing's 86 to both kills the enemy on 50, and Strike's 100 finishes the 180 one: 94 left after the spread.
        two = (Foe(0.55, 50, None, None, True), Foe(0.75, 180, None, None, True))
        with hits(CALIBRATED):
            chosen = cards.plan(hand("Strike", "High-Power Scope", "Drone Bombing"), cards.Board(foes=two, enemies=2))
            self.assertEqual(["Drone Bombing", "Strike"], played(chosen[:2]))
            self.assertTrue(all(card.get("kills") for card in chosen[:2]))


class TestNothingThatDoesNothing(unittest.TestCase):
    """A card whose text does nothing here is never bought just because points are left."""

    def test_a_heal_is_played_only_with_something_to_restore(self):
        for name, team, health, expected in (("full HP, a hit coming", 1.0, 0.8, ["Strike"]),
                                             ("healthy after the hit", 0.95, 0.95, ["Strike"]),
                                             ("hurt, and hit again", 0.6, 0.5, ["Strike", "Water Barrier"]),
                                             ("nothing read", None, None, ["Strike", "Water Barrier"])):
            with self.subTest(name):
                chosen = cards.plan(hand("Water Barrier", "Strike"), cards.Board(team=team, health=health))
                self.assertEqual(expected, played(chosen))

    def test_a_card_that_gains_points_is_played_while_the_hand_has_more_to_pay_for(self):
        # Free, and its heal restores nothing at full HP. The point it gains pays for a fourth card, and buys nothing when three pay for all.
        board_now = cards.Board(team=1.0, health=1.0)
        four = hand("Strike", "Strike", "Engagement Fire", "Engagement Fire", "Source of Water")
        self.assertEqual("Source of Water", played(cards.plan(four, board_now))[0])
        for held in (("Strike", "Strike", "Engagement Fire", "Source of Water"), ("Strike", "Source of Water")):
            with self.subTest(held=held):
                self.assertNotIn("Source of Water", played(cards.plan(hand(*held), board_now)))

    def test_a_card_whose_text_does_not_read_is_still_played(self):
        # "2 Mark" names no figure the picker reads, so it is priced as an ordinary card rather than dropped.
        self.assertIn("High-Power Scope", played(cards.plan(hand("High-Power Scope", "Water Barrier"), cards.Board(team=1.0, health=1.0))))

    def test_a_heal_card_with_a_line_nothing_reads_keeps_that_line(self):
        # The heal restores nothing at full HP, but the dagger, the Credits, the Decibel and the Retain still come with the card.
        board_now = cards.Board(team=1.0, health=1.0)
        for name in HEALS_WITH_MORE:
            with self.subTest(name):
                self.assertEqual(cards.UNREAD_VALUE, cards.rated(name, board_now))
                self.assertIn(cards.canonical(name), map(cards.canonical, played(cards.plan(hand(name, "Strike"), board_now))))
        # Orlea's kit keeps these two for a hand of creatures, and plays them once it holds one.
        for held in (("Will of Light", "Strike", "Swiftie ★", "Softie ★", "Growing Creature"), ("Growth Acceleration", "Strike", "Swiftie ★")):
            with self.subTest(held[0]):
                self.assertEqual(cards.UNREAD_VALUE, cards.rated(held[0], board_now))
                self.assertIn(held[0], played(cards.plan(hand(*held), board_now)))

    def test_a_heal_or_points_card_whose_other_line_only_heals_or_moves_points_is_not_played_for_it(self):
        board_now = cards.Board(team=1.0, health=1.0)
        for name in NOTHING_MORE:
            with self.subTest(name):
                self.assertEqual(0, cards.rated(name, board_now))
                self.assertEqual(["Strike"], played(cards.plan(hand(name, "Strike"), board_now)))

    def test_a_shield_card_keeps_its_line_as_before(self):
        # Energy Barrier's "1 AP" line keeps the shield card priced with no hit coming: only heal and point cards pass such a line over.
        self.assertEqual(cards.UNREAD_VALUE, cards.rated("Energy Barrier", cards.Board(team=1.0, health=1.0, foes=one(400, counter=8))))

    def test_a_kit_rating_a_card_at_nothing_still_spends_points_nothing_else_wants(self):
        # Cassius's kit rates his filler at nothing, meaning only on spare points, which a card that does nothing never gets.
        rated = cards.rated("Strike", cards.Board())
        with mock.patch.object(cards, "value", lambda name, board_now: 0 if name == "Strike" else rated):
            self.assertEqual(["Strike"], played(cards.plan(hand("Strike"), cards.Board())))


class TestShieldByNeed(unittest.TestCase):
    """A shield is worth something only while a hit is coming."""

    def test_a_shield_waits_for_a_hit(self):
        for name, health, counter, expected in (("no hit on the bar or the counters", 1.0, 8, ["Strike"]),
                                                ("the bar shows a hit", 0.8, 8, ["Strike", "Emergency Shielding"]),
                                                ("a counter runs out this turn", 1.0, 2, ["Strike", "Emergency Shielding"]),
                                                ("the bar did not read", None, 8, ["Strike", "Emergency Shielding"]),
                                                ("no counter read", 1.0, None, ["Strike"])):
            with self.subTest(name):
                chosen = cards.plan(hand("Emergency Shielding", "Strike"), cards.Board(health=health, foes=one(400, counter=counter)))
                self.assertEqual(expected, played(chosen))

    def test_a_shield_card_with_a_line_nothing_reads_keeps_that_line(self):
        # Tactical Maneuver also deals Tenacity Damage, which no figure here reads.
        chosen = cards.plan(hand("Tactical Maneuver", "Strike"), cards.Board(health=1.0, foes=one(400, counter=8)))
        self.assertEqual({"Tactical Maneuver", "Strike"}, set(played(chosen)))


class TestUpgradeByTurnsLeft(unittest.TestCase):
    """An Upgrade's first copy goes first only while the fight lasts long enough for it to pay."""

    def test_the_two_turn_threshold(self):
        # Three Strikes a turn at Mei Lin's middle of 100 do 300, so 600 HP is two turns and 590 is not.
        with hits({"Mei Lin": [100] * 5}):
            for health, expected in ((600, [JEWEL, "Strike", "Strike"]), (590, ["Strike", "Strike", "Strike"])):
                with self.subTest(health=health):
                    chosen = cards.plan(hand("Strike", "Strike", "Strike", JEWEL), cards.Board(foes=one(health, sure=False)))
                    self.assertEqual(expected, played(chosen))

    def test_with_the_turns_left_unknown_the_upgrade_still_goes_first(self):
        for foes, seen in ((one(100), {}), (one(None, sure=False), {"Mei Lin": [100] * 5}), ((), {"Mei Lin": [100] * 5})):
            with self.subTest(foes=foes, seen=bool(seen)), hits(seen):
                self.assertEqual(JEWEL, played(cards.plan(hand("Strike", "Strike", "Strike", JEWEL), cards.Board(foes=foes)))[0])

    def test_the_jewel_is_left_with_one_weak_enemy(self):
        held = hand(JEWEL, "Strike", "Engagement Fire", "Engagement Fire")
        with hits(CALIBRATED):
            for sure in (True, False):
                with self.subTest(sure=sure):
                    chosen = cards.plan(held, cards.Board(foes=one(60, sure=sure)))
                    self.assertNotIn(JEWEL, played(chosen))
                    self.assertEqual(sure, bool(chosen[0].get("kills")))


class TestLearningHits(unittest.TestCase):
    """What a combatant's attacks do is read off the HP an enemy loses."""

    def setUp(self):
        self.saved = dict(cards.HITS)
        cards.HITS.clear()

    def tearDown(self):
        cards.HITS.clear()
        cards.HITS.update(self.saved)

    def test_a_plain_hit_on_one_enemy_is_learnt(self):
        before = (Foe(0.55, 300, 4, None, True, True), Foe(0.75, 200, 5, None, True, True))
        after = (Foe(0.551, 195, 3, None, True, True), Foe(0.75, 200, 4, None, True, True))
        self.assertEqual(105, cards.note_hit("Strike", before, after))
        self.assertEqual([105], list(cards.HITS["Mei Lin"]))

    def test_a_hit_that_cannot_be_told_apart_is_not_learnt(self):
        sure = (Foe(0.55, 300, 4, None, True, True),)
        cases = {
            "unsure before": ("Strike", (Foe(0.55, 300, 4, None, False),), (Foe(0.55, 195, 3, None, True, True),)),
            "unsure after": ("Strike", sure, (Foe(0.55, 195, 3, None, False),)),
            "the crop alone before": ("Strike", (Foe(0.55, 300, 4, None, True),), (Foe(0.55, 195, 3, None, True, True),)),
            "the crop alone after": ("Strike", sure, (Foe(0.55, 195, 3, None, True),)),
            "damage to all enemies": ("Drone Bombing", sure, (Foe(0.55, 195, 3, None, True, True),)),
            "a figure left as X": ("Rising Dragon Spire", sure, (Foe(0.55, 195, 3, None, True, True),)),
            "the enemy died": ("Strike", sure, ()),
            "two enemies lost HP": ("Strike", sure + (Foe(0.75, 200, 5, None, True, True),),
                                    (Foe(0.55, 195, 3, None, True, True), Foe(0.75, 150, 4, None, True, True))),
            "an enemy gained HP": ("Strike", sure + (Foe(0.75, 200, 5, None, True, True),),
                                   (Foe(0.55, 195, 3, None, True, True), Foe(0.75, 250, 4, None, True, True))),
            "no HP lost": ("Strike", sure, sure),
        }
        for name, (card, before, after) in cases.items():
            with self.subTest(name):
                self.assertIsNone(cards.note_hit(card, before, after))
        self.assertEqual({}, cards.HITS)

    def test_a_kill_is_planned_on_the_low_end_and_the_turns_left_on_the_middle(self):
        cards.HITS["Selena"] = deque(SELENA_HITS)
        self.assertEqual(72, cards.per_hundred("Selena", cards.SURE_HIT))
        self.assertEqual(78, cards.per_hundred("Selena", cards.TYPICAL_HIT))
        cards.HITS["Selena"] = deque(SELENA_HITS[:2])
        self.assertIsNone(cards.per_hundred("Selena", cards.SURE_HIT))

    def test_only_the_newest_hits_are_kept(self):
        for figure in range(cards.HIT_MEMORY + 5):
            cards.note_hit("Strike", (Foe(0.55, 1000, 4, None, True, True),), (Foe(0.55, 1000 - figure - 1, 3, None, True, True),))
        self.assertEqual(cards.HIT_MEMORY, len(cards.HITS["Mei Lin"]))
        self.assertEqual(6, min(cards.HITS["Mei Lin"]))


class TestHitsInBattle(unittest.TestCase):
    """The battle learns each hit from the frame that shows its card played, and keeps the hits for the next run."""

    def setUp(self):
        self.saved = dict(cards.HITS)
        cards.HITS.clear()
        self.folder = tempfile.TemporaryDirectory()
        self.file = Path(self.folder.name) / "data" / "hits.json"
        self.patches = [mock.patch.object(battle, "HITS_FILE", str(self.file)), mock.patch.object(battle, "_hits_loaded", False)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.folder.cleanup()
        cards.HITS.clear()
        cards.HITS.update(self.saved)

    def test_a_hit_is_learnt_from_the_next_frame_and_saved(self):
        reads = [one(300), one(195)]
        with upstream(hand("Strike", "Strike")) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: reads[0]):
            battle.install()
            utils_sortie._try_all_card_keys(task, 2)
            self.assertEqual("Strike", getattr(task, battle.TURN).attempted)
            reads.pop(0)
            task.hand_cards = hand("Strike")
            utils_sortie._try_all_card_keys(task, 1)
        self.assertEqual([105], list(cards.HITS["Mei Lin"]))
        self.assertEqual({"Mei Lin": [105]}, json.loads(self.file.read_text(encoding="utf-8")))
        self.assertTrue(any("hit for 105 per 100% printed" in line for line in task.logged))

    def test_the_hits_an_earlier_run_saved_are_planned_on(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(json.dumps({"Selena": SELENA_HITS}), encoding="utf-8")
        with upstream(hand(*BUFFED_INTO_A_KILL)) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: one(75)):
            battle.install()
            utils_sortie._try_all_card_keys(task, len(BUFFED_INTO_A_KILL))
        self.assertEqual(SELENA_HITS, list(cards.HITS["Selena"]))
        self.assertTrue(any(line.startswith("playing Target Spotted") and line.endswith("to kill an enemy") for line in task.logged))

    def test_a_hand_edited_file_gives_only_the_hits_a_plan_can_count_on(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(EDITED_HITS, encoding="utf-8")
        with upstream(hand(*BUFFED_INTO_A_KILL)) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: one(75)):
            battle.install()
            utils_sortie._try_all_card_keys(task, len(BUFFED_INTO_A_KILL))
        self.assertEqual({"Selena": [72, 80, 95]}, {who: list(figures) for who, figures in cards.HITS.items()})
        self.assertTrue(any(line.startswith("playing Target Spotted") and line.endswith("to kill an enemy") for line in task.logged))
        battle.save_hits()
        self.assertEqual({"Selena": [72, 80, 95]}, json.loads(self.file.read_text(encoding="utf-8")))

    def test_nan_among_the_hits_kills_nothing(self):
        # With the NaN read as a hit, every sure enemy counted as killed, and Target Spotted went first against 178 HP.
        self.file.parent.mkdir(parents=True)
        self.file.write_text('{"Selena": [NaN, 78, 80, 95]}', encoding="utf-8")
        battle.load_hits()
        self.assertEqual([78, 80, 95], list(cards.HITS["Selena"]))
        chosen = cards.plan(hand(*BUFFED_INTO_A_KILL), cards.Board(foes=one(178)))
        self.assertFalse(any(card.get("kills") for card in chosen))

    def test_a_file_that_is_no_table_of_hits_is_learnt_again(self):
        for text in ("[72, 80]", "78", "null", '"Selena"', "{not json"):
            with self.subTest(text), mock.patch.object(battle, "_hits_loaded", False):
                self.file.parent.mkdir(parents=True, exist_ok=True)
                self.file.write_text(text, encoding="utf-8")
                with mock.patch.object(battle.logger, "warning") as warned:
                    battle.load_hits()
                warned.assert_called_once()
                self.assertEqual({}, cards.HITS)

    def test_a_save_that_fails_never_leaves_the_fight(self):
        cards.HITS["Selena"] = deque([72.0])
        for error in (OSError("disk full"), TypeError("not serialisable"), ValueError("bad value")):
            with self.subTest(type(error).__name__), mock.patch.object(battle.json, "dump", side_effect=error),                     mock.patch.object(battle.logger, "warning") as warned:
                battle.save_hits()
                warned.assert_called_once()


class TestReadingSureHealth(unittest.TestCase):
    """An enemy's HP is sure only when the zoomed crop reads one number and the full-frame pass reads the same or none."""

    def test_agreement_makes_a_read_sure(self):
        # The crop wins either way, as before. A pass holding an earlier frame's HP leaves the read unsure. One reading nothing does not,
        # since it drops small numbers rather than misreading them: live, a 3 HP enemy the crop alone read held back a sure kill.
        for full, sure in (("75", True), ("175", False), (None, True)):
            with self.subTest(full=full):
                task = CropTask(["enemy_eight"], full=[health_box("enemy_eight", full)] if full else [])
                self.assertEqual([(75, sure)], [(foe.health, foe.sure) for foe in board.enemies(task)])

    def test_a_partly_covered_number_plans_no_kill(self):
        # Measured, a second counter strip covered the 8 of a "178": the crop read 17 at 0.989 and the full-frame pass 178. The crop wins
        # the HP, so only the full read disagreeing keeps it from looking like an enemy Target Spotted's 108 would kill. A cover can stay
        # put across plans, so the second plan sees the same.
        for name, crop, full, health, sure in (("covered, full read 178", "17", "178", 17, False),
                                               ("uncovered", "178", "178", 178, True)):
            with self.subTest(name):
                reads = {"enemy_eight": ([(crop, 0.989)], [("8", 1.0)])}
                foes = board.enemies(CropTask(["enemy_eight"], full=[health_box("enemy_eight", full)] if full else [], reads=reads))
                self.assertEqual([(health, sure)], [(foe.health, foe.sure) for foe in foes])
                if sure:
                    continue
                with hits(CALIBRATED):
                    for plan in range(2):
                        chosen = cards.plan(hand(*BUFFS_AT_8_HP), cards.Board(foes=foes, health=0.957, team=1.0))
                        self.assertFalse(any(card.get("kills") for card in chosen))
                    # The same 17 read for sure is a kill, so it is the read, not the damage, that holds the plan back.
                    self.assertTrue(cards.plan(hand(*BUFFS_AT_8_HP), cards.Board(foes=(foes[0]._replace(sure=True),)))[0].get("kills"))

    def test_only_hp_both_readers_agreed_on_teaches_a_hit(self):
        # 178 read by both, then a cover takes the 8 and the full-frame pass reads nothing: the crop's 17 is sure for a kill, but taken
        # for a hit it would teach a figure far too high, and the saved hits would keep it.
        def read(crop, full):
            reads = {"enemy_eight": ([(crop, 0.989)], [("8", 1.0)])}
            return board.enemies(CropTask(["enemy_eight"], full=[health_box("enemy_eight", full)] if full else [], reads=reads))

        both, crop_alone = read("178", "178"), read("17", None)
        self.assertEqual([(178, True, True)], [(foe.health, foe.sure, foe.agreed) for foe in both])
        self.assertEqual([(17, True, False)], [(foe.health, foe.sure, foe.agreed) for foe in crop_alone])
        with hits({}):
            self.assertIsNone(cards.note_hit("Strike", both, crop_alone))
            self.assertEqual({}, cards.HITS)
            self.assertIsNotNone(cards.note_hit("Strike", both, read("75", "75")))


# The hits saved at the end of a run whose sure kills came a card late.
RUN_END = {"Mei Lin": [105, 100, 112, 112], "Selena": [101, 81, 81, 81, 79.3]}
# Four enemies after Sniper's Domain, Deluge and Drone Bombing, with one Action Point left. Mika had only two hits seen then.
LOW_FOUR = (Foe(0.431, 14, 1, None, True), Foe(0.566, 12, 4, None, True), Foe(0.697, 3, 4, None, True), Foe(0.828, 4, 3, None, True))
LOW_FOUR_HAND = ("Water Arrow", "Blessing of Waves", "Flame Dragon Guardian", JEWEL)


class TestKillsFromTheBoardRead(unittest.TestCase):
    """Boards from logged turns where a sure kill came a card late, as the enemy read now gives them."""

    def test_an_elite_read_behind_its_x_is_killed_with_the_first_card(self):
        # The turn's first frame showed the elite's X, so the board held no enemy and High-Power Scope went before Drone Bombing.
        held = ("Blessing of Waves", "High-Power Scope", "Drone Bombing", "Strike", "Flame Dragon Guardian")
        state = cards.Board(action_points=3, hand=held, health=0.954, team=0.952, enemies=1)
        with hits(RUN_END):
            chosen = cards.plan(hand(*held), state._replace(foes=(Foe(0.636, 16, None, None, True),)))
            self.assertEqual("Drone Bombing", chosen[0]["name"])
            self.assertTrue(chosen[0].get("kills"))
            self.assertNotEqual("Drone Bombing", cards.plan(hand(*held), state)[0]["name"])

    def test_a_low_enemy_the_crop_alone_read_is_killed_with_the_first_card(self):
        state = cards.Board(action_points=1, hand=LOW_FOUR_HAND, played=("Sniper's Domain", "Deluge", "Drone Bombing"),
                            battle=("Sniper's Domain", "Deluge", "Drone Bombing"), health=0.924, team=0.989, enemies=4, foes=LOW_FOUR)
        with hits({**RUN_END, "Mika": [39, 55, 44]}):
            chosen = cards.plan(hand(*LOW_FOUR_HAND), state)
            self.assertEqual("Water Arrow", chosen[0]["name"])
            self.assertTrue(chosen[0].get("kills"))
            # With the 3 HP enemy unsure, Water Arrow could land on it or not: no kill is planned.
            unsure = state._replace(foes=(*LOW_FOUR[:2], LOW_FOUR[2]._replace(sure=False), LOW_FOUR[3]))
            self.assertFalse(any(card.get("kills") for card in cards.plan(hand(*LOW_FOUR_HAND), unsure)))


if __name__ == "__main__":
    unittest.main()
