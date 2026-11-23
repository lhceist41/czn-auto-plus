"""Check the fight record: every plan, play and fight end written as the picker saw it, nothing it does changed by a record that fails,
and the replay rebuilding every recorded plan exactly.

The fights here run through the real picker and its hooks, against the same stand-in upstream `TestBattlePlay` uses. The fixture file
holds fights played the same way from hands, HP and counters the bot logged in Chaos.
"""

import json
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import replay_fights  # noqa: E402

from src.en import battle, board, cards, fight_log  # noqa: E402
from tests.TestBattlePlay import ATTACK, BIG_ATTACK, SHIELD, Pressed, hand, upstream  # noqa: E402
import utils as real_utils  # noqa: E402
from tests.fakes import FakeBox  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fights" / "recorded.jsonl"
Foe = board.Foe
# The card reward's title, which only comes up after a won fight.
REWARD = "卡牌奖励"
# A share of each attack's printed damage the stand-in enemies lose, so plays leave HP to read and a kill can come up.
DAMAGE_TAKEN = 0.6
# A Finale, which ends the turn on play with no end-turn key.
FINALE = "Reloading"
# Most frames one turn is given before the harness gives up on the picker ending it.
TURN_FRAMES = 15
TWO_TURNS = [
    {"hand": [ATTACK, SHIELD, BIG_ATTACK], "points": 3, "team": (406, 406)},
    {"hand": [ATTACK, ATTACK, SHIELD], "points": 3, "team": (350, 406)},
]


def two_foes():
    return [Foe(0.55, 300, 3, None, True, True), Foe(0.70, 200, 5, None, True, True)]


class Waiting(Pressed):
    """A stand-in task that notes its waits among its keys, so two fights can be compared wait for wait."""

    def sleep(self, seconds):
        self.keys.append(("sleep", seconds))


class ChaosMode(Waiting):
    """A stand-in task named like the real mode, the only kind of task the record writes for."""


def next_run(task):
    """Start the task's next run the way upstream does on the result page: one more run counted, floor and node back to 0, and the
    task's start time left as it is."""
    task.node_status.update(total_rounds=task.node_status["total_rounds"] + 1, pass_final_boss_count=0, node_count=0)


def enter_again(task, counted):
    """Enter the task's next run the way upstream does: a new status with floor and node at 0, counting the run only when its result
    page was read, and the task's start time left as it is."""
    task.node_status = {"pass_final_boss_count": 0, "node_count": 0, "total_rounds": task.node_status["total_rounds"] + counted}


def team_box(team):
    hp, most = team
    return FakeBox(f"{hp}/{most}", 0.30, 0.04)


def show(task, names, points, team):
    """Put one battle frame up: the hand, the Action Point digit and the team readout, in a fresh OCR pass."""
    task.hand_cards = hand(*names)
    task.points = [FakeBox(str(points), 0.508, 0.923)]
    task.all_texts = [] if team is None else [team_box(team)]


def play_fight(utils_sortie, task, turns, foes, end_texts=(REWARD,)):
    """Play a fight through the picker frame by frame, the way the game answers it, then leave the battle screen.

    Each card the picker presses leaves the hand on the next frame, its cost comes off the points, and an attack takes HP off the
    leftmost enemy. A turn ends when the picker presses end turn, or upstream's own end turn once the hand is empty.

    Args:
        utils_sortie: The stand-in Sortie module the picker is installed on.
        task: The stand-in task.
        turns: Each turn's hand, points and team readout.
        foes: The enemies, as a list the plays take HP off.
        end_texts: What the screen after the fight reads, or None to stay on the battle screen.
    """
    page = next(handler for handler in utils_sortie.PAGE_HANDLERS if handler.__name__ == "handle_battle_page")
    with mock.patch.object(board, "enemies", lambda task: tuple(foes)):
        for number, opening in enumerate(turns):
            names, points, team = list(opening["hand"]), opening["points"], opening.get("team")
            if number:
                # The counter reads 0 between the discard and the deal, which is what lets a deal no bigger than the last hand open a turn.
                getattr(task, battle.TURN).hand_count = 0
            for _ in range(TURN_FRAMES):
                show(task, names, points, team)
                pressed = len(task.keys)
                utils_sortie._try_all_card_keys(task, len(names))
                turn = getattr(task, battle.TURN)
                if battle.END_TURN_KEY in task.keys[pressed:]:
                    break
                if turn.attempted is None:
                    continue
                names.remove(turn.attempted)
                points -= max(cards.price({"name": turn.attempted}), 0)
                damage = cards.features(turn.attempted).damage
                if damage and foes and foes[0].health is not None:
                    foes[0] = foes[0]._replace(health=foes[0].health - round(damage * DAMAGE_TAKEN))
                    if foes[0].health <= 0:
                        foes.pop(0)
                if not names:
                    show(task, names, points, team)
                    utils_sortie._try_all_card_keys(task, 0)
                    battle.end_of_turn(task)
                    break
        if end_texts is not None:
            task.hand_cards, task.off_screen = [], True
            task.all_texts = [FakeBox(text, 0.5, 0.07) for text in end_texts] or [FakeBox("...", 0.5, 0.5)]
            page(task)
            task.off_screen = False


