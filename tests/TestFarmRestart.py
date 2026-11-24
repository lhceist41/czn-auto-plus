"""Check that Farm Gaps and Farm Starting Card never tap a Chaos run's menu, or the start page's Adaptation Distortion switch.

Upstream restarts the run through its menu when the starting event lacks the wanted option, and matches the option by
its Chinese wording. The Global client shows no such event and writes in English, so the tap only opened Chaos Info,
where the run sat until the stuck stop. Each check runs upstream's own handler, bare as the control and as the fork wraps it.
"""

import inspect
import json
import os
import re
import subprocess
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
import utils_chaos  # noqa: E402

from src.en import farm_restart, handlers  # noqa: E402
from src.en.farm_restart import FARM_GAPS, STARTING_CARD  # noqa: E402
from src.en.handlers import WRAPS, standing_in  # noqa: E402
from tests.TestSpendGuard import RESUME  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

# The run menu's button, where upstream's restart taps land.
MENU_TAP = (0.96, 0.053)
# The two options of an event a resumed Global run met, as upstream read their descriptions, with their icons' centres.
GLOBAL_EVENT = (("Examine the ghoul's enclosureEvent Encounter: Key FoundDecrease Health by 20%,", 0.361, 0.95),
                ("Pass byEnd the event", 0.573, 0.95))
CARDS = [{"name": "Strike", "x": 0.30, "y": 0.45}, {"name": "Defend", "x": 0.50, "y": 0.45}, {"name": "Rally", "x": 0.70, "y": 0.45}]
SKIP = ("跳过", 0.80, 0.93)
SWITCH = (0.575, 0.093)
# The start page's switch while Adaptation Distortion is on, as upstream checks it, in RGB.
SWITCH_ON = (255, 186, 55)
EVERY_SETTING = {FARM_GAPS: True, STARTING_CARD: "Rally", "只打第一层": True, "首层刷特定闪光": True}
ROUND_BUTTON = (0.90, 0.85, 1.0, 1.0)


class FakeTask:
    """A Chaos run at its first node, recording every tap and line."""

    def __init__(self, config, texts=()):
        self.name = "自动卡厄思模式"
        self.width, self.height = WIDTH, HEIGHT
        self.config = dict(config)
        self.node_status = utils._initial_node_status()
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        self.taps = []
        self.logged = []

    def find_feature(self, *args, **kwargs):
        return []

    def find_one(self, *args, **kwargs):
        return None

    def box_of_screen(self, *region):
        return region

    def move_relative(self, x, y):
        pass

    def click(self, x, y, *args, **kwargs):
        self.taps.append((round(x, 3), round(y, 3)))

    def click_box(self, box, *args, **kwargs):
        self.taps.append(box.name)

    def sleep(self, seconds):
        pass

    def log_info(self, message, notify=False):
        self.logged.append(message)


def event_options(task, *args, **kwargs):
    """Give the Global event's options the way `recognize_event_options` returns them."""
    return [{"x": x, "y": y, "description": description, "feature_name": "event3", "confidence": 0.95,
             "description_region": (x - 0.119, y - 0.208, x + 0.122, y - 0.021)} for description, x, y in GLOBAL_EVENT]


def option_centres():
    """Give where upstream taps to take each option: the centre of its description."""
    centres = []
    for option in event_options(None):
        left, top, right, bottom = option["description_region"]
        centres.append((round((left + right) / 2, 3), round((top + bottom) / 2, 3)))
    return centres


def menu_tapped(task):
    """Say whether any tap landed on the run menu's button."""
    return any(isinstance(tap, tuple) and abs(tap[0] - MENU_TAP[0]) <= 0.01 and abs(tap[1] - MENU_TAP[1]) <= 0.01 for tap in task.taps)


def said(task):
    """Count the lines saying a setting cannot restart a run."""
    return sum("cannot restart a run on the Global client yet" in line for line in task.logged)


def show_event(config, wrapped=True, task=None):
    """Show the Global event to upstream's event handler.

    Args:
        config: The saved settings.
        wrapped: Whether the fork's change is on.
        task: A task to reuse, or None for a fresh one.

    Returns:
        The task and the handler's answer.
    """
    task = task or FakeTask(config)
    handler = utils.handle_event_task
    if wrapped:
        handler = farm_restart.playing_on(utils, *farm_restart.RESTART_BRANCHES["handle_event_task"])(handler)
    with standing_in(utils, recognize_event_options=event_options):
        return task, handler(task)


