"""Check that Chaos walks from the Lobby to The Blue Pot's Team Formation, or back into an open run, and presses nothing else.

The screens are the boxes OCR read off the Global client on the way in, as the bot sees them once the catalog has mapped
them, with the player's name left out: the faded Lobby with a speech bubble, the Lobby, the Chaos hub, the Chaos
Manifestation map, The Blue Pot's detail, the Team Formation, and the prompt a run still open raises. What the walk must
never do: press the prompt's Escape, which abandons the run, or its Cancel; press the Zero System card; walk a run Story
handed over; take any screen of a run for one of its own.
"""

import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

import utils  # noqa: E402

from src.en import chaos_entry, daily, enter, handlers, notify  # noqa: E402
from src.en.screen import centre_of  # noqa: E402
from src.en.story_relay import RELAYED  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402
from tests.TestChaosScreens import ENTRY_GUIDE, OTHER_SCREENS, RECORD_CARD, RECORD_ENCOURAGEMENT  # noqa: E402
from tests.TestDailyMode import LOBBY as LOBBY_ICON_READ  # noqa: E402
from tests.TestDailyMode import SCENE_REGION, faded_lobby, placed, registered_installs, stand_in  # noqa: E402

INSTALLS = 3
START = 1_000.0

# The faded Lobby on a start: only the character's speech bubble reads.
FADED_BUBBLE = [("oh, I was writing a poem. t's my hobby.", 0.258, 0.278)]
# The Lobby after the wake, and again after four back arrows from The Blue Pot's detail.
LOBBY = [("等级", 0.054, 0.049), ("N", 0.136, 0.032), ("61%", 0.106, 0.084), ("16/240÷", 0.704, 0.049), ("E", 0.834, 0.048), ("N", 0.972, 0.03),
         ("FT", 0.777, 0.076), ("★", 0.778, 0.055), ("F2", 0.835, 0.077), ("F3", 0.898, 0.076), ("Q", 0.959, 0.076), ("故事", 0.884, 0.156),
         ("Act", 0.744, 0.195), ("1-Chapter 2, Episode 2", 0.834, 0.194), ("ility", 0.057, 0.234), ("0/1", 0.064, 0.262), ("Learn 1 time", 0.201, 0.234),
         ("Sortie", 0.884, 0.266), ("CAC>0", 0.898, 0.292), ("O8d 21h", 0.049, 0.332), ("Simulation", 0.875, 0.354), ("Nightmare Carnival", 0.101, 0.396),
         ("N", 0.048, 0.439), ("Chaos", 0.891, 0.442), ("F4", 0.035, 0.5), ("Awaiting policies 3", 0.854, 0.555), ("方舟城市", 0.883, 0.521),
         ("Combatants", 0.868, 0.617), ("EVENT", 0.822, 0.704), ("营救", 0.886, 0.705), ("N", 0.049, 0.736), ("29d21h", 0.922, 0.832),
         ("CORONOMICON", 0.142, 0.887), ("GIFT", 0.165, 0.921), ("Uponthe SnW", 0.889, 0.925), ("APromrse", 0.894, 0.887)]
LOBBY_BACK = [("等级", 0.054, 0.05), ("21", 0.053, 0.089), ("N", 0.136, 0.032), ("20/240+", 0.703, 0.049), ("N", 0.972, 0.03), ("F1", 0.775, 0.075),
              ("★", 0.777, 0.056), ("61%", 0.106, 0.084), ("F2", 0.835, 0.076), ("F3", 0.898, 0.076), ("Q", 0.959, 0.076), ("故事", 0.884, 0.156),
              ("Act", 0.744, 0.195), ("-Chapter 2, Episode 2", 0.839, 0.194), ("me(s) at the Ark City Researcl", 0.145, 0.234), ("0/1", 0.064, 0.262),
              ("Sortie", 0.884, 0.266), ("O8d 21h", 0.05, 0.331), ("口", 0.19, 0.325), ("Simulation", 0.874, 0.353), ("Nightmare Carnival", 0.101, 0.396),
              ("Chaos", 0.891, 0.442), ("F4", 0.035, 0.5), ("Awaiting policies 3", 0.854, 0.555), ("方舟城市", 0.883, 0.521), ("Combatants", 0.868, 0.617),
              ("6", 0.951, 0.651), ("EVENT", 0.822, 0.704), ("营救", 0.887, 0.703), ("N", 0.049, 0.736), ("·C4>", 0.898, 0.73), ("29d 21h", 0.924, 0.832),
              ("Blazebell", 0.148, 0.925), ("Rate up", 0.162, 0.892), ("UpontheSnW", 0.89, 0.925), ("APromrse", 0.894, 0.887)]
