"""Check what reaches the log: that upstream's Chinese comes out English, and that nothing repeats per frame.

The table is hand-written and will end up carrying every one of the 454 shapes `ok_tasks/` logs, so the tests
that matter are the ones a wordlist gets wrong: a shape whose pattern does not match the line it renders as,
a replacement that drops one of its interpolations, and a rebase that reworded a line nobody noticed.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scan_log_strings import collect_shapes  # noqa: E402

from src.en import dashboard, log_text, state  # noqa: E402
from src.en.log_strings import MESSAGES, TEMPLATES, VALUES  # noqa: E402

CJK = re.compile(r"[一-鿿]")
# A stand-in for one interpolated value, distinctive enough that a pattern cannot match it by accident.
MARKER = "XyZ"
# What `scan_log_strings.py` finds today. Raise it as each file is translated; the last phase makes it total.
MINIMUM_COVERAGE = 51
# The Info rows `log_node_status` and `log_credit` write, which are `info_set` keys rather than logged lines,
# so the extractor never sees them. Upstream renaming one would leave the row Chinese with nothing to say so.
DASHBOARD_KEYS = ("当前信用点", "版本号", "游戏语言", "所处层数，节点，类型", "是否到达关底boss",
                  "是否进入关底boss战斗", "是否已逃脱", "是否已获得特定闪光", "获取刷存档主战员头像",
                  "本局已移除卡牌", "本局已获得中立牌", "装备信息", "当前胜率")


def rendered(shape):
    """Fill a written shape in the way the f-string in `ok_tasks/` would.

    Args:
        shape: A `TEMPLATES` key, with each interpolation written `{}`.

    Returns:
        The line as it would reach the logger, with a marker in each interpolation.
    """
    return shape.replace("{}", MARKER)


class TestTemplates(unittest.TestCase):
    """The half of the table that has to be compiled to be matched."""

    def test_every_template_matches_the_line_it_renders_as(self):
        # The likeliest authoring mistake by far: a Chinese literal carrying a regex character. The very first
        # line in the table has unescaped parens in it, at `点击目标坐标=({}, {})`.
        for shape in TEMPLATES:
            with self.subTest(shape):
                self.assertIsNotNone(log_text.compile_template(shape).match(rendered(shape)))

    def test_a_shape_carrying_regex_characters_is_matched_literally(self):
        # `_move_and_click` writes the most-logged line in the app and it has bare parens in it, so the escape
        # is what stands between the table and a pattern that matches nothing. Pinned with the real shape
        # rather than the entries present today, which happen to carry no regex character at all.
        shape = "页面处理「{}」触发点击事件，点击目标坐标=({}, {})"
        found = log_text.compile_template(shape).match(
            "页面处理「handle_route_selection」触发点击事件，点击目标坐标=(0.805, 0.425)")
        self.assertIsNotNone(found)
        self.assertEqual(("handle_route_selection", "0.805", "0.425"), found.groups())

    def test_every_replacement_uses_all_of_its_interpolations(self):
        # A dropped group silently loses a coordinate or a count from the finished line.
        for shape, english in TEMPLATES.items():
            with self.subTest(shape):
                wanted = shape.count("{}")
                used = {int(field) for field in re.findall(r"\{(\d+)\}", english)}
                self.assertEqual(set(range(wanted)), used)

    def test_no_template_answers_for_another(self):
        log_text._compile_templates()
        for shape, english in TEMPLATES.items():
            with self.subTest(shape):
                self.assertEqual(english.format(*([MARKER] * shape.count("{}"))),
                                 log_text.translate(rendered(shape)))


class TestTranslate(unittest.TestCase):
    """What comes back for something the table does not cover."""

    def test_chinese_with_no_entry_is_handed_back_unchanged(self):
        # Whole lines only. A partial rewrite would read as a bug in the tool where plain Chinese reads as
        # untranslated, and it is what keeps every Chinese value the fork does not own working as it did.
        for text in ("检测到一个没有条目的中文行", "卡牌「未知」"):
            with self.subTest(text):
                self.assertEqual(text, log_text.translate(text))

    def test_anything_that_is_not_text_is_left_alone(self):
        for value in (None, True, 3, 0.5, ["a", "b"], {"k": "v"}):
            with self.subTest(value):
                self.assertIs(value, log_text.translate(value))

    def test_english_is_handed_back_untouched(self):
        self.assertEqual("nothing to do here", log_text.translate("nothing to do here"))

    def test_every_translation_is_english(self):
        for source in (MESSAGES.values(), TEMPLATES.values(), VALUES.values()):
            for english in source:
                with self.subTest(english):
                    self.assertIsNone(CJK.search(english))


class TestReporting(unittest.TestCase):
    """The Info rows, and how often they reach the log."""

    class Task:
        """A task holding just the Info dict and the echo the framework would write."""

        def __init__(self):
            self.info = {}
            self.echoed = []

        def info_set(self, key, value):
            if key not in ("Log", "Error"):
                self.echoed.append(key)
            self.info[key] = value

    @staticmethod
    def report(task, rows):
        """Put rows through the patched `info_set`.

        Args:
            task: The fake task to report on.
            rows: `(key, value)` pairs, in order.

        Returns:
            The task's rows.
        """
        log_text._compile_templates()
        patched = log_text.reporting(TestReporting.Task.info_set)
        for key, value in rows:
            patched(task, key, value)
        return task.info

    def test_a_row_that_did_not_move_is_not_echoed_again(self):
        task = self.Task()
        self.report(task, [("当前信用点", "203")] * 5)
        self.assertEqual(["Credits"], task.echoed)

    def test_a_row_that_moved_is_echoed(self):
        task = self.Task()
        self.report(task, [("当前信用点", "203"), ("当前信用点", "203"), ("当前信用点", "96")])
        self.assertEqual(["Credits", "Credits"], task.echoed)

    def test_the_tab_still_gets_every_row_whether_or_not_it_moved(self):
        # Withholding the echo must never withhold the row: the tab reads `info`, not the log.
        task = self.Task()
        self.report(task, [("当前信用点", "203")] * 3 + [("是否已逃脱", "False"), ("版本号", "dev")])
        self.assertEqual({"Credits": "203"}, task.info, "a hidden row is never drawn")

    def test_the_rows_a_catalog_could_not_reach_are_english(self):
        # These three are composed at runtime, so `og.app.tr` could never have matched them whole.
        log_text._compile_templates()
        self.assertEqual("Floor 2, node 5, Elite Battle Area", log_text.translate("第2层，第5节点，精英"))
        self.assertEqual("slot 1 Anchor, slot 2 empty, slot 3 empty",
                         log_text.translate("1号位：Anchor，2号位：空，3号位：空"))
        self.assertEqual("Meditating on Soul Riff", log_text.translate("冥想：Soul Riff"))

    def test_a_row_reads_the_same_before_the_run_has_a_node_type(self):
        # `node_status` opens with `node_type` empty, so the first status row of every run renders with the
        # last interpolation missing entirely.
        log_text._compile_templates()
        self.assertEqual("Floor 1, node 0, ", log_text.translate("第1层，第0节点，"))


class TestSayOnce(unittest.TestCase):
    """Decisions the judging handlers reach on every tick the screen is up."""

    class Task:
        """A task carrying only the Info dict `say_once` reads the start of a run from."""

        def __init__(self):
            self.info = {"Version": "dev"}

    def setUp(self):
        self.task = self.Task()
        self.said = []
        state.logger.info = self.said.append

    def test_a_decision_that_has_not_changed_is_said_once(self):
        for _ in range(4):
            state.say_once(self.task, state.GEAR, "slot 2 is filled on every combatant")
        self.assertEqual(["[gear] slot 2 is filled on every combatant"], self.said)

    def test_a_different_decision_is_said(self):
        state.say_once(self.task, state.GEAR, "24 credits is under the 29 floor")
        state.say_once(self.task, state.GEAR, "96 credits is over the 29 floor")
        self.assertEqual(2, len(self.said))

    def test_each_tag_is_remembered_on_its_own(self):
        state.say_once(self.task, state.GEAR, "the same words")
        state.say_once(self.task, state.BATTLE, "the same words")
        self.assertEqual(["[gear] the same words", "[battle] the same words"], self.said)

    def test_a_new_run_says_it_again(self):
        # The framework clears `info` on Start. Without reading that, a second run opening on the state the
        # first one ended in would report none of it - which is the bug `src/en/stuck.py` exists for.
        state.say_once(self.task, state.GEAR, "slot 1 is bare and there are 300 credits")
        self.task.info.clear()
        state.say_once(self.task, state.GEAR, "slot 1 is bare and there are 300 credits")
        self.assertEqual(2, len(self.said))


class TestReadingOrder(unittest.TestCase):
    """The Info rows as drawn, once every row has been written out of order."""

    def test_rows_come_out_in_reading_order(self):
        # A row that falls through to the bottom would mean ORDER stopped naming it.
        meditations = ["Meditating on Shock", "Meditating on Rally"]
        team = ["Hugo", "Owen"]
        written = [dashboard.TARGET_PORTRAIT, dashboard.DECK, *meditations, "Something new", dashboard.RUNS, *team,
                   MESSAGES["当前信用点"], dashboard.FLOOR_ROW, dashboard.LOG]
        task = TestReporting.Task()
        setattr(task, dashboard.TEAM_NAMES, team)
        info_set = dashboard.ordering(TestReporting.Task.info_set)
        for key in written:
            info_set(task, key, "")

        expected = [dashboard.LOG, dashboard.FLOOR_ROW, MESSAGES["当前信用点"], dashboard.RUNS, *team, dashboard.DECK,
                    *meditations, dashboard.TARGET_PORTRAIT, "Something new"]
        self.assertEqual(expected, list(task.info))


class TestPresentedRows(unittest.TestCase):
    """Upstream's row writes, as the rows the table draws."""

    class Task(TestReporting.Task):
        """A task carrying the run state and settings the rows are composed from."""

        def __init__(self, config=None, **status):
            super().__init__()
            self.config = config or {}
            self.node_status = status

    def test_rows_read_in_plain_words(self):
        # Each value is upstream's row as written, so a reworded upstream row fails here.
        for status, config, key, written, row, shown in (
                ({}, {}, "所处层数，节点，类型", "第1层，第0节点，", "Floor", "Floor 1, node 0"),
                ({}, {}, "所处层数，节点，类型", "第2层，第5节点，精英", "Floor", "Floor 2, node 5, Elite Battle Area"),
                ({"final_boss_battle": True, "reach_final_boss": True}, {}, "所处层数，节点，类型", "第3层，第7节点，精英", "Floor",
                 "Floor 3, boss fight"),
                ({"total_rounds": 0, "success_rounds": 0}, {"几轮后停止(0为不停止)": 5}, "当前胜率", "0/0 NaN", "Runs", "0 of 5 done"),
                ({"total_rounds": 4, "success_rounds": 3}, {"几轮后停止(0为不停止)": 0}, "当前胜率", "3/4 (75%)", "Runs", "4 done, 3 won"),
                ({"removed_card_count": 2, "neutral_card_count": 1}, {}, "本局已移除卡牌", 2, "Deck this run", "2 removed, 1 Neutral taken"),
                ({}, {"刷存档主战员": "Hugo"}, "获取刷存档主战员头像", False, "Target portrait captured", "No")):
            with self.subTest(written):
                self.assertEqual(shown, TestReporting.report(self.Task(config, **status), [(key, written)])[row])

    def test_the_target_rows_only_show_while_their_setting_is_on(self):
        # Sortie declares neither setting, so before this its table carried two rows that could only ever say No.
        rows = [("是否已获得特定闪光", False), ("获取刷存档主战员头像", False)]
        for config in ({}, {"刷存档主战员": "(none)", "首层刷特定闪光": False}):
            with self.subTest(config):
                self.assertEqual({}, TestReporting.report(self.Task(config), rows))
        shown = TestReporting.report(self.Task({"刷存档主战员": "Hugo", "首层刷特定闪光": True}), rows)
        self.assertEqual({dashboard.TARGET_EPIPHANY: "No", dashboard.TARGET_PORTRAIT: "No"}, shown)

    def test_an_unchanged_row_is_echoed_once(self):
        # The floor row is rewritten, so it only settles if the rewrite lands before `log_text` compares.
        task = self.Task()
        TestReporting.report(task, [("所处层数，节点，类型", "第1层，第0节点，")] * 3)
        self.assertEqual(["Floor"], task.echoed)

    def test_runs_counts_a_run_that_stopped_the_task(self):
        # Upstream counts the run and stops the task before it rewrites its win rate, so a 1-run limit read "0 of 1 done".
        task = self.Task({"几轮后停止(0为不停止)": 1}, total_rounds=0, success_rounds=0)
        TestReporting.report(task, [("当前胜率", "0/0 NaN")])
        task.node_status.update(total_rounds=1, success_rounds=1)
        rows = TestReporting.report(task, [(dashboard.LOG, "stopping")])
        self.assertEqual("1 of 1 done, 1 won", rows[dashboard.RUNS])


