"""Check what the bot decides is worth buying and keeping."""

import contextlib
import sys
import types
import unittest
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

# The real module, so the Settlement check fails if upstream stops reading the claim setting the way the fork stands in for it.
import utils_chaos  # noqa: E402
import utils_sortie  # noqa: E402
# Held here rather than looked up by name, since other modules in the same run stand stubs in for it.
import utils  # noqa: E402

from src.en import cards, dashboard, handlers, loot_cards, navigation, piles, reason, rewards, spend_guard  # noqa: E402
from src.en.battle import PARTY  # noqa: E402
from src.en.dashboard import COMBATANTS as COMBATANTS_ROW  # noqa: E402
from src.en.game_data import COMBATANTS  # noqa: E402
from src.en.game_text import DESCRIPTIONS, EPIPHANIES  # noqa: E402
from src.en.overrides import FARMED_COMBATANT  # noqa: E402
from src.en.shop import TAKE_MONSTER_REWARDS  # noqa: E402
from src.en.game_quality import (  # noqa: E402
    CARD_CLASSES, CARD_RARITY, COMBATANT_CLASS, EQUIPMENT_RARITY, EQUIPMENT_SLOT,
)
from src.en.game_quality import COMBATANT_TAG_WEIGHTS, EQUIPMENT_TAGS  # noqa: E402
from src.en.hand_tags import HAND_TAGS  # noqa: E402
from src.en.handlers import standing_in  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402
from src.en.quality import (  # noqa: E402
    CLASS_NAMES, TAGS, WORTH_TAKING, fold, index, named, one_edit_apart, slot_of, sorted_letters, suits,
    team_classes, unconfused, usable_by, worth_taking,
)

# The shop, twice, exactly as the reader saw it.
SHOP_CARDS = ["Prepare forBattle", "Protectiveshout", "Tactical Action", "Wanderer of theVoid", "Shock"]
SHOP_EQUIPMENT = ["Cloud-WalkingShoes", "Sadism", "TacticalReformation", "Gladiator'sHelmet",
                  "Scout's CombatBoots", "Crimson Sword"]

# The game calls these a Vanguard and two Controllers.
TEAM = ["Nine", "Orlea", "Tiphera"]

# One Dellang Shop shelf and the Purchase Card screen that confirms buying from it, both exactly as the
# reader saw them in the run that looped between the two for seventy seconds.
LOOPING_SHELF = ["售罄", "Gauntlets of", "Protection", "Reorganize", "Rally", "Big Game Hunter", "技能",
                 "On sale", "200140", "105", "35", "96", "3/3", "免费", "Remaining: 5", "离开"]
LOOPING_PURCHASE = ["购买卡牌", "请选择要接受卡牌的主战员", "无法获得", "攻击力", "Reorganize", "防御力",
                    "技能", "LEVEL", "60", "等级", "[Exhaust ]", "Draw 3", "取消", "购买", "105"]
# A shelf card whose name the client wraps onto two lines, boxed exactly as OCR boxed it, and its Purchase Card screen.
# The two lines overlap by a pixel, and "Judgment" alone is another card's name.
WRAPPED_SHELF = [FakeBox("Instant", 1715, 700.5, width=98, height=33, units="pixels"),
                 FakeBox("Judgment", 1720, 735.5, width=140, height=39, units="pixels")]
WRAPPED_PURCHASE = ["购买卡牌", "Instant Judgment", "攻击力", "取消", "购买", "60"]


def unusable_by(classes):
    """Find a card worth buying that the given classes cannot hold.

    Args:
        classes: The team's classes.

    Returns:
        The name of a Legend or Unique card restricted away from them.
    """
    return next(name for name, restricted_to in CARD_CLASSES.items()
                if not set(restricted_to) & classes and CARD_RARITY.get(name) in WORTH_TAKING)


class FakeTask:
    """A task holding one OCR pass, the info table, and once the run has started the team."""

    def __init__(self, texts=(), team=None, info=None):
        # All on one row, so none reads as the two lines of one wrapped name.
        self.all_texts = [text if isinstance(text, FakeBox) else FakeBox(text, 0.5, 0.5) for text in texts]
        self.info = dict(info or {})
        if team is not None:
            setattr(self, rewards.TEAM, team)

    def info_set(self, key, value):
        self.info[key] = value


