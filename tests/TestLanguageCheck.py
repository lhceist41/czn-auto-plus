"""Check that a run stops once, with what to change, when Game Language cannot read the client, and never on a pairing that works.

The English frames are live Global-client readings as the raw OCR returns them: what the run's own reading turned into
catalog Chinese is put back to the English the client draws, and the OCR's stray characters are left in.
"""

import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import game_language, handlers, language_check  # noqa: E402
from tests.TestDailyMode import registered_installs, stand_in  # noqa: E402
from tests.fakes import FakeBox  # noqa: E402

TRADITIONAL = "繁体中文"
SIMPLIFIED = "简体中文"
ENGLISH = "English"
INSTALLS = 3

TITLE = ["ready", "CHAOS", "ZERO", "NIGHTMARE", "TOUCHTOSTART", "Repair Resources", "cznlive:853 R:166 t:enm:ja o:en weglobal",
         "©Smilegate. All Rights Reserved."]
LOBBY = ["N", "104/240+", "U", "LV", "mail", "😜", "N", "F", "★", "48%", "F2", "F3", "Q", "-Chapter 2, Episode 2", "Story", "Act",
         'ir Story Chapter 2. EP "Ark Cit', "1/1", "Sortie", "010d 5h", "Simulation", "Nightmare Carnival", "Chaos", "F4",
         "Awaiting policies 2", "Ark City", "Combatants", "6", "EVENT", "Rescue", "N", "·C4>", "31d 5h", "Blazebell", "Rate up",
         "Upon the SnW", "APromrse"]
CHAOS_MAP = ["241/241", "0", "(", "9", "□", "Tap an Area to move to.", "+", ">"]
STORY_HUB = ["Story", "N", "ECOJCI-221C-L101", "Act 1- Chapter 2, Episode 2", "Story", "N", "Battle Missions", "Chapter 2 B6"]
BATTLE = ["236/236", "□", "U-uwahhhh!", "933", "START", "EF", "Water Barrier", "Dark Blade", "Water Arrow", "Basic Skill",
          "Basic Attack", "Dark Blade", "Basic Attack", "Basic Attack", "Downward Cut", "Basic", "105/10"]
LEVEL_UP = ["Level Up", "Attack", "246", "286", "Defense", "53", "65", "Health", "115", "149", "V", "Tap to close the window."]
ITEMS = ["Items Obtained", "200", "40,000", "Tap to close the window.", "Enter"]
ENGLISH_RUN = [TITLE, LOBBY, CHAOS_MAP, STORY_HUB, BATTLE, LEVEL_UP, ITEMS]
# Every English frame on record that carries fewer than two long words, battles and turn ends mostly, stray characters kept.
SPARSE = [
    ["157 /157", "6", "CCC", "853", "□2", "5+5", "EF", "00/10"],
    ["145/157", "Y", "90", "8", "406", "Z3", "13+2", "EF", "100/10"],
    ["184／236", "□", "Running away won't change anything.", "8", "406", "□4", "3", "15+2", "个00/10", "3"],
    ["184/236", "You did well, Rei!", "406", "2", "15+2", "00/10", "3"],
    ["184/236", "406", "￥2", "I think I can do just about anything now!", "15+2", "100/10"],
    ["184/236", "406", "I think I can do just about anything now!", "15+2", "Q00/10"],
    ["184/236", "406", "I think I can do just about anything now!", "15+2", "00/10"],
    ["241/241", "0", "(", "9", "□", "Tap an Area to move to.", "+", ">"],
    ["135/241", "ツ三", "73", "□+7", "印3", "6", "5", "5", "四00/10"],
    ["157/358", "9", "□", "82", "Ctrl", "Q", "2", "1", "X", "50", "X", "?", "Z16", "10", "A", "12", "CS", "印3", "5", "F1", "K",
     "F2", "F3", "100/10", "E"],
    ["|Achievement Log", "1", "02", "LV", "7", "20", "10", "40,000", "大", "03", "LV", "1", "20", "10", "04", "LV", "4", "20", "10",
     "40,000", "05", "LV", "300", "4", "20", "10"],
    ["|Achievement Log", "1", "16", "LV", "8", "8", "40", "20", "17", "X", "……", "1", "8", "8", "40", "20", "18", "LV", "5", "8", "8",
     "40", "20", "19", "LV", "……", "8", "8", "40", "20"],
    ["426/426", "267", "R", "Cti", "Q", "+", "M", "X", "5"],
    ["426/426", "255", "M", "R", "Ctrl", "Q", "+", "M", "四", "四"],
    ["W", "④Blessing ofWaves", "0/100pt", "0/100pt", "0/100pt", "26180TB", "▼11350 TB"],
]
JAPANESE = ["攻撃力", "スキル", "カードを選択してください", "確認", "バトル開始", "防御力", "キャンセル", "報酬", "HP", "120/120"]
KOREAN = ["공격력", "스킬", "카드를 선택하세요", "확인", "전투 시작", "방어력", "취소", "보상", "HP", "120/120"]
# A screen that holds still with long Latin words and next to no Chinese, as a Traditional client might draw one.
STILL_TRADITIONAL = ["183/241", "0", "AUTO", "SKIP", "SPEED", "MENU", "戰鬥"]