# The Chaos hub, on the way in and on the way back out.
HUB = [("Chaos", 0.112, 0.047), ("HECOC1-22C-L0", 0.095, 0.155), ("卡厄思显现", 0.244, 0.8), ("零式系统", 0.71, 0.801)]
HUB_BACK = [("Chaos", 0.112, 0.047), ("HECOCI-221-C-L0", 0.095, 0.155), ("卡厄思显现", 0.245, 0.801), ("零式系统", 0.71, 0.801)]
# The Chaos Manifestation map, on the way in and on the way back out.
MAP = [("卡厄思显现", 0.176, 0.047), ("0/4+", 0.838, 0.049), ("N", 0.973, 0.031), ("Content Introduction", 0.881, 0.136), ("Chaos", 0.499, 0.344),
       ("Unconfirmed", 0.52, 0.31), ("2.", 0.873, 0.306), ("Chaos", 0.92, 0.345), ("Unconfirmed", 0.941, 0.309), ("The Blue Pot", 0.32, 0.676),
       ("?", 0.663, 0.679), ("Unconfirmed", 0.731, 0.679), ("Exploration: 14", 0.305, 0.729), ("Chaos", 0.709, 0.715), ("Small", 0.268, 0.767),
       ("Chaos Size", 0.866, 0.922)]
MAP_BACK = [("卡厄思显现", 0.176, 0.047), ("0/4+", 0.838, 0.049), ("N", 0.973, 0.031), ("Content Introduction", 0.881, 0.136), ("Chaos", 0.499, 0.344),
            ("Unconfirmed", 0.52, 0.31), ("2.", 0.873, 0.306), ("Chaos", 0.92, 0.345), ("Unconfirmed", 0.941, 0.309), ("The Blue Pot", 0.32, 0.676),
            ("?", 0.663, 0.678), ("Unconfirmed", 0.731, 0.679), ("Exploration: 15", 0.304, 0.728), ("Chaos", 0.709, 0.715), ("Small", 0.268, 0.767),
            ("Chaos Size", 0.866, 0.922)]
# The Blue Pot's detail, on the way in and on the way back out.
DETAIL = [("卡厄思显现", 0.176, 0.045), ("0/4+", 0.84, 0.047), ("The Blue Pot", 0.76, 0.215), ("0", 0.967, 0.252),
          ("· A street in a city completely consumed", 0.833, 0.348), ("by Chaos.", 0.744, 0.381), ("· [Alert] The Chaos Order is inhabiting", 0.828, 0.491),
          ("[Alert] Mutants are inhabiting this area.", 0.835, 0.448), ("this area.", 0.741, 0.522), ("ExplorationLv. 14", 0.115, 0.901),
          ("Reward Info", 0.334, 0.9), ("进入", 0.935, 0.899)]
DETAIL_BACK = [("卡厄思显现", 0.175, 0.045), ("0/4+", 0.839, 0.047), ("N", 0.973, 0.031), ("The Blue Pot", 0.76, 0.215), ("0", 0.967, 0.252),
               ("· A street in a city completely consumed", 0.833, 0.348), ("by Chaos.", 0.744, 0.381), ("· [Alert] The Chaos Order is inhabiting", 0.828, 0.49),
               ("[Alert] Mutants are inhabiting this area.", 0.835, 0.448), ("this area.", 0.74, 0.522), ("Exploration Lv. 15", 0.115, 0.901),
               ("口", 0.391, 0.865), ("Reward Info", 0.334, 0.901), ("进入", 0.935, 0.899)]