class TestRewardQuality(unittest.TestCase):

    def test_the_generated_data_covers_what_a_run_sees(self):
        self.assertGreater(len(CARD_RARITY), 800)
        self.assertGreater(len(EQUIPMENT_RARITY), 400)
        self.assertGreater(len(COMBATANT_CLASS), 40)
        self.assertGreater(len(EQUIPMENT_SLOT), 400)

    def test_a_typographic_apostrophe_still_matches(self):
        """The client writes Gladiator's with a curly apostrophe; nobody types that."""
        self.assertEqual(fold("Gladiator's Helmet"), fold("Gladiator’s Helmet"))

    def test_a_hidden_zero_width_space_still_matches(self):
        """One card name carries an invisible character, which an exact match would never find."""
        self.assertEqual(fold("Sadism"), fold("Sadism​"))

    def test_a_concatenated_reading_still_matches(self):
        """The reader joins words across line breaks, so the spacing cannot be trusted."""
        self.assertEqual(fold("Scout's Combat Boots"), fold("Scout's CombatBoots"))
        self.assertEqual(1, slot_of("Cloud-WalkingShoes"))

    def test_the_team_resolves_to_its_classes(self):
        self.assertEqual({"vanguard", "controller"}, team_classes(TEAM))

    def test_classes_are_logged_the_way_the_game_names_them(self):
        """A log in the data's own ids, rather than the names on screen, is one nobody recognises."""
        self.assertEqual(["Controller", "Vanguard"], named(team_classes(TEAM)))

    def test_every_class_in_the_data_has_an_in_game_name(self):
        """A class added by a future patch must be noticed here, not shipped as a raw id."""
        in_data = set(COMBATANT_CLASS.values()) | {c for cs in CARD_CLASSES.values() for c in cs}
        self.assertEqual(set(), in_data - set(CLASS_NAMES))

    def test_an_unknown_name_leaves_the_team_unknown(self):
        """An unreadable name must not silently narrow the team and filter out usable cards."""
        # Not a misreading of a real name: those are recovered now. This is a name that is simply not there.
        self.assertEqual(set(), team_classes(["Rewards cannot be obtained", "Skip"]))

    def test_only_the_best_grades_are_taken(self):
        """Rare is most of what a shop stocks; buying it is how a run ends with nothing."""
        taken = worth_taking(SHOP_CARDS, {"vanguard", "controller"})
        self.assertEqual(["Prepare for Battle"], taken)
        for name in taken:
            self.assertIn(CARD_RARITY[name], WORTH_TAKING)

    def test_equipment_is_graded_the_same_way(self):
        taken = worth_taking(SHOP_EQUIPMENT, {"vanguard", "controller"}, cards=False)
        self.assertEqual(["Cloud-Walking Shoes", "Crimson Sword"], taken)

    def test_a_card_no_one_can_hold_is_skipped(self):
        """The one thing the class data is good for: not paying for an unusable Legend."""
        ranger_only = unusable_by({"vanguard", "controller"})
        self.assertFalse(usable_by(ranger_only, {"vanguard", "controller"}))
        self.assertEqual([], worth_taking([ranger_only], {"vanguard", "controller"}))

    def test_an_unknown_team_filters_nothing(self):
        """Better to buy a card nobody can hold than to skip everything because a name was misread."""
        ranger_only = unusable_by({"vanguard", "controller"})
        self.assertTrue(usable_by(ranger_only, set()))

    def test_the_generated_list_holds_only_what_is_on_screen(self):
        """Offering all 625 good names would invite upstream's loose matching to pair the wrong ones."""
        task = FakeTask(SHOP_CARDS, {"vanguard", "controller"})
        generated = rewards.generated_list(task, rewards.CARD_KEY)
        self.assertEqual(["Prepare for Battle"], generated)
        self.assertLess(len(generated), 10)

    def test_a_free_upgrade_beats_skipping(self):
        # Live, a reward of Overpower, Mutation: Iron Wall and Distortion: Protective Shout was skipped whole.
        offer = ["Overpower", "Mutation: Iron Wall", "Distortion: Protective Shout"]
        for free, expected in ((True, ["Mutation: Iron Wall"]), (False, [])):
            with self.subTest(free=free):
                self.assertEqual(expected, rewards.generated_list(FakeTask(offer, set()), rewards.SORTIE_CARD_KEY, free=free))

    def test_a_reward_that_helps_while_held_is_taken_at_any_grade(self):
        # Live, a Rare Unknown: Mutant Sample was left out of the list, so a reward screen could never pick it.
        offer = ["Unknown: Mutant Sample", "Gale Strike", "Distortion: Hand-to-Hand Combat"]
        for free, expected in ((True, ["Gale Strike", "Unknown: Mutant Sample"]), (False, ["Gale Strike"])):
            with self.subTest(free=free):
                self.assertEqual(expected, rewards.generated_list(FakeTask(offer, set()), rewards.SORTIE_CARD_KEY, free=free))

    def test_a_monster_card_reward_is_left_while_its_switch_is_off(self):
        # Live, Chaos card rewards offered Evil Spirit Dullahan, a Legend Monster Card the auto-filled list took.
        offer = ["Evil Spirit Dullahan", "Gale Strike"]
        for takes, expected in ((True, ["Gale Strike", "Evil Spirit Dullahan"]), (False, ["Gale Strike"])):
            with self.subTest(takes=takes):
                reader = rewards.filling_in(lambda task, key, default: {TAKE_MONSTER_REWARDS: takes}.get(key, default), "utils", free=True)
                self.assertEqual(expected, reader(FakeTask(offer, set()), rewards.CARD_KEY, []))

    def test_a_card_the_deck_holds_ranks_after_one_it_lacks(self):
        # Live, a second Gale Strike was taken over Unknown: Mutant Sample because its rarity ranked it first.
        offer = ["Unknown: Mutant Sample", "Gale Strike", "Distortion: Hand-to-Hand Combat"]
        cards.use_deck({"Gale Strike": {""}})
        self.addCleanup(cards.use_deck, {})
        self.assertEqual(["Unknown: Mutant Sample", "Gale Strike"], rewards.generated_list(FakeTask(offer, set()), rewards.SORTIE_CARD_KEY, free=True))

    def test_obtain_card_waits_for_the_first_team_read(self):
        # Live, a run started on Obtain Card lost its first team tap and picked before the retry, knowing neither the team nor the deck.
        boxes = {rewards.OBTAIN_TITLE_AT: rewards.OBTAIN_TITLE, rewards.OBTAIN_TIP_AT: "请选择1张要获得的卡牌"}
        picked = []
        handler = rewards.after_the_team(lambda task: picked.append(task) or True, utils_sortie)
        cases = {"tapped, unread": (1, frozenset(), False), "tapped, read": (1, frozenset({"Owen"}), True),
                 "tries spent": (navigation.TEAM_TRIES, frozenset(), True)}
        with standing_in(utils_sortie, find_box_at_point=lambda task, x, y: types.SimpleNamespace(name=boxes.get((x, y), "")),
                         recognize_cards=lambda task, page: []):
            for case, (tries, party, picks) in cases.items():
                with self.subTest(case):
                    picked.clear()
                    task = types.SimpleNamespace(node_status={navigation.TEAM_TAPPED: (tries, 0.0)}, sleep=lambda seconds: None, **{PARTY: party})
                    self.assertTrue(handler(task))
                    self.assertEqual(picks, bool(picked))

    def test_obtain_card_waits_for_every_card_to_land(self):
        # Live, upstream read the first of three cards while the rest dealt in, did not want it, and skipped the reward.
        boxes = {rewards.OBTAIN_TITLE_AT: rewards.OBTAIN_TITLE, rewards.OBTAIN_TIP_AT: "请选择1张要获得的卡牌"}
        offer = [{"name": "Distortion: Overwhelm"}, {"name": "Prepare to Subdue"}, {"name": "Distortion: Nature's Gift"}]
        seen = []
        handler = rewards.after_the_team(lambda task: seen.append(utils_sortie.recognize_cards(task, page="")) or True, utils_sortie)
        task = types.SimpleNamespace(node_status={}, sleep=lambda seconds: None, **{PARTY: frozenset({"Yuki"})})
        landed = iter([1, 3, 3])
        with standing_in(utils_sortie, find_box_at_point=lambda task, x, y: types.SimpleNamespace(name=boxes.get((x, y), "")),
                         recognize_cards=lambda task, page: offer[:next(landed)]):
            for _ in range(3):
                self.assertTrue(handler(task))
        self.assertEqual([offer], seen)

    def test_a_misread_reward_is_still_picked(self):
        # Live, Black Dance was read as `Back Dance`, so upstream found no listed name in it and skipped the reward.
        offer = [{"name": "Dark Mist Secret Art: Back Dance", "x": 0.7375, "y": 0.3472}]
        boxes = {rewards.OBTAIN_TITLE_AT: rewards.OBTAIN_TITLE, (0.883, 0.131): "请选择1张要获得的卡牌"}
        clicks = []
        task = types.SimpleNamespace(sleep=lambda seconds: None, log_info=lambda *args, **kwargs: None)
        with standing_in(utils_sortie, find_box_at_point=lambda task, x, y: types.SimpleNamespace(name=boxes.get((x, y), "")),
                         recognize_cards=lambda task, page: [dict(card) for card in offer], _move_and_click=lambda task, x, y: clicks.append((x, y)),
                         _get_config_value=lambda task, key, default: ["Dark Mist Secret Art: Black Dance"]):
            rewards.with_generated_lists(utils_sortie.handle_get_card, [utils_sortie])(task)
        self.assertEqual((0.7375, 0.3472), clicks[0])

    def test_a_picked_reward_joins_the_deck(self):
        # Live, an Annoying taken mid-layer was valued by its base text until the next layer's read, though the screen showed its Epiphany.
        sparked = EPIPHANIES["Annoying"][-1]
        boxes = {rewards.OBTAIN_TITLE_AT: rewards.OBTAIN_TITLE, (0.883, 0.131): "请选择1张要获得的卡牌"}
        task = type("SortieMode", (), {"sleep": lambda self, seconds: None, "log_info": lambda self, *args, **kwargs: None,
                                       "move_relative": lambda self, x, y: None, "click": lambda self, x, y: None})()
        self.addCleanup(cards.use_deck, {})
        # Live, the first tap and its Confirm did not take, the screen came back with the same offer, and the card was counted twice.
        # An Epiphany screen came back the same way with its cards moved and one name misread. A second pick that takes another card is no
        # retry: live, Photo Time was undone when Gear Bag followed it, though both took.
        for second, misread, expected in (("Annoying", "Ice Frao", {"Annoying": 1}), ("Ice Fragment", "Ice Fragment", {"Annoying": 1, "Ice Fragment": 1})):
            with self.subTest(second=second):
                cards.use_deck({})
                offer = [{"name": "Annoying", "description": sparked, "x": 0.7375, "y": 0.3472}, {"name": "Ice Fragment", "description": "", "x": 0.5, "y": 0.3472}]
                priority = ["Annoying"]
                # The real `_move_and_click`, so the deck still follows if upstream stops tapping a card at the point its reader returned.
                with standing_in(utils_sortie, find_box_at_point=lambda task, x, y: types.SimpleNamespace(name=boxes.get((x, y), "")),
                                 recognize_cards=lambda task, page: offer, _get_config_value=lambda task, key, default: priority),                         standing_in(piles, _last_pick=None):
                    obtain = piles.following(utils_sortie.handle_get_card, utils_sortie, piles.GAINED)
                    obtain(task)
                    offer[1] = {**offer[1], "name": misread, "x": 0.2}
                    priority[:] = [second]
                    obtain(task)
                self.assertEqual(expected, {name: sum(copies.values()) for name, copies in cards.COPIES.items()})

    def test_two_cards_taken_on_one_visit_both_count(self):
        # A screen that removes two cards taps both on one visit, which must not pass for a retry of the first.
        base = DESCRIPTIONS["Experienced Strike"]
        offer = [{"name": "Experienced Strike", "description": base, "x": 0.3, "y": 0.4}, {"name": "Experienced Strike", "description": base, "x": 0.5, "y": 0.4}]
        module = types.SimpleNamespace(recognize_cards=lambda task: offer)
        task = type("SortieMode", (), {"click": lambda self, x, y: None})()

        def remove_two(task):
            for card in module.recognize_cards(task):
                task.click(card["x"], card["y"])

        cards.use_deck({"Experienced Strike": [base, base, base]})
        self.addCleanup(cards.use_deck, {})
        piles.following(remove_two, module, piles.REMOVED)(task)
        self.assertEqual({"Experienced Strike": Counter({base: 1})}, cards.COPIES)

    def test_a_card_assigned_to_a_combatant_joins_the_deck(self):
        # Live, a Wanderer Arbitum handed out on Card Assign never reached the deck, since the pick taps the combatant, not the card.
        card = {"name": "Annoying", "description": DESCRIPTIONS["Annoying"], "x": 0.17, "y": 0.31}
        title = types.SimpleNamespace(name="请选择要接受卡牌的主战员")
        level = types.SimpleNamespace(x=0, y=HEIGHT * 0.4, width=10, height=10)
        task = type("SortieMode", (), {"sleep": lambda self, seconds: None, "log_info": lambda self, *args, **kwargs: None, "all_texts": [],
                                       "width": WIDTH, "height": HEIGHT, "move_relative": lambda self, x, y: None, "click": lambda self, x, y: None})()
        self.addCleanup(cards.use_deck, {})
        # The real handler and `_move_and_click`, so the deck still follows if upstream moves the combatant column.
        with standing_in(utils, find_box_at_point=lambda task, x, y: title if (x, y) == (0.863, 0.133) else None, _get_game_text=lambda task, text: text,
                         recognize_cards=lambda task, region, page: [card], _get_card_list=lambda task, key: [],
                         _get_card_reward_priority=lambda task: ["Annoying"], _find_member_level_tags=lambda task, region, page: [level],
                         _find_target_member_index=lambda task, levels, region: 0, _member_deck_state=lambda task: {},
                         _record_neutral_card=lambda task: None):
            piles.following(utils.handle_card_assign, utils, piles.GAINED, next(column for *_, column in piles.FOLLOWED if column))(task)
        self.assertEqual({"Annoying": DESCRIPTIONS["Annoying"]}, cards.DECK)

    def test_every_screen_that_changes_the_deck_is_still_there(self):
        for module_name, name, *_ in piles.FOLLOWED:
            with self.subTest(name):
                module = {"utils": utils, "utils_sortie": utils_sortie}[module_name]
                self.assertTrue(callable(getattr(module, name, None)))
                self.assertTrue(any(reader in vars(module) for reader in piles.READERS))

    def test_each_change_lands_on_its_own_copy(self):
        base, shield = DESCRIPTIONS["Experienced Strike"], EPIPHANIES["Experienced Strike"][0]
        annoying = EPIPHANIES["Annoying"][-1]
        for description, deck, taps, expected in (
            # The deck shows the weaker base copy, so taking the wrong copy away would leave the base on show.
            ("a removal takes the copy tapped", {"Experienced Strike": {base, shield}}, [(piles.REMOVED, "Experienced Strike", base)],
             {"Experienced Strike": shield}),
            # Keeping the base copy beside the Epiphany would leave the deck showing the base.
            ("an Epiphany replaces the version it was chosen in", {"Annoying": {DESCRIPTIONS["Annoying"]}},
             [(piles.SPARKED, "Annoying", DESCRIPTIONS["Annoying"]), (piles.EPIPHANY, "Annoying", annoying)], {"Annoying": annoying}),
        ):
            with self.subTest(description):
                cards.use_deck(deck)
                self.addCleanup(cards.use_deck, {})
                for change, name, text in taps:
                    piles.follow(change, {"name": name, "description": text})
                self.assertEqual(expected, cards.DECK)

    def test_equipment_is_offered_to_its_own_slot_only(self):
        task = FakeTask(SHOP_EQUIPMENT, {"vanguard", "controller"})
        by_slot = {slot: rewards.generated_list(task, key) for key, slot in rewards.EQUIPMENT_KEYS.items()}
        self.assertEqual(["Crimson Sword"], by_slot[0])
        self.assertEqual(["Cloud-Walking Shoes"], by_slot[1])
        self.assertEqual([], by_slot[2])

    def test_a_setting_we_do_not_fill_in_is_left_alone(self):
        self.assertIsNone(rewards.generated_list(FakeTask(SHOP_CARDS), "优先移除基础牌"))

    def test_a_configured_list_always_wins(self):
        """The generated list is a fallback, never an override."""
        reader = rewards.filling_in(lambda task, key, default: ["Absolute Zero"], "utils")
        self.assertEqual(["Absolute Zero"],
                         reader(FakeTask(SHOP_CARDS, {"vanguard"}), rewards.CARD_KEY, []))

    def test_an_empty_list_is_filled_in(self):
        reader = rewards.filling_in(lambda task, key, default: [], "utils")
        self.assertEqual(["Prepare for Battle"],
                         reader(FakeTask(SHOP_CARDS, {"vanguard", "controller"}), rewards.CARD_KEY, []))

    def test_a_reading_with_no_letters_in_it_matches_nothing(self):
        # One real card is named with three geometric symbols, and folding used to reduce it to an empty
        # string - which every punctuation-only box the reader produces also folds to. A bare "-" was read
        # 310 times in one run, and each one resolved to that card and was offered as a Unique to take.
        for reading in ("-", "+", "•", "」", "?"):
            with self.subTest(reading=reading):
                self.assertEqual([], worth_taking([reading], ()))

    def test_a_card_named_only_in_symbols_still_matches_itself(self):
        # Tiphereth's Archetype payoff card. Dropping it from the index would be the easy fix, but it is a
        # cost-0 Unique and worth taking, so the fold keeps the shapes instead.
        self.assertEqual(["○ △ □"], worth_taking(["○ △ □"], ()))

    def test_nothing_worth_taking_leaves_the_list_empty(self):
        """A shop of Commons must stay a shop of Commons, not become one it buys from."""
        reader = rewards.filling_in(lambda task, key, default: [], "utils")
        self.assertEqual([], reader(FakeTask(["Shock", "Multishot"], {"vanguard"}), rewards.CARD_KEY, []))

    def test_a_free_reward_takes_the_teams_own_card(self):
        """A run skipping every Common and Rare reward leaves the team's lineup too weak, and the shop must not start buying them."""
        task = FakeTask(["Harmonization: Hidden Bullet", "Harmonization: Moon of Destruction", "Opening Found"], {"ranger"})
        setattr(task, rewards.PARTY, frozenset({"Hugo", "Beryl"}))
        module = types.ModuleType("utils")
        module._get_config_value = lambda task, key, default: default
        cases = [("handle_get_card", rewards.SORTIE_CARD_KEY, ["Opening Found"]), ("handle_card_reward", rewards.CARD_KEY, ["Opening Found"]),
                 ("handle_shop", rewards.CARD_KEY, []), ("handle_card_assign", rewards.CARD_KEY, [])]
        for name, key, expected in cases:
            with self.subTest(handler=name):
                def handler(task, key=key):
                    return module._get_config_value(task, key, [])

                # The handler's name is what marks a reward screen, so the stand-in borrows upstream's.
                handler.__name__ = name
                self.assertEqual(expected, rewards.with_generated_lists(handler, [module])(task))


