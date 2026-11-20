"""Check that the Chaos start page and Zero System Codices are rerolled for a blacklisted modifier, within what may be spent.

The panel boxes are the OCR of the Celestial Bulwark start page on the Global client, 2026-10-29, and of the Zero System
screens, 2026-11-19.
"""

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en.reobserve import MODIFIER_BLACKLIST, REOBSERVE, SAVE_LIMIT_KEY, modifiers_in, reobserving  # noqa: E402
from src.en.zero_system import (ANY, CHAOS_MERGE, CODEX, CODEX_MERGE, CODEX_SEASON, CONFIRM, MAX_MERGES, NORMAL_MERGE, REROLL, SLOTS,  # noqa: E402
                                hunt_of, judge, merge_handler, obtained_handler, select_handler)
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

TITLE = FakeBox("Chaos", 0.117, 0.046, units="fraction")
REOBSERVE_BUTTON = FakeBox("Re-observe", 0.773, 0.794, width=180, units="fraction")
COST = FakeBox("10", 0.955, 0.794, units="fraction")
# The top bar: the Loot Certification count, the event currency, and a stray icon read as a digit beside it.
TOP_BAR = [FakeBox("0/4+", 0.703, 0.045, units="fraction"), FakeBox("434", 0.846, 0.048, units="fraction"), FakeBox("0", 0.899, 0.052, units="fraction")]
# Difficulty VI: four modifiers, the last one's description running off the bottom of the panel.
ANXIETY_PLAGUE = [
    FakeBox("- Save Data Storage Limit 140pt", 0.805, 0.400, width=500, units="fraction"),
    FakeBox("[Anxiety 1] Cannot rest in Safe Zone", 0.827, 0.543, width=560, units="fraction"),
    FakeBox("[Elite 3]: Add 6 Elite Areas", 0.793, 0.584, width=420, units="fraction"),
    FakeBox("[Plague 1]Decrease Max HP by 50%", 0.827, 0.626, width=560, units="fraction"),
    FakeBox("Tyrant 2: Increase Attack and Health of", 0.834, 0.667, width=580, units="fraction"),
    FakeBox("monsters in Elite and Boss Areas by", 0.824, 0.700, width=560, units="fraction"),
]
# Difficulty VII: Tyrant alone, whose wrapped second line names Elite Areas.
TYRANT_ONLY = [
    FakeBox("- Save Data Storage Limit 120pt", 0.806, 0.402, width=500, units="fraction"),
    FakeBox("Tyrant 3: Increase Attack and Health of", 0.836, 0.543, width=580, units="fraction"),
    FakeBox("monsters in Elite and Boss Areas by", 0.825, 0.576, width=560, units="fraction"),
    FakeBox("30%", 0.726, 0.606, units="fraction"),
]
# Difficulty X, its OCR gluing the Loss tag to its percentage.
NEGLECT_LOSS_GANGRENE = [
    FakeBox("- Save Data Storage Limit 140pt", 0.805, 0.400, width=500, units="fraction"),
    FakeBox("[Neglect 1] Discard 1 card randomly at", 0.834, 0.543, width=580, units="fraction"),
    FakeBox("the start of each turn", 0.778, 0.575, width=320, units="fraction"),
    FakeBox("[Loss 1]-40% Credits gained from", 0.821, 0.617, width=500, units="fraction"),
    FakeBox("battle", 0.730, 0.649, units="fraction"),
    FakeBox("[Gangrene 1] At the start of each turn", 0.830, 0.690, width=580, units="fraction"),
]


class FakeTask:
    """The Chaos start page, recording the boxes clicked on it."""

    def __init__(self, boxes, **config):
        self.all_texts = boxes
        self.width, self.height = WIDTH, HEIGHT
        self.config = {SAVE_LIMIT_KEY: 0, REOBSERVE: True, MODIFIER_BLACKLIST: ["Anxiety", "Plague"], **config}
        self.clicked = []

    def click_box(self, box, *args, **kwargs):
        self.clicked.append(box)

    def log_info(self, message):
        pass

    def sleep(self, seconds):
        pass


# Upstream's config reader, as far as this handler leans on it.
UTILS_CHAOS = types.SimpleNamespace(_get_config_value=lambda task, key, default: task.config.get(key, default))


def start_page(panel, currency=TOP_BAR, **config):
    return FakeTask([TITLE, *currency, *panel, REOBSERVE_BUTTON, COST], **config)