def show_card_reward(config, cards=CARDS, wrapped=True):
    """Show a Card Reward to upstream's handler.

    Args:
        config: The saved settings.
        cards: The cards on offer.
        wrapped: Whether the fork's change is on.

    Returns:
        The task and the handler's answer.
    """
    task = FakeTask(config, texts=[("卡牌奖励", 0.5, 0.07), SKIP])
    handler = utils.handle_card_reward
    if wrapped:
        handler = farm_restart.playing_on(utils, *farm_restart.RESTART_BRANCHES["handle_card_reward"])(handler)
    with standing_in(utils, recognize_cards=lambda task_, *args, **kwargs: [dict(card) for card in cards]):
        return task, handler(task)


def show_start_page(config, wrapped=True):
    """Show the Chaos start page with Adaptation Distortion switched on to upstream's handler.

    Args:
        config: The saved settings.
        wrapped: Whether the fork's change is on.

    Returns:
        The task and the handler's answer.
    """
    task = FakeTask(config, texts=[("适应畸变", 0.526, 0.093)])
    x, y = round(SWITCH[0] * WIDTH), round(SWITCH[1] * HEIGHT)
    task.frame[y, x] = SWITCH_ON[::-1]
    handler = utils_chaos.handle_disable_adaptation_distortion
    if wrapped:
        handler = farm_restart.leaving_adaptation_distortion(utils_chaos)(handler)
    return task, handler(task)


class TestEventScreen(unittest.TestCase):

    def test_neither_setting_taps_the_menu_and_the_run_takes_an_option(self):
        for config in ({FARM_GAPS: True}, {STARTING_CARD: "Rally"}, {FARM_GAPS: True, STARTING_CARD: "Rally"}):
            with self.subTest(config=config):
                task, answer = show_event(config)
                self.assertIs(True, answer)
                self.assertFalse(menu_tapped(task), task.taps)
                self.assertEqual(1, len(task.taps))
                self.assertIn(task.taps[0], option_centres())
                self.assertEqual(len(config), said(task))

    def test_bare_upstream_taps_the_menu_on_the_same_screen(self):
        """The control: the frame is one upstream restarts on, so a pass without the menu tap means something."""
        for config in ({FARM_GAPS: True}, {STARTING_CARD: "Rally"}):
            with self.subTest(config=config):
                task, answer = show_event(config, wrapped=False)
                self.assertIs(True, answer)
                self.assertEqual([MENU_TAP], [(round(x, 2), round(y, 3)) for x, y in task.taps])

    def test_with_both_settings_off_nothing_is_said_and_the_menu_is_left_alone(self):
        task, answer = show_event({FARM_GAPS: False, STARTING_CARD: ""})
        self.assertIs(True, answer)
        self.assertFalse(menu_tapped(task))
        self.assertEqual(0, said(task))

    def test_it_is_said_once_per_run(self):
        task, _ = show_event({FARM_GAPS: True})
        show_event({}, task=task)
        task.node_status["node_count"] = 3
        show_event({}, task=task)
        self.assertEqual(1, said(task))
        # The next floor, after the first boss.
        task.node_status["pass_final_boss_count"] = 1
        utils.reset_layer_status(task)
        show_event({}, task=task)
        self.assertEqual(1, said(task))
        # The next run.
        utils.reset_mission_status(task)
        show_event({}, task=task)
        self.assertEqual(2, said(task))
        self.assertFalse(menu_tapped(task))


class TestCardReward(unittest.TestCase):

    def test_a_reward_without_the_starting_card_is_skipped_rather_than_restarted(self):
        task, answer = show_card_reward({STARTING_CARD: "Bash"})
        self.assertIs(True, answer)
        self.assertEqual(["跳过"], task.taps)
        self.assertEqual(1, said(task))

    def test_bare_upstream_taps_the_menu_on_the_same_reward(self):
        task, answer = show_card_reward({STARTING_CARD: "Bash"}, wrapped=False)
        self.assertIs(True, answer)
        self.assertTrue(menu_tapped(task), task.taps)

    def test_the_starting_card_still_heads_the_reward_priority(self):
        task, answer = show_card_reward({STARTING_CARD: "Rally"})
        self.assertIs(True, answer)
        self.assertEqual([(0.7, 0.45)], task.taps)
        self.assertTrue(any("Rally" in line for line in task.logged))


class TestStartPage(unittest.TestCase):

    def test_farm_gaps_leaves_adaptation_distortion_switched_on(self):
        task, answer = show_start_page({FARM_GAPS: True})
        self.assertIs(False, answer)
        self.assertEqual([], task.taps)
        self.assertEqual(1, said(task))

    def test_bare_upstream_switches_it_off(self):
        task, answer = show_start_page({FARM_GAPS: True}, wrapped=False)
        self.assertIs(False, answer)
        self.assertEqual([SWITCH], task.taps)

    def test_with_farm_gaps_off_upstream_runs_as_before(self):
        task, answer = show_start_page({FARM_GAPS: False})
        self.assertIs(False, answer)
        self.assertEqual([], task.taps)
        self.assertEqual(0, said(task))


