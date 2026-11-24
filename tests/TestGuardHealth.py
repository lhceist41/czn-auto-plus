"""Check that a mode refuses to start when one of its safety guards did not install, and starts when all did.

A failed install only logs, and an edit whose anchor is missing does not even do that, so without the start check a
mode would run on upstream behaviour: press any centred Confirm, pay Aether for Reason, tap blind on a frozen screen.
"""

import functools
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ok.task.exceptions import TaskDisabledException  # noqa: E402

from src.en import claims, equipment, farm_restart, guard_health, handlers, heal, reason, shell, spend_guard  # noqa: E402
from src.en.handlers import WRAPS  # noqa: E402

CHAOS, SORTIE, STORY, DAILY = guard_health.CHAOS, guard_health.SORTIE, guard_health.STORY, guard_health.DAILY
CLASS_OF = {mode: name for name, mode in guard_health.MODES.items()}
# The spend guard's wrapped handlers, as its install reaches them on `utils`.
SPEND_NAMES = ("handle_stuck_log", "handle_center_confirm", "handle_enter", *spend_guard.RUN_MENU_HANDLERS, "handle_escape")
FULL_INSTALL_SECONDS = 240
CONFIRM = "handle_center_confirm"
CAPTIONS = ("handle_next_step", "handle_continue", "handle_close_page", "handle_skip", "handle_settlement")


def carrying(handler, tag):
    """Pin the need for a handler carrying one change, undone by a same-named handler without it.

    Args:
        handler: The handler's name.
        tag: The change.

    Returns:
        `(label, undo)`.
    """
    return f"{tag} ({handler})", ("tag", handler, tag)


def spend_pins(captions, taps_and_escape=True):
    """Pin what the spend guard leaves in one of Chaos, Sortie and Story.

    Args:
        captions: The mode's caption handlers the guard keeps off a run menu.
        taps_and_escape: Whether the mode's list holds `handle_stuck_log` and `handle_escape`.

    Returns:
        A list of `(label, undo)`.
    """
    return [
        *([carrying("handle_stuck_log", spend_guard.TAPS_TAG)] if taps_and_escape else []),
        carrying(CONFIRM, spend_guard.CONFIRM_TAG),
        carrying("handle_enter", spend_guard.ENTER_TAG),
        *(carrying(name, spend_guard.RUN_MENU_TAG) for name in captions),
        *([carrying("handle_escape", spend_guard.ESCAPE_TAG)] if taps_and_escape else []),
        (f"Rescue stop (handle_rescue_screen ahead of {CONFIRM})", ("before", "handle_rescue_screen", CONFIRM)),
        ("run-menu hold (handle_run_menu)", ("name", "handle_run_menu", None)),
    ]


STUCK_STOP = ("stuck stop (stop_when_stuck)", ("name", "stop_when_stuck", None))
LANGUAGE_CHECK = ("Game Language check (check_game_language)", ("name", "check_game_language", None))
FAINT_MEMORY = [("Faint Memory limit (handle_memory_limit)", ("before", "handle_memory_limit", CONFIRM)),
                ("Divine notice (handle_divine_epiphany)", ("before", "handle_divine_epiphany", CONFIRM))]
EQUIPMENT = [*(carrying("handle_equipment", tag) for tag in (
                 equipment.UPGRADE_TAG, equipment.PLACEMENT_TAG, equipment.RECOMMENDED_TAG, equipment.MYTHIC_TAG,
                 equipment.SLOT_TAG, equipment.PICK_TAG, equipment.SELECTED_TAG, equipment.DRAWN_TAG)),
             (f"{equipment.LISTS_TAG} (_equipment_priority)", ("utils", "_equipment_priority", equipment.LISTS_TAG))]
ZERO_SYSTEM = [*((f"Zero System Codex ({name})", ("name", name, None))
                 for name in ("handle_select_codex", "handle_merge_codices", "handle_codex_obtained")),
               ("Zero System Codex (handle_discovery_select)", ("identity", "handle_discovery_select", None))]
