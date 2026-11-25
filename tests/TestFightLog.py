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
from tests.TestEnemyRead import DEVOUR_INTRO, screen  # noqa: E402
import utils as real_utils  # noqa: E402
from tests.fakes import FakeBox  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fights" / "recorded.jsonl"
# The plans in the fixture where the picker it was recorded with missed a sure kill on the leftmost of two enemies, where the game raises a
# card, and today's picker plays Engagement Fire for it: fight, turn, time, the recorded plan and today's.
KILLS_NOW_PLANNED = (("17a45db1adc6", 3, 0.11, ("High-Power Scope", "Engagement Fire"), ("Engagement Fire", "High-Power Scope")),
                     ("17a45db1adc6", 3, 0.11, ("Engagement Fire",), ("Engagement Fire",)),
                     ("994677b1a053", 1, 0.02, ("High-Power Scope", "Engagement Fire"), ("Engagement Fire", "High-Power Scope")),
                     ("994677b1a053", 1, 0.03, ("Engagement Fire",), ("Engagement Fire",)))
# Two recorded Chaos fights with an Aether Eater, which loses 1 HP a hit behind shields that lose 1 too, standing at x 0.83 to 0.85.
AETHER_EATER = REPO_ROOT / "tests" / "fights" / "aether_eater.jsonl"
AETHER_EATER_X = 0.84
# The plans the bot made in them with a kill on the Aether Eater that today's picker no longer makes: fight and time.
KILLS_NO_LONGER_PLANNED = (("aether-eater-1", 70.05), ("aether-eater-1", 74.7), ("aether-eater-1", 86.02), ("aether-eater-1", 90.59),
                           ("aether-eater-2", 112.22), ("aether-eater-2", 124.48))
Foe = board.Foe
# The card reward's title, which only comes up after a won fight.
REWARD = "卡牌奖励"
# Full-frame reads the game gave, without the captain's level and EXP: a lost and a won Story fight's result screen, a promotion's detail
# with its Reward and no MVP, an exploration result with its MVP and no Reward, and a battle frame. The last three must never end a fight.
DEFEAT_RESULT = (("Chapter 2. Wolf's Requiem", 0.731, 0.238), ("Lv.20 Promotion Missions", 0.719, 0.272), ("Battle failed", 0.299, 0.717),
                 ("Sync failed", 0.298, 0.761), ("Reward", 0.605, 0.738), ("No loot acquired.", 0.771, 0.816), ("Retry", 0.719, 0.92),
                 ("进入", 0.817, 0.888), ("确认", 0.928, 0.918))
WIN_RESULT = (("MVP", 0.087, 0.202), ("Chapter 2. Wolf's Requiem", 0.731, 0.237), ("Lv.20 Promotion Missions", 0.718, 0.272),
              ("Reward", 0.607, 0.627), ("20", 0.615, 0.747), ("F1", 0.593, 0.888), ("Next Mission", 0.693, 0.918), ("进入", 0.811, 0.887),
              ("确认", 0.921, 0.917))
PROMOTION_DETAIL = (("Battle Missions", 0.151, 0.045), ("Chapter 2", 0.403, 0.04), ("Client information", 0.748, 0.143),
                    ("Chaos Operations Assessment Officer", 0.824, 0.18), ("①Win the battle", 0.696, 0.262), ("Promotion Missions", 0.475, 0.415),
                    ("Requires Lv.2", 0.573, 0.529), ("Reward", 0.665, 0.731), ("500", 0.678, 0.854), ("20", 0.739, 0.854), ("10", 0.801, 0.854),
                    ("48,000", 0.907, 0.854), ("18/18", 0.359, 0.931), ("NORMAL", 0.523, 0.932), ("进入", 0.817, 0.931))