class TestReobserve(unittest.TestCase):

    def test_only_a_tag_opening_a_line_counts_as_a_modifier(self):
        """Tyrant's wrapped line names Elite Areas, which would blacklist every Tyrant roll for someone avoiding Elite."""
        for panel, expected in ((ANXIETY_PLAGUE, ["Anxiety", "Elite", "Plague", "Tyrant"]), (TYRANT_ONLY, ["Tyrant"]),
                                (NEGLECT_LOSS_GANGRENE, ["Neglect", "Loss", "Gangrene"])):
            with self.subTest(expected=expected):
                self.assertEqual(expected, modifiers_in([box.name for box in panel]))

    def test_each_start_page(self):
        upstream = []
        handler = reobserving(lambda task: upstream.append(task) or "upstream", UTILS_CHAOS)
        cases = (
            ("blacklisted and affordable", start_page(ANXIETY_PLAGUE), True, [REOBSERVE_BUTTON]),
            ("blacklisted but broke", start_page(ANXIETY_PLAGUE, currency=[FakeBox("9", 0.846, 0.048, units="fraction")]), False, []),
            ("currency unread", start_page(ANXIETY_PLAGUE, currency=[]), False, []),
            ("switched off", start_page(ANXIETY_PLAGUE, **{REOBSERVE: False}), False, []),
            ("nothing blacklisted", start_page(NEGLECT_LOSS_GANGRENE), False, []),
            # The save limit still re-observes with the blacklist off, as upstream's own rule.
            ("save limit too low", start_page(TYRANT_ONLY, **{SAVE_LIMIT_KEY: 140, REOBSERVE: False}), True, [REOBSERVE_BUTTON]),
        )
        for label, task, claimed, clicked in cases:
            with self.subTest(label):
                self.assertEqual(claimed, handler(task))
                self.assertEqual(clicked, task.clicked)
        self.assertEqual([], upstream)

    def test_a_page_without_the_english_title_and_button_is_left_to_upstream(self):
        """The Chinese clients still re-observe through upstream's own literals, and a Re-observe on another screen is not pressed."""
        for label, boxes in (("Chinese client", [TITLE, FakeBox("再次观测", 0.773, 0.794, units="fraction")]), ("no title", [REOBSERVE_BUTTON])):
            with self.subTest(label):
                task = FakeTask([*TOP_BAR, *ANXIETY_PLAGUE, *boxes, COST])
                self.assertEqual("upstream", reobserving(lambda task: "upstream", UTILS_CHAOS)(task))
                self.assertEqual([], task.clicked)



def at(name, x, y):
    """Place a box sized to its text, the way OCR boxes a line."""
    return FakeBox(name, x, y, width=11 * len(name), units="fraction")