class TestInstall(unittest.TestCase):

    def test_each_change_lands_once_on_the_module_and_in_the_lists(self):
        utils_copy = types.ModuleType("utils")
        utils_copy.__dict__.update(vars(utils))
        chaos_copy = types.ModuleType("utils_chaos")
        chaos_copy.__dict__.update(vars(utils_chaos))
        mode = types.ModuleType("fake_chaos_for_farm_restart_test")
        mode.PAGE_HANDLERS = [utils.handle_event_task, utils.handle_card_reward, utils_chaos.handle_disable_adaptation_distortion]
        # `wrap` swaps the handler in every loaded list, the real modes' too, which the shared test process must get back.
        saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        try:
            with mock.patch.dict(sys.modules, {"utils": utils_copy, "utils_chaos": chaos_copy, mode.__name__: mode}):
                for _ in range(3):
                    farm_restart.install()
        finally:
            for entries, before in saved:
                entries[:] = before
        for module, name in ((utils_copy, "handle_event_task"), (utils_copy, "handle_card_reward"),
                             (chaos_copy, "handle_disable_adaptation_distortion")):
            with self.subTest(handler=name):
                handler = getattr(module, name)
                self.assertEqual(1, getattr(handler, WRAPS, ()).count(farm_restart.TAG))
                self.assertIn(handler, mode.PAGE_HANDLERS)
                self.assertEqual(name, handler.__name__)

    def test_the_app_applies_it_before_rewards_renames_the_card_reward_entry(self):
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        calls = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertEqual(1, calls.count("farm_restart"))
        self.assertLess(calls.index("farm_restart"), calls.index("rewards"))


def replay(spec):
    """Apply every patch as `src/globals.py` does, then show each screen to Chaos's whole list with every farm setting on.

    Runs in a fresh interpreter: the installs patch the real handler lists for good, which the shared test process cannot take.

    Args:
        spec: The screens and settings, as `whole_list` builds them.

    Returns:
        Per screen, the handler that took the frame, every input made and every handler that failed on it.
    """
    import importlib
    import logging
    import re
    import sys
    from pathlib import Path

    import numpy as np

    root = Path(spec["root"])
    sys.path[:0] = [str(root), str(root / "ok_tasks")]
    logging.disable(logging.CRITICAL)
    from src.en import handlers

    needs_app = {"frame_log", "remote", "sections", "forms", "task_list", "kept_forms", "picker", "shell", "game_language"}
    source = (root / "src" / "globals.py").read_text(encoding="utf-8")
    for name, function in re.findall(r"^\s*(\w+)\.(apply\w*)\(\)", source, re.M):
        if name not in needs_app and f"{name}.{function}" not in spec["leave_out"]:
            getattr(importlib.import_module(f"src.en.{name}"), function)()
    import utils
    import utils_chaos
    importlib.import_module("src.en.daily")
    for _ in range(3):
        for install in handlers._pending:
            install()

    width, height = 1920, 1080

    class Box:
        def __init__(self, name, cx, cy):
            self.name = name
            self.width, self.height = max(40, 17 * len(name)), 30
            self.x = int(round(cx * width - self.width / 2))
            self.y = int(round(cy * height - self.height / 2))
            self.confidence = 0.99

        def area(self):
            return self.width * self.height

    class ChaosMode:
        def __init__(self, texts, frame):
            self.name = "自动卡厄思模式"
            self.width, self.height = width, height
            self.all_texts = [Box(*text) for text in texts]
            self.frame = frame
            self.config = dict(spec["config"])
            self.node_status = utils._initial_node_status()
            self.member_status = utils._initial_member_status()
            self.inputs = []
            self.disabled = False
            self.info = {}
            self.executor = None
            self.trigger_interval = 0.1

        def click_box(self, box, *args, **kwargs):
            box = box[0] if isinstance(box, list) else box
            self.inputs.append([round((box.x + box.width / 2) / width, 3), round((box.y + box.height / 2) / height, 3), box.name])

        def click(self, x=-1, y=-1, *args, **kwargs):
            if hasattr(x, "width"):
                return self.click_box(x)
            self.inputs.append([round(x, 3), round(y, 3), "tap"])

        def click_relative(self, x, y, *args, **kwargs):
            self.inputs.append([round(x, 3), round(y, 3), "tap"])

        def send_key(self, key, *args, **kwargs):
            self.inputs.append([None, None, f"key {key}"])

        def swipe_relative(self, *args, **kwargs):
            self.inputs.append([None, None, "swipe"])

        def move_relative(self, *args, **kwargs):
            pass

        def ocr(self, *args, **kwargs):
            return [] if args or kwargs else list(self.all_texts)

        def wait_ocr(self, *args, **kwargs):
            return []

        def find_one(self, *args, **kwargs):
            return None

        def find_feature(self, *args, **kwargs):
            return []

        def get_feature_by_name(self, *args, **kwargs):
            return None

        def box_of_screen(self, x1, y1, x2, y2, *args, **kwargs):
            return Box("", (x1 + x2) / 2, (y1 + y2) / 2)

        def next_frame(self):
            return self.frame

        def sleep(self, *args, **kwargs):
            pass

        def log_info(self, *args, **kwargs):
            pass

        log_debug = log_warning = log_error = log_info

        def info_set(self, key, value):
            self.info[key] = value

        def info_get(self, key, default=None):
            return self.info.get(key, default)

        def notification(self, *args, **kwargs):
            pass

        def disable(self):
            self.disabled = True

        def enable(self):
            self.disabled = False

    shown = {}
    for name, screen in spec["screens"].items():
        frame = np.zeros((height, width, 3), np.uint8)
        for x, y, bgr in screen["pixels"]:
            frame[round(y * height), round(x * width)] = bgr
        task = ChaosMode(screen["texts"], frame)
        claimed, errors = None, []
        for handler in utils_chaos.PAGE_HANDLERS:
            try:
                if handler(task):
                    claimed = handler.__name__
                    break
            except Exception as error:
                errors.append(f"{handler.__name__}: {error!r}"[:160])
        shown[name] = {"claimed": claimed, "inputs": task.inputs, "errors": errors}
    return shown


