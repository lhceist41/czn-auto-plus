"""Check that a run starting on the Combatants tab reads it instead of tapping its way back to it, that Sortie and Chaos go there once a
layer, that the deck read off All Piles on the way values each card by its Epiphany, that a mode starts with no team or deck read, and that
a Sortie or Chaos Epiphany goes on the card that read found without one."""

import sys
import types
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import battle, cards, epiphany, navigation, piles, rewards  # noqa: E402
from src.en.handlers import standing_in  # noqa: E402
from src.en.battle import PARTY, TURN  # noqa: E402
from src.en.dashboard import TEAM_NAMES  # noqa: E402
from src.en.game_text import DESCRIPTIONS, EPIPHANIES  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402
from tests.TestStuckStop import Modes, named, names  # noqa: E402

TARGET = "Arabella"
# What the log shows on the Combatants tab, at the three points upstream reads names from.
ON_THE_TAB = {(0.159, 0.368): "Arabella", (0.432, 0.368): "Veronica", (0.705, 0.369): "Mika"}
# A sibling tab: names at the same points, none of them a combatant.
ANOTHER_TAB = {(0.159, 0.368): "Whisper", (0.432, 0.368): "Ember", (0.705, 0.369): "Tallow"}
# The taps upstream's capture makes: the 3-person icon, the Combatants tab, then the one that closes the page.
CLOSE_PAGE = (0.960, 0.054)
# Columns one and four of an All Piles page as the reader returned them, as (text, centre x, centre y, width, height) in pixels. The two
# Experienced Strikes carry different versions, Hew's text names a card, and the last row runs off the bottom.
PILES_PAGE = (
    ("Slash", 707, 159, 70, 28), ("XBasic Attack", 756, 184, 164, 26), ("143% Defense-Based", 749, 364, 214, 26), ("Damage", 749, 392, 96, 30),
    ("Increase Damage", 747, 417, 178, 28), ("Amount of Exhaust", 749, 443, 186, 20), ("cards by 15% for1 turn", 751, 468, 234, 30),
    ("(max2 stacks)", 748, 494, 148, 28),
    ("Experienced Strike", 773, 612, 218, 31), ("XAttack", 723, 640, 110, 33), ("168% Defense-Based", 750, 817, 216, 26), ("Damage", 751, 846, 88, 29),
    ("20% DMG-Based Shield", 756, 869, 248, 30), ("Increase Damage", 748, 895, 176, 24), ("Amount of Exhaust", 749, 920, 190, 26),
    ("cards by 20% for 1 turn", 752, 948, 232, 26),
    ("QVulture Ejection", 748, 1060, 240, 37),
    ("Hew", 1647, 158, 62, 30), ("Attack", 1690, 187, 68, 20), ("[Unique/lnitiation/", 1706, 364, 212, 26), ("Exhaust / Ephemeral]", 1701, 391, 222, 32),
    ("420% Defense-Based", 1701, 416, 222, 26), ("Damage", 1701, 444, 90, 27), ("Incinerate: Create", 1702, 468, 176, 19), ("1HewLv.1", 1704, 495, 112, 26),
    ("Experienced Strike", 1727, 612, 210, 25), ("Attack", 1676, 640, 108, 33), ("252%Defense-Based", 1699, 818, 214, 20), ("Damage", 1702, 846, 90, 29),
    ("20% DMG-Based Shield", 1707, 869, 250, 30), ("Increase Shield Gain", 1701, 895, 202, 20), ("Amount of Skill Cards", 1700, 921, 212, 20),
    ("by 30%for1turn", 1704, 947, 172, 20),
    ("Absolute Protection", 1725, 1062, 214, 32),
    # A card named inside another card's text, with a text line as close below it as a type label would be. From the next page.
    ("Contaminated Spore", 1282, 433, 210, 30), ("Retain:Create", 1316, 465, 146, 19),
)
# The Experienced Strike Epiphany the second copy above carries.
SHIELD_GAIN = next(text for text in EPIPHANIES["Experienced Strike"] if "Shield Gain" in text)


class FakeTask:
    """A mode recording the taps a handler asks for."""

    def __init__(self):
        self.clicks = []
        self.boxes = []

    def click_box(self, box, *args, **kwargs):
        self.boxes.append(getattr(box, "name", box))


