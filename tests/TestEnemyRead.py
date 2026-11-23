"""Check what the picker reads about each enemy: its HP, how many cards until it acts, and which magenta is no enemy at all.

The cut-outs are real pixels from saved 1080p battle frames, pasted back where they were cut from, so the counter finder, the infinity's
shape and the weakness badge are judged on what the game draws. OCR is not run here: each crop answers with what the real engine read
on that same crop, confidence included, and the reader's threshold is applied to it the way the framework applies it.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import battle, board, cards  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402
from tests.TestBattlePlay import ATTACK, BIG_ATTACK, SHIELD, hand, upstream  # noqa: E402
from tests.TestBoard import fixture  # noqa: E402

# Each cut-out's top left corner in the frame it came from, and what OCR read on its HP crop and on its counter crop, as
# (text, confidence) pairs. The full-frame pass had read 804 for the 304, a number the enemy had shown a moment earlier.
FIXTURES = {
    "enemy_stale_full": ((1117, 207), [("304", 0.851)], [("10", 0.993)]),
    "enemy_one_digit": ((1411, 298), [("9", 0.661)], [("7", 1.0)]),
    "enemy_two_digits": ((1394, 321), [("24", 0.998)], [("5", 0.998)]),
    "enemy_leading_one": ((1400, 319), [("111", 0.668)], [("4", 0.999)]),
    "enemy_infinity": ((1586, 362), [("3", 0.997)], [("8", 0.842)]),
    "enemy_eight": ((1039, 373), [("75", 0.999)], [("8", 1.0)]),
    # Card art thrown over the enemies, whose magenta passes every test the counter finder makes. OCR read nothing on it.
    "enemy_card_art": ((570, 433), [], []),
}
# Where the counter's centre sits inside each cut-out, in pixels from its left edge. The HP crop starts well right of it.
COUNTER_INSIDE = 48
# The framework's own threshold when a caller passes none.
DEFAULT_THRESHOLD = 0.2


class CropTask:
    """A battle frame built from cut-outs, whose OCR answers each crop with what the real engine read there."""

    def __init__(self, names, full=(), reads=None):
        """Paste the cut-outs back and note what each of their crops reads.

        Args:
            names: The cut-outs to paste, by file name.
            full: `(text, x, y)` boxes the full-frame pass read, at fractions of the screen.
            reads: Cut-out name to `(hp reads, counter reads)`, standing in for the measured ones.
        """
        self.frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        self.height, self.width = HEIGHT, WIDTH
        self.placed = []
        for name in names:
            (left, top), hp, counter = FIXTURES[name]
            hp, counter = (reads or {}).get(name, (hp, counter))
            patch = fixture(name)
            self.frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
            self.placed.append((left, top, left + patch.shape[1], top + patch.shape[0], hp, counter))
        self.all_texts = [FakeBox(text, x, y) for text, x, y in full]
        self.processed = []

    def ocr(self, left, top, right, bottom, frame=None, threshold=0, frame_processor=None):
        """Answer a crop the way the framework would, from the reads the real engine gave on it.

        Returns:
            A box for each read at least as sure as the threshold.
        """
        x1, y1, x2, y2 = round(left * WIDTH), round(top * HEIGHT), round(right * WIDTH), round(bottom * HEIGHT)
        if frame_processor is not None:
            self.processed.append(frame_processor(frame[y1:y2, x1:x2]).shape)
        middle_x, middle_y = (x1 + x2) / 2, (y1 + y2) / 2
        for place_left, place_top, place_right, place_bottom, hp, counter in self.placed:
            if place_left <= middle_x <= place_right and place_top <= middle_y <= place_bottom:
                reads = counter if middle_x - place_left < 2 * COUNTER_INSIDE else hp
                return [FakeBox(text, middle_x / WIDTH, middle_y / HEIGHT) for text, sure in reads if sure >= (threshold or DEFAULT_THRESHOLD)]
        return []


def health_box(name, text):
    """Place a full-frame HP reading where the pass puts one for a cut-out's enemy.

    Args:
        name: The cut-out.
        text: What the pass read.

    Returns:
        A `(text, x, y)` box in fractions of the screen.
    """
    (left, top), _, _ = FIXTURES[name]
    return text, (left + 200) / WIDTH, (top + 38) / HEIGHT


def read(name, **kwargs):
    """Read the enemies off a frame holding one cut-out.

    Returns:
        `(health, counter)` for each enemy read.
    """
    return [(foe.health, foe.counter) for foe in board.enemies(CropTask([name], **kwargs))]


class TestEnemyRead(unittest.TestCase):
    """Each enemy's HP and counter, as the game draws them."""

    def test_each_enemy_reads_its_hp_and_counter(self):
        for name, full, expected in (
                ("enemy_stale_full", "804", (304, 10)),
                ("enemy_one_digit", None, (9, 7)),
                ("enemy_two_digits", "24", (24, 5)),
                ("enemy_leading_one", "11", (111, 4)),
                ("enemy_eight", "75", (75, 8)),
        ):
            with self.subTest(name):
                boxes = [health_box(name, full)] if full else []
                self.assertEqual([expected], read(name, full=boxes))

    def test_the_crops_are_enlarged_before_they_are_read(self):
        task = CropTask(["enemy_two_digits"])
        board.enemies(task)
        hp, counter = task.processed
        self.assertGreater(hp[0], board.HEALTH_ZOOM * (board.HEALTH_NUMBER[3] - board.HEALTH_NUMBER[1]) * HEIGHT)
        self.assertGreater(counter[0], board.COUNTER_ZOOM * 2 * board.COUNTER_DIGIT_HALF[1] * HEIGHT)

    def test_an_infinity_is_never_read_as_an_eight(self):
        self.assertEqual([(3, None)], read("enemy_infinity"))
        # Even read sure of itself, the infinity's shape gives it away, and a real 8 keeps its count.
        for name, expected in (("enemy_infinity", None), ("enemy_eight", 8)):
            with self.subTest(name):
                sure = {name: ([("50", 0.99)], [("8", 0.99)])}
                self.assertEqual([(50, expected)], read(name, reads=sure))

    def test_an_unsure_counter_is_left_unread(self):
        # Measured, a 7 read as a 1 at 0.81.
        unsure = {"enemy_one_digit": ([("9", 0.99)], [("1", 0.81)])}
        self.assertEqual([(9, None)], read("enemy_one_digit", reads=unsure))

    def test_card_art_in_counter_magenta_is_not_an_enemy(self):
        task = CropTask(["enemy_card_art", "enemy_eight", "enemy_infinity"])
        self.assertEqual(3, len(board.enemy_counters(task.frame, board.TARGET_BAND)))
        foes = board.enemies(task)
        self.assertEqual([(75, 8), (3, None)], [(foe.health, foe.counter) for foe in foes])
        self.assertEqual(sorted(foe.x for foe in foes), [foe.x for foe in foes])

    def test_the_full_frame_number_stands_in_only_for_a_long_one(self):
        # With the crop reading nothing, three digits are taken and two are not: the pass drops leading 1s.
        blank = {"enemy_two_digits": ([], [("5", 0.998)])}
        for full, expected in (("412", 412), ("97", None)):
            with self.subTest(full):
                self.assertEqual([(expected, 5)], read("enemy_two_digits", full=[health_box("enemy_two_digits", full)], reads=blank))

    def test_two_different_crop_readings_are_settled_by_the_full_frame_one(self):
        both = {"enemy_two_digits": ([("24", 0.9), ("4", 0.9)], [("5", 0.998)])}
        self.assertEqual([(24, 5)], read("enemy_two_digits", full=[health_box("enemy_two_digits", "24")], reads=both))
        self.assertEqual([(None, 5)], read("enemy_two_digits", reads=both))

    def test_no_frame_reads_no_enemies(self):
        task = CropTask([])
        task.frame = None
        self.assertEqual((), board.enemies(task))