EXPLORATION_RESULT = (("探险结果", 0.691, 0.119), ("MVP", 0.087, 0.2), ("Exploration Lv. 09", 0.668, 0.207), ("6/150", 0.954, 0.208),
                      ("Final Score", 0.637, 0.326), ("698", 0.93, 0.324), (") Collect The Ghoul Kennel", 0.686, 0.419), ("+60", 0.952, 0.42),
                      ("Collect Aqua Ball", 0.659, 0.739), ("+40", 0.953, 0.737), ("进入", 0.807, 0.888), ("下一步", 0.93, 0.917))
BATTLE_FRAME = (("563/568", 0.212, 0.039), ("10", 0.443, 0.042), ("Ctrl", 0.895, 0.078), ("701", 0.684, 0.163), ("297", 0.593, 0.312),
                ("297", 0.848, 0.312), ("57", 0.473, 0.387), ("157", 0.922, 0.388), ("EF", 0.03, 0.699), ("E1", 0.066, 0.752),
                ("Water Barrier", 0.365, 0.855), ("Blessing of Waves", 0.515, 0.848), ("基础技能", 0.362, 0.877), ("技能", 0.486, 0.868),
                ("Blessing of Waves", 0.65, 0.857), ("03/10", 0.501, 0.971), ("E", 0.888, 0.953))
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


def changed(report):
    """Find the plans a replay gets back different, less the kills today's picker plans on purpose where the fixture's did not.

    Args:
        report: What `replay_fights.replay` returned.

    Returns:
        The other differences, as the report holds them.
    """
    return [diff for diff in report["differ"] if (diff["fight"], diff["turn"], diff["t"], tuple(diff["recorded"]), tuple(diff["now"]))
            not in KILLS_NOW_PLANNED or diff["recorded_kills"] or diff["now_kills"] != [0]]


def two_foes():
    return [Foe(0.55, 300, 3, None, True, True), Foe(0.70, 200, 5, None, True, True)]


class Waiting(Pressed):
    """A stand-in task that notes its waits among its keys, so two fights can be compared wait for wait."""

    def sleep(self, seconds):
        self.keys.append(("sleep", seconds))


class ChaosMode(Waiting):
    """A stand-in task named like the real mode, the only kind of task the record writes for."""