def install(names, target=TARGET):
    """Put stand-in task modules where `handlers.loaded` will find them.

    Args:
        names: What OCR reads at each of the three name points.
        target: The combatant the run is farming, as the setting would give it.

    Returns:
        The stand-in `utils_chaos`, whose `_move_and_click` the capture calls.
    """
    utils = types.ModuleType("utils")
    utils.find_box_at_point = lambda task, x, y: (
        types.SimpleNamespace(name=names[(x, y)]) if (x, y) in names else None
    )
    utils._get_config_value = lambda task, key, default=None: target

    utils_chaos = types.ModuleType("utils_chaos")
    utils_chaos._move_and_click = lambda task, x, y: task.clicks.append((x, y))

    sys.modules["utils"] = utils
    sys.modules["utils_chaos"] = utils_chaos
    return utils_chaos


def restoring_modules(test):
    """Put back whatever `utils` and `utils_chaos` were before the test, once it ends.

    A later test module in the same process may hold the real modules, which popping the stand-ins would take away.

    Args:
        test: The running test case.
    """
    saved = {name: sys.modules[name] for name in ("utils", "utils_chaos") if name in sys.modules}

    def restore():
        for name in ("utils", "utils_chaos"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)

    test.addCleanup(restore)


def upstream_capture(utils_chaos, extra_boxes=0):
    """Stand in for upstream's capture: the two navigation taps, then the tap that closes the page.

    Args:
        utils_chaos: The module whose `_move_and_click` the capture reaches for.
        extra_boxes: Box clicks beyond the one upstream makes today, for the rebase the tally guards against.

    Returns:
        A handler that records what it tapped and reports that it handled the frame.
    """
    def handle_archive_target_member(task):
        for _ in range(1 + extra_boxes):
            task.click_box(types.SimpleNamespace(name="memberinfo"))
        utils_chaos._move_and_click(task, *navigation.COMBATANTS_TAB)
        utils_chaos._move_and_click(task, *CLOSE_PAGE)
        return True

    return handle_archive_target_member


class TestOnCombatantsTab(unittest.TestCase):
    """The guard that decides whether the trip can be skipped."""

    def setUp(self):
        restoring_modules(self)

    def test_a_combatant_on_screen_proves_the_tab_is_open(self):
        install(ON_THE_TAB)
        self.assertTrue(navigation.on_combatants_tab(FakeTask()))

    def test_a_sibling_tab_is_not_mistaken_for_it(self):
        """Partners and Fate draw names at the same points, so names alone would not be proof."""
        install(ANOTHER_TAB)
        self.assertFalse(navigation.on_combatants_tab(FakeTask()))

    def test_a_screen_with_no_names_is_not_it(self):
        install({})
        self.assertFalse(navigation.on_combatants_tab(FakeTask()))

    def test_one_readable_slot_is_enough(self):
        install({(0.705, 0.369): TARGET})
        self.assertTrue(navigation.on_combatants_tab(FakeTask()))

    def test_a_name_read_with_extra_text_still_counts(self):
        """Upstream matches either way round, so anything its own read would accept has to be accepted here."""
        install({(0.159, 0.368): "Arabella Lv40"})
        self.assertTrue(navigation.on_combatants_tab(FakeTask()))

    def test_it_does_not_depend_on_who_is_farmed(self):
        # A run farming nobody clicked the icon and the tab every time, because the farmed name was the only proof.
        for target in ("", "(none)", "Heidemarie"):
            with self.subTest(target=target):
                install(ON_THE_TAB, target=target)
                self.assertTrue(navigation.on_combatants_tab(FakeTask()))

    def test_a_short_name_inside_a_longer_word_does_not_count(self):
        install({(0.159, 0.368): "Fenia"})
        self.assertFalse(navigation.on_combatants_tab(FakeTask()))