def chinese_frames():
    """Build Chinese-client frames from the screen text the OCR catalog names, with the short Latin a Chinese client keeps.

    Returns:
        A list of frames, each a list of box texts.
    """
    catalog = (REPO_ROOT / "i18n" / "en_US" / "LC_MESSAGES" / "ocr.po").read_text(encoding="utf-8")
    texts = [text for text in re.findall(r'^msgstr "(.+)"$', catalog, re.M) if language_check.CJK_WORD.search(text)]
    return [texts[start:start + 8] + ["HP", "Lv.20", "120/120", "F1"] for start in range(0, len(texts), 8)]


class FakeTask:
    """A mode looking at one frame per pass, recording raw reads, announcements and stops."""

    def __init__(self, frames):
        """Queue the frames the passes will see.

        Args:
            frames: Frames in order, one per pass, each a list of box texts. The last one stays on screen.
        """
        self.name = "自动卡厄思模式"
        self.frames = list(frames)
        self.screen = []
        self.translation = object()
        self.executor = types.SimpleNamespace(ocr_po_translation=self.translation)
        self.all_texts = []
        self.reads = []
        self.logged = []
        self.notifications = []
        self.disabled = 0
        self.enabled = True

    def next_pass(self):
        """Show the next frame and read it the way a mode's `run` does before its handlers."""
        self.screen = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        self.all_texts = [FakeBox(text, 0.5, 0.5) for text in self.screen]

    def ocr(self):
        self.reads.append(self.executor.ocr_po_translation)
        return [FakeBox(text, 0.5, 0.5) for text in self.screen]

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled += 1
        self.enabled = False


def message(setting, client, wanted):
    return language_check.MESSAGE.format(setting=setting, client=client, wanted=wanted)


TRADITIONAL_ON_ENGLISH = message("Traditional Chinese", "English", "English")
ENGLISH_ON_CHINESE = message("English", "Chinese", "Traditional Chinese")


class Checked(unittest.TestCase):

    def setUp(self):
        self.setting = ENGLISH
        patcher = mock.patch.object(game_language, "current", lambda: self.setting)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_frames(self, task, passes):
        """Run the check over a number of frames the way the loop does.

        Args:
            task: The task.
            passes: How many frames.

        Returns:
            The pass, counted from 1, on which the check first claimed a frame, or None.
        """
        claimed = None
        for number in range(1, passes + 1):
            task.next_pass()
            if language_check.check_game_language(task) and claimed is None:
                claimed = number
        return claimed