class TestSeededTable(unittest.TestCase):
    """The Info table over the first seconds of a run.

    Starting a task clears it, and a row is only created by its first write, so it fell to the single row the
    first log line makes and grew back over the next few seconds as the status handlers reached a frame. Every
    row a run will fill is seeded blank at the clear instead, so only the values arrive late.
    """

    class Task(TestReporting.Task):
        """A task the framework can clear, carrying the `node_status` a Chaos or Sortie mode builds."""

        node_status = {"node_count": 0}

        def info_clear(self):
            self.info.clear()

    def cleared(self, task=None):
        """Start a run on a task holding a finished one's rows, and report what the table holds after.

        Args:
            task: The task to start, or None for one that runs the status handlers.

        Returns:
            The task's rows.
        """
        task = task if task is not None else self.Task()
        task.info.update({dashboard.LOG: "done", dashboard.COMBATANTS: "Arabella, Adelheid, Narja"})
        dashboard.seeding_the_table(type(task).info_clear)(task)
        return task.info

    def test_every_row_a_run_fills_is_there_from_the_start(self):
        self.assertEqual(list(dashboard.STARTED), list(self.cleared()))

    def test_the_rows_are_seeded_in_reading_order(self):
        # Seeded straight into the dict, so they are drawn in the order they go in rather than re-sorted.
        rows = list(self.cleared())
        self.assertEqual(rows, [key for key in dashboard.ORDER if key in rows])

    def test_nothing_of_the_last_run_survives_the_clear(self):
        self.assertEqual({dashboard.UNREAD}, set(self.cleared().values()))

    def test_the_meditation_rows_are_left_to_arrive(self):
        # One row per configured card rather than a key, so there is nothing to seed under that rank.
        self.assertNotIn(dashboard.MEDITATING, self.cleared())

    def test_a_mode_that_fills_none_of_them_is_left_empty(self):
        # Story runs neither status handler, so seeded rows there would stay blank for the whole run.
        story = self.Task()
        story.node_status = None
        self.assertEqual({}, self.cleared(story))