if __name__ == "__main__":
    unittest.main()


class TestPurchaseAgreesWithTheShop(unittest.TestCase):
    """The shop decides to buy, and the screen that confirms the buy has to reach the same answer.

    The shelf and the Purchase Card screen are two views of one decision, judged against the same setting.
    When that setting is filled in from what is on screen, both views have to fill it in the same way. They
    did not: the shelf's handler had the fallback and the purchase screen's did not, so the shop clicked buy,
    the purchase screen found an empty list, cancelled, and the shelf clicked buy again - sixteen times in
    seventy seconds, with nothing detecting it as stuck because the screen kept changing.
    """

    def test_the_purchase_screen_gets_the_fallback_too(self):
        self.assertIn("handle_card_assign", rewards.FILLED_IN)

    def test_both_views_of_one_shelf_pick_the_same_card(self):
        shelf = rewards.generated_list(FakeTask(LOOPING_SHELF, team=set()), rewards.CARD_KEY)
        purchase = rewards.generated_list(FakeTask(LOOPING_PURCHASE, team=set()), rewards.CARD_KEY)
        self.assertEqual(["Reorganize"], shelf)
        self.assertEqual(shelf, purchase)

    def test_a_name_wrapped_onto_two_lines_is_read_whole(self):
        shelf = rewards.generated_list(FakeTask(WRAPPED_SHELF, team=set()), rewards.CARD_KEY)
        purchase = rewards.generated_list(FakeTask(WRAPPED_PURCHASE, team=set()), rewards.CARD_KEY)
        self.assertNotIn("Judgment", shelf)
        self.assertEqual(shelf, purchase)