class StoryMode(Waiting):
    """A stand-in task named like the real Story mode, which counts no nodes."""


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
        self.assertEqual([{"x": 0.55, "hp": 300, "hp_source": "both", "counter": 3, "weakness": None, "summoned": False},
                          {"x": 0.70, "hp": 200, "hp_source": "both", "counter": 5, "weakness": None, "summoned": False}], first["foes"])
        self.assertEqual((406, 406, 1.0, 0), (first["team_hp"], first["team_max"], first["team_share"], first["shield"]))
        self.assertFalse(first["devours"])
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
        self.assertEqual({"x": 0.55, "hp": None, "hp_source": None, "counter": None, "weakness": None,
                          "summoned": False}, first["foes"][0])

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

    def test_the_global_defeat_line_ends_the_fight_lost_only_as_a_whole_box(self):
        # Global shows the loss line untranslated. The other screens, and the words inside longer text, leave the fight open.
        lost = [("lost", "defeat title")]
        for name, texts, ends in (("lost", DEFEAT_RESULT, lost), ("other case and punctuation", [("Battle Failed.",)], lost),
                                  ("defeat inside a line", [("Battle failed to sync",)], []), ("battle frame", BATTLE_FRAME, []),
                                  ("promotion detail", PROMOTION_DETAIL, []), ("exploration result", EXPLORATION_RESULT, [])):
            with self.subTest(name):
                self.file.unlink(missing_ok=True)
                self.fight(task_class=StoryMode, end_texts=[text for text, *_ in texts])
                self.assertEqual(ends, self.ends())

    def test_a_title_that_ends_the_fight_drops_the_devour_flag(self):
        # Story counts no nodes, so only the end of the fight tells the next one, starting inside the gap, from the devouring boss's.
        for title, ends in ((REWARD, True), ("战斗失败", True), ("Battle failed", True), ("Battle failed to sync", False),
                            ("a hand prompt", False)):
            now = [100.0]
            with self.subTest(title=title), upstream(hand()) as (utils_sortie, task), mock.patch.object(battle.time, "monotonic", lambda: now[0]):
                self.stand_up(utils_sortie, task, StoryMode)
                task.node_status = None
                with mock.patch.object(board, "devours_summons", lambda task: True):
                    battle.handle_devour_text(task)
                play_fight(utils_sortie, task, TWO_TURNS[:1], two_foes(), end_texts=None)
                self.assertTrue(battle.fight_devours(task))
                now[0] += 1
                play_fight(utils_sortie, task, [], [], end_texts=(title,))
                now[0] += battle.DEVOUR_GAP - 2
                self.assertEqual(not ends, battle.fight_devours(task, seen=True))
                # The next fight's intro sets it again, and a frame off the battle screen after the ended fight leaves it standing.
                with mock.patch.object(board, "devours_summons", lambda task: True):
                    battle.handle_devour_text(task)
                play_fight(utils_sortie, task, [], [], end_texts=("a hand prompt",))
                self.assertTrue(battle.fight_devours(task))

    def test_a_result_screen_drops_the_devour_flag(self):
        # The flag set, a battle frame 5 s later, the screen after the fight, and the next Story fight's first frame 30 s after the battle frame,
        # where the gap alone still holds it. A result screen wins over devour text on the same frame.
        self.assertTrue(board.devours_summons(screen(WIN_RESULT + DEVOUR_INTRO)))
        for name, texts, drops in (("lost", DEFEAT_RESULT, True), ("won", WIN_RESULT, True), ("promotion detail", PROMOTION_DETAIL, False),
                                   ("exploration result", EXPLORATION_RESULT, False), ("battle frame", BATTLE_FRAME, False),
                                   ("won beside devour text", WIN_RESULT + DEVOUR_INTRO, True)):
            now = [100.0]
            with self.subTest(name), upstream(hand()) as (utils_sortie, task), mock.patch.object(battle.time, "monotonic", lambda: now[0]):
                self.stand_up(utils_sortie, task, StoryMode)
                task.node_status = None
                with mock.patch.object(board, "devours_summons", lambda task: True):
                    battle.handle_devour_text(task)
                now[0] += 5
                play_fight(utils_sortie, task, TWO_TURNS[:1], two_foes(), end_texts=None)
                self.assertTrue(battle.fight_devours(task, seen=True))
                task.all_texts = [FakeBox(text, x, y) for text, x, y in texts]
                pressed = list(task.keys)
                self.assertEqual(drops, battle.fight_result(task))
                self.assertFalse(battle.handle_devour_text(task))
                self.assertEqual(pressed, task.keys)
                now[0] += battle.DEVOUR_GAP
                self.assertEqual(not drops, battle.fight_devours(task, seen=True))

    def test_only_whole_result_words_make_a_result_screen(self):
        # Words a battle frame's effect feed or a card could carry, holding the result words inside longer text.
        for name, texts in (("reward inside a line", [("Reward: Draw 1", 0.6, 0.7), ("MVP", 0.08, 0.2)]),
                            ("mvp inside a line", [("Reward", 0.6, 0.7), ("MVP Bonus", 0.08, 0.2)]),
                            ("defeat inside a line", [("Reward", 0.6, 0.7), ("Battle failed to sync", 0.3, 0.7)])):
            with self.subTest(name):
                self.assertFalse(battle.fight_result(screen(texts)))
        self.assertTrue(battle.fight_result(screen([(" reward ", 0.6, 0.7), ("Battle Failed.", 0.3, 0.7)])))

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

    def test_the_fixture_replays_exactly_but_for_the_kills_now_planned_on_the_leftmost_enemy(self):
        records, skipped = replay_fights.read_lines([FIXTURE])
        report = replay_fights.replay(records)
        self.assertEqual(0, skipped)
        self.assertEqual(0, report["broken"])
        self.assertEqual([], changed(report))
        self.assertEqual(len(KILLS_NOW_PLANNED), len(report["differ"]))
        self.assertEqual(sum(line["kind"] == "plan" for line in records), report["plans"])
        self.assertGreaterEqual(report["plans"], 30)
        self.assertEqual(report["calls"], report["same"] + len(KILLS_NOW_PLANNED))
        self.assertGreater(report["recorded"]["kill available"], 0)
        self.assertEqual(sum(line["kind"] == "end" for line in records), report["fights_ended"])

    def test_no_kill_is_planned_on_the_aether_eater_once_it_lost_a_point_or_two_to_a_hit(self):
        records, _ = replay_fights.read_lines([AETHER_EATER])
        plans, plan = [], cards.plan

        def recording(hand_cards, state):
            chosen = plan(hand_cards, state)
            plans.append((state, chosen))
            return chosen

        with mock.patch.object(cards, "plan", recording):
            report = replay_fights.replay(records)
        self.assertEqual(0, report["broken"])
        self.assertEqual(KILLS_NO_LONGER_PLANNED, tuple((diff["fight"], diff["t"]) for diff in report["differ"]))
        self.assertTrue(all(diff["recorded_kills"] and not diff["now_kills"] for diff in report["differ"]))
        replanned = iter(plans)
        shrugged, before, checked = set(), {}, 0
        for line in records:
            if line["kind"] == "play":
                eater = [(foe["hp"], later["hp"]) for foe in before.get(line["fight"], ()) for later in line["foes"] or ()
                         if abs(foe["x"] - AETHER_EATER_X) <= 0.02 and abs(later["x"] - AETHER_EATER_X) <= 0.02]
                if any(foe is not None and later is not None and 1 <= foe - later <= 2 for foe, later in eater):
                    shrugged.add(line["fight"])
            elif line["kind"] == "plan":
                before[line["fight"]] = line["foes"]
                for _ in line["plans"]:
                    state, chosen = next(replanned)
                    if line["fight"] in shrugged:
                        on_it = [card for card in chosen if card.get("kills") and (card["target"] is None and len(state.foes) == 1
                                                                                   or abs((card["target"] or 0) - AETHER_EATER_X) <= 0.02)]
                        self.assertEqual([], on_it, f"{line['fight']} at {line['t']}s")
                        checked += 1
        self.assertGreater(checked, 5)

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
        self.assertEqual(1, len(changed(report)))
        self.assertEqual(line["fight"], changed(report)[0]["fight"])

    def test_a_changed_kill_is_reported(self):
        records, _ = replay_fights.read_lines([FIXTURE])
        line = next(line for line in records if line["kind"] == "plan" and line["plans"][0]["kills"])
        line["plans"][0]["kills"] = []
        report = replay_fights.replay(records)
        self.assertEqual(1, len(changed(report)))
        self.assertEqual([], changed(report)[0]["recorded_kills"])

    def test_a_replay_without_the_recorded_hits_differs(self):
        # The hits are what a kill is planned on, so a replay that dropped them could not have reproduced the kills.
        records, _ = replay_fights.read_lines([FIXTURE])
        for line in records:
            line.pop("hits", None)
        self.assertTrue(changed(replay_fights.replay(records)))

    def test_unreadable_lines_are_skipped_and_counted(self):
        text = FIXTURE.read_text(encoding="utf-8")
        broken = self.file
        broken.parent.mkdir(parents=True)
        broken.write_text(text + "not json\n[1, 2]\n" + '{"kind": "plan", "fight": "f"}\n' + text.splitlines()[0][:40] + "\n", encoding="utf-8")
        records, skipped = replay_fights.read_lines([broken, Path(self.folder.name) / "missing.jsonl"])
        report = replay_fights.replay(records)
        self.assertEqual(3, skipped)
        self.assertEqual(1, report["broken"])
        self.assertEqual([], changed(report))
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
        self.assertEqual([], changed(report))
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