class TestReadingInPlace(unittest.TestCase):
    """The wrapper drops the two navigation taps and leaves everything else upstream does alone."""

    def setUp(self):
        restoring_modules(self)

    def capture(self, names, extra_boxes=0):
        """Run the wrapped capture against a screen.

        Args:
            names: What OCR reads at the three name points.
            extra_boxes: Box clicks beyond the one upstream makes today.

        Returns:
            A `(task, handled)` pair.
        """
        utils_chaos = install(names)
        task = FakeTask()
        handled = navigation.reading_in_place(upstream_capture(utils_chaos, extra_boxes))(task)
        return task, handled

    def test_only_the_trip_back_to_the_screen_is_dropped(self):
        """Both navigation taps go, the tap that closes the page stays, and the answer is handed back."""
        task, handled = self.capture(ON_THE_TAB)
        self.assertEqual([], task.boxes)
        self.assertEqual([CLOSE_PAGE], task.clicks)
        self.assertTrue(handled)

    def test_a_run_starting_elsewhere_taps_only_the_icon(self):
        """The 3-person icon already lands on the Combatants tab, so the tab tap after it would do nothing."""
        task, handled = self.capture(ANOTHER_TAB)
        self.assertEqual(["memberinfo"], task.boxes)
        self.assertEqual([CLOSE_PAGE], task.clicks)
        self.assertTrue(handled)

    def test_a_capture_that_throws_still_puts_them_back(self):
        """A capture that raised while the taps were stood in for would leave upstream permanently rewired."""
        utils_chaos = install(ON_THE_TAB)
        original = utils_chaos._move_and_click
        task = FakeTask()

        def raising(task):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            navigation.reading_in_place(raising)(task)
        self.assertIs(original, utils_chaos._move_and_click)
        self.assertNotIn("click_box", task.__dict__)

    def test_the_stand_in_keeps_the_name_upstream_logs(self):
        """`_move_and_click` logs the name of the frame that called it, and this stands in mid-capture."""
        stand_in = navigation.without_the_tab_tap(lambda task, x, y: None, navigation.Dropped())
        self.assertEqual("handle_archive_target_member", stand_in.__code__.co_name)


class TestTheTallyNoticesARebase(unittest.TestCase):
    """Both taps are recognised by shape, so upstream moving one has to be made loud rather than silent."""

    def setUp(self):
        restoring_modules(self)

    def warnings(self, extra_boxes=0, tab=navigation.COMBATANTS_TAB):
        """Run the wrapped capture and collect what it warned about.

        Args:
            extra_boxes: Box clicks beyond the one upstream makes today.
            tab: Where the capture taps for the Combatants tab.

        Returns:
            The warning lines the wrapper logged.
        """
        utils_chaos = install(ON_THE_TAB)
        said = []
        original_warning = navigation.logger.warning
        navigation.logger.warning = lambda message, *args, **kwargs: said.append(message)
        try:
            def handle_archive_target_member(task):
                for _ in range(1 + extra_boxes):
                    task.click_box(types.SimpleNamespace(name="memberinfo"))
                utils_chaos._move_and_click(task, *tab)
                return True

            navigation.reading_in_place(handle_archive_target_member)(FakeTask())
        finally:
            navigation.logger.warning = original_warning
        return said

    def test_the_shape_upstream_has_today_says_nothing(self):
        self.assertEqual([], self.warnings())

    def test_a_frame_upstream_declines_says_nothing(self):
        """Off the page upstream returns before tapping, and a live run logged the warning on every such frame."""
        install(ANOTHER_TAB)
        said = []
        original_warning = navigation.logger.warning
        navigation.logger.warning = lambda message, *args, **kwargs: said.append(message)
        try:
            navigation.reading_in_place(lambda task: False)(FakeTask())
        finally:
            navigation.logger.warning = original_warning
        self.assertEqual([], said)

    def test_a_moved_tab_tap_is_reported(self):
        """The skip would quietly stop saving anything, which is the failure nobody would notice."""
        said = self.warnings(tab=(0.250, 0.056))
        self.assertEqual(1, len(said))
        self.assertIn("dropped 0 and 1", said[0])

    def test_a_second_box_click_is_reported(self):
        """This is the sharper one: a tap upstream needed would have been swallowed."""
        said = self.warnings(extra_boxes=1)
        self.assertEqual(1, len(said))
        self.assertIn("dropped 1 and 2", said[0])