# Codex Obtained after merging The Kaleidoscope Hatchery: the season only on the third card, and every list cut off.
OBTAINED = [
    at("Codex Obtained", 0.501, 0.099), at("9,363", 0.751, 0.048), at("4780K", 0.885, 0.048),
    at("Kaleidoscope", 0.124, 0.255), at("Hatchery", 0.107, 0.293), at("orb acquisition increased by 90%", 0.169, 0.399),
    at("· Save Data Storage Limit 130pt", 0.161, 0.489), at("· Tyrant 2: Increase Attack and Health of", 0.187, 0.616),
    at("·[Loss 3] -60% Credits gained from", 0.174, 0.707), at("· [Plague 1] Decrease Max HP by 50%", 0.180, 0.773),
    at("Kaleidoscope", 0.438, 0.255), at("Hatchery", 0.420, 0.292), at("· Save Data Storage Limit 120pt", 0.474, 0.489),
    at("[Revenge 2] Each time a monster dies,", 0.498, 0.615), at("[Gangrene 2] At the start of each turn", 0.497, 0.680),
    at(" [Plague 1] Decrease Max HP by 30%", 0.494, 0.773),
    at("Kaleidoscope", 0.749, 0.255), at("Hatchery", 0.732, 0.293), at(" Shattered Light and Claw", 0.779, 0.457),
    at("· Save Data Storage Limit 130pt", 0.786, 0.588), at(" [Neglect 1] Discard 1 card randomly at", 0.811, 0.713),
    at("· Tyrant 3: Increase Attack and Health of", 0.813, 0.780),
    at("28800", 0.265, 0.920), at("Normal Merge", 0.099, 0.921), at("60", 0.576, 0.922), at("Chaos Merge", 0.394, 0.922),
    at("Confirm", 0.881, 0.923),
]
# Merge Codices for Theater of Illusions, the list scrolled down to Laboratory 0 through Hatchery.
MERGE_THEATER = [
    at("Merge Codices", 0.151, 0.047), at("9,423", 0.704, 0.048), at("4780K", 0.838, 0.049),
    at("The Foretold Ruin", 0.118, 0.129), at(" Laboratory 0", 0.096, 0.296), at("Burning Life", 0.095, 0.463),
    at("Theater of llusions", 0.125, 0.631), at("The Kaleidoscope Hatehery", 0.146, 0.800),
    at("Theater of llusions", 0.705, 0.395), at(" A Song Rippling Through the Stars", 0.655, 0.465),
    at(" Chaos Merge", 0.819, 0.811), at("10", 0.247, 0.923), at("Normal Merge", 0.445, 0.922), at("57600", 0.609, 0.921),
    at("Chaos Merge", 0.756, 0.922), at("120", 0.935, 0.921),
]
SELECT_CAPTION = at("Select Codex", 0.094, 0.243)
# The three slots on Select Codex, none of them a Hatchery.
SLOT_PANELS = [
    [at("The Foretold", 0.759, 0.179), at("Ruin", 0.721, 0.220), at("Promise Upon the Snow", 0.792, 0.409),
     at("· Save Data Storage Limit 140pt", 0.806, 0.591), at("Tyrant 3: Increase Attack and Health of", 0.835, 0.736)],
    [at("Swamp of", 0.746, 0.179), at("Judgment", 0.747, 0.222), at(" A Song Rippling Through the Stars", 0.828, 0.410),
     at("· Save Data Storage Limit 150pt", 0.806, 0.628), at("[Gangrene 2] At the start of each turn", 0.831, 0.769)],
    [at("City of Mist", 0.754, 0.222), at(" A Song Rippling Through the Stars", 0.828, 0.410),
     at("· Save Data Storage Limit 170pt", 0.805, 0.628), at("Tyrant 4: Increase Attack and Health of", 0.836, 0.771)],
]


class ZeroSystemTask(FakeTask):
    """A Zero System screen, recording taps by point and scrolls, and showing `hidden` once a list is scrolled."""

    def __init__(self, boxes, hidden=(), **config):
        super().__init__(boxes, **{SAVE_LIMIT_KEY: 130, MODIFIER_BLACKLIST: ["Plague"], CODEX: "The Kaleidoscope Hatchery",
                                   CODEX_SEASON: "Shattered Light and Claw", CODEX_MERGE: NORMAL_MERGE, MAX_MERGES: 10, **config})
        self.hidden = list(hidden)
        self.tapped = []

    def ocr(self):
        return self.all_texts + self.hidden


def tapping(task, x, y):
    task.tapped.append((round(x, 3), round(y, 3)))
    # On Select Codex a slot tap shows that slot's Codex.
    if (x, y) in SLOTS and task.all_texts[:1] == [SELECT_CAPTION]:
        task.all_texts = [SELECT_CAPTION, *SLOT_PANELS[SLOTS.index((x, y))]]


ZERO_UTILS_CHAOS = types.SimpleNamespace(_get_config_value=UTILS_CHAOS._get_config_value, _move_and_click=tapping)
ZERO_UTILS = types.SimpleNamespace(_scroll_card_page=lambda task, x, y, amount, page: task.tapped.append(("scroll", amount)))