# Every need each mode's start checks with a farm setting on, written out rather than read from `guard_health.GUARDS`
# so a need dropped from the table fails a test: its label, then how the real-install test undoes it.
PINS = {
    "ChaosMode": ("utils_chaos", dict([
        *spend_pins(CAPTIONS), carrying("handle_trauma_center", heal.TAG), *FAINT_MEMORY, *EQUIPMENT, *ZERO_SYSTEM,
        *(carrying(name, farm_restart.TAG)
          for name in ("handle_event_task", "handle_card_reward", "handle_disable_adaptation_distortion")),
        STUCK_STOP, LANGUAGE_CHECK])),
    "SortieMode": ("utils_sortie", dict([
        *spend_pins(CAPTIONS),
        (f"Reason only (handle_charge_reason ahead of {CONFIRM})", ("before", "handle_charge_reason", CONFIRM)),
        carrying("handle_sortie_reward_settlement", reason.SETTLEMENT_TAG),
        carrying("handle_sortie_reward_claim", reason.CLAIM_TAG),
        *FAINT_MEMORY, *EQUIPMENT, STUCK_STOP, LANGUAGE_CHECK])),
    "StoryMode": ("utils_story", dict([
        *spend_pins(("handle_next_step", "handle_close_page"), taps_and_escape=False), STUCK_STOP, LANGUAGE_CHECK])),
    "DailyMode": ("src.en.daily", dict([("Rescue stop (handle_rescue_screen)", ("name", "handle_rescue_screen", None)),
                                         STUCK_STOP])),
}
# Daily's Rescue stop is in its own list, so upstream's lists meet it with no install run.
STATIC = {"DailyMode": ("Rescue stop (handle_rescue_screen)",)}
# Each guard module whose install raising refuses a start with every need met: the guard's label and the modes it refuses.
RAISED = {
    "src.en.spend_guard": ("spend guard", ("ChaosMode", "SortieMode", "StoryMode")),
    "src.en.reason": ("Reason only", ("SortieMode",)),
    "src.en.heal": ("Credits-only healing", ("ChaosMode", "SortieMode")),
    "src.en.memory_limit": ("Faint Memory limit", ("ChaosMode", "SortieMode")),
    "src.en.equipment": ("equipment rules", ("ChaosMode", "SortieMode")),
    "src.en.zero_system": ("Zero System Codex rules", ("ChaosMode",)),
    "src.en.farm_restart": ("farm restart off", ("ChaosMode",)),
    "src.en.stuck_stop": ("stuck stop", ("ChaosMode", "SortieMode", "StoryMode", "DailyMode")),
    "src.en.language_check": ("Game Language check", ("ChaosMode", "SortieMode", "StoryMode")),
}