class TestSuits(unittest.TestCase):
    """Weighing a piece of equipment against the combatant who would wear it.

    The game keeps this opinion for Sortie and leaves the Chaos copies of the same relics blank, so the
    generator carries it across. It covers about a third of what a Chaos run can meet, and a piece with no
    tags has to read as "no opinion" rather than as "unsuitable" - otherwise two thirds of the pool would
    quietly sink below the third that happens to be labelled.
    """

    def test_a_piece_the_combatant_wants_scores_her_own_weight(self):
        # Arabella wants all-attack equipment, and the game says how much.
        self.assertEqual(COMBATANT_TAG_WEIGHTS["Arabella"]["allatk"], suits("Nature's Hostility", "Arabella"))

    def test_nothing_it_has_no_opinion_on_scores_anything(self):
        """Silence and dislike both read as zero, which is what keeps an unlabelled piece from sinking."""
        for description, piece, combatant in (
            ("a piece she does not want", "Assault Boots", "Arabella"),
            ("a combatant the data does not know", "Nature's Hostility", "Someone Unreleased"),
            ("a reading that is not equipment", "Rewards cannot be obtained", "Arabella"),
        ):
            with self.subTest(description):
                self.assertEqual(0, suits(piece, combatant))

    def test_two_wanted_kinds_on_one_piece_add_up(self):
        weights = COMBATANT_TAG_WEIGHTS["Nia"]
        self.assertEqual(weights["discard"] + weights["draw"],
                         suits("Fragment of the Empty Void", "Nia"))

    def test_an_untagged_piece_is_no_opinion(self):
        # Not a named piece: coverage grows with every dump, and the test should outlive any one item.
        untagged = next(name for name in EQUIPMENT_RARITY if name not in EQUIPMENT_TAGS)
        self.assertEqual(0, suits(untagged, "Arabella"))


    def test_a_concatenated_reading_still_matches(self):
        # The reader runs words together constantly - "Gauntlets ofProtection" is from a real run.
        self.assertEqual(suits("Fragment of the Empty Void", "Nia"),
                         suits("Fragment of theEmpty Void", "Nia"))

    def test_every_released_combatant_has_an_opinion(self):
        # A dump that stopped carrying these would leave the shopping list ordered by name again, silently.
        self.assertEqual(set(), set(COMBATANTS) - set(COMBATANT_TAG_WEIGHTS))


class TestWorthTakingSuited(unittest.TestCase):
    """Ordering the generated shopping list by who is going to wear the thing."""

    SHELF = ["Nature's Hostility", "Assault Boots", "Blood Giant Claw"]

    def test_the_wanted_piece_comes_first(self):
        # Compared folded: the client spells this one with a typographic apostrophe.
        first = worth_taking(self.SHELF, cards=False, suited_to="Arabella")[0]
        self.assertEqual(fold("Nature's Hostility"), fold(first))

    def test_without_a_combatant_the_order_is_unchanged(self):
        self.assertEqual(worth_taking(self.SHELF, cards=False),
                         worth_taking(self.SHELF, cards=False, suited_to=None))

    def test_rarity_still_outranks_the_preference(self):
        # A Legend she wants must not jump a Unique she does not: the run wants the better item.
        shelf = ["Nature's Hostility", "Fragment of the Empty Void"]
        self.assertEqual("Fragment of the Empty Void",
                         worth_taking(shelf, cards=False, suited_to="Arabella")[0])

    def test_an_unknown_combatant_changes_nothing(self):
        self.assertEqual(worth_taking(self.SHELF, cards=False),
                         worth_taking(self.SHELF, cards=False, suited_to="Someone Unreleased"))

    def test_cards_are_untouched_by_it(self):
        self.assertEqual(worth_taking(SHOP_CARDS), worth_taking(SHOP_CARDS, suited_to="Arabella"))


class TestFarmedCombatantReachesTheList(unittest.TestCase):
    """The farming target reaches the shopping list, read through the reader being stood in for.

    Reading it around that reader would be the easy mistake: this code runs as the stand-in for it, so asking
    through the module attribute would come straight back here. It also has to survive the slot filter, which
    is the only thing this layer adds over `worth_taking`.
    """

    # Two slot-0 Legends: the game says Arabella wants the first kind and says nothing about the second.
    SHELF = ["Nature's Hostility", "Blood Giant Claw"]
    SLOT_ONE = next(key for key, slot in rewards.EQUIPMENT_KEYS.items() if slot == 0)

    def offered(self, config):
        """Read back what the list offers for the first equipment slot.

        Args:
            config: The settings the run is holding, as the reader would answer them.

        Returns:
            The names offered, best first.
        """
        reader = rewards.filling_in(lambda task, key, default: config.get(key, default), "utils")
        return reader(FakeTask(self.SHELF), self.SLOT_ONE, [])

    def test_the_configured_combatant_orders_the_equipment(self):
        self.assertEqual(fold("Nature's Hostility"), fold(self.offered({FARMED_COMBATANT: "Arabella"})[0]))

    def test_an_unset_combatant_leaves_the_name_order_alone(self):
        self.assertEqual(fold("Blood Giant Claw"), fold(self.offered({})[0]))

    def test_only_this_slot_is_offered(self):
        self.assertEqual(2, len(self.offered({FARMED_COMBATANT: "Arabella"})))


class TestHandTags(unittest.TestCase):
    """The labels read by hand for the pieces the game never labelled.

    The generator reaches a relic only when Sortie carries the same row, and 98 of the pieces a Chaos run can
    meet have no such row. These are a reading of those pieces' own effect text, so the suite has to pin what
    a reading can get wrong: a name that is not real equipment, a kind no combatant wants, or an entry that
    quietly contradicts the developers' own answer.
    """

    def test_every_name_is_real_equipment(self):
        self.assertEqual(set(), set(HAND_TAGS) - set(EQUIPMENT_RARITY))

    def test_no_combatant_wants_a_kind_nothing_can_carry(self):
        """A preference nothing can satisfy is a dead entry, and the game shipped one.

        Its own table spells `bullet` with three Ls for two combatants, so their strongest preference matched
        no equipment at all. The generator corrects known misspellings, and this is what notices the next one.
        """
        carried = {tag for tags in TAGS.values() for tag in tags}
        wanted = {tag for weights in COMBATANT_TAG_WEIGHTS.values() for tag in weights}
        self.assertEqual(set(), wanted - carried)

    def test_every_kind_is_one_a_combatant_wants(self):
        wanted = {tag for weights in COMBATANT_TAG_WEIGHTS.values() for tag in weights}
        self.assertEqual(set(), {tag for tags in HAND_TAGS.values() for tag in tags} - wanted)

    def test_it_only_fills_gaps(self):
        # Reading one differently from the developers would be a silent disagreement, so overlap is refused.
        self.assertEqual(set(), set(HAND_TAGS) & set(EQUIPMENT_TAGS))

    def test_the_generated_answer_wins_where_both_speak(self):
        overlapping = next(iter(EQUIPMENT_TAGS))
        self.assertEqual(EQUIPMENT_TAGS[overlapping], TAGS[overlapping])

    def test_a_hand_read_piece_is_scored(self):
        # Cycle of Circulation heals mid-battle, and Orlea is one of the combatants who want that.
        self.assertIn("heal", HAND_TAGS["Cycle of Circulation"])
        self.assertGreater(suits("Cycle of Circulation", "Orlea"), 0)

    def test_it_widens_what_the_run_has_an_opinion_on(self):
        self.assertEqual(len(EQUIPMENT_TAGS) + len(HAND_TAGS), len(TAGS))