class TestZeroSystem(unittest.TestCase):

    def test_codex_obtained(self):
        """Only the third card carries the season and no Plague. A Codex is passed only once its cut-off modifiers are read too."""
        handler = obtained_handler(ZERO_UTILS_CHAOS, ZERO_UTILS)
        third = [(0.812, 0.59), CONFIRM]
        cases = (
            ("the fitting card is taken", {}, [], third),
            ("a hidden blacklisted line sends it back to merge", {}, [at("[Plague 2] Decrease Max HP by 40%", 0.8, 0.7)], []),
            ("none fit, so merge again", {SAVE_LIMIT_KEY: 140}, [], []),
            ("none fit at the cap, so the best is taken", {SAVE_LIMIT_KEY: 140, MAX_MERGES: 0}, [], third),
        )
        for label, config, hidden, taps in cases:
            with self.subTest(label):
                task = ZeroSystemTask(OBTAINED, hidden, **config)
                self.assertTrue(handler(task))
                self.assertEqual(taps, [tap for tap in task.tapped if tap[0] != "scroll"])
                self.assertEqual([] if taps else ["Normal Merge"], [box.name for box in task.clicked])
        # A season and a God box push the third card's save limit below the cut, so it is only read off the scroll.
        limit = at("· Save Data Storage Limit 130pt", 0.786, 0.588)
        task = ZeroSystemTask([box for box in OBTAINED if (box.name, box.x) != (limit.name, limit.x)], [limit])
        self.assertTrue(handler(task))
        self.assertEqual(third, [tap for tap in task.tapped if tap[0] != "scroll"])

    def test_merge_codices(self):
        """The Chaos Merge info label above the row carries the button's own words, and the list scrolls toward the row it wants."""
        handler = merge_handler(ZERO_UTILS_CHAOS, ZERO_UTILS)
        cases = (
            ("an off-screen Chaos above scrolls up", {CODEX: "The Blue Pot"}, [("scroll", 3)], []),
            ("a Chaos on screen is tapped", {CODEX: "Burning Life"}, [], [("Burning Life", 0.463)]),
            ("a tied season is left alone", {CODEX: ANY, CODEX_SEASON: "A Promise Upon the Snow"}, [], [(NORMAL_MERGE, 0.922)]),
            ("orbs on the button row", {CODEX: ANY, CODEX_SEASON: ANY, CODEX_MERGE: CHAOS_MERGE}, [], [(CHAOS_MERGE, 0.922)]),
            ("Credits read in thousands", {CODEX: ANY, CODEX_SEASON: ANY}, [], [(NORMAL_MERGE, 0.922)]),
        )
        for label, config, taps, clicked in cases:
            with self.subTest(label):
                task = ZeroSystemTask(MERGE_THEATER, **config)
                self.assertTrue(handler(task))
                self.assertEqual(taps, task.tapped)
                self.assertEqual(clicked, [(box.name, round((box.y + box.height / 2) / HEIGHT, 3)) for box in task.clicked])

    def test_merge_codices_picks_a_free_season_off_the_strip(self):
        task = ZeroSystemTask([at("The Blue Pot", 0.679, 0.395) if box.name == "Theater of llusions" and box.x > WIDTH / 2 else box for box in MERGE_THEATER],
                              **{CODEX: ANY, CODEX_SEASON: "A Promise Upon the Snow"})
        self.assertTrue(merge_handler(ZERO_UTILS_CHAOS, ZERO_UTILS)(task))
        self.assertEqual([(0.298, 0.799)], task.tapped)

    def test_merge_codices_goes_back_once_it_cannot_pay(self):
        task = ZeroSystemTask([box for box in MERGE_THEATER if box.name != "9,423"] + [at("90", 0.704, 0.048)],
                              **{CODEX: ANY, CODEX_SEASON: ANY, CODEX_MERGE: CHAOS_MERGE})
        handler = merge_handler(ZERO_UTILS_CHAOS, ZERO_UTILS)
        self.assertFalse(handler(task))
        self.assertTrue(handler(task))
        self.assertEqual([(0.042, 0.046)], task.tapped)
        self.assertEqual([], task.clicked)

    def test_select_codex_checks_every_slot_rerolls_the_worst_then_enters_the_best(self):
        handler = select_handler(ZERO_UTILS_CHAOS, ZERO_UTILS)
        task = ZeroSystemTask([SELECT_CAPTION, *SLOT_PANELS[0]], **{MAX_MERGES: 1})
        while handler(task):
            self.assertLess(len(task.tapped), 10)
            if task.tapped[-1] == REROLL:
                hunt_of(task)["merges"] += 1
        # Every slot checked, the lowest save limit remerged, then the highest one entered once the merge is spent.
        self.assertEqual([SLOTS[0], SLOTS[1], SLOTS[2], SLOTS[0], REROLL, SLOTS[2]], task.tapped)

    def test_a_chaos_tied_to_another_season_is_let_off_the_season_check(self):
        task = ZeroSystemTask([], **{CODEX: ANY, CODEX_SEASON: "A Promise Upon the Snow"})
        for chaos, reasons in (("The Kaleidoscope Hatchery", []), ("The Blue Pot", ["season none is not A Promise Upon the Snow"])):
            with self.subTest(chaos):
                self.assertEqual(reasons, judge(task, chaos, None, 140, [], hunt_of(task), ZERO_UTILS_CHAOS).reasons)


if __name__ == "__main__":
    unittest.main()