class TestEnglishClient(Checked):

    def test_traditional_on_an_english_client_stops_once_with_what_to_change(self):
        self.setting = TRADITIONAL
        task = FakeTask(ENGLISH_RUN)
        claimed = self.run_frames(task, len(ENGLISH_RUN))
        self.assertIsNotNone(claimed)
        self.assertLessEqual(claimed, language_check.FRAMES + 1)
        self.assertEqual([TRADITIONAL_ON_ENGLISH], task.notifications)
        self.assertIn(TRADITIONAL_ON_ENGLISH, task.logged)
        self.assertGreaterEqual(task.disabled, 1)

    def test_the_message_names_the_choices_as_the_settings_page_shows_them(self):
        self.assertIn("Game Language is set to Traditional Chinese", TRADITIONAL_ON_ENGLISH)
        self.assertIn("Set Game Language to English on the Settings page", TRADITIONAL_ON_ENGLISH)
        self.assertNotIn(TRADITIONAL, TRADITIONAL_ON_ENGLISH)
        self.assertFalse(language_check.CJK_WORD.search(ENGLISH_ON_CHINESE))

    def test_english_and_simplified_on_an_english_client_never_stop(self):
        """Simplified reads an English client the same way English does: `_get_game_text` has no map for either."""
        for setting in (ENGLISH, SIMPLIFIED):
            for start in range(len(ENGLISH_RUN)):
                with self.subTest(setting=setting, start=start):
                    self.setting = setting
                    task = FakeTask(ENGLISH_RUN[start:] + ENGLISH_RUN[:start])
                    self.assertIsNone(self.run_frames(task, language_check.READS * 2))
                    self.assertEqual([], task.notifications)
                    self.assertEqual(0, task.disabled)

    def test_no_single_frame_settles_the_language(self):
        """One frame read once is never enough, however English it looks."""
        self.setting = TRADITIONAL
        for frame in ENGLISH_RUN + SPARSE:
            with self.subTest(frame=frame[:3]):
                task = FakeTask([frame])
                self.assertIsNone(self.run_frames(task, 1))
                self.assertEqual(0, task.disabled)

    def test_one_screen_read_again_and_again_settles_nothing(self):
        """A run that starts on a screen that holds still sees it on every pass, and that is still one frame read once."""
        self.setting = TRADITIONAL
        for frame in ENGLISH_RUN + [STILL_TRADITIONAL]:
            with self.subTest(frame=frame[:3]):
                task = FakeTask([frame])
                self.assertIsNone(self.run_frames(task, language_check.READS * 2))
                self.assertEqual(1, len(task.reads))
                self.assertEqual(0, task.disabled)

    def test_screens_that_hold_still_for_many_passes_still_settle_the_language(self):
        """The Entry Guide and the record notice sit still for many passes, so held screens must not use up the reads."""
        for hold in (10, 15, language_check.READS):
            frames = [frame for frame in ENGLISH_RUN for _ in range(hold)]
            with self.subTest(hold=hold, setting=TRADITIONAL):
                self.setting = TRADITIONAL
                task = FakeTask(frames)
                self.assertIsNotNone(self.run_frames(task, len(frames)))
                self.assertEqual([TRADITIONAL_ON_ENGLISH], task.notifications)
                self.assertLessEqual(len(task.reads), language_check.FRAMES + 1)
            with self.subTest(hold=hold, setting=ENGLISH):
                self.setting = ENGLISH
                task = FakeTask(frames)
                self.assertIsNone(self.run_frames(task, len(frames)))
                self.assertEqual([], task.notifications)
                self.assertEqual(language_check.ENGLISH, vars(task)[language_check.TALLY].verdict())

    def test_two_screens_that_alternate_for_many_passes_still_let_a_third_settle_the_language(self):
        """A run can bounce between two screens its handlers miss, or read one still screen two ways by turns."""
        for first, second in ((TITLE, LOBBY), (LOBBY, LOBBY[:-1] + ["APromise"])):
            rest = [frame for frame in ENGLISH_RUN if frame not in (first, second)]
            frames = [first, second] * language_check.READS + rest
            with self.subTest(first=first[:2], setting=TRADITIONAL):
                self.setting = TRADITIONAL
                task = FakeTask(frames)
                claimed = self.run_frames(task, len(frames))
                self.assertIsNotNone(claimed)
                self.assertGreater(claimed, 2 * language_check.READS)
                self.assertEqual([TRADITIONAL_ON_ENGLISH], task.notifications)
                self.assertLessEqual(len(task.reads), 2 + len(rest))
            with self.subTest(first=first[:2], setting=ENGLISH):
                self.setting = ENGLISH
                task = FakeTask(frames)
                self.assertIsNone(self.run_frames(task, len(frames)))
                self.assertEqual([], task.notifications)
                self.assertEqual(language_check.ENGLISH, vars(task)[language_check.TALLY].verdict())

    def test_two_screens_that_alternate_spend_one_raw_read_each(self):
        self.setting = TRADITIONAL
        task = FakeTask([TITLE, LOBBY] * language_check.READS * 2)
        self.assertIsNone(self.run_frames(task, language_check.READS * 4))
        self.assertEqual(2, len(task.reads))
        self.assertFalse(vars(task)[language_check.TALLY].done)

    def test_frames_that_each_fall_short_never_stop_together(self):
        self.setting = TRADITIONAL
        task = FakeTask(SPARSE + [[]])
        self.assertIsNone(self.run_frames(task, len(SPARSE)))
        self.assertEqual([], task.notifications)
        self.assertEqual(0, task.disabled)

    def test_an_english_client_never_reads_as_chinese(self):
        tally = language_check.Tally()
        for frame in (ENGLISH_RUN + SPARSE) * 3:
            tally.add(frame)
            self.assertNotEqual(language_check.CHINESE, tally.verdict())