class Recording(unittest.TestCase):
    """Runs each test with the record, the hits file and the learnt tables kept apart from the real ones."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.file = root / "data" / "fights.jsonl"
        self.older = root / "data" / "fights.1.jsonl"
        self.saved = dict(cards.HITS), dict(cards.DECK)
        cards.HITS.clear()
        cards.DECK.clear()
        self.patches = [mock.patch.object(fight_log, "FIGHTS_FILE", str(self.file)), mock.patch.object(fight_log, "OLDER_FILE", str(self.older)),
                        mock.patch.object(battle, "HITS_FILE", str(root / "data" / "hits.json")), mock.patch.object(battle, "_hits_loaded", True),
                        mock.patch.object(fight_log, "_warned", False)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.folder.cleanup()
        cards.HITS.clear()
        cards.HITS.update(self.saved[0])
        cards.DECK.clear()
        cards.DECK.update(self.saved[1])

    def fight(self, turns=TWO_TURNS, foes=None, task_class=ChaosMode, node=1, run="run", end_texts=(REWARD,), utils_task=None):
        """Play one fight and hand back the task, or play it on a task and module already standing."""
        foes = two_foes() if foes is None else foes
        if utils_task is not None:
            utils_sortie, task = utils_task
            task.node_status["node_count"] = node
            task.start_time = run
            play_fight(utils_sortie, task, turns, foes, end_texts)
            return task
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, task_class, node, run)
            play_fight(utils_sortie, task, turns, foes, end_texts)
        return task

    @staticmethod
    def stand_up(utils_sortie, task, task_class, node=1, run="run"):
        task.__class__ = task_class
        task.off_screen = False
        task.node_status = {"pass_final_boss_count": 0, "node_count": node, "total_rounds": 0}
        task.start_time = run
        counted = utils_sortie._read_hand_count
        utils_sortie._read_hand_count = lambda task: None if task.off_screen else counted(task)
        battle.install()

    def lines(self, path=None):
        path = path or self.file
        return [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def ends(self):
        return [(line["outcome"], line["why"]) for line in self.lines() if line["kind"] == "end"]


class TestRecorder(Recording):
    """What a fight leaves in the file."""

    def test_a_fight_writes_its_plans_plays_and_end(self):
        task = self.fight()
        lines = self.lines()
        kinds = [line["kind"] for line in lines]
        self.assertEqual("plan", kinds[0])
        self.assertEqual("end", kinds[-1])
        self.assertEqual(1, kinds.count("end"))
        self.assertEqual({lines[0]["fight"]}, {line["fight"] for line in lines})
        first = lines[0]
        self.assertEqual(("ChaosMode", 1, 3, True), (first["mode"], first["turn"], first["ap"], first["ap_read"]))
        self.assertEqual([{"name": ATTACK, "key": "1", "cost": 1, "shown": False}, {"name": SHIELD, "key": "2", "cost": 1, "shown": False},
                          {"name": BIG_ATTACK, "key": "3", "cost": cards.cost(BIG_ATTACK), "shown": False}], first["hand"])
        self.assertEqual([{"x": 0.55, "hp": 300, "hp_source": "both", "counter": 3, "weakness": None},
                          {"x": 0.70, "hp": 200, "hp_source": "both", "counter": 5, "weakness": None}], first["foes"])
        self.assertEqual((406, 406, 1.0, 0), (first["team_hp"], first["team_max"], first["team_share"], first["shield"]))
        self.assertEqual(first["chosen"]["name"], first["plans"][0]["plan"][0])
        self.assertIn(f"worth {first['chosen']['worth']:.0f}", next(line for line in task.logged if line.startswith("playing ")))
        plays = [line for line in lines if line["kind"] == "play"]
        self.assertTrue(plays)
        self.assertEqual({"played"}, {line["result"] for line in plays})
        hit = next(line for line in plays if cards.features(line["card"]).damage)
        self.assertLess(hit["foes"][0]["hp"], 300)
        self.assertEqual(2, max(line["turn"] for line in lines if line["kind"] == "plan"))
        end = lines[-1]
        self.assertEqual(("won", "reward title", 2), (end["outcome"], end["why"], end["turns"]))
        self.assertEqual(len(plays), end["cards_played"])
        self.assertEqual(56, end["team_hp_lost"])
        self.assertEqual(kinds.count("plan"), end["plans"])
        self.assertTrue(all(line["hand"] for line in lines if line["kind"] == "plan"))

    def test_a_card_the_game_refuses_is_written_as_refused(self):
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            task.toasts = [[FakeBox(battle.NO_POINTS + ".", 0.5, 0.5)]]
            play_fight(utils_sortie, task, TWO_TURNS[:1], two_foes())
        refused = [line for line in self.lines() if line["kind"] == "play" and line["result"] == "refused"]
        self.assertEqual(1, len(refused))
        self.assertEqual(("toast", None), (refused[0]["seen"], refused[0]["foes"]))

    def test_a_stand_in_task_writes_nothing(self):
        self.fight(task_class=Pressed)
        self.assertFalse(self.file.exists())

    def test_a_field_the_screen_did_not_give_is_null(self):
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            play_fight(utils_sortie, task, [{"hand": [ATTACK, SHIELD], "points": 3, "team": None}], [Foe(0.55, None, None, None, False)])
        first = self.lines()[0]
        self.assertEqual((None, None, None, None), (first["team_hp"], first["team_max"], first["team_share"], first["shield"]))
        self.assertEqual({"x": 0.55, "hp": None, "hp_source": None, "counter": None, "weakness": None}, first["foes"][0])

    def test_a_number_json_cannot_hold_is_written_as_null(self):
        self.assertEqual({"a": [None, 1.5, None], "b": None}, fight_log.finite({"a": [float("nan"), 1.5, float("inf")], "b": float("-inf")}))
        with upstream(hand()) as (utils_sortie, task), mock.patch.object(battle, "team_share", lambda task: float("nan")):
            self.stand_up(utils_sortie, task, ChaosMode)
            play_fight(utils_sortie, task, TWO_TURNS[:1], two_foes())
        text = self.file.read_text(encoding="utf-8")
        self.assertNotIn("NaN", text)
        self.assertIsNone(json.loads(text.splitlines()[0])["team_share"])

    def test_a_later_node_of_the_same_run_says_the_last_fight_was_won(self):
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
            self.fight(utils_task=(utils_sortie, task), node=2, end_texts=None)
            # Past a floor boss upstream counts the floor and puts the node back to 0, still in the same run.
            task.node_status["pass_final_boss_count"] = 1
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
        self.assertEqual([("won", "next fight of the same run")] * 2, self.ends())
        self.assertEqual(3, len({line["fight"] for line in self.lines()}))

    def test_a_fight_the_next_run_follows_is_never_won(self):
        # A lost fight that showed no title: the run ends, and the task's next run keeps its start time.
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task), node=3, end_texts=None)
            next_run(task)
            self.fight(utils_task=(utils_sortie, task), node=3, end_texts=None)
            # A run whose result page went unread starts over without the count rising.
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
        self.assertEqual([("unknown", "no title seen")] * 2, self.ends())
        self.assertEqual(3, len({line["fight"] for line in self.lines()}))

    def test_the_next_run_on_the_same_node_is_a_fight_of_its_own(self):
        # A lost fight on the first node that showed no title, then the next run's first fight on that same node.
        for counted in (0, 1):
            with self.subTest(counted=counted), upstream(hand()) as (utils_sortie, task):
                self.file.unlink(missing_ok=True)
                self.stand_up(utils_sortie, task, ChaosMode)
                self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
                enter_again(task, counted)
                self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
                self.assertEqual([("unknown", "no title seen")], self.ends())
                self.assertEqual(2, len({line["fight"] for line in self.lines()}))

    def test_a_later_node_after_enter_is_never_won(self):
        # A lost fight that showed no title and a result page that went unread, then upstream's Enter starts the next run without the
        # count rising, and its first fight sits one node further on.
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
            real_utils.reset_mission_status(task)
            self.fight(utils_task=(utils_sortie, task), node=2, end_texts=None)
        self.assertEqual([("unknown", "no title seen")], self.ends())

    def test_the_first_fight_past_a_floor_boss_says_the_boss_was_won(self):
        # Upstream's settlement after a floor boss counts the floor and builds a new status for it, in the same run.
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task), node=3, end_texts=None)
            task.node_status["pass_final_boss_count"] += 1
            real_utils.reset_layer_status(task)
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
        self.assertEqual([("won", "next fight of the same run")], self.ends())

    def test_a_fight_the_bot_was_started_in_is_never_won(self):
        # Started mid-fight, so upstream's status puts the node at 0. The fight is lost, its result page goes unread and the next run
        # is entered without the count rising.
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode, node=0)
            self.fight(utils_task=(utils_sortie, task), node=0, end_texts=None)
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
        self.assertEqual([("unknown", "no title seen")], self.ends())

    def test_a_later_node_in_the_next_run_is_never_won(self):
        # A lost fight on the first node, the result page read, and the next run's first fight one node further on.
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task), node=1, end_texts=None)
            next_run(task)
            self.fight(utils_task=(utils_sortie, task), node=2, end_texts=None)
        self.assertEqual([("unknown", "no title seen")], self.ends())

    def test_a_reward_title_over_several_frames_ends_the_fight_once(self):
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task))
            page = next(handler for handler in utils_sortie.PAGE_HANDLERS if handler.__name__ == "handle_battle_page")
            task.hand_cards, task.off_screen = [], True
            for _ in range(3):
                page(task)
        self.assertEqual([("won", "reward title")], self.ends())

    def test_a_defeat_title_ends_the_fight_lost(self):
        self.fight(end_texts=("战斗失败",))
        self.assertEqual(("lost", "defeat title"), (self.lines()[-1]["outcome"], self.lines()[-1]["why"]))

    def test_a_short_spell_off_the_battle_screen_does_not_end_the_fight(self):
        with upstream(hand()) as (utils_sortie, task):
            self.stand_up(utils_sortie, task, ChaosMode)
            self.fight(utils_task=(utils_sortie, task), turns=TWO_TURNS[:1], end_texts=("a hand prompt",))
            self.fight(utils_task=(utils_sortie, task), turns=TWO_TURNS[1:], end_texts=None)
            self.assertEqual(1, len({line["fight"] for line in self.lines()}))
            self.assertNotIn("end", [line["kind"] for line in self.lines()])
            record = getattr(task, fight_log.RECORD)
            self.assertIsNone(record.left_at)
            record.left_at = 0.0
            self.fight(utils_task=(utils_sortie, task), turns=TWO_TURNS[:1], end_texts=None)
        lines = self.lines()
        first = lines[0]["fight"]
        self.assertEqual(2, len({line["fight"] for line in lines}))
        self.assertEqual([(first, "unknown")], [(line["fight"], line["outcome"]) for line in lines if line["kind"] == "end"])

    def test_a_full_file_is_moved_aside_before_the_next_fight(self):
        with mock.patch.object(fight_log, "MAX_BYTES", 1):
            self.fight()
            first = {line["fight"] for line in self.lines()}
            self.fight()
        self.assertEqual(first, {line["fight"] for line in self.lines(self.older)})
        self.assertNotEqual(first, {line["fight"] for line in self.lines()})
        self.assertEqual(1, len({line["fight"] for line in self.lines()}))

    def test_hits_and_deck_ride_only_on_the_lines_where_they_change(self):
        cards.HITS["Selena"] = deque([72.0, 80.0, 95.0], maxlen=cards.HIT_MEMORY)
        self.fight()
        plans = [line for line in self.lines() if line["kind"] == "plan"]
        self.assertEqual({"Selena": [72.0, 80.0, 95.0]}, {who: figures for who, figures in plans[0]["hits"].items() if who == "Selena"})
        self.assertEqual({}, plans[0]["deck"])
        self.assertNotIn("deck", plans[1])
        for line in plans[1:]:
            self.assertNotIn("Selena", line.get("hits", {}))


class TestPlayResults(Recording):
    """Each way the picker learns what became of a card it pressed leaves a play line."""

    def pressed(self, names, utils_sortie, task):
        """Show a hand and let the picker press a card, handing back the card it pressed."""
        show(task, names, 3, (406, 406))
        utils_sortie._try_all_card_keys(task, len(names))
        return getattr(task, battle.TURN).attempted

    def plays(self):
        return [line for line in self.lines() if line["kind"] == "play"]

    def test_a_card_left_in_hand_is_refused(self):
        names = [ATTACK, SHIELD]
        with upstream(hand()) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: tuple(two_foes())):
            self.stand_up(utils_sortie, task, ChaosMode)
            stuck = self.pressed(names, utils_sortie, task)
            for _ in range(battle.REFUSALS):
                self.pressed(names, utils_sortie, task)
        self.assertEqual([(stuck, "refused", "hand", 300)], [(line["card"], line["result"], line["seen"], line["foes"][0]["hp"]) for line in self.plays()])

    def test_a_card_back_on_its_retrieve_is_played(self):
        names = [ATTACK, SHIELD]
        with upstream(hand()) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: tuple(two_foes())):
            self.stand_up(utils_sortie, task, ChaosMode)
            back = self.pressed(names, utils_sortie, task)
            with mock.patch.dict(cards.RETRIEVES, {back: 1}):
                self.pressed(names, utils_sortie, task)
        self.assertEqual([(back, "played", "retrieve")], [(line["card"], line["result"], line["seen"]) for line in self.plays()])

    def test_a_card_pressed_as_the_turn_ends_is_played(self):
        with upstream(hand()) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: tuple(two_foes())):
            self.stand_up(utils_sortie, task, ChaosMode)
            last = self.pressed([ATTACK, SHIELD], utils_sortie, task)
            battle.end_of_turn(task)
        self.assertEqual([(last, "played", "end turn", None)], [(line["card"], line["result"], line["seen"], line["foes"]) for line in self.plays()])

    def test_a_finale_is_played_by_the_next_deal(self):
        with upstream(hand()) as (utils_sortie, task), mock.patch.object(board, "enemies", lambda task: tuple(two_foes())):
            self.stand_up(utils_sortie, task, ChaosMode)
            finale = self.pressed([FINALE], utils_sortie, task)
            self.assertEqual(FINALE, finale)
            self.pressed([ATTACK, ATTACK, SHIELD], utils_sortie, task)
        self.assertEqual((FINALE, "played", "deal"), tuple(self.plays()[0][key] for key in ("card", "result", "seen")))
        self.assertEqual([1, 2], [line["turn"] for line in self.lines() if line["kind"] == "plan"])


class TestNothingChanges(Recording):
    """A record that cannot be written, or a recorder that breaks, leaves every key, tap and wait exactly as it was."""

    def played(self, task_class=ChaosMode):
        task = self.fight(task_class=task_class)
        return task.keys, task.logged, task.taps, {who: list(figures) for who, figures in cards.HITS.items()}

    def test_a_write_that_always_fails_changes_nothing(self):
        recorded = self.played()
        self.assertTrue(self.file.exists())
        cards.HITS.clear()

        def refuse(*args, **kwargs):
            raise PermissionError("denied")

        with mock.patch.object(fight_log, "open", refuse, create=True), mock.patch.object(fight_log.logger, "warning") as warning:
            failing = self.played()
        self.assertEqual(recorded, failing)
        self.assertEqual(1, warning.call_count)
        self.assertIn("could not write the fight record", warning.call_args.args[0])
        cards.HITS.clear()
        self.assertEqual(recorded, self.played(Waiting))

    def test_a_recorder_that_breaks_changes_nothing(self):
        recorded = self.played()
        for name in ("foe_line", "team_read", "end"):
            cards.HITS.clear()

            def broken(*args, **kwargs):
                raise RuntimeError("broken")

            with self.subTest(name), mock.patch.object(fight_log, name, broken), mock.patch.object(fight_log.logger, "warning") as warning:
                self.assertEqual(recorded, self.played())
                self.assertEqual(1, warning.call_count)

    def test_each_fight_logs_its_first_failure(self):
        def refuse(*args, **kwargs):
            raise OSError("disk full")

        with mock.patch.object(fight_log, "open", refuse, create=True), mock.patch.object(fight_log.logger, "warning") as warning:
            with upstream(hand()) as (utils_sortie, task):
                self.stand_up(utils_sortie, task, ChaosMode)
                self.fight(utils_task=(utils_sortie, task))
                self.fight(utils_task=(utils_sortie, task), node=2)
        self.assertEqual(2, warning.call_count)


class TestHealthSource(unittest.TestCase):
    """Each enemy's HP is written down with the readers that gave it, and the replay reads it back the same."""

    def test_the_record_tells_a_lone_crop_read_from_two_readers_agreeing(self):
        for foe, source in ((Foe(0.55, 178, 3, None, True, True), "both"), (Foe(0.55, 17, 3, None, True), "crop"),
                            (Foe(0.55, 304, 3, None, False), "one"), (Foe(0.55, None, None, None, False), None)):
            with self.subTest(source=source):
                line = fight_log.foe_line(foe)
                self.assertEqual(source, line["hp_source"])
                self.assertEqual((foe,), replay_fights.foes_of([line]))