def whole_list(leave_out=()):
    """Run `replay` in a fresh interpreter on the resume prompt and the Chaos start page.

    Args:
        leave_out: Apply calls in `src/globals.py` to skip, such as `"farm_restart.apply"`.

    Returns:
        What `replay` returns.
    """
    spec = {"root": str(REPO_ROOT), "leave_out": list(leave_out), "config": {"游戏语言": "English", **EVERY_SETTING},
            "screens": {"resume prompt": {"texts": [list(text) for text in RESUME], "pixels": []},
                        "start page": {"texts": [["适应畸变", 0.526, 0.093]], "pixels": [[*SWITCH, list(SWITCH_ON[::-1])]]}}}
    code = f"import json, sys\n{inspect.getsource(replay)}\nprint('REPLAY ' + json.dumps(replay(json.load(sys.stdin))))\n"
    done = subprocess.run([sys.executable, "-I", "-c", code], input=json.dumps(spec), capture_output=True, text=True, encoding="utf-8",
                          timeout=600, cwd=str(REPO_ROOT), env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    lines = [line for line in done.stdout.splitlines() if line.startswith("REPLAY ")]
    if done.returncode != 0 or not lines:
        raise AssertionError(f"replay failed ({done.returncode}): {done.stderr[-2000:]}")
    return json.loads(lines[-1][len("REPLAY "):])


def on_round_button(press):
    """Say whether an input landed on the round button, where the resume prompt's Escape sits."""
    x, y, _ = press
    return x is not None and ROUND_BUTTON[0] <= x <= ROUND_BUTTON[2] and ROUND_BUTTON[1] <= y <= ROUND_BUTTON[3]


class TestWholeList(unittest.TestCase):
    """Chaos's whole list, shaped by every patch in the app's order, with every farm and first-floor setting on."""

    @classmethod
    def setUpClass(cls):
        cls.shown = whole_list()
        cls.control = whole_list(leave_out=("farm_restart.apply",))

    def test_no_handler_failed_on_either_screen(self):
        for result in (self.shown, self.control):
            for name, screen in result.items():
                with self.subTest(screen=name):
                    self.assertEqual([], screen["errors"])

    def test_the_resume_prompt_gets_its_enter_and_never_its_escape(self):
        screen = self.shown["resume prompt"]
        self.assertEqual([], [press for press in screen["inputs"] if on_round_button(press)])
        self.assertEqual("handle_resume_prompt", screen["claimed"])
        self.assertEqual([[0.637, 0.907]], [press[:2] for press in screen["inputs"]])

    def test_the_start_page_switch_is_left_alone(self):
        self.assertEqual([], [press for press in self.shown["start page"]["inputs"] if press[:2] == list(SWITCH)])

    def test_without_the_change_the_whole_list_switches_it_off(self):
        """The control: the start page frame reaches upstream's switch handler in the app's own list."""
        self.assertIn(list(SWITCH), [press[:2] for press in self.control["start page"]["inputs"]])


if __name__ == "__main__":
    unittest.main()