class TestScrambledReadings(unittest.TestCase):
    """Names whose words came back out of order.

    The reader does this constantly, and until now every one was simply lost: `Assault Gauntlets` read as
    `GauntletsAssault` matched no equipment, so the run had no rarity and no opinion for it and walked past.
    Six of the 62 distinct pieces the shop has offered across the logs came back this way.

    Sorting a name's letters is what makes those match, and it is safe here because no two equipment names
    are anagrams of each other. Where two names would collide, only their exact spellings are kept.
    """

    # Real readings, from the shop lines in `logs/`.
    SCRAMBLED = {
        "GauntletsAssault": "Assault Gauntlets",
        "CarapaceGrowing": "Growing Carapace",
        "Night ButterfliesDance of the": "Dance of the Night Butterflies",
    }

    def test_the_client_spelling_is_recovered(self):
        for reading, real in self.SCRAMBLED.items():
            with self.subTest(reading=reading):
                self.assertEqual(slot_of(real), slot_of(reading))
                self.assertIsNotNone(slot_of(reading))

    def test_a_scrambled_name_still_carries_its_kinds(self):
        # Magna wants counter equipment, and Assault Gauntlets is counter equipment.
        self.assertGreater(suits("GauntletsAssault", "Magna"), 0)

    def test_a_scrambled_name_is_still_graded(self):
        # Growing Carapace is a Legend, so recognising it is the difference between buying it and walking past.
        self.assertEqual(["Growing Carapace"], worth_taking(["CarapaceGrowing"], cards=False))

    def test_no_two_pieces_of_equipment_are_anagrams(self):
        letters = Counter("".join(sorted(fold(name))) for name in EQUIPMENT_RARITY if fold(name))
        self.assertEqual([], [key for key, count in letters.items() if count > 1])

    def test_an_ambiguous_scramble_is_refused(self):
        # Two names of the same letters cannot be told apart, so neither answers to the scrambled spelling.
        lookup = index(["Dark Star", "Stark Dar"])
        self.assertIsNone(lookup.look_up("StarDark"))
        self.assertEqual("Dark Star", lookup.look_up("Dark Star"))


class TestMisreadLetters(unittest.TestCase):
    """Names the reader spelled with a lookalike letter.

    A capital I comes back as a lowercase l constantly - `Magic-lnfused Sapphire`, `Instinct lgnition`,
    `Mutation: lron Wall` are all from real logs - and every one of those was a name the run then failed to
    recognise at all. The characters corrected here are only the ones the logs actually show being swapped,
    and only where exactly one name answers to the corrected spelling.

    `Vute Accent` and `Moon or Destruction` are deliberately not in this table. Reading v as m or r as f
    would turn real words into other real words, and a blanket swap has no way to know it has. Both readings
    are still recovered, but by the pass below, which has to agree on every other character and find only one
    candidate.
    """

    # Reading, and the name it was meant to be. All from `logs/`.
    MISREAD = {
        "Magic-lnfusedSapphire": "Magic-Infused Sapphire",
        "Instinct lgnition": "Instinct Ignition",
        "Mutation: lron Wall": "Mutation: Iron Wall",
        "Bloom: Strateqic Starting Point": "Bloom: Strategic Starting Point",
    }

    def test_the_real_name_is_recovered(self):
        lookup = index(list(EQUIPMENT_RARITY) + list(CARD_RARITY))
        for reading, real in self.MISREAD.items():
            with self.subTest(reading=reading):
                self.assertEqual(real, lookup.look_up(reading))

    def test_a_misread_piece_of_equipment_is_placed(self):
        # None of the real misreadings happen to be Legends, so this checks recognition rather than grading.
        self.assertEqual(slot_of("Magic-Infused Sapphire"), slot_of("Magic-lnfusedSapphire"))
        self.assertIsNotNone(slot_of("Magic-lnfusedSapphire"))

    def test_a_misread_piece_still_carries_its_kinds(self):
        # Magic-Infused Sapphire is initiation equipment, and Lucas is one of the combatants who want that.
        self.assertGreater(suits("Magic-lnfusedSapphire", "Lucas"), 0)

    def test_a_reading_that_is_both_scrambled_and_misread_still_matches(self):
        self.assertEqual("Magic-Infused Sapphire",
                         index(EQUIPMENT_RARITY).look_up("lnfusedSapphireMagic"))

    def test_no_two_names_collide_once_lookalikes_are_folded(self):
        for table in (EQUIPMENT_RARITY, CARD_RARITY, COMBATANT_CLASS):
            folded = {fold(name) for name in table if fold(name)}
            keys = Counter(sorted_letters(unconfused(name)) for name in folded)
            with self.subTest(table=len(table)):
                self.assertEqual([], [key for key, count in keys.items() if count > 1])


class TestNearestName(unittest.TestCase):
    """The last resort: a reading one edit away from exactly one real name.

    Everything above this keeps all of a name's letters. This is for the readings that lost one, gained one,
    or got one plain wrong - `Shuffl`, `arget Spotted`, `1-Devil Dice`, `Vute Accent`. A few dozen readings
    land here across every log and every one of them is correct, because the pass only answers when a single
    name is that close. Two candidates and it declines, which is what keeps a short reading like `Dice` from
    being talked into `Daze`.
    """

    # Reading, and the name it was meant to be. All from `logs/`.
    NEAR = {
        "Shuffl": "Shuffle",
        "Shuffli": "Shuffle",
        "arget Spotted": "Target Spotted",
        "1-Devil Dice": "Devil Dice",
        "Vute Accent": "Mute Accent",
        "Harmonization: Moon or Destruction": "Harmonization: Moon of Destruction",
    }

    def setUp(self):
        self.lookup = index(list(EQUIPMENT_RARITY) + list(CARD_RARITY))

    def test_the_real_name_is_recovered(self):
        for reading, real in self.NEAR.items():
            with self.subTest(reading=reading):
                self.assertEqual(real, self.lookup.look_up(reading))

    def test_a_long_name_survives_a_few_lost_letters(self):
        # Live, two readings of Rin's Destruction three and two letters short, so her kit could not place it first. A squeezed
        # Criticism of Discord lost five, so the reward screen never offered it.
        for reading, name in (("DarkMistSecretAr:Destuctio", "Dark Mist Secret Art: Destruction"),
                              ("DarkMistSecretArtDestction", "Dark Mist Secret Art: Destruction"),
                              ("HarmonizationcicimofDicord", "Harmonization: Criticism of Discord")):
            with self.subTest(reading=reading):
                self.assertEqual(name, self.lookup.look_up(reading))

    def test_two_candidates_are_refused(self):
        # `Daze` and `Dice` are both real cards, so a reading of `Dace` belongs to neither.
        self.assertIsNone(self.lookup.look_up("Dace"))

    def test_a_short_reading_is_never_guessed_at(self):
        # Below the floor a single edit is most of the name, and the screen is full of stray glyphs.
        self.assertIsNone(index(["Daze"]).look_up("Dice"))
        self.assertIsNone(self.lookup.look_up("+60"))

    def test_an_exact_name_still_wins(self):
        # A name that really is one edit from another, so the tiers have something to get wrong.
        for name in ("Archetype: □", "Archetype: △"):
            with self.subTest(name=name):
                self.assertEqual(name, self.lookup.look_up(name))

    def test_nothing_close_stays_unrecognised(self):
        self.assertIsNone(self.lookup.look_up("Rewards cannot be obtained"))


class TestOneEditApart(unittest.TestCase):
    """The distance test itself, which has to mean exactly one edit and not zero or two."""

    CASES = (
        ("a substitution", "mute", "vute", True),
        ("a deletion", "shuffle", "shuffl", True),
        ("an insertion", "targetspotted", "argetspotted", True),
        ("the pair the other way round", "shuffl", "shuffle", True),
        ("the same string", "shuffle", "shuffle", False),
        ("two edits", "dice", "daze", False),
        ("a big difference in length", "shuffle", "shu", False),
    )

    def test_counts_exactly_one_edit(self):
        for why, first, second, expected in self.CASES:
            with self.subTest(why):
                self.assertEqual(expected, one_edit_apart(first, second))


class TestCombatantsRowHoldsItsPlace(unittest.TestCase):
    """The team row, which upstream's info table has nothing to draw until the Combatants screen is read.

    `info_clear` empties the table at the start of every run, so a row that only appears once the team is
    scanned is missing for the first stretch of the run - and after the idle table drew it, that reads as the
    row vanishing on Start and coming back minutes later.
    """

    SCANNED = ", ".join(TEAM)

    def test_the_row_is_seeded_before_the_team_has_been_read(self):
        task = FakeTask()
        self.assertIs(False, rewards.hold_the_combatants_row(task), "it must not claim the frame")
        self.assertEqual({COMBATANTS_ROW: dashboard.UNREAD}, task.info)

    def test_a_scanned_team_is_never_overwritten_by_the_placeholder(self):
        # Once read, the team draws one row per combatant and the placeholder row is gone for good.
        task = FakeTask(info={})
        setattr(task, dashboard.TEAM_NAMES, TEAM)
        rewards.hold_the_combatants_row(task)
        self.assertEqual({}, task.info)

    def test_a_new_run_seeds_it_again(self):
        task = FakeTask(info={COMBATANTS_ROW: self.SCANNED})
        task.info.clear()  # What upstream's info_clear does at the start of every run.
        rewards.hold_the_combatants_row(task)
        self.assertEqual({COMBATANTS_ROW: dashboard.UNREAD}, task.info)