class TestTeamRows(unittest.TestCase):
    """One row per combatant with their gear, in place of upstream's team and equipment rows.

    Upstream's equipment row is a ledger of installs, blank at the start of every run, so the gear comes from what
    `src/en/equipment.py` read off the screen instead.
    """

    LEDGER = "1号位：空，2号位：空，3号位：空"

    def test_the_placeholder_holds_until_the_team_is_read(self):
        task = TestReporting.Task()
        setattr(task, dashboard.TEAM_GEAR, "Rare/Legend/Mythic")
        self.assertEqual({dashboard.COMBATANTS: dashboard.UNREAD}, TestReporting.report(task, [("装备信息", self.LEDGER)]))

    def test_each_combatant_gets_their_own_gear(self):
        task = TestReporting.Task()
        setattr(task, dashboard.TEAM_NAMES, ["Hugo", "Owen", "Mika"])
        setattr(task, dashboard.TEAM_GEAR, "Rare/Legend/Mythic, -/Mythic/-")
        rows = TestReporting.report(task, [(dashboard.COMBATANTS, dashboard.UNREAD), ("装备信息", self.LEDGER)])
        self.assertEqual({"Hugo": "Rare, Legend, Mythic", "Owen": "empty, Mythic, empty", "Mika": dashboard.UNREAD}, rows)

    def test_an_unchanged_reading_stops_being_logged(self):
        # Upstream writes its ledger every tick, so a row that never settles is logged at INFO on every one.
        task = TestReporting.Task()
        setattr(task, dashboard.TEAM_NAMES, ["Hugo"])
        setattr(task, dashboard.TEAM_GEAR, "Rare/Legend/Mythic")
        TestReporting.report(task, [("装备信息", self.LEDGER)] * 3)
        self.assertEqual(["Hugo"], task.echoed)