# The Team Formation the detail's Enter opens.
FORMATION = [("主战员配置", 0.155, 0.045), ("0/4+", 0.962, 0.047), ("卡厄思显现", 0.76, 0.103), ("The Blue Pot", 0.744, 0.154), ("Q", 0.272, 0.239),
             ("Difficulty", 0.831, 0.214), ("日", 0.946, 0.266), ("推荐", 0.74, 0.376), ("LV.5", 0.908, 0.375), ("Monsters That Appear", 0.762, 0.438),
             ("LV.5", 0.928, 0.436), ("Q", 0.969, 0.433), ("Available Loot", 0.738, 0.607), ("Q", 0.968, 0.605), ("First", 0.832, 0.654),
             ("First", 0.899, 0.654), ("First", 0.967, 0.654), ("200", 0.73, 0.735), ("150", 0.802, 0.736), ("400", 0.866, 0.735), ("40", 0.935, 0.735),
             ("20", 0.056, 0.8), ("等级", 0.057, 0.765), ("20", 0.27, 0.8), ("等级", 0.271, 0.766), ("20", 0.485, 0.8), ("等级", 0.484, 0.766),
             ("存储数据保存上限", 0.789, 0.814), ("100pt", 0.946, 0.813), ("Preset", 0.142, 0.918), ("0.g", 0.247, 0.916), ("の", 0.318, 0.915),
             ("免费", 0.645, 0.912), ("Delegate4", 0.735, 0.912), ("进入", 0.945, 0.913)]
# The prompt a Chaos run still open raises on the way in. Escape abandons the run.
RESUME = [("53%", 0.501, 0.508), ("9/17", 0.500, 0.563), ("卡厄思显现", 0.501, 0.677), ("The Blue Pot", 0.502, 0.728),
          ("Do you wish'to enter the stage in progress?", 0.501, 0.828), ("取消", 0.369, 0.907), ("进入", 0.637, 0.907), ("Escape", 0.898, 0.910)]
RESUME_LINE = "Do you wish'to enter the stage in progress?"
ESCAPE = (0.898, 0.910)
CANCEL = (0.369, 0.907)
NO_FRAME = None


class Clock:
    """Monotonic time the test moves by hand."""

    def __init__(self):
        self.now = START

    def monotonic(self):
        return self.now


class Mode:
    """A mode looking at one screen, recording where it taps, what it says and whether it stopped."""

    def __init__(self, texts=(), frame=NO_FRAME):
        self.name = "自动卡厄思模式"
        self.width, self.height = WIDTH, HEIGHT
        self.clicks = []
        self.logged = []
        self.notifications = []
        self.stops = 0
        self.show(texts, frame)

    def show(self, texts, frame=NO_FRAME):
        self.all_texts = [FakeBox(text, x, y) for text, x, y in texts]
        self.frame = frame
        return self

    def move_relative(self, x, y):
        pass

    def sleep(self, seconds):
        pass

    def click(self, x, y, after_sleep=0):
        self.clicks.append((round(x, 3), round(y, 3)))

    def click_box(self, box):
        self.clicks.append(tuple(round(value, 3) for value in centre_of(box, self.width, self.height)))

    def find_one(self, *args, **kwargs):
        return None

    def box_of_screen(self, *args):
        return args

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.stops += 1


class ChaosMode(Mode):
    pass


class SortieMode(Mode):
    pass


def without(texts, name):
    return [entry for entry in texts if entry[0] != name]


def moved(texts, name, x, y):
    return [(text, x, y) if text == name else (text, x_, y_) for text, x_, y_ in texts]


def black():
    return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)