class TestObtainNeedsReason(unittest.TestCase):
    """Obtain spends 1 Reason, and with none left the Charge Reason dialog it opens would spend Aether."""

    def test_obtain_is_pressed_only_with_reason_left(self):
        # A declined Charge Reason dialog holds for the run, since the counter reading 3 is what let Obtain open it.
        for why, counter, out_of_reason, obtains in (("none left", "0/9", False, False), ("some left", "3/9", False, True),
                                                     ("charge declined", "3/9", True, False)):
            with self.subTest(why):
                pressed = []
                # The Settlement page, placed the way the run's capture read it.
                task = types.SimpleNamespace(
                    all_texts=[FakeBox("结算", 0.590, 0.065, width=259, height=54, units="fraction"), FakeBox(counter, 0.880, 0.051, units="fraction"),
                               FakeBox("获得", 0.857, 0.386, width=108, height=36, units="fraction")],
                    width=WIDTH, height=HEIGHT, config={"领取奖励": True}, node_status={reason.OUT_OF_REASON: out_of_reason},
                    click_box=lambda box: pressed.append(box.name), log_info=lambda message: None, sleep=lambda seconds: None,
                )
                with standing_in(utils_sortie, _finish_only_first_layer=lambda task: True):
                    reason.with_reason_only(utils_sortie.handle_sortie_reward_settlement, utils_sortie)(task)
                self.assertEqual(["获得"] if obtains else [], pressed)
                self.assertTrue(task.config["领取奖励"])

    def test_the_charge_dialog_is_declined_even_with_aether_to_pay(self):
        # Upstream only backs out when Confirm is greyed, so an active Confirm is the case that spent Aether.
        clicks = []
        task = types.SimpleNamespace(all_texts=[FakeBox("补充理性", 0.5, 0.17, units="fraction"), FakeBox("确认", 0.664, 0.774, units="fraction")],
                                     width=WIDTH, height=HEIGHT, node_status={}, log_info=lambda message: None, sleep=lambda seconds: None)
        with standing_in(utils_sortie, _move_and_click=lambda task_, x, y: clicks.append((x, y))):
            self.assertIs(True, reason.charge_reason_handler(utils_sortie)(task))
        self.assertEqual([reason.DECLINE_POINT], clicks)
        self.assertIs(True, task.node_status[reason.OUT_OF_REASON])

    def test_the_loot_dialog_gives_up_once_the_run_is_out_of_reason(self):
        for out_of_reason, point in ((False, (0.567, 0.708)), (True, (0.355, 0.714))):
            with self.subTest(out_of_reason=out_of_reason):
                clicks = []
                task = types.SimpleNamespace(all_texts=[FakeBox("卡厄思战利品", 0.503, 0.335, width=300, units="fraction")], width=WIDTH, height=HEIGHT,
                                             config={"领取奖励": True}, node_status={reason.OUT_OF_REASON: out_of_reason},
                                             log_info=lambda message: None, sleep=lambda seconds: None)
                with standing_in(utils_sortie, _move_and_click=lambda task_, x, y: clicks.append((x, y))):
                    reason.with_reason_only(utils_sortie.handle_sortie_reward_claim, utils_sortie)(task)
                self.assertEqual([point], clicks)


class TestLootCardsRunOut(unittest.TestCase):
    """Chaos's Additional Loot setting, which upstream saved as off for good the first time the cards read 0."""

    def test_a_claim_with_no_cards_is_cancelled_and_the_setting_kept(self):
        # Any other count is left to upstream's own handler, which claims with the card.
        for counter, handled in (("0/3", True), ("2/3", False)):
            with self.subTest(counter):
                clicks = []
                task = types.SimpleNamespace(all_texts=[FakeBox("获得", *loot_cards.CLAIM_POINT), FakeBox(counter, *loot_cards.CARD_COUNTER_POINT, width=40)],
                                             width=WIDTH, height=HEIGHT, config={loot_cards.CLAIMING: True}, node_status={},
                                             log_info=lambda message: None, sleep=lambda seconds: None)
                with standing_in(utils_chaos, _move_and_click=lambda task_, x, y: clicks.append((x, y))):
                    self.assertIs(handled, loot_cards.no_cards_handler(utils_chaos)(task))
                self.assertEqual([loot_cards.CANCEL_POINT] if handled else [], clicks)
                self.assertIs(handled, task.node_status.get(loot_cards.OUT_OF_CARDS, False))

    def test_obtain_is_skipped_for_the_rest_of_a_run_out_of_cards(self):
        # Without this the Settlement presses Obtain again, the claim is cancelled again, and the run never leaves.
        for out_of_cards in (False, True):
            with self.subTest(out_of_cards=out_of_cards):
                pressed = []
                task = types.SimpleNamespace(all_texts=[FakeBox("结算", 0.552, 0.067), FakeBox("获得", 0.851, 0.389)], width=WIDTH, height=HEIGHT,
                                             config={loot_cards.CLAIMING: True}, node_status={loot_cards.OUT_OF_CARDS: out_of_cards},
                                             click_box=lambda box: pressed.append(box.name), log_info=lambda message: None, sleep=lambda seconds: None)
                with standing_in(utils_chaos, _finish_only_first_layer=lambda task_: True):
                    loot_cards.with_cards_only(utils_chaos.handle_chaos_reward_settlement, utils_chaos)(task)
                self.assertEqual([] if out_of_cards else ["获得"], pressed)


def captured(*rows):
    """Place OCR boxes exactly where a capture had them.

    Args:
        *rows: `(text, left, right, top, bottom)` in screen fractions, as the capture read them.

    Returns:
        The boxes.
    """
    return [FakeBox(name, (left + right) / 2, (top + bottom) / 2, width=(right - left) * WIDTH, height=(bottom - top) * HEIGHT, units="fraction")
            for name, left, right, top, bottom in rows]