# Every handler-list `apply` from `src/globals.py` on the vendored modes, run twice as two task loads would, then the
# check for each mode; then the same with each guard's module left out, on the pristine lists. Before the installs the
# check reads the pristine lists; between the two, on the healthy lists, each pinned need is undone alone and each
# guard module's install made to raise.
FULL_INSTALL = r"""
import importlib, json, re, sys
root = sys.argv[1]
sys.path[:0] = [root, root + "/ok_tasks"]
import utils, utils_chaos, utils_sortie, utils_story
import src.en.daily
modules = [utils, utils_chaos, utils_sortie, utils_story, src.en.daily]
pristine = [(module, dict(vars(module)), list(module.PAGE_HANDLERS)) for module in modules if hasattr(module, "PAGE_HANDLERS")]
pristine += [(utils, dict(vars(utils)), None)]
source = open(root + "/src/globals.py", encoding="utf-8").read()
calls = re.findall(r"^\s*(\w+)\.(apply\w*)\(\)", source, re.M)
names = [module for module, _ in calls]
for module, function in calls[names.index("navigation"):names.index("shell")]:
    getattr(importlib.import_module("src.en." + module), function)()
from src.en import guard_health, handlers
from src.en.handlers import WRAPS, loaded
pins, raising = json.loads(sys.argv[2]), json.loads(sys.argv[3])

def farming(name):
    return type(name, (), {"config": {"刷空档": True}, "default_config": {}})()

def stand_in(name, tags):
    def handle(task):
        return False
    handle.__name__ = name
    setattr(handle, WRAPS, tuple(sorted(tags)))
    return handle

def undo(module, kind, name, arg):
    if kind == "utils":
        setattr(utils, name, stand_in(name, guard_health.carried(getattr(utils, name)) - {arg}))
        return
    entries = loaded(module).PAGE_HANDLERS
    index = guard_health.find(entries, guard_health.Need(name, name))
    if kind == "tag":
        entries[index] = stand_in(name, guard_health.carried(entries[index]) - {arg})
    elif kind == "identity":
        entries[index] = stand_in(name, guard_health.carried(entries[index]))
    elif kind == "name":
        del entries[index]
    else:
        entry = entries.pop(index)
        entries.insert(guard_health.find(entries, guard_health.Need(arg, arg)) + 1, entry)

def restore():
    for module, attributes, entries in pristine:
        vars(module).update(attributes)
        if entries is not None:
            module.PAGE_HANDLERS[:] = entries

def refusals(skipped=None):
    restore()
    installs = [install for install in handlers._pending if install.__module__ != skipped]
    for _ in range(2):
        handlers.run_installs(installs)
    found = {}
    for name, mode in guard_health.MODES.items():
        for farming in (False, True):
            task = type(name, (), {"config": {"刷空档": farming}, "default_config": {}})()
            found[f"{name} {farming}"] = guard_health.missing(task)
    return found

restore()
result = {"pristine": {name: guard_health.missing(farming(name)) for name in pins}}
result.update(healthy=refusals(), failed=sorted(map(str, handlers.failed)), skipped={}, undone={}, raised={})
result["table"] = {name: [need.label for guard in guard_health.GUARDS if module in guard.modes
                          for need in guard.needs.get(module, ())] for name, (module, _) in pins.items()}
for name, (module, needs) in pins.items():
    for label, (kind, handler, arg) in needs.items():
        entries, attributes = list(loaded(module).PAGE_HANDLERS), dict(vars(utils))
        undo(module, kind, handler, arg)
        result["undone"][f"{name} {label}"] = guard_health.missing(farming(name))
        loaded(module).PAGE_HANDLERS[:] = entries
        vars(utils).update(attributes)
for module in raising:
    def install():
        raise RuntimeError("raised on purpose")
    install.__module__ = module
    handlers.run_installs([install])
    result["raised"][module] = {name: guard_health.missing(farming(name)) for name in pins}
    handlers.failed.discard(install)
for module in sorted({guard.module for guard in guard_health.GUARDS if guard.module}) + ["src.en.dice"]:
    result["skipped"][module] = refusals(module)
print("RESULT " + json.dumps(result))
"""