class WalkCase(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        patcher = mock.patch.object(chaos_entry, "time", types.SimpleNamespace(monotonic=self.clock.monotonic))
        patcher.start()
        self.addCleanup(patcher.stop)

    def assertStopped(self, task, phrase):
        self.assertEqual(1, task.stops)
        self.assertEqual(1, len(task.notifications))
        self.assertIn(phrase, task.notifications[0])
        self.assertTrue(task.notifications[0].isascii())


class TestLobby(WalkCase):
    """The Lobby, where upstream stopped Chaos at once."""

    def test_the_lobby_s_chaos_caption_is_pressed(self):
        for label, texts, spot in (("after the wake", LOBBY, (0.891, 0.442)), ("after the back arrows", LOBBY_BACK, (0.891, 0.442)),
                                   ("icon read as a glyph", LOBBY_ICON_READ, (0.883, 0.44))):
            with self.subTest(label):
                task = ChaosMode(texts)
                self.assertTrue(chaos_entry.handle_chaos_lobby(task))
                self.assertEqual([spot], task.clicks)
                self.assertEqual(0, task.stops)

    def test_without_the_caption_nothing_is_pressed_and_upstream_s_stop_says_the_walk_could_not_go_on(self):
        task = ChaosMode(without(LOBBY, "Chaos"))
        self.assertFalse(chaos_entry.handle_chaos_lobby(task))
        self.assertTrue(notify.lobby_stop(utils)(utils.handle_non_battle_page)(task))
        self.assertEqual([], task.clicks)
        self.assertEqual([notify.LOBBY_STOPS["ChaosMode"]], task.notifications)
        self.assertIn("could not open The Blue Pot from the Lobby", task.notifications[0])

    def test_the_caption_is_read_only_in_its_place_on_the_lobby(self):
        task = ChaosMode(moved(LOBBY, "Chaos", 0.891, 0.50))
        self.assertFalse(chaos_entry.handle_chaos_lobby(task))
        self.assertEqual([], task.clicks)

    def test_only_chaos_alone_or_behind_one_icon_glyph_reads_as_the_caption(self):
        for text in ("Chaos", "日 Chaos", "θ Chaos", "CHAOS"):
            with self.subTest(text):
                self.assertTrue(chaos_entry.reads_chaos(text))
        for text in ("Unconfirmed Chaos", "Chaos Size", "x Chaos", "Chaoss", "日日 Chaos", ""):
            with self.subTest(text):
                self.assertFalse(chaos_entry.reads_chaos(text))

    def test_a_relayed_run_never_walks_and_upstream_s_stop_follows(self):
        task = ChaosMode(LOBBY)
        setattr(task, RELAYED, True)
        self.assertFalse(chaos_entry.handle_chaos_lobby(task))
        self.assertTrue(notify.lobby_stop(utils)(utils.handle_non_battle_page)(task))
        self.assertEqual([], task.clicks)
        self.assertEqual(1, task.stops)
        self.assertEqual([notify.LOBBY_STOPS["ChaosMode"]], task.notifications)

    def test_no_other_mode_walks(self):
        for handler, texts in ((chaos_entry.handle_chaos_lobby, LOBBY), (chaos_entry.handle_chaos_hub, HUB),
                               (chaos_entry.handle_manifestation_planet, MAP), (chaos_entry.handle_resume_prompt, RESUME)):
            with self.subTest(handler.__name__):
                task = SortieMode(texts)
                self.assertFalse(handler(task))
                self.assertEqual([], task.clicks)


class TestFadedLobby(WalkCase):
    """A start on an idle Lobby whose UI has faded out, its character's speech bubble still reading."""

    def test_the_faded_lobby_with_a_speech_bubble_gets_the_wake_tap(self):
        for crop in ("daily_faded_lobby", "daily_faded_lobby_character"):
            with self.subTest(crop):
                task = ChaosMode(FADED_BUBBLE, faded_lobby(crop))
                self.assertTrue(chaos_entry.handle_chaos_faded_lobby(task))
                self.assertEqual([daily.TARGETS[daily.WAKE]], task.clicks)
                self.assertEqual([(0.3, 0.42)], task.clicks)

    def test_the_wake_waits_for_the_ui_before_tapping_again(self):
        task = ChaosMode(FADED_BUBBLE, faded_lobby())
        self.assertTrue(chaos_entry.handle_chaos_faded_lobby(task))
        self.clock.now += daily.WAKE_WAIT - 1
        self.assertTrue(chaos_entry.handle_chaos_faded_lobby(task))
        self.assertEqual(1, len(task.clicks))
        self.clock.now += 1
        self.assertTrue(chaos_entry.handle_chaos_faded_lobby(task))
        self.assertEqual(2, len(task.clicks))

    def test_a_low_confidence_scrap_beside_the_bubble_still_counts_as_faded(self):
        task = ChaosMode(FADED_BUBBLE + [("rort", 0.083, 0.531)], faded_lobby())
        task.all_texts[-1].confidence = 0.585
        self.assertTrue(chaos_entry.handle_chaos_faded_lobby(task))
        self.assertEqual(1, len(task.clicks))

    def test_a_frame_without_the_faded_scene_gets_no_tap(self):
        frames = {"black": black(), "no capture": NO_FRAME}
        frames.update({name: placed(name, SCENE_REGION) for name in ("daily_blank_cutscene", "daily_blank_rescue_flash", "daily_blank_carnival",
                                                                     "daily_scene_under_dialogue")})
        for name, frame in frames.items():
            for texts in ((), FADED_BUBBLE):
                with self.subTest(frame=name, texts=len(texts)):
                    task = ChaosMode(texts, frame)
                    self.assertFalse(chaos_entry.handle_chaos_faded_lobby(task))
                    self.assertEqual([], task.clicks)

    def test_the_faded_scene_under_more_text_than_a_bubble_gets_no_tap(self):
        for label, texts in (("the Lobby", LOBBY), ("two lines", FADED_BUBBLE + [("Loading", 0.5, 0.5)]),
                             ("a caption where the Lobby writes them", [("Combatants", 0.868, 0.617)])):
            with self.subTest(label):
                task = ChaosMode(texts, faded_lobby())
                self.assertFalse(chaos_entry.handle_chaos_faded_lobby(task))
                self.assertEqual([], task.clicks)


class TestHub(WalkCase):
    """The Chaos hub the Lobby's Chaos opens."""

    def test_chaos_manifestation_is_pressed_and_zero_system_never(self):
        for label, texts, spot in (("on the way in", HUB, (0.244, 0.8)), ("on the way out", HUB_BACK, (0.245, 0.801))):
            with self.subTest(label):
                task = ChaosMode(texts)
                self.assertTrue(chaos_entry.handle_chaos_hub(task))
                self.assertEqual([spot], task.clicks)
                self.assertNotIn((0.71, 0.801), task.clicks)

    def test_the_title_and_the_card_are_both_needed(self):
        for name in ("Chaos", "卡厄思显现"):
            with self.subTest(missing=name):
                task = ChaosMode(without(HUB, name))
                self.assertFalse(chaos_entry.handle_chaos_hub(task))
                self.assertEqual([], task.clicks)

    def test_a_card_read_elsewhere_is_not_pressed(self):
        task = ChaosMode(moved(HUB, "卡厄思显现", 0.71, 0.70))
        self.assertFalse(chaos_entry.handle_chaos_hub(task))
        self.assertEqual([], task.clicks)


class TestManifestationMap(WalkCase):
    """The map Chaos Manifestation opens, and The Blue Pot's detail the planet opens."""

    def test_the_blue_pot_is_pressed(self):
        for label, texts in (("on the way in", MAP), ("on the way out", MAP_BACK)):
            with self.subTest(label):
                task = ChaosMode(texts)
                self.assertTrue(chaos_entry.handle_manifestation_planet(task))
                self.assertEqual([(0.32, 0.676)], task.clicks)

    def test_the_detail_is_left_to_handle_enter_which_presses_its_enter(self):
        handle_enter = enter.on_the_button(utils)(pressing("handle_enter"))
        for label, texts in (("on the way in", DETAIL), ("on the way out", DETAIL_BACK)):
            with self.subTest(label):
                task = ChaosMode(texts)
                self.assertFalse(chaos_entry.handle_manifestation_planet(task))
                self.assertTrue(handle_enter(task))
                self.assertEqual([(0.935, 0.899)], task.clicks)

    def test_a_detail_still_drawing_its_enter_is_neither_pressed_nor_stopped_on(self):
        task = ChaosMode(without(DETAIL, "进入"))
        self.assertFalse(chaos_entry.handle_manifestation_planet(task))
        self.assertEqual([], task.clicks)
        self.assertEqual(0, task.stops)

    def test_a_map_without_the_blue_pot_stops_with_nothing_pressed(self):
        task = ChaosMode(without(MAP, "The Blue Pot"))
        self.assertTrue(chaos_entry.handle_manifestation_planet(task))
        self.assertEqual([], task.clicks)
        self.assertStopped(task, "could not find The Blue Pot on the Chaos Manifestation map")


class TestResumePrompt(WalkCase):
    """The prompt to enter a run still open, whose Escape abandons the run."""

    def test_only_enter_is_pressed(self):
        task = ChaosMode(RESUME)
        self.assertTrue(chaos_entry.handle_resume_prompt(task))
        self.assertEqual([(0.637, 0.907)], task.clicks)
        self.assertIn("a Chaos run is still open, entering it again", task.logged)

    def test_escape_and_cancel_are_never_pressed(self):
        escape = next(box for box in ChaosMode(RESUME).all_texts if box.name == "Escape")
        cancel = next(box for box in ChaosMode(RESUME).all_texts if box.name == "取消")
        for label, texts in (("as read", RESUME), ("no Enter", without(RESUME, "进入")), ("Enter where Escape is", moved(RESUME, "进入", *ESCAPE)),
                             ("Enter where Cancel is", moved(without(RESUME, "取消"), "进入", *CANCEL))):
            with self.subTest(label):
                task = ChaosMode(texts)
                for _ in range(chaos_entry.TAP_LIMIT + 1):
                    chaos_entry.handle_resume_prompt(task)
                for x, y in task.clicks:
                    for box in (escape, cancel):
                        self.assertFalse(box.x <= x * WIDTH <= box.x + box.width and box.y <= y * HEIGHT <= box.y + box.height)
                    self.assertLess(x, 0.75)

    def test_with_its_line_read_and_its_enter_not_the_prompt_is_held_with_nothing_pressed(self):
        for label, texts in (("no Enter", without(RESUME, "进入")), ("Enter where Escape is", moved(RESUME, "进入", *ESCAPE))):
            with self.subTest(label):
                task = ChaosMode(texts)
                self.assertTrue(chaos_entry.handle_resume_prompt(task))
                self.assertEqual([], task.clicks)
                self.assertEqual(0, task.stops)

    def test_without_its_line_nothing_is_pressed(self):
        task = ChaosMode(without(RESUME, RESUME_LINE))
        self.assertFalse(chaos_entry.handle_resume_prompt(task))
        self.assertEqual([], task.clicks)

    def test_the_map_handler_never_takes_the_prompt_even_over_the_map_s_title(self):
        for label, texts in (("as read", RESUME), ("map title under it", RESUME + [("卡厄思显现", 0.176, 0.047), ("Content Introduction", 0.881, 0.136)])):
            with self.subTest(label):
                task = ChaosMode(texts)
                self.assertFalse(chaos_entry.handle_manifestation_planet(task))
                self.assertEqual([], task.clicks)
                self.assertEqual(0, task.stops)

    def test_a_relayed_run_is_left_to_upstream(self):
        task = ChaosMode(RESUME)
        setattr(task, RELAYED, True)
        self.assertFalse(chaos_entry.handle_resume_prompt(task))
        self.assertEqual([], task.clicks)


class TestPress(WalkCase):
    """Every walk press is counted and checked against what lies under it."""

    def test_a_fourth_press_of_one_target_stops_with_its_name(self):
        task = ChaosMode(LOBBY)
        for _ in range(chaos_entry.TAP_LIMIT):
            self.assertTrue(chaos_entry.handle_chaos_lobby(task))
        self.assertEqual(chaos_entry.TAP_LIMIT, len(task.clicks))
        self.assertTrue(chaos_entry.handle_chaos_lobby(task))
        self.assertEqual(chaos_entry.TAP_LIMIT, len(task.clicks))
        self.assertStopped(task, "Chaos pressed the Lobby's Chaos 3 times and the screen did not move on")

    def test_each_target_counts_on_its_own(self):
        task = ChaosMode(LOBBY)
        for texts, handler in ((LOBBY, chaos_entry.handle_chaos_lobby), (HUB, chaos_entry.handle_chaos_hub),
                               (MAP, chaos_entry.handle_manifestation_planet), (RESUME, chaos_entry.handle_resume_prompt)) * chaos_entry.TAP_LIMIT:
            self.assertTrue(handler(task.show(texts)))
        self.assertEqual(4 * chaos_entry.TAP_LIMIT, len(task.clicks))
        self.assertEqual(0, task.stops)

    def test_a_refused_word_under_the_point_stops_without_a_tap(self):
        for word in ("Spend 1600 Crystals to make the purchase?", "Shop"):
            with self.subTest(word):
                task = ChaosMode(LOBBY + [(word, 0.891, 0.442)])
                self.assertTrue(chaos_entry.handle_chaos_lobby(task))
                self.assertEqual([], task.clicks)
                self.assertStopped(task, "Chaos would have pressed")

    def test_every_start_and_stop_forgets_the_walk(self):
        class Task:
            def enable(self):
                return "enabled"

            def disable(self):
                return "disabled"

        registered = []
        with mock.patch.object(chaos_entry, "_patched", False), mock.patch.object(chaos_entry, "register", registered.append), \
                mock.patch("ok.task.task.BaseTask", Task):
            chaos_entry.apply()
        self.assertEqual([chaos_entry.install], registered)
        for method in ("enable", "disable"):
            with self.subTest(method):
                task = Task()
                vars(task).update({chaos_entry.TAPS: {"x": 3}, chaos_entry.WOKEN: START})
                self.assertEqual(f"{method}d", getattr(task, method)())
                self.assertNotIn(chaos_entry.TAPS, vars(task))
                self.assertNotIn(chaos_entry.WOKEN, vars(task))


def pressing(name):
    """Stand in for an upstream handler that presses the first box it is shown, as `handle_enter` presses its button."""
    def handler(task):
        task.click_box(task.all_texts[0])
        return True
    handler.__name__ = name
    return handler


def recording(name, reached):
    """Stand in for an upstream handler under its name, recording when a frame reaches it and declining it."""
    def handler(task):
        reached.append(name)
        return False
    handler.__name__ = name
    return handler


def installed_lists():
    """Run every handler-list edit the app registers on copies of the real modes, three times over.

    Returns:
        Each copied mode's handler names, by module name.
    """
    real = {name: sys.modules[name] for name, _ in handlers.each_list()}
    real.update({name: sys.modules[name] for name in ("utils", "utils_chaos", "utils_sortie", "utils_story", daily.__name__)})
    copies = {name: stand_in(module) for name, module in real.items()}
    with mock.patch.dict(sys.modules, copies):
        for _ in range(INSTALLS):
            for install in registered_installs():
                install()
    return {name: [handler.__name__ for handler in copy.PAGE_HANDLERS] for name, copy in copies.items() if hasattr(copy, handlers.HANDLER_LIST)}


WALK = [handler.__name__ for handler in chaos_entry.HANDLERS]


class TestInstall(WalkCase):
    """The walk sits in Chaos's list only, once, behind the stops and the hold and ahead of every handler that taps."""

    @classmethod
    def setUpClass(cls):
        cls.lists = installed_lists()

    def test_chaos_gains_the_walk_once_just_ahead_of_the_close_page_tap(self):
        names = self.lists["utils_chaos"]
        for name in WALK:
            self.assertEqual(1, names.count(name))
        start = names.index(WALK[0])
        self.assertEqual(WALK + [chaos_entry.ANCHOR], names[start:start + len(WALK) + 1])
        for earlier in ("handle_remote", "stop_when_stuck", "handle_auto_stop", "handle_stuck_log_announcing"):
            with self.subTest(earlier):
                self.assertLess(names.index(earlier), start)
        for later in ("handle_center_confirm", "handle_non_battle_page", "handle_enter", "handle_escape"):
            with self.subTest(later):
                self.assertGreater(names.index(later), start)

    def test_no_other_mode_gains_any_of_it(self):
        for module, names in self.lists.items():
            if module == "utils_chaos":
                continue
            with self.subTest(module):
                self.assertEqual([], [name for name in names if name in WALK])

    def test_each_screen_on_the_way_in_is_claimed_by_its_own_handler_and_nothing_after_it_runs(self):
        live = {handler.__name__: handler for handler in chaos_entry.HANDLERS}
        for label, texts, frame, claimant, spot in (
                ("faded Lobby", FADED_BUBBLE, faded_lobby(), "handle_chaos_faded_lobby", (0.3, 0.42)),
                ("Lobby", LOBBY, NO_FRAME, "handle_chaos_lobby", (0.891, 0.442)),
                ("hub", HUB, NO_FRAME, "handle_chaos_hub", (0.244, 0.8)),
                ("map", MAP, NO_FRAME, "handle_manifestation_planet", (0.32, 0.676)),
                ("resume prompt", RESUME, NO_FRAME, "handle_resume_prompt", (0.637, 0.907)),
                ("detail", DETAIL, NO_FRAME, "handle_enter", (0.935, 0.899)),
                ("formation", FORMATION, NO_FRAME, "handle_enter", (0.945, 0.913))):
            with self.subTest(label):
                reached = []
                chain = []
                for name in self.lists["utils_chaos"]:
                    if name in live:
                        chain.append(live[name])
                    elif name == "handle_enter":
                        chain.append(enter.on_the_button(utils)(pressing(name)))
                    else:
                        chain.append(recording(name, reached))
                task = ChaosMode(texts, frame)
                claimed = next((handler.__name__ for handler in chain if handler(task)), None)
                self.assertEqual(claimant, claimed)
                self.assertEqual([spot], task.clicks)
                names = self.lists["utils_chaos"]
                after = names[names.index(claimant) + 1:]
                self.assertEqual([], [name for name in reached if name in after])

    def test_chaos_entry_is_applied_after_the_enter_change_and_before_notify(self):
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertLess(applied.index("route"), applied.index("chaos_entry"))
        self.assertLess(applied.index("enter"), applied.index("chaos_entry"))
        self.assertLess(applied.index("chaos_entry"), applied.index("notify"))


class TestOtherScreens(WalkCase):
    """No screen of a run, and no other Chaos screen, is taken for one on the way in."""

    def test_no_walk_handler_takes_any_of_them(self):
        screens = {**OTHER_SCREENS, "Entry Guide": ENTRY_GUIDE, "record notice": RECORD_CARD, "record Encouragement": RECORD_ENCOURAGEMENT,
                   "formation": FORMATION, "detail": DETAIL}
        for label, texts in screens.items():
            for frame_label, frame in (("no capture", NO_FRAME), ("black", black())):
                for handler in chaos_entry.HANDLERS:
                    with self.subTest(screen=label, frame=frame_label, handler=handler.__name__):
                        task = ChaosMode(texts, frame)
                        self.assertFalse(handler(task))
                        self.assertEqual([], task.clicks)
                        self.assertEqual(0, task.stops)


if __name__ == "__main__":
    unittest.main()