# Four captures from one live Chaos run, read with the app's OCR and its `ocr.po`: a waypoint Settlement, the final one with
# Leave where the waypoint has Continue, the dialog Leave raised there, and the claim dialog Obtain opens. `COUNTER` marks the
# card counter, set per test.
COUNTER = "2/4"
WAYPOINT_SETTLEMENT = [
    ("378/378", 0.1708, 0.2531, 0.0222, 0.0537), (COUNTER, 0.8609, 0.8964, 0.0306, 0.0704), ("结算", 0.5240, 0.6562, 0.0398, 0.0907),
    ("Loot", 0.5188, 0.5625, 0.1231, 0.1546), ("Additional Loot", 0.5188, 0.6385, 0.3546, 0.3843), ("F2", 0.8031, 0.8302, 0.3324, 0.3602),
    ("获得", 0.8292, 0.8854, 0.3694, 0.4009), ("me 1 Loot Voucher Card to exchange for Ai", 0.5208, 0.7927, 0.3898, 0.4194),
    ("1.200", 0.5552, 0.5854, 0.5167, 0.5370), ("Exploration Score", 0.5552, 0.6958, 0.8000, 0.8306), ("188", 0.8969, 0.9333, 0.7944, 0.8343),
    ("进入", 0.8146, 0.8542, 0.8639, 0.8898), ("Temporary Return", 0.5615, 0.6865, 0.8954, 0.9370), ("继续", 0.8885, 0.9667, 0.8981, 0.9343),
]
FINAL_SETTLEMENT = [
    ("242/456", 0.1708, 0.2521, 0.0204, 0.0537), ("结算", 0.5229, 0.6573, 0.0380, 0.0926), (COUNTER, 0.8625, 0.8958, 0.0333, 0.0657),
    ("Loot", 0.5198, 0.5625, 0.1231, 0.1546), ("Additional Loot", 0.5208, 0.6385, 0.3546, 0.3843), ("F2", 0.8052, 0.8281, 0.3361, 0.3583),
    ("获得", 0.8286, 0.8859, 0.3657, 0.4028), ("nsume 1 Loot Voucher Card to exchange fo", 0.5208, 0.7937, 0.3898, 0.4194),
    ("1.200", 0.5552, 0.5854, 0.5167, 0.5370), ("Exploration Score", 0.5542, 0.6958, 0.8000, 0.8306), ("698", 0.8927, 0.9333, 0.7944, 0.8343),
    ("进入", 0.8146, 0.8542, 0.8639, 0.8898), ("离开", 0.9135, 0.9677, 0.9028, 0.9343),
]
WITHOUT_CARD_DIALOG = [
    ("242/456", 0.1719, 0.2521, 0.0222, 0.0537), ("结算", 0.5219, 0.6573, 0.0380, 0.0926), (COUNTER, 0.8625, 0.8948, 0.0333, 0.0657),
    ("Loot", 0.5156, 0.5625, 0.1231, 0.1546),
    ("There is additional loot available. Continue without using Loot Certification Card?", 0.1719, 0.8313, 0.3935, 0.4306),
    ("Ctrl", 0.3792, 0.4062, 0.4778, 0.5037), ("Do not show until next login", 0.4167, 0.6250, 0.5130, 0.5500),
    ("ESC", 0.2010, 0.2302, 0.5824, 0.6028), ("进入", 0.5146, 0.5563, 0.5806, 0.6065), ("取消", 0.3141, 0.3797, 0.6102, 0.6546),
    ("确认", 0.6276, 0.7057, 0.6046, 0.6546), ("Exploration Score", 0.5542, 0.6979, 0.7935, 0.8352), ("698", 0.8927, 0.9333, 0.7944, 0.8343),
    ("进入", 0.8146, 0.8542, 0.8639, 0.8898), ("离开", 0.9135, 0.9677, 0.9009, 0.9343),
]
CLAIM_DIALOG = [
    (COUNTER, 0.9406, 0.9771, 0.2593, 0.3000), ("卡厄思战利品", 0.4437, 0.5573, 0.3111, 0.3546), ("→Available rewards +", 0.4198, 0.5792, 0.3731, 0.4120),
    ("1,200", 0.3875, 0.4229, 0.5241, 0.5500), ("4,000", 0.4562, 0.4958, 0.5241, 0.5500), ("10", 0.5458, 0.5677, 0.5222, 0.5500),
    ("8", 0.6260, 0.6406, 0.5259, 0.5500), ("Consume 1 Loot Certification Card to exchange for a reward", 0.2875, 0.7135, 0.5787, 0.6176),
    ("取消", 0.3156, 0.3823, 0.6907, 0.7296), ("获得", 0.5437, 0.6083, 0.6870, 0.7315),
]
# The same dialog raised by a waypoint's Continue, which stays where the waypoint draws it.
WAYPOINT_WITHOUT_CARD_DIALOG = [row for row in WITHOUT_CARD_DIALOG if row[0] != "离开"] + [("继续", 0.8885, 0.9667, 0.8981, 0.9343)]


class SettlementTask:
    """A Chaos task on one capture, with the card counter and the Additional Loot setting as given."""

    name = "ChaosMode"

    def __init__(self, rows, counter=COUNTER, claiming=True, out_of_cards=False):
        self.width, self.height = WIDTH, HEIGHT
        self.config = {loot_cards.CLAIMING: claiming}
        self.node_status = {loot_cards.OUT_OF_CARDS: True} if out_of_cards else {}
        self.clicked = []
        self.notified = []
        self.disabled = False
        self.show(rows, counter)

    def show(self, rows, counter=COUNTER, unread=()):
        """Put a capture on screen.

        Args:
            rows: The capture's boxes.
            counter: The card counter's text, or None for a counter OCR did not read.
            unread: Texts OCR did not read on this frame.
        """
        self.all_texts = captured(*((counter if name == COUNTER else name, *rest) for name, *rest in rows
                                    if (counter or name != COUNTER) and name not in unread))

    def click_box(self, box):
        self.clicked.append(box.name)

    def log_info(self, message, notify=False):
        pass

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notified.append(message)

    def sleep(self, seconds):
        pass

    def disable(self):
        self.disabled = True

    def find_one(self, feature_name, box=None):
        return None

    def box_of_screen(self, *region):
        return None


def upstream_stub(name):
    """Stand in for an upstream handler this check does not exercise, under its name, since position and name are the priority scheme.

    Args:
        name: The upstream handler's name.

    Returns:
        A handler that declines every frame.
    """
    def handler(task):
        return False
    handler.__name__ = name
    return handler


class SettlementHandlers:
    """Runs frames through Chaos's handlers around the Settlement, for the test classes below."""

    @contextlib.contextmanager
    def chaos_handlers(self, continue_handler=None):
        """Install into Chaos's handlers around the Settlement, in upstream's order.

        Upstream's own Leave, Settlement, claim and centred Confirm handlers run, the Confirm behind the real spend guard. Every
        loaded list is stood in for, so the install edits none another test reads.

        Args:
            continue_handler: What stands at upstream's `handle_continue`; a handler that declines every frame when None.

        Returns:
            A context manager giving the Chaos and Sortie lists.
        """
        chaos = [spend_guard.guarding_confirm(utils.handle_center_confirm), upstream_stub("handle_precision_memory_process"), utils.handle_leave,
                 utils_chaos.handle_chaos_reward_settlement, utils_chaos.handle_chaos_reward_claim,
                 continue_handler or upstream_stub("handle_continue")]
        sortie = [upstream_stub("handle_center_confirm"), upstream_stub("handle_leave")]
        modes = {name: types.ModuleType(name) for name, _ in handlers.each_list()}
        for name, handler_list in (("utils_chaos", chaos), ("utils_sortie", sortie)):
            modes[name] = types.ModuleType(name)
            modes[name].PAGE_HANDLERS = handler_list
        held = {name: sys.modules.get(name) for name in modes}
        sys.modules.update(modes)
        try:
            with standing_in(utils_chaos, handle_chaos_reward_settlement=utils_chaos.handle_chaos_reward_settlement,
                             _finish_only_first_layer=lambda task_: False, _move_and_click=lambda task_, x, y: task_.clicked.append((x, y))), \
                    standing_in(utils, is_button_active=lambda task_, box: True):
                # Twice, as every task load runs it again.
                loot_cards.install(utils_chaos)
                loot_cards.install(utils_chaos)
                yield chaos, sortie
        finally:
            for name, original in held.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

    def run_chaos(self, task):
        """Run one frame through Chaos's handlers around the Settlement, and say which claimed it.

        Args:
            task: The task on the capture.

        Returns:
            A `(claimed, chaos, sortie)` triple: the name of the handler that claimed the frame, or None, and both lists' names.
        """
        with self.chaos_handlers() as (chaos, sortie):
            claimed = next((handler.__name__ for handler in chaos if handler(task)), None)
        return claimed, [handler.__name__ for handler in chaos], [handler.__name__ for handler in sortie]

    def play(self, task, frames, continue_handler=None):
        """Show one task a run of frames, as the loop would, until it is stopped.

        Args:
            task: The task, which keeps its state from frame to frame.
            frames: `(rows, show_arguments)` pairs.
            continue_handler: Passed to `chaos_handlers`.

        Returns:
            The name of the handler that claimed each frame shown.
        """
        claimed = []
        with self.chaos_handlers(continue_handler) as (chaos, _):
            for rows, arguments in frames:
                if task.disabled:
                    break
                task.show(rows, **arguments)
                claimed.append(next((handler.__name__ for handler in chaos if handler(task)), None))
        return claimed