class TestUpstreamStillWritesWhatWeTranslate(unittest.TestCase):
    """The rebase alarms. Upstream rewording a line leaves it Chinese, with nothing else to say so."""

    def test_coverage_has_not_regressed(self):
        shapes = collect_shapes()
        covered = len(set(shapes) & (set(MESSAGES) | set(TEMPLATES)))
        self.assertGreaterEqual(covered, MINIMUM_COVERAGE)

    def test_every_dashboard_row_is_still_written_by_upstream(self):
        source = (REPO_ROOT / "ok_tasks" / "utils.py").read_text(encoding="utf-8")
        written = set()
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "info_set" and node.args):
                key = node.args[0]
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    written.add(key.value)
        # The rows composed from run state and settings rather than from upstream's text.
        modes = "".join((REPO_ROOT / "ok_tasks" / name).read_text(encoding="utf-8") for name in ("ChaosMode.py", "SortieMode.py"))
        for key in (dashboard.STOP_AFTER, dashboard.FARM_EPIPHANY):
            with self.subTest(key):
                self.assertIn(f"'{key}'", modes.replace('"', "'"))
        for flag in ("total_rounds", "success_rounds", "removed_card_count", "neutral_card_count",
                     *(name for name, _ in dashboard.BOSS_FLAGS)):
            with self.subTest(flag):
                self.assertIn(f"'{flag}'", source.replace('"', "'"))
        for key in DASHBOARD_KEYS:
            with self.subTest(key):
                self.assertIn(key, written)


if __name__ == "__main__":
    unittest.main()