@functools.lru_cache(maxsize=None)
def real_install():
    """Run `FULL_INSTALL` once for every test reading it.

    Returns:
        `(result, stderr)`: the parsed result, or None when the run printed none, and the end of its error output.
    """
    run = subprocess.run([sys.executable, "-c", FULL_INSTALL, str(REPO_ROOT), json.dumps(PINS), json.dumps(sorted(RAISED))],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=FULL_INSTALL_SECONDS,
                         cwd=REPO_ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [line for line in run.stdout.splitlines() if line.startswith("RESULT ")]
    return (json.loads(lines[0][len("RESULT "):]) if len(lines) == 1 else None), run.stderr[-3000:]


class FakeTask:
    """A mode starting, recording every tap, announcement and stop."""

    def __init__(self, config=None):
        self.name = "mode"
        self.config = config or {}
        self.default_config = {}
        self.clicked = []
        self.logged = []
        self.notifications = []
        self.disabled = 0

    def click(self, *args, **kwargs):
        self.clicked.append(args)

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled += 1


def mode_task(mode, config=None):
    """Build a task whose class carries the mode's class name, which is how the check tells modes apart.

    Args:
        mode: The mode's list module.
        config: The run's settings.

    Returns:
        The task.
    """
    return type(CLASS_OF[mode], (FakeTask,), {})(config)


def handler(name, called, tags=()):
    """Build a handler that records being called, carrying a name and the changes it already has.

    Args:
        name: Its `__name__`.
        called: The list it records into.
        tags: The changes `handlers.wrap` would have recorded on it.

    Returns:
        The handler.
    """
    def handle(task):
        called.append(name)
        return False

    handle.__name__ = name
    if tags:
        setattr(handle, WRAPS, tuple(tags))
    return handle


def healthy(mode, called, utils, skip=()):
    """Build a mode's list as a complete install leaves it, less the guards named.

    Args:
        mode: The mode's list module.
        called: The list its handlers record into.
        utils: The stand-in `utils`, which gets the attributes a guard checks there.
        skip: Labels of the guards to leave out.

    Returns:
        The list.
    """
    tags, functions, anchors = {}, [], set()
    for guard in guard_health.GUARDS:
        if guard.label in skip:
            continue
        for need in guard.needs.get(mode, ()):
            if need.on is not None:
                current = getattr(utils, need.handler, None)
                setattr(utils, need.handler, handler(need.handler, called, (*getattr(current, WRAPS, ()), need.tag)))
            elif need.function is not None:
                functions.append(need.function)
            else:
                tags.setdefault(need.handler, [])
                if need.tag is not None:
                    tags[need.handler].append(need.tag)
            if need.before is not None:
                anchors.add(need.before)
    ahead = [handler(name, called, found) for name, found in tags.items() if name not in anchors]
    return [*ahead, *functions, *(handler(name, called, found) for name, found in tags.items() if name in anchors)]


def from_module(module, install):
    """Have an install count as one a guard module registered.

    Args:
        module: The module name the install claims.
        install: The callable.

    Returns:
        The same callable.
    """
    install.__module__ = module
    return install


class RaisingUtils(types.SimpleNamespace):
    """A stand-in `utils` on which reading any of the named functions raises, as a broken install would meet it."""

    def __init__(self, raising, **functions):
        super().__init__(**functions)
        object.__setattr__(self, "_raising", raising)

    def __getattribute__(self, name):
        if name in object.__getattribute__(self, "_raising"):
            raise RuntimeError(f"{name} cannot be read")
        return super().__getattribute__(name)


class TestGuardHealth(unittest.TestCase):
    """Starting a mode over lists the installs have finished with, or failed on."""

    def setUp(self):
        self.called = []
        self.utils = types.SimpleNamespace()
        self.modules = {name: types.ModuleType(name) for name in (CHAOS, SORTIE, STORY, DAILY)}
        for name, module in self.modules.items():
            module.PAGE_HANDLERS = healthy(name, self.called, self.utils)
        # The real lists, when another test loaded them: `replace` and `insert_before` edit every list they find.
        self.saved = [(entries, list(entries)) for _, entries in handlers.each_list()]
        self.loaded = mock.patch.dict(sys.modules, {**self.modules, "utils": self.utils})
        self.loaded.start()
        failed = set(handlers.failed)
        handlers.failed.clear()
        self.addCleanup(handlers.failed.update, failed)
        self.addCleanup(handlers.failed.clear)

    def tearDown(self):
        self.loaded.stop()
        for entries, before in self.saved:
            entries[:] = before

    def start(self, mode, config=None):
        """Start a mode through the checking `enable`, as the run loop does.

        Args:
            mode: The mode's list module.
            config: The run's settings.

        Returns:
            `(task, refused, enabled)`: the task, the refusal raised or None, and how often the original `enable` ran.
        """
        task = mode_task(mode, config)
        enabled = []
        enable = guard_health.checking(lambda self_: enabled.append(self_))
        try:
            enable(task)
        except TaskDisabledException as refusal:
            return task, refusal, len(enabled)
        return task, None, len(enabled)

    def assert_refused(self, mode, *named, config=None):
        """Start a mode and check it stopped before any input, naming each guard given.

        Args:
            mode: The mode's list module.
            *named: Text each must appear in the one notice.
            config: The run's settings.

        Returns:
            The notice.
        """
        with mock.patch.object(guard_health.logger, "error") as error:
            task, refusal, enabled = self.start(mode, config)
        self.assertIsNotNone(refusal)
        self.assertEqual(0, enabled)
        self.assertEqual(1, task.disabled)
        self.assertEqual(1, len(task.notifications))
        self.assertEqual(1, error.call_count)
        notice = task.notifications[0]
        self.assertTrue(notice.startswith("Safety guard missing: "), notice)
        self.assertTrue(notice.endswith(". Stopped before any input."), notice)
        for text in named:
            self.assertIn(text, notice)
        self.assertEqual([], task.clicked)
        self.assertEqual([], self.called)
        return notice

    def assert_started(self, mode, config=None):
        """Start a mode and check it started without a notice.

        Args:
            mode: The mode's list module.
            config: The run's settings.
        """
        task, refusal, enabled = self.start(mode, config)
        self.assertIsNone(refusal, refusal)
        self.assertEqual(1, enabled)
        self.assertEqual(0, task.disabled)
        self.assertEqual([], task.notifications)

    def spend_utils(self, raising=(), leave_out=()):
        """Build a stand-in `utils` carrying the handlers the spend guard wraps, unguarded.

        Args:
            raising: Names whose reading raises.
            leave_out: Names it does not carry.

        Returns:
            The stand-in.
        """
        functions = {name: handler(name, self.called) for name in SPEND_NAMES if name not in leave_out}
        return RaisingUtils(raising, **functions)

    def unguarded(self, mode, utils):
        """Rebuild a mode's list without the spend guard, holding upstream's handlers from `utils` instead.

        Args:
            mode: The mode's list module.
            utils: The stand-in carrying upstream's handlers.
        """
        upstream = [object.__getattribute__(utils, name) for name in SPEND_NAMES if name in vars(utils)]
        self.modules[mode].PAGE_HANDLERS = [*healthy(mode, self.called, self.utils, skip=("spend guard",)), *upstream]

    def test_an_install_raising_before_any_wrap_refuses_chaos(self):
        utils = self.spend_utils(raising=SPEND_NAMES)
        self.unguarded(CHAOS, utils)
        handlers.run_installs([from_module(spend_guard.__name__, lambda: spend_guard.install(utils))])
        notice = self.assert_refused(CHAOS, "spend guard (its install raised)", spend_guard.CONFIRM_TAG, spend_guard.TAPS_TAG)
        self.assertIn(guard_health.RESCUE.label, notice)

    def test_an_install_raising_after_the_taps_wrap_names_the_confirm_guard(self):
        utils = self.spend_utils(raising=("handle_center_confirm",))
        self.unguarded(CHAOS, utils)
        handlers.run_installs([from_module(spend_guard.__name__, lambda: spend_guard.install(utils))])
        self.assertIn(spend_guard.TAPS_TAG, getattr(self.modules[CHAOS].PAGE_HANDLERS[-len(SPEND_NAMES)], WRAPS))
        notice = self.assert_refused(CHAOS, f"{spend_guard.CONFIRM_TAG} (handle_center_confirm)")
        self.assertNotIn(spend_guard.TAPS_TAG, notice)

    def test_a_missing_confirm_anchor_in_sortie_names_the_rescue_stop(self):
        utils = self.spend_utils(leave_out=("handle_center_confirm",))
        self.unguarded(SORTIE, utils)
        installs = [from_module(spend_guard.__name__, lambda: spend_guard.install(utils)),
                    from_module(spend_guard.__name__, lambda: spend_guard.install_run_menus(utils))]
        handlers.run_installs(installs)
        self.assertEqual(set(), handlers.failed)
        notice = self.assert_refused(SORTIE, guard_health.RESCUE.label)
        self.assertNotIn("run-menu hold", notice)

    def test_a_missing_run_menu_hold_refuses_story(self):
        entries = self.modules[STORY].PAGE_HANDLERS
        entries[:] = [entry for entry in entries if entry.__name__ != guard_health.RUN_MENU]
        self.assert_refused(STORY, f"run-menu hold ({guard_health.RUN_MENU})")

    def test_a_missing_reason_guard_refuses_sortie_only(self):
        name = reason.charge_reason_handler(None).__name__
        for mode in (SORTIE, CHAOS):
            entries = self.modules[mode].PAGE_HANDLERS
            entries[:] = [entry for entry in entries if entry.__name__ != name]
        self.assert_refused(SORTIE, f"Reason only ({name}")
        self.assert_started(CHAOS)

    def test_a_quality_install_raising_starts_with_one_warning(self):
        def install():
            raise RuntimeError("dice broke")

        handlers.run_installs([from_module("src.en.dice", install)])
        with mock.patch.object(guard_health.logger, "warning") as warning:
            self.assert_started(CHAOS)
        self.assertEqual(1, warning.call_count)
        self.assertIn("src.en.dice", warning.call_args.args[0])

    def test_every_mode_starts_without_a_warning_when_every_guard_installed(self):
        with mock.patch.object(guard_health.logger, "warning") as warning:
            for mode in (CHAOS, SORTIE, STORY, DAILY):
                self.assert_started(mode, {"刷空档": True})
        warning.assert_not_called()

    def test_the_real_install_starts_every_mode_and_each_skipped_guard_refuses_its_modes(self):
        result, stderr = real_install()
        self.assertIsNotNone(result, stderr)
        self.assertEqual([], result["failed"])
        self.assertEqual({}, {key: names for key, names in result["healthy"].items() if names})

        def refused(module):
            return sorted(key for key, names in result["skipped"][module].items() if names)

        every = ["{} False", "{} True"]
        expected = {
            "src.en.spend_guard": ("ChaosMode", "SortieMode", "StoryMode"),
            "src.en.reason": ("SortieMode",),
            "src.en.heal": ("ChaosMode",),
            "src.en.memory_limit": ("ChaosMode", "SortieMode"),
            "src.en.equipment": ("ChaosMode", "SortieMode"),
            "src.en.zero_system": ("ChaosMode",),
            "src.en.stuck_stop": ("ChaosMode", "DailyMode", "SortieMode", "StoryMode"),
            "src.en.language_check": ("ChaosMode", "SortieMode", "StoryMode"),
            "src.en.dice": (),
        }
        for module, modes in expected.items():
            with self.subTest(module=module):
                self.assertEqual(sorted(form.format(mode) for mode in modes for form in every), refused(module))
        self.assertEqual(["ChaosMode True"], refused("src.en.farm_restart"))

    def test_the_real_install_refuses_each_need_undone_alone_and_each_guard_install_raising(self):
        result, stderr = real_install()
        self.assertIsNotNone(result, stderr)
        self.assertEqual({"ChaosMode": 32, "SortieMode": 27, "StoryMode": 8, "DailyMode": 2},
                         {name: len(needs) for name, (_, needs) in PINS.items()})
        for name, (_, needs) in PINS.items():
            with self.subTest(mode=name):
                self.assertEqual(sorted(needs), sorted(result["table"][name]))
                # With no install run, only a need held in the mode's own list is met, so none is met by chance.
                self.assertEqual(sorted(set(needs) - set(STATIC.get(name, ()))), sorted(result["pristine"][name]))
            for label in needs:
                with self.subTest(mode=name, need=label):
                    self.assertEqual([label], result["undone"][f"{name} {label}"])
        for module, (label, modes) in RAISED.items():
            for name in PINS:
                with self.subTest(raised=module, mode=name):
                    expected = [f"{label} (its install raised)"] if name in modes else []
                    self.assertEqual(expected, result["raised"][module][name])

    def test_a_claims_wrapper_over_a_guarded_handler_still_counts(self):
        for module in self.modules.values():
            module.PAGE_HANDLERS[:] = [claims.logging_claim(entry) for entry in module.PAGE_HANDLERS]
        self.assert_started(CHAOS)
        entries = self.modules[CHAOS].PAGE_HANDLERS
        index = next(index for index, entry in enumerate(entries) if entry.__name__ == "handle_center_confirm")
        entries[index] = claims.logging_claim(handler("handle_center_confirm", self.called))
        self.assert_refused(CHAOS, spend_guard.CONFIRM_TAG)

    def test_a_closure_renaming_a_guarded_handler_is_read_through(self):
        """notify's stuck notice holds the guarded handler as `original`, `rewards`' list filler as `handler`."""
        def announcing(original):
            def handle_stuck_log_announcing(task):
                return original(task)

            return handle_stuck_log_announcing

        def filling(handler):
            def wrapped(task):
                return handler(task)

            wrapped.__name__ = f"{handler.__name__}_filling_empty_lists"
            return wrapped

        entries = self.modules[CHAOS].PAGE_HANDLERS
        for rename, name, tag in ((announcing, "handle_stuck_log", spend_guard.TAPS_TAG),
                                  (filling, "handle_card_reward", "no farm restart on Global")):
            with self.subTest(name=name):
                index = next(index for index, entry in enumerate(entries) if entry.__name__ == name)
                guarded = entries[index]
                entries[index] = claims.logging_claim(rename(guarded))
                self.assert_started(CHAOS, {"刷空档": True})
                entries[index] = claims.logging_claim(rename(handler(name, self.called)))
                self.assert_refused(CHAOS, tag, config={"刷空档": True})
                entries[index] = guarded

    def test_a_rescue_stop_behind_the_confirm_refuses(self):
        entries = self.modules[STORY].PAGE_HANDLERS
        rescue = next(entry for entry in entries if entry.__name__ == guard_health.RESCUE.handler)
        entries.remove(rescue)
        entries.append(rescue)
        self.assert_refused(STORY, guard_health.RESCUE.label)

    def test_daily_without_its_rescue_stop_refuses(self):
        entries = self.modules[DAILY].PAGE_HANDLERS
        entries[:] = [entry for entry in entries if entry.__name__ != guard_health.RESCUE.handler]
        self.assert_refused(DAILY, f"Rescue stop ({guard_health.RESCUE.handler})")

    def test_a_missing_farm_restart_guard_matters_only_with_a_farm_setting_on(self):
        self.modules[CHAOS].PAGE_HANDLERS = healthy(CHAOS, self.called, self.utils, skip=("farm restart off",))
        self.assert_started(CHAOS, {"刷空档": False, "刷初始卡牌": ""})
        self.assert_refused(CHAOS, "no farm restart on Global", config={"刷空档": True})
        self.called.clear()
        self.assert_refused(CHAOS, "no farm restart on Global", config={"刷初始卡牌": "Some Card"})

    def test_the_check_runs_before_the_run_loop_reads_a_frame(self):
        """The run loop calls the mode's `enable` before its first pass, so a refusal leaves `run` uncalled."""
        self.modules[CHAOS].PAGE_HANDLERS = healthy(CHAOS, self.called, self.utils, skip=("stuck stop",))
        frames = []
        enabled = []
        task = mode_task(CHAOS)
        task.run = lambda: frames.append("frame")
        task.enable = lambda: guard_health.checking(lambda self_: enabled.append(self_))(task)
        task.enabled = True
        with mock.patch.object(guard_health.logger, "error"), self.assertRaises(TaskDisabledException):
            shell.looping(task)()
        self.assertEqual([], frames)
        self.assertEqual([], enabled)
        self.assertEqual(1, task.disabled)
        self.assertEqual([], self.called)

    def test_an_install_that_completes_on_a_later_load_is_forgotten(self):
        broken = [True]

        def install():
            if broken[0]:
                raise RuntimeError("not yet")

        install = from_module(spend_guard.__name__, install)
        handlers.run_installs([install])
        self.assertEqual({install}, handlers.failed)
        broken[0] = False
        handlers.run_installs([install])
        self.assertEqual(set(), handlers.failed)

    def test_a_task_that_is_not_a_mode_is_never_refused(self):
        handlers.run_installs([from_module(spend_guard.__name__, lambda: 1 / 0)])
        self.assertEqual([], guard_health.missing(FakeTask()))

    def test_the_table_names_only_handlers_the_guards_define(self):
        self.assertTrue(set(guard_health.CAPTIONS[STORY]) <= set(spend_guard.RUN_MENU_HANDLERS))
        self.assertEqual(guard_health.RUN_MENU, spend_guard.holding_run_menu(None, False).__name__)
        self.assertEqual("stop_when_stuck", guard_health.STUCK_STOP.handler)


if __name__ == "__main__":
    unittest.main()