class TestSortieTeamTrip(unittest.TestCase):
    """Sortie taps through to the team once a run, and the new run's roster replaces the old party."""

    def setUp(self):
        restoring_modules(self)

    def test_each_run_taps_through_once_and_reads_its_own_party(self):
        install(ON_THE_TAB)
        utils = sys.modules["utils"]
        on_map = [False]
        utils._get_current_hp_percent = lambda task: 100 if on_map[0] else False
        utils._move_and_click = lambda task, x, y: task.clicks.append((x, y))
        task = FakeTask()
        task.sleep = lambda seconds: None
        task.info_set = lambda key, value: None
        task.node_status = {}
        clock = [0.0]

        task.width, task.height = WIDTH, HEIGHT

        with mock.patch.object(navigation.time, "monotonic", lambda: clock[0]):
            self.assertFalse(navigation.handle_open_team(task), "off the map there is nothing to tap")
            on_map[0] = True
            # Live, the portraits were tapped over the end turn prompt, which ended a turn with a card still playable.
            task.all_texts = [FakeBox("取消", 0.34, 0.60)]
            self.assertFalse(navigation.handle_open_team(task))
            # A restart on a battle screen still reads the team, but once the turn has pressed anything it asks the next turn for a frame.
            task.all_texts = [FakeBox("04/10", 0.5, 0.97)]
            setattr(task, TURN, battle.Turn(4))
            getattr(task, TURN).ended = True
            self.assertFalse(navigation.handle_open_team(task))
            self.assertTrue(getattr(task, battle.TEAM_WANTED))
            delattr(task, TURN)
            # Live, the health bar read as "1728 /1728", which upstream's own read fails on.
            on_map[0] = False
            self.assertTrue(navigation.handle_open_team(task))
            on_map[0] = True
            # A pending dialog swallowed the tap, and its own handler needs the next frames to clear it.
            self.assertFalse(navigation.handle_open_team(task))
            # Once it has, the team is tapped for again, but not past `TEAM_TRIES`.
            for _ in range(navigation.TEAM_TRIES - 1):
                clock[0] += navigation.TEAM_RETRY_SECONDS
                self.assertTrue(navigation.handle_open_team(task))
            clock[0] += navigation.TEAM_RETRY_SECONDS
            self.assertFalse(navigation.handle_open_team(task))
            self.assertEqual([navigation.TEAM_PORTRAITS] * navigation.TEAM_TRIES, task.clicks)
            task.clicks.clear()

            # Upstream rebuilds `node_status` for the next run, and the last run's party must not outlive it.
            task.node_status = {}
            setattr(task, PARTY, frozenset({"Yuki"}))
            self.assertTrue(navigation.handle_open_team(task))
            self.assertEqual(frozenset(), getattr(task, PARTY))
            self.assertEqual([navigation.TEAM_PORTRAITS], task.clicks)

            rewards.remember_team(task, utils)
            self.assertEqual({"Arabella", "Veronica", "Mika"}, getattr(task, PARTY))
            # The page shows three names, so after a restart a drafted fourth comes from their cards in the deck read on the same trip.
            task.node_status[piles.READ] = True
            with mock.patch.dict(cards.COPIES, {"Hunting Instincts": {}, "Arcane Rush": {}}, clear=True):
                rewards.remember_team(task, utils)
            self.assertEqual({"Arabella", "Veronica", "Mika", "Hugo"}, getattr(task, PARTY))
            clock[0] += navigation.TEAM_RETRY_SECONDS
            self.assertFalse(navigation.handle_open_team(task), "a team read stops the retries")

    def test_the_deck_is_read_just_before_the_page_closes(self):
        # Live, the read opened All Piles first and needed a tap back to the Combatants tab before the team could be read.
        utils_chaos = install(ON_THE_TAB)
        capture = piles.reading_the_deck(upstream_capture(utils_chaos), utils_chaos)
        sortie, chaos, story = (type(mode, (FakeTask,), {})() for mode in ("SortieMode", "ChaosMode", "StoryMode"))
        for task in (sortie, chaos, story):
            task.node_status, task.all_texts = {}, ["Owen"]

        def read_deck(task, utils):
            task.clicks.append("deck")
            task.all_texts = ["All Piles"]

        with standing_in(piles, read_deck=read_deck):
            for task in (sortie, sortie, chaos, chaos, story):
                capture(task)
        for task in (sortie, chaos):
            with self.subTest(mode=type(task).__name__):
                self.assertEqual([navigation.COMBATANTS_TAB, "deck", CLOSE_PAGE] + [navigation.COMBATANTS_TAB, CLOSE_PAGE], task.clicks)
                self.assertEqual(["Owen"], task.all_texts, "the team read after the capture takes its names from the Combatants pass")
        self.assertNotIn("deck", story.clicks)
        # Upstream rebuilds `node_status` as a layer starts, so the next layer's trip reads the deck again.
        chaos.node_status, chaos.clicks = {}, []
        with standing_in(piles, read_deck=read_deck):
            capture(chaos)
        self.assertEqual([navigation.COMBATANTS_TAB, "deck", CLOSE_PAGE], chaos.clicks)


    def test_a_pick_changes_the_deck_in_chaos_too(self):
        # The pickers Chaos shares with Sortie keep the deck read current until the next layer reads it again.
        base = DESCRIPTIONS["Experienced Strike"]
        module = types.SimpleNamespace(recognize_cards=lambda task: [{"name": "Experienced Strike", "description": base, "x": 0.3, "y": 0.4}])

        def take_one(task):
            card = module.recognize_cards(task)[0]
            task.click(card["x"], card["y"])

        self.addCleanup(cards.use_deck, {})
        for mode, held in (("ChaosMode", 2), ("StoryMode", 1)):
            with self.subTest(mode=mode):
                cards.use_deck({"Experienced Strike": [base]})
                piles.following(take_one, module, piles.GAINED)(type(mode, (), {"click": lambda self, x, y: None})())
                self.assertEqual(held, cards.COPIES["Experienced Strike"][base])