class TestChineseClient(Checked):

    def test_english_on_a_chinese_client_stops_once_with_what_to_change(self):
        frames = chinese_frames()
        self.assertGreaterEqual(len(frames), language_check.FRAMES + 2)
        task = FakeTask(frames)
        self.assertIsNotNone(self.run_frames(task, len(frames)))
        self.assertEqual([ENGLISH_ON_CHINESE], task.notifications)
        self.assertGreaterEqual(task.disabled, 1)

    def test_chinese_settings_on_a_chinese_client_never_stop(self):
        """Simplified may be a Simplified client read right, and a script count cannot tell it from a Traditional one."""
        for setting in (TRADITIONAL, SIMPLIFIED):
            with self.subTest(setting=setting):
                self.setting = setting
                task = FakeTask(chinese_frames())
                self.assertIsNone(self.run_frames(task, language_check.READS))
                self.assertEqual([], task.notifications)

    def test_a_japanese_or_korean_client_is_not_taken_for_a_chinese_one(self):
        """Kanji alone would read as Chinese, and the stop would send the player to a language the game does not show."""
        for frame in (JAPANESE, KOREAN):
            with self.subTest(frame=frame[0]):
                # Each box order is a different frame, so the boxes are counted read after read.
                task = FakeTask([frame[start:] + frame[:start] for start in range(len(frame))])
                self.assertIsNone(self.run_frames(task, language_check.READS))
                self.assertEqual([], task.notifications)


class TestOncePerRun(Checked):

    def test_after_a_verdict_the_check_reads_nothing_more_and_stays_quiet(self):
        task = FakeTask(ENGLISH_RUN[:language_check.FRAMES + 1] + chinese_frames() * 4)
        self.assertIsNone(self.run_frames(task, language_check.READS * 2))
        reads = len(task.reads)
        self.assertLessEqual(reads, language_check.FRAMES + 1)
        self.assertEqual([], task.notifications)
        self.assertEqual(0, task.disabled)

    def test_a_stopped_run_keeps_claiming_frames_without_announcing_again(self):
        """The loop can come round again before it sees the task disabled, and a toast per frame would bury the one that matters."""
        self.setting = TRADITIONAL
        task = FakeTask(ENGLISH_RUN)
        claimed = self.run_frames(task, len(ENGLISH_RUN))
        self.assertIsNotNone(claimed)
        reads, disabled = len(task.reads), task.disabled
        for _ in range(5):
            self.assertIs(True, language_check.check_game_language(task))
        self.assertEqual(reads, len(task.reads))
        self.assertEqual([TRADITIONAL_ON_ENGLISH], task.notifications)
        self.assertEqual(disabled + 5, task.disabled)

    def test_a_run_that_settles_nothing_gives_up_reading(self):
        self.setting = TRADITIONAL
        # A new frame every pass with no long word at all, so even the whole budget of reads adds up to nothing.
        task = FakeTask([[f"{health}/157", "6", "EF", "00/10"] for health in range(100, 100 + language_check.READS * 2)])
        self.assertIsNone(self.run_frames(task, language_check.READS * 2))
        self.assertEqual(language_check.READS, len(task.reads))
        self.assertEqual(0, task.disabled)

    def test_a_failed_read_never_stops_and_stops_the_reads(self):
        self.setting = TRADITIONAL
        task = FakeTask(ENGLISH_RUN)

        def broken():
            task.reads.append(None)
            raise RuntimeError("no frame")

        task.ocr = broken
        self.assertIsNone(self.run_frames(task, 10))
        self.assertEqual(1, len(task.reads))
        self.assertEqual(0, task.disabled)

    def test_the_read_is_raw_and_leaves_the_run_reading_alone(self):
        """`ocr.po` turns an English client's captions into Chinese, which would count towards the wrong client."""
        task = FakeTask(ENGLISH_RUN)
        for _ in range(2):
            task.next_pass()
            before = list(task.all_texts)
            language_check.check_game_language(task)
            self.assertEqual(before, task.all_texts)
        self.assertEqual([None, None], task.reads)
        self.assertIs(task.translation, task.executor.ocr_po_translation)