class TestReplay(Recording):
    """The replay rebuilds each recorded board and gets the recorded plan back."""

    def test_the_fixture_replays_exactly(self):
        records, skipped = replay_fights.read_lines([FIXTURE])
        report = replay_fights.replay(records)
        self.assertEqual(0, skipped)
        self.assertEqual(0, report["broken"])
        self.assertEqual([], report["differ"])
        self.assertEqual(sum(line["kind"] == "plan" for line in records), report["plans"])
        self.assertGreaterEqual(report["plans"], 30)
        self.assertEqual(report["calls"], report["same"])
        self.assertGreater(report["recorded"]["kill available"], 0)
        self.assertEqual(sum(line["kind"] == "end" for line in records), report["fights_ended"])

    def test_a_fight_just_recorded_replays_exactly(self):
        cards.HITS["Selena"] = deque([72.0, 80.0, 95.0], maxlen=cards.HIT_MEMORY)
        cards.HITS["Mei Lin"] = deque([90.0, 100.0, 105.0], maxlen=cards.HIT_MEMORY)
        self.fight()
        cards.HITS.clear()
        report = replay_fights.replay(replay_fights.read_lines([self.file])[0])
        self.assertEqual([], report["differ"])
        self.assertEqual(report["plans"], report["calls"])

    def test_a_changed_plan_is_reported(self):
        records, _ = replay_fights.read_lines([FIXTURE])
        line = next(line for line in records if line["kind"] == "plan" and len(line["plans"][0]["plan"]) > 1)
        line["plans"][0]["plan"].reverse()
        report = replay_fights.replay(records)
        self.assertEqual(1, len(report["differ"]))
        self.assertEqual(line["fight"], report["differ"][0]["fight"])

    def test_a_changed_kill_is_reported(self):
        records, _ = replay_fights.read_lines([FIXTURE])
        line = next(line for line in records if line["kind"] == "plan" and line["plans"][0]["kills"])
        line["plans"][0]["kills"] = []
        report = replay_fights.replay(records)
        self.assertEqual(1, len(report["differ"]))
        self.assertEqual([], report["differ"][0]["recorded_kills"])

    def test_a_replay_without_the_recorded_hits_differs(self):
        # The hits are what a kill is planned on, so a replay that dropped them could not have reproduced the kills.
        records, _ = replay_fights.read_lines([FIXTURE])
        for line in records:
            line.pop("hits", None)
        self.assertTrue(replay_fights.replay(records)["differ"])

    def test_unreadable_lines_are_skipped_and_counted(self):
        text = FIXTURE.read_text(encoding="utf-8")
        broken = self.file
        broken.parent.mkdir(parents=True)
        broken.write_text(text + "not json\n[1, 2]\n" + '{"kind": "plan", "fight": "f"}\n' + text.splitlines()[0][:40] + "\n", encoding="utf-8")
        records, skipped = replay_fights.read_lines([broken, Path(self.folder.name) / "missing.jsonl"])
        report = replay_fights.replay(records)
        self.assertEqual(3, skipped)
        self.assertEqual(1, report["broken"])
        self.assertEqual([], report["differ"])
        self.assertIn("3 unreadable line(s) skipped, 1 plan line(s) that could not be rebuilt", replay_fights.summary(report, skipped, 5)[0])

    def test_a_card_text_from_another_fight_is_not_replayed(self):
        records, _ = replay_fights.read_lines([FIXTURE])
        first = records[0]["fight"]
        alone = [line for line in records if line["fight"] == first]
        other = json.loads(json.dumps(alone))
        for line in other:
            line["fight"] = "another fight"
        other[0]["deck"] = {"Strike": "500% Damage"}
        self.addCleanup(cards.parsed.cache_clear)
        cards.parsed.cache_clear()
        expected = replay_fights.replay(alone)["differ"]
        cards.parsed.cache_clear()
        both = replay_fights.replay(other + alone)["differ"]
        self.assertTrue([diff for diff in both if diff["fight"] == "another fight"])
        self.assertEqual(expected, [diff for diff in both if diff["fight"] == first])

    def test_the_replay_plans_with_the_recorded_texts_and_leaves_the_live_ones(self):
        self.addCleanup(cards.parsed.cache_clear)
        cards.DECK["Strike"] = "500% Damage"
        live, recorded = cards.features("Strike"), cards.figures(cards.DESCRIPTIONS["Strike"])
        self.assertNotEqual(live, recorded)
        with replay_fights.as_recorded({}, {}):
            self.assertEqual(recorded, cards.features("Strike"))
        self.assertEqual(live, cards.features("Strike"))

    def test_lines_of_the_wrong_shape_are_counted_and_change_nothing(self):
        cards.HITS["Mei Lin"] = deque([1.0], maxlen=cards.HIT_MEMORY)
        cards.DECK["Strike"] = "text"
        text = FIXTURE.read_text(encoding="utf-8").splitlines()
        plan = json.loads(text[0])
        wrong = [{"kind": "end", "fight": plan["fight"], "outcome": [1]}, {"kind": "play", "fight": plan["fight"], "turn": [1], "result": "played"},
                 {**plan, "deck": [1, 2]}]
        self.file.parent.mkdir(parents=True)
        self.file.write_text("\n".join(text[:1] + [json.dumps(line) for line in wrong] + text[1:]) + "\n", encoding="utf-8")
        records, skipped = replay_fights.read_lines([self.file])
        report = replay_fights.replay(records)
        self.assertEqual(2, skipped)
        self.assertEqual(1, report["broken"])
        self.assertEqual([], report["differ"])
        for hits, deck in (({}, [1, 2]), ({"Selena": 5}, {})):
            with self.assertRaises(TypeError), replay_fights.as_recorded(hits, deck):
                pass
        self.assertEqual({"Mei Lin": [1.0]}, {who: list(figures) for who, figures in cards.HITS.items()})
        self.assertEqual({"Strike": "text"}, cards.DECK)

    def test_the_replay_puts_the_live_tables_back(self):
        cards.HITS["Mei Lin"] = deque([1.0], maxlen=cards.HIT_MEMORY)
        cards.DECK["Strike"] = "text"
        replay_fights.replay(replay_fights.read_lines([FIXTURE])[0])
        self.assertEqual({"Mei Lin": [1.0]}, {who: list(figures) for who, figures in cards.HITS.items()})
        self.assertEqual({"Strike": "text"}, cards.DECK)

    def test_the_help_says_it_scores_decisions_not_outcomes(self):
        self.assertIn("scores decisions, not outcomes", replay_fights.__doc__)


if __name__ == "__main__":
    unittest.main()