class TestChaosTeamTrip(unittest.TestCase):
    """Chaos opens the page once a layer: upstream's own trip on a task's first layer, the fork's on every later one, never both."""

    def setUp(self):
        restoring_modules(self)
        install(ON_THE_TAB)
        self.utils = sys.modules["utils"]
        self.utils._get_current_hp_percent = lambda task: 100
        self.utils._move_and_click = lambda task, x, y: task.clicks.append((x, y))
        task = type("ChaosMode", (FakeTask,), {})()
        task.sleep = lambda seconds: None
        task.info_set = lambda key, value: None
        task.node_status, task.all_texts = {}, []
        task.width, task.height = WIDTH, HEIGHT
        self.task = task
        self.clock = [0.0]
        patcher = mock.patch.object(navigation.time, "monotonic", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_the_page(self):
        """Stand in for the archive handler on the page just opened: the deck read marks the layer and the team read names the party."""
        self.task.node_status[piles.READ] = True
        rewards.remember_team(self.task, self.utils)

    def test_the_layer_upstream_opened_gets_no_second_trip(self):
        # A task's first layer: upstream's `handle_save_target_member` tapped, and the page was read and closed.
        self.read_the_page()
        for _ in range(navigation.TEAM_TRIES + 1):
            self.assertFalse(navigation.handle_open_team(self.task))
            self.clock[0] += navigation.TEAM_RETRY_SECONDS
        self.assertEqual([], self.task.clicks)

    def test_a_layer_whose_page_named_nobody_is_not_opened_again(self):
        # The page was read, so a second trip would read no deck, and the next layer reads the team again.
        self.task.node_status[piles.READ] = True
        self.assertFalse(navigation.handle_open_team(self.task))
        self.task.node_status = {}
        self.assertTrue(navigation.handle_open_team(self.task))
        self.task.node_status[piles.READ] = True
        self.clock[0] += navigation.TEAM_RETRY_SECONDS
        self.assertFalse(navigation.handle_open_team(self.task))
        self.assertFalse(navigation.team_pending(self.task), "Obtain Card must not wait on a team no trip will read")
        self.assertEqual([navigation.TEAM_PORTRAITS], self.task.clicks)

    def test_the_page_upstream_opened_is_not_tapped_before_its_read(self):
        # A task's first layer: upstream's trip has the page open and unread. It draws no health readout and no hand counter, so no tap lands on it.
        self.utils._get_current_hp_percent = lambda task: False
        self.assertFalse(navigation.handle_open_team(self.task))
        self.assertEqual([], self.task.clicks)
        self.assertNotIn(navigation.TEAM_TAPPED, self.task.node_status, "no try is spent on the page")

    def test_ours_tapping_first_still_makes_one_trip(self):
        # Should a frame reach the fork's tap before upstream's, the page that opens is read once and nobody taps again.
        self.assertTrue(navigation.handle_open_team(self.task))
        self.read_the_page()
        self.clock[0] += navigation.TEAM_RETRY_SECONDS
        self.assertFalse(navigation.handle_open_team(self.task))
        self.assertEqual([navigation.TEAM_PORTRAITS], self.task.clicks)

    def test_each_later_layer_taps_through_once(self):
        self.read_the_page()
        # Upstream rebuilds `node_status` for the next layer and keeps its own "portrait saved" flag, so its trip does not come again.
        self.task.node_status = {"save_target_member": True}
        self.assertTrue(navigation.handle_open_team(self.task))
        self.assertEqual(frozenset(), getattr(self.task, PARTY), "the next layer's party is read afresh")
        self.read_the_page()
        self.clock[0] += navigation.TEAM_RETRY_SECONDS
        self.assertFalse(navigation.handle_open_team(self.task))
        self.assertEqual([navigation.TEAM_PORTRAITS], self.task.clicks)

    def test_the_trip_goes_in_both_lists_after_upstreams_own(self):
        installs = []
        modes = Modes(
            utils_chaos=[named("handle_auto_stop"), named("handle_save_target_member"), named("handle_route_selection"),
                         named("handle_archive_target_member")],
            utils_sortie=[named("handle_auto_stop"), named("handle_route_selection"), named("handle_archive_target_member")],
            utils_story=[named("handle_route_selection")],
        )
        with modes as loaded, mock.patch.object(navigation, "_patched", False), mock.patch.object(navigation, "register", installs.append):
            module = loaded["utils_chaos"]
            for handler in module.PAGE_HANDLERS[1:]:
                setattr(module, handler.__name__, handler)
            navigation.apply()
            installs[0]()
        chaos = names(loaded["utils_chaos"])
        self.assertEqual(chaos.index("handle_route_selection") - 1, chaos.index("handle_open_team"))
        # navigation.py stands upstream's handler in under its own name, so it is found by the end of that name.
        upstream = next(index for index, name in enumerate(chaos) if name.endswith("handle_save_target_member"))
        self.assertLess(upstream, chaos.index("handle_open_team"))
        self.assertEqual(["handle_auto_stop", "handle_open_team", "handle_route_selection", "handle_archive_target_member"],
                         names(loaded["utils_sortie"]))
        self.assertNotIn("handle_open_team", names(loaded["utils_story"]))


class TestStartingUnread(unittest.TestCase):
    """A mode starts with no team or deck, so nothing an earlier task read is taken for this one's."""

    def tearDown(self):
        cards.use_deck({})

    @staticmethod
    def read_task():
        """Build a mode carrying an earlier task's reads, and fill the deck the same way."""
        cards.use_deck({"Experienced Strike": {SHIELD_GAIN}}, {"Experienced Strike": 1})
        task = FakeTask()
        setattr(task, PARTY, frozenset({"Yuki"}))
        setattr(task, TEAM_NAMES, ["Yuki"])
        setattr(task, rewards.TEAM, {"Striker"})
        return task

    def assert_unread(self, task):
        self.assertEqual(({}, {}, {}), (cards.COPIES, cards.DECK, cards.RETRIEVES))
        for name in (PARTY, TEAM_NAMES, rewards.TEAM):
            self.assertFalse(hasattr(task, name), name)

    def test_a_mode_starts_with_no_team_or_deck(self):
        started = []
        task = self.read_task()
        rewards.starting_unread(started.append)(task)
        self.assertEqual([task], started)
        self.assert_unread(task)

    def test_every_start_goes_through_it(self):
        from ok.task.task import BaseTask

        started = []
        with mock.patch.object(BaseTask, "enable", started.append), mock.patch.object(rewards, "_patched", False), \
                mock.patch.object(rewards, "register"):
            rewards.apply()
            task = self.read_task()
            BaseTask.enable(task)
        self.assertEqual([task], started)
        self.assert_unread(task)


class TestDeckRead(unittest.TestCase):
    """All Piles is read card by card, each card is taken for the version its text matches, and a card is valued by its weakest copy."""

    def tearDown(self):
        cards.use_deck({})

    def test_each_whole_card_is_taken_for_its_version(self):
        task = types.SimpleNamespace(width=WIDTH, height=HEIGHT, all_texts=[FakeBox(text, x, y, width=w, height=h, units="pixels")
                                                                           for text, x, y, w, h in PILES_PAGE])
        # A named card inside a text, or a card cut off at the bottom, would add a fifth. A broken match would land a copy on the base.
        self.assertEqual({
            ("Slash", next(iter(EPIPHANIES["Slash"]))),
            ("Experienced Strike", DESCRIPTIONS["Experienced Strike"]),
            ("Experienced Strike", SHIELD_GAIN),
            ("Hew", DESCRIPTIONS["Hew"]),
        }, {(name, piles.version_of(name, text)) for name, text, _ in piles.cards_on_page(task)})

    def test_a_card_is_valued_by_its_weakest_copy(self):
        base, stronger = cards.figures(DESCRIPTIONS["Experienced Strike"]), cards.figures(SHIELD_GAIN)
        self.assertLess(base.damage, stronger.damage)
        cards.use_deck({"Experienced Strike": {SHIELD_GAIN}})
        self.assertEqual(stronger, cards.features("Experienced Strike"))
        # A second read replaces the first, which a stale cache of the figures would hide.
        cards.use_deck({"Experienced Strike": {SHIELD_GAIN, DESCRIPTIONS["Experienced Strike"]}})
        self.assertEqual(base, cards.features("Experienced Strike"))

    def test_only_a_retrieve_tag_counts(self):
        # The first two were read live off All Piles. The others apply Retrieve to other cards, which leaves the card itself without one.
        for text, expected in (("[Retrieve 2/Exhaust 396%ShieldIncinerate", "2"), ("[Retrieve] 100% Damage", ""),
                               (DESCRIPTIONS["Harmonization: Spirit Kefox"], None), (DESCRIPTIONS["Spirit Kefox"], None)):
            with self.subTest(text):
                found = piles.RETRIEVE.search(text)
                self.assertEqual(expected, found and found.group(1))

    def test_each_copy_keeps_its_own_retrieves(self):
        # Two copies on one page are 4 returns, not 2. The next page shows the lower copy again, which must not make it 6.
        herb, text = "Harmonization: Residual Herb", "[Retrieve 2/Exhaust 3]96% Shield"
        pages = iter([[(herb, text, 100), (herb, text, 300)], [(herb, text, 50)], [(herb, text, 50)]])
        with standing_in(piles, raw_ocr=lambda task: None, cards_on_page=lambda task: next(pages)):
            _, retrieves = piles.read_piles(None, types.SimpleNamespace(_scroll_card_page=lambda *args: None))
        self.assertEqual({herb: 4}, retrieves)

    def test_a_divine_epiphany_keeps_its_lines(self):
        # Read live off a card holding Diallos's Epiphany, its lines out of order. Without them the deck stored the plain base.
        text = ("Exhaust ]higher non-Unique DellangCreate 1 random 1-Cost orFor 1 turn, change Cost ofShop card(s)those cards to 0Morale 1"
                "*Create 2. Activation Core")
        base = DESCRIPTIONS["Mutation: Prepare for Battle"]
        self.assertEqual(f"{base}\nMorale 1\nCreate 2 Activation Core", piles.version_of("Mutation: Prepare for Battle", text))



class TestEpiphanyChoice(unittest.TestCase):
    """A Sortie or Chaos Epiphany goes on a card even when the user listed none, and every other choice is left to the pins and the user's lists."""

    def tearDown(self):
        cards.use_deck({})

    def use_sparked_deck(self, annoying=(DESCRIPTIONS["Annoying"],)):
        """Read a deck where Sacred Censer and Growing Creature carry an Epiphany, and Annoying the given versions."""
        cards.use_deck({name: {next(iter(EPIPHANIES[name]))} for name in ("Sacred Censer", "Growing Creature")} | {"Annoying": set(annoying)})

    def choose_through_pages(self, pages, listed=()):
        """Run a Chaos Epiphany through upstream's paging and list match, then Skip once no page matched.

        On each page every listed name in turn taps the first card, in page order, whose name holds it or is held in it.

        Args:
            pages: The card names on each page, in the order the scroll reads them.
            listed: The user's own Epiphany list.

        Returns:
            The name of the card tapped, or "Skip".
        """
        reads = iter(pages)
        utils = types.SimpleNamespace(recognize_cards_in_deck=lambda task, page="": [{"name": name} for name in next(reads)])

        def select_card(task, names, count=1, action=""):
            for _ in pages:
                offered = [card["name"] for card in utils.recognize_cards_in_deck(task)]
                tapped = next((card for name in names for card in offered if name.strip() in card.strip() or card.strip() in name.strip()), None)
                if tapped:
                    return tapped
            return "Skip"

        return epiphany.choosing(select_card, utils)(type("ChaosMode", (), {})(), list(listed), action=epiphany.ACTIONS[0])

    def test_a_card_with_an_epiphany_is_never_ranked(self):
        # The three cards a Sortie run offered, where the deck read had found Epiphanies on the first two.
        self.use_sparked_deck()
        self.assertEqual(["Annoying"], epiphany.ranked([{"name": "Sacred Censer"}, {"name": "Growing Creature"}, {"name": "Annoying"}]))

    def test_a_later_page_gives_the_card_without_one(self):
        self.use_sparked_deck()
        self.assertEqual("Annoying", self.choose_through_pages([["Sacred Censer", "Growing Creature"], ["Annoying"]]))

    def test_only_cards_with_one_leave_it_to_skip(self):
        self.use_sparked_deck()
        self.assertEqual("Skip", self.choose_through_pages([["Sacred Censer"], ["Growing Creature"]]))

    def test_one_copy_with_an_epiphany_keeps_the_name_off(self):
        # Upstream taps by name, so the tap could land on the copy that carries it.
        self.use_sparked_deck(annoying=(DESCRIPTIONS["Annoying"], next(iter(EPIPHANIES["Annoying"]))))
        self.assertEqual("Skip", self.choose_through_pages([["Annoying"]]))

    def test_a_listed_card_with_one_is_still_the_users_choice(self):
        self.use_sparked_deck()
        self.assertEqual("Sacred Censer", self.choose_through_pages([["Annoying", "Sacred Censer"]], listed=["Sacred Censer"]))

    def test_a_name_inside_a_card_with_one_taps_nothing(self):
        # Haru's cards: upstream would tap whichever of the two comes first for either name.
        for sparked, fresh in (("Anchor Shot", "Anchor"), ("Anchor", "Anchor Shot")):
            with self.subTest(sparked=sparked):
                cards.use_deck({sparked: {next(iter(EPIPHANIES[sparked]))}, fresh: {DESCRIPTIONS[fresh]}})
                self.assertEqual("Skip", self.choose_through_pages([[sparked, fresh]]))

    def test_a_card_clear_of_the_collision_is_still_chosen(self):
        # Anchor is the stronger card, so it would be named first and tap Anchor Shot.
        cards.use_deck({"Anchor Shot": {next(iter(EPIPHANIES["Anchor Shot"]))}, "Anchor": {DESCRIPTIONS["Anchor"]},
                        "Annoying": {DESCRIPTIONS["Annoying"]}})
        self.assertEqual("Annoying", self.choose_through_pages([["Anchor Shot", "Anchor", "Annoying"]]))

    def test_no_card_is_named_before_the_first_deck_read(self):
        self.assertEqual([], epiphany.ranked([{"name": "Annoying"}, {"name": "Anchor"}]))
        self.assertEqual("Skip", self.choose_through_pages([["Annoying"]]))
        self.assertEqual("Annoying", self.choose_through_pages([["Annoying"]], listed=["Annoying"]))

    def test_a_sortie_or_chaos_epiphany_is_chosen(self):
        cards.use_deck({"Annoying": {DESCRIPTIONS["Annoying"]}})
        utils = types.SimpleNamespace(recognize_cards_in_deck=lambda task, page="": [{"name": "Annoying"}])
        passed = []

        def select_card(task, names, count=1, action=""):
            # Upstream reads the page before matching the names, so the names are taken after the read.
            utils.recognize_cards_in_deck(task)
            passed.append(list(names))

        choose = epiphany.choosing(select_card, utils)
        for mode, action, expected in (
            ("SortieMode", epiphany.ACTIONS[0], ["Slash", "Annoying"]),
            ("ChaosMode", epiphany.ACTIONS[1], ["Slash", "Annoying"]),
            ("StoryMode", epiphany.ACTIONS[0], ["Slash"]),
            ("ChaosMode", "", ["Slash"]),
        ):
            with self.subTest(mode=mode, action=action):
                passed.clear()
                choose(type(mode, (), {})(), ["Slash"], action=action)
                self.assertEqual([expected], passed)


if __name__ == "__main__":
    unittest.main()