class TestStartButton(Checked):
    """Each Start checks afresh, so a player who fixed the setting after a stop gets a run.

    The Start button marks a mode enabled before the run loop calls `enable`, so a reset that waits for a stopped task
    never runs on that path.
    """

    def setUp(self):
        super().setUp()
        from ok.core.start_controller import StartController
        from ok.task.task import BaseTask, TriggerTask
        self.mark_enabled = StartController._mark_task_enabled
        for patcher in (mock.patch.object(BaseTask, "enable", BaseTask.enable), mock.patch.object(language_check, "_patched", False),
                        mock.patch.object(language_check, "register")):
            patcher.start()
            self.addCleanup(patcher.stop)
        language_check.apply()

        class Mode(TriggerTask):
            """A mode whose `enable` goes on to the framework's, as Chaos, Sortie and Story do."""

            ocr = FakeTask.ocr
            next_pass = FakeTask.next_pass
            log_info = FakeTask.log_info
            notification = FakeTask.notification

            def __init__(self):
                self.name = "自动卡厄思模式"
                self._enabled = False
                self.config = {}
                self.info = {}
                self.frames = []
                self.screen = []
                self.all_texts = []
                self.reads = []
                self.logged = []
                self.notifications = []
                self._executor = types.SimpleNamespace(ocr_po_translation=None, enqueue_onetime_task=lambda task: None,
                                                       remove_onetime_task=lambda task: None, _wake_executor=lambda: None)

            def enable(self):
                super().enable()

        self.task = Mode()

    def start(self, frames):
        """Press Start the way the window does, then let the run loop call `enable` as `src/en/shell.py` does."""
        self.task.frames = list(frames)
        self.mark_enabled(self.task)
        self.task.enable()

    def test_a_run_after_a_stop_checks_afresh(self):
        self.setting = TRADITIONAL
        self.start(ENGLISH_RUN)
        self.assertIsNotNone(self.run_frames(self.task, len(ENGLISH_RUN)))
        self.assertFalse(self.task.enabled)
        self.setting = ENGLISH
        reads = len(self.task.reads)
        self.start(ENGLISH_RUN)
        self.assertIsNone(self.run_frames(self.task, language_check.READS))
        self.assertTrue(self.task.enabled)
        self.assertGreater(len(self.task.reads), reads)
        self.assertEqual([TRADITIONAL_ON_ENGLISH], self.task.notifications)

    def test_a_run_after_a_quiet_one_checks_afresh(self):
        """The player may change the setting between runs, and the run after must see it."""
        self.start(ENGLISH_RUN)
        self.assertIsNone(self.run_frames(self.task, language_check.READS))
        self.task.disable()
        self.setting = TRADITIONAL
        self.start(ENGLISH_RUN)
        self.assertIsNotNone(self.run_frames(self.task, len(ENGLISH_RUN)))
        self.assertEqual([TRADITIONAL_ON_ENGLISH], self.task.notifications)


class TestInstall(unittest.TestCase):

    def test_after_every_install_the_check_runs_right_behind_the_stuck_stop_in_chaos_sortie_and_story(self):
        """Behind the hold, so a held run is never stopped, and ahead of every handler that taps."""
        real = {name: sys.modules[name] for name, _ in handlers.each_list()}
        real.update({name: sys.modules[name] for name in ("utils", "utils_chaos", "utils_sortie", "utils_story", "src.en.daily")})
        copies = {name: stand_in(module) for name, module in real.items()}
        with mock.patch.dict(sys.modules, copies):
            for _ in range(INSTALLS):
                for install in registered_installs():
                    install()
        for mode in language_check.MODES:
            with self.subTest(mode=mode):
                names = [handler.__name__ for handler in copies[mode].PAGE_HANDLERS]
                self.assertEqual("handle_remote", names[0])
                self.assertEqual(1, names.count("check_game_language"))
                self.assertEqual(names.index("stop_when_stuck") + 1, names.index("check_game_language"))
        self.assertNotIn("check_game_language", [handler.__name__ for handler in copies["src.en.daily"].PAGE_HANDLERS])

    def test_it_goes_behind_the_hold_where_there_is_no_stuck_stop(self):
        def handle_remote(task):
            return False

        def handle_auto_stop(task):
            return False

        module = types.ModuleType("utils_sortie")
        module.PAGE_HANDLERS = [handle_remote, handle_auto_stop]
        with mock.patch.dict(sys.modules, {"utils_sortie": module, "utils_chaos": types.ModuleType("utils_chaos"),
                                           "utils_story": types.ModuleType("utils_story")}):
            for _ in range(INSTALLS):
                language_check.install()
        self.assertEqual(["handle_remote", "check_game_language", "handle_auto_stop"], [handler.__name__ for handler in module.PAGE_HANDLERS])


if __name__ == "__main__":
    unittest.main()