class TestFinalSettlementLoot(SettlementHandlers, unittest.TestCase):
    """The final Settlement, where Leave ranks above the Settlement's own claim and its dialog went to the centred Confirm."""

    def test_the_final_settlement_claims_with_a_card_before_leave(self):
        task = SettlementTask(FINAL_SETTLEMENT)
        self.assertEqual("handle_obtain_before_leave", self.run_chaos(task)[0])
        self.assertEqual(["获得"], task.clicked)

    def test_the_final_settlement_leaves_with_no_card_or_the_setting_off(self):
        for case in ({"counter": "0/4"}, {"claiming": False}, {"out_of_cards": True}, {"counter": None}):
            with self.subTest(**case):
                task = SettlementTask(FINAL_SETTLEMENT, **case)
                self.assertEqual("handle_leave", self.run_chaos(task)[0])
                self.assertEqual(["离开"], task.clicked)

    def test_continue_without_card_is_cancelled_while_cards_are_left(self):
        task = SettlementTask(WITHOUT_CARD_DIALOG)
        self.assertEqual("handle_continue_without_card", self.run_chaos(task)[0])
        self.assertEqual(["取消"], task.clicked)
        self.assertFalse(task.disabled)

    def test_continue_without_card_is_confirmed_with_no_card_or_the_setting_off(self):
        for case in ({"counter": "0/4"}, {"claiming": False}, {"out_of_cards": True}, {"counter": None}):
            with self.subTest(**case):
                task = SettlementTask(WITHOUT_CARD_DIALOG, **case)
                self.assertEqual("handle_center_confirm", self.run_chaos(task)[0])
                self.assertEqual(["确认"], task.clicked)
                self.assertFalse(task.disabled)

    def test_the_dialog_handler_only_ever_cancels(self):
        # Never Confirm and never the "Do not show" box: with no Cancel read it taps where the capture had Cancel.
        handler = loot_cards.without_card_handler(utils_chaos)
        without_cancel = [row for row in WITHOUT_CARD_DIALOG if row[0] != "取消"]
        for counter in ("0/4", "1/4", "4/4", None):
            for claiming in (True, False):
                for rows, cancel in ((WITHOUT_CARD_DIALOG, "取消"), (without_cancel, loot_cards.WITHOUT_CARD_CANCEL_POINT)):
                    with self.subTest(counter=counter, claiming=claiming, cancel=cancel):
                        task = SettlementTask(rows, counter=counter, claiming=claiming)
                        with standing_in(utils_chaos, _move_and_click=lambda task_, x, y: task_.clicked.append((x, y))):
                            handled = handler(task)
                        self.assertIs(claiming and counter not in ("0/4", None), handled)
                        self.assertEqual([cancel] if handled else [], task.clicked)

    def test_the_waypoint_settlement_is_left_to_upstream(self):
        # Upstream presses Obtain on the setting alone and lets the claim dialog read the cards.
        for case, claimed, clicked in (({"counter": "3/4"}, "handle_chaos_reward_settlement", ["获得"]),
                                       ({"counter": "0/4"}, "handle_chaos_reward_settlement", ["获得"]),
                                       ({"counter": "3/4", "claiming": False}, None, []),
                                       ({"counter": "3/4", "out_of_cards": True}, None, [])):
            with self.subTest(**case):
                self.assertFalse(loot_cards.obtain_before_leave_handler(utils_chaos)(SettlementTask(WAYPOINT_SETTLEMENT, **case)))
                task = SettlementTask(WAYPOINT_SETTLEMENT, **case)
                self.assertEqual(claimed, self.run_chaos(task)[0])
                self.assertEqual(clicked, task.clicked)

    def test_only_chaos_gains_the_handlers_each_once_and_next_to_their_anchor(self):
        _, chaos, sortie = self.run_chaos(SettlementTask(FINAL_SETTLEMENT))
        self.assertEqual(["handle_center_confirm", "handle_leave"], sortie)
        self.assertEqual(chaos.index("handle_leave") - 1, chaos.index("handle_obtain_before_leave"))
        self.assertEqual(chaos.index("handle_center_confirm") - 1, chaos.index("handle_continue_without_card"))
        for name in ("handle_obtain_before_leave", "handle_continue_without_card", "handle_claim_without_cards"):
            self.assertEqual(1, chaos.count(name))

    def test_obtain_waits_for_the_settlement_title(self):
        task = SettlementTask(FINAL_SETTLEMENT)
        task.show(FINAL_SETTLEMENT, unread=("结算",))
        self.assertFalse(loot_cards.obtain_before_leave_handler(utils_chaos)(task))
        self.assertEqual([], task.clicked)

    def test_the_dialog_is_read_only_where_it_draws_its_question(self):
        # The same words higher up the screen are not this dialog.
        moved = [(name, left, right, top - 0.25, bottom - 0.25) if name.startswith("There is") else (name, left, right, top, bottom)
                 for name, left, right, top, bottom in WITHOUT_CARD_DIALOG]
        task = SettlementTask(moved)
        self.assertFalse(loot_cards.without_card_handler(utils_chaos)(task))
        self.assertEqual([], task.clicked)


class TestSettlementCancelLoop(SettlementHandlers, unittest.TestCase):
    """A Settlement read that fails on a still screen, which cycles a Cancel the stuck stop cannot see."""

    def assertStoppedAfterTwoCancels(self, task, claimed, clicked):
        self.assertEqual(clicked, task.clicked)
        self.assertEqual(len(clicked), len(claimed), "no frame is handled after the stop")
        self.assertTrue(task.disabled)
        self.assertEqual([loot_cards.STOP_MESSAGE], task.notified)
        self.assertNotIn("确认", task.clicked)

    def test_leave_and_cancel_stop_on_the_second_cancel(self):
        # Obtain or the counter misread on the final Settlement while the dialog reads the cards.
        for settlement in ({"unread": ("获得",)}, {"counter": None}):
            with self.subTest(**settlement):
                task = SettlementTask(FINAL_SETTLEMENT)
                claimed = self.play(task, [(FINAL_SETTLEMENT, settlement), (WITHOUT_CARD_DIALOG, {})] * 3)
                self.assertEqual(["handle_leave", "handle_continue_without_card"] * 2, claimed)
                self.assertStoppedAfterTwoCancels(task, claimed, ["离开", "取消", "离开", "取消"])

    def test_continue_and_cancel_stop_on_the_second_cancel(self):
        task = SettlementTask(WAYPOINT_SETTLEMENT, counter="3/4")
        claimed = self.play(task, [(WAYPOINT_SETTLEMENT, {"counter": "3/4", "unread": ("获得",)}),
                                   (WAYPOINT_WITHOUT_CARD_DIALOG, {"counter": "3/4"})] * 3, continue_handler=utils.handle_continue)
        self.assertEqual(["handle_continue", "handle_continue_without_card"] * 2, claimed)
        self.assertStoppedAfterTwoCancels(task, claimed, ["继续", "取消", "继续", "取消"])

    def test_obtain_and_an_unreadable_claim_counter_stop_on_the_second_cancel(self):
        for settlement, opened_by in ((FINAL_SETTLEMENT, "handle_obtain_before_leave"), (WAYPOINT_SETTLEMENT, "handle_chaos_reward_settlement")):
            with self.subTest(opened_by=opened_by):
                task = SettlementTask(settlement)
                claimed = self.play(task, [(settlement, {}), (CLAIM_DIALOG, {"counter": None})] * 3)
                self.assertEqual([opened_by, "handle_claim_without_cards"] * 2, claimed)
                self.assertStoppedAfterTwoCancels(task, claimed, ["获得", loot_cards.CANCEL_POINT, "获得", loot_cards.CANCEL_POINT])

    def test_a_claim_in_between_starts_the_count_again(self):
        task = SettlementTask(FINAL_SETTLEMENT)
        claimed = self.play(task, [(FINAL_SETTLEMENT, {}), (CLAIM_DIALOG, {"counter": None}), (FINAL_SETTLEMENT, {}),
                                   (CLAIM_DIALOG, {}), (WITHOUT_CARD_DIALOG, {})])
        self.assertEqual(["handle_obtain_before_leave", "handle_claim_without_cards", "handle_obtain_before_leave",
                          "handle_chaos_reward_claim", "handle_continue_without_card"], claimed)
        self.assertEqual(["获得", loot_cards.CANCEL_POINT, "获得", "获得", "取消"], task.clicked)
        self.assertFalse(task.disabled)
        self.assertEqual(1, task.node_status[loot_cards.CANCELS])

    def test_one_cancel_alone_carries_on(self):
        for frames in ([(WITHOUT_CARD_DIALOG, {})], [(FINAL_SETTLEMENT, {}), (CLAIM_DIALOG, {"counter": None})]):
            with self.subTest(frames=len(frames)):
                task = SettlementTask(FINAL_SETTLEMENT)
                self.play(task, frames)
                self.assertFalse(task.disabled)
                self.assertEqual([], task.notified)
                self.assertEqual(1, task.node_status[loot_cards.CANCELS])

    def test_the_count_starts_again_with_each_run(self):
        # Upstream rebuilds the run state between runs and when the mode starts, keeping only its own totals.
        for reset in (utils.reset_mission_status, utils.reset_all_status):
            with self.subTest(reset=reset.__name__):
                task = SettlementTask(WITHOUT_CARD_DIALOG)
                self.play(task, [(WITHOUT_CARD_DIALOG, {})])
                reset(task)
                self.assertNotIn(loot_cards.CANCELS, task.node_status)
                self.play(task, [(WITHOUT_CARD_DIALOG, {})])
                self.assertFalse(task.disabled)