class TestEnemiesReachThePlan(unittest.TestCase):
    """The enemies ride along on the board the plan is made against. With no hits seen and the team bar unread or showing a hit, they change nothing."""

    FOES = (board.Foe(0.55, 75, 8, None), board.Foe(0.83, 3, None, "Justice"))

    def test_the_enemies_reach_the_plan_unchanged_and_are_logged(self):
        with upstream(hand(ATTACK, BIG_ATTACK)) as (utils_sortie, task), \
                mock.patch.object(board, "enemies", lambda task: self.FOES), \
                mock.patch.object(cards, "plan", wraps=cards.plan) as plan:
            battle.install()
            utils_sortie._try_all_card_keys(task, len(task.hand_cards))
            self.assertIs(self.FOES, plan.call_args.args[1].foes)
            self.assertEqual(task.keys, ["2", battle.CONFIRM_KEY])
            line = next(message for message in task.logged if message.startswith("board "))
            logged = json.loads(line[len("board "):])
            self.assertEqual([foe._asdict() for foe in self.FOES], logged["foes"])
            self.assertEqual([ATTACK, BIG_ATTACK], logged["hand"])

    def test_with_no_hits_seen_the_plan_picks_the_same_with_or_without_the_enemies(self):
        for held, state in (((ATTACK, BIG_ATTACK), cards.Board()), ((ATTACK, BIG_ATTACK), cards.Board(action_points=1)),
                            ((SHIELD, ATTACK), cards.Board(health=0.3)), ((ATTACK, SHIELD), cards.Board(enemies=2))):
            with self.subTest(held=held, state=state), mock.patch.dict(cards.HITS, clear=True):
                cards_in_hand = hand(*held)
                self.assertEqual(cards.plan(cards_in_hand, state), cards.plan(cards_in_hand, state._replace(foes=self.FOES)))

    def test_a_board_with_no_enemies_read_has_none(self):
        self.assertEqual((), cards.Board().foes)


if __name__ == "__main__":
    unittest.main()
